"""Agent accuracy: history replay of the technical rule, measured confidence, locked bias,
skill-weighted consensus, and the forward scorecard."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from app.analysis import agent_scorecard as sc
from app.analysis import track_record as tr
from app.analysis.consensus_engine import compute_specialist_confidence
from app.research import agent_backtest as ab

IST = timezone(timedelta(hours=5, minutes=30))


def _rows_15m(n_days: int, *, momentum: float, seed: int = 5) -> list[list]:
    """Regular-session 15m bars; afternoon drift follows the morning move by `momentum`."""
    rng = np.random.default_rng(seed)
    rows, price, day = [], 20000.0, date(2022, 1, 3)
    while len(rows) < n_days * 25:
        if day.weekday() < 5:
            morning = 0.004 * rng.standard_normal()
            for i in range(25):
                start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST) + timedelta(minutes=15 * i)
                drift = morning / 10 if i < 10 else momentum * morning / 15
                o, price = price, price * math.exp(drift + 0.0008 * rng.standard_normal())
                rows.append([start.isoformat(), o, max(o, price) * 1.0005, min(o, price) * 0.9995, price, None, None])
        day += timedelta(days=1)
    return rows


def test_sessions_need_the_closing_bar():
    rows = _rows_15m(3, momentum=0.0)
    sessions = ab.sessions_from_15m(rows)
    assert len(sessions) == 3 and set(sessions[0]["bars"]) >= {"10:15", "12:00", "14:00", "15:30"}
    assert ab.sessions_from_15m([r for r in rows if not r[0].endswith("15:15:00+05:30")]) == []


def test_replay_scores_stated_confidence_not_a_previous_backtest(tmp_path, monkeypatch):
    # Even with a measured track record on disk, the replay calibrates the rule's own stated confidence
    monkeypatch.setattr(tr, "BACKTEST_PATH", _write_backtest(tmp_path, hit=0.548))
    bias, conf = ab.technical_call(22412.65, 22687.65)
    assert bias == "BEARISH" and conf == pytest.approx(min(0.80, 0.60 + 10 * abs(22412.65 / 22687.65 - 1)))


def test_replay_finds_planted_momentum_and_nothing_in_noise():
    strong = ab.backtest_technical(ab.sessions_from_15m(_rows_15m(400, momentum=1.5)))
    noise = ab.backtest_technical(ab.sessions_from_15m(_rows_15m(400, momentum=0.0, seed=9)))
    s, n = strong["12:00"]["rest_of_day"]["all"], noise["12:00"]["rest_of_day"]["all"]
    assert s["hit_rate"] > 0.6 and s["p_value_vs_50pct"] < 0.01
    assert abs(n["hit_rate"] - 0.5) < 0.08 and n["p_value_vs_50pct"] > 0.01
    assert [c["stated_confidence"] for c in s["calibration"]]  # calibration buckets are reported


def _write_backtest(tmp_path, hit=0.548):
    rec = {"n_calls": 1450, "hit_rate": hit, "hit_rate_ci95": [0.523, 0.574], "p_value_vs_50pct": 0.0003,
           "mean_net_return_pct_per_call": -0.018}
    cp = {"rest_of_day": {"all": rec, "holdout": {"hit_rate": 0.563}}, "next_session": {"all": {**rec, "hit_rate": 0.537}}}
    doc = {"generated_at": "2026-10-23T15:00:00+05:30", "sessions": 1679,
           "agents": {"technical_analyst": {"checkpoints": {"10:15": cp, "12:00": cp, "14:00": cp}}}}
    path = tmp_path / "agent_backtest.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_track_record_picks_the_time_of_day(tmp_path):
    path = _write_backtest(tmp_path)
    noon = tr.technical_track_record(datetime(2026, 10, 23, 12, 30, tzinfo=IST), path=path)
    assert noon["checkpoint"] == "12:00" and noon["horizon"] == "rest_of_day" and noon["hit_rate"] == 0.548
    early = tr.technical_track_record(datetime(2026, 10, 23, 9, 40, tzinfo=IST), path=path)
    assert early["checkpoint"] == "10:15"
    evening = tr.technical_track_record(datetime(2026, 10, 23, 18, 0, tzinfo=IST), path=path)
    assert evening["horizon"] == "next_session" and evening["hit_rate"] == 0.537
    assert tr.technical_track_record(path=tmp_path / "missing.json") is None


def _tech_state(created_at: str, llm: bool = False) -> dict:
    return {"instruments": ["NIFTY"], "enable_agent_llm": llm, "agent_outputs": {}, "created_at": created_at,
            "evidence": [{"evidence_id": "e1", "category": "INDIAN_MARKET", "instrument": "NIFTY",
                          "last_price": 22412.65, "ohlc": {"close": 22687.65}}]}


def test_technical_agent_reports_measured_hit_rate(tmp_path, monkeypatch):
    from app.analysis.agent_nodes import technical_analyst_node

    monkeypatch.setattr(tr, "BACKTEST_PATH", _write_backtest(tmp_path))
    out = technical_analyst_node(_tech_state("2026-10-23T06:35:00+00:00"))["agent_outputs"]["technical_analyst"]
    assert out["directional_bias"] == "BEARISH"
    assert out["confidence"] == pytest.approx(0.548) and out["is_calibrated"] is True
    assert out["semantic_type"] == "MEASURED_HIT_RATE"
    assert any("Measured track record" in f and "54.8%" in f for f in out["findings"])
    assert any("lost money after costs" in lim for lim in out["limitations"])


def test_quote_without_ohlc_uses_saved_previous_close(tmp_path, monkeypatch):
    from app.analysis.agent_nodes import technical_analyst_node
    from app.market import history_loader as hl

    monkeypatch.setattr(tr, "BACKTEST_PATH", tmp_path / "none.json")
    daily = [["2026-10-21T00:00:00+05:30", 1, 1, 1, 22900.0], ["2026-10-22T00:00:00+05:30", 1, 1, 1, 22687.65],
             ["2026-10-23T00:00:00+05:30", 1, 1, 1, 22400.0]]  # today's (forming) row must not be used
    monkeypatch.setattr(hl, "load_series", lambda symbol, interval, root=None: {"candles": daily})
    state = _tech_state("2026-10-23T09:34:00+00:00")
    state["evidence"][0].pop("ohlc")
    out = technical_analyst_node(state)["agent_outputs"]["technical_analyst"]
    assert out["directional_bias"] == "BEARISH"
    assert any("reference close 22,687.65" in f and "2026-10-22" in f for f in out["findings"])


def test_llm_cannot_flip_the_technical_call(tmp_path, monkeypatch):
    from app.analysis import agent_nodes
    from app.analysis.ai_providers import AIProviderRegistry

    monkeypatch.setattr(tr, "BACKTEST_PATH", _write_backtest(tmp_path))

    class Result:
        ok, fallback_used, provider, model = True, False, "openai", "x"
        structured_data = {"directional_bias": "BULLISH", "confidence": 0.95, "findings": ["LLM thinks up"], "limitations": []}
        prompt_tokens = completion_tokens = total_tokens = 0
        latency_ms = 1.0
        error_code = error_message = primary_error_code = primary_error_message = None

    monkeypatch.setattr(AIProviderRegistry, "generate_with_fallback", classmethod(lambda cls, **kw: Result()))
    out = agent_nodes.technical_analyst_node(_tech_state("2026-10-23T06:35:00+00:00", llm=True))["agent_outputs"]["technical_analyst"]
    assert out["directional_bias"] == "BEARISH" and out["confidence"] == pytest.approx(0.548)
    assert any("LLM thinks up" in f for f in out["findings"])  # the explanation is kept


def test_consensus_weights_measured_agents_by_skill():
    measured = {"confidence": 0.548, "semantic_type": "MEASURED_HIT_RATE", "is_calibrated": True}
    assert compute_specialist_confidence(measured) == pytest.approx(0.096)
    assert compute_specialist_confidence({**measured, "confidence": 0.49}) == 0.0
    assert compute_specialist_confidence({"confidence": 0.8}) == 0.8  # stated confidences unchanged


def _today_outputs() -> dict:
    """23 Oct 15:23 IST: price above yesterday's close; news and macro still bearish."""
    measured = {"status": "SUCCESS", "directional_bias": "BULLISH", "confidence": 0.524,
                "semantic_type": "MEASURED_HIT_RATE", "is_calibrated": True, "findings": []}
    stated = {"status": "SUCCESS", "semantic_type": "HEURISTIC_SIGNAL_STRENGTH", "findings": []}
    return {"technical_analyst": measured,
            "news_event_analyst": {**stated, "directional_bias": "BEARISH", "confidence": 0.65},
            "global_macro_analyst": {**stated, "directional_bias": "BEARISH", "confidence": 0.69}}


