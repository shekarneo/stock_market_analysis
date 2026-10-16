from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.market.history import assess_candles, capabilities, features_from_source
from app.market.quality import validate_candle
from app.market.schemas import Candle, DataOrigin, MarketSession
from app.market.timestamp_contract import contract, map_provider_timestamp
from app.market.verified_history import (
    assessment,
    build_trusted_dataset,
    normalize_provider_record,
    requirements_checklist,
    run_readonly_validation,
)
from app.settings import REPO_ROOT

IST = ZoneInfo("Asia/Kolkata")
QUARANTINE = {
    "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057": "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
    "5edd4d3543825aa3a385092b9d16b3938e5995e026cbf3b2ade0872c18414a5d": "878e6b0406f83c8009cd0e47f9cd1466662b7125ed06b065ad9c828bca4bea7b",
}


def _candle(**overrides) -> Candle:
    start = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    body = {
        "instrument_id": "NIFTY",
        "underlying": "NIFTY",
        "interval": "M15",
        "bar_start": start,
        "bar_end": start + timedelta(minutes=15),
        "retrieved_at": start + timedelta(minutes=15),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": None,
        "source_id": "fixture",
        "origin": DataOrigin.SYNTHETIC,
        "session": MarketSession.OPEN,
    }
    body.update(overrides)
    return Candle(**body)


def test_quarantine_files_keep_their_checksums_and_are_not_trusted():
    for name, digest in QUARANTINE.items():
        path = REPO_ROOT / "var" / "history" / "quarantine" / f"{name}.json"
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        assert b"UNVERIFIED_PROVIDER" in raw
    report = assessment()
    assert report["trusted_dataset_created"] is False
    assert report["status"] == "BLOCKED"
    again = build_trusted_dataset()
    assert again["dataset_id"] is None
    assert again["checksum"] is None
    for name, digest in QUARANTINE.items():
        path = REPO_ROOT / "var" / "history" / "quarantine" / f"{name}.json"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_groww_contract_and_independent_sources_stay_blocked():
    facts = contract()
    assert facts["established"] is False
    assert facts["support_response_received"] is False
    mapped = map_provider_timestamp("2026-10-13T09:15:00")
    assert mapped["ok"] is False
    assert mapped["bar_start"] is None
    assert mapped["bar_end"] is None
    assert mapped["source_timezone"] is None
    refused = normalize_provider_record({"timestamp": "2026-10-13T09:15:00", "open": 1, "high": 1, "low": 1, "close": 1})
    assert refused["ok"] is False
    assert refused["normalized"] is None
    quarantined = normalize_provider_record({"quarantine_id": "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057", "timestamp": "2026-10-13T09:15:00"})
    assert quarantined["code"] == "QUARANTINE_REJECTED"
    report = assessment()
    assert report["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert report["unresolved"]
    assert all(item["suitable"] is False for item in report["independent_sources"])
    by_provider = {item["provider"]: item for item in report["independent_sources"]}
    assert "start time" in by_provider["Upstox"]["timestamp_semantics"]
    assert "UNRESOLVED" in by_provider["Upstox"]["timezone_contract"]
    assert "no completeness flag" in by_provider["Zerodha Kite Connect"]["incomplete_candle"]
    assert by_provider["NSE"]["interval"].startswith("Daily")
    assert report["dataset_id"] is None
    assert "IST" not in " ".join(report["documented_facts"])
    assert report["m2_ran"] is False
    assert report["m3_ran"] is False
    assert report["m4_ran"] is False
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False
    public = capabilities()
    assert public["verified_history"]["trusted_dataset_created"] is False
    assert public["real_market_data_verified"] is False
    checklist = requirements_checklist()
    allowed = {"VERIFIED", "UNVERIFIED", "NOT_SUPPORTED", "NOT_APPLICABLE"}
    assert {item["status"] for item in checklist} <= allowed
    assert all(item["citation"] for item in checklist if item["status"] == "VERIFIED")
    assert next(item for item in checklist if item["id"] == "timezone")["status"] == "UNVERIFIED"
    assert next(item for item in checklist if item["id"] == "candle_boundary")["status"] == "UNVERIFIED"
    validation = run_readonly_validation()
    assert validation["provider_requests"] == 0
    assert validation["trusted_dataset_created"] is False
    assert validation["validation"]["status"] == "NOT_RUN"
    assert report["provider_selected"] is None
    assert report["provider_contacted"] is False


def test_quality_rules_do_not_invent_candles_or_volume():
    broken = _candle(high=90.0)
    assert validate_candle(broken).ok is False
    assert any(issue.code == "INVALID_OHLC" for issue in validate_candle(broken).issues)
    missing_volume = _candle()
    assert missing_volume.volume is None
    assert validate_candle(missing_volume).ok is True
    start = datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    first = _candle()
    same_instant = _candle(
        bar_start=datetime(2026, 1, 5, 3, 45, tzinfo=timezone.utc),
        bar_end=datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2026, 1, 5, 4, 0, tzinfo=timezone.utc),
    )
    duplicate = assess_candles([first, same_instant], instrument="NIFTY")
    assert duplicate["duplicate_count"] == 1
    assert duplicate["candle_count"] == 2
    later = _candle(
        bar_start=start + timedelta(minutes=30),
        bar_end=start + timedelta(minutes=45),
        retrieved_at=start + timedelta(minutes=45),
    )
    gapped = assess_candles([first, later], instrument="NIFTY")
    assert gapped["candle_count"] == 2
    assert gapped["missing_interval_count"] >= 1
    reversed_rows = assess_candles([later, first], instrument="NIFTY")
    assert any(item["code"] == "OUT_OF_ORDER" for item in reversed_rows["issues"])
    mismatch = assess_candles([_candle(instrument_id="SENSEX", underlying="SENSEX")], instrument="NIFTY")
    assert any(item["code"] == "INCONSISTENT_INSTRUMENT" for item in mismatch["issues"])


def test_quarantine_cannot_enter_the_feature_pipeline():
    blocked = features_from_source(
        {
            "forecast_eligible": False,
            "real_market_data_verified": False,
            "candle_boundary_role": "UNVERIFIED",
            "label": "UNVERIFIED_PROVIDER",
            "candles": [],
        }
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "QUARANTINE_REJECTED"
    claimed = features_from_source({"forecast_eligible": True, "real_market_data_verified": True, "candles": []})
    assert claimed["code"] == "VERIFICATION_REFUSED"
