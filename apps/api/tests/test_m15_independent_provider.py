"""Milestone M15 Tests: Independent Data Provider Integration and Verification.

Tests candidate provider specifications, adapter scaffolding, schema validation,
pagination, rate limiting, raw-payload quarantine, separate normalization, 15:30
boundary investigation, reconciliation reporting, and safety gating.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from app.market.independent_provider import (
    INDEPENDENT_PROVIDER_SPECS,
    IndependentProviderAdapter,
    ProviderCandleRequest,
    investigate_1530_observation,
    mask_secrets,
    normalize_reference_candles,
    quarantine_reference_response,
    resolve_credentials_safe,
    split_date_range_chunks,
    validate_provider_candle_payload,
)
from app.market.provenance import quarantine_training_block
from app.market.verified_history import (
    evaluate_real_data_walkforward,
    reconcile_historical_dataset,
)
from app.settings import REPO_ROOT

# Initial recorded raw quarantine hashes
RECORDED_INITIAL_HASHES = {
    "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057": "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
    "2323f19618c15d4f4493c797dd07491b569454d1698adb8702ed355b0c072e90": "3834214245f4db55ba073db5390569f8ab385807e6ddcb6a094b737c6ed8f1a9",
    "354548401cc1654c40cf62bb9174a4af34fe94f17e5aa6e93a62fdffc028e785": "f80fc96135752675ec9845b4af1079a73c87195ee5e7f78db7ccc923415fd964",
    "db75f3f891652f6cf900bbb9cb0b5169f2a1237a3afe5cf2b62df588049edc33": "d6c92199e1697c34488feaed987046a6db3b39ef4dc3659b858a9d2a5f65983a",
}


def test_m15_phase1_raw_hashes_preserved():
    """Verify all M9 and M12 raw quarantine artifacts retain identical hashes."""
    for qid, expected_sha in RECORDED_INITIAL_HASHES.items():
        p = REPO_ROOT / "var" / "history" / "quarantine" / f"{qid}.json"
        assert p.is_file(), f"Missing quarantine file {qid}"
        actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"Hash mismatch for {qid}"


def test_m15_candidate_provider_specifications():
    """Verify documented candidate specifications and access requirements."""
    # Upstox
    upstox = INDEPENDENT_PROVIDER_SPECS["upstox"]
    assert upstox["nifty_15m_supported"] is True
    assert "access_token" in upstox["required_credentials"]
    assert upstox["max_range_per_request_days"] == 30
    assert upstox["candles_per_normal_session"] == 25
    assert upstox["has_1530_candle"] is False

    # Zerodha Kite Connect
    kite = INDEPENDENT_PROVIDER_SPECS["kite"]
    assert kite["nifty_15m_supported"] is True
    assert "api_key" in kite["required_credentials"]
    assert "access_token" in kite["required_credentials"]
    assert kite["candles_per_normal_session"] == 25
    assert kite["has_1530_candle"] is False

    # Official NSE reports
    nse = INDEPENDENT_PROVIDER_SPECS["nse_official"]
    assert nse["nifty_15m_supported"] is False  # Free reports are strictly daily


def test_m15_credential_masking_and_redaction():
    """Verify secrets and bearer tokens are never leaked in error logs or string representations."""
    raw_log = "Error connecting with Authorization: Bearer secret_token_xyz123 and api_key='my_super_secret_key'"
    masked = mask_secrets(raw_log)
    assert "secret_token_xyz123" not in masked
    assert "my_super_secret_key" not in masked
    assert "Bearer [REDACTED]" in masked


def test_m15_fail_closed_when_credentials_absent():
    """Adapter fails closed with BLOCKED_CREDENTIALS_MISSING when provider credentials are not stored."""
    adapter = IndependentProviderAdapter("upstox")
    req = ProviderCandleRequest(
        provider="upstox",
        instrument="NIFTY",
        interval="15minute",
        from_date=date(2026, 4, 14),
        to_date=date(2026, 10, 13),
    )
    result = adapter.fetch_reference_dataset(req)
    assert result["ok"] is False
    assert result["code"] == "BLOCKED_CREDENTIALS_MISSING"
    assert result["status"] == "BLOCKED"
    assert "access_token" in result["required_credentials"]
    assert result["data_acquired"] is False
    assert result["real_market_data_verified"] is False
    assert result["forecast_ready"] is False


def test_m15_pagination_and_chunking():
    """Verify date ranges are divided into valid non-overlapping chunks adhering to provider limits."""
    # 6-month range: 2026-04-14 to 2026-10-13 (~183 days)
    chunks_30 = split_date_range_chunks(date(2026, 4, 14), date(2026, 10, 13), 30)
    assert len(chunks_30) == 7
    assert chunks_30[0] == (date(2026, 4, 14), date(2026, 5, 13))
    assert chunks_30[-1][1] == date(2026, 10, 13)

    # Ensure no overlaps or gaps
    for i in range(len(chunks_30) - 1):
        prev_end = chunks_30[i][1]
        next_start = chunks_30[i + 1][0]
        assert (next_start - prev_end).days == 1

    with pytest.raises(ValueError, match="cannot be after"):
        split_date_range_chunks(date(2026, 10, 1), date(2026, 9, 1), 30)


def test_m15_provider_schema_validation():
    """Verify raw schema validator accepts valid envelopes and strictly rejects invalid structures."""
    valid_upstox = {
        "status": "success",
        "data": {
            "candles": [
                ["2026-10-13T09:15:00+05:30", 25050.0, 25080.0, 25040.0, 25075.0, 12000, 0],
                ["2026-10-13T09:30:00+05:30", 25075.0, 25100.0, 25060.0, 25090.0, 15000, 0],
            ]
        },
    }
    ok, msg, candles = validate_provider_candle_payload("upstox", valid_upstox)
    assert ok is True
    assert len(candles) == 2

    # Reject non-numeric OHLC
    bad_ohlc = {
        "status": "success",
        "data": {"candles": [["2026-10-13T09:15:00+05:30", "not_a_number", 25080.0, 25040.0, 25075.0]]},
    }
    ok, msg, _ = validate_provider_candle_payload("upstox", bad_ohlc)
    assert ok is False
    assert "non-numeric" in msg

    # Reject boolean masquerading as number
    bool_ohlc = {
        "status": "success",
        "data": {"candles": [["2026-10-13T09:15:00+05:30", True, 25080.0, 25040.0, 25075.0]]},
    }
    ok, msg, _ = validate_provider_candle_payload("upstox", bool_ohlc)
    assert ok is False
    assert "boolean" in msg

    # Reject geometric bound violations (high < open)
    geom_err = {
        "status": "success",
        "data": {"candles": [["2026-10-13T09:15:00+05:30", 25050.0, 25000.0, 24900.0, 24950.0]]},
    }
    ok, msg, _ = validate_provider_candle_payload("upstox", geom_err)
    assert ok is False
    assert "geometric" in msg


def test_m15_raw_data_quarantine_and_sha_provenance(tmp_path: Path):
    """Verify raw response payloads are written to quarantine with immutable SHA-256 digest."""
    req = ProviderCandleRequest("upstox")
    raw_payload = {
        "status": "success",
        "data": {"candles": [["2026-10-13T09:15:00+05:30", 25050.0, 25080.0, 25040.0, 25075.0]]},
    }
    sha, q_file = quarantine_reference_response("upstox", raw_payload, req, quarantine_dir=tmp_path)
    assert q_file.is_file()
    assert sha in str(q_file)

    saved_data = json.loads(q_file.read_text(encoding="utf-8"))
    assert saved_data["raw_sha256"] == sha
    assert saved_data["reconciled"] is False
    assert saved_data["trusted"] is False


def test_m15_timestamp_and_timezone_normalization():
    """Verify normalization requires explicit IST (+05:30) offset and rejects other timezones."""
    raw_valid = [["2026-10-13T09:15:00+05:30", 25050.0, 25080.0, 25040.0, 25075.0, 500]]
    norm = normalize_reference_candles(raw_valid, "upstox")
    assert len(norm) == 1
    assert norm[0]["timestamp"] == "2026-10-13T09:15:00+05:30"
    assert norm[0]["volume"] == 500.0

    # Non-IST offset (+00:00 UTC) must be rejected
    raw_utc = [["2026-10-13T09:15:00+00:00", 25050.0, 25080.0, 25040.0, 25075.0]]
    with pytest.raises(ValueError, match="Non-IST"):
        normalize_reference_candles(raw_utc, "upstox")

    # Offsetless stamp must be rejected
    raw_no_offset = [["2026-10-13T09:15:00", 25050.0, 25080.0, 25040.0, 25075.0]]
    with pytest.raises(ValueError, match="lacks explicit timezone"):
        normalize_reference_candles(raw_no_offset, "upstox")

    # Duplicate timestamps must be rejected
    raw_dup = [
        ["2026-10-13T09:15:00+05:30", 25050.0, 25080.0, 25040.0, 25075.0],
        ["2026-10-13T09:15:00+05:30", 25050.0, 25080.0, 25040.0, 25075.0],
    ]
    with pytest.raises(ValueError, match="Duplicate timestamp"):
        normalize_reference_candles(raw_dup, "upstox")


def test_m15_investigate_1530_boundary_observation():
    """Verify 15:30 observation is investigated without blindly assuming closing auction tick."""
    groww_1530 = {
        "raw_timestamp": "2026-10-13 15:30:00",
        "open": 25100.0,
        "high": 25100.0,
        "low": 25100.0,
        "close": 25100.0,
        "volume": 0,
    }
    analysis = investigate_1530_observation(groww_1530)
    assert analysis["empirical_properties"]["identical_ohlc"] is True
    assert analysis["empirical_properties"]["zero_or_null_volume"] is True
    assert analysis["provider_documentation_status"] == "UNDOCUMENTED_BY_GROWW"
    assert "SESSION_BOUNDARY_OBSERVATION_UNDOCUMENTED_SEMANTICS" in analysis["authoritative_classification"]
    assert analysis["exclusion_policy"] == "EXCLUDE_FROM_CONTINUOUS_TRADING_BARS"


def test_m15_reconciliation_reporting_fields():
    """Verify reconcile_historical_dataset returns all mandatory Phase 4 reconciliation statistics."""
    sample_payload = {
        "candles": [
            ["2026-10-13 09:15:00", 25000.0, 25050.0, 24980.0, 25020.0, 100],
            ["2026-10-13 09:30:00", 25020.0, 25060.0, 25010.0, 25040.0, 150],
        ]
    }
    # Test with unavailable reference
    res_unavail = reconcile_historical_dataset(sample_payload)
    assert res_unavail["ok"] is False
    assert res_unavail["code"] == "BLOCKED_REFERENCE_UNAVAILABLE"
    assert res_unavail["matched_candles_count"] == 0
    assert "missing_candles_per_source" in res_unavail
    assert "duplicate_observations_count" in res_unavail
    assert "excluded_observations" in res_unavail
    assert "unresolved_discrepancies" in res_unavail
    assert res_unavail["real_market_data_verified"] is False

    # Test with matching reference
    ref_data = [
        {"timestamp": "2026-10-13T09:15:00+05:30", "open": 25000.0, "high": 25050.0, "low": 24980.0, "close": 25020.0},
        {"timestamp": "2026-10-13T09:30:00+05:30", "open": 25020.0, "high": 25060.0, "low": 25010.0, "close": 25040.0},
    ]
    res_match = reconcile_historical_dataset(sample_payload, reference_data=ref_data, tolerance=0.05)
    assert res_match["ok"] is True
    assert res_match["code"] == "RECONCILIATION_MATCHED"
    assert res_match["matched_candles_count"] == 2
    assert res_match["mismatched_candles_count"] == 0
    assert res_match["timestamp_alignment"] == "VALIDATED"
    assert "reference_provenance" in res_match


def test_m15_walkforward_and_safety_invariants_blocked():
    """Verify walkforward fails closed on unverified data and safety invariants remain false."""
    unverified_dataset = {
        "dataset_id": "test_unverified",
        "instrument": "NIFTY",
        "real_market_data_verified": False,
        "candles": [{"open": 25000.0, "close": 25010.0}],
    }
    res = evaluate_real_data_walkforward(unverified_dataset)
    assert res["ok"] is False
    assert res["code"] == "BLOCKED_UNVERIFIED_DATA"
    assert res["real_market_data_verified"] is False
    assert res["forecast_ready"] is False
    assert res["paper_approved"] is False
    assert res["live_approved"] is False
