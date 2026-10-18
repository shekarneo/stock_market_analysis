"""Milestone M43: Master System Audit, CLI Synthesis & Platform Certification Tests.

Verifies:
1. Operational CLI entrypoints (`health`, `audit`, `drift`, `simulation`, `multi-asset`, `attribution`, `kill-switch`).
2. Global enforcement of the 5 Financial Safety Invariants across all system layers.
3. Complete 8-Gate Paper Readiness verification with 0 active blockers.
4. Dataset provenance, candle count integrity, and serialization artifacts.
5. End-to-end multi-asset concurrent execution and factor attribution consistency.
6. Permanent live capital routing lock (`STRICT_NO_GO_LOCKED`).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from app.cli import build_parser, main
from app.config.store import current_config, ensure_seed
from app.db import get_session_factory
from app.execution.m42_multi_asset_execution import run_multi_asset_paper_simulation
from app.forecasting.m41_factor_attribution import run_m41_factor_attribution_benchmark
from app.research.paper_readiness_audit import audit_paper_trading_readiness
from app.risk.ledger import read_kill_switch, set_kill_switch
from app.settings import REPO_ROOT, get_settings


def test_m43_cli_parser_build():
    """Verify CLI parser builds cleanly with all 7 subcommands."""
    parser = build_parser()
    assert parser.prog == "imm-cli"
    subparsers_actions = [
        action for action in parser._actions if action.dest == "command"
    ]
    assert len(subparsers_actions) == 1
    choices = subparsers_actions[0].choices
    expected_cmds = {"audit", "drift", "simulation", "multi-asset", "attribution", "kill-switch", "health"}
    assert expected_cmds.issubset(set(choices.keys()))


def test_m43_cli_health_and_json(capsys):
    """Verify health command runs and outputs valid JSON."""
    exit_code = main(["health", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "ok"
    assert data["database"] is True
    assert data["safety_invariants"]["live_broker_routing_enabled"] is False
    assert data["safety_invariants"]["live_approved"] is False


def test_m43_cli_audit_command(capsys):
    """Verify 8-Gate audit command executes via CLI with JSON output."""
    exit_code = main(["audit", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["overall_readiness"] == "READY_FOR_PAPER_SIMULATION"
    assert report["live_trading_verdict"] == "STRICT_NO_GO_LOCKED"
    assert report["total_gates_evaluated"] == 8
    assert report["failed_gates"] == 0
    assert len(report["active_blockers"]) == 0


def test_m43_cli_multi_asset_command(capsys):
    """Verify multi-asset execution simulation command executes via CLI."""
    exit_code = main(["multi-asset", "--capital", "1000000.0"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "V6 MULTI-ASSET PAPER EXECUTION SIMULATION" in captured.out
    assert "Portfolio Profit Factor" in captured.out
    assert "NIFTY" in captured.out
    assert "BANKNIFTY" in captured.out


def test_m43_cli_attribution_command(capsys):
    """Verify factor attribution command executes via CLI with JSON."""
    exit_code = main(["attribution", "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["milestone"] == "M41"
    assert "cross_asset_divergence" in data
    assert data["cross_asset_divergence"]["cosine_similarity"] < 0.50


def test_m43_cli_kill_switch_query(capsys):
    """Verify kill switch status command runs cleanly."""
    exit_code = main(["kill-switch", "status"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Kill Switch Status:" in captured.out


def test_m43_hard_financial_safety_invariants_lock(db):
    """Strict verification: All 5 safety invariants must be False across all subsystems."""
    session = get_session_factory()()
    try:
        ensure_seed(session, get_settings())
        cfg = current_config(session)
        assert cfg.runtime.live_trading_enabled is False
        assert cfg.runtime.unattended_orders is False
        assert get_settings().live_order_server_flag is False

        audit_rep = audit_paper_trading_readiness(session)
        for flag_name, val in audit_rep.safety_invariants.items():
            assert val is False, f"Safety invariant {flag_name} was True in audit report!"

        sim_rep = run_multi_asset_paper_simulation(initial_capital_inr=1_000_000.0)
        for flag_name, val in sim_rep.safety_invariants.items():
            assert val is False, f"Safety invariant {flag_name} was True in multi-asset simulation!"

        attr_rep = run_m41_factor_attribution_benchmark()
        for flag_name, val in attr_rep.safety_invariants.items():
            assert val is False, f"Safety invariant {flag_name} was True in factor attribution!"
    finally:
        session.close()


def test_m43_all_eight_gates_certification(db):
    """Verify all 8 gates pass without blockers and live trading remains STRICT_NO_GO_LOCKED."""
    session = get_session_factory()()
    try:
        ensure_seed(session, get_settings())
        report = audit_paper_trading_readiness(session)
        assert report.overall_readiness == "READY_FOR_PAPER_SIMULATION"
        assert report.live_trading_verdict == "STRICT_NO_GO_LOCKED"
        assert len(report.active_blockers) == 0

        expected_gates = [
            "GATE_1_SAFETY_INVARIANTS",
            "GATE_2_DATA_PROVENANCE",
            "GATE_3_COST_ABSORPTION",
            "GATE_4_PORTFOLIO_RISK",
            "GATE_5_DRIFT_MONITORING",
            "GATE_6_MULTI_AGENT_CONSENSUS",
            "GATE_7_PAPER_ACCOUNTING",
            "GATE_8_OPS_CONTROLS",
        ]
        for gate_id in expected_gates:
            assert gate_id in report.gates
            gate = report.gates[gate_id]
            assert gate.status == "PASSED", f"Gate {gate_id} failed: {gate.metrics}"
    finally:
        session.close()


def test_m43_dataset_provenance_and_artifact_integrity():
    """Verify that all core benchmark datasets and milestone artifacts exist and have valid structure."""
    datasets_dir = REPO_ROOT / "var" / "datasets"

    nifty_path = datasets_dir / "derived_nifty_15m_m23_bc7d31bceebf13a3.json"
    assert nifty_path.exists(), "NIFTY 15m dataset missing"
    with open(nifty_path, "r") as f:
        n_data = json.load(f)
    assert len(n_data["candles"]) == 6227

    bank_path = datasets_dir / "derived_banknifty_15m_m40.json"
    assert bank_path.exists(), "BANK NIFTY 15m dataset missing"
    with open(bank_path, "r") as f:
        b_data = json.load(f)
    assert len(b_data["candles"]) == 6227
    assert b_data["symbol"] == "NSE-BANKNIFTY"
    assert b_data["candle_count"] == 6227

    m40_bench = datasets_dir / "m40_multi_asset_benchmark.json"
    assert m40_bench.exists(), "M40 benchmark artifact missing"

    m41_attr = datasets_dir / "m41_factor_attribution_results.json"
    assert m41_attr.exists(), "M41 factor attribution artifact missing"

    m42_sim = datasets_dir / "m42_multi_asset_simulation_results.json"
    assert m42_sim.exists(), "M42 multi-asset simulation artifact missing"


def _make_mock_http_caller(status_code: int, body: dict):
    from app.integrations.http import HttpResult

    class _MockHttpCaller:
        def __init__(self, sc: int, b: dict) -> None:
            self._sc = sc
            self._b = b
            self.last_request: dict = {}

        def send(self, method: str, url: str, *, headers=None, json_body=None, timeout=None) -> HttpResult:
            self.last_request = {"method": method, "url": url, "headers": headers, "json_body": json_body, "timeout": timeout}
            return HttpResult(status_code=self._sc, body=self._b, text=json.dumps(self._b))

    return _MockHttpCaller(status_code, body)


def test_ai_provider_negative_cases_and_reasoning_payload():
    """Verify OpenAI o1/o3 payload semantics, malformed JSON rejection, truncation rejection, and Gemini safety block detection."""
    from app.analysis.ai_providers import GeminiModelProvider, OpenAIModelProvider

    # 1. OpenAI o1 reasoning model uses max_completion_tokens and omits temperature
    caller_o1 = _make_mock_http_caller(
        status_code=200,
        body={
            "choices": [{"finish_reason": "stop", "message": {"content": '{"directional_bias": "NEUTRAL", "findings": ["o1 ok"]}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        },
    )
    provider_o1 = OpenAIModelProvider(caller=caller_o1, api_key="sk-test-o1")
    res_o1 = provider_o1.generate(messages=[{"role": "user", "content": "test"}], model="o1-mini", temperature=0.7, max_tokens=500)
    assert res_o1.ok is True
    sent_payload = caller_o1.last_request["json_body"]
    assert "max_completion_tokens" in sent_payload
    assert "max_tokens" not in sent_payload
    assert "temperature" not in sent_payload

    # 2. OpenAI malformed JSON fails closed with MALFORMED_OUTPUT
    caller_bad_json = _make_mock_http_caller(
        status_code=200,
        body={
            "choices": [{"finish_reason": "stop", "message": {"content": "not valid json {"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )
    res_bad = OpenAIModelProvider(caller=caller_bad_json, api_key="sk-test").generate(
        messages=[{"role": "user", "content": "test"}], model="gpt-4o-mini"
    )
    assert res_bad.ok is False
    assert res_bad.error_code == "MALFORMED_OUTPUT"

    # 3. OpenAI truncated output fails closed with TRUNCATED_OUTPUT
    caller_trunc = _make_mock_http_caller(
        status_code=200,
        body={
            "choices": [{"finish_reason": "length", "message": {"content": '{"findings": ["cut'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 100, "total_tokens": 110},
        },
    )
    res_trunc = OpenAIModelProvider(caller=caller_trunc, api_key="sk-test").generate(
        messages=[{"role": "user", "content": "test"}], model="gpt-4o-mini"
    )
    assert res_trunc.ok is False
    assert res_trunc.error_code == "TRUNCATED_OUTPUT"

    # 4. Gemini safety block fails closed with SAFETY_BLOCKED
    caller_safety = _make_mock_http_caller(
        status_code=200,
        body={
            "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 0, "totalTokenCount": 12},
        },
    )
    res_safety = GeminiModelProvider(caller=caller_safety, api_key="AIzaSyTest").generate(
        messages=[{"role": "user", "content": "test"}], model="gemini-1.5-pro"
    )
    assert res_safety.ok is False
    assert res_safety.error_code == "SAFETY_BLOCKED"


def test_specialist_agents_truthful_execution_mode_and_llm_routing(monkeypatch):
    """Verify specialist agents distinguish DETERMINISTIC_RULE, LLM, LLM_FALLBACK, and DETERMINISTIC_FALLBACK_ON_LLM_ERROR."""
    from app.analysis.agent_config import DEFAULT_AGENTS_CONFIG, MultiAgentSystemConfig, SingleAgentConfig
    from app.analysis.agent_nodes import market_data_analyst_node, technical_analyst_node
    from app.analysis.ai_providers import AIProviderRegistry, GeminiModelProvider, OpenAIModelProvider

    canonical_cfg = MultiAgentSystemConfig(
        version="v6.18.0",
        agents={r: SingleAgentConfig(**c) for r, c in DEFAULT_AGENTS_CONFIG.items()},
    )
    monkeypatch.setattr("app.analysis.agent_nodes.load_agent_system_config", lambda: canonical_cfg)

    AIProviderRegistry._providers.clear()
    base_state = {
        "quality": {"status": "PARTIAL"},
        "accepted": [{"instrument": "NIFTY", "provenance": "PROVIDER"}],
        "rejected": [],
        "evidence": [
            {"evidence_id": "e1", "category": "INDIAN_MARKET", "last_price": 23000.0, "verification_status": "UNVERIFIED"},
            {"evidence_id": "e2", "category": "INDIAN_MARKET", "last_price": 23100.0, "verification_status": "UNVERIFIED"},
        ],
        "missing": [],
        "agent_outputs": {},
    }

    # 1. Purely deterministic offline mode: never claims LLM provider/model success
    det_res = market_data_analyst_node(base_state)
    det_out = det_res["agent_outputs"]["market_data_analyst"]
    assert det_out["execution_mode"] == "DETERMINISTIC_RULE"
    assert det_out["llm_attempted"] is False
    assert det_out["llm_succeeded"] is False
    assert det_out["provider"] == "deterministic_rule"
    assert det_out["model"] == "v6_rule_engine"
    assert det_out["configured_provider"] is not None

    # 2. LLM execution enabled with primary OpenAI failure and Gemini fallback success
    fail_openai = OpenAIModelProvider(
        caller=_make_mock_http_caller(status_code=429, body={"error": {"message": "Quota exceeded", "code": "insufficient_quota"}}),
        api_key="sk-test",
    )
    ok_gemini = GeminiModelProvider(
        caller=_make_mock_http_caller(
            status_code=200,
            body={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": '{"directional_bias": "BULLISH", "confidence": 0.74, "findings": ["Gemini fallback synthesized trend."], "limitations": []}'
                                }
                            ]
                        },
                    }
                ],
                "usageMetadata": {"promptTokenCount": 45, "candidatesTokenCount": 20, "totalTokenCount": 65},
            },
        ),
        api_key="AIzaSyTest",
    )
    AIProviderRegistry.register_provider("openai", fail_openai)
    AIProviderRegistry.register_provider("gemini", ok_gemini)
    AIProviderRegistry.register_provider("google", ok_gemini)

    try:
        fb_res = market_data_analyst_node(base_state)
        fb_out = fb_res["agent_outputs"]["market_data_analyst"]
        assert fb_out["execution_mode"] == "LLM_FALLBACK"
        assert fb_out["llm_attempted"] is True
        assert fb_out["llm_succeeded"] is True
        assert fb_out["fallback_used"] is True
        assert fb_out["status"] == "FALLBACK_USED"
        assert fb_out["provider"] == "gemini"
        assert fb_out["token_usage"]["total_tokens"] == 65
        assert any("Gemini fallback synthesized trend." in f for f in fb_out["findings"])

        # 3. Direct primary Gemini LLM success on Technical Analyst
        tech_res = technical_analyst_node(base_state)
        tech_out = tech_res["agent_outputs"]["technical_analyst"]
        assert tech_out["execution_mode"] == "LLM"
        assert tech_out["llm_attempted"] is True
        assert tech_out["llm_succeeded"] is True
        assert tech_out["fallback_used"] is False
        assert tech_out["provider"] == "gemini"

        # 4. Both primary and fallback fail -> DETERMINISTIC_FALLBACK_ON_LLM_ERROR (never reported as LLM success)
        fail_gemini = GeminiModelProvider(
            caller=_make_mock_http_caller(status_code=503, body={"error": {"message": "Service unavailable", "code": "UNAVAILABLE"}}),
            api_key="AIzaSyTest",
        )
        AIProviderRegistry.register_provider("gemini", fail_gemini)
        AIProviderRegistry.register_provider("google", fail_gemini)

        err_res = market_data_analyst_node(base_state)
        err_out = err_res["agent_outputs"]["market_data_analyst"]
        assert err_out["execution_mode"] == "DETERMINISTIC_FALLBACK_ON_LLM_ERROR"
        assert err_out["llm_attempted"] is True
        assert err_out["llm_succeeded"] is False
        assert err_out["status"] == "PARTIAL"
        assert err_out["provider"] == "deterministic_fallback"
        assert len(err_out["errors"]) >= 1
    finally:
        AIProviderRegistry._providers.clear()


def test_agent_config_legacy_frontend_keys_normalized():
    """Verify SingleAgentConfig accepts both canonical (model, max_tokens, fallback_model) and legacy frontend aliases."""
    from app.analysis.agent_config import SingleAgentConfig

    cfg = SingleAgentConfig(
        role="market_data_analyst",
        display_name="Market Data Analyst",
        enabled=True,
        provider="openai",
        model_id="gpt-4o",
        temperature=0.2,
        max_output_tokens=1200,
        fallback_provider="gemini",
        fallback_model_id="gemini-1.5-flash",
    )
    assert cfg.model == "gpt-4o"
    assert cfg.max_tokens == 1200
    assert cfg.fallback_model == "gemini-1.5-flash"


def test_leak_free_registry_and_historical_feature_provenance(db):
    """Verify var/registry/registry.json passes checksum verification, uses leak-free out-of-sample split, and resolves live DB candles when available."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from app.domain.tables import MarketCandle
    from app.forecasting.live_forecast import compute_live_forecast_for_instrument
    from app.registry.store import registry_store

    doc = registry_store().read()
    exp = list(doc["experiments"].values())[0]
    lr_outcomes = exp["model_outcomes"]["logistic_regression"]
    # Verify validation and test splits have realistic out-of-sample counts (473 val, 474 test) rather than synthetic 2/5 rows
    assert lr_outcomes["validation"]["observations"] == 473
    assert lr_outcomes["test"]["observations"] == 474
    assert 0.45 <= lr_outcomes["test"]["accuracy"]["value"] <= 0.70

    # 1. Verify trailing feature resolution preserves actual historical candle bar_end when no newer DB candles exist
    f_nifty = compute_live_forecast_for_instrument("NIFTY", {"instrument": "NIFTY", "last_price": 23146.15})
    assert f_nifty["status"] == "ACTIVE"
    assert f_nifty["feature_source"] == "HISTORICAL_CANDLE_DATASET"
    assert f_nifty["is_live_feature_vector"] is False
    assert f_nifty["feature_bar_end"] == "2026-10-14T15:30:00+05:30"

    # 2. Verify live 15m candles in MarketCandle take precedence and set is_live_feature_vector=True
    session = get_session_factory()()
    try:
        ist = timezone(timedelta(hours=5, minutes=30))
        base_dt = datetime(2026, 10, 16, 9, 15, tzinfo=ist)
        for i in range(12):
            bar_ts = base_dt + timedelta(minutes=15 * i)
            session.add(
                MarketCandle(
                    symbol="NSE-NIFTY",
                    interval="15minute",
                    timestamp=bar_ts,
                    open=Decimal(str(23100.0 + i * 5)),
                    high=Decimal(str(23115.0 + i * 5)),
                    low=Decimal(str(23090.0 + i * 5)),
                    close=Decimal(str(23108.0 + i * 5)),
                    volume=Decimal("100000"),
                    session_type="REGULAR",
                    is_complete=True,
                )
            )
        session.commit()

        f_live = compute_live_forecast_for_instrument("NIFTY", {"instrument": "NIFTY", "last_price": 23165.0})
        assert f_live["status"] == "ACTIVE"
        assert f_live["feature_source"] == "LIVE_DB_MARKET_CANDLES"
        assert f_live["is_live_feature_vector"] is True
        assert "2026-10-16" in f_live["feature_bar_end"]
    finally:
        session.close()


