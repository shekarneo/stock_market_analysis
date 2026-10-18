import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.analysis.agent_config import (
    SingleAgentConfig,
    MultiAgentSystemConfig,
    AgentRole,
    load_agent_system_config,
    save_agent_system_config,
    DEFAULT_AGENTS_CONFIG,
)
from app.analysis.ai_providers import (
    AICompletionResult,
    AIProviderRegistry,
    GeminiModelProvider,
    OpenAIModelProvider,
)
from app.analysis.agent_nodes import (
    market_data_analyst_node,
    technical_analyst_node,
    global_macro_analyst_node,
    news_event_analyst_node,
    options_analyst_node,
    quant_forecast_analyst_node,
    risk_uncertainty_analyst_node,
    final_decision_agent_node,
)
from app.analysis.graph import build_graph
from app.analysis.schema import AgentOutput
from app.analysis.state import AnalysisState
from app.forecasting.comparison import compare_quantitative_models
from app.forecasting.targets import MODEL_FEATURES
from app.forecasting.walkforward import WalkForwardConfig
from app.market.schemas import IST
from app.market.independent_provider import (
    IndependentProviderAdapter,
    ProviderCandleRequest,
    normalize_reference_candles,
    to_canonical_candles,
    reconcile_providers_pairwise,
    investigate_indmoney_support,
    investigate_nse_official_support,
    INDEPENDENT_PROVIDER_SPECS,
)


def test_independent_provider_specifications():
    assert "kite" in INDEPENDENT_PROVIDER_SPECS
    assert "upstox" in INDEPENDENT_PROVIDER_SPECS
    assert "angelone" in INDEPENDENT_PROVIDER_SPECS

    kite = INDEPENDENT_PROVIDER_SPECS["kite"]
    assert "Zerodha Kite Connect" in kite["name"]
    assert kite["rate_limit_requests_per_sec"] == 3

    upstox = INDEPENDENT_PROVIDER_SPECS["upstox"]
    assert "Upstox" in upstox["name"]
    assert upstox["rate_limit_requests_per_sec"] == 5

    angelone = INDEPENDENT_PROVIDER_SPECS["angelone"]
    assert "Angel One" in angelone["name"]
    assert angelone["rate_limit_requests_per_sec"] == 3


def test_upstox_request_and_normalization():
    adapter = IndependentProviderAdapter("upstox")
    req = ProviderCandleRequest("NIFTY", "15minute", date(2026, 10, 14), date(2026, 10, 14))
    url, headers, params, body, method = adapter._build_request_parameters(
        date(2026, 10, 14),
        date(2026, 10, 14),
        req,
        {"access_token": "test_token"},
    )
    assert "/v2/historical-candle/NSE_INDEX%7CNifty%2050/15minute/2026-10-14/2026-10-14" in url
    assert headers["Authorization"] == "Bearer test_token"
    assert method == "GET"

    # Upstox returns descending candles [timestamp, open, high, low, close, volume, oi]
    raw_candles = [
        ["2026-10-14T09:30:00+05:30", 25050.0, 25080.0, 25040.0, 25070.0, 15000, 0],
        ["2026-10-14T09:15:00+05:30", 25000.0, 25060.0, 24990.0, 25045.0, 12000, 0],
    ]
    normalized = normalize_reference_candles(raw_candles, "upstox")
    assert len(normalized) == 2
    # Verify sorted ascending
    assert normalized[0]["timestamp"] == "2026-10-14T09:15:00+05:30"
    assert normalized[0]["open"] == 25000.0
    assert normalized[0]["close"] == 25045.0
    assert normalized[0]["provider"] == "upstox"
    assert normalized[1]["timestamp"] == "2026-10-14T09:30:00+05:30"
    assert normalized[1]["close"] == 25070.0

    canonical = to_canonical_candles(normalized, "NIFTY")
    assert len(canonical) == 2
    assert canonical[0].open == 25000.0


def test_kite_request_and_normalization():
    adapter = IndependentProviderAdapter("kite")
    req = ProviderCandleRequest("NIFTY", "15minute", date(2026, 10, 14), date(2026, 10, 14))
    url, headers, params, body, method = adapter._build_request_parameters(
        date(2026, 10, 14),
        date(2026, 10, 14),
        req,
        {"api_key": "k_key", "access_token": "k_tok"},
    )
    assert "/instruments/historical/256265/15minute" in url
    assert headers["Authorization"] == "token k_key:k_tok"
    assert params["from"] == "2026-10-14 09:15:00"
    assert params["to"] == "2026-10-14 15:30:00"

    raw_candles = [
        ["2026-10-14T09:15:00+0530", 25000.0, 25060.0, 24990.0, 25045.0, 12000, 0],
        ["2026-10-14T09:30:00+0530", 25050.0, 25080.0, 25040.0, 25070.0, 15000, 0],
    ]
    normalized = normalize_reference_candles(raw_candles, "kite")
    assert len(normalized) == 2
    assert normalized[0]["provider"] == "kite"
    assert normalized[0]["open"] == 25000.0


