"""Validated, versioned configuration management for independent AI agents.

Enables administrators to choose provider and model per agent independently
without altering application source code.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.settings import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "var" / "config" / "agent_system_config.json"


class AgentRole(str, Enum):
    MARKET_DATA = "market_data_analyst"
    TECHNICAL = "technical_analyst"
    GLOBAL_MACRO = "global_macro_analyst"
    NEWS_EVENT = "news_event_analyst"
    OPTIONS = "options_analyst"
    QUANT_FORECAST = "quant_forecast_analyst"
    RISK_UNCERTAINTY = "risk_uncertainty_analyst"
    FINAL_DECISION = "final_decision_agent"


class SingleAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    display_name: str
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=100, le=8000)
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    fallback_provider: str | None = None
    fallback_model: str | None = None
    description: str = ""


class MultiAgentSystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = "v6.18.0"
    updated_at: str | None = None
    agents: dict[str, SingleAgentConfig]


DEFAULT_AGENTS_CONFIG: dict[str, dict[str, Any]] = {
    AgentRole.MARKET_DATA.value: {
        "role": AgentRole.MARKET_DATA.value,
        "display_name": "Market Data Analyst",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 800,
        "timeout_seconds": 15.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-flash",
        "description": "Assesses data quality, coverage, freshness, missing values, and provider reconciliation results.",
    },
    AgentRole.TECHNICAL.value: {
        "role": AgentRole.TECHNICAL.value,
        "display_name": "Technical Analyst",
        "enabled": True,
        "provider": "google",
        "model": "gemini-1.5-pro",
        "temperature": 0.1,
        "max_tokens": 1000,
        "timeout_seconds": 15.0,
        "fallback_provider": "openai",
        "fallback_model": "gpt-4o-mini",
        "description": "Interprets validated trend, momentum, realized volatility, ATR, and multi-horizon returns.",
    },
    AgentRole.GLOBAL_MACRO.value: {
        "role": AgentRole.GLOBAL_MACRO.value,
        "display_name": "Global and Macro Analyst",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.1,
        "max_tokens": 1000,
        "timeout_seconds": 15.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-flash",
        "description": "Analyzes GIFT NIFTY, global equity indices, US Treasury yields, crude oil, USD/INR, and India VIX.",
    },
    AgentRole.NEWS_EVENT.value: {
        "role": AgentRole.NEWS_EVENT.value,
        "display_name": "News and Event Analyst",
        "enabled": True,
        "provider": "google",
        "model": "gemini-1.5-pro",
        "temperature": 0.0,
        "max_tokens": 1200,
        "timeout_seconds": 15.0,
        "fallback_provider": "openai",
        "fallback_model": "gpt-4o-mini",
        "description": "Evaluates timestamped news, distinguishing confirmed facts, reported claims, and interpretations.",
    },
    AgentRole.OPTIONS.value: {
        "role": AgentRole.OPTIONS.value,
        "display_name": "Options Analyst",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 800,
        "timeout_seconds": 15.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-flash",
        "description": "Analyzes options-derived metrics (PCR, Max Pain, IV) strictly when verified data is available.",
    },
    AgentRole.QUANT_FORECAST.value: {
        "role": AgentRole.QUANT_FORECAST.value,
        "display_name": "Quantitative Forecast Analyst",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 1000,
        "timeout_seconds": 15.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-flash",
        "description": "Interprets registered quantitative model forecasts, evaluation evidence, and probability estimates.",
    },
    AgentRole.RISK_UNCERTAINTY.value: {
        "role": AgentRole.RISK_UNCERTAINTY.value,
        "display_name": "Risk and Uncertainty Analyst",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "max_tokens": 1200,
        "timeout_seconds": 15.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-pro",
        "description": "Identifies conflicting evidence, stale inputs, high model uncertainty, and unsupported assumptions.",
    },
    AgentRole.FINAL_DECISION.value: {
        "role": AgentRole.FINAL_DECISION.value,
        "display_name": "Final Decision Agent",
        "enabled": True,
        "provider": "openai",
        "model": "gpt-4o",
        "temperature": 0.0,
        "max_tokens": 1500,
        "timeout_seconds": 20.0,
        "fallback_provider": "gemini",
        "fallback_model": "gemini-1.5-pro",
        "description": "Synthesizes specialist agent outputs into a structured recommendation, enforcing NO_TRADE on gate failure.",
    },
}


def load_agent_system_config(config_file: Path | None = None) -> MultiAgentSystemConfig:
    """Load persisted agent configuration with fallback to canonical defaults."""
    target_path = config_file or CONFIG_PATH
    if target_path.exists():
        try:
            data = json.loads(target_path.read_text(encoding="utf-8"))
            return MultiAgentSystemConfig(**data)
        except Exception:
            pass

    # Build default config
    agents = {
        role: SingleAgentConfig(**cfg) for role, cfg in DEFAULT_AGENTS_CONFIG.items()
    }
    return MultiAgentSystemConfig(version="v6.18.0", agents=agents)


def save_agent_system_config(
    config: MultiAgentSystemConfig,
    config_file: Path | None = None,
) -> MultiAgentSystemConfig:
    """Persist validated agent system configuration to disk."""
    from datetime import datetime, timezone
    target_path = config_file or CONFIG_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    config.updated_at = datetime.now(timezone.utc).isoformat()
    target_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return config