def test_without_evidence_the_stated_weights_are_unchanged():
    from app.analysis.consensus_engine import evaluate_multi_agent_consensus

    ev = evaluate_multi_agent_consensus(_today_outputs(), provenance_verified=True)
    scores = ev.specialist_scores
    assert scores["news_event_analyst"]["evidence_status"] == "NOT_EVALUATED"
    assert ev.consensus_score < -0.5  # unmeasured bearish agents dominate, as before


def test_unmeasured_agents_keep_a_tenth_of_their_weight():
    from app.analysis.consensus_engine import UNMEASURED_WEIGHT_FACTOR, evaluate_multi_agent_consensus

    before = evaluate_multi_agent_consensus(_today_outputs(), provenance_verified=True).specialist_scores
    ev = evaluate_multi_agent_consensus(_today_outputs(), provenance_verified=True, evidence={})
    s = ev.specialist_scores
    assert s["technical_analyst"]["evidence_status"] == "MEASURED_HISTORY"
    assert s["technical_analyst"]["effective_weight"] == pytest.approx(before["technical_analyst"]["effective_weight"])
    for role in ("news_event_analyst", "global_macro_analyst"):
        assert s[role]["evidence_status"] == "UNMEASURED"
        assert s[role]["effective_weight"] == pytest.approx(before[role]["effective_weight"] * UNMEASURED_WEIGHT_FACTOR)
    # Neither side has real evidence of skill, so no strong direction comes out
    assert abs(ev.consensus_score) < 0.30 and ev.directional_recommendation == "NEUTRAL"