def test_angelone_request_and_normalization():
    adapter = IndependentProviderAdapter("angelone")
    req = ProviderCandleRequest("NIFTY", "15minute", date(2026, 10, 14), date(2026, 10, 14))
    url, headers, params, body, method = adapter._build_request_parameters(
        date(2026, 10, 14),
        date(2026, 10, 14),
        req,
        {"jwt_token": "j_tok", "api_key": "p_key"},
    )
    assert "getCandleData" in url
    assert headers["Authorization"] == "Bearer j_tok"
    assert headers["X-PrivateKey"] == "p_key"
    assert body["exchange"] == "NSE"
    assert body["symboltoken"] == "99926000"
    assert body["interval"] == "FIFTEEN_MINUTE"
    assert method == "POST"

    raw_candles = [
        ["2026-10-14T09:15:00+05:30", 25000.0, 25060.0, 24990.0, 25045.0, 12000],
        ["2026-10-14T09:30:00+05:30", 25050.0, 25080.0, 25040.0, 25070.0, 15000],
    ]
    normalized = normalize_reference_candles(raw_candles, "angelone")
    assert len(normalized) == 2
    assert normalized[0]["provider"] == "angelone"
    assert normalized[1]["volume"] == 15000.0


def test_reconciliation_pairwise():
    candles_kite = normalize_reference_candles([
        ["2026-10-14T09:15:00+05:30", 25000.0, 25060.0, 24990.0, 25045.0, 12000, 0],
        ["2026-10-14T09:30:00+05:30", 25050.0, 25080.0, 25040.0, 25070.0, 15000, 0],
    ], "kite")

    # Identical prices
    candles_upstox = normalize_reference_candles([
        ["2026-10-14T09:15:00+05:30", 25000.0, 25060.0, 24990.0, 25045.0, 12000, 0],
        ["2026-10-14T09:30:00+05:30", 25050.0, 25080.0, 25040.0, 25070.0, 15000, 0],
    ], "upstox")

    report = reconcile_providers_pairwise(candles_kite, candles_upstox, "kite", "upstox", tolerance=0.05)
    assert report["status"] == "RECONCILIATION_MATCHED"
    assert report["matched_candles_count"] == 2
    assert report["mismatches_count"] == 0

    # Introduce a price discrepancy
    candles_upstox_diff = normalize_reference_candles([
        ["2026-10-14T09:15:00+05:30", 25000.0, 25060.0, 24990.0, 25045.0, 12000, 0],
        ["2026-10-14T09:30:00+05:30", 25050.0, 25080.0, 25040.0, 25150.0, 15000, 0],  # 80 pts diff
    ], "upstox")

    report_diff = reconcile_providers_pairwise(candles_kite, candles_upstox_diff, "kite", "upstox", tolerance=0.05)
    assert report_diff["status"] == "DISCREPANCIES_DETECTED"
    assert report_diff["mismatches_count"] == 1


def test_indmoney_and_nse_investigations():
    indmoney_eval = investigate_indmoney_support()
    assert indmoney_eval["status"] == "BLOCKED_NOT_PERMITTED"
    assert "No public, documented, or permitted developer API" in indmoney_eval["finding"]

    nse_eval = investigate_nse_official_support()
    assert nse_eval["status"] == "LIMITED_TO_DAILY_PUBLIC_REPORTS"
    assert "DotEx" in nse_eval["finding"]


def test_agent_configuration_crud(tmp_path):
    cfg_file = tmp_path / "agent_system_config.json"
    cfg = load_agent_system_config(config_file=cfg_file)
    assert len(cfg.agents) == 8
    assert AgentRole.MARKET_DATA.value in cfg.agents
    assert AgentRole.FINAL_DECISION.value in cfg.agents

    # Modify an agent configuration
    cfg.agents[AgentRole.TECHNICAL.value].temperature = 0.42
    save_agent_system_config(cfg, config_file=cfg_file)

    reloaded = load_agent_system_config(config_file=cfg_file)
    assert reloaded.agents[AgentRole.TECHNICAL.value].temperature == 0.42

    # Reset
    default_cfg = MultiAgentSystemConfig(
        version="v6.18.0",
        agents={r: SingleAgentConfig(**c) for r, c in DEFAULT_AGENTS_CONFIG.items()},
    )
    save_agent_system_config(default_cfg, config_file=cfg_file)


