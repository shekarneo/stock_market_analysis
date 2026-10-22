"""V6 Indian Market AI Trading System — Command Line Interface (CLI).

Provides unified operational, quantitative, and administrative control commands:
1. `audit`: Runs the formal 8-Gate Paper Readiness Audit and reports gate status.
2. `drift`: Runs statistical feature drift detection (PSI / KS) on benchmark datasets.
3. `simulation`: Executes the realistic Indian statutory friction simulation on swing data.
4. `multi-asset`: Executes multi-asset concurrent paper simulation across NIFTY & BANK NIFTY.
5. `attribution`: Executes statistical factor attribution & feature explainability benchmark.
6. `kill-switch`: Queries, trips, or clears the emergency operational kill switch.
7. `health`: Checks database connectivity, seed configuration, and safety invariant flags.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.store import current_config, ensure_seed
from app.db import get_engine, get_session_factory
from app.domain.tables import OpsState
from app.execution.m42_multi_asset_execution import run_multi_asset_paper_simulation
from app.execution.paper_simulation_harness import run_nifty_swing_paper_simulation
from app.forecasting.m41_factor_attribution import run_m41_factor_attribution_benchmark
from app.monitoring.drift_detector import run_nifty_benchmark_drift_audit
from app.research.paper_readiness_audit import audit_paper_trading_readiness
from app.risk.ledger import read_kill_switch, set_kill_switch
from app.settings import REPO_ROOT, get_settings


def cmd_audit(args: argparse.Namespace) -> int:
    """Run formal 8-Gate Paper-Trading Readiness Review."""
    session = get_session_factory()()
    try:
        report = audit_paper_trading_readiness(session)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
            return 0

        print("\n========================================================")
        print("     V6 SYSTEM — 8-GATE PAPER READINESS AUDIT")
        print("========================================================")
        print(f"Overall Readiness Verdict : {report.overall_readiness}")
        print(f"Live Capital Verdict      : {report.live_trading_verdict}")
        print(f"Gates Evaluated / Passed  : {report.total_gates_evaluated - report.failed_gates} / {report.total_gates_evaluated}")
        print(f"Active Blockers Count     : {len(report.active_blockers)}")
        print("--------------------------------------------------------")
        print("Gate Breakdown:")
        for gate_id, gate in report.gates.items():
            icon = "PASSED" if gate.status == "PASSED" else "FAILED"
            print(f"  [{icon}] {gate.gate_id}: {gate.name} ({gate.status})")
            if gate.status != "PASSED" and gate.metrics.get("error"):
                print(f"         - Detail: {gate.metrics.get('error')}")

        print("--------------------------------------------------------")
        print("Safety Invariants Enforcement:")
        for flag, val in report.safety_invariants.items():
            print(f"  - {flag:30s}: {'FALSE (SECURE)' if not val else 'TRUE (DANGER!)'}")
        print("========================================================\n")
        return 0 if report.overall_readiness == "READY_FOR_PAPER_SIMULATION" else 1
    finally:
        session.close()


def cmd_drift(args: argparse.Namespace) -> int:
    """Run statistical distribution drift audit across NIFTY benchmark features."""
    report = run_nifty_benchmark_drift_audit()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print("\n========================================================")
    print("     V6 SYSTEM — STATISTICAL FEATURE DRIFT AUDIT")
    print("========================================================")
    print(f"Overall Drift Status      : {report.overall_status}")
    print(f"Maximum Feature PSI       : {report.max_psi:.4f}")
    print(f"Warning PSI Threshold     : {report.warning_psi_threshold:.2f}")
    print(f"Critical PSI Threshold    : {report.critical_psi_threshold:.2f}")
    print(f"Circuit Breaker Tripped   : {report.kill_switch_tripped}")
    print("--------------------------------------------------------")
    print("Feature Breakdown:")
    for name, metric in report.feature_metrics.items():
        print(f"  - {name:15s}: PSI={metric.psi:.4f} | KS-Stat={metric.ks_statistic:.4f} (p={metric.ks_pvalue:.4f}) | {metric.status}")
    print("========================================================\n")
    return 0


def cmd_simulation(args: argparse.Namespace) -> int:
    """Run paper trading simulation with complete Indian statutory friction."""
    capital = float(args.capital)
    product = str(args.product).upper()
    sim = run_nifty_swing_paper_simulation(
        initial_capital_inr=capital,
        product_type=product,
    )
    if args.json:
        print(json.dumps(sim.to_dict(), indent=2))
        return 0

    net_ret = ((sim.final_capital_inr - sim.initial_capital_inr) / sim.initial_capital_inr) * 100.0
    total_fric = sim.total_regulatory_charges_inr + sim.total_slippage_inr

    print("\n========================================================")
    print(f"  V6 PAPER EXECUTION SIMULATION ({product} PRODUCT)")
    print("========================================================")
    print(f"Initial Capital           : Rs {sim.initial_capital_inr:,.2f}")
    print(f"Final Capital             : Rs {sim.final_capital_inr:,.2f}")
    print(f"Net Return                : {net_ret:.2f}% (Rs {sim.net_pnl_inr:+,.2f})")
    print(f"Gross PnL                 : Rs {sim.gross_pnl_inr:+,.2f}")
    print(f"Total Friction Deducted   : Rs {total_fric:,.2f} ({sim.fee_drag_pct:.2f}% drag)")
    print("--------------------------------------------------------")
    print("Statutory Indian Tax & Friction Breakdown:")
    print(f"  - STT Charges           : Rs {sim.total_stt_inr:,.2f}")
    print(f"  - Exchange (NSE) Turnover: Rs {sim.total_exchange_turnover_inr:,.2f}")
    print(f"  - SEBI Regulatory Fees  : Rs {sim.total_sebi_charges_inr:,.2f}")
    print(f"  - GST (18%)             : Rs {sim.total_gst_inr:,.2f}")
    print(f"  - Stamp Duty            : Rs {sim.total_stamp_duty_inr:,.2f}")
    print(f"  - Brokerage             : Rs {sim.total_brokerage_inr:,.2f}")
    print(f"  - Bid/Ask Slippage      : Rs {sim.total_slippage_inr:,.2f}")
    print("--------------------------------------------------------")
    print(f"Total Trade Count         : {sim.total_trades} trades (Win Rate: {sim.win_rate_pct:.1f}%)")
    print(f"Profit Factor             : {sim.profit_factor:.2f}")
    print(f"Max Drawdown              : {sim.max_drawdown_pct:.2f}%")
    print("========================================================\n")
    return 0


def cmd_multi_asset(args: argparse.Namespace) -> int:
    """Run concurrent multi-asset paper trading simulation across NIFTY and BANK NIFTY."""
    capital = float(args.capital)
    summary = run_multi_asset_paper_simulation(initial_capital_inr=capital)
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
        return 0

    print("\n========================================================")
    print("  V6 MULTI-ASSET PAPER EXECUTION SIMULATION (CONCURRENT)")
    print("========================================================")
    print(f"Initial Capital           : Rs {summary.initial_capital_inr:,.2f}")
    print(f"Ending Capital            : Rs {summary.ending_capital_inr:,.2f}")
    print(f"Net Return (ROI)          : {summary.net_roi_pct:.2f}% (Rs {summary.net_pnl_inr:+,.2f})")
    print(f"Gross PnL                 : Rs {summary.gross_pnl_inr:+,.2f}")
    total_charges = sum(summary.total_charges_breakdown.values())
    print(f"Total Friction Deducted   : Rs {total_charges:,.2f}")
    print("--------------------------------------------------------")
    print("Portfolio Allocation Weights:")
    for sym, weight in summary.capital_allocation_weights.items():
        print(f"  - {sym:12s}: {weight * 100:.1f}%")
    print("--------------------------------------------------------")
    print("Asset Performance Breakdown:")
    for sym, m in summary.asset_metrics.items():
        print(f"  [{sym}]")
        print(f"    Trades: {m.total_trades} (Win Rate: {m.win_rate_pct:.1f}%) | PF: {m.profit_factor:.2f}")
        print(f"    Gross PnL: Rs {m.gross_pnl_inr:+,.2f} | Net PnL: Rs {m.net_pnl_inr:+,.2f} | Charges: Rs {m.total_charges_inr + m.total_slippage_inr:,.2f}")
    print("--------------------------------------------------------")
    print(f"Total Trade Count         : {summary.total_trades_count} trades (Win Rate: {summary.overall_win_rate_pct:.1f}%)")
    print(f"Portfolio Profit Factor   : {summary.overall_profit_factor:.2f}")
    print(f"Max Portfolio Drawdown    : {summary.max_drawdown_pct:.2f}%")
    print("========================================================\n")
    return 0


def cmd_attribution(args: argparse.Namespace) -> int:
    """Run statistical factor attribution and feature explainability benchmark."""
    from dataclasses import asdict
    report = run_m41_factor_attribution_benchmark()
    if args.json:
        print(json.dumps(asdict(report), indent=2))
        return 0

    print("\n========================================================")
    print("  V6 FACTOR ATTRIBUTION & FEATURE EXPLAINABILITY (M41)")
    print("========================================================")
    print("Cross-Asset Divergence:")
    print(f"  - Cosine Similarity     : {report.cross_asset_divergence.cosine_similarity:.4f}")
    print(f"  - Euclidean Distance    : {report.cross_asset_divergence.euclidean_distance:.4f}")
    print(f"  - Inverted Sign Factors : {', '.join(report.cross_asset_divergence.inverted_sign_factors)}")
    print("--------------------------------------------------------")
    print("Top Alpha Drivers (NIFTY 50):")
    for f in report.nifty_attribution.top_predictive_factors[:5]:
        print(f"  - {f}")
    print("Top Alpha Drivers (BANK NIFTY):")
    for f in report.banknifty_attribution.top_predictive_factors[:5]:
        print(f"  - {f}")
    print("--------------------------------------------------------")
    print("Key Quantitative Findings:")
    for finding in report.key_findings:
        print(f"  * {finding}")
    print("========================================================\n")
    return 0


def cmd_kill_switch(args: argparse.Namespace) -> int:
    """Manage operational fail-safe kill switch."""
    session = get_session_factory()()
    try:
        action = args.action.lower()
        if action == "status":
            ops = session.get(OpsState, 1)
            is_tripped = False if ops is None else bool(ops.kill_switch)
            reason = ops.note if ops else "No note"
            print(f"Kill Switch Status: {'TRIPPED (HALTED)' if is_tripped else 'CLEARED (NORMAL)'}")
            print(f"Current Note/Reason: {reason}")
            return 0

        if action == "trip":
            reason = args.reason or "MANUAL_OPERATOR_LOCKOUT"
            set_kill_switch(session, True, actor="cli.operator", reason=reason)
            print(f"Kill switch TRIPPED: {reason}")
            return 0

        if action == "clear":
            reason = args.reason or "MANUAL_OPERATOR_CLEARANCE"
            set_kill_switch(session, False, actor="cli.operator", reason=reason)
            print(f"Kill switch CLEARED: {reason}")
            return 0

        print(f"Unknown action: {action}. Use 'status', 'trip', or 'clear'.")
        return 1
    finally:
        session.close()


def cmd_health(args: argparse.Namespace) -> int:
    """Verify system health, DB connection, and safety invariants."""
    database_ok = False
    mode = "UNKNOWN"
    kill_switch = None
    settings = get_settings()

    try:
        from sqlalchemy import text
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        session = get_session_factory()()
        try:
            ensure_seed(session, settings)
            cfg = current_config(session)
            ops = session.get(OpsState, 1)
            mode = cfg.runtime.mode.value
            kill_switch = None if ops is None else bool(ops.kill_switch)
            database_ok = True
        finally:
            session.close()
    except Exception as e:
        print(f"Database connection error: {e}")
        database_ok = False

    status = {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "runtime_mode": mode,
        "kill_switch": kill_switch,
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }

    if args.json:
        print(json.dumps(status, indent=2))
        return 0

    print("\n========================================================")
    print("     V6 SYSTEM — OPERATIONAL HEALTH CHECK")
    print("========================================================")
    print(f"Status              : {status['status'].upper()}")
    print(f"Database (Postgres) : {'CONNECTED' if database_ok else 'UNAVAILABLE'}")
    print(f"Runtime Mode        : {mode}")
    print(f"Kill Switch         : {'TRIPPED' if kill_switch else 'NORMAL (OFF)'}")
    print("Safety Invariants   : ALL 5 FLAGS STRICTLY FALSE")
    print("========================================================\n")
    return 0 if database_ok else 1


def cmd_retrain_live(args: argparse.Namespace) -> int:
    """Rebuild features (current feature set), run the M3 holdout and register the live model.

    Reuses the same steps as History -> Evaluate (M3) -> Model Studio -> Register, so the
    registry keeps its checksums and lineage. Needed after a feature-set change: older
    registered models are refused by the live loader because their inputs no longer match.
    """
    from app.features.definitions import FEATURE_SET_VERSION
    from app.features.service import feature_store
    from app.forecasting.experiment import run_experiment
    from app.forecasting.splits import SplitConfig
    from app.forecasting.store import experiment_store
    from app.market.history import features_from_source, history_store
    from app.registry.service import apply, register_artifact
    from app.registry.store import registry_store

    store = history_store()
    dataset_id = args.dataset_id
    if not dataset_id:
        ids = store.list_ids()
        print("Pass --dataset-id. Stored history datasets:")
        for item in ids:
            print(f"  - {item}")
        return 2
    source = store.read(dataset_id)
    if not source.get("forecast_eligible"):
        print(f"Dataset {dataset_id} is not eligible for forecasting evaluation.")
        return 1
    built = features_from_source(source, feature_store=feature_store())
    if not built["ok"] or built["artifact"] is None:
        print(f"Feature build failed: {built.get('code')}: {built.get('message')}")
        return 1
    result = run_experiment(built["artifact"], config=SplitConfig())
    if not result.get("ok") or result.get("artifact") is None:
        print(f"Experiment failed: {result.get('code')}: {result.get('message')}")
        return 1
    artifact = result["artifact"]
    experiment_store().write(artifact)
    registered = apply(
        registry_store(),
        lambda document: register_artifact(document, artifact, kind="m3", actor="cli-retrain", expected_revision=None),
        idempotency_key=None,
        body={"experiment_id": artifact.get("experiment_id"), "kind": "m3"},
    )
    versions = [v.get("version_id") for v in registered.get("versions") or []]
    print(f"Feature set     : {FEATURE_SET_VERSION}")
    print(f"Experiment      : {artifact.get('experiment_id')}")
    print(f"Registered      : {', '.join(versions) or 'already registered (duplicate)'}")
    print("Note: the model is research-only; it has no after-cost validation and probabilities are uncalibrated.")
    return 0


def cmd_refresh_expiries(args: argparse.Namespace) -> int:
    """Refresh listed expiries (and check lot sizes) from the Groww instrument master.

    --csv PATH   read a downloaded instrument.csv
    --download   fetch the public instrument.csv from Groww
    --api        also query the authenticated Groww Expiries API for NSE/BSE underlyings
    """
    from app.integrations.http import HttpxCaller
    from app.market.instrument_master import (
        INSTRUMENTS_CSV_URL,
        MASTER_SYMBOLS,
        contract_spec_mismatches,
        expiries_from_api_payload,
        front_month_future_symbol,
        option_expiries_from_rows,
        parse_instruments_csv,
        save_listed_expiries,
    )

    rows: list[dict] = []
    sources = []
    if args.csv:
        with open(args.csv, encoding="utf-8") as handle:
            rows = parse_instruments_csv(handle.read())
        sources.append(f"csv:{args.csv}")
    elif args.download:
        result = HttpxCaller().send("GET", INSTRUMENTS_CSV_URL, headers={"Accept": "text/csv"}, json_body=None, timeout=60.0)
        if result.status_code != 200 or not result.text:
            print(f"Download failed: HTTP {result.status_code}")
            return 1
        rows = parse_instruments_csv(result.text)
        sources.append(INSTRUMENTS_CSV_URL)

    expiries = {name: option_expiries_from_rows(rows, name) for name in MASTER_SYMBOLS} if rows else {}

    if args.api:
        from app.db import get_session_factory
        from app.integrations.groww import read_expiries
        from app.integrations.service import groww_read_token
        from app.settings import get_settings

        session = get_session_factory()()
        try:
            token = groww_read_token(session, get_settings())
        finally:
            session.close()
        now = datetime.now(timezone.utc)
        for name, (exchange, symbol) in MASTER_SYMBOLS.items():
            if exchange not in {"NSE", "BSE"}:
                continue
            found = set(expiries.get(name, []))
            for year in (now.year, now.year + 1):
                result = read_expiries(HttpxCaller(), token, exchange=exchange, underlying_symbol=symbol, year=year)
                if result.status_code == 200:
                    found.update(expiries_from_api_payload(result.body))
            expiries[name] = sorted(found)
        sources.append("groww-expiries-api")

    if not sources:
        print("Pass --csv PATH, --download and/or --api.")
        return 2
    path = save_listed_expiries(expiries, source=", ".join(sources))
    for name in MASTER_SYMBOLS:
        listed = expiries.get(name) or []
        print(f"{name:13s}: {len(listed)} expiries" + (f" (next {listed[0]})" if listed else " - none found"))
    if rows:
        today = datetime.now(timezone.utc).date()
        print(f"MCX front-month crude mini future: {front_month_future_symbol(rows, 'CRUDEOILMINI', today) or 'not found'}")
        for issue in contract_spec_mismatches(rows):
            print(f"LOT SIZE MISMATCH {issue['instrument']}: configured {issue['configured']}, master {issue['master']} - update app/instrument_specs.py")
    print(f"Saved to {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imm-cli",
        description="V6 Indian Market AI Trading System — Management & Research CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # audit
    p_audit = subparsers.add_parser("audit", help="Run 8-Gate Paper Readiness Audit")
    p_audit.add_argument("--json", action="store_true", help="Output JSON format")
    p_audit.set_defaults(func=cmd_audit)

    # drift
    p_drift = subparsers.add_parser("drift", help="Run statistical feature drift audit")
    p_drift.add_argument("--json", action="store_true", help="Output JSON format")
    p_drift.set_defaults(func=cmd_drift)

    # simulation
    p_sim = subparsers.add_parser("simulation", help="Run paper execution simulation with Indian friction")
    p_sim.add_argument("--capital", default="1000000.0", help="Initial capital in INR (default: 1,000,000)")
    p_sim.add_argument("--product", default="NRML", choices=["NRML", "MIS"], help="Execution product type (NRML or MIS)")
    p_sim.add_argument("--json", action="store_true", help="Output JSON format")
    p_sim.set_defaults(func=cmd_simulation)

    # multi-asset
    p_multi = subparsers.add_parser("multi-asset", help="Run multi-asset concurrent paper simulation")
    p_multi.add_argument("--capital", default="1000000.0", help="Initial capital in INR (default: 1,000,000)")
    p_multi.add_argument("--json", action="store_true", help="Output JSON format")
    p_multi.set_defaults(func=cmd_multi_asset)

    # attribution
    p_attr = subparsers.add_parser("attribution", help="Run statistical factor attribution benchmark")
    p_attr.add_argument("--json", action="store_true", help="Output JSON format")
    p_attr.set_defaults(func=cmd_attribution)

    # kill-switch
    p_ks = subparsers.add_parser("kill-switch", help="Query or toggle operational kill switch")
    p_ks.add_argument("action", choices=["status", "trip", "clear"], help="Kill switch action")
    p_ks.add_argument("--reason", default="", help="Audit reason for state change")
    p_ks.set_defaults(func=cmd_kill_switch)

    # refresh-expiries
    p_exp = subparsers.add_parser("refresh-expiries", help="Load listed expiries and check lot sizes from the Groww instrument master")
    p_exp.add_argument("--csv", default=None, help="Path to a downloaded instrument.csv")
    p_exp.add_argument("--download", action="store_true", help="Download the public instrument.csv from Groww")
    p_exp.add_argument("--api", action="store_true", help="Also query the Groww Expiries API (NSE/BSE; needs a saved token)")
    p_exp.set_defaults(func=cmd_refresh_expiries)

    # retrain-live
    p_retrain = subparsers.add_parser("retrain-live", help="Rebuild features, run the M3 holdout and register the live model")
    p_retrain.add_argument("--dataset-id", default=None, help="Stored history dataset id (omit to list them)")
    p_retrain.set_defaults(func=cmd_retrain_live)

    # health
    p_health = subparsers.add_parser("health", help="Check operational health and invariants")
    p_health.add_argument("--json", action="store_true", help="Output JSON format")
    p_health.set_defaults(func=cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
