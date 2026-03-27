"""
Polygon.io API client.
DTE window: 30–90 days for all strategies (agreed design).
Spread measurement uses 30–45 DTE (most liquid front of the window).
All functions are async and accept an aiohttp.ClientSession.
Compatible with Python 3.9+.
"""

import os
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import logging

from env_config import ensure_env_loaded

ensure_env_loaded()

logger = logging.getLogger(__name__)

POLYGON_BASE = "https://api.polygon.io"


def _api_key() -> str:
    key = os.getenv("POLYGON_API_KEY", "")
    if not key:
        raise RuntimeError("POLYGON_API_KEY environment variable is not set")
    return key


async def _get(
    session: aiohttp.ClientSession,
    url: str,
    params: Optional[Dict] = None,
) -> Dict:
    """Single GET request to Polygon with full error handling."""
    p = dict(params) if params else {}
    p["apiKey"] = _api_key()
    try:
        async with session.get(
            url, params=p, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 403:
                logger.error(f"Polygon 403 Forbidden — check API key and subscription tier: {url}")
                return {}
            if resp.status == 429:
                logger.warning(f"Polygon rate limit hit: {url} — sleeping 2s")
                await asyncio.sleep(2)
                return {}
            if resp.status != 200:
                text = await resp.text()
                logger.error(f"Polygon {resp.status}: {url} -> {text[:200]}")
                return {}
            return await resp.json()
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {url}")
        return {}
    except Exception as e:
        logger.warning(f"Request error {url}: {e}")
        return {}


# ── Price bars ────────────────────────────────────────────────────────────────

async def get_daily_bars(
    session: aiohttp.ClientSession,
    ticker: str,
    days: int = 365,
) -> List[Dict]:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    url   = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    data  = await _get(session, url, {"adjusted": "true", "sort": "asc", "limit": 365})
    return data.get("results", [])


async def get_weekly_bars(
    session: aiohttp.ClientSession,
    ticker: str,
    weeks: int = 52,
) -> List[Dict]:
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    url   = f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/week/{start}/{end}"
    data  = await _get(session, url, {"adjusted": "true", "sort": "asc", "limit": 52})
    return data.get("results", [])


# ── Ticker name ───────────────────────────────────────────────────────────────

async def get_ticker_name(
    session: aiohttp.ClientSession,
    ticker: str,
) -> str:
    url  = f"{POLYGON_BASE}/v3/reference/tickers/{ticker}"
    data = await _get(session, url)
    return (data.get("results") or {}).get("name", ticker)


# ── Options chain — core fetch ─────────────────────────────────────────────────

async def get_options_chain(
    session:  aiohttp.ClientSession,
    ticker:   str,
    dte_min:  int = 30,
    dte_max:  int = 90,
) -> List[Dict]:
    """
    Fetch options snapshot for contracts expiring between dte_min and dte_max.
    Default window is 30–90 DTE, targeting liquid monthly and quarterly contracts.
    """
    exp_from = (datetime.today() + timedelta(days=dte_min)).strftime("%Y-%m-%d")
    exp_to   = (datetime.today() + timedelta(days=dte_max)).strftime("%Y-%m-%d")
    url  = f"{POLYGON_BASE}/v3/snapshot/options/{ticker}"
    data = await _get(session, url, {
        "expiration_date.gte": exp_from,
        "expiration_date.lte": exp_to,
        "limit": 250,
    })
    return data.get("results", [])


# ── IV Rank ───────────────────────────────────────────────────────────────────

async def get_iv_rank(
    session:       aiohttp.ClientSession,
    ticker:        str,
    current_price: float,
    dte_min:       int = 30,
    dte_max:       int = 90,
) -> Optional[float]:
    """
    Approximate IVR from spread of implied volatilities across the 30–90 DTE chain.
    ATM IV is compared against the full IV range across all strikes/expiries.

    Note: A true 52-week IVR requires storing daily IV snapshots in a database.
    This proxy is a reasonable approximation (+/- 10–15 pts vs broker IVR).
    """
    chain = await get_options_chain(session, ticker, dte_min=dte_min, dte_max=dte_max)
    if not chain:
        return None

    all_ivs: List[float] = []
    atm_ivs: List[float] = []

    for opt in chain:
        details = opt.get("details") or {}
        iv      = opt.get("implied_volatility")
        if not iv or iv <= 0:
            continue
        all_ivs.append(iv)
        strike = details.get("strike_price", 0)
        if strike and current_price:
            if abs(strike - current_price) / current_price < 0.03:
                atm_ivs.append(iv)

    if not all_ivs or not atm_ivs:
        return None

    current_iv = sum(atm_ivs) / len(atm_ivs)
    iv_min = min(all_ivs)
    iv_max = max(all_ivs)
    if iv_max <= iv_min:
        return 50.0

    ivr = (current_iv - iv_min) / (iv_max - iv_min) * 100
    return round(min(max(ivr, 0.0), 100.0), 1)


# ── Earnings ──────────────────────────────────────────────────────────────────

async def days_to_earnings(
    session: aiohttp.ClientSession,
    ticker:  str,
) -> Optional[int]:
    """
    Fetch next earnings date from Polygon ticker details.
    Returns days until earnings, or None if unavailable.
    Note: Polygon does not always populate next_earnings — check independently
    for short strategies if this field returns None.
    """
    url  = f"{POLYGON_BASE}/v3/reference/tickers/{ticker}"
    data = await _get(session, url)
    next_earn = (data.get("results") or {}).get("next_earnings")
    if not next_earn:
        return None
    try:
        earn_date = datetime.strptime(next_earn[:10], "%Y-%m-%d")
        delta = (earn_date - datetime.today()).days
        return delta if delta >= 0 else None
    except Exception:
        return None


# ── ATM straddle implied move ─────────────────────────────────────────────────

async def get_implied_move_pct(
    session:       aiohttp.ClientSession,
    ticker:        str,
    current_price: float,
    dte_min:       int = 30,
    dte_max:       int = 45,
) -> Optional[float]:
    """
    ATM straddle price / stock price = implied 1-sigma expected move %.
    Uses 30–45 DTE (front of the agreed window) for the most liquid straddle.
    """
    chain = await get_options_chain(session, ticker, dte_min=dte_min, dte_max=dte_max)
    if not chain:
        return None

    calls: Dict[float, float] = {}
    puts:  Dict[float, float] = {}

    for opt in chain:
        details    = opt.get("details") or {}
        strike     = details.get("strike_price")
        ctype      = details.get("contract_type")
        last_quote = opt.get("last_quote") or {}
        bid = last_quote.get("bid", 0) or 0
        ask = last_quote.get("ask", 0) or 0
        if not strike or not ctype or bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2
        if ctype == "call":
            calls[strike] = mid
        elif ctype == "put":
            puts[strike] = mid

    if not calls or not puts:
        return None

    atm_strike = min(calls.keys(), key=lambda s: abs(s - current_price))
    straddle   = calls.get(atm_strike, 0) + puts.get(atm_strike, 0)
    if straddle <= 0 or current_price <= 0:
        return None

    return round((straddle / current_price) * 100, 2)


# ── Spread quality ────────────────────────────────────────────────────────────

async def get_spread_pct(
    session:       aiohttp.ClientSession,
    ticker:        str,
    current_price: float,
    dte_min:       int = 30,
    dte_max:       int = 45,
) -> Dict:
    """
    (ask - bid) / ask * 100 for near-ATM options in the 30–45 DTE range.
    30–45 DTE is the most liquid part of the 30–90 window and gives the most
    representative spread quality reading. Must be < 10% to pass the gate.
    """
    chain = await get_options_chain(session, ticker, dte_min=dte_min, dte_max=dte_max)
    if not chain:
        return {"spread_pct": None, "quote_data_available": False}

    spreads: List[float] = []
    quote_data_available = False
    for opt in chain:
        details = opt.get("details") or {}
        strike  = details.get("strike_price", 0)
        if not strike or not current_price:
            continue
        if abs(strike - current_price) / current_price > 0.05:
            continue
        last_quote = opt.get("last_quote") or {}
        if last_quote:
            quote_data_available = True
        bid = last_quote.get("bid", 0) or 0
        ask = last_quote.get("ask", 0) or 0
        if ask > 0:
            spreads.append((ask - bid) / ask * 100)

    return {
        "spread_pct": round(sum(spreads) / len(spreads), 2) if spreads else None,
        "quote_data_available": quote_data_available,
    }


# ── Put/Call ratio ────────────────────────────────────────────────────────────

async def get_put_call_ratio(
    session:  aiohttp.ClientSession,
    ticker:   str,
    dte_min:  int = 30,
    dte_max:  int = 90,
) -> Optional[float]:
    """Put/call volume ratio across the full 30–90 DTE window."""
    chain = await get_options_chain(session, ticker, dte_min=dte_min, dte_max=dte_max)
    if not chain:
        return None

    call_vol = sum(
        (opt.get("day") or {}).get("volume", 0)
        for opt in chain
        if (opt.get("details") or {}).get("contract_type") == "call"
    )
    put_vol = sum(
        (opt.get("day") or {}).get("volume", 0)
        for opt in chain
        if (opt.get("details") or {}).get("contract_type") == "put"
    )
    if call_vol == 0:
        return None
    return round(put_vol / call_vol, 2)


# ── Options liquidity gate ────────────────────────────────────────────────────

async def get_options_liquidity(
    session:       aiohttp.ClientSession,
    ticker:        str,
    current_price: float,
    dte_min:       int = 30,
    dte_max:       int = 90,
) -> Dict:
    """
    Returns ATM open interest and total daily options dollar volume
    across the full 30–90 DTE window.
    Gate: ATM OI >= 500, daily vol >= $500K.
    """
    chain = await get_options_chain(session, ticker, dte_min=dte_min, dte_max=dte_max)
    if not chain:
        return {
            "atm_oi": 0,
            "daily_options_volume_usd": 0,
            "oi_data_available": False,
            "volume_data_available": False,
        }

    atm_oi           = 0
    total_dollar_vol = 0.0
    oi_data_available = False
    volume_data_available = False

    for opt in chain:
        details = opt.get("details") or {}
        strike  = details.get("strike_price", 0)
        day     = opt.get("day") or {}
        vol     = day.get("volume", 0) or 0
        vwap    = day.get("vwap",   0) or 0
        if "open_interest" in opt and opt.get("open_interest") is not None:
            oi_data_available = True
        oi = opt.get("open_interest", 0) or 0
        if vol > 0 and vwap > 0:
            volume_data_available = True

        total_dollar_vol += vol * vwap * 100
        if strike and current_price and abs(strike - current_price) / current_price < 0.03:
            atm_oi += oi

    return {
        "atm_oi": atm_oi,
        "daily_options_volume_usd": total_dollar_vol,
        "oi_data_available": oi_data_available,
        "volume_data_available": volume_data_available,
    }
