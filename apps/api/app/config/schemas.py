from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OperatingMode(str, Enum):
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    LIVE_READ_ONLY = "LIVE_READ_ONLY"
    LIVE_TRADING = "LIVE_TRADING"


class SourceKind(str, Enum):
    market = "market"
    commodity = "commodity"
    macro = "macro"
    flow = "flow"
    calendar = "calendar"
    news = "news"


class Connector(str, Enum):
    groww = "groww"
    rss = "rss"
    atom = "atom"
    http_json = "http_json"
    fixture = "fixture"


class NewsTier(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CONTEXT = "CONTEXT"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeConfig(StrictModel):
    mode: OperatingMode = OperatingMode.PAPER
    live_trading_enabled: bool = False
    unattended_orders: bool = False

    @model_validator(mode="after")
    def live_flags(self) -> "RuntimeConfig":
        if self.mode is OperatingMode.LIVE_TRADING and not self.live_trading_enabled:
            raise ValueError("LIVE_TRADING requires live_trading_enabled")
        if self.unattended_orders and self.mode is not OperatingMode.LIVE_TRADING:
            raise ValueError("unattended orders require LIVE_TRADING")
        if self.unattended_orders:
            raise ValueError("unattended live orders are not available")
        return self


class DataSource(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    enabled: bool
    kind: SourceKind
    connector: Connector
    endpoint: str = Field(min_length=1)
    secret_ref: str | None = None
    symbols: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    poll_seconds: int = Field(ge=30, le=86400)
    timeout_seconds: int = Field(ge=1, le=60)
    max_items: int = Field(ge=1, le=200)
    priority: int = 0
    tier: NewsTier | None = None
    language: str | None = None
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    @field_validator("secret_ref")
    @classmethod
    def secret_ref_is_env_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.isidentifier() or not value.isupper():
            raise ValueError("secret_ref must be an uppercase environment variable name")
        return value

    @model_validator(mode="after")
    def news_fields(self) -> "DataSource":
        if self.kind is SourceKind.news and self.tier is None:
            raise ValueError("news sources require a tier")
        if self.kind is not SourceKind.news and self.tier is not None:
            raise ValueError("tier is only valid for news sources")
        return self


class FreshnessConfig(StrictModel):
    index_warn_seconds: int = Field(60, ge=1)
    option_block_seconds: int = Field(15, ge=1)
    crude_warn_seconds: int = Field(900, ge=1)
    crude_shock_warn_seconds: int = Field(300, ge=1)


class Situation(StrictModel):
    code: Literal[
        "ENERGY_SUPPLY",
        "SHIPPING_DISRUPTION",
        "RATES_LIQUIDITY",
        "TRADE_TARIFF",
        "RISK_OFF",
        "DOMESTIC_POLICY",
    ]
    scope: Literal["DAY", "WEEK", "MONTH"]
    driver_codes: list[str]


class ContextBookConfig(StrictModel):
    standing: list[str]
    situations: list[Situation]


class HorizonsConfig(StrictModel):
    enabled: list[Literal["M15", "M30", "SESSION", "NEXT_SESSION"]]
    # Candidate grid only. An empty list means no threshold has been selected.
    threshold_grid: list[float] = Field(default_factory=list)
    selection_metric: Literal["log_loss", "brier"] | None = None

    @field_validator("threshold_grid")
    @classmethod
    def positive_candidates(cls, value: list[float]) -> list[float]:
        if any(item <= 0 for item in value):
            raise ValueError("threshold candidates must be positive")
        return value


class FusionConfig(StrictModel):
    enabled: Literal[True] = True
    min_log_loss_improvement: float | None = None
    tail_metric: Literal["worst_decile_mean_return"] = "worst_decile_mean_return"


class RiskConfig(StrictModel):
    risk_capital_inr: float | None = None
    max_risk_fraction_per_trade: float = Field(0.01, gt=0, le=1)
    daily_loss_fraction: float = Field(0.02, gt=0, le=1)
    daily_loss_includes_unrealized: bool = True
    cash_buffer_fraction: float = Field(0.20, ge=0, lt=1)
    max_open_positions: int = Field(2, ge=0)
    max_new_entries_per_session: int = Field(3, ge=0)
    consecutive_loss_cooldown: int = Field(2, ge=1)
    drawdown_lockout_fraction: float | None = None
    allowed_structures: list[Literal["LONG_CE", "LONG_PE", "LONG_FUT", "SHORT_FUT"]]
    allowed_underlyings: list[Literal["NIFTY", "SENSEX", "CRUDEOILMINI", "BANKNIFTY", "CRUDEMINI"]]
    max_futures_lots_per_trade: int = Field(1, ge=1)
    quote_max_age_seconds: int = Field(15, ge=1)
    # When true (default), experimental paper simulations need a server-computed expected
    # net; a client-sent expected_net is never trusted. Operators may set it false in their
    # stored config to exercise the paper pipeline while no EV model exists.
    experimental_requires_server_ev: bool = True

    @field_validator("risk_capital_inr", "drawdown_lockout_fraction")
    @classmethod
    def positive_optional(cls, value: float | None) -> float | None:
        if value is not None and value <= 0:
            raise ValueError("value must be positive when set")
        return value


class ExecutionConfig(StrictModel):
    quote_max_age_seconds: int = Field(15, ge=1)
    paper_haircut: Literal["half_spread"] = "half_spread"
    extra_tick_penalty: Literal[False] = False


class ScheduleConfig(StrictModel):
    analysis_cadence_seconds: int = Field(300, ge=30)
    holiday_calendar_source_id: str | None = None


class CursorConfig(StrictModel):
    model_id: str = "composer-2.5"
    news_open_web: bool = False
    macro_open_web: bool = False
    repair_attempts: int = Field(1, ge=0, le=1)


class NotifyConfig(StrictModel):
    adapter: Literal["log"] = "log"
    events: list[str] = Field(default_factory=list)


class AppConfig(StrictModel):
    runtime: RuntimeConfig
    sources: list[DataSource]
    freshness: FreshnessConfig
    context_book: ContextBookConfig
    horizons: HorizonsConfig
    fusion: FusionConfig
    risk: RiskConfig
    execution: ExecutionConfig
    schedule: ScheduleConfig
    cursor: CursorConfig
    notify: NotifyConfig

    @model_validator(mode="after")
    def unique_sources(self) -> "AppConfig":
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source ids must be unique")
        return self


SECTION_MODELS = {
    "runtime": RuntimeConfig,
    "freshness": FreshnessConfig,
    "context_book": ContextBookConfig,
    "horizons": HorizonsConfig,
    "fusion": FusionConfig,
    "risk": RiskConfig,
    "execution": ExecutionConfig,
    "schedule": ScheduleConfig,
    "cursor": CursorConfig,
    "notify": NotifyConfig,
}
