from __future__ import annotations

import asyncio
import inspect
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import aiohttp

from defaults_store import DEFAULT_PARAMS
from polygon_client import get_daily_bars, get_ticker_name
from technical import calculate_rsi, ema, find_pivot_highs, find_pivot_lows
from universe import get_universe


logger = logging.getLogger(__name__)

BATCH_SIZE = 10
BATCH_DELAY = 0.8


def _score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _closeness(value: Optional[float], target: float, tolerance: float) -> float:
    if value is None:
        return 0.0
    return _score(100 - abs(value - target) / max(tolerance, 1e-6) * 100)


def _band(value: Optional[float], low: float, high: float, pad: float) -> float:
    if value is None:
        return 0.0
    if low <= value <= high:
        return 100.0
    if value < low:
        return _score(100 - ((low - value) / max(pad, 1e-6)) * 100)
    return _score(100 - ((value - high) / max(pad, 1e-6)) * 100)


def _merged_pivots(bars: List[Dict], window: int) -> List[Dict]:
    pivots = [{"kind": "high", **pivot} for pivot in find_pivot_highs(bars, window)]
    pivots += [{"kind": "low", **pivot} for pivot in find_pivot_lows(bars, window)]
    pivots.sort(key=lambda item: item["index"])

    filtered = []
    for pivot in pivots:
        if not filtered:
            filtered.append(pivot)
            continue
        last = filtered[-1]
        if last["kind"] != pivot["kind"]:
            filtered.append(pivot)
            continue
        if pivot["kind"] == "high" and pivot["price"] > last["price"]:
            filtered[-1] = pivot
        elif pivot["kind"] == "low" and pivot["price"] < last["price"]:
            filtered[-1] = pivot
    return filtered


def _avg_volume_ratio(bars: List[Dict], recent: int = 5, base: int = 20) -> Optional[float]:
    if len(bars) < base + recent:
        return None
    recent_avg = sum(bar.get("v", 0) or 0 for bar in bars[-recent:]) / recent
    base_avg = sum(bar.get("v", 0) or 0 for bar in bars[-(base + recent):-recent]) / base
    if base_avg <= 0:
        return None
    return round(recent_avg / base_avg, 2)


def _bar_date(bar: Dict) -> Optional[str]:
    ts = bar.get("t")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc).date().isoformat()
    except Exception:
        return None


def _add_trading_days(days: int) -> str:
    cursor = datetime.utcnow().date()
    remaining = max(0, days)
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor.isoformat()


def _project_c_timing(a_days: int, b_days: int, retrace: float, days_since_b: int) -> Dict:
    likely_total = max(5, a_days)
    if retrace >= 0.75:
        likely_total = round(a_days * 1.382)
    elif retrace <= 0.5:
        likely_total = round(max(5, a_days * 0.786))

    fast_total = round(max(5, a_days * 0.618))
    slow_total = round(max(likely_total, a_days * 1.618, (a_days + b_days) * 0.618))
    projected_total = max(likely_total, round((likely_total + slow_total) / 2))
    remaining = max(1, projected_total - days_since_b)
    lower_remaining = max(1, fast_total - days_since_b)
    upper_remaining = max(1, slow_total - days_since_b)

    return {
        "wave_a_days": a_days,
        "wave_b_days": b_days,
        "expected_c_days_total": int(projected_total),
        "expected_c_days_remaining": int(remaining),
        "expected_completion_date": _add_trading_days(int(remaining)),
        "expected_c_days_range": {
            "min": int(lower_remaining),
            "base": int(remaining),
            "max": int(upper_remaining),
        },
        "expected_completion_window": {
            "earliest": _add_trading_days(int(lower_remaining)),
            "base": _add_trading_days(int(remaining)),
            "latest": _add_trading_days(int(upper_remaining)),
        },
    }