def test_proven_and_disproven_scorecards_set_the_weight():
    from app.analysis.consensus_engine import evaluate_multi_agent_consensus

    evidence = {"news_event_analyst": {"status": "PROVEN", "hit_rate": 0.62},
                "global_macro_analyst": {"status": "NO_EDGE_YET", "hit_rate": 0.51}}
    s = evaluate_multi_agent_consensus(_today_outputs(), provenance_verified=True, evidence=evidence).specialist_scores
    assert s["news_event_analyst"]["evidence_status"] == "PROVEN_FORWARD"
    assert s["news_event_analyst"]["confidence"] == pytest.approx(0.24)  # skill 2 x 0.62 - 1
    assert s["global_macro_analyst"]["evidence_status"] == "NO_EDGE_YET"
    assert s["global_macro_analyst"]["effective_weight"] == 0.0


def test_decision_node_weights_by_the_live_scorecard(monkeypatch):
    from app.analysis import agent_nodes

    monkeypatch.setattr(agent_nodes, "_agent_evidence", lambda: {})  # nothing scored yet
    state = {"instruments": ["NIFTY"], "agent_outputs": _today_outputs(), "evidence": [], "missing": [],
             "quality": {"status": "GOOD"}, "report": {}, "created_at": "2026-10-23T09:53:00+00:00"}
    report = agent_nodes.final_decision_agent_node(state)["report"]
    scores = report["consensus"]["specialist_scores"]
    assert scores["news_event_analyst"]["evidence_status"] == "UNMEASURED"
    assert scores["technical_analyst"]["evidence_status"] == "MEASURED_HISTORY"
    assert report["consensus"]["directional_recommendation"] == "NEUTRAL"
    assert report["decision"] == "NO_TRADE"


def test_evidence_by_agent_reads_the_scorecard(tmp_path):
    path = tmp_path / "calls.jsonl"
    sc._write(path, _daily_calls(60, next_session_return=None))
    ev = sc.evidence_by_agent(path)
    assert ev["news_event_analyst"]["status"] == "PROVEN" and ev["news_event_analyst"]["hit_rate"] == pytest.approx(0.9)
    assert sc.evidence_by_agent(tmp_path / "missing.jsonl") == {}


def _report(bias: str) -> dict:
    return {"analysis_id": f"a-{bias}", "agent_outputs": {
        "technical_analyst": {"status": "SUCCESS", "directional_bias": bias, "confidence": 0.548},
        "options_analyst": {"status": "SKIPPED", "directional_bias": "UNKNOWN"}},
        "consensus": {"directional_recommendation": "NEUTRAL", "consensus_score": -0.2}}


