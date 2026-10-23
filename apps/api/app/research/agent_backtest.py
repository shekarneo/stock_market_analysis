"""Historical track record of the price-based agents, measured on real Groww NIFTY data.

The real agent code is replayed (LLM off, so the deterministic rule is what is scored) at
fixed intraday checkpoints on every completed session. At checkpoint T the agent sees what
it sees live: the latest price and the previous session's close. Each BULLISH / BEARISH call
is scored against what NIFTY did next:

- rest of day: session close vs the price at T (the horizon an intraday call is about);
- next session: the next session's close vs the price at T.

Reported per checkpoint and horizon: hit rate with Wilson 95% CI and binomial p-value vs
50%, the "always bullish" baseline, calibration of the stated confidence, and the
after-cost return of following the call with index futures, split by time into
development and holdout. Agents whose inputs cannot be replayed without look-ahead
(news, macro, LLM output) are not scored here; they are scored going forward.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable

import numpy as np
from scipy import stats

from app.forecasting.evaluation import FuturesCostModel, wilson_interval

CHECKPOINTS = ("10:15", "12:00", "14:00")  # IST time the call is made (end of a 15m bar)
CONF_BUCKETS = ((0.60, 0.65), (0.65, 0.70), (0.70, 0.75), (0.75, 0.81))
HOLDOUT_FRACTION = 0.2


def sessions_from_15m(rows: list[list]) -> list[dict]:
    """Completed regular-session bars grouped by day: {day, bars: {bar_end 'HH:MM' -> close}, close}."""
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        ts = str(r[0])
        start = ts[11:16]
        if not ("09:15" <= start <= "15:15"):
            continue
        h, m = int(start[:2]), int(start[3:5]) + 15
        end = f"{h + m // 60:02d}:{m % 60:02d}"
        by_day.setdefault(ts[:10], {})[end] = float(r[4])
    out = []
    for day in sorted(by_day):
        bars = by_day[day]
        if "15:30" not in bars:  # the session's last bar must be present to know its close
            continue
        out.append({"day": day, "bars": bars, "close": bars["15:30"]})
    return out


def technical_call(price: float, prev_close: float, *, node: Callable | None = None) -> tuple[str, float | None]:
    """Bias from the real Technical Analyst node on live-shaped evidence (LLM off); the
    confidence is the rule's own stated value, so calibration is judged against what the
    rule claims and the replay never depends on a previous backtest."""
    from app.analysis.agent_nodes import technical_stated_confidence

    if node is None:
        from app.analysis.agent_nodes import technical_analyst_node as node
    state = {
        "instruments": ["NIFTY"],
        "enable_agent_llm": False,
        "agent_outputs": {},
        "evidence": [{
            "evidence_id": "bt", "category": "INDIAN_MARKET", "instrument": "NIFTY",
            "last_price": price, "ohlc": {"close": prev_close},
        }],
    }
    bias = node(state)["agent_outputs"]["technical_analyst"]["directional_bias"]
    stated = technical_stated_confidence((price - prev_close) / prev_close) if bias in ("BULLISH", "BEARISH") else None
    return bias, stated


def _score(calls: list[dict], horizon: str, cost_per_side: float) -> dict:
    active = [c for c in calls if c["bias"] in ("BULLISH", "BEARISH") and c.get(horizon) is not None]
    n = len(active)
    if n == 0:
        return {"n_calls": 0}
    hits = sum(1 for c in active if (c["bias"] == "BULLISH") == (c[horizon] > 0))
    up_share = float(np.mean([c[horizon] > 0 for c in calls if c.get(horizon) is not None]))
    bull_share = float(np.mean([c["bias"] == "BULLISH" for c in active]))
    # Expected hit rate of a coin that says BULLISH as often as the agent does, given the up rate
    baseline = bull_share * up_share + (1 - bull_share) * (1 - up_share)
    pnl = np.array([(1 if c["bias"] == "BULLISH" else -1) * math.expm1(c[horizon]) - 2 * cost_per_side for c in active])
    t = stats.ttest_1samp(pnl, 0.0) if n > 2 else None
    calib = []
    for lo, hi in CONF_BUCKETS:
        bucket = [c for c in active if c["confidence"] is not None and lo <= c["confidence"] < hi]
        if bucket:
            bh = sum(1 for c in bucket if (c["bias"] == "BULLISH") == (c[horizon] > 0))
            calib.append({"stated_confidence": f"{lo:.2f}-{min(hi, 0.80):.2f}", "n": len(bucket),
                          "actual_hit_rate": bh / len(bucket)})
    return {
        "n_calls": n,
        "hit_rate": hits / n,
        "hit_rate_ci95": wilson_interval(hits, n),
        "p_value_vs_50pct": float(stats.binomtest(hits, n, 0.5).pvalue),
        "baseline_hit_rate_same_bias_mix": baseline,
        "p_value_vs_baseline": float(stats.binomtest(hits, n, baseline).pvalue) if 0 < baseline < 1 else None,
        "mean_net_return_pct_per_call": float(pnl.mean() * 100),
        "net_return_t_stat": None if t is None else float(t.statistic),
        "net_return_p_value": None if t is None else float(t.pvalue),
        "calibration": calib,
    }


def backtest_technical(sessions: list[dict], *, node: Callable | None = None,
                       cost_per_side: float | None = None, log: Callable[[str], None] = lambda m: None) -> dict:
    cost = cost_per_side if cost_per_side is not None else FuturesCostModel().per_side()
    calls: dict[str, list[dict]] = {cp: [] for cp in CHECKPOINTS}
    for i in range(1, len(sessions)):
        prev, s = sessions[i - 1], sessions[i]
        nxt = sessions[i + 1] if i + 1 < len(sessions) else None
        for cp in CHECKPOINTS:
            price = s["bars"].get(cp)
            if price is None or price <= 0:
                continue
            bias, conf = technical_call(price, prev["close"], node=node)
            calls[cp].append({
                "day": s["day"], "bias": bias, "confidence": conf,
                "rest_of_day": math.log(s["close"] / price),
                "next_session": math.log(nxt["close"] / price) if nxt else None,
            })
        if i % 250 == 0:
            log(f"replayed {i} sessions")
    result: dict[str, Any] = {}
    for cp, rows in calls.items():
        if not rows:
            continue
        cut = int(len(rows) * (1 - HOLDOUT_FRACTION))
        dev, hold = rows[:cut], rows[cut:]
        counts = {b: sum(1 for r in rows if r["bias"] == b) for b in ("BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN")}
        result[cp] = {
            "sessions": len(rows), "first": rows[0]["day"], "last": rows[-1]["day"], "call_counts": counts,
            "holdout_from": hold[0]["day"] if hold else None,
            "rest_of_day": {"all": _score(rows, "rest_of_day", cost), "development": _score(dev, "rest_of_day", cost),
                            "holdout": _score(hold, "rest_of_day", cost)},
            "next_session": {"all": _score(rows, "next_session", cost), "development": _score(dev, "next_session", cost),
                             "holdout": _score(hold, "next_session", cost)},
        }
    return result


def verdict(result: dict) -> dict:
    """Edge only if the holdout beats both 50% and the same-bias baseline (p < 0.05) and pays after costs."""
    best, any_edge = None, False
    for cp, r in result.items():
        for horizon in ("rest_of_day", "next_session"):
            h = r[horizon]["holdout"]
            if not h.get("n_calls"):
                continue
            ok = verdict_row_ok(h)
            any_edge = any_edge or ok
            row = {"checkpoint": cp, "horizon": horizon, "holdout_hit_rate": h["hit_rate"],
                   "holdout_ci95": h["hit_rate_ci95"], "holdout_p": h["p_value_vs_50pct"],
                   "holdout_net_return_pct_per_call": h["mean_net_return_pct_per_call"], "edge": ok}
            if best is None or h["hit_rate"] > best["holdout_hit_rate"]:
                best = row
    return {"edge_supported": any_edge, "best_holdout": best}


def verdict_row_ok(h: dict) -> bool:
    return bool(h["p_value_vs_50pct"] < 0.05 and (h.get("p_value_vs_baseline") or 1) < 0.05
                and h["hit_rate"] > 0.5 and h["mean_net_return_pct_per_call"] > 0
                and (h.get("net_return_p_value") or 1) < 0.05)


def run_agent_backtest(rows_15m: list[list], *, log: Callable[[str], None] = lambda m: None) -> dict:
    sessions = sessions_from_15m(rows_15m)
    technical = backtest_technical(sessions, log=log)
    return {
        "schema": "agent-backtest-1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "instrument": "NIFTY",
        "sessions": len(sessions),
        "agents": {
            "technical_analyst": {
                "rule": "BULLISH if price is >0.10% above the previous close, BEARISH if >0.10% below, else NEUTRAL; "
                        "confidence 0.60 + 10 x |move|, capped at 0.80 (stated, not fitted).",
                "checkpoints": technical,
                "verdict": verdict(technical),
            },
        },
        "not_replayable": {
            "news_event_analyst": "No point-in-time headline archive; scored forward by the agent scorecard.",
            "global_macro_analyst": "Releases before this week are not stored; scored forward.",
            "llm_overrides": "An LLM replaying past days knows what happened next; only forward scoring is honest.",
        },
        "cost_per_side": FuturesCostModel().per_side(),
    }