def _bullish_candidate(bars: List[Dict], ticker: str, name: str, params: Dict) -> Optional[Dict]:
    pivots = _merged_pivots(bars, int(params["pivot_window"]))
    if len(pivots) < 3:
        return None

    current = float(bars[-1]["c"])
    current_idx = len(bars) - 1
    daily_rsi = calculate_rsi(bars, 14)
    ema10 = ema(bars, 10)
    ema20 = ema(bars, 20)
    ema50 = ema(bars, 50)
    volume_ratio = _avg_volume_ratio(bars)
    best = None

    for i in range(max(0, len(pivots) - 12), len(pivots) - 2):
        start_low, wave_a_high, wave_b_low = pivots[i:i + 3]
        if (start_low["kind"], wave_a_high["kind"], wave_b_low["kind"]) != ("low", "high", "low"):
            continue

        a_len = wave_a_high["price"] - start_low["price"]
        if a_len <= 0:
            continue
        a_pct = a_len / max(start_low["price"], 1e-6) * 100
        if a_pct < float(params["min_wave_a_pct"]):
            continue

        b_retrace = (wave_a_high["price"] - wave_b_low["price"]) / a_len
        if b_retrace < float(params["min_b_retrace"]) or b_retrace > float(params["max_b_retrace"]):
            continue
        if wave_b_low["price"] <= start_low["price"]:
            continue

        days_since_b = current_idx - wave_b_low["index"]
        if days_since_b <= 0 or days_since_b > int(params["max_days_since_b"]):
            continue

        c_progress = (current - wave_b_low["price"]) / a_len
        if c_progress < float(params["min_c_progress"]) or c_progress > float(params["max_c_progress"]):
            continue

        if bool(params["require_ema_confirmation"]) and not (ema10 and ema20 and current > ema10 > ema20):
            continue

        if daily_rsi is None:
            continue

        target_equal = wave_b_low["price"] + a_len
        target_stretch = wave_b_low["price"] + a_len * 1.618
        risk = current - wave_b_low["price"]
        reward = target_equal - current
        if risk <= 0 or reward <= 0:
            continue
        reward_risk = reward / risk
        if reward_risk < 1.1:
            continue

        timing = _project_c_timing(
            wave_a_high["index"] - start_low["index"],
            wave_b_low["index"] - wave_a_high["index"],
            b_retrace,
            days_since_b,
        )

        score = round(
            _closeness(b_retrace, float(params["ideal_b_retrace"]), 0.25) * 0.28
            + _closeness(c_progress, 0.18, 0.20) * 0.24
            + _band(daily_rsi, float(params["bullish_daily_rsi_min"]), float(params["bullish_daily_rsi_max"]), 10.0) * 0.16
            + _band(volume_ratio, float(params["min_volume_ratio"]), 1.8, 0.7) * 0.12
            + _band(reward_risk, 1.5, 3.5, 2.0) * 0.20,
            1,
        )

        candidate = {
            "ticker": ticker,
            "name": name,
            "direction": "bullish",
            "price": round(current, 2),
            "daily_rsi": daily_rsi,
            "ema10": round(ema10, 2) if ema10 else None,
            "ema20": round(ema20, 2) if ema20 else None,
            "ema50": round(ema50, 2) if ema50 else None,
            "volume_ratio_5d_vs_20d": volume_ratio,
            "wave_a_pct": round(a_pct, 2),
            "wave_b_retrace": round(b_retrace * 100, 1),
            "wave_c_progress": round(c_progress * 100, 1),
            "target_price": round(target_equal, 2),
            "stretch_target_price": round(target_stretch, 2),
            "invalidation_price": round(wave_b_low["price"], 2),
            "reward_risk": round(reward_risk, 2),
            "wave_a_start": {"price": round(start_low["price"], 2), "index": start_low["index"], "date": _bar_date(bars[start_low["index"]])},
            "wave_a_end": {"price": round(wave_a_high["price"], 2), "index": wave_a_high["index"], "date": _bar_date(bars[wave_a_high["index"]])},
            "wave_b_end": {"price": round(wave_b_low["price"], 2), "index": wave_b_low["index"], "date": _bar_date(bars[wave_b_low["index"]])},
            **timing,
            "score": score,
        }

        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best


