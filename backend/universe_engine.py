from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from defaults_store import DEFAULT_PARAMS
from env_config import ensure_env_loaded

ensure_env_loaded()

logger = logging.getLogger(__name__)

POLYGON_BASE = "https://api.polygon.io"
CACHE_FILE = Path(__file__).resolve().with_name("universe_cache.json")


def _api_key() -> str:
    key = os.getenv("POLYGON_API_KEY", "")
    if not key:
        raise RuntimeError("POLYGON_API_KEY environment variable is not set")
    return key


async def _get(session: aiohttp.ClientSession, url: str, params: Optional[Dict] = None) -> Dict:
    payload = dict(params or {})
    payload["apiKey"] = _api_key()
    try:
        async with session.get(url, params=payload, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                text = await response.text()
                logger.error(f"Polygon {response.status}: {url} -> {text[:200]}")
                return {}
            return await response.json()
    except asyncio.TimeoutError:
        logger.warning(f"Timeout: {url}")
        return {}
    except Exception as exc:
        logger.warning(f"Request error {url}: {exc}")
        return {}


async def _fetch_reference_page(
    session: aiohttp.ClientSession,
    min_market_cap: float,
    cursor: Optional[str] = None,
) -> Dict:
    params = {
        "market": "stocks",
        "locale": "us",
        "active": "true",
        "market_cap.gte": int(min_market_cap),
        "limit": 1000,
    }
    if cursor:
        params["cursor"] = cursor
    return await _get(session, f"{POLYGON_BASE}/v3/reference/tickers", params)


async def _get_30d_stock_metrics(session: aiohttp.ClientSession, ticker: str) -> Dict:
    date_to = datetime.utcnow().date()
    date_from = date_to - timedelta(days=60)
    url = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{date_from.isoformat()}/{date_to.isoformat()}"
    data = await _get(session, url, {"adjusted": "true", "sort": "desc", "limit": 60})
    bars = data.get("results", []) or []
    if not bars:
        return {}

    valid = []
    for bar in bars:
        close = bar.get("c") or 0
        vwap = bar.get("vw") or close or 0
        volume = bar.get("v", 0) or 0
        if close <= 0 or volume <= 0:
            continue
        valid.append({
            "close": float(close),
            "dollar_vol": float(volume) * float(vwap),
        })

    if len(valid) < 20:
        return {}

    last_30 = valid[:30]
    avg_dollar_vol = sum(row["dollar_vol"] for row in last_30) / len(last_30)
    return {
        "price": last_30[0]["close"],
        "avg_dollar_vol_30d": avg_dollar_vol,
    }


async def build_universe(params: Optional[Dict] = None) -> Dict:
    config = {**DEFAULT_PARAMS, **(params or {})}
    progress_cb = config.get("_progress_cb")
    min_market_cap = float(config["universe_min_market_cap_b"]) * 1_000_000_000
    min_dollar_vol = float(config["universe_min_dollar_vol_m"]) * 1_000_000
    min_price = float(config["universe_min_price"])
    universe_size = int(config["universe_size"])

    async def emit(payload: Dict) -> None:
        if progress_cb is None:
            return
        result = progress_cb(payload)
        if inspect.isawaitable(result):
            await result

    start = datetime.utcnow()
    await emit({"stage": "stage1", "percent": 0, "qualified": 0, "candidates": 0, "message": "Universe refresh starting"})

    async with aiohttp.ClientSession() as session:
        candidates = []
        cursor = None
        pages = 0

        while True:
            data = await _fetch_reference_page(session, min_market_cap, cursor)
            results = data.get("results", []) or []
            if not results:
                break

            for row in results:
                ticker = row.get("ticker")
                if not ticker:
                    continue
                if row.get("type") not in ("CS", "ETF", "ETV", None):
                    continue
                candidates.append({
                    "ticker": ticker,
                    "name": row.get("name", ticker),
                    "market_cap": row.get("market_cap", 0) or 0,
                })

            pages += 1
            next_url = data.get("next_url", "")
            cursor = parse_qs(urlparse(next_url).query).get("cursor", [None])[0] if next_url else None
            logger.info(f"Universe page {pages}: {len(results)} fetched, {len(candidates)} total")
            if not cursor or pages >= 10:
                break
            await asyncio.sleep(0.2)

        qualified = []
        batch_size = 40

        for idx in range(0, len(candidates), batch_size):
            batch = candidates[idx: idx + batch_size]
            metrics = await asyncio.gather(
                *[_get_30d_stock_metrics(session, item["ticker"]) for item in batch],
                return_exceptions=True,
            )

            for item, metric in zip(batch, metrics):
                if isinstance(metric, Exception) or not metric:
                    continue
                if metric["price"] < min_price or metric["avg_dollar_vol_30d"] < min_dollar_vol:
                    continue
                qualified.append({
                    **item,
                    "price": round(metric["price"], 2),
                    "avg_dollar_vol_30d": round(metric["avg_dollar_vol_30d"], 2),
                })

            processed = min(idx + batch_size, len(candidates))
            percent = min(100, round((processed / max(len(candidates), 1)) * 100))
            message = f"Stage 1 {percent}%: {len(qualified)} liquid tickers qualified"
            logger.info(message)
            await emit({
                "stage": "stage1",
                "percent": percent,
                "qualified": len(qualified),
                "candidates": len(candidates),
                "message": message,
            })
            await asyncio.sleep(0.3)

    qualified.sort(key=lambda item: (item["avg_dollar_vol_30d"], item["market_cap"]), reverse=True)
    top = qualified[:universe_size]
    elapsed = (datetime.utcnow() - start).total_seconds()
    result = {
        "tickers": [item["ticker"] for item in top],
        "count": len(top),
        "built_at": datetime.utcnow().isoformat() + "Z",
        "elapsed_seconds": round(elapsed, 1),
        "params": {
            "universe_min_market_cap_b": config["universe_min_market_cap_b"],
            "universe_min_dollar_vol_m": config["universe_min_dollar_vol_m"],
            "universe_min_price": config["universe_min_price"],
            "universe_size": config["universe_size"],
        },
        "stage1_candidates": len(candidates),
    }
    CACHE_FILE.write_text(json.dumps(result, indent=2))

    await emit({
        "stage": "complete",
        "percent": 100,
        "qualified": len(top),
        "candidates": len(candidates),
        "message": f"Universe refresh complete - {len(top)} tickers",
    })
    return result


def load_cached_universe() -> List[str]:
    try:
        data = json.loads(CACHE_FILE.read_text())
    except Exception:
        return []
    return data.get("tickers", [])


def get_cache_metadata() -> Dict:
    try:
        data = json.loads(CACHE_FILE.read_text())
    except Exception:
        return {"built_at": None, "count": 0}
    return {
        "built_at": data.get("built_at"),
        "count": data.get("count", 0),
        "elapsed_s": data.get("elapsed_seconds"),
        "params": data.get("params", {}),
        "stage1_candidates": data.get("stage1_candidates", 0),
    }
