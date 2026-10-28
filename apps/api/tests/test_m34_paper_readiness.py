"""Milestone M34 Test Suite: Paper-Trading Readiness Review & Formal Gate Audit.

Verifies:
1. Systematic evaluation of all 8 Readiness Gates across safety, data, alpha, risk, observability, and operations.
2. "READY_FOR_PAPER_SIMULATION" only when research shows an edge after costs; otherwise BLOCKED.
3. Absolute hardcoded locking of Live Trading: "STRICT_NO_GO_LOCKED".
4. Immediate failure detection if any safety invariant is compromised.
5. Automated persistence of m34_paper_readiness_audit.json artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.db import get_session_factory
from app.research.paper_readiness_audit import (
    PaperReadinessReport,
    audit_paper_trading_readiness,
)
from app.settings import REPO_ROOT


@pytest.mark.usefixtures("validated_edge")
def test_paper_readiness_audit_all_gates_pass(db):
    """Verify that all 8 readiness gates pass under current engineering implementation."""
    session = get_session_factory()()
    try:
        report = audit_paper_trading_readiness(session)

        assert report is not None
        assert isinstance(report, PaperReadinessReport)
        assert report.total_gates_evaluated == 8
        assert report.failed_gates == 0
        assert len(report.active_blockers) == 0
        assert report.overall_readiness == "READY_FOR_PAPER_SIMULATION"

        # Verify specific critical gates
        assert report.gates["GATE_1_SAFETY_INVARIANTS"].status == "PASSED"
        assert report.gates["GATE_2_DATA_PROVENANCE"].status == "PASSED"
        assert report.gates["GATE_3_COST_ABSORPTION"].status == "PASSED"
        assert report.gates["GATE_4_PORTFOLIO_RISK"].status == "PASSED"
        assert report.gates["GATE_5_DRIFT_MONITORING"].status == "PASSED"
        assert report.gates["GATE_6_MULTI_AGENT_CONSENSUS"].status == "PASSED"
        assert report.gates["GATE_7_PAPER_ACCOUNTING"].status == "PASSED"
        assert report.gates["GATE_8_OPS_CONTROLS"].status == "PASSED"
    finally:
        session.close()


def test_no_validated_edge_blocks_paper_readiness(db, monkeypatch, tmp_path):
    """Without research showing an edge after costs, readiness is BLOCKED, never 8/8."""
    from app.research import paper_readiness_audit as pra

    datasets = tmp_path / "datasets"
    datasets.mkdir()
    (datasets / "research_daily_report.json").write_text(json.dumps({"summary": {"direction_edge_supported": False}}))
    (datasets / "realistic_forecast.json").write_text(json.dumps({"direction_next_session": {"status": "NO_RELIABLE_EDGE"}}))
    (datasets / "agent_backtest.json").write_text(json.dumps(
        {"agents": {"technical_analyst": {"verdict": {"edge_supported": False}}}}))
    monkeypatch.setattr(pra, "EVIDENCE_DIR", datasets)
    evidence = pra.validated_net_edge()
    assert evidence == {"supported": False, "sources": {"daily_direction_research": False,
                                                       "next_session_forecast": False, "technical_agent_replay": False}}
    report = audit_paper_trading_readiness(None)
    assert report.gates["GATE_3_COST_ABSORPTION"].status == "FAILED"
    assert "NO_VALIDATED_NET_EDGE_AFTER_COSTS" in report.active_blockers
    assert report.overall_readiness == "BLOCKED" and report.passed_gates == 7
    # Research never run: unknown, which is not evidence either
    for f in datasets.iterdir():
        f.unlink()
    assert pra.validated_net_edge()["supported"] is False
    assert pra.validated_net_edge()["sources"]["technical_agent_replay"] is None


def test_live_trading_verdict_strictly_locked(db):
    """Verify that live trading verdict remains permanently locked to STRICT_NO_GO_LOCKED."""
    session = get_session_factory()()
    try:
        report = audit_paper_trading_readiness(session)
        assert report.live_trading_verdict == "STRICT_NO_GO_LOCKED"
        assert report.forecast_ready is False
        assert report.real_market_data_verified is False
        assert report.paper_approved is False
        assert report.live_approved is False
        assert report.live_broker_routing_enabled is False

        # Verify internal dictionary
        for flag, val in report.safety_invariants.items():
            assert val is False, f"Safety invariant {flag} must be False"
    finally:
        session.close()


def test_persisted_audit_json_artifact(db):
    """Verify that audit report is written to var/datasets/m34_paper_readiness_audit.json."""
    session = get_session_factory()()
    try:
        report = audit_paper_trading_readiness(session)
        artifact_path = REPO_ROOT / "var/datasets/m34_paper_readiness_audit.json"
        assert artifact_path.exists()

        with open(artifact_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["overall_readiness"] == report.overall_readiness
        assert data["live_trading_verdict"] == "STRICT_NO_GO_LOCKED"
        assert data["total_gates_evaluated"] == 8
        assert "gates" in data
        assert len(data["gates"]) == 8
    finally:
        session.close()
