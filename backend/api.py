from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Body, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from defaults_store import load_defaults, save_defaults, universe_params
from elliott_engine import run_elliott_scan
from env_config import ensure_env_loaded
from universe import get_universe
from universe_engine import build_universe, get_cache_metadata

ensure_env_loaded()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SCAN_API_KEY = os.getenv("SCAN_API_KEY", "")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

if not SCAN_API_KEY:
    logger.warning("SCAN_API_KEY not set - management endpoints are unprotected")

state = {
    "last_result": None,
    "last_scan_time": None,
    "is_scanning": False,
    "last_scan_error": None,
    "scan_task": None,
    "scan_progress": None,
    "is_refreshing": False,
    "last_refresh_time": None,
    "last_refresh_error": None,
    "refresh_task": None,
    "refresh_progress": None,
}

scheduler = AsyncIOScheduler(timezone="America/New_York")


def _check_key(x_api_key: str) -> None:
    if SCAN_API_KEY and x_api_key != SCAN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header")


def _merged_params(params: Optional[Dict]) -> Dict:
    return {**load_defaults(), **(params or {})}


async def _run_scan_task(params: Optional[Dict] = None) -> None:
    if state["is_scanning"]:
        return

    state["is_scanning"] = True
    state["last_scan_error"] = None
    state["scan_progress"] = {
        "phase": "elliott_scan",
        "percent": 0,
        "processed": 0,
        "total": 0,
        "message": "Scan queued",
    }
    try:
        def _progress(payload: Dict) -> None:
            state["scan_progress"] = payload

        result = await run_elliott_scan(
            tickers=get_universe(),
            params=_merged_params(params),
            progress_cb=_progress,
        )
        state["last_result"] = result
        state["last_scan_time"] = datetime.now(timezone.utc).isoformat()
    except asyncio.CancelledError:
        state["last_scan_error"] = "Scan cancelled by user"
        raise
    except Exception as exc:
        state["last_scan_error"] = str(exc)
        logger.error(f"Elliott scan failed: {exc}")
    finally:
        state["is_scanning"] = False
        state["scan_task"] = None
        if state["scan_progress"] is not None:
            state["scan_progress"]["active"] = False


async def _run_universe_refresh(params: Optional[Dict] = None) -> None:
    if state["is_refreshing"]:
        return

    state["is_refreshing"] = True
    state["last_refresh_error"] = None
    state["refresh_progress"] = {
        "stage": "stage1",
        "percent": 0,
        "qualified": 0,
        "candidates": 0,
        "message": "Universe refresh queued",
    }
    try:
        def _progress(payload: Dict) -> None:
            state["refresh_progress"] = payload

        payload = {**universe_params(_merged_params(params)), "_progress_cb": _progress}
        result = await build_universe(payload)
        state["last_refresh_time"] = datetime.now(timezone.utc).isoformat()
        if result.get("error"):
            state["last_refresh_error"] = result["error"]
    except Exception as exc:
        state["last_refresh_error"] = str(exc)
        logger.error(f"Universe refresh failed: {exc}")
    finally:
        state["is_refreshing"] = False
        state["refresh_task"] = None
        if state["refresh_progress"] is not None:
            state["refresh_progress"]["active"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        _run_scan_task,
        CronTrigger(hour=8, minute=35, timezone="America/New_York"),
        id="elliott_daily_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_universe_refresh,
        CronTrigger(day_of_week="sun", hour=0, minute=10, timezone="America/New_York"),
        id="elliott_universe_refresh",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Elliott Wave Radar API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok", "service": "Elliott Wave Radar API", "version": "1.0.0"}


@app.get("/status")
def status():
    cache_meta = get_cache_metadata()
    universe = get_universe()
    return {
        "is_scanning": state["is_scanning"],
        "last_scan_time": state["last_scan_time"],
        "last_scan_error": state["last_scan_error"],
        "has_data": state["last_result"] is not None,
        "is_refreshing": state["is_refreshing"],
        "last_refresh_time": state["last_refresh_time"],
        "last_refresh_error": state["last_refresh_error"],
        "scan_progress": state["scan_progress"],
        "refresh_progress": state["refresh_progress"],
        "universe_size": len(universe),
        "universe_cache": cache_meta,
    }


@app.get("/results")
def results():
    if state["last_result"] is None:
        return {
            "status": "no_data",
            "message": "No Elliott scan has run yet.",
            "last_scan_time": None,
            "is_scanning": state["is_scanning"],
        }
    return {
        "status": "ok",
        "last_scan_time": state["last_scan_time"],
        "is_scanning": state["is_scanning"],
        **state["last_result"],
    }


@app.get("/defaults")
def defaults():
    return {"status": "ok", "defaults": load_defaults()}


@app.post("/defaults")
def update_defaults(params: Dict = Body(...), x_api_key: str = Header(default="")):
    _check_key(x_api_key)
    saved = save_defaults(params)
    return {"status": "ok", "defaults": saved}


@app.get("/universe")
def universe_list():
    tickers = get_universe()
    cache_meta = get_cache_metadata()
    is_dynamic = cache_meta.get("built_at") is not None and cache_meta.get("count", 0) > 0
    return {
        "tickers": sorted(tickers),
        "count": len(tickers),
        "source": "dynamic_cache" if is_dynamic else "static_fallback",
        "cache_meta": cache_meta,
    }


@app.post("/scan")
async def trigger_scan(params: Optional[Dict] = Body(default=None), x_api_key: str = Header(default="")):
    _check_key(x_api_key)
    if state["is_scanning"]:
        return {"status": "already_running", "message": "A scan is already in progress"}
    state["scan_task"] = asyncio.create_task(_run_scan_task(params=params))
    return {"status": "started", "message": "Elliott scan started. Poll /status or /results for progress."}


@app.post("/cancel-scan")
async def cancel_scan(x_api_key: str = Header(default="")):
    _check_key(x_api_key)
    task = state.get("scan_task")
    if not state["is_scanning"] or task is None or task.done():
        return {"status": "idle", "message": "No scan is currently running."}
    task.cancel()
    return {"status": "cancelling", "message": "Scan cancellation requested."}


@app.post("/refresh-universe")
async def refresh_universe(params: Optional[Dict] = Body(default=None), x_api_key: str = Header(default="")):
    _check_key(x_api_key)
    if state["is_refreshing"]:
        return {"status": "already_running", "message": "Universe refresh already in progress."}
    state["refresh_task"] = asyncio.create_task(_run_universe_refresh(params=params))
    return {"status": "started", "message": "Universe refresh started. Poll /status for progress."}
