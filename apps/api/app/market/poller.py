"""Background market poller service for automated Groww live quote updates.

Polls Groww live quotes, commodities, and global indices at a configurable interval
(default: 60 seconds). Updates `latest.json` and evaluates open watchlist trades.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.integrations.http import HttpxCaller
from app.market.groww_market_snapshot import (
    build_groww_market_observations,
    parse_global_indices,
    parse_mcx_commodities,
    parse_sectoral_indices,
)
from app.market.live_quotes import load_read, run_live_read, save_read, stored_observations
from app.market.schemas import IST
from app.settings import Settings, get_settings
from app.watchlist.service import evaluate_open

logger = logging.getLogger("app.market.poller")

# In-memory polling configuration & status
_config: dict[str, Any] = {
    "enabled": True,
    "interval_seconds": 15,
    "last_polled_at": None,
    "status": "RUNNING",
    "last_error": None,
    "poll_count": 0,
}

_task: asyncio.Task | None = None


def get_poll_config() -> dict[str, Any]:
    return dict(_config)


def update_poll_config(enabled: bool | None = None, interval_seconds: int | None = None) -> dict[str, Any]:
    global _config
    if enabled is not None:
        _config["enabled"] = bool(enabled)
    if interval_seconds is not None:
        _config["interval_seconds"] = max(10, min(3600, int(interval_seconds)))
    return dict(_config)


def perform_live_sync(session: Session, settings: Settings, caller: Any = None) -> dict:
    """Execute synchronous live quote read, MCX commodities fetch, and watchlist evaluation."""
    caller = caller or HttpxCaller()
    now_ist = datetime.now(IST)
    result = run_live_read(session, settings, caller=caller, retrieved_at=now_ist)

    # Fetch fresh live option chain for NIFTY from Groww official API
    try:
        from app.market.groww_options import fetch_groww_option_chain
        fetch_groww_option_chain(session, settings, caller=caller, underlying="NIFTY")
    except Exception as exc:
        logger.warning("Option chain refresh failed during live sync: %s", exc)

    # Merge Groww MCX Commodities, Global Indices, and Domestic Sectorals
    try:
        commodities = parse_mcx_commodities()
        global_indices = parse_global_indices()
        sectoral_indices = parse_sectoral_indices()
        result["commodities"] = commodities
        result["global_indices"] = global_indices
        result["sectoral_indices"] = sectoral_indices

        quotes_list = [q for q in (result.get("quotes") or []) if q.get("instrument") in ("NIFTY", "SENSEX")]
        result["quotes"] = quotes_list

        stored_rec = load_read() or {}
        stored_rec.update(result)
        stored_rec["commodities"] = commodities
        stored_rec["global_indices"] = global_indices
        stored_rec["sectoral_indices"] = sectoral_indices
        stored_rec["quotes"] = quotes_list

        base_obs = result.get("observations") or stored_rec.get("observations") or []
        extra_obs = build_groww_market_observations(commodities, global_indices, sectoral_indices)
        seen_inst = set()
        merged_obs = []
        for o in base_obs + extra_obs:
            inst = o.get("instrument")
            if inst and inst not in seen_inst:
                seen_inst.add(inst)
                merged_obs.append(o)
        stored_rec["observations"] = merged_obs

        from app.market.session_intelligence import build_cross_market_snapshot, generate_post_close_analysis
        cross_snapshot = build_cross_market_snapshot(quotes_list, commodities, global_indices, sectoral_indices, as_of=now_ist)
        result["cross_market_snapshot"] = cross_snapshot
        result["is_equity_open"] = cross_snapshot["is_equity_open"]
        result["is_commodity_open"] = cross_snapshot["is_commodity_open"]
        result["post_close_mode"] = cross_snapshot["post_close_mode"]
        if cross_snapshot["post_close_mode"]:
            result["post_close_analysis"] = generate_post_close_analysis(cross_snapshot, as_of=now_ist)

        stored_rec["cross_market_snapshot"] = cross_snapshot
        stored_rec["is_equity_open"] = cross_snapshot["is_equity_open"]
        stored_rec["is_commodity_open"] = cross_snapshot["is_commodity_open"]
        stored_rec["post_close_mode"] = cross_snapshot["post_close_mode"]
        if cross_snapshot["post_close_mode"]:
            stored_rec["post_close_analysis"] = result.get("post_close_analysis")

        save_read(stored_rec)
    except Exception as exc:
        logger.warning("Snapshot merge failed during live sync: %s", exc)

    # Evaluate open watchlist items against the fresh quotes
    try:
        with session.begin_nested():
            result["watchlist"] = evaluate_open(session, stored_observations())
    except Exception as exc:
        logger.warning("Watchlist evaluation failed during live sync: %s", exc)

    return result


import os

async def _poll_worker(settings: Settings) -> None:
    global _config
    logger.info("Market poller worker started (default interval: %ds)", _config["interval_seconds"])
    session_factory = get_session_factory()

    while True:
        try:
            if os.environ.get("PYTEST_CURRENT_TEST") and not _config.get("_force_test_poll"):
                try:
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
                continue

            if _config["enabled"]:
                now = datetime.now(timezone.utc)
                last = _config.get("last_polled_at")
                should_run = True
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last)
                        elapsed = (now - last_dt).total_seconds()
                        if elapsed < _config["interval_seconds"]:
                            should_run = False
                    except Exception:
                        pass

                if should_run:
                    session = session_factory()
                    try:
                        await asyncio.to_thread(perform_live_sync, session, settings)
                        _config["last_polled_at"] = now.isoformat()
                        _config["poll_count"] += 1
                        _config["status"] = "ACTIVE"
                        _config["last_error"] = None
                        session.commit()
                    except Exception as exc:
                        _config["last_error"] = str(exc)
                        _config["status"] = "ERROR"
                        logger.warning("Market poll iteration failed: %s", exc)
                        session.rollback()
                    finally:
                        session.close()
        except asyncio.CancelledError:
            logger.info("Market poller worker cancelled.")
            break
        except Exception as exc:
            logger.exception("Unexpected error in market poller loop: %s", exc)

        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break


def start_market_poller(settings: Settings) -> asyncio.Task:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_poll_worker(settings))
    return _task


def stop_market_poller() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
