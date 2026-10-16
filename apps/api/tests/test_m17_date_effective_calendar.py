"""Unit and integration tests for Milestone M17: Date-Effective Market Session Calendar & Verification."""

from datetime import date, datetime, time
import pytest
from zoneinfo import ZoneInfo

from app.market.groww_ingestion import (
    RECORDED_RAW_HASHES,
    classify_market_session_observations,
    load_raw_quarantine_chunks,
    reconcile_chunk_boundaries,
    verify_raw_quarantine_integrity,
)
from app.market.session_calendar import (
    CIRCULAR_NSE_CAS_AUG_2026,
    CIRCULAR_PRE_AUG_2026,
    CIRCULAR_SEBI_OCT_2026,
    Exchange,
    IndependentVerificationLevel,
    InstrumentCategory,
    MarketSegment,
    MarketSessionRule,
    PhaseType,
    ReconciliationTolerances,
    SessionRuleNotFoundError,
    UnverifiedRuleError,
    VerificationStatus,
    audit_m16_derived_dataset,
    audit_observation_against_calendar,
    get_market_session_rule,
    run_independent_verification_audit,
)
from app.market.schemas import IST

KOLKATA = ZoneInfo("Asia/Kolkata")


class TestRawQuarantineImmutability:
    """Safety & data preservation: verify recorded SHA-256 hashes of raw quarantine files."""

    def test_all_raw_quarantine_hashes_intact(self) -> None:
        integrity = verify_raw_quarantine_integrity()
        assert integrity["ok"] is True
        assert integrity["total_files"] == 4
        for qid, res in integrity["results"].items():
            assert res["status"] == "MATCH"
            assert res["match"] is True
            assert res["actual"] == RECORDED_RAW_HASHES[qid]


