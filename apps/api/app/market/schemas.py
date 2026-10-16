from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Literal["1.0"] = "1.0"
IST = ZoneInfo("Asia/Kolkata")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataOrigin(str, Enum):
    SYNTHETIC = "SYNTHETIC"
    DOCUMENTED_SAMPLE = "DOCUMENTED_SAMPLE"
    PROVIDER = "PROVIDER"


class QualityStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class MarketSession(str, Enum):
    PRE_OPEN = "PRE_OPEN"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class IssueSeverity(str, Enum):
    FATAL = "FATAL"
    WARNING = "WARNING"


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(IST)


class InstrumentRef(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    instrument_id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    underlying: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,31}$")
    exchange: str | None = None
    segment: str | None = None


class Candle(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    instrument_id: str
    underlying: str
    exchange: str | None = None
    interval: Literal["M15"]
    bar_start: datetime
    bar_end: datetime
    provider_timestamp: datetime | None = None
    retrieved_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    source_id: str
    origin: DataOrigin
    session: MarketSession
    quality: QualityStatus = QualityStatus.PASS

    @field_validator("bar_start", "bar_end", "retrieved_at", "provider_timestamp")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware(value, "timestamp")


class Quote(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    instrument_id: str
    underlying: str
    exchange: str | None = None
    event_timestamp: datetime
    provider_timestamp: datetime | None = None
    retrieved_at: datetime
    last_price: float | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    source_id: str
    origin: DataOrigin
    session: MarketSession
    quality: QualityStatus = QualityStatus.PASS
    unavailable_reason: str | None = None

    @field_validator("event_timestamp", "retrieved_at", "provider_timestamp")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware(value, "timestamp")


class ContextObservation(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    code: str
    value: float | None
    unit: str | None = None
    event_timestamp: datetime | None = None
    retrieved_at: datetime | None = None
    source_id: str
    origin: DataOrigin
    quality: QualityStatus
    detail: str

    @field_validator("event_timestamp", "retrieved_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware(value, "timestamp")


class QualityIssue(StrictModel):
    code: str
    severity: IssueSeverity
    message: str
    instrument_id: str | None = None


class QualityReport(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    status: QualityStatus
    ok: bool
    issues: list[QualityIssue]


class RetrievalFailure(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    ok: Literal[False] = False
    code: str
    message: str
    origin: DataOrigin | None = None


class Readiness(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    data_ready: bool
    forecast_ready: Literal[False] = False
    proposal_blocked: bool
    reasons: list[str]
