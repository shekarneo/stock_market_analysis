"""What the forecast cards actually said, saved when it was said, and scored after the close.

A backtest rebuilds forecasts from old data; this log is the stronger test: the numbers the
operator saw, recorded before the outcome existed, and never edited afterwards except to add
the outcome once.

- daily: the next-session NIFTY range forecast, one record per target session (the first
  one published; a later rebuild for the same session is not a second forecast).
- intraday: the rest-of-day forecast for each index at each 15-minute checkpoint, logged by
  the live poller within LOG_WINDOW_SECONDS of the checkpoint (so the logged price is the
  checkpoint price). A checkpoint missed while the app was down is simply absent.

Outcomes come from the saved Groww candles of completed sessions only.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.settings import REPO_ROOT

LOG_PATH = REPO_ROOT / "var" / "analysis" / "forecast_log.jsonl"
IST = timezone(timedelta(hours=5, minutes=30))
LOG_WINDOW_SECONDS = 120
RECENT = 15


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def _write(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _key(row: dict) -> tuple:
    if row["kind"] == "daily":
        return ("daily", row["instrument"], row["for_session"])
    return ("intraday", row["instrument"], row["session_day"], row["checkpoint"])


# ------------------------------------------------------------------------------ record

def record_daily(forecast: dict, *, now: datetime | None = None, path: Path | None = None) -> dict | None:
    """Log a published next-session forecast once per target session. Returns the new record."""
    target = path or LOG_PATH
    rng = forecast.get("range") or {}
    if rng.get("status") != "OK" or not forecast.get("for_session"):
        return None
    made = (now or datetime.now(timezone.utc)).astimezone(IST)
    opens = datetime.fromisoformat(f"{forecast['for_session']}T09:15:00+05:30")
    if made >= opens:  # rebuilt after its session opened: not a forecast any more
        return None
    row = {
        "kind": "daily", "instrument": forecast.get("instrument") or "NIFTY",
        "for_session": forecast["for_session"], "as_of_session": forecast.get("as_of_session"),
        "made_at": made.isoformat(),
        "last_close": forecast.get("last_close"),
        "expected_range_pct": rng["expected_range_pct"],
        "range_band68_pct": rng["range_band68_pct"], "range_band90_pct": rng["range_band90_pct"],
        "close_move_p90_pct": rng.get("close_move_p90_pct"),
        "probability_up": (forecast.get("direction_next_session") or {}).get("probability_up"),
        "direction_status": (forecast.get("direction_next_session") or {}).get("status"),
        "outcome": None,
    }
    if any(_key(r) == _key(row) for r in _read(target) if r.get("kind") == "daily"):
        return None
    _append(target, row)
    return row


_logged_keys: set[tuple] | None = None


def record_intraday(instrument: str, forecast: dict, *, now: datetime, path: Path | None = None) -> dict | None:
    """Log an OK rest-of-day forecast made within LOG_WINDOW_SECONDS of its checkpoint, once."""
    global _logged_keys
    target = path or LOG_PATH
    if forecast.get("status") != "OK":
        return None
    now = now.astimezone(IST)
    hh, mm = (int(x) for x in forecast["checkpoint"].split(":"))
    checkpoint_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if not 0 <= (now - checkpoint_at).total_seconds() <= LOG_WINDOW_SECONDS:
        return None
    row = {
        "kind": "intraday", "instrument": instrument, "session_day": now.date().isoformat(),
        "checkpoint": forecast["checkpoint"], "made_at": now.isoformat(), "price": forecast["price"],
        "expected_remaining_range_pct": forecast["expected_remaining_range_pct"],
        "remaining_range_band68_pct": forecast["remaining_range_band68_pct"],
        "remaining_range_band90_pct": forecast["remaining_range_band90_pct"],
        "high_by_close": forecast["high_by_close"], "low_by_close": forecast["low_by_close"],
        "close_band68": forecast["close_band68"], "close_band90": forecast["close_band90"],
        "model_trained_through": (forecast.get("model") or {}).get("last"),
        "outcome": None,
    }
    if path is not None or _logged_keys is None:  # a test path, or the first call in this process
        keys = {_key(r) for r in _read(target)}
        if path is None:
            _logged_keys = keys
    else:
        keys = _logged_keys
    if _key(row) in keys:
        return None
    _append(target, row)
    keys.add(_key(row))
    return row


def log_live_intraday(*, now: datetime | None = None, path: Path | None = None) -> list[dict]:
    """Called by the live poller: log each index's forecast when a checkpoint has just passed."""
    from app.research import multiyear_service as svc

    now = (now or datetime.now(IST)).astimezone(IST)
    logged = []
    for instrument in svc.INTRADAY_INSTRUMENTS:
        row = record_intraday(instrument, svc.live_intraday_forecast(instrument, now=now), now=now, path=path)
        if row:
            logged.append(row)
    return logged


# ------------------------------------------------------------------------------- score

def _bars_by_day(rows: list[list]) -> dict[str, list[list]]:
    out: dict[str, list[list]] = {}
    for r in rows:
        if "09:15" <= str(r[0])[11:16] <= "15:15":
            out.setdefault(str(r[0])[:10], []).append(r)
    return {d: sorted(b, key=lambda r: r[0]) for d, b in out.items()}