class TestDateEffectiveSessionRules:
    """Test date-effective rule resolution across regulatory boundaries."""

    def test_pre_august_3_2026_rules(self) -> None:
        as_of = date(2026, 6, 15)

        # 1. Spot Index: Continuous 09:15 to 15:30
        spot_rule = get_market_session_rule(InstrumentCategory.SPOT_INDEX, as_of)
        assert spot_rule.rule_id == "NSE_INDEX_SPOT_PRE_AUG_2026"
        assert spot_rule.continuous_start == time(9, 15)
        assert spot_rule.continuous_end == time(15, 30)
        assert spot_rule.is_verified is True
        assert spot_rule.circular.circular_id == CIRCULAR_PRE_AUG_2026.circular_id

        # 2. Cash CAS: Continuous 09:15 to 15:30
        cash_rule = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, as_of)
        assert cash_rule.rule_id == "NSE_CASH_CAS_PRE_AUG_2026"
        assert cash_rule.continuous_start == time(9, 15)
        assert cash_rule.continuous_end == time(15, 30)

        # 3. Derivatives: Continuous 09:15 to 15:30
        deriv_rule = get_market_session_rule(InstrumentCategory.INDEX_FUTURES, as_of)
        assert deriv_rule.rule_id == "NSE_DERIVATIVES_INDEX_PRE_AUG_2026"
        assert deriv_rule.continuous_start == time(9, 15)
        assert deriv_rule.continuous_end == time(15, 30)

    def test_post_august_3_2026_rules(self) -> None:
        as_of = date(2026, 8, 10)

        # 1. Spot Index: Still continuous 09:15 to 15:30 (spot index doesn't close at 15:15 or 15:40)
        spot_rule = get_market_session_rule(InstrumentCategory.SPOT_INDEX, as_of)
        assert spot_rule.rule_id == "NSE_INDEX_SPOT_AUG_DEC_2026"
        assert spot_rule.continuous_start == time(9, 15)
        assert spot_rule.continuous_end == time(15, 30)
        assert spot_rule.circular.circular_id == CIRCULAR_NSE_CAS_AUG_2026.circular_id

        # 2. Cash CAS: Truncated to 15:15 for CAS window
        cash_rule = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, as_of)
        assert cash_rule.rule_id == "NSE_CASH_CAS_AUG_DEC_2026"
        assert cash_rule.continuous_start == time(9, 15)
        assert cash_rule.continuous_end == time(15, 15)

        # 3. Cash Non-CAS: Continuous remains 09:15 to 15:30
        non_cas_rule = get_market_session_rule(InstrumentCategory.CASH_EQUITY_NON_CAS, as_of)
        assert non_cas_rule.continuous_start == time(9, 15)
        assert non_cas_rule.continuous_end == time(15, 30)

        # 4. Derivatives: Extended to 15:40
        deriv_rule = get_market_session_rule(InstrumentCategory.INDEX_FUTURES, as_of)
        assert deriv_rule.rule_id == "NSE_DERIVATIVES_INDEX_AUG_DEC_2026"
        assert deriv_rule.continuous_start == time(9, 15)
        assert deriv_rule.continuous_end == time(15, 40)

    def test_scheduled_december_7_2026_overhaul(self) -> None:
        as_of = date(2026, 12, 10)

        # 1. Spot Index: 09:15 to 15:30
        spot_rule = get_market_session_rule(InstrumentCategory.SPOT_INDEX, as_of)
        assert spot_rule.rule_id == "NSE_INDEX_SPOT_DEC_2026_ONWARD"
        assert spot_rule.continuous_start == time(9, 15)
        assert spot_rule.continuous_end == time(15, 30)
        assert spot_rule.circular.circular_id == CIRCULAR_SEBI_OCT_2026.circular_id

        # 2. Cash CAS: Continuous restored to 15:30; CAS dedicated 15:30 to 15:40
        cash_rule = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, as_of)
        assert cash_rule.rule_id == "NSE_CASH_CAS_DEC_2026_ONWARD"
        assert cash_rule.continuous_start == time(9, 15)
        assert cash_rule.continuous_end == time(15, 30)
        cas_phase = next(p for p in cash_rule.phases if p.phase_type == PhaseType.CLOSING_AUCTION)
        assert cas_phase.start_time == time(15, 30)
        assert cas_phase.end_time == time(15, 40)

        # 3. Index Derivatives regular day: Extended to 15:45
        deriv_reg = get_market_session_rule(InstrumentCategory.INDEX_FUTURES, as_of, is_expiry_day=False)
        assert deriv_reg.rule_id == "NSE_DERIVATIVES_INDEX_DEC_2026_REGULAR"
        assert deriv_reg.continuous_end == time(15, 45)

        # 4. Expiry-day exception: Expiring index contracts cease trading at 15:30:00
        deriv_exp = get_market_session_rule(
            InstrumentCategory.INDEX_OPTIONS,
            as_of,
            is_expiry_day=True,
            is_expiring_contract=True,
        )
        assert deriv_exp.rule_id == "NSE_DERIVATIVES_INDEX_DEC_2026_EXPIRY_EXPIRING"
        assert deriv_exp.continuous_end == time(15, 30)
        assert deriv_exp.expiry_day_exception == "EXPIRING_INDEX_CONTRACTS_CLOSE_AT_1530"

        # 5. Stock Derivatives: Trade to 15:45 even on expiry day
        stock_deriv = get_market_session_rule(
            InstrumentCategory.STOCK_DERIVATIVES,
            as_of,
            is_expiry_day=True,
            is_expiring_contract=True,
        )
        assert stock_deriv.continuous_end == time(15, 45)

    def test_effective_date_boundary_conditions(self) -> None:
        # Day before Aug 3, 2026 (Sunday Aug 2, 2026) -> PRE_AUG rule
        pre_day = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, date(2026, 8, 2))
        assert pre_day.rule_id == "NSE_CASH_CAS_PRE_AUG_2026"
        assert pre_day.continuous_end == time(15, 30)

        # Day of Aug 3, 2026 -> AUG_DEC rule
        on_day = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, date(2026, 8, 3))
        assert on_day.rule_id == "NSE_CASH_CAS_AUG_DEC_2026"
        assert on_day.continuous_end == time(15, 15)

        # Day before Dec 7, 2026 (Sunday Dec 6, 2026) -> AUG_DEC rule
        pre_dec = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, date(2026, 12, 6))
        assert pre_dec.rule_id == "NSE_CASH_CAS_AUG_DEC_2026"

        # Day of Dec 7, 2026 -> DEC_ONWARD rule
        on_dec = get_market_session_rule(InstrumentCategory.CASH_EQUITY_CAS, date(2026, 12, 7))
        assert on_dec.rule_id == "NSE_CASH_CAS_DEC_2026_ONWARD"
        assert on_dec.continuous_end == time(15, 30)


