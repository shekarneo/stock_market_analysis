"""PostgreSQL row lease manager for distributed workers.

A row lease prevents multiple worker instances from submitting duplicate trades,
running concurrent scheduler ticks, or conflicting over the same intent.
Expired leases can be taken over monotonically with an incremented fencing token.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.tables import WorkerLease


def acquire_lease(
    session: Session,
    lease_key: str,
    owner_id: str,
    *,
    duration_seconds: int = 30,
    now: datetime | None = None,
    commit: bool = True,
) -> dict:
    """Acquire or renew a row lease. Returns an acquisition result with fencing token."""
    if not isinstance(lease_key, str) or not lease_key.strip():
        return {"acquired": False, "reason": "INVALID_LEASE_KEY"}
    if not isinstance(owner_id, str) or not owner_id.strip():
        return {"acquired": False, "reason": "INVALID_OWNER_ID"}
    current_time = _ensure_utc(now) or datetime.now(timezone.utc)
    expires_at = current_time + timedelta(seconds=max(1, duration_seconds))

    row = session.execute(
        select(WorkerLease).where(WorkerLease.lease_key == lease_key).with_for_update()
    ).scalar_one_or_none()

    if row is None:
        new_row = WorkerLease(
            lease_key=lease_key,
            owner_id=owner_id,
            acquired_at=current_time,
            expires_at=expires_at,
            fencing_token=1,
            updated_at=current_time,
        )
        session.add(new_row)
        _finish_tx(session, commit=commit)
        return {
            "acquired": True,
            "lease_key": lease_key,
            "owner_id": owner_id,
            "fencing_token": 1,
            "expires_at": expires_at.isoformat(),
        }

    # Existing row owned by the same worker
    if row.owner_id == owner_id:
        row.expires_at = expires_at
        row.updated_at = current_time
        _finish_tx(session, commit=commit)
        return {
            "acquired": True,
            "lease_key": lease_key,
            "owner_id": owner_id,
            "fencing_token": row.fencing_token,
            "expires_at": expires_at.isoformat(),
        }

    # Lease has expired: takeover allowed
    if row.expires_at <= current_time:
        row.owner_id = owner_id
        row.acquired_at = current_time
        row.expires_at = expires_at
        row.fencing_token += 1
        row.updated_at = current_time
        _finish_tx(session, commit=commit)
        return {
            "acquired": True,
            "lease_key": lease_key,
            "owner_id": owner_id,
            "fencing_token": row.fencing_token,
            "expires_at": expires_at.isoformat(),
            "takeover": True,
        }

    # Lease actively held by another owner
    return {
        "acquired": False,
        "reason": "LEASE_HELD_BY_ANOTHER_OWNER",
        "lease_key": lease_key,
        "current_owner": row.owner_id,
        "expires_at": row.expires_at.isoformat(),
    }


def renew_lease(
    session: Session,
    lease_key: str,
    owner_id: str,
    *,
    duration_seconds: int = 30,
    now: datetime | None = None,
    commit: bool = True,
) -> dict:
    """Renew an actively held lease. Fails if the lease was lost or expired."""
    current_time = _ensure_utc(now) or datetime.now(timezone.utc)
    expires_at = current_time + timedelta(seconds=max(1, duration_seconds))

    row = session.execute(
        select(WorkerLease).where(WorkerLease.lease_key == lease_key).with_for_update()
    ).scalar_one_or_none()

    if row is None or row.owner_id != owner_id:
        return {"renewed": False, "reason": "LEASE_NOT_FOUND_OR_NOT_OWNED"}

    if row.expires_at <= current_time:
        return {"renewed": False, "reason": "LEASE_ALREADY_EXPIRED"}

    row.expires_at = expires_at
    row.updated_at = current_time
    _finish_tx(session, commit=commit)
    return {
        "renewed": True,
        "lease_key": lease_key,
        "owner_id": owner_id,
        "fencing_token": row.fencing_token,
        "expires_at": expires_at.isoformat(),
    }


def release_lease(
    session: Session,
    lease_key: str,
    owner_id: str,
    *,
    commit: bool = True,
) -> bool:
    """Release a lease row if owned by the caller."""
    row = session.execute(
        select(WorkerLease).where(WorkerLease.lease_key == lease_key).with_for_update()
    ).scalar_one_or_none()

    if row is not None and row.owner_id == owner_id:
        session.delete(row)
        _finish_tx(session, commit=commit)
        return True
    return False


def read_lease(
    session: Session,
    lease_key: str,
    *,
    now: datetime | None = None,
) -> dict | None:
    """Read a lease without holding a write lock."""
    current_time = _ensure_utc(now) or datetime.now(timezone.utc)
    row = session.get(WorkerLease, lease_key)
    if row is None:
        return None
    is_active = row.expires_at > current_time
    return {
        "lease_key": row.lease_key,
        "owner_id": row.owner_id,
        "acquired_at": row.acquired_at.isoformat(),
        "expires_at": row.expires_at.isoformat(),
        "fencing_token": row.fencing_token,
        "is_active": is_active,
    }


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _finish_tx(session: Session, *, commit: bool) -> None:
    if commit:
        session.commit()
    else:
        session.flush()
