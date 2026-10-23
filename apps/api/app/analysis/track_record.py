"""Measured track records that replace stated agent confidence.

The agent backtest (app.research.agent_backtest, `python -m app.cli agent-backtest`) replays
an agent's real rule on years of NIFTY data. An agent's confidence is then the hit rate its
call actually had at that time of day, not a number chosen by a formula or an LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from app.settings import REPO_ROOT

BACKTEST_PATH = REPO_ROOT / "var" / "datasets" / "agent_backtest.json"
IST = timezone(timedelta(hours=5, minutes=30))
_CHECKPOINT_TIMES = {"10:15": time(10, 15), "12:00": time(12, 0), "14:00": time(14, 0)}


def _load(path: Path | None) -> dict | None:
    target = path or BACKTEST_PATH
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def technical_track_record(when: datetime | None = None, *, path: Path | None = None) -> dict | None:
    """Measured record of the Technical Analyst call made at `when` (IST), or None if not measured.

    In session the call is about the rest of the day (nearest checkpoint at or before `when`;
    before 10:15 the 10:15 record is used). Outside the session it is about the next session
    (the 14:00 record, the latest measured call).
    """
    doc = _load(path)
    checkpoints = (((doc or {}).get("agents") or {}).get("technical_analyst") or {}).get("checkpoints") or {}
    if not checkpoints:
        return None
    local = (when or datetime.now(IST)).astimezone(IST)
    in_session = local.weekday() < 5 and time(9, 15) <= local.time() < time(15, 30)
    if in_session:
        horizon = "rest_of_day"
        earlier = [cp for cp, t in _CHECKPOINT_TIMES.items() if t <= local.time() and cp in checkpoints]
        checkpoint = earlier[-1] if earlier else "10:15"
    else:
        horizon, checkpoint = "next_session", "14:00"
    record = ((checkpoints.get(checkpoint) or {}).get(horizon) or {}).get("all") or {}
    if not record.get("n_calls"):
        return None
    holdout = ((checkpoints.get(checkpoint) or {}).get(horizon) or {}).get("holdout") or {}
    return {
        "checkpoint": checkpoint,
        "horizon": horizon,
        "hit_rate": record["hit_rate"],
        "hit_rate_ci95": record.get("hit_rate_ci95"),
        "n_calls": record["n_calls"],
        "p_value_vs_50pct": record.get("p_value_vs_50pct"),
        "holdout_hit_rate": holdout.get("hit_rate"),
        "mean_net_return_pct_per_call": record.get("mean_net_return_pct_per_call"),
        "generated_at": doc.get("generated_at"),
        "sessions": doc.get("sessions"),
    }