class TestSeparationAndFailClosed:
    """Spot index vs derivatives separation, unknown rules, and fail closed semantics."""

    def test_spot_index_never_inherits_derivatives_closing_time(self) -> None:
        # In August-December 2026 era, derivatives trade to 15:40, but spot index continuous end is 15:30
        as_of = date(2026, 9, 15)
        spot = get_market_session_rule(InstrumentCategory.SPOT_INDEX, as_of)
        deriv = get_market_session_rule(InstrumentCategory.INDEX_FUTURES, as_of)

        assert spot.continuous_end == time(15, 30)
        assert deriv.continuous_end == time(15, 40)
        assert spot.continuous_end != deriv.continuous_end

        # In post-Dec 7 era, derivatives trade to 15:45, spot index remains 15:30
        as_of_dec = date(2026, 12, 15)
        spot_dec = get_market_session_rule(InstrumentCategory.SPOT_INDEX, as_of_dec)
        deriv_dec = get_market_session_rule(InstrumentCategory.INDEX_FUTURES, as_of_dec)

        assert spot_dec.continuous_end == time(15, 30)
        assert deriv_dec.continuous_end == time(15, 45)

    def test_unknown_instrument_category_fails_closed(self) -> None:
        with pytest.raises(SessionRuleNotFoundError):
            get_market_session_rule("UNKNOWN_INSTRUMENT_XYZ", date(2026, 10, 1))

    def test_unverified_rule_fails_closed_when_strict(self) -> None:
        # Accessing the UNVERIFIED rule directly fails closed when fail_on_unverified=True
        with pytest.raises(UnverifiedRuleError):
            get_market_session_rule(
                InstrumentCategory.COMMODITY_FUTURES,
                date(2027, 2, 1),
                exchange=Exchange.MCX,
                segment=MarketSegment.COMMODITY,
                fail_on_unverified=True,
            )

    def test_timezone_handling_asia_kolkata(self) -> None:
        obs = {
            "timestamp": "2026-09-15T09:15:00+05:30",
            "open": 25000.0,
            "high": 25050.0,
            "low": 24980.0,
            "close": 25020.0,
        }
        audit = audit_observation_against_calendar(obs, instrument="NIFTY")
        assert audit.time_of_day == "09:15:00"
        assert audit.is_continuous_regular is True
        assert audit.is_excluded is False