def _bearish_candidate(bars: List[Dict], ticker: str, name: str, params: Dict) -> Optional[Dict]:
    pivots = _merged_pivots(bars, int(params["pivot_window"]))
    if len(pivots) < 3:
        return None

    current = float(bars[-1]["c"])
    current_idx = len(bars) - 1
    daily_rsi = calculate_rsi(bars, 14)
    ema10 = ema(bars, 10)
    ema20 = ema(bars, 20)
    ema50 = ema(bars, 50)
    volume_ratio = _avg_volume_ratio(bars)
    best = None

    for i in range(max(0, len(pivots) - 12), len(pivots) - 2):
        start_high, wave_a_low, wave_b_high = pivots[i:i + 3]
        if (start_high["kind"], wave_a_low["kind"], wave_b_high["kind"]) != ("high", "low", "high"):
            continue

        a_len = start_high["price"] - wave_a_low["price"]
        if a_len <= 0:
            continue
        a_pct = a_len / max(start_high["price"], 1e-6) * 100
        if a_pct < float(params["min_wave_a_pct"]):
            continue

        b_retrace = (wave_b_high["price"] - wave_a_low["price"]) / a_len
        if b_retrace < float(params["min_b_retrace"]) or b_retrace > float(params["max_b_retrace"]):
            continue
        if wave_b_high["price"] >= start_high["price"]:
            continue

        days_since_b = current_idx - wave_b_high["index"]
        if days_since_b <= 0 or days_since_b > int(params["max_days_since_b"]):
            continue

        c_progress = (wave_b_high["price"] - current) / a_len
        if c_progress < float(params["min_c_progress"]) or c_progress > float(params["max_c_progress"]):
            continue

        if bool(params["require_ema_confirmation"]) and not (ema10 and ema20 and current < ema10 < ema20):
            continue

        if daily_rsi is None:
            continue

        target_equal = wave_b_high["price"] - a_len
        target_stretch = wave_b_high["price"] - a_len * 1.618
        risk = wave_b_high["price"] - current
        reward = current - target_equal
        if risk <= 0 or reward <= 0:
            continue
        reward_risk = reward / risk
        if reward_risk < 1.1:
            continue

        timing = _project_c_timing(
            wave_a_low["index"] - start_high["index"],
            wave_b_high["index"] - wave_a_low["index"],
            b_retrace,
            days_since_b,
        )

        score = round(
            _closeness(b_retrace, float(params["ideal_b_retrace"]), 0.25) * 0.28
            + _closeness(c_progress, 0.18, 0.20) * 0.24
            + _band(daily_rsi, float(params["bearish_daily_rsi_min"]), float(params["bearish_daily_rsi_max"]), 10.0) * 0.16
            + _band(volume_ratio, float(params["min_volume_ratio"]), 1.8, 0.7) * 0.12
            + _band(reward_risk, 1.5, 3.5, 2.0) * 0.20,
            1,
        )

        candidate = {
            "ticker": ticker,
            "name": name,
            "direction": "bearish",
            "price": round(current, 2),
            "daily_rsi": daily_rsi,
            "ema10": round(ema10, 2) if ema10 else None,
            "ema20": round(ema20, 2) if ema20 else None,
            "ema50": round(ema50, 2) if ema50 else None,
            "volume_ratio_5d_vs_20d": volume_ratio,
            "wave_a_pct": round(a_pct, 2),
            "wave_b_retrace": round(b_retrace * 100, 1),
            "wave_c_progress": round(c_progress * 100, 1),
            "target_price": round(target_equal, 2),
            "stretch_target_price": round(target_stretch, 2),
            "invalidation_price": round(wave_b_high["price"], 2),
            "reward_risk": round(reward_risk, 2),
            "wave_a_start": {"price": round(start_high["price"], 2), "index": start_high["index"], "date": _bar_date(bars[start_high["index"]])},
            "wave_a_end": {"price": round(wave_a_low["price"], 2), "index": wave_a_low["index"], "date": _bar_date(bars[wave_a_low["index"]])},
            "wave_b_end": {"price": round(wave_b_high["price"], 2), "index": wave_b_high["index"], "date": _bar_date(bars[wave_b_high["index"]])},
            **timing,
            "score": score,
        }

        if best is None or candidate["score"] > best["score"]:
            best = candidate

    return best


