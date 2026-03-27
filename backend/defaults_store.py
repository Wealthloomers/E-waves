from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


DEFAULT_PARAMS: Dict[str, float | int | bool] = {
    "top_n_per_side": 10,
    "universe_min_market_cap_b": 3.0,
    "universe_min_dollar_vol_m": 50.0,
    "universe_min_price": 10.0,
    "universe_size": 1000,
    "lookback_days": 320,
    "pivot_window": 5,
    "min_wave_a_pct": 12.0,
    "min_b_retrace": 0.382,
    "max_b_retrace": 0.886,
    "ideal_b_retrace": 0.618,
    "max_days_since_b": 30,
    "min_c_progress": 0.03,
    "max_c_progress": 0.45,
    "bullish_daily_rsi_min": 45.0,
    "bullish_daily_rsi_max": 67.0,
    "bearish_daily_rsi_min": 33.0,
    "bearish_daily_rsi_max": 55.0,
    "min_volume_ratio": 0.9,
    "require_ema_confirmation": True,
}


SAVE_PATH = Path(__file__).resolve().with_name("saved_defaults.json")


def _normalize(params: Dict) -> Dict:
    merged = {**DEFAULT_PARAMS, **(params or {})}
    out: Dict = {}
    for key, default_value in DEFAULT_PARAMS.items():
        value = merged.get(key, default_value)
        if isinstance(default_value, bool):
            out[key] = bool(value)
        elif isinstance(default_value, int):
            out[key] = int(float(value))
        else:
            out[key] = float(value)
    return out


def load_defaults() -> Dict:
    if not SAVE_PATH.exists():
        return dict(DEFAULT_PARAMS)
    try:
        data = json.loads(SAVE_PATH.read_text())
    except Exception:
        return dict(DEFAULT_PARAMS)
    return _normalize(data)


def save_defaults(params: Dict) -> Dict:
    normalized = _normalize(params)
    SAVE_PATH.write_text(json.dumps(normalized, indent=2))
    return normalized


def universe_params(params: Dict) -> Dict:
    keys = [
        "universe_min_market_cap_b",
        "universe_min_dollar_vol_m",
        "universe_min_price",
        "universe_size",
    ]
    return {key: params[key] for key in keys if key in params}
