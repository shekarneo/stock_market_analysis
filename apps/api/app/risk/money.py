"""Decimal parsing. Values are not rounded to a tick."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_or_none(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number