async def _process_ticker(session: aiohttp.ClientSession, ticker: str, params: Dict) -> Dict:
    bars, name = await asyncio.gather(
        get_daily_bars(session, ticker, days=int(params["lookback_days"])),
        get_ticker_name(session, ticker),
    )
    if not bars or len(bars) < 120:
        return {"bullish": None, "bearish": None}
    return {
        "bullish": _bullish_candidate(bars, ticker, name, params),
        "bearish": _bearish_candidate(bars, ticker, name, params),
    }


async def run_elliott_scan(
    tickers: Optional[List[str]] = None,
    params: Optional[Dict] = None,
    progress_cb=None,
) -> Dict:
    if tickers is None:
        tickers = get_universe()

    if not os.getenv("POLYGON_API_KEY"):
        raise RuntimeError("POLYGON_API_KEY is not set")

    config = {**DEFAULT_PARAMS, **(params or {})}

    async def emit_progress(payload: Dict) -> None:
        if progress_cb is None:
            return
        result = progress_cb(payload)
        if inspect.isawaitable(result):
            await result

    bullish = []
    bearish = []

    await emit_progress({
        "phase": "elliott_scan",
        "percent": 0,
        "processed": 0,
        "total": len(tickers),
        "message": f"Starting Elliott scan on {len(tickers)} tickers",
    })

    async with aiohttp.ClientSession() as session:
        for idx in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[idx: idx + BATCH_SIZE]
            batch_results = await asyncio.gather(
                *[_process_ticker(session, ticker, config) for ticker in batch],
                return_exceptions=True,
            )

            for result in batch_results:
                if isinstance(result, Exception):
                    logger.warning(f"Elliott batch exception: {result}")
                    continue
                if result.get("bullish"):
                    bullish.append(result["bullish"])
                if result.get("bearish"):
                    bearish.append(result["bearish"])

            processed = min(idx + BATCH_SIZE, len(tickers))
            percent = min(100, round((processed / max(len(tickers), 1)) * 100))
            await emit_progress({
                "phase": "elliott_scan",
                "percent": percent,
                "processed": processed,
                "total": len(tickers),
                "message": f"Progress {percent}% - {len(bullish)} bullish and {len(bearish)} bearish candidates",
            })
            if processed < len(tickers):
                await asyncio.sleep(BATCH_DELAY)

    bullish.sort(key=lambda item: item["score"], reverse=True)
    bearish.sort(key=lambda item: item["score"], reverse=True)
    bullish_total = len(bullish)
    bearish_total = len(bearish)
    top_n = int(config["top_n_per_side"])
    bullish = bullish[:top_n]
    bearish = bearish[:top_n]

    for index, item in enumerate(bullish, start=1):
        item["rank"] = index
    for index, item in enumerate(bearish, start=1):
        item["rank"] = index

    return {
        "bullish_candidates": bullish,
        "bearish_candidates": bearish,
        "scan_time": datetime.utcnow().isoformat() + "Z",
        "scanned": len(tickers),
        "params_used": {key: config[key] for key in DEFAULT_PARAMS},
        "diagnostics": {
            "bullish_found": len(bullish),
            "bearish_found": len(bearish),
            "bullish_total_matches": bullish_total,
            "bearish_total_matches": bearish_total,
        },
        "research_notes": {
            "pattern_basis": "Scanner looks for a three-leg corrective structure where Wave B retraces part of Wave A and price has only started progressing into Wave C.",
            "price_target_basis": "Primary target assumes Wave C is approximately equal to Wave A. Stretch target uses 1.618 x Wave A.",
            "time_target_basis": "Base timing assumes Wave C duration is broadly similar to Wave A, with a Fibonacci-style completion window built from 0.618x to 1.618x of Wave A duration and adjusted for deeper Wave B retracements.",
        },
    }