def score_pending(daily: dict[str, dict[str, list]], intraday: dict[str, dict[str, list[list]]], *,
                  path: Path | None = None, now: datetime | None = None) -> dict:
    """daily: instrument -> {day: [ts, o, h, l, c]}; intraday: instrument -> {day: 15m bars}, completed sessions only."""
    target = path or LOG_PATH
    rows = _read(target)
    changed = 0
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    for r in rows:
        if r.get("outcome") is not None:
            continue
        if r["kind"] == "daily":
            bar = (daily.get(r["instrument"]) or {}).get(r["for_session"])
            if bar is None or not r.get("last_close"):
                continue
            actual = (bar[2] / bar[3] - 1) * 100
            move = abs(bar[4] / r["last_close"] - 1) * 100
            r["outcome"] = {
                "actual_range_pct": actual, "close": bar[4], "close_move_pct": move,
                "in_band68": r["range_band68_pct"][0] <= actual <= r["range_band68_pct"][1],
                "in_band90": r["range_band90_pct"][0] <= actual <= r["range_band90_pct"][1],
                "move_within_p90": None if r.get("close_move_p90_pct") is None else move <= r["close_move_p90_pct"],
                "up": bar[4] > r["last_close"], "scored_at": stamp,
            }
        else:
            bars = (intraday.get(r["instrument"]) or {}).get(r["session_day"])
            if not bars or len(bars) != 25:  # only a complete regular session is a result
                continue
            rest = [b for b in bars if str(b[0])[11:16] >= r["checkpoint"]]
            if not rest:
                continue
            price = r["price"]
            hi, lo, close = max(b[2] for b in rest), min(b[3] for b in rest), rest[-1][4]
            actual = (max(hi, price) / min(lo, price) - 1) * 100
            r["outcome"] = {
                "actual_remaining_range_pct": actual, "high": hi, "low": lo, "close": close,
                "range_in_band68": r["remaining_range_band68_pct"][0] <= actual <= r["remaining_range_band68_pct"][1],
                "range_in_band90": r["remaining_range_band90_pct"][0] <= actual <= r["remaining_range_band90_pct"][1],
                "high_within_p90": hi <= r["high_by_close"]["p90"],
                "low_within_p90": lo >= r["low_by_close"]["p90"],
                "close_in_band68": r["close_band68"][0] <= close <= r["close_band68"][1],
                "close_in_band90": r["close_band90"][0] <= close <= r["close_band90"][1],
                "size_log_error": math.log(max(actual, 1e-3) / r["expected_remaining_range_pct"]),
                "scored_at": stamp,
            }
        changed += 1
    if changed:
        _write(target, rows)
    return {"records": len(rows), "newly_scored": changed, "pending": sum(1 for r in rows if r.get("outcome") is None)}


def score_from_saved_history(path: Path | None = None) -> dict:
    """Score pending records from the saved Groww candles (completed sessions only)."""
    from app.market import history_loader as hl
    from app.research.multiyear_service import INTRADAY_INSTRUMENTS, completed_sessions

    daily, intraday = {}, {}
    for instrument, symbol in INTRADAY_INSTRUMENTS.items():
        d = hl.load_series(symbol, "1day")
        q = hl.load_series(symbol, "15minute")
        daily[instrument] = {str(r[0])[:10]: r for r in completed_sessions(d["candles"])} if d and d.get("candles") else {}
        intraday[instrument] = _bars_by_day(completed_sessions(q["candles"])) if q and q.get("candles") else {}
    return score_pending(daily, intraday, path=path)


# ----------------------------------------------------------------------------- summary

def _rate(rows: list[dict], key: str) -> float | None:
    vals = [r["outcome"][key] for r in rows if r["outcome"].get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def summarize(path: Path | None = None) -> dict[str, Any]:
    rows = _read(path or LOG_PATH)
    daily = [r for r in rows if r["kind"] == "daily"]
    scored_daily = [r for r in daily if r.get("outcome")]
    out: dict[str, Any] = {
        "schema": "forecast-log-1",
        "first_record": min((r["made_at"] for r in rows), default=None),
        "daily": {
            "logged": len(daily), "scored": len(scored_daily),
            "range_in_band68": _rate(scored_daily, "in_band68"), "range_in_band90": _rate(scored_daily, "in_band90"),
            "move_within_p90": _rate(scored_daily, "move_within_p90"),
            "recent": [
                {k: r.get(k) for k in ("for_session", "as_of_session", "last_close", "expected_range_pct",
                                       "range_band68_pct", "range_band90_pct", "probability_up", "outcome")}
                for r in sorted(daily, key=lambda r: r["for_session"], reverse=True)[:RECENT]
            ],
        },
        "intraday": {},
    }
    for instrument in sorted({r["instrument"] for r in rows if r["kind"] == "intraday"}):
        logged = [r for r in rows if r["kind"] == "intraday" and r["instrument"] == instrument]
        scored = [r for r in logged if r.get("outcome")]
        sessions: dict[str, list[dict]] = {}
        for r in logged:
            sessions.setdefault(r["session_day"], []).append(r)
        errors = [abs(r["outcome"]["size_log_error"]) for r in scored]
        out["intraday"][instrument] = {
            "logged": len(logged), "scored": len(scored), "sessions": len(sessions),
            **{k: _rate(scored, k) for k in ("range_in_band68", "range_in_band90", "high_within_p90",
                                             "low_within_p90", "close_in_band68", "close_in_band90")},
            "typical_size_error_factor": math.exp(sum(errors) / len(errors)) if errors else None,
            "recent_sessions": [
                {
                    "day": day, "checkpoints": len(rs),
                    "scored": sum(1 for r in rs if r.get("outcome")),
                    "range_in_band90": _rate([r for r in rs if r.get("outcome")], "range_in_band90"),
                    "high_within_p90": _rate([r for r in rs if r.get("outcome")], "high_within_p90"),
                    "low_within_p90": _rate([r for r in rs if r.get("outcome")], "low_within_p90"),
                }
                for day, rs in sorted(sessions.items(), reverse=True)[:RECENT]
            ],
        }
    return out
