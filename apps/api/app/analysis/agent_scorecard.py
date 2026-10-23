"""Forward scorecard: every agent's NIFTY call, scored against what NIFTY did afterwards.

News, macro and LLM-assisted calls cannot be replayed on past days without look-ahead, so
they are recorded when they are made and scored once the outcome exists:

- rest of day: the session's close vs the NIFTY price when the call was made;
- next session: the next session's close vs that price.

Closes come from the Groww history saved by `fetch-history` (completed sessions only), so a
call is scored only after its session (or the next one) has closed. Records are append-only
JSON lines; scoring rewrites a record once, with its outcome.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scipy import stats

from app.forecasting.evaluation import wilson_interval
from app.settings import REPO_ROOT

SCORECARD_PATH = REPO_ROOT / "var" / "analysis" / "agent_calls.jsonl"
IST = timezone(timedelta(hours=5, minutes=30))
DIRECTIONAL = {"BULLISH", "BEARISH"}
MIN_SCORED_FOR_VERDICT = 30


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def record_agent_calls(report: dict, *, spot: float | None, at: datetime | None = None,
                       instrument: str = "NIFTY", path: Path | None = None) -> list[dict]:
    """Append one record per reporting agent of an analysis report. No spot -> nothing recorded."""
    if spot is None or spot <= 0:
        return []
    when = (at or datetime.now(timezone.utc)).astimezone(IST)
    outputs = report.get("agent_outputs") or {}
    consensus = report.get("consensus") or {}
    calls = []
    for role, out in outputs.items():
        if not isinstance(out, dict) or out.get("status") in ("SKIPPED", "FAILED"):
            continue
        calls.append({
            "call_id": f"{report.get('analysis_id') or when.isoformat()}:{role}",
            "analysis_id": report.get("analysis_id"),
            "agent": role,
            "instrument": instrument,
            "made_at": when.isoformat(),
            "session_day": when.date().isoformat(),
            "in_session": when.weekday() < 5 and "09:15" <= when.strftime("%H:%M") < "15:30",
            "bias": str(out.get("directional_bias") or "UNKNOWN").upper(),
            "confidence": out.get("confidence"),
            "semantic_type": out.get("semantic_type"),
            "execution_mode": out.get("execution_mode"),
            "spot": float(spot),
            "outcome": None,
        })
    if consensus.get("directional_recommendation"):
        rec = str(consensus["directional_recommendation"]).upper()
        calls.append({
            "call_id": f"{report.get('analysis_id') or when.isoformat()}:consensus",
            "analysis_id": report.get("analysis_id"), "agent": "consensus", "instrument": instrument,
            "made_at": when.isoformat(), "session_day": when.date().isoformat(),
            "in_session": when.weekday() < 5 and "09:15" <= when.strftime("%H:%M") < "15:30",
            "bias": rec, "confidence": consensus.get("consensus_score"), "semantic_type": "CONSENSUS_SCORE",
            "execution_mode": None, "spot": float(spot), "outcome": None,
        })
    if calls:
        target = path or SCORECARD_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            for c in calls:
                handle.write(json.dumps(c) + "\n")
    return calls


def _target_session(r: dict) -> str:
    """The session a call is about: today's when made in (or before) the session, else the next weekday's."""
    when = datetime.fromisoformat(r["made_at"]).astimezone(IST)
    day = when.date()
    if r.get("in_session") or (when.weekday() < 5 and when.strftime("%H:%M") < "09:15"):
        return day.isoformat()
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def counted_calls(calls: list[dict]) -> list[dict]:
    """At most one call per agent per session: the first in-session call and the first off-hours call.

    Re-running the analysis within a session repeats one market view; counting every run would let
    a busy afternoon reach the verdict threshold on what is really a single call.
    """
    seen, out = set(), []
    for c in sorted(calls, key=lambda c: c["made_at"]):
        key = (c["agent"], bool(c.get("in_session")), _target_session(c))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _fully_scored(r: dict) -> bool:
    return bool(r.get("outcome")) and r["outcome"].get("next_session_return") is not None


def score_pending(closes: dict[str, float], *, path: Path | None = None) -> dict:
    """Score each horizon as soon as its close exists.

    closes maps completed session day (YYYY-MM-DD) -> close. An in-session call gets its
    rest-of-day result at that session's close and its next-session result a session later.
    A call made outside the session is about the next session only (a pre-open call: today's).
    """
    target = path or SCORECARD_PATH
    rows = _read(target)
    days = sorted(closes)
    changed = 0
    for r in rows:
        if _fully_scored(r):
            continue
        outcome = dict(r.get("outcome") or {})
        spot = r["spot"]
        if r.get("in_session"):
            day = r["session_day"]
            if outcome.get("rest_of_day_return") is None and day in closes:
                outcome["rest_of_day_return"] = math.log(closes[day] / spot)
            later = [d for d in days if d > day]
        else:
            later = [d for d in days if d >= _target_session(r)]
        if later:
            outcome["next_session_return"] = math.log(closes[later[0]] / spot)
            outcome["next_session_day"] = later[0]
        if outcome != (r.get("outcome") or {}):
            outcome["scored_at"] = datetime.now(timezone.utc).isoformat()
            r["outcome"] = outcome
            changed += 1
    if changed:
        _write(target, rows)
    return {"records": len(rows), "newly_scored": changed,
            "pending": sum(1 for r in rows if not _fully_scored(r))}


def _stats(calls: list[dict], key: str) -> dict:
    scored = [c for c in calls if c["bias"] in DIRECTIONAL and c.get("outcome")
              and c["outcome"].get(key) is not None and c["outcome"][key] != 0]
    n = len(scored)
    if n == 0:
        return {"n": 0}
    hits = sum(1 for c in scored if (c["bias"] == "BULLISH") == (c["outcome"][key] > 0))
    return {"n": n, "hit_rate": hits / n, "ci95": wilson_interval(hits, n),
            "p_value_vs_50pct": float(stats.binomtest(hits, n, 0.5).pvalue)}


def summarize(path: Path | None = None) -> dict:
    rows = _read(path or SCORECARD_PATH)
    agents: dict[str, list[dict]] = {}
    for r in rows:
        agents.setdefault(r["agent"], []).append(r)
    table = {}
    for agent, recorded in sorted(agents.items()):
        calls = counted_calls(recorded)
        rest, nxt = _stats(calls, "rest_of_day_return"), _stats(calls, "next_session_return")
        best = max((rest, nxt), key=lambda s: s.get("n", 0))
        if best.get("n", 0) < MIN_SCORED_FOR_VERDICT:
            status = "COLLECTING"
        elif best["p_value_vs_50pct"] < 0.05 and best["hit_rate"] > 0.5:
            status = "PROVEN"
        elif best["p_value_vs_50pct"] < 0.05:
            status = "WORSE_THAN_CHANCE"
        else:
            status = "NO_EDGE_YET"
        table[agent] = {
            "recorded_calls": len(recorded),
            "calls": len(calls),  # counted: one per agent per session
            "directional_calls": sum(1 for c in calls if c["bias"] in DIRECTIONAL),
            "pending": sum(1 for c in calls if not _fully_scored(c)),
            "rest_of_day": rest, "next_session": nxt, "status": status,
            "last_call": max(c["made_at"] for c in recorded),
        }
    return {"schema": "agent-scorecard-1", "min_scored_for_verdict": MIN_SCORED_FOR_VERDICT,
            "counting": "one call per agent per session (the first in-session and the first off-hours call)",
            "first_call": min((r["made_at"] for r in rows), default=None), "agents": table}


def evidence_by_agent(path: Path | None = None) -> dict[str, dict]:
    """Per agent: scorecard status and the hit rate of its best-sampled horizon (consensus input).

    Never raises: an unreadable scorecard means every agent is treated as unmeasured.
    """
    try:
        agents = summarize(path)["agents"]
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for name, row in agents.items():
        best = max((row["rest_of_day"], row["next_session"]), key=lambda s: s.get("n", 0))
        out[name] = {"status": row["status"], "hit_rate": best.get("hit_rate"), "n": best.get("n", 0)}
    return out


def closes_from_history(rows_1d: list[list] | None) -> dict[str, float]:
    return {str(r[0])[:10]: float(r[4]) for r in rows_1d or []}


def latest_spot(observations: list[dict], instrument: str = "NIFTY") -> float | None:
    for obs in observations:
        if str(obs.get("instrument") or "").upper() == instrument and obs.get("last_price") is not None:
            try:
                return float(obs["last_price"])
            except (TypeError, ValueError):
                continue
    return None


def score_from_saved_history(path: Path | None = None) -> dict[str, Any]:
    """Score pending calls using the saved NIFTY daily history (completed sessions only)."""
    from app.market import history_loader as hl
    from app.research.multiyear_service import completed_sessions

    doc = hl.load_series("NSE-NIFTY", "1day")
    rows = completed_sessions(doc["candles"]) if doc and doc.get("candles") else []
    return score_pending(closes_from_history(rows), path=path)