def test_scorecard_records_scores_and_judges(tmp_path):
    path = tmp_path / "calls.jsonl"
    noon = datetime(2026, 10, 22, 12, 0, tzinfo=IST)
    evening = datetime(2026, 10, 22, 19, 0, tzinfo=IST)
    calls = sc.record_agent_calls(_report("BEARISH"), spot=22600.0, at=noon, path=path)
    assert {c["agent"] for c in calls} == {"technical_analyst", "consensus"}  # skipped agents are not recorded
    sc.record_agent_calls(_report("BULLISH"), spot=22500.0, at=evening, path=path)
    assert sc.record_agent_calls(_report("BULLISH"), spot=None, path=path) == []

    first = sc.score_pending({"2026-10-22": 22687.65}, path=path)  # next session not closed yet
    assert first["newly_scored"] == 2 and first["pending"] == 4  # rest-of-day scored at the close
    noon_now = next(r for r in sc._read(path) if r["agent"] == "technical_analyst" and r["in_session"])
    assert noon_now["outcome"]["rest_of_day_return"] > 0 and "next_session_return" not in noon_now["outcome"]
    done = sc.score_pending({"2026-10-22": 22687.65, "2026-10-23": 22450.0}, path=path)
    assert done["newly_scored"] == 4 and done["pending"] == 0
    rows = sc._read(path)
    noon_call = next(r for r in rows if r["agent"] == "technical_analyst" and r["in_session"])
    assert noon_call["outcome"]["rest_of_day_return"] > 0  # BEARISH at 22600, closed 22687.65: wrong
    evening_call = next(r for r in rows if r["agent"] == "technical_analyst" and not r["in_session"])
    assert evening_call["outcome"].get("rest_of_day_return") is None  # made after the close: next session only

    summary = sc.summarize(path)["agents"]["technical_analyst"]
    assert summary["status"] == "COLLECTING" and summary["rest_of_day"]["n"] == 1
    assert summary["rest_of_day"]["hit_rate"] == 0.0 and summary["next_session"]["hit_rate"] == 0.5


def _daily_calls(n: int, **outcome_extra) -> list[dict]:
    """One in-session call per day for n days; 9 in 10 are right."""
    start = date(2026, 1, 1)
    return [{"agent": "news_event_analyst", "bias": "BULLISH", "in_session": True,
             "made_at": f"{start + timedelta(days=i)}T12:00:00+05:30",
             "outcome": {"rest_of_day_return": 0.01 if i % 10 else -0.01, **outcome_extra}} for i in range(n)]


def test_repeat_calls_in_one_session_count_once(tmp_path):
    path = tmp_path / "calls.jsonl"
    # 40 runs in one afternoon: still a single market view
    same_day = [{"agent": "news_event_analyst", "bias": "BEARISH", "in_session": True,
                 "made_at": f"2026-10-23T14:{m:02d}:00+05:30", "outcome": {"rest_of_day_return": -0.01}} for m in range(10, 50)]
    sc._write(path, same_day)
    row = sc.summarize(path)["agents"]["news_event_analyst"]
    assert row["recorded_calls"] == 40 and row["calls"] == 1
    assert row["rest_of_day"]["n"] == 1 and row["status"] == "COLLECTING"
    # An evening call and a pre-open call the next morning are both about the next session: one counts
    evening = {"agent": "news_event_analyst", "bias": "BULLISH", "in_session": False, "made_at": "2026-10-23T19:00:00+05:30"}
    pre_open = {**evening, "made_at": "2026-10-26T08:30:00+05:30"}  # Monday, before the open
    assert len(sc.counted_calls([evening, pre_open])) == 1


def test_pre_open_call_is_scored_on_the_same_days_close(tmp_path):
    path = tmp_path / "calls.jsonl"
    sc._write(path, [{"agent": "macro", "bias": "BULLISH", "in_session": False, "spot": 22600.0,
                      "session_day": "2026-10-26", "made_at": "2026-10-26T08:30:00+05:30", "outcome": None}])
    sc.score_pending({"2026-10-23": 22600.0, "2026-10-26": 22700.0, "2026-10-27": 22800.0}, path=path)
    outcome = sc._read(path)[0]["outcome"]
    assert outcome["next_session_day"] == "2026-10-26"  # the session it was made before, not the one after


def test_scorecard_verdicts(tmp_path):
    path = tmp_path / "calls.jsonl"
    rows = _daily_calls(60, next_session_return=0.01)
    sc._write(path, rows)
    assert sc.summarize(path)["agents"]["news_event_analyst"]["status"] == "PROVEN"
    sc._write(path, [{**r, "bias": "BEARISH"} for r in rows])
    assert sc.summarize(path)["agents"]["news_event_analyst"]["status"] == "WORSE_THAN_CHANCE"


def test_agents_endpoint(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research import multiyear_routes as routes

    monkeypatch.setattr(tr, "BACKTEST_PATH", _write_backtest(tmp_path))
    monkeypatch.setattr(sc, "SCORECARD_PATH", tmp_path / "calls.jsonl")
    monkeypatch.setattr(routes, "read_session", lambda request, settings: {"username": "op"})
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._settings] = lambda: None
    body = TestClient(app).get("/api/research/agents").json()
    assert body["backtest"]["sessions"] == 1679
    assert body["scorecard"]["agents"] == {}
