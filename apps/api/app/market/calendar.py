from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum

from pydantic import BaseModel, ConfigDict

from app.market.schemas import IST


class CalendarState(str, Enum):
    LISTED_SESSION = "LISTED_SESSION"
    NOT_A_SESSION = "NOT_A_SESSION"
    UNKNOWN = "UNKNOWN"


class CalendarAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: CalendarState
    authoritative: bool
    limitation: str


class ExchangeCalendar:
    """Session clock for gap checks.

    This is not an official NSE or BSE holiday calendar. `holiday_calendar_source_id`
    is unset, so a date that is not explicitly listed stays UNKNOWN.
    """

    open_time = time(9, 15)
    close_time = time(15, 30)
    limitation = (
        "No authoritative holiday calendar is configured. "
        "Only dates listed on this fixture calendar have a session state."
    )

    def __init__(self, listed_sessions: set[date], closed_dates: set[date]) -> None:
        overlap = listed_sessions & closed_dates
        if overlap:
            raise ValueError(f"calendar lists and closes the same date: {sorted(overlap)}")
        self.listed_sessions = set(listed_sessions)
        self.closed_dates = set(closed_dates)

    def assess(self, moment: datetime) -> CalendarAssessment:
        local = moment.astimezone(IST)
        day = local.date()
        if day in self.listed_sessions:
            state = CalendarState.LISTED_SESSION
        elif day in self.closed_dates:
            state = CalendarState.NOT_A_SESSION
        else:
            state = CalendarState.UNKNOWN
        return CalendarAssessment(state=state, authoritative=False, limitation=self.limitation)

    def in_regular_window(self, moment: datetime) -> bool:
        local = moment.astimezone(IST)
        return self.open_time <= local.time() <= self.close_time


class MCXExchangeCalendar(ExchangeCalendar):
    """Session clock for MCX Commodity trades (e.g. CRUDEOILMINI, GOLDMINI).

    Standard MCX trading hours: 09:00:00 to 23:30:00 IST during US DST,
    and extended to 23:55:00 IST during US standard time (winter).
    """

    open_time = time(9, 0)
    close_time = time(23, 30)
    limitation = (
        "Standard MCX commodity session window is 09:00:00 to 23:30:00 IST "
        "(extended to 23:55:00 IST when US Daylight Saving Time is not active)."
    )

    def in_regular_window(self, moment: datetime) -> bool:
        from app.market.session_intelligence import is_us_daylight_saving_time
        local = moment.astimezone(IST)
        eff_close = time(23, 30) if is_us_daylight_saving_time(moment) else time(23, 55)
        return self.open_time <= local.time() <= eff_close


def get_exchange_calendar(
    instrument_or_exchange: str | None = None,
    *,
    listed_sessions: set[date] | None = None,
    closed_dates: set[date] | None = None,
) -> ExchangeCalendar:
    """Return appropriate exchange calendar based on instrument or exchange identifier."""
    listed = listed_sessions or set()
    closed = closed_dates or set()
    if not instrument_or_exchange:
        return ExchangeCalendar(listed, closed)
    upper = str(instrument_or_exchange).upper()
    if upper in {"MCX", "COMMODITY", "CRUDEOILMINI", "CRUDEMINI", "GOLDMINI", "SILVERMINI", "NATURALGASMINI"}:
        return MCXExchangeCalendar(listed, closed)
    return ExchangeCalendar(listed, closed)

