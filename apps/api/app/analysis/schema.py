"""Evidence and report schemas for the M8 analysis graph.

A source claim is not verified because a model repeats it. This module does
not emit a probability and does not accept approval flags.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["NEWS", "MACRO", "GLOBAL_MARKET", "INDIAN_MARKET", "DERIVATIVES", "TECHNICAL", "OTHER"]
ClaimType = Literal["OBSERVATION", "SOURCE_CLAIM", "CALCULATION", "INTERPRETATION"]
Direction = Literal["BULLISH", "BEARISH", "MIXED", "UNKNOWN"]
Horizon = Literal["INTRADAY", "SHORT_TERM", "LONGER_TERM", "UNKNOWN"]
Provenance = Literal["PROVIDER", "DOCUMENTED_SAMPLE", "SYNTHETIC"]
Freshness = Literal["FRESH", "STALE", "CLOSED_SESSION_VALID", "UNKNOWN"]
Verification = Literal["VERIFIED", "UNVERIFIED", "CONFLICTING"]

INSTRUMENTS = (
    "NIFTY",
    "SENSEX",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "BANKEX",
    "NIFTYIT",
    "NIFTYAUTO",
    "NIFTYMETAL",
    "SPX",
    "NASDAQ",
    "DJI",
    "RUSSELL",
    "VIX",
    "GIFTNIFTY",
    "DOW_FUT",
    "NIKKEI",
    "HANGSENG",
    "CRUDE",
    "CRUDEMINI",
    "CRUDEOILMINI",
    "GOLD",
    "GOLDMINI",
    "SILVER",
    "SILVERMINI",
    "NATURALGAS",
    "NATURALGASMINI",
    "COPPER",
    "ZINC",
    "USDINR",
)
GLOBAL_INSTRUMENTS = ("SPX", "NASDAQ", "DJI", "RUSSELL", "VIX")
INDIAN_INSTRUMENTS = ("NIFTY", "SENSEX")
MACRO_INSTRUMENTS = ("CRUDE", "USDINR")
COMMODITY_INSTRUMENTS = ("CRUDE", "CRUDEMINI", "CRUDEOILMINI", "GOLD", "GOLDMINI", "SILVER", "SILVERMINI", "NATURALGAS", "NATURALGASMINI", "COPPER", "ZINC")
HORIZONS = ("INTRADAY", "SHORT_TERM", "LONGER_TERM")


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    category: Category
    claim: str
    claim_type: ClaimType
    source_name: str
    source_url: str | None = None
    observed_at: datetime | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    instrument: str | None = None
    directional_implication: Direction
    time_horizon: Horizon
    provenance: Provenance
    freshness: Freshness
    verification_status: Verification
    limitations: list[str] = Field(default_factory=list)
    claim_kind: Literal["FACT", "ALLEGATION", "ESTIMATE", "OPINION", "UNKNOWN"] = "UNKNOWN"
    event_category: str | None = None
    affected_entities: list[str] = Field(default_factory=list)
    last_price: float | None = None
    unit: str | None = None
    ohlc: dict | None = None
    price_direction: Literal["UP", "DOWN", "FLAT", "UNKNOWN"] = "UNKNOWN"
    """The instrument's own price move. directional_implication is its implication for Indian equities."""


class InferenceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    note: str
    directional_implication: Direction


class InferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interpretations: list[InferenceNote]


class AnalysisReport(BaseModel):
    """Public analysis result. Approval flags and confidence cannot be set true."""

    model_config = ConfigDict(extra="forbid")
    analysis_id: str | None = None
    status: Literal["INSUFFICIENT_DATA", "COMPLETED", "FAILED"]
    decision: Literal["NO_TRADE"] = "NO_TRADE"
    code: str | None = None
    message: str | None = None
    created_at: str | None = None
    timezone: str = "UTC"
    instruments: list[str] = Field(default_factory=list)
    directional_assessment: Literal["BULLISH", "BEARISH", "MIXED"] | None = None
    confidence: None = None
    bullish_evidence: list[str] = Field(default_factory=list)
    bearish_evidence: list[str] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    rejected: list[dict] = Field(default_factory=list)
    node_status: dict = Field(default_factory=dict)
    provider_errors: list[dict] = Field(default_factory=list)
    inference: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    quality: dict = Field(default_factory=dict)
    intelligence: dict = Field(default_factory=dict)
    post_close_context: bool = False
    forecast_ready: bool = False
    paper_approved: bool = False
    live_approved: bool = False
    real_market_data_verified: bool = False
    live_trading_enabled: bool = False
    live_broker_routing_enabled: bool = False
    agent_outputs: dict = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    consensus: dict = Field(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        object.__setattr__(self, "forecast_ready", False)
        object.__setattr__(self, "paper_approved", False)
        object.__setattr__(self, "live_approved", False)
        object.__setattr__(self, "real_market_data_verified", False)
        object.__setattr__(self, "live_trading_enabled", False)
        object.__setattr__(self, "live_broker_routing_enabled", False)
        object.__setattr__(self, "confidence", None)
        object.__setattr__(self, "decision", "NO_TRADE")


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    role: str
    display_name: str
    status: Literal["SUCCESS", "PARTIAL", "FAILED", "SKIPPED", "FALLBACK_USED"]
    provider: str
    model: str
    execution_mode: Literal[
        "LLM",
        "LLM_FALLBACK",
        "MOCK_LLM",
        "DETERMINISTIC_RULE",
        "DETERMINISTIC_FALLBACK_ON_LLM_ERROR",
        "SKIPPED",
    ] = "DETERMINISTIC_RULE"
    llm_attempted: bool = False
    llm_succeeded: bool = False
    fallback_used: bool = False
    configured_provider: str | None = None
    configured_model: str | None = None
    config_version: str = "v6.18.0"
    findings: list[str] = Field(default_factory=list)
    directional_bias: Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED", "UNKNOWN"] = "UNKNOWN"
    confidence: float | None = None
    semantic_type: str = "UNKNOWN"
    is_probability: bool = False
    is_calibrated: bool = False
    provenance_verified: bool = False
    evidence_references: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    token_usage: dict[str, int] | None = None
    timestamp: str | None = None

