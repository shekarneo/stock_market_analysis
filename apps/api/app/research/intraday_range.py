"""Rest-of-day range forecast for NIFTY, updated through the session from the live Groww quote.

At each checkpoint (09:30, 09:45, ... 15:15 IST: after k of the 25 regular 15-minute bars)
the target is how far NIFTY travels between now and the close:

    R = log(max(high_rest, price) / min(low_rest, price))

plus where that travel goes: the rest-of-day high above the current price, the low below it,
and the close relative to it.

Inputs are only what is known at the checkpoint and what the live quote can supply: the
day's open / high / low so far and the last price (Groww quote `ohlc` + `last_price`), the
previous close, the previous sessions' daily ranges (saved Groww daily history) and the
previous India VIX close.

Evaluation: one model per checkpoint, walk-forward over sessions (expanding window), model
chosen on the development period by mean squared log error, holdout reported once.
Diebold-Mariano on per-session mean loss (rows within a session are not independent).
Bands are quantiles of development errors; their coverage is checked on the holdout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import numpy as np

from app.research import daily_research as dr

SESSION_BARS = 25                      # 09:15 .. 15:15 bar starts
FIRST_BAR = time(9, 15)
CHECKPOINTS = range(1, SESSION_BARS)   # k bars done: 09:30 .. 15:15
FLOOR = 1e-5                           # log of a zero range is undefined; a flat stretch is ~0.001%
MIN_TRAIN_SESSIONS = 250


def checkpoint_label(k: int) -> str:
    t = datetime.combine(datetime.min, FIRST_BAR) + timedelta(minutes=15 * k)
    return t.strftime("%H:%M")


# ------------------------------------------------------------------------------ data

@dataclass(frozen=True)
class Context:
    """What is known before the session opens."""
    prev_close: float
    log_rv1: float
    log_rv5: float
    log_rv22: float
    log_vix: float | None


def _log_range(high: float, low: float) -> float:
    return max(math.log(high / low), FLOOR)


def _context(prev: list[dr.Bar], vix_close: float | None) -> Context:
    """From the 22 sessions before the day and the last VIX close before it."""
    ranges = [_log_range(b.high, b.low) for b in prev]
    return Context(
        prev_close=prev[-1].close,
        log_rv1=math.log(ranges[-1]),
        log_rv5=math.log(sum(ranges[-5:]) / 5),
        log_rv22=math.log(sum(ranges) / 22),
        log_vix=math.log(vix_close) if vix_close and vix_close > 0 else None,
    )


def _vix_before(vix: list[dr.Bar] | None, day: str) -> float | None:
    before = [b for b in vix or [] if b.day < day]
    return before[-1].close if before else None


def contexts(daily: list[dr.Bar], vix: list[dr.Bar] | None) -> dict[str, Context]:
    """Per session day: the context from the sessions before it (22 needed)."""
    vix_sorted = sorted(vix or [], key=lambda b: b.day)
    out, j, last_vix = {}, 0, None
    for i in range(22, len(daily)):
        while j < len(vix_sorted) and vix_sorted[j].day < daily[i].day:
            last_vix = vix_sorted[j].close
            j += 1
        out[daily[i].day] = _context(daily[i - 22:i], last_vix)
    return out


def context_for(day: str, daily: list[dr.Bar], vix: list[dr.Bar] | None) -> Context | None:
    """Live context for `day` from the saved sessions strictly before it."""
    prior = [b for b in daily if b.day < day]
    return _context(prior[-22:], _vix_before(vix, day)) if len(prior) >= 22 else None


def features(ctx: Context, *, open_: float, high: float, low: float, price: float) -> dict[str, float]:
    """Checkpoint features from the day so far (live: the quote's ohlc and last price)."""
    out = {
        "log_rv1": ctx.log_rv1, "log_rv5": ctx.log_rv5, "log_rv22": ctx.log_rv22,
        "log_so_far": math.log(_log_range(max(high, price), min(low, price))),
        "log_gap": math.log(max(abs(math.log(open_ / ctx.prev_close)), FLOOR)),
        "log_move": math.log(max(abs(math.log(price / ctx.prev_close)), FLOOR)),
    }
    if ctx.log_vix is not None:
        out["log_vix"] = ctx.log_vix
    return out


def sessions_15m(rows: list[list]) -> dict[str, list[list]]:
    """Complete regular sessions only: the 25 bars 09:15 .. 15:15."""
    by_day: dict[str, list[list]] = {}
    for r in rows:
        hhmm = str(r[0])[11:16]
        if "09:15" <= hhmm <= "15:15":
            by_day.setdefault(str(r[0])[:10], []).append(r)
    return {d: sorted(b, key=lambda r: r[0]) for d, b in by_day.items() if len(b) == SESSION_BARS}


def build_rows(rows_15m: list[list], daily: list[dr.Bar], vix: list[dr.Bar] | None) -> list[dict]:
    """One row per (session, checkpoint) with features and rest-of-day outcomes."""
    ctxs = contexts(daily, vix)
    out = []
    for day, bars in sorted(sessions_15m(rows_15m).items()):
        ctx = ctxs.get(day)
        if ctx is None:
            continue
        o = [float(b[1]) for b in bars]
        h = [float(b[2]) for b in bars]
        lo = [float(b[3]) for b in bars]
        c = [float(b[4]) for b in bars]
        for k in CHECKPOINTS:
            price = c[k - 1]
            hi_rest, lo_rest = max(h[k:]), min(lo[k:])
            out.append({
                "day": day, "k": k,
                "features": features(ctx, open_=o[0], high=max(h[:k]), low=min(lo[:k]), price=price),
                "y": math.log(_log_range(max(hi_rest, price), min(lo_rest, price))),
                "up": max(hi_rest / price - 1, 0.0),
                "down": max(1 - lo_rest / price, 0.0),
                "close": c[-1] / price - 1,
            })
    return out


# ------------------------------------------------------------------------- modelling

MODELS: dict[str, tuple[str, ...]] = {
    "naive_prev_day": ("log_rv1",),            # yesterday's range, scaled to the time left
    "so_far_scaled": ("log_so_far",),          # today's range so far, scaled to the time left
    "har_intraday": ("log_rv1", "log_rv5", "log_rv22", "log_so_far", "log_gap", "log_move"),
    "har_intraday_vix": ("log_rv1", "log_rv5", "log_rv22", "log_so_far", "log_gap", "log_move", "log_vix"),
}
SCALED = {"naive_prev_day", "so_far_scaled"}   # fixed slope 1: only the time-of-day offset is fitted
UNDERCOVERED_BELOW = 0.85                      # a 90% band that held less often than this on the holdout


def _x(rows: list[dict], names: tuple[str, ...]) -> np.ndarray:
    return np.array([[r["features"][n] for n in names] for r in rows], dtype=float)


def fit(model: str, train: list[dict]) -> dict:
    names = MODELS[model]
    y = np.array([r["y"] for r in train])
    x = _x(train, names)
    if model in SCALED:
        return {"names": names, "intercept": float(np.mean(y - x[:, 0])), "coef": [1.0]}
    a = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.solve(a.T @ a + 1e-6 * np.eye(a.shape[1]), a.T @ y)
    return {"names": names, "intercept": float(beta[0]), "coef": [float(b) for b in beta[1:]]}


def predict(params: dict, feats: dict[str, float]) -> float | None:
    if any(n not in feats for n in params["names"]):
        return None
    return params["intercept"] + sum(c * feats[n] for c, n in zip(params["coef"], params["names"]))


QUANTILES = {"q05": 0.05, "q16": 0.16, "q84": 0.84, "q95": 0.95}


def _quantiles(rows: list[dict], preds: np.ndarray) -> dict[str, dict[str, float]]:
    level = np.exp(preds)
    resid = np.array([r["y"] for r in rows]) - preds
    up = np.array([r["up"] for r in rows]) / level
    down = np.array([r["down"] for r in rows]) / level
    close = np.array([r["close"] for r in rows]) / level
    return {
        "range_resid": {k: float(np.quantile(resid, v)) for k, v in QUANTILES.items()},
        "up_ratio": {"p68": float(np.quantile(up, 0.68)), "p90": float(np.quantile(up, 0.90))},
        "down_ratio": {"p68": float(np.quantile(down, 0.68)), "p90": float(np.quantile(down, 0.90))},
        "close_ratio": {k: float(np.quantile(close, v)) for k, v in QUANTILES.items()},
    }


def _coverage(rows: list[dict], preds: np.ndarray, q: dict) -> dict[str, float]:
    level = np.exp(preds)
    resid = np.array([r["y"] for r in rows]) - preds
    up = np.array([r["up"] for r in rows]) / level
    down = np.array([r["down"] for r in rows]) / level
    close = np.array([r["close"] for r in rows]) / level
    rq, cq = q["range_resid"], q["close_ratio"]
    return {
        "range_band68": float(np.mean((resid >= rq["q16"]) & (resid <= rq["q84"]))),
        "range_band90": float(np.mean((resid >= rq["q05"]) & (resid <= rq["q95"]))),
        "high_within_p90": float(np.mean(up <= q["up_ratio"]["p90"])),
        "low_within_p90": float(np.mean(down <= q["down_ratio"]["p90"])),
        "close_band68": float(np.mean((close >= cq["q16"]) & (close <= cq["q84"]))),
        "close_band90": float(np.mean((close >= cq["q05"]) & (close <= cq["q95"]))),
    }


def evaluate(rows: list[dict], *, cfg: dr.WalkForwardConfig | None = None) -> dict:
    """Walk-forward by session for every checkpoint and model; selection on development only."""
    cfg = cfg or dr.WalkForwardConfig(initial_train=MIN_TRAIN_SESSIONS * 2, step=20)
    usable = [r for r in rows if all(n in r["features"] for n in MODELS["har_intraday_vix"])]
    days = sorted({r["day"] for r in usable})
    if len(days) < cfg.initial_train + 2 * cfg.step:
        return {"status": "INSUFFICIENT_SESSIONS", "sessions": len(days)}
    fold_list = dr.folds(len(days), cfg)
    holdout_from = days[fold_list[int(len(fold_list) * (1 - cfg.holdout_fraction))][1]]
    by_k: dict[int, list[dict]] = {}
    for r in usable:
        by_k.setdefault(r["k"], []).append(r)

    oos: dict[str, dict[int, tuple[list[dict], list[float]]]] = {m: {} for m in MODELS}
    for k, k_rows in by_k.items():
        for model in MODELS:
            tested, preds = [], []
            for train_end, test_start, test_end in fold_list:
                train_days, test_days = set(days[:train_end]), set(days[test_start:test_end])
                params = fit(model, [r for r in k_rows if r["day"] in train_days])
                for r in k_rows:
                    if r["day"] in test_days:
                        tested.append(r)
                        preds.append(predict(params, r["features"]))
            oos[model][k] = (tested, preds)

    def loss_by_session(model: str, part: str) -> dict[str, float]:
        per: dict[str, list[float]] = {}
        for tested, preds in oos[model].values():
            for r, p in zip(tested, preds):
                if (r["day"] >= holdout_from) == (part == "holdout"):
                    per.setdefault(r["day"], []).append((p - r["y"]) ** 2)
        return {d: float(np.mean(v)) for d, v in per.items()}

    table = {}
    for model in MODELS:
        table[model] = {}
        for part in ("development", "holdout"):
            losses = loss_by_session(model, part)
            table[model][part] = {"sessions": len(losses), "mse_log_range": float(np.mean(list(losses.values())))}
    selected = min((m for m in MODELS if m not in SCALED), key=lambda m: table[m]["development"]["mse_log_range"])
    sel = loss_by_session(selected, "holdout")
    dm = {}
    for ref in SCALED:  # both simple rules: yesterday's range, and today's range so far
        base = loss_by_session(ref, "holdout")
        common = sorted(set(base) & set(sel))
        dm[ref] = dr.diebold_mariano(np.array([sel[d] for d in common]), np.array([base[d] for d in common]))
    improvement = {ref: 100 * (1 - table[selected]["holdout"]["mse_log_range"] / table[ref]["holdout"]["mse_log_range"])
                   for ref in SCALED}

    per_checkpoint = {}
    for k in sorted(by_k):
        tested, preds = oos[selected][k]
        p = np.array(preds)
        dev = np.array([r["day"] < holdout_from for r in tested])
        q = _quantiles([r for r, d in zip(tested, dev) if d], p[dev])
        hold_rows = [r for r, d in zip(tested, dev) if not d]
        per_checkpoint[k] = {
            "time": checkpoint_label(k),
            "params": fit(selected, by_k[k]),  # final fit on every session for the live forecast
            "quantiles": q,
            "holdout_coverage": _coverage(hold_rows, p[~dev], q),
            "holdout_sessions": len(hold_rows),
        }
    pooled = {key: float(np.mean([pc["holdout_coverage"][key] for pc in per_checkpoint.values()]))
              for key in next(iter(per_checkpoint.values()))["holdout_coverage"]}
    return {
        "status": "EVALUATED",
        "sessions": len(days), "first": days[0], "last": days[-1], "holdout_from": holdout_from,
        "selected_on_development": selected, "baselines": sorted(SCALED), "models": table,
        "holdout_mse_improvement_pct": improvement,
        "dm_holdout": dm,
        "holdout_coverage_mean": pooled,
        "checkpoints": {str(k): v for k, v in per_checkpoint.items()},
    }


# ------------------------------------------------------------------------------ live

def forecast_from_quote(model: dict, *, ctx: Context, k: int, open_: float, high: float, low: float,
                        price: float) -> dict[str, Any]:
    """Rest-of-day bands at checkpoint k from the day so far."""
    cp = model["checkpoints"].get(str(k))
    if cp is None:
        return {"status": "NO_MODEL_FOR_CHECKPOINT", "checkpoint": checkpoint_label(k)}
    feats = features(ctx, open_=open_, high=high, low=low, price=price)
    y_hat = predict(cp["params"], feats)
    if y_hat is None:
        return {"status": "MISSING_INPUTS", "missing": [n for n in cp["params"]["names"] if n not in feats]}
    q = cp["quantiles"]
    level = math.exp(y_hat)

    def pct(log_range: float) -> float:
        return math.expm1(log_range) * 100

    rq, cq = q["range_resid"], q["close_ratio"]
    up68, up90 = q["up_ratio"]["p68"] * level, q["up_ratio"]["p90"] * level
    dn68, dn90 = q["down_ratio"]["p68"] * level, q["down_ratio"]["p90"] * level
    return {
        "status": "OK",
        "checkpoint": cp["time"],
        "price": price,
        "expected_remaining_range_pct": pct(level),
        "expected_remaining_range_points": price * math.expm1(level),
        "remaining_range_band68_pct": [pct(level * math.exp(rq["q16"])), pct(level * math.exp(rq["q84"]))],
        "remaining_range_band90_pct": [pct(level * math.exp(rq["q05"])), pct(level * math.exp(rq["q95"]))],
        "high_by_close": {"p68": price * (1 + up68), "p90": price * (1 + up90)},
        "low_by_close": {"p68": price * (1 - dn68), "p90": price * (1 - dn90)},
        "close_band68": [price * (1 + cq["q16"] * level), price * (1 + cq["q84"] * level)],
        "close_band90": [price * (1 + cq["q05"] * level), price * (1 + cq["q95"] * level)],
        "holdout_coverage": cp["holdout_coverage"],
        "holdout_sessions": cp["holdout_sessions"],
        # 90% bands that held less often than UNDERCOVERED_BELOW on unseen sessions at this time
        "undercovered": sorted(name for name, v in cp["holdout_coverage"].items()
                               if "90" in name and v < UNDERCOVERED_BELOW),
    }
