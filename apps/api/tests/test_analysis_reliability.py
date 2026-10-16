from __future__ import annotations

import json
from datetime import datetime, timezone

from app.analysis.graph import build_graph
from app.analysis.inference import commentary, retry_after_seconds
from app.analysis.service import run_analysis
from app.execution.orders import live_order_calls
from app.integrations.http import HttpResult
from app.integrations.openai_client import classify

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


def _state():
    return {
        "run_id": "reliability",
        "created_at": NOW.isoformat(),
        "instruments": ["NIFTY"],
        "horizon": "INTRADAY",
        "include_news": True,
        "include_macro": True,
        "include_derivatives": True,
        "accepted": [],
        "inference": {"status": "NOT_REQUESTED"},
    }


class Sequence:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def send(self, method, url, *, headers, json_body, timeout):
        self.calls += 1
        assert "sk-test-openai-key" not in json.dumps(json_body)
        assert "/v1/order/" not in url
        assert "authorization" not in json.dumps(headers).lower() or headers.get("Authorization", "").startswith("Bearer ")
        return self.results.pop(0)


def test_news_exception_leaves_a_partial_report_and_does_not_invent_derivatives():
    def boom(_state):
        raise RuntimeError("news down")

    before = len(live_order_calls)
    result = build_graph({"news": boom}).invoke(_state(), config={"configurable": {"thread_id": "news-fail"}})
    report = result["report"]
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["decision"] == "NO_TRADE"
    assert report["confidence"] is None
    assert any(item["node"] == "news" and item["code"] == "NODE_FAILED" for item in report["provider_errors"])
    assert any(item["node"] == "macro" and item["code"] == "PROVIDER_UNAVAILABLE" for item in report["provider_errors"])
    assert result["node_status"]["indian"] == "PROVIDER_UNAVAILABLE"
    assert "indian:NIFTY" in report["missing"]
    assert "derivatives" in report["missing"]
    assert not any(row.get("category") == "DERIVATIVES" for row in report["evidence"])
    assert len(live_order_calls) == before


def test_missing_report_is_a_failure_and_schema_fields_stay_present(monkeypatch):
    class Broken:
        def invoke(self, state, config=None):
            return {"node_status": {"report": "FAILED"}}

    monkeypatch.setattr("app.analysis.service.get_graph", lambda: Broken())
    report = run_analysis(instruments=["NIFTY"], created_at=NOW)
    assert report["status"] == "FAILED"
    assert report["code"] == "REPORT_FAILED"
    assert report["decision"] == "NO_TRADE"
    assert report["confidence"] is None
    assert report["missing"] == []
    assert report["provider_errors"] == []
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    assert report["real_market_data_verified"] is False


def test_provider_gaps_and_claim_types_remain_visible():
    report = run_analysis(
        instruments=["NIFTY"],
        created_at=NOW,
        observations=[
            {
                "instrument": "NIFTY",
                "category": "INDIAN_MARKET",
                "claim": "A fixture observation.",
                "claim_type": "OBSERVATION",
                "source_name": "fixture",
                "provenance": "SYNTHETIC",
                "observed_at": NOW,
                "retrieved_at": NOW,
                "directional_implication": "BULLISH",
                "time_horizon": "INTRADAY",
            },
            {
                "instrument": "NIFTY",
                "category": "NEWS",
                "claim": "A publisher said the session was quiet.",
                "claim_type": "SOURCE_CLAIM",
                "source_name": "fixture-wire",
                "provenance": "DOCUMENTED_SAMPLE",
                "published_at": NOW,
                "retrieved_at": NOW,
                "directional_implication": "UNKNOWN",
                "time_horizon": "INTRADAY",
            },
        ],
    )
    required = {
        "analysis_id",
        "status",
        "decision",
        "created_at",
        "instruments",
        "confidence",
        "missing",
        "provider_errors",
        "evidence",
        "limitations",
        "forecast_ready",
        "paper_approved",
        "live_approved",
        "real_market_data_verified",
    }
    assert required <= set(report)
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["decision"] == "NO_TRADE"
    assert report["confidence"] is None
    assert "macro:CRUDE" in report["missing"]
    assert "derivatives" in report["missing"]
    kinds = {row["claim_type"] for row in report["evidence"]}
    assert "OBSERVATION" in kinds
    assert "SOURCE_CLAIM" in kinds
    assert any(row["provenance"] == "SYNTHETIC" for row in report["evidence"])
    assert any("not a live market observation" in item for item in report["limitations"])
    assert not any(row["verification_status"] == "VERIFIED" for row in report["evidence"])
    assert not any(row["directional_implication"] == "BEARISH" for row in report["evidence"])
    assert report["forecast_ready"] is False


