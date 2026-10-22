"""Unit tests for V6 System Command Line Interface (CLI).

Verifies:
1. `health` command output in text and JSON formats.
2. `audit` command 8-Gate Paper Readiness review execution and exit codes.
3. `drift` command statistical feature distribution drift report.
4. `simulation` command statutory Indian market friction simulation.
5. `kill-switch` status, trip, and clear operations with database persistence.
"""

from __future__ import annotations

import io
import json
import sys
import pytest

from app.cli import main
from app.db import get_session_factory
from app.domain.tables import OpsState
from app.risk.ledger import set_kill_switch


def _run_cli(args: list[str]) -> tuple[int, str]:
    """Capture stdout and return (exit_code, captured_output)."""
    old_stdout = sys.stdout
    buffer = io.StringIO()
    try:
        sys.stdout = buffer
        code = main(args)
    finally:
        sys.stdout = old_stdout
    return code, buffer.getvalue()


def test_cli_health_text_and_json(db):
    """Verify health command outputs valid database status and invariant flags."""
    # Text format
    code_text, out_text = _run_cli(["health"])
    assert code_text == 0
    assert "OPERATIONAL HEALTH CHECK" in out_text
    assert "Status              : OK" in out_text
    assert "Database (Postgres) : CONNECTED" in out_text
    assert "Safety Invariants   : ALL 5 FLAGS STRICTLY FALSE" in out_text

    # JSON format
    code_json, out_json = _run_cli(["health", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["status"] == "ok"
    assert data["database"] is True
    assert data["runtime_mode"] == "PAPER"
    assert data["kill_switch"] is False
    assert data["safety_invariants"]["live_broker_routing_enabled"] is False


def test_cli_audit_command(db):
    """Verify audit command evaluates all 8 readiness gates and returns 0."""
    code_text, out_text = _run_cli(["audit"])
    assert code_text == 0
    assert "8-GATE PAPER READINESS AUDIT" in out_text
    assert "READY_FOR_PAPER_SIMULATION" in out_text
    assert "STRICT_NO_GO_LOCKED" in out_text
    assert "Gates Evaluated / Passed  : 8 / 8" in out_text
    assert "[PASSED] GATE_1_SAFETY_INVARIANTS" in out_text
    assert "[PASSED] GATE_8_OPS_CONTROLS" in out_text

    code_json, out_json = _run_cli(["audit", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["overall_readiness"] == "READY_FOR_PAPER_SIMULATION"
    assert data["total_gates_evaluated"] == 8
    assert data["failed_gates"] == 0


def test_cli_drift_command():
    """Verify drift command computes feature metrics and handles JSON format."""
    code_text, out_text = _run_cli(["drift"])
    assert code_text == 0
    assert "STATISTICAL FEATURE DRIFT AUDIT" in out_text
    assert "Maximum Feature PSI       : 0.2861" in out_text
    assert "returns" in out_text
    assert "atr" in out_text

    code_json, out_json = _run_cli(["drift", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["overall_status"] == "CRITICAL_DRIFT"
    assert "atr" in data["feature_metrics"]
    assert data["feature_metrics"]["atr"]["psi"] > 0.25


def test_cli_simulation_command():
    """Verify simulation command runs statutory friction calculations."""
    code_text, out_text = _run_cli(["simulation", "--capital", "1000000", "--product", "NRML"])
    assert code_text == 0
    assert "V6 PAPER EXECUTION SIMULATION (NRML PRODUCT)" in out_text
    assert "Initial Capital           : Rs 1,000,000.00" in out_text
    assert "Final Capital" in out_text
    assert "Net Return" in out_text
    assert "STT Charges" in out_text
    assert "Profit Factor" in out_text

    code_json, out_json = _run_cli(["simulation", "--capital", "1000000", "--product", "NRML", "--json"])
    assert code_json == 0
    data = json.loads(out_json)
    assert data["symbol"] == "NIFTY"
    assert data["total_trades"] >= 0
    # The report is an accounting record; no particular profit is required
    assert isinstance(data["net_pnl_inr"], (int, float))


def test_cli_kill_switch_lifecycle(db):
    """Verify kill switch status, trip, and clear commands."""
    # 1. Status query
    code, out = _run_cli(["kill-switch", "status"])
    assert code == 0
    assert "Kill Switch Status:" in out

    # 2. Trip kill switch
    code_trip, out_trip = _run_cli(["kill-switch", "trip", "--reason", "TEST_MANUAL_LOCKOUT"])
    assert code_trip == 0
    assert "Kill switch TRIPPED: TEST_MANUAL_LOCKOUT" in out_trip

    code_stat, out_stat = _run_cli(["kill-switch", "status"])
    assert "TRIPPED (HALTED)" in out_stat
    assert "TEST_MANUAL_LOCKOUT" in out_stat

    # Verify DB state
    session = get_session_factory()()
    try:
        ops = session.get(OpsState, 1)
        assert ops is not None and ops.kill_switch is True
    finally:
        session.close()

    # 3. Clear kill switch
    code_clear, out_clear = _run_cli(["kill-switch", "clear", "--reason", "TEST_CLEARANCE"])
    assert code_clear == 0
    assert "Kill switch CLEARED: TEST_CLEARANCE" in out_clear

    session = get_session_factory()()
    try:
        ops = session.get(OpsState, 1)
        assert ops is not None and ops.kill_switch is False
    finally:
        session.close()
