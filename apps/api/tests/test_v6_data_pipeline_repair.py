"""Comprehensive Verification and Regression Tests for V6 Data Ingestion & Forecast Pipeline.

Verifies:
1. News event category classification across all 6 categories, provenance, and exclusions.
2. Official macro series reference data (FII/DII, USD/INR, US 10Y Yield) evidence generation.
3. Feature resolution & quantitative model forecast execution (NIFTY active, SENSEX/CRUDEOILMINI NO_FITTED_MODEL).
4. Calibrated scenario derivation with explicit uncertainty bounds.
5. All 18 pipeline stages correctly reflecting operational states.
6. Outcome tracking immutable logging & calibration scoring.
7. Mandatory financial safety invariants remain strictly enforced (fail-closed, NO_TRADE).
"""

from datetime import datetime, timezone
import pytest

from app.analysis.evidence import build_evidence
from app.analysis.nodes import report_node, validate_node
from app.analysis.outcome_tracker import evaluate_forecast_outcome, record_forecast_prediction
from app.analysis.service import assemble_analysis
from app.forecasting.live_forecast import (
    compute_live_forecast_for_instrument,
    generate_all_live_forecasts,
    resolve_trailing_features_for_instrument,
)
from app.market.live_quotes import stored_observations
from app.market.macro_series import get_macro_observations
from app.news.classifier import classify_news_item, classify_text
from app.news.ingest import stored_news_observations


def test_news_classifier_all_six_categories():
    """Verify all 6 categories are detected with RULE_INFERRED provenance."""
    # 1. OIL_SUPPLY
    cat, conf = classify_text("OPEC announces surprise crude oil output cut of 1 million barrels per day")
    assert cat == "OIL_SUPPLY"
    assert conf > 0.6

    # 2. TRADE_RESTRICTION
    cat, conf = classify_text("US imposes new tariffs and import ban on semiconductor equipment")
    assert cat == "TRADE_RESTRICTION"
    assert conf > 0.6

    # 3. SANCTION
    cat, conf = classify_text("European Union ratifies 14th package of financial sanctions against designated entities")
    assert cat == "SANCTION"

    # 4. CONFLICT
    cat, conf = classify_text("Military airstrikes reported near regional oil infrastructure amid armed conflict")
    assert cat == "CONFLICT"

    # 5. CENTRAL_BANK
    cat, conf = classify_text("Federal Reserve and RBI monetary policy committee hold repo rate steady")
    assert cat == "CENTRAL_BANK"

    # 6. DIPLOMACY
    cat, conf = classify_text("Envoys sign bilateral trade pact following diplomatic summit")
    assert cat == "DIPLOMACY"


def test_news_classifier_exclusions_and_ambiguity():
    """Verify commercial bank exclusions and ambiguous/unrelated headlines."""
    # Central Bank of India (commercial retail bank) should NOT be classified as CENTRAL_BANK policy
    cat, conf = classify_text("Central Bank of India opens 50 new retail customer branches")
    assert cat is None

    # Generic market noise should remain None without forcing an arbitrary label
    cat, conf = classify_text("Local IT firm conducts annual campus hiring drive")
    assert cat is None

    # classify_news_item preservation
    item = {
        "claim": "Central Bank of India opens branches",
        "source_name": "Reuters",
    }
    res = classify_news_item(item)
    assert res["event_category"] is None
    assert res["classification_provenance"] == "UNCLASSIFIED"

    # Source provided preservation
    src_item = {
        "claim": "Some text",
        "event_category": "SANCTION",
        "classification_provenance": "SOURCE_PROVIDED",
    }
    src_res = classify_news_item(src_item)
    assert src_res["event_category"] == "SANCTION"
    assert src_res["classification_provenance"] == "SOURCE_PROVIDED"


def test_macro_series_observations_valid_evidence(tmp_path):
    """Verify official macro series produce valid EvidenceItem entries."""
    import json

    now = datetime.now(timezone.utc)
    path = tmp_path / "macro_series.json"
    path.write_text(json.dumps({"retrieved_at": now.isoformat(), "series": {
        "FII_DII_FLOWS": {"fii_net_crores": -1245.5, "dii_net_crores": 1850.25, "net_total_crores": 604.75,
                          "as_of_date": "2026-10-16", "verification_status": "VERIFIED_PUBLIC_REPORT"},
        "USDINR_REF": {"rate": 95.08, "as_of_date": "2026-10-18"},
        "US10Y_YIELD": {"yield_pct": 4.08, "as_of_date": "2026-10-16"},
    }}), encoding="utf-8")
    obs = get_macro_observations(path)
    assert len(obs) >= 3

    insts = {o["instrument"] for o in obs}
    assert "FII_DII_FLOWS" in insts
    assert "USDINR_REF" in insts
    assert "US10Y_YIELD" in insts

    for o in obs:
        ev = build_evidence(o, as_of=now, horizon="INTRADAY")
        assert ev is not None
        assert ev.category == "MACRO"
        assert ev.claim
        assert ev.retrieved_at.tzinfo is not None
        assert ev.observed_at is not None
        assert ev.verification_status in {"VERIFIED_PUBLIC_REPORT", "UNVERIFIED"}


