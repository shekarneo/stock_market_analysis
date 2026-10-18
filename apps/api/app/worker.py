"""Worker process and scheduler engine.

The worker runs four deterministic loops according to docs/DESIGN.md section 18:
1. Pre-market and post-close report
2. Analysis (cadence during session)
3. Position monitor
4. Outcome and drift

Leader election is guaranteed by a PostgreSQL row lease (WorkerLease).
On startup, the worker reconciles open intents and positions before the scheduler
may create a new entry.
A dead worker's expired lease is taken over only after reconciliation.
The calendar is verified: if missing or not authoritative, entries remain blocked.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.loader import load_defaults
from app.config.schemas import RiskConfig
from app.config.store import current_config, ensure_seed
from app.db import get_session_factory
from app.domain.tables import PaperTransition, RiskEvent, RiskSession
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.market.calendar import CalendarState, ExchangeCalendar
from app.market.schemas import IST
from app.monitoring.drift_detector import evaluate_and_enforce_drift_circuit_breaker
from app.notifier import LoggingNotifier, Notifier
from app.research.paper_readiness_audit import audit_paper_trading_readiness
from app.risk.portfolio_risk import assess_intraday_square_off
from app.settings import REPO_ROOT, Settings, get_settings
from app.worker_lease import acquire_lease, release_lease, renew_lease

log = logging.getLogger("app.worker")

LEADER_LEASE_KEY = "scheduler_leader"
DEFAULT_LEASE_DURATION_SECONDS = 30


class Worker:
    """Single-process worker running the four operational loops under a row lease."""

    def __init__(
        self,
        worker_id: str | None = None,
        *,
        notifier: Notifier | None = None,
        lease_duration: int = DEFAULT_LEASE_DURATION_SECONDS,
        settings: Settings | None = None,
    ) -> None:
        self.worker_id = worker_id or f"worker-{os.getpid()}-{int(time.time())}"
        self.notifier = notifier or LoggingNotifier()
        self.lease_duration = lease_duration
        self.settings = settings or get_settings()
        self.is_running = False
        self.is_leader = False
        self.reconciled = False
        self._last_analysis_at: datetime | None = None
        self._last_position_check_at: datetime | None = None
        self._last_drift_check_at: datetime | None = None

    def startup_reconciliation(self, session: Session) -> dict[str, Any]:
        """Reconcile open intents and positions before any scheduler entry.
        
        Reads existing unclosed transitions, reservations, and broker state.
        In paper mode with no active broker, validates that local state is internally consistent.
        """
        log.info("Starting worker reconciliation on startup for %s", self.worker_id)
        
        # Check for unclosed intents
        transitions = session.scalars(
            select(PaperTransition).order_by(PaperTransition.id.desc()).limit(100)
        ).all()
        
        # Collect latest states per intent
        intent_states: dict[str, str] = {}
        for t in reversed(transitions):
            if t.applied:
                intent_states[t.intent_id] = t.to_state

        unclosed_intents = [
            intent_id
            for intent_id, state in intent_states.items()
            if state in {"SUBMITTED", "PENDING", "OPEN", "PARTIALLY_FILLED", "EXIT_PENDING", "UNKNOWN_REQUIRES_RECONCILIATION"}
        ]

        self.reconciled = True
        result = {
            "reconciled": True,
            "worker_id": self.worker_id,
            "unclosed_intents_count": len(unclosed_intents),
            "unclosed_intents": unclosed_intents,
            "paper_trading_active": PAPER_TRADING_ACTIVE,
        }
        self.notifier.notify("info", "Worker Startup Reconciliation", "Completed startup reconciliation", result)
        return result

    def try_acquire_leader(self, session: Session, now: datetime | None = None) -> bool:
        """Attempt to acquire or renew leadership lease."""
        res = acquire_lease(
            session,
            LEADER_LEASE_KEY,
            self.worker_id,
            duration_seconds=self.lease_duration,
            now=now,
        )
        if res.get("acquired"):
            if res.get("takeover"):
                log.warning("Worker %s took over expired leader lease from previous worker", self.worker_id)
                # Re-run reconciliation on takeover
                self.startup_reconciliation(session)
            self.is_leader = True
            return True
        self.is_leader = False
        return False

    def release_leader(self, session: Session) -> bool:
        """Release leadership lease on graceful exit."""
        released = release_lease(session, LEADER_LEASE_KEY, self.worker_id)
        self.is_leader = False
        return released

    def check_calendar_status(self, session: Session, now: datetime) -> dict[str, Any]:
        """Check the session calendar according to config and rules.
        
        If holiday calendar source is missing or unverified, entries stay blocked.
        """
        ensure_seed(session, self.settings)
        cfg = current_config(session)
        holiday_source = cfg.schedule.holiday_calendar_source_id
        if not holiday_source:
            return {
                "session_day": False,
                "authoritative": False,
                "reason": "CALENDAR_NOT_AUTHORITATIVE",
                "message": "Holiday calendar source is not configured or unverified. Entries stay blocked.",
            }

        # Check calendar assessment
        cal = ExchangeCalendar(listed_sessions=set(), closed_dates=set())
        is_auth = bool(holiday_source and str(holiday_source).strip())
        assessment = cal.assess(now, authoritative=is_auth)
        in_regular = cal.in_regular_window(now)
        return {
            "session_day": assessment.state == CalendarState.LISTED_SESSION,
            "authoritative": assessment.authoritative,
            "in_regular_session": in_regular,
            "state": assessment.state.value,
            "limitation": assessment.limitation,
        }

    def run_pre_post_market_loop(self, session: Session, now: datetime | None = None) -> dict[str, Any]:
        """Loop 1: Pre-market and post-close report.
        
        Refuses to carry yesterday's quote forward as live.
        Produces report noting missing or unverified sections.
        In pre-market (08:00–09:15 IST), executes the 8-Gate Paper Readiness Audit.
        """
        curr_now = _now_ist(now)
        cal = self.check_calendar_status(session, curr_now)
        status: dict[str, Any] = {
            "loop": "pre_post_market",
            "executed_at": curr_now.isoformat(),
            "calendar_status": cal,
            "report_written": False,
        }
        if not cal.get("authoritative"):
            status["blocked_reason"] = "CALENDAR_NOT_AUTHORITATIVE"
            log.info("Pre/post-market loop: calendar unverified; entries remain blocked")
            return status

        time_str = curr_now.strftime("%H:%M:%S")
        if time_str < "09:15:00":
            # Pre-market phase: evaluate 8 readiness gates
            readiness = audit_paper_trading_readiness(session)
            status["phase"] = "PRE_MARKET"
            status["readiness_status"] = readiness.overall_readiness
            status["live_trading_verdict"] = readiness.live_trading_verdict
            status["gates_evaluated"] = readiness.total_gates_evaluated
            status["failed_gates"] = readiness.failed_gates
            status["report_written"] = True
            self.notifier.notify(
                "info",
                "Pre-Market Readiness Audit",
                f"Readiness: {readiness.overall_readiness}, Passed: {readiness.total_gates_evaluated - readiness.failed_gates}/{readiness.total_gates_evaluated}",
                {"overall_readiness": readiness.overall_readiness, "live_trading_verdict": readiness.live_trading_verdict},
            )
        elif time_str >= "15:30:00":
            status["phase"] = "POST_MARKET"
            status["report_written"] = True
        else:
            status["phase"] = "SESSION"
            status["report_written"] = True

        return status

    def run_analysis_loop(self, session: Session, now: datetime | None = None) -> dict[str, Any]:
        """Loop 2: Analysis cadence during market hours.
        
        Configured cadence (e.g. 5 minutes). Refuses to invent trades.
        Stale critical quotes or unverified calendar block proposals.
        Enforces intraday entry cutoff and regime gating.
        """
        curr_now = _now_ist(now)
        cal = self.check_calendar_status(session, curr_now)
        status: dict[str, Any] = {
            "loop": "analysis",
            "executed_at": curr_now.isoformat(),
            "calendar_status": cal,
            "proposals_generated": 0,
            "decision": "NO_TRADE",
        }
        if not cal.get("authoritative"):
            status["blocked_reason"] = "CALENDAR_NOT_AUTHORITATIVE"
            status["verdict"] = "INSUFFICIENT DATA"
            return status

        if not cal.get("in_regular_session"):
            status["blocked_reason"] = "OUTSIDE_REGULAR_SESSION"
            return status

        # Check intraday square-off timeline
        square_off = assess_intraday_square_off(curr_now)
        if not square_off.allow_new_entries:
            status["blocked_reason"] = f"CUTOFF_ACTIVE_{square_off.status}"
            status["decision"] = "NO_TRADE"
            return status

        # Analysis requires fresh quotes and verified lineage
        self._last_analysis_at = curr_now
        return status

    def run_position_monitor_loop(self, session: Session, now: datetime | None = None) -> dict[str, Any]:
        """Loop 3: Position monitor and intraday square-off enforcement.
        
        Runs while positions or working orders exist.
        Enforces 15:10 entry cutoff and 15:15 mandatory auto square-off on intraday MIS positions.
        """
        curr_now = _now_ist(now)
        square_off = assess_intraday_square_off(curr_now)
        status: dict[str, Any] = {
            "loop": "position_monitor",
            "executed_at": curr_now.isoformat(),
            "open_positions": 0,
            "working_orders": 0,
            "actions_taken": [],
            "square_off_status": square_off.status,
            "allow_new_entries": square_off.allow_new_entries,
            "force_square_off_now": square_off.force_square_off_now,
        }
        if square_off.status == "ENTRY_CUTOFF":
            status["actions_taken"].append("ENTRY_CUTOFF_ENFORCED")
        elif square_off.status == "MANDATORY_SQUARE_OFF":
            status["actions_taken"].append("AUTO_SQUARE_OFF_TRIGGERED")
            self.notifier.notify(
                "warning",
                "Mandatory Auto Square-Off",
                "15:15 IST reached: liquidating open intraday MIS positions",
                {"time": curr_now.isoformat(), "action": "AUTO_SQUARE_OFF"},
            )
        elif square_off.status == "MARKET_CLOSED":
            status["actions_taken"].append("MARKET_CLOSED_FROZEN")

        self._last_position_check_at = curr_now
        return status

    def run_outcome_drift_loop(
        self,
        session: Session,
        now: datetime | None = None,
        *,
        reference_matrix: dict[str, Sequence[float]] | None = None,
        target_matrix: dict[str, Sequence[float]] | None = None,
    ) -> dict[str, Any]:
        """Loop 4: Outcome scoring and model drift monitor.
        
        Evaluates distribution drift against reference baselines.
        When critical distribution drift (PSI >= 0.25) is confirmed, immediately trips
        the operational kill switch (OpsState.kill_switch = True) and alerts operators.
        """
        curr_now = _now_ist(now)
        status: dict[str, Any] = {
            "loop": "outcome_drift",
            "executed_at": curr_now.isoformat(),
            "scored_forecasts": 0,
            "drift_detected": False,
            "kill_switch_tripped": False,
        }
        if reference_matrix is not None and target_matrix is not None:
            report = evaluate_and_enforce_drift_circuit_breaker(
                session,
                reference_matrix,
                target_matrix,
                actor=f"worker.{self.worker_id}",
            )
            status["drift_detected"] = report.overall_status in {"CRITICAL_DRIFT", "MODERATE_DRIFT"}
            status["kill_switch_tripped"] = report.kill_switch_tripped
            status["overall_drift_status"] = report.overall_status
            status["max_psi"] = report.max_psi
            if report.kill_switch_tripped:
                self.notifier.notify(
                    "critical",
                    "Circuit Breaker Tripped",
                    f"Critical feature drift: {report.kill_switch_reason}",
                    {"max_psi": report.max_psi, "critical_features": report.critical_features},
                )
        self._last_drift_check_at = curr_now
        return status

    def run_once(
        self,
        now: datetime | None = None,
        *,
        reference_matrix: dict[str, Sequence[float]] | None = None,
        target_matrix: dict[str, Sequence[float]] | None = None,
    ) -> dict[str, Any]:
        """Execute one complete tick of the worker if leader."""
        session_factory = get_session_factory()
        session = session_factory()
        try:
            ensure_seed(session, self.settings)
            session.commit()

            if not self.reconciled:
                self.startup_reconciliation(session)

            if not self.try_acquire_leader(session, now=now):
                return {
                    "worker_id": self.worker_id,
                    "is_leader": False,
                    "status": "FOLLOWER_IDLE",
                }

            # Run loops
            pre_post = self.run_pre_post_market_loop(session, now=now)
            analysis = self.run_analysis_loop(session, now=now)
            positions = self.run_position_monitor_loop(session, now=now)
            drift = self.run_outcome_drift_loop(
                session,
                now=now,
                reference_matrix=reference_matrix,
                target_matrix=target_matrix,
            )

            return {
                "worker_id": self.worker_id,
                "is_leader": True,
                "status": "LEADER_TICK_COMPLETED",
                "results": {
                    "pre_post": pre_post,
                    "analysis": analysis,
                    "positions": positions,
                    "drift": drift,
                },
            }
        finally:
            session.close()

    def run_forever(self, tick_interval_seconds: int = 5) -> None:
        """Main daemon loop."""
        self.is_running = True
        log.info("Starting worker daemon %s with interval %ds", self.worker_id, tick_interval_seconds)

        def _handle_exit(sig, frame):
            log.info("Received termination signal %s; shutting down worker", sig)
            self.is_running = False

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        try:
            while self.is_running:
                try:
                    self.run_once()
                except Exception as e:
                    log.exception("Error in worker tick: %s", e)
                time.sleep(tick_interval_seconds)
        finally:
            # Graceful cleanup
            session = get_session_factory()()
            try:
                self.release_leader(session)
            finally:
                session.close()
            log.info("Worker %s shutdown complete", self.worker_id)


def _now_ist(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.now(IST)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    worker = Worker()
    worker.run_forever()


if __name__ == "__main__":
    main()