def test_experimental_paper_risk_limits_enforced(db):
    """Verify _position_gate enforces max_open_positions and cumulative daily_loss_fraction lockout."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from app.config.loader import load_defaults
    from app.domain.tables import PaperAccountEvent
    from app.risk.gates import _position_gate

    session = get_session_factory()()
    try:
        # Clean any prior test simulation events
        session.query(PaperAccountEvent).filter(PaperAccountEvent.event_id.like("sim-%-risk-limit-test-%")).delete(synchronize_session=False)
        session.commit()

        risk_cfg = load_defaults(REPO_ROOT / "config" / "defaults.yaml").risk.model_copy(
            update={
                "risk_capital_inr": Decimal("100000.00"),
                "max_risk_fraction_per_trade": 0.02,
                "daily_loss_fraction": 0.01,  # Max daily loss = 1,000 INR
                "max_open_positions": 1,
            }
        )
        intent = {"session_date": "2026-10-18"}

        # 1. Insert 1 open position (sim-fill without sim-exit) -> should VETO with MAX_OPEN_POSITIONS_EXCEEDED
        open_ev = PaperAccountEvent(
            event_id="sim-fill-risk-limit-test-1",
            event_type="FILL",
            occurred_at=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            intent_id="risk-limit-test-1",
            source="SIMULATION",
            body_hash="h1",
            opening_cash_inr=Decimal("100000.00"),
            quantity=Decimal("65"),
            price=Decimal("100.00"),
            charges_inr=Decimal("50.00"),
            payload={"intent_id": "risk-limit-test-1", "side": "BUY"},
            effect={},
            ledger_applied=False,
            broker_confirmed=False,
        )
        session.add(open_ev)
        session.commit()

        reasons_open: list[str] = []
        gate_open = _position_gate(intent, session, risk_cfg, reasons_open, apply=True, is_experimental=True)
        assert gate_open["state"] == "VETO"
        assert "MAX_OPEN_POSITIONS_EXCEEDED" in reasons_open

        # 2. Close that position with a realized loss of -1,250 INR (exceeding 1,000 INR daily loss limit) -> should VETO with DAILY_LOSS_LOCKOUT
        exit_ev = PaperAccountEvent(
            event_id="sim-exit-risk-limit-test-1",
            event_type="FILL",
            occurred_at=datetime(2026, 10, 18, 10, 15, tzinfo=timezone.utc),
            intent_id="risk-limit-test-1",
            source="SIMULATION",
            body_hash="h1",
            opening_cash_inr=Decimal("100000.00"),
            quantity=Decimal("65"),
            price=Decimal("80.00"),
            charges_inr=Decimal("50.00"),
            payload={
                "intent_id": "risk-limit-test-1",
                "side": "SELL",
                "realized_pnl_inr": -1250.0,
                "net_realized_pnl_inr": -1250.0,
            },
            effect={},
            ledger_applied=False,
            broker_confirmed=False,
        )
        session.add(exit_ev)
        session.commit()

        reasons_loss: list[str] = []
        gate_loss = _position_gate(intent, session, risk_cfg, reasons_loss, apply=True, is_experimental=True)
        assert gate_loss["state"] == "VETO"
        assert "DAILY_LOSS_LOCKOUT" in reasons_loss
    finally:
        session.query(PaperAccountEvent).filter(PaperAccountEvent.event_id.like("sim-%-risk-limit-test-%")).delete(synchronize_session=False)
        session.commit()
        session.close()

