"""Watchlist outcome tracking.

A saved suggestion is judged only against the underlying spot that Groww reports
(target_spot / stop_loss_spot). The option premiums shown on the desk are model
estimates, not exchange quotes, so they are stored for reference and never used
to decide whether a target or a stop was hit.

Limitations that are surfaced to the operator:
- Prices are polled snapshots, not ticks. A level touched briefly between two
  polls is not seen, so hit rates are approximate.
- A quote retrieved before the suggestion was saved is never used to resolve it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.tables import WatchlistSuggestion
from app.market.schemas import IST

MCX_INSTRUMENTS = {
    "CRUDE", "CRUDEMINI", "CRUDEOILMINI", "GOLD", "GOLDMINI", "SILVER", "SILVERMINI",
    "NATURALGAS", "NATURALGASMINI", "COPPER", "ZINC",
}
MCX_CLOSE = time(23, 30)
NSE_CLOSE = time(15, 30)
RESOLVED = {"TARGET_HIT", "SL_HIT", "AMBIGUOUS", "EXPIRED", "CANCELLED"}


def _parse_ts(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def session_close(instrument: str, now: datetime) -> datetime:
    """End of the current trading session for the instrument (next weekday if already past)."""
    local = now.astimezone(IST)
    close = MCX_CLOSE if instrument.upper() in MCX_INSTRUMENTS else NSE_CLOSE
    candidate = datetime.combine(local.date(), close, tzinfo=IST)
    if local >= candidate or local.weekday() >= 5:
        day = local.date() + timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        candidate = datetime.combine(day, close, tzinfo=IST)
    return candidate


def latest_spots(observations: list[dict]) -> dict[str, dict]:
    """Newest numeric last_price per instrument with its retrieval time."""
    out: dict[str, dict] = {}
    for row in observations:
        inst = row.get("instrument")
        price = row.get("last_price")
        if not inst or price is None:
            continue
        try:
            value = float(price)
        except (TypeError, ValueError):
            continue
        stamp = _parse_ts(row.get("retrieved_at")) or _parse_ts(row.get("observed_at"))
        prev = out.get(inst)
        if prev is None or (stamp and (prev["at"] is None or stamp > prev["at"])):
            out[inst] = {"price": value, "at": stamp}
    return out


def create_suggestion(
    session: Session,
    *,
    instrument: str,
    contract: str,
    option_type: str,
    call: str | None,
    entry_spot: float,
    target_points: float,
    stop_loss_points: float,
    model_premiums: dict,
    data_class: str | None,
    created_by: str,
    now: datetime | None = None,
) -> WatchlistSuggestion:
    now = now or datetime.now(timezone.utc)
    opt = option_type.upper()
    if opt not in {"CE", "PE"}:
        raise ValueError("option_type must be CE or PE.")
    if entry_spot <= 0 or target_points <= 0 or stop_loss_points <= 0:
        raise ValueError("Spot and point distances must be positive.")
    up = opt == "CE"
    row = WatchlistSuggestion(
        suggestion_id=uuid.uuid4().hex,
        instrument=instrument.upper(),
        contract=contract,
        option_type=opt,
        direction="UP" if up else "DOWN",
        call=call,
        entry_spot=Decimal(str(round(entry_spot, 4))),
        target_spot=Decimal(str(round(entry_spot + target_points if up else entry_spot - target_points, 4))),
        stop_loss_spot=Decimal(str(round(entry_spot - stop_loss_points if up else entry_spot + stop_loss_points, 4))),
        model_premiums=model_premiums,
        data_class=data_class,
        status="OPEN",
        expires_at=session_close(instrument, now),
        checks=0,
        created_by=created_by,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row


def evaluate_open(session: Session, observations: list[dict], now: datetime | None = None) -> dict:
    """Check every OPEN suggestion against the newest spot that post-dates it."""
    now = now or datetime.now(timezone.utc)
    spots = latest_spots(observations)
    rows = session.scalars(select(WatchlistSuggestion).where(WatchlistSuggestion.status == "OPEN")).all()
    changed = 0
    for row in rows:
        quote = spots.get(row.instrument)
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        fresh = quote is not None and quote["at"] is not None and quote["at"] > created
        if fresh:
            spot = Decimal(str(quote["price"]))
            row.last_spot = spot
            row.last_checked_at = quote["at"]
            row.checks = (row.checks or 0) + 1
            up = row.direction == "UP"
            if row.max_favorable_spot is None:
                row.max_favorable_spot = spot
                row.max_adverse_spot = spot
            else:
                row.max_favorable_spot = max(row.max_favorable_spot, spot) if up else min(row.max_favorable_spot, spot)
                row.max_adverse_spot = min(row.max_adverse_spot, spot) if up else max(row.max_adverse_spot, spot)
            hit_target = spot >= row.target_spot if up else spot <= row.target_spot
            hit_sl = spot <= row.stop_loss_spot if up else spot >= row.stop_loss_spot
            if hit_target or hit_sl:
                row.status = "TARGET_HIT" if hit_target else "SL_HIT"
                row.resolved_at = quote["at"]
                row.resolved_spot = spot
                changed += 1
                continue
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if now >= expires:
            row.status = "EXPIRED"
            row.resolved_at = now
            row.resolved_spot = row.last_spot
            row.note = "Session closed before target or stop was observed."
            changed += 1
    session.flush()
    return {"checked": len(rows), "resolved": changed}


def serialize(row: WatchlistSuggestion) -> dict:
    def num(v):
        return float(v) if v is not None else None

    def ts(v):
        return v.isoformat() if v is not None else None

    return {
        "suggestion_id": row.suggestion_id,
        "instrument": row.instrument,
        "contract": row.contract,
        "option_type": row.option_type,
        "direction": row.direction,
        "call": row.call,
        "entry_spot": num(row.entry_spot),
        "target_spot": num(row.target_spot),
        "stop_loss_spot": num(row.stop_loss_spot),
        "model_premiums": row.model_premiums,
        "data_class": row.data_class,
        "status": row.status,
        "expires_at": ts(row.expires_at),
        "last_spot": num(row.last_spot),
        "last_checked_at": ts(row.last_checked_at),
        "max_favorable_spot": num(row.max_favorable_spot),
        "max_adverse_spot": num(row.max_adverse_spot),
        "checks": row.checks,
        "resolved_at": ts(row.resolved_at),
        "resolved_spot": num(row.resolved_spot),
        "note": row.note,
        "created_at": ts(row.created_at),
    }


def accuracy(rows: list[WatchlistSuggestion]) -> dict:
    """Hit rate = TARGET_HIT / (TARGET_HIT + SL_HIT). Expired rows are reported, not scored."""

    def tally(items):
        counts = {s: 0 for s in ("OPEN", "TARGET_HIT", "SL_HIT", "AMBIGUOUS", "EXPIRED", "CANCELLED")}
        for r in items:
            counts[r.status] = counts.get(r.status, 0) + 1
        decided = counts["TARGET_HIT"] + counts["SL_HIT"]
        return {
            **counts,
            "decided": decided,
            "hit_rate": round(counts["TARGET_HIT"] / decided, 4) if decided else None,
        }

    overall = tally(rows)
    by_instrument = {}
    for inst in sorted({r.instrument for r in rows}):
        by_instrument[inst] = tally([r for r in rows if r.instrument == inst])
    by_direction = {d: tally([r for r in rows if r.direction == d]) for d in ("UP", "DOWN")}
    return {
        "overall": overall,
        "by_instrument": by_instrument,
        "by_direction": by_direction,
        "sample_warning": overall["decided"] < 30,
        "method": "Judged on observed underlying spot vs target/stop spot. Option premiums are model estimates and are not scored.",
    }
