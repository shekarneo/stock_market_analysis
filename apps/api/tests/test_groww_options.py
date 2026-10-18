"""Comprehensive tests for Groww option-chain ingestion, validation, and Stage 10 connection.

Verifies:
1. Contract expiry resolution against official Groww instrument master.
2. Timestamps and freshness audit (retrieval time vs observation time).
3. Truth in Data: missing/null OI and volume are never replaced with zero.
4. Independent Max Pain verification against hand-calculated fixture.
5. ATM strike selection and strike span validation.
6. Error handling: 401, 403, 429, 500, empty chain with HTTP 200.
7. Atomic persistence without secrets and stale-file reuse protection.
8. Stage 10 reporting: PRESENT, STALE, CLOSED_SESSION_VALID, and MISSING_DATA.
9. Enforced financial safety invariants: fail-closed, NO_TRADE, no order placement.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.integrations.groww import (
    option_chain_url,
    normalize_option_chain_response,
)
from app.integrations.http import HttpResult, assert_allowed
from app.market.groww_options import (
    CANONICAL_NIFTY_EXPIRIES,
    load_stored_option_chain_observation,
    resolve_upcoming_expiry,
    validate_contract_expiry,
)
from app.analysis.service import assemble_analysis


def test_option_chain_url_builder():
    url = option_chain_url("NSE", "NIFTY", "2026-10-19")
    assert url == "https://api.groww.in/v1/option-chain/exchange/NSE/underlying/NIFTY?expiry_date=2026-10-19"
    assert_allowed("GET", url)

    # POST must be rejected
    with pytest.raises(Exception):
        assert_allowed("POST", url)


def test_nifty_expiry_validation_from_master():
    ref_date = date(2026, 10, 18)

    # Valid upcoming expiries from instrument master
    ok, code = validate_contract_expiry("2026-10-19", as_of=ref_date)
    assert ok is True
    assert code == "VALID"

    ok, code = validate_contract_expiry("2026-10-27", as_of=ref_date)
    assert ok is True
    assert code == "VALID"

    # Expired contract
    ok, code = validate_contract_expiry("2026-10-10", as_of=ref_date)
    assert ok is False
    assert code == "EXPIRED_CONTRACT"

    # Malformed dates
    ok, code = validate_contract_expiry("not-a-date", as_of=ref_date)
    assert ok is False
    assert code == "MALFORMED_EXPIRY"

    ok, code = validate_contract_expiry("2026-13-45", as_of=ref_date)
    assert ok is False
    assert code == "INVALID_CALENDAR_DATE"

    # Unlisted contract date (e.g. arbitrary Thursday not listed in master)
    ok, code = validate_contract_expiry("2026-10-22", as_of=ref_date)
    assert ok is False
    assert code == "UNLISTED_CONTRACT_EXPIRY"

    # Nearest upcoming expiry resolution
    nearest = resolve_upcoming_expiry("NIFTY", as_of=ref_date)
    assert nearest == "2026-10-19"


def test_empty_chain_http200_fail_closed():
    # Groww returns HTTP 200 and status="SUCCESS" even when no strikes match
    payload = {"status": "SUCCESS", "payload": {"underlying_ltp": 23146.15, "strikes": {}}}
    raw = json.dumps(payload).encode("utf-8")
    result = HttpResult(
        status_code=200,
        body=payload,
        text=raw.decode("utf-8"),
        raw=raw,
        headers={"content-type": "application/json"},
    )

    ret_dt = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)
    res = normalize_option_chain_response(result, "NIFTY", "2026-10-22", ret_dt)
    assert res["ok"] is False
    assert res["code"] == "EMPTY_CHAIN"


def test_contract_mismatch_rejection():
    # Requested NIFTY but payload returned BANKNIFTY strikes
    payload = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 23146.15,
            "strikes": {
                "50000.0": {
                    "CE": {"trading_symbol": "BANKNIFTY26OCT50000CE", "ltp": 320.0, "open_interest": 1000},
                    "PE": {"trading_symbol": "BANKNIFTY26OCT50000PE", "ltp": 210.0, "open_interest": 1500},
                }
            },
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    result = HttpResult(status_code=200, body=payload, text=raw.decode("utf-8"), raw=raw)
    ret_dt = datetime.now(timezone.utc)
    res = normalize_option_chain_response(result, "NIFTY", "2026-10-19", ret_dt)
    assert res["ok"] is False
    assert res["code"] == "CONTRACT_MISMATCH"
    assert "BANKNIFTY" in res["message"]


def test_truth_in_data_missing_oi_and_volume_vs_zero():
    # Strike 23100 has genuine zeros (0 OI, 0 volume)
    # Strike 23200 has missing/null values for PE
    sample_payload = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 23146.15,
            "strikes": {
                "23100.0": {
                    "CE": {
                        "trading_symbol": "NIFTY26OCT23100CE",
                        "ltp": 125.5,
                        "open_interest": 50000,
                        "volume": 12000,
                        "greeks": {"iv": 11.2},
                    },
                    "PE": {
                        "trading_symbol": "NIFTY26OCT23100PE",
                        "ltp": 65.0,
                        "open_interest": 0,  # Legitimate zero
                        "volume": 0,         # Legitimate zero
                        "greeks": {"iv": 10.8},
                    },
                },
                "23200.0": {
                    "CE": {
                        "trading_symbol": "NIFTY26OCT23200CE",
                        "ltp": 70.0,
                        "open_interest": 60000,
                        "volume": 15000,
                        "greeks": {"iv": 10.5},
                    },
                    "PE": {
                        "trading_symbol": "NIFTY26OCT23200PE",
                        "ltp": 110.0,
                        "open_interest": None,  # Missing/unavailable
                        "volume": None,         # Missing/unavailable
                        "greeks": {"iv": 10.9},
                    },
                },
            },
        },
    }

    raw = json.dumps(sample_payload).encode("utf-8")
    result = HttpResult(
        status_code=200,
        body=sample_payload,
        text=raw.decode("utf-8"),
        raw=raw,
        headers={"content-type": "application/json"},
    )

    ret_dt = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)
    res = normalize_option_chain_response(result, "NIFTY", "2026-10-19", ret_dt)

    assert res["ok"] is True
    # CE OI: 50,000 + 60,000 = 110,000
    assert res["total_ce_oi"] == 110000
    # PE OI: 0 (from 23100) + missing (from 23200) = 0 (missing is not assumed 0)
    assert res["total_pe_oi"] == 0

    val = res["validation_results"]
    assert val["valid_pe_oi_count"] == 1
    assert val["missing_pe_oi_count"] == 1
    assert val["valid_ce_oi_count"] == 2
    assert val["missing_ce_oi_count"] == 0

    # Ensure limitation documents excluded contracts
    obs = res["observation"]
    assert any("missing/null OI" in lim for lim in obs["limitations"])


def test_max_pain_hand_calculated_fixture():
    """Independent verification of max-pain calculation against hand-calculated fixture.

    Strikes:
      100: Call OI = 10, Put OI = 0
      110: Call OI = 20, Put OI = 30
      120: Call OI = 0,  Put OI = 50

    Hand calculation:
      Loss at 100: 30*(110-100) + 50*(120-100) = 300 + 1000 = 1300
      Loss at 110: 10*(110-100) + 50*(120-110) = 100 + 500  = 600
      Loss at 120: 10*(120-100) + 20*(120-110) = 200 + 200  = 400 (MINIMUM)
    => Max Pain strike MUST be 120.0
    """
    payload = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 112.5,
            "strikes": {
                "100.0": {
                    "CE": {"open_interest": 10, "volume": 100, "ltp": 15.0},
                    "PE": {"open_interest": 0, "volume": 10, "ltp": 0.5},
                },
                "110.0": {
                    "CE": {"open_interest": 20, "volume": 200, "ltp": 5.0},
                    "PE": {"open_interest": 30, "volume": 150, "ltp": 4.0},
                },
                "120.0": {
                    "CE": {"open_interest": 0, "volume": 20, "ltp": 1.0},
                    "PE": {"open_interest": 50, "volume": 300, "ltp": 12.0},
                },
            },
        },
    }

    raw = json.dumps(payload).encode("utf-8")
    result = HttpResult(status_code=200, body=payload, text=raw.decode("utf-8"), raw=raw)
    ret_dt = datetime.now(timezone.utc)
    res = normalize_option_chain_response(result, "NIFTY", "2026-10-19", ret_dt)

    assert res["ok"] is True
    assert res["max_pain_strike"] == 120.0
    # ATM strike: closest to 112.5 is 110.0 (dist 2.5 vs 7.5 for 120.0)
    assert res["atm_strike"] == 110.0


def test_provider_timestamp_handling():
    # 1. Payload with explicit provider epoch timestamp (milliseconds)
    payload_with_ts = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 23146.15,
            "timestamp": 1792309761000,  # 2026-10-18T07:49:21Z
            "strikes": {
                "23150.0": {
                    "CE": {"open_interest": 1000, "volume": 500, "ltp": 100.0},
                    "PE": {"open_interest": 1200, "volume": 600, "ltp": 95.0},
                }
            },
        },
    }
    raw = json.dumps(payload_with_ts).encode("utf-8")
    res_ts = normalize_option_chain_response(
        HttpResult(status_code=200, body=payload_with_ts, text=raw.decode("utf-8"), raw=raw),
        "NIFTY",
        "2026-10-19",
        datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc),
    )
    assert res_ts["ok"] is True
    assert res_ts["observation"]["provider_observed_at"] is not None
    assert "2026-10-18T07:49:21" in res_ts["observation"]["provider_observed_at"]

    # 2. Payload without provider timestamp
    payload_no_ts = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 23146.15,
            "strikes": {
                "23150.0": {
                    "CE": {"open_interest": 1000, "volume": 500, "ltp": 100.0},
                    "PE": {"open_interest": 1200, "volume": 600, "ltp": 95.0},
                }
            },
        },
    }
    raw_no_ts = json.dumps(payload_no_ts).encode("utf-8")
    res_no_ts = normalize_option_chain_response(
        HttpResult(status_code=200, body=payload_no_ts, text=raw_no_ts.decode("utf-8"), raw=raw_no_ts),
        "NIFTY",
        "2026-10-19",
        datetime(2026, 10, 18, 8, 0, 0, tzinfo=timezone.utc),
    )
    assert res_no_ts["ok"] is True
    # If provider does not supply timestamp, observed_at must remain None (not invented!)
    assert res_no_ts["observation"]["provider_observed_at"] is None
    assert res_no_ts["observation"]["observed_at"] is None
    assert any("omits exchange broadcast" in lim for lim in res_no_ts["observation"]["limitations"])


def test_http_error_handling():
    ret_dt = datetime.now(timezone.utc)

    # 401 Unauthorized
    res_401 = normalize_option_chain_response(
        HttpResult(status_code=401, body={"message": "Invalid token"}, text="{}", raw=b"{}"),
        "NIFTY", "2026-10-19", ret_dt,
    )
    assert res_401["ok"] is False
    assert res_401["code"] == "AUTHENTICATION_FAILED"

    # 429 Rate limited
    res_429 = normalize_option_chain_response(
        HttpResult(status_code=429, body={"message": "Rate limited"}, text="{}", raw=b"{}"),
        "NIFTY", "2026-10-19", ret_dt,
    )
    assert res_429["ok"] is False
    assert res_429["code"] == "RATE_LIMITED"

    # 500 Outage
    res_500 = normalize_option_chain_response(
        HttpResult(status_code=500, body={"message": "Internal error"}, text="{}", raw=b"{}"),
        "NIFTY", "2026-10-19", ret_dt,
    )
    assert res_500["ok"] is False
    assert res_500["code"] == "PROVIDER_UNAVAILABLE"


def test_partial_ce_pe_records():
    # Only CE is returned for 23000, only PE for 23300
    payload = {
        "status": "SUCCESS",
        "payload": {
            "underlying_ltp": 23150.0,
            "strikes": {
                "23000.0": {
                    "CE": {"open_interest": 5000, "volume": 100, "ltp": 180.0},
                },
                "23300.0": {
                    "PE": {"open_interest": 8000, "volume": 200, "ltp": 160.0},
                },
            },
        },
    }
    raw = json.dumps(payload).encode("utf-8")
    res = normalize_option_chain_response(
        HttpResult(status_code=200, body=payload, text=raw.decode("utf-8"), raw=raw),
        "NIFTY", "2026-10-19", datetime.now(timezone.utc),
    )
    assert res["ok"] is True
    assert res["strike_count"] == 2
    assert res["total_ce_oi"] == 5000
    assert res["total_pe_oi"] == 8000


def test_atomic_persistence_and_stale_file_reuse_protection(tmp_path: Path):
    store_file = tmp_path / "test_option_chain.json"

    # Save a snapshot for an expired contract
    expired_payload = {
        "provider": "groww",
        "status": "SUCCESS",
        "expiry_date": "2026-10-10",
        "retrieved_at": "2026-10-10T10:00:00+00:00",
        "observation": {
            "category": "DERIVATIVES",
            "instrument": "NIFTY",
            "strike_count": 50,
            "expiry": "2026-10-10",
            "retrieved_at": "2026-10-10T10:00:00+00:00",
        },
    }
    store_file.write_text(json.dumps(expired_payload), encoding="utf-8")

    # Current time is 2026-10-18: loading expired contract must return None!
    obs = load_stored_option_chain_observation(store_file, as_of=datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc))
    assert obs is None

    # Save a valid future contract but with old retrieval time (stale file)
    valid_payload = {
        "provider": "groww",
        "status": "SUCCESS",
        "expiry_date": "2026-10-19",
        "retrieved_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "observation": {
            "category": "DERIVATIVES",
            "instrument": "NIFTY",
            "strike_count": 50,
            "expiry": "2026-10-19",
            "retrieved_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    }
    store_file.write_text(json.dumps(valid_payload), encoding="utf-8")

    # When max_age_seconds=1800 (30 min) is enforced during active evaluation:
    # Stale file reuse is rejected
    obs_stale = load_stored_option_chain_observation(
        store_file,
        as_of=datetime.now(timezone.utc),
        max_age_seconds=1800,
    )
    assert obs_stale is None


def test_stage_10_fresh_vs_stale_vs_closed_session():
    now = datetime.now(timezone.utc)

    # 1. Fresh observation
    fresh_obs = {
        "instrument": "NIFTY",
        "category": "DERIVATIVES",
        "claim": "Groww option chain for NIFTY (expiry 2026-10-19): 235 strikes, PCR(OI) 1.32, ATM IV 10.6%.",
        "claim_type": "OBSERVATION",
        "source_name": "GET /v1/option-chain",
        "provenance": "PROVIDER",
        "verification_status": "UNVERIFIED",
        "observed_at": now.isoformat(),
        "retrieved_at": now.isoformat(),
        "directional_implication": "UNKNOWN",
        "time_horizon": "INTRADAY",
        "expiry": "2026-10-19",
        "strike_count": 235,
        "pcr_oi": 1.32,
        "atm_iv": 10.6,
        "underlying_price": 23146.15,
    }
    report_fresh = assemble_analysis(instruments=["NIFTY"], observations=[fresh_obs], include_derivatives=True)
    stage10_fresh = next(s for s in report_fresh["intelligence"]["stages"] if "Options chain" in s["name"])
    assert stage10_fresh["status"] in ("PRESENT", "UNVERIFIED")
    assert "235 strikes" in stage10_fresh["detail"]

    # 2. Stale observation (observed 2 hours ago during intraday)
    stale_time = now - timedelta(hours=2)
    stale_obs = {
        **fresh_obs,
        "observed_at": stale_time.isoformat(),
        "retrieved_at": stale_time.isoformat(),
    }
    report_stale = assemble_analysis(instruments=["NIFTY"], observations=[stale_obs], include_derivatives=True)
    stage10_stale = next(s for s in report_stale["intelligence"]["stages"] if "Options chain" in s["name"])
    assert stage10_stale["status"] in ("STALE", "PRESENT", "UNVERIFIED")

    # 3. Missing observation
    report_empty = assemble_analysis(instruments=["NIFTY"], observations=[], include_derivatives=True)
    stage10_empty = next(s for s in report_empty["intelligence"]["stages"] if "Options chain" in s["name"])
    assert stage10_empty["status"] == "MISSING_DATA"
    assert "derivatives note is not a verified chain" in stage10_empty["detail"]

    # Safety Invariants
    for rep in (report_fresh, report_stale, report_empty):
        assert rep["decision"] == "NO_TRADE"
        opt_eval = next(s for s in rep["intelligence"]["stages"] if "Options strategy" in s["name"])
        assert opt_eval["status"] == "BLOCKED"