def test_rate_limit_retry_is_bounded_and_auth_timeout_are_not_retried():
    assert retry_after_seconds({"Retry-After": "1"}) == 1.0
    assert retry_after_seconds({"retry-after": "soon"}) is None
    assert retry_after_seconds({"retry-after": "-1"}) is None
    assert retry_after_seconds({"retry-after": "30"}) is None
    evidence = [{"evidence_id": "abc", "claim": "A fixture claim."}]
    waits: list[float] = []
    success = HttpResult(
        200,
        {"choices": [{"message": {"content": json.dumps({"interpretations": [{"evidence_id": "abc", "note": "Noted.", "directional_implication": "UNKNOWN"}]})}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        "",
    )
    limited = Sequence([HttpResult(429, {"error": {"type": "rate_limit"}}, "", headers={"retry-after": "1"}), success])
    retried = commentary(limited, api_key="sk-test-openai-key", model="gpt-4.1-mini", evidence=evidence, sleeper=waits.append)
    assert retried["status"] == "COMPLETED"
    assert retried["attempts"] == 2
    assert retried["waited_seconds"] == 1.0
    assert waits == [1.0]
    assert limited.calls == 2
    assert retried["interpretations"][0]["evidence_id"] == "abc"
    huge = Sequence([HttpResult(429, {"error": {"type": "rate_limit"}}, "", headers={"retry-after": "30"})])
    skipped = commentary(huge, api_key="sk-test-openai-key", model="gpt-4.1-mini", evidence=evidence, sleeper=waits.append)
    assert skipped["status"] == "RATE_LIMITED"
    assert skipped["attempts"] == 1
    assert skipped["interpretations"] == []
    assert huge.calls == 1
    invalid = Sequence([HttpResult(429, {"error": {"type": "rate_limit"}}, "", headers={"retry-after": "soon"})])
    bad_header = commentary(invalid, api_key="sk-test-openai-key", model="gpt-4.1-mini", evidence=evidence, sleeper=waits.append)
    assert bad_header["attempts"] == 1
    assert invalid.calls == 1
    auth = Sequence([HttpResult(401, {"error": {"message": "bad sk-test-openai-key"}}, "")])
    denied = commentary(auth, api_key="sk-test-openai-key", model="gpt-4.1-mini", evidence=evidence, sleeper=waits.append)
    assert denied["status"] == "INVALID_CREDENTIALS"
    assert denied["attempts"] == 1
    assert "sk-test-openai-key" not in json.dumps(denied)
    assert auth.calls == 1
    timed = Sequence([])

    def raise_timeout(*_args, **_kwargs):
        timed.calls += 1
        raise TimeoutError("slow")

    timed.send = raise_timeout
    expired = commentary(timed, api_key="sk-test-openai-key", model="gpt-4.1-mini", evidence=evidence, sleeper=waits.append)
    assert expired["status"] == "TIMEOUT"
    assert expired["attempts"] == 1
    assert timed.calls == 1
    ok, code, message = classify(HttpResult(429, {}, ""), api_key="sk-test-openai-key", model="gpt-4.1-mini")
    assert ok is False
    assert code == "RATE_LIMITED"
    assert "not retried" in message
