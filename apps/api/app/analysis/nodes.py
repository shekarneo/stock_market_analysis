"""Deterministic analysis nodes. A missing provider is reported, not filled in."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from app.analysis.evidence import aware, build_evidence, quarantine_reason
from app.analysis.intelligence import build_intelligence
from app.analysis.schema import GLOBAL_INSTRUMENTS, INDIAN_INSTRUMENTS, MACRO_INSTRUMENTS
from app.analysis.state import AnalysisState

_UNAVAILABLE = {
    "global_context": "No verified global-index feed is configured.",
    "news": "No articles are stored. Fetch the latest market feeds to supply them.",
    "macro": "No verified crude, currency, or macro feed is configured.",
    "indian": "No verified Indian index feed is configured. Quarantined candles are not used.",
    "derivatives": "No verified option-chain provider is configured.",
}


def _status(state: AnalysisState, name: str, status: str) -> dict:
    current = dict(state.get("node_status") or {})
    current[name] = status
    return current


def _as_of(state: AnalysisState) -> datetime:
    parsed = datetime.fromisoformat(state["created_at"])
    return parsed


def validate_node(state: AnalysisState) -> dict:
    as_of = _as_of(state)
    accepted: list[dict] = []
    rejected: list[dict] = []
    invalid_time = 0
    for row in state.get("accepted") or []:
        if not isinstance(row, dict):
            rejected.append({"reason": "An observation was not an object."})
            continue
        reason = quarantine_reason(row)
        if reason:
            rejected.append({"reason": reason, "quarantine_id": row.get("quarantine_id")})
            continue
        if row.get("observed_at") is not None and aware(row.get("observed_at")) is None:
            invalid_time += 1
            rejected.append({"reason": "observed_at must be timezone-aware. It was not replaced with the current time."})
            continue
        if row.get("retrieved_at") is None or aware(row.get("retrieved_at")) is None:
            invalid_time += 1
            rejected.append({"reason": "retrieved_at must be timezone-aware."})
            continue
        item = build_evidence(row, as_of=as_of, horizon=state.get("horizon") or "INTRADAY")
        if item is None:
            rejected.append({"reason": "The observation could not be converted to evidence."})
            continue
        data = item.model_dump(mode="json")
        if "ohlc" in row and row["ohlc"] is not None:
            data["ohlc"] = row["ohlc"]
        if "last_price" in row and row["last_price"] is not None:
            data["last_price"] = row["last_price"]
        if "unit" in row and row["unit"] is not None:
            data["unit"] = row["unit"]
        accepted.append(data)
    quality = "FAIL" if rejected and not accepted else "WARN" if not accepted or rejected else "PASS"
    return {
        "accepted": accepted,
        "rejected": rejected,
        "evidence": [],
        "quality": {
            "status": quality,
            "rejected_count": len(rejected),
            "accepted_count": len(accepted),
            "invalid_timestamps": invalid_time,
            "synthetic_count": sum(1 for row in accepted if row["provenance"] == "SYNTHETIC"),
        },
        "node_status": _status(state, "validate", "COMPLETED"),
        "errors": list(state.get("errors") or []),
        "missing": [],
        "conflicts": [],
    }


def _take(state: AnalysisState, category: str, instruments: tuple[str, ...] | None = None) -> list[dict]:
    rows = []
    for row in state.get("accepted") or []:
        if row.get("category") != category:
            continue
        if instruments is not None and row.get("instrument") not in instruments:
            continue
        rows.append(row)
    return rows


def _missing(names: tuple[str, ...], rows: list[dict]) -> list[str]:
    present = {row.get("instrument") for row in rows}
    return [name for name in names if name not in present]


def global_context(state: AnalysisState) -> dict:
    rows = _take(state, "GLOBAL_MARKET", GLOBAL_INSTRUMENTS)
    missing = _missing(GLOBAL_INSTRUMENTS, rows)
    status = "COMPLETED" if rows else "PROVIDER_UNAVAILABLE"
    return {
        "evidence": list(state.get("evidence") or []) + rows,
        "missing": list(state.get("missing") or []) + [f"global:{name}" for name in missing],
        "node_status": _status(state, "global_context", status),
        "errors": list(state.get("errors") or []) + ([] if rows else [{"node": "global_context", "code": "PROVIDER_UNAVAILABLE", "message": _UNAVAILABLE["global_context"]}]),
    }


def news_node(state: AnalysisState) -> dict:
    if not state.get("include_news", True):
        return {"node_status": _status(state, "news", "SKIPPED")}
    rows = _take(state, "NEWS")
    seen: set[str] = set()
    kept: list[dict] = []
    for row in rows:
        key = (str(row.get("source_name") or "").casefold(), " ".join(str(row.get("claim") or "").casefold().split()))
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    status = "COMPLETED" if kept else "PROVIDER_UNAVAILABLE"
    errors = list(state.get("errors") or [])
    if not kept:
        errors.append({"node": "news", "code": "PROVIDER_UNAVAILABLE", "message": _UNAVAILABLE["news"]})
    return {
        "evidence": list(state.get("evidence") or []) + kept,
        "missing": list(state.get("missing") or []) + ([] if kept else ["news"]),
        "node_status": _status(state, "news", status),
        "errors": errors,
    }


def macro_node(state: AnalysisState) -> dict:
    if not state.get("include_macro", True):
        return {"node_status": _status(state, "macro", "SKIPPED")}
    rows = _take(state, "MACRO", MACRO_INSTRUMENTS) + [row for row in _take(state, "MACRO") if row.get("instrument") not in MACRO_INSTRUMENTS]
    missing = _missing(MACRO_INSTRUMENTS, rows)
    status = "COMPLETED" if rows else "PROVIDER_UNAVAILABLE"
    errors = list(state.get("errors") or [])
    if not rows:
        errors.append({"node": "macro", "code": "PROVIDER_UNAVAILABLE", "message": _UNAVAILABLE["macro"]})
    return {
        "evidence": list(state.get("evidence") or []) + rows,
        "missing": list(state.get("missing") or []) + [f"macro:{name}" for name in missing],
        "node_status": _status(state, "macro", status),
        "errors": errors,
    }


def indian_node(state: AnalysisState) -> dict:
    requested = [name for name in state.get("instruments") or [] if name in INDIAN_INSTRUMENTS]
    wanted = requested or list(INDIAN_INSTRUMENTS)
    rows = [row for row in _take(state, "INDIAN_MARKET", INDIAN_INSTRUMENTS) if row.get("instrument") in wanted]
    missing = [name for name in wanted if name not in {row.get("instrument") for row in rows}]
    status = "COMPLETED" if rows else "PROVIDER_UNAVAILABLE"
    errors = list(state.get("errors") or [])
    if not rows:
        errors.append({"node": "indian", "code": "PROVIDER_UNAVAILABLE", "message": _UNAVAILABLE["indian"]})
    return {
        "evidence": list(state.get("evidence") or []) + rows,
        "missing": list(state.get("missing") or []) + [f"indian:{name}" for name in missing],
        "node_status": _status(state, "indian", status),
        "errors": errors,
    }


def derivatives_node(state: AnalysisState) -> dict:
    if not state.get("include_derivatives", True):
        return {"node_status": _status(state, "derivatives", "SKIPPED")}
    rows = _take(state, "DERIVATIVES")
    status = "COMPLETED" if rows else "PROVIDER_UNAVAILABLE"
    errors = list(state.get("errors") or [])
    if not rows:
        errors.append({"node": "derivatives", "code": "PROVIDER_UNAVAILABLE", "message": _UNAVAILABLE["derivatives"]})
    return {
        "evidence": list(state.get("evidence") or []) + rows,
        "missing": list(state.get("missing") or []) + ([] if rows else ["derivatives"]),
        "node_status": _status(state, "derivatives", status),
        "errors": errors,
    }


def contrarian_node(state: AnalysisState) -> dict:
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in state.get("evidence") or []:
        if row.get("freshness") == "STALE" or row.get("provenance") == "SYNTHETIC":
            continue
        direction = row.get("directional_implication")
        if direction in {"BULLISH", "BEARISH"}:
            grouped[str(row.get("instrument") or "MARKET")].add(direction)
    conflicts = []
    for instrument, directions in grouped.items():
        if directions == {"BULLISH", "BEARISH"}:
            conflicts.append({"instrument": instrument, "directions": sorted(directions)})
    note = {
        "evidence_id": "contrarian-summary",
        "category": "OTHER",
        "claim": "No opposing verified observation was supplied." if not conflicts else "Supplied observations disagree in direction. Both sides are kept.",
        "claim_type": "INTERPRETATION",
        "source_name": "analysis-graph",
        "source_url": None,
        "observed_at": None,
        "published_at": None,
        "retrieved_at": state.get("created_at"),
        "instrument": None,
        "directional_implication": "MIXED" if conflicts else "UNKNOWN",
        "time_horizon": "UNKNOWN",
        "provenance": "DOCUMENTED_SAMPLE",
        "freshness": "UNKNOWN",
        "verification_status": "CONFLICTING" if conflicts else "UNVERIFIED",
        "limitations": ["This note is not a new market fact."],
    }
    marked = []
    conflicted = {item["instrument"] for item in conflicts}
    for row in state.get("evidence") or []:
        copied = dict(row)
        if copied.get("instrument") in conflicted and copied.get("directional_implication") in {"BULLISH", "BEARISH"}:
            copied["verification_status"] = "CONFLICTING"
        marked.append(copied)
    return {
        "evidence": marked + [note],
        "conflicts": conflicts,
        "node_status": _status(state, "contrarian", "COMPLETED"),
    }


def fusion_node(state: AnalysisState) -> dict:
    by_type: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for row in state.get("evidence") or []:
        identifier = str(row.get("evidence_id"))
        if identifier in seen:
            continue
        seen.add(identifier)
        by_type[str(row.get("claim_type") or "OTHER")].append(identifier)
    return {
        "node_status": _status(state, "fusion", "COMPLETED"),
        "quality": {
            **dict(state.get("quality") or {}),
            "claim_types": {key: value for key, value in by_type.items()},
            "confidence": None,
            "provider_errors": list(state.get("errors") or []),
            "missing": list(state.get("missing") or []),
        },
    }


def report_node(state: AnalysisState) -> dict:
    evidence = list(state.get("evidence") or [])
    fresh_verified = [
        row for row in evidence
        if row.get("verification_status") == "VERIFIED" and row.get("freshness") == "FRESH" and row.get("provenance") != "SYNTHETIC"
    ]
    decision = "NO_TRADE"
    status = "INSUFFICIENT_DATA" if not fresh_verified else "COMPLETED"
    directions = {row.get("directional_implication") for row in fresh_verified}
    directional = None
    if directions == {"BULLISH"}:
        directional = "BULLISH"
    elif directions == {"BEARISH"}:
        directional = "BEARISH"
    elif len(directions) > 1:
        directional = "MIXED"
    node_status = _status(state, "report", "COMPLETED")
    bullish = [row.get("evidence_id") for row in evidence if row.get("directional_implication") == "BULLISH"]
    bearish = [row.get("evidence_id") for row in evidence if row.get("directional_implication") == "BEARISH"]
    synthetic = any(row.get("provenance") == "SYNTHETIC" for row in evidence)

    intel = build_intelligence(
        evidence,
        missing=list(state.get("missing") or []),
        conflicts=list(state.get("conflicts") or []),
        instruments=list(state.get("instruments") or []),
    )
    forecast_ready = False
    if state.get("include_forecast"):
        try:
            from app.forecasting.live_forecast import generate_all_live_forecasts, fuse_agents_and_forecast
            live_f = generate_all_live_forecasts()
            forecast_ready = live_f.get("forecast_ready", False)
            has_probs = any(f.get("probability_up") is not None for f in live_f.get("forecasts", []))
            f_status = live_f.get("status") or ("AVAILABLE" if has_probs else "NO_FITTED_MODEL")
            intel["forecast"] = {
                "status": f_status,
                "probabilities": {
                    f["instrument"]: {"up": f["probability_up"], "down": f["probability_down"], "direction": f["direction"]}
                    for f in live_f.get("forecasts", [])
                } if has_probs else None,
                "expected_move": {
                    f["instrument"]: f["expected_move_points"]
                    for f in live_f.get("forecasts", [])
                } if has_probs else None,
                "models": [f["model_version"] for f in live_f.get("forecasts", []) if f.get("model_version")],
                "live_forecasts": live_f.get("forecasts", []),
                "reason": (
                    "Live statistical model predictions computed from registered artifacts."
                    if has_probs else
                    "No approved fitted model artifact produced probabilities. Forecast requires registered model over completed candles."
                ),
            }
            f_map = {f["instrument"]: f for f in live_f.get("forecasts", [])}
            for inst, m in intel.get("markets", {}).items():
                rec = m.get("manual_trade_recommendation")
                f_item = f_map.get(inst)
                if rec and f_item:
                    fusion = fuse_agents_and_forecast(rec, f_item)
                    rec["quant_fusion"] = fusion
                    rec["bias"] = fusion["fused_bias"]
                    rec["conviction"] = fusion["conviction"]
        except Exception:
            pass

    as_of = _as_of(state)
    is_equity_closed = False
    try:
        from app.market.session_intelligence import assess_market_session, MarketState
        eq_sess = assess_market_session("NIFTY", as_of)
        is_equity_closed = eq_sess.market_state != MarketState.OPEN
    except Exception:
        pass

    limitations = [
        "No probability was calculated.",
        "Synthetic or fixture evidence is not a live market observation." if synthetic else "No synthetic evidence was added by the graph.",
        "Quarantined candles were not promoted.",
        "This report cannot place an order or change an approval flag.",
    ]
    if is_equity_closed:
        limitations.append("Indian equity cash sessions are CLOSED. Analysis reflects post-close / overnight context.")

    report = {
        "analysis_id": state.get("run_id"),
        "status": status,
        "decision": decision,
        "created_at": state.get("created_at"),
        "timezone": "UTC",
        "instruments": list(state.get("instruments") or []),
        "directional_assessment": directional,
        "confidence": None,
        "bullish_evidence": bullish,
        "bearish_evidence": bearish,
        "contradictions": list(state.get("conflicts") or []),
        "missing": list(state.get("missing") or []),
        "rejected": list(state.get("rejected") or []),
        "node_status": node_status,
        "provider_errors": list(state.get("errors") or []),
        "inference": state.get("inference") or {"status": "NOT_REQUESTED"},
        "limitations": limitations,
        "post_close_context": is_equity_closed,
        "forecast_ready": forecast_ready,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "evidence": evidence,
        "quality": dict(state.get("quality") or {}),
        "intelligence": intel,
    }
    return {"report": report, "node_status": node_status}