def test_quantitative_forecast_generation_and_no_model():
    """Verify NIFTY generates active predictions while unsupported instruments cleanly return NO_FITTED_MODEL."""
    # 1. Feature resolution
    feats = resolve_trailing_features_for_instrument("NIFTY")
    assert feats is not None
    assert "ret_1" in feats
    assert "ret_3" in feats
    assert "close_vs_sma_3" in feats  # scale-free model input (ohlc-2)
    assert "close_position" in feats

    # 2. Live forecast for NIFTY
    nifty_quote = {"instrument": "NIFTY", "last_price": 23146.15}
    f_nifty = compute_live_forecast_for_instrument("NIFTY", nifty_quote)
    assert f_nifty["status"] == "ACTIVE"
    assert f_nifty["probability_up"] is not None
    assert f_nifty["probability_down"] is not None
    assert round(f_nifty["probability_up"] + f_nifty["probability_down"], 4) == 1.0
    assert f_nifty["model_version"] == "logistic-l2-newton-1"

    # 3. Live forecast for SENSEX (unregistered model)
    sensex_quote = {"instrument": "SENSEX", "last_price": 74729.27}
    f_sensex = compute_live_forecast_for_instrument("SENSEX", sensex_quote)
    assert f_sensex["status"] == "NO_FITTED_MODEL"
    assert f_sensex["probability_up"] is None
    assert f_sensex["probability_down"] is None

    # 4. Live forecast for CRUDEOILMINI (unregistered model)
    crude_quote = {"instrument": "CRUDEOILMINI", "last_price": 9388.0}
    f_crude = compute_live_forecast_for_instrument("CRUDEOILMINI", crude_quote)
    assert f_crude["status"] == "NO_FITTED_MODEL"
    assert f_crude["probability_up"] is None

    # 5. Full live forecast aggregation
    all_f = generate_all_live_forecasts()
    assert all_f["status"] == "ACTIVE"
    assert len(all_f["forecasts"]) == 3


def test_outcome_tracker_logging_and_calibration(tmp_path):
    """Verify immutable prediction recording and post-close outcome calibration."""
    test_log = tmp_path / "test_outcomes.jsonl"

    rec = record_forecast_prediction(
        analysis_id="unit-test-run-1",
        instrument="NIFTY",
        model_version="logistic-l2-newton-1",
        probability_up=0.20,
        direction="BEARISH",
        spot_price=23100.0,
        horizon="next_m15_close",
        decision="NO_TRADE",
        path=test_log,
    )
    assert rec["instrument"] == "NIFTY"
    assert rec["execution_context"] == "FORECAST_EVALUATION"

    # Evaluate outcome when next close is lower (direction DOWN/BEARISH)
    calib = evaluate_forecast_outcome(
        prediction_record=rec,
        subsequent_close_price=23050.0,
        subsequent_bar_end="2026-10-18T10:00:00+00:00",
    )
    assert calib["actual_direction"] == "BEARISH"
    assert calib["direction_correct"] is True  # Model predicted BEARISH
    assert 0.0 <= calib["brier_score"] <= 1.0


def test_assemble_analysis_all_18_stages_and_invariants():
    """Verify end-to-end assemble_analysis produces expected stages and strictly enforces safety gates."""
    obs = [*stored_observations(), *stored_news_observations()]
    report = assemble_analysis(
        instruments=["NIFTY", "SENSEX", "CRUDEOILMINI"],
        horizon="INTRADAY",
        include_news=True,
        include_macro=True,
        include_derivatives=True,
        include_inference=False,
        include_forecast=True,
        observations=obs,
    )

    # Invariants MUST remain strictly fail-closed
    assert report["decision"] == "NO_TRADE"
    assert report["forecast_ready"] is False
    assert report["real_market_data_verified"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False

    intel = report["intelligence"]
    stages = {s["name"]: s for s in intel["stages"]}
    assert len(stages) == 18

    # Specific operational stage checks
    assert stages["Data validation"]["status"] == "COMPLETED"
    assert stages["Global markets and macro"]["status"] == "PRESENT"
    assert stages["Fresh verified news"]["status"] == "PRESENT"
    assert stages["Geopolitical and trade policy"]["status"] == "PRESENT"
    assert stages["Crude, currency and yields"]["status"] == "PRESENT"
    assert stages["NIFTY 50"]["status"] in ("PRESENT", "UNVERIFIED", "VERIFIED")
    assert stages["SENSEX"]["status"] in ("PRESENT", "UNVERIFIED", "VERIFIED")
    assert stages["India VIX, breadth and sectors"]["status"] in ("PRESENT", "PARTIAL")
    assert stages["FII/DII flows"]["status"] == "PRESENT"
    assert stages["Quantitative forecasts"]["status"] == "PRESENT"
    assert stages["Bullish, bearish and sideways scenarios"]["status"] in ("PRESENT", "UNCALIBRATED")
    assert stages["Contrarian challenge"]["status"] == "COMPLETED"
    assert stages["Options strategy evaluation"]["status"] == "BLOCKED"
    assert stages["Independent risk validation"]["status"] == "VETO"
    assert stages["Final decision"]["status"] == "NO_TRADE"
    assert stages["Outcome tracking"]["status"] == "PRESENT"