def test_ai_provider_registry_and_fallback():
    # Mock provider completion
    mock_provider = MagicMock()
    mock_provider.generate.return_value = AICompletionResult(
        ok=True,
        text="{\"signal\": \"HOLD\"}",
        provider="mock",
        model="mock-model",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        latency_ms=120.0,
    )
    AIProviderRegistry.register_provider("mock", mock_provider)

    res = AIProviderRegistry.generate_with_fallback(
        primary_provider="mock",
        primary_model="mock-model",
        messages=[{"role": "user", "content": "Analyze data"}],
    )
    assert res.ok is True
    assert res.text == "{\"signal\": \"HOLD\"}"
    assert res.provider == "mock"

    # Test fallback
    mock_fail = MagicMock()
    mock_fail.generate.return_value = AICompletionResult(
        ok=False,
        provider="fail_prov",
        model="fail-model",
        text="",
        error_code="PROVIDER_ERROR",
        error_message="Provider down",
    )
    AIProviderRegistry.register_provider("fail_prov", mock_fail)

    fallback_res = AIProviderRegistry.generate_with_fallback(
        primary_provider="fail_prov",
        primary_model="fail-model",
        messages=[{"role": "user", "content": "Analyze data"}],
        fallback_provider="mock",
        fallback_model="mock-model",
    )
    assert fallback_res.ok is True
    assert fallback_res.provider == "mock"
    assert fallback_res.fallback_used is True


def test_agent_nodes_and_safety_gate():
    state: AnalysisState = {
        "analysis_id": "test-analysis-1",
        "symbol": "NIFTY",
        "direction": "LONG",
        "confidence": 0.6,
        "entry_range": [25000.0, 25050.0],
        "invalidation_price": 24900.0,
        "targets": [25200.0],
        "features": {"rsi_14": 55.0, "atr_14": 120.0, "close": 25020.0},
        "forecast": {"directional_bias": "UP", "win_prob": 0.54, "model_id": "test_quant_v1"},
        "macro_factors": {"vix": 13.5, "usdinr": 83.9},
        "regime": "LOW_VOLATILITY_UPTREND",
        "data_verified": False,
        "agent_outputs": {},
    }

    # Run specialist nodes
    m_out = market_data_analyst_node(state)
    assert "market_data_analyst" in m_out["agent_outputs"]
    assert m_out["agent_outputs"]["market_data_analyst"]["status"] == "SUCCESS"

    t_out = technical_analyst_node(state)
    assert "technical_analyst" in t_out["agent_outputs"]

    g_out = global_macro_analyst_node(state)
    assert "global_macro_analyst" in g_out["agent_outputs"]

    n_out = news_event_analyst_node(state)
    assert "news_event_analyst" in n_out["agent_outputs"]

    o_out = options_analyst_node(state)
    assert "options_analyst" in o_out["agent_outputs"]

    q_out = quant_forecast_analyst_node(state)
    assert "quant_forecast_analyst" in q_out["agent_outputs"]

    r_out = risk_uncertainty_analyst_node(state)
    assert "risk_uncertainty_analyst" in r_out["agent_outputs"]

    # Final decision node when data is UNVERIFIED must enforce NO_TRADE
    full_outputs = {
        **m_out["agent_outputs"],
        **t_out["agent_outputs"],
        **g_out["agent_outputs"],
        **n_out["agent_outputs"],
        **o_out["agent_outputs"],
        **q_out["agent_outputs"],
        **r_out["agent_outputs"],
    }
    merged_state = dict(state)
    merged_state["agent_outputs"] = full_outputs
    dec_out = final_decision_agent_node(merged_state)

    assert "final_decision_agent" in dec_out["agent_outputs"]
    final_output = dec_out["agent_outputs"]["final_decision_agent"]
    assert any("NO_TRADE" in f for f in final_output["findings"])
    assert "REAL_MARKET_DATA_UNVERIFIED" in dec_out["report"]["reason_codes"]
    assert dec_out["report"]["decision"] == "NO_TRADE"


def test_quantitative_model_comparison_walk_forward():
    from tests.test_forecasting import alternating, series
    dataset = series(alternating())

    # Run multi-model comparison
    comparison = compare_quantitative_models(
        feature_dataset=dataset,
        config=WalkForwardConfig(
            initial_train_size=9,
            validation_size=5,
            test_size=4,
            step_size=4,
            embargo_bars=1,
            seed=42,
        ),
    )

    assert comparison["ok"] is True
    assert comparison["dataset_id"] == dataset["dataset_id"]
    assert comparison["leakage_prevention"]["lookahead_leakage_detected"] is False
    assert comparison["leakage_prevention"]["chronological_expanding_splits"] is True

    model_metrics = comparison["model_metrics"]
    assert "majority_class" in model_metrics
    assert "last_return_sign" in model_metrics
    assert "logistic_regression" in model_metrics

    for m_name, metrics in model_metrics.items():
        assert metrics["folds_evaluated"] > 0
        assert metrics["mean_accuracy"] is not None
        assert 0.0 <= metrics["mean_accuracy"] <= 1.0

    # Verify baseline comparison exists
    assert "baseline_comparison" in comparison
    assert comparison["baseline_comparison"]["baseline_model"] == "majority_class"
    assert "recommendation" in comparison
    assert comparison["forecast_ready"] is False
    assert comparison["real_market_data_verified"] is False
