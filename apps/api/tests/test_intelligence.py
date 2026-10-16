from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analysis.service import run_analysis
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


def _row(**overrides):
    body = {
        "instrument": "NIFTY",
        "category": "NEWS",
        "claim": "A supplied item said shipping risk rose.",
        "claim_type": "SOURCE_CLAIM",
        "source_name": "desk-a",
        "provenance": "DOCUMENTED_SAMPLE",
        "published_at": NOW - timedelta(minutes=10),
        "retrieved_at": NOW,
        "directional_implication": "BEARISH",
        "time_horizon": "INTRADAY",
        "claim_kind": "ALLEGATION",
        "event_category": "OIL_SUPPLY",
        "affected_entities": ["NIFTY"],
    }
    body.update(overrides)
    return body


def test_news_dedup_keeps_a_conflict_and_does_not_invent_a_direction():
    report = run_analysis(
        instruments=["NIFTY"],
        created_at=NOW,
        observations=[
            _row(),
            _row(source_name="desk-b"),
            _row(source_name="desk-c", directional_implication="BULLISH", claim_kind="OPINION"),
        ],
    )
    news = report["intelligence"]["news"]
    assert len(news) == 1
    assert news[0]["sources"] == ["desk-a", "desk-b", "desk-c"]
    assert news[0]["conflicts"] is True
    assert news[0]["verification_status"] == "CONFLICTING"
    assert set(news[0]["directions"]) == {"BEARISH", "BULLISH"}
    assert news[0]["published_at"] is not None
    geopolitics = report["intelligence"]["geopolitics"]
    assert geopolitics[0]["confirmed"] is False
    assert "crude oil" in geopolitics[0]["channels"]
    assert "bearish" in geopolitics[0]["bearish_reading"].lower()
    assert "bullish" in geopolitics[0]["bullish_reading"].lower()
    assert report["decision"] == "NO_TRADE"
    assert report["forecast_ready"] is False


def test_stale_news_and_a_contradicting_fixture_print_cannot_confirm():
    report = run_analysis(
        instruments=["NIFTY"],
        created_at=NOW,
        observations=[
            _row(observed_at=NOW - timedelta(days=5), published_at=NOW - timedelta(days=5), retrieved_at=NOW),
            _row(
                category="INDIAN_MARKET",
                claim="A labeled fixture print was higher.",
                provenance="SYNTHETIC",
                directional_implication="BULLISH",
                observed_at=NOW,
                event_category=None,
                claim_kind="UNKNOWN",
            ),
        ],
    )
    item = report["intelligence"]["news"][0]
    assert item["freshness"] == "STALE"
    impact = report["intelligence"]["impact"][0]
    assert impact["expected"] == "BEARISH"
    assert impact["actual"] == "BULLISH"
    assert impact["status"] == "SYNTHETIC_OR_FIXTURE_DATA"
    assert impact["confirms_narrative"] is False
    assert report["intelligence"]["forecast"]["probabilities"] is None
    assert report["intelligence"]["forecast"]["expected_move"] is None


def test_missing_and_quarantined_inputs_stay_no_trade():
    before = len(live_order_calls)
    report = run_analysis(
        instruments=["NIFTY", "SENSEX", "BANKNIFTY"],
        created_at=NOW,
        observations=[{"quarantine_id": "abc", "claim": "Quarantined candles.", "retrieved_at": NOW, "category": "INDIAN_MARKET"}],
    )
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["decision"] == "NO_TRADE"
    assert report["intelligence"]["markets"]["NIFTY"]["status"] == "MISSING_DATA"
    assert report["intelligence"]["options"]["decision"] == "NO_TRADE"
    assert report["intelligence"]["risk"]["veto"] is True
    assert report["intelligence"]["outcome"]["tracked"] is False
    assert report["intelligence"]["outcome"]["calibration"] is None
    assert any(stage["name"] == "FII/DII flows" and stage["status"] == "MISSING_DATA" for stage in report["intelligence"]["stages"])
    assert any("quarantine" in item["reason"].lower() or "Quarantined" in item["reason"] for item in report["rejected"])
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False
    assert PAPER_TRADING_ACTIVE is False
    assert len(live_order_calls) == before
    assert any("positioning" in note["question"].lower() for note in report["intelligence"]["contrarian"])