class TestDatasetAndObservationAudit:
    """Audit M16 dataset observations and historical exclusion preservation."""

    def test_m16_derived_dataset_calendar_audit(self) -> None:
        audit_res = audit_m16_derived_dataset()
        assert audit_res["ok"] is True
        assert audit_res["status"] == "CALENDAR_AUDIT_VERIFIED"
        assert audit_res["total_candles"] == 3120
        assert audit_res["accepted_regular_count"] == 3120
        assert audit_res["anomalous_observations_count"] == 0

        # Verify known 2026-09-29 gap is isolated
        assert audit_res["session_gaps_count"] == 1
        gap = audit_res["session_gaps"][0]
        assert gap["date"] == "2026-09-29"
        assert gap["observed_count"] == 20
        assert gap["missing_count"] == 5
        assert gap["missing_times"] == ["14:15:00", "14:30:00", "14:45:00", "15:00:00", "15:15:00"]

    def test_excluded_observations_audit_and_preservation(self) -> None:
        chunks = load_raw_quarantine_chunks()
        reconciled = reconcile_chunk_boundaries(chunks)
        classified = classify_market_session_observations(reconciled["reconciled_candles"])

        excluded = classified["excluded_observations"]
        assert len(excluded) == 371

        # Audit each excluded observation against the date-effective calendar
        audits = [audit_observation_against_calendar(c, instrument="NIFTY") for c in excluded]
        assert all(a.is_excluded for a in audits)
        assert not any(a.is_continuous_regular for a in audits)

        # Counts by category
        pre_market = [a for a in audits if a.exclusion_reason == "PRE_MARKET_CALL_AUCTION"]
        assert len(pre_market) == 124

        post_auction = [a for a in audits if a.exclusion_reason == "POST_CONTINUOUS_SESSION_BOUNDARY_CLOSING_AUCTION"]
        assert len(post_auction) == 124

        post_settled = [a for a in audits if a.exclusion_reason == "POST_MARKET_SETTLED_MARK"]
        assert len(post_settled) == 123

    def test_chunk_boundaries_conflict_reconciliation(self) -> None:
        chunks = load_raw_quarantine_chunks()
        reconciled = reconcile_chunk_boundaries(chunks)

        assert reconciled["conflicts_count"] == 2
        conflicts = reconciled["conflicts"]

        # Conflict 1: 2026-07-15 09:15:00
        c1 = conflicts[0]
        assert c1["timestamp"].replace("T", " ") == "2026-07-15 09:15:00"
        assert c1["resolution"] == "RETAIN_LEADING_CHUNK_CANDLE"
        assert c1["trailing_ohlc"][1] < c1["leading_ohlc"][1]  # Truncated high vs complete high

        # Conflict 2: 2026-10-13 09:15:00
        c2 = conflicts[1]
        assert c2["timestamp"].replace("T", " ") == "2026-10-13 09:15:00"
        assert c2["resolution"] == "RETAIN_LEADING_CHUNK_CANDLE"
        assert c2["trailing_ohlc"][1] < c2["leading_ohlc"][1]


class TestIndependentVerificationFramework:
    """Test multi-level independent verification audit and fail-closed handling."""

    def test_run_independent_verification_audit_fails_closed(self) -> None:
        res = run_independent_verification_audit()

        assert res["verdict"] == "BLOCKED"
        assert res["reason"] == "BLOCKED_CREDENTIALS_MISSING"

        # Check multi-level breakdown
        levels = res["verification_levels"]
        assert levels["level_1_internal_structural"]["status"] == "PASS"
        assert levels["level_1_internal_structural"]["raw_quarantine_hashes_verified"] is True
        assert levels["level_1_internal_structural"]["accepted_regular_candles"] == 3120

        assert levels["level_2_independent_timestamp_session"]["status"] == "BLOCKED"
        assert levels["level_3_independent_ohlc_price"]["status"] == "BLOCKED"

        # Check documented missing prerequisites
        prereqs = res["prerequisites_missing"]
        assert "access_token" in prereqs["upstox"]
        assert "api_key" in prereqs["kite"]
        assert "jwt_token" in prereqs["angelone"]

        # Check safety invariants
        invs = res["safety_invariants"]
        assert invs["forecast_ready"] is False
        assert invs["real_market_data_verified"] is False
        assert invs["paper_approved"] is False
        assert invs["live_approved"] is False
        assert invs["live_broker_routing_enabled"] is False

    def test_reconciliation_tolerances_contract(self) -> None:
        tol = ReconciliationTolerances()
        assert tol.max_price_delta_percent == 0.05
        assert tol.max_price_delta_points == 2.0
        assert tol.max_timestamp_drift_seconds == 0
        assert tol.interval_seconds == 900
        assert tol.allow_inverted_candle is False
        assert tol.max_unexpected_missing_bars == 0
