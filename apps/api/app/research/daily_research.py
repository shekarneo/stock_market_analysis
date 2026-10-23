"""Multi-year research: next-day / next-half-day direction and next-day volatility.

Inputs are Groww history series (see app.market.history_loader): NIFTY daily and 15-minute
candles, optionally India VIX, BANKNIFTY, SENSEX and a daily put/call OI ratio.

Design rules
- Every feature for day t is known at the close of day t; targets are about t+1.
- A row with any missing input is dropped, never filled.
- Walk-forward with an expanding window and a one-row embargo. Selection uses the
  development period only; the final holdout is reported once.
- Direction is scored on one chained out-of-sample curve with realistic index-futures
  costs (app.forecasting.evaluation): Sharpe, deflated Sharpe over every trial,
  accuracy with Wilson CI and binomial p-value.
- Volatility is scored on next-day Parkinson variance: MSE of log variance and QLIKE,
  Mincer-Zarnowitz R^2, and Diebold-Mariano tests against a naive and a VIX forecast.

Not available from Groww's historical API and therefore not used: MCX crude, USD/INR,
FII/DII flows. Their absence is reported, not substituted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from app.forecasting.evaluation import (
    FuturesCostModel,
    OOSBar,
    add_deflated_sharpe,
    evaluate_partition,
)

LN2 = math.log(2.0)
TRADING_DAYS = 248


# ----------------------------------------------------------------------------- bars

@dataclass(frozen=True)
class Bar:
    key: str  # session date (daily) or "<date> AM|PM" (half-day)
    day: str
    open: float
    high: float
    low: float
    close: float


def daily_bars(rows: list[list]) -> list[Bar]:
    """Bars from a 1day series ([iso_ts, o, h, l, c, ...]); one per session date."""
    out: dict[str, Bar] = {}
    for r in rows:
        day = str(r[0])[:10]
        out[day] = Bar(day, day, float(r[1]), float(r[2]), float(r[3]), float(r[4]))
    return [out[k] for k in sorted(out)]


def daily_from_intraday(rows: list[list], *, min_bars: int = 20) -> list[Bar]:
    """Daily bars built from 15-minute rows; sessions with fewer than min_bars are dropped."""
    sessions: dict[str, list[list]] = {}
    for r in rows:
        sessions.setdefault(str(r[0])[:10], []).append(r)
    out = []
    for day in sorted(sessions):
        s = sorted(sessions[day], key=lambda r: r[0])
        if len(s) < min_bars:
            continue
        out.append(Bar(day, day, float(s[0][1]), max(float(r[2]) for r in s), min(float(r[3]) for r in s), float(s[-1][4])))
    return out


def half_day_bars(rows: list[list], *, min_am: int = 11, min_pm: int = 12) -> list[Bar]:
    """AM (bars starting before 12:15) and PM bars per session; incomplete halves dropped."""
    sessions: dict[str, list[list]] = {}
    for r in rows:
        sessions.setdefault(str(r[0])[:10], []).append(r)
    out = []
    for day in sorted(sessions):
        s = sorted(sessions[day], key=lambda r: r[0])
        am = [r for r in s if str(r[0])[11:16] < "12:15"]
        pm = [r for r in s if str(r[0])[11:16] >= "12:15"]
        for label, part, need in (("AM", am, min_am), ("PM", pm, min_pm)):
            if len(part) >= need:
                out.append(Bar(f"{day} {label}", day, float(part[0][1]), max(float(r[2]) for r in part),
                               min(float(r[3]) for r in part), float(part[-1][4])))
    return out


def parkinson_var(bar: Bar) -> float | None:
    if bar.high <= 0 or bar.low <= 0 or bar.high < bar.low:
        return None
    hl = math.log(bar.high / bar.low)
    var = hl * hl / (4.0 * LN2)
    return var if var > 0 else None


# -------------------------------------------------------------------------- dataset

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "price": ("r1", "r5", "r20", "gap", "log_rv1", "log_rv5", "log_rv20"),
    "price_vix": ("r1", "r5", "r20", "gap", "log_rv1", "log_rv5", "log_rv20", "vix_lvl", "vix_chg", "vrp"),
    "price_vix_cross": ("r1", "r5", "r20", "gap", "log_rv1", "log_rv5", "log_rv20", "vix_lvl", "vix_chg", "vrp",
                        "bn_rel", "sx_rel"),
    "price_vix_cross_pcr": ("r1", "r5", "r20", "gap", "log_rv1", "log_rv5", "log_rv20", "vix_lvl", "vix_chg", "vrp",
                            "bn_rel", "sx_rel", "pcr", "pcr_chg"),
}


def _by_day(bars: list[Bar] | None) -> dict[str, Bar]:
    return {b.day: b for b in bars or []}


def build_rows(
    bars: list[Bar],
    *,
    vix: list[Bar] | None = None,
    banknifty: list[Bar] | None = None,
    sensex: list[Bar] | None = None,
    pcr: dict[str, dict] | None = None,
    min_history: int = 20,
) -> list[dict]:
    """Feature rows for each bar t with targets from bar t+1. Missing inputs -> key absent."""
    vix_d, bn_d, sx_d = _by_day(vix), _by_day(banknifty), _by_day(sensex)
    pv = [parkinson_var(b) for b in bars]
    rows = []
    for t in range(min_history, len(bars) - 1):
        b, prev, nxt = bars[t], bars[t - 1], bars[t + 1]
        window = pv[t - min_history + 1:t + 1]
        if any(v is None for v in window) or pv[t + 1] is None:
            continue
        f: dict[str, float] = {
            "r1": math.log(b.close / prev.close),
            "r5": math.log(b.close / bars[t - 5].close),
            "r20": math.log(b.close / bars[t - 20].close),
            "gap": math.log(b.open / prev.close),
            "log_rv1": math.log(pv[t]),
            "log_rv5": math.log(float(np.mean(window[-5:]))),
            "log_rv20": math.log(float(np.mean(window))),
        }
        # Cross-asset inputs are taken from the same session date only (no look-ahead).
        v, v_prev = vix_d.get(b.day), vix_d.get(prev.day)
        if v is not None and v_prev is not None and v.close > 0 and v_prev.close > 0:
            daily_implied_var = (v.close / 100.0) ** 2 / TRADING_DAYS
            f["vix_lvl"] = v.close / 100.0
            f["vix_chg"] = math.log(v.close / v_prev.close)
            f["vrp"] = math.log(daily_implied_var) - f["log_rv5"]
            f["log_vix_var"] = math.log(daily_implied_var)
        for name, src in (("bn_rel", bn_d), ("sx_rel", sx_d)):
            x, x_prev = src.get(b.day), src.get(prev.day)
            if x is not None and x_prev is not None and x_prev.close > 0:
                f[name] = math.log(x.close / x_prev.close) - f["r1"]
        if pcr:
            p, p_prev = pcr.get(b.day), pcr.get(prev.day)
            if p is not None and p.get("pcr_oi"):
                f["pcr"] = math.log(p["pcr_oi"])
                if p_prev is not None and p_prev.get("pcr_oi"):
                    f["pcr_chg"] = math.log(p["pcr_oi"] / p_prev["pcr_oi"])
        ret_next = math.log(nxt.close / b.close)
        rows.append({
            "key": b.key, "day": b.day, "features": f,
            "ret_next": ret_next, "dir_next": 1 if ret_next > 0 else 0,
            "log_var_next": math.log(pv[t + 1]),
        })
    return rows


def usable(rows: list[dict], names: tuple[str, ...]) -> list[dict]:
    return [r for r in rows if all(n in r["features"] for n in names)]


# ----------------------------------------------------------------------- walk-forward

@dataclass
class WalkForwardConfig:
    initial_train: int = 500
    step: int = 20
    embargo: int = 1
    holdout_fraction: float = 0.2


def folds(n: int, cfg: WalkForwardConfig) -> list[tuple[int, int, int]]:
    """(train_end, test_start, test_end) index triples; contiguous test windows."""
    out, train_end = [], cfg.initial_train
    while train_end + cfg.embargo < n:
        test_start = train_end + cfg.embargo
        test_end = min(test_start + cfg.step, n)
        out.append((train_end, test_start, test_end))
        train_end += cfg.step
    return out


def _matrix(rows: list[dict], names: tuple[str, ...]) -> np.ndarray:
    return np.array([[r["features"][n] for n in names] for r in rows], dtype=float)


def _standardize(train: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = train.mean(axis=0)
    sd = train.std(axis=0)
    sd[sd == 0] = 1.0
    return (train - mu) / sd, (test - mu) / sd


def _logistic(train_x, train_y, test_x, *, l2: float = 1.0) -> np.ndarray | None:
    from sklearn.linear_model import LogisticRegression

    if len(set(train_y.tolist())) < 2:
        return None
    xs, ts = _standardize(train_x, test_x)
    model = LogisticRegression(C=1.0 / l2, max_iter=500)
    model.fit(xs, train_y)
    return model.predict_proba(ts)[:, 1]


def _lightgbm(train_x, train_y, test_x) -> np.ndarray | None:
    """Shallow, heavily regularized trees; None when lightgbm is not installed."""
    try:
        import lightgbm as lgb
    except ImportError:
        return None
    if len(set(train_y.tolist())) < 2:
        return None
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.03, num_leaves=4, max_depth=2,
                               min_child_samples=50, subsample=0.8, subsample_freq=1,
                               colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=7)
    model.fit(train_x, train_y)
    return model.predict_proba(test_x)[:, 1]


def _ols(train_x, train_y, test_x, *, ridge: float = 1e-6) -> np.ndarray:
    a = np.column_stack([np.ones(len(train_x)), train_x])
    b = np.column_stack([np.ones(len(test_x)), test_x])
    beta = np.linalg.solve(a.T @ a + ridge * np.eye(a.shape[1]), a.T @ train_y)
    return b @ beta


# -------------------------------------------------------------------------- direction

def run_direction(
    rows: list[dict],
    *,
    horizon: str,
    feature_sets: dict[str, tuple[str, ...]],
    cfg: WalkForwardConfig,
    deadband: tuple[float, float] = (0.45, 0.55),
    cost_per_side: float | None = None,
    periods_per_year: int = TRADING_DAYS,
) -> list[dict]:
    """One result per (feature set, model): honest dev/holdout/full metrics."""
    cost = cost_per_side if cost_per_side is not None else FuturesCostModel().per_side()
    results = []
    for set_index, (set_name, names) in enumerate(feature_sets.items()):
        data = usable(rows, names)
        if len(data) < cfg.initial_train + 2 * cfg.step:
            results.append({"horizon": horizon, "feature_set": set_name, "model": None,
                            "status": "INSUFFICIENT_ROWS", "rows": len(data)})
            continue
        x, y = _matrix(data, names), np.array([r["dir_next"] for r in data])
        fold_list = folds(len(data), cfg)
        holdout_from = fold_list[int(len(fold_list) * (1 - cfg.holdout_fraction))][1]
        # The prior ignores features, so it is one trial per horizon, not one per feature set.
        models = (["empirical_prior"] if set_index == 0 else []) + ["logistic", "lightgbm"]
        bars: dict[str, list[OOSBar]] = {m: [] for m in models}
        for train_end, test_start, test_end in fold_list:
            tx, ty, vx = x[:train_end], y[:train_end], x[test_start:test_end]
            probs = {
                "empirical_prior": np.full(len(vx), ty.mean()) if "empirical_prior" in bars else None,
                "logistic": _logistic(tx, ty, vx),
                "lightgbm": _lightgbm(tx, ty, vx),
            }
            for model, p in probs.items():
                if p is None:
                    continue
                for i, prob in enumerate(p):
                    r = data[test_start + i]
                    pos = 1.0 if prob > deadband[1] else (-1.0 if prob < deadband[0] else 0.0)
                    bars[model].append(OOSBar(r["key"], "holdout" if test_start + i >= holdout_from else "development",
                                              pos, math.expm1(r["ret_next"]), float(prob), r["dir_next"]))
        for model, series in bars.items():
            if not series:
                continue
            results.append({
                "horizon": horizon, "feature_set": set_name, "model": model, "status": "EVALUATED",
                "rows": len(data), "first": data[0]["day"], "last": data[-1]["day"],
                "development": evaluate_partition([b for b in series if b.partition == "development"],
                                                  cost_per_side=cost, periods_per_year=periods_per_year),
                "holdout": evaluate_partition([b for b in series if b.partition == "holdout"],
                                              cost_per_side=cost, periods_per_year=periods_per_year),
            })
    return results


# ------------------------------------------------------------------------- volatility

def qlike(log_pred: np.ndarray, log_true: np.ndarray) -> np.ndarray:
    ratio = np.exp(log_true - log_pred)
    return ratio - np.log(ratio) - 1.0


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, *, lag: int = 5) -> dict:
    """DM test of equal predictive accuracy (Newey-West variance). Negative stat: A better."""
    d = loss_a - loss_b
    n = len(d)
    if n < 20:
        return {"stat": None, "p_value": None, "n": n}
    mean = d.mean()
    centered = d - mean
    var = centered @ centered / n
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1)
        var += 2 * weight * (centered[k:] @ centered[:-k]) / n
    if var <= 0:
        return {"stat": None, "p_value": None, "n": n}
    stat = mean / math.sqrt(var / n)
    return {"stat": float(stat), "p_value": float(2 * (1 - stats.norm.cdf(abs(stat)))), "n": n}


VOL_MODELS: dict[str, tuple[str, ...]] = {
    "naive_rv1": (),                     # forecast = today's log variance
    "har": ("log_rv1", "log_rv5", "log_rv20"),
    "vix_implied": ("log_vix_var",),     # linear map of VIX-implied variance (bias-corrected in train)
    "har_vix": ("log_rv1", "log_rv5", "log_rv20", "log_vix_var"),
}


def run_volatility(rows: list[dict], *, cfg: WalkForwardConfig) -> dict:
    """Next-day log-variance forecasts; every model scored on the same rows."""
    data = usable(rows, ("log_rv1", "log_rv5", "log_rv20", "log_vix_var"))
    vix_available = len(data) >= cfg.initial_train + 2 * cfg.step
    if not vix_available:
        data = usable(rows, ("log_rv1", "log_rv5", "log_rv20"))
    if len(data) < cfg.initial_train + 2 * cfg.step:
        return {"status": "INSUFFICIENT_ROWS", "rows": len(data)}
    models = {k: v for k, v in VOL_MODELS.items() if vix_available or "log_vix_var" not in v}
    y = np.array([r["log_var_next"] for r in data])
    fold_list = folds(len(data), cfg)
    holdout_from = fold_list[int(len(fold_list) * (1 - cfg.holdout_fraction))][1]
    preds: dict[str, list[float]] = {m: [] for m in models}
    idx: list[int] = []
    for train_end, test_start, test_end in fold_list:
        idx.extend(range(test_start, test_end))
        for model, names in models.items():
            if not names:
                preds[model].extend(r["features"]["log_rv1"] for r in data[test_start:test_end])
                continue
            tx = _matrix(data[:train_end], names)
            vx = _matrix(data[test_start:test_end], names)
            preds[model].extend(_ols(tx, y[:train_end], vx).tolist())
    truth = y[idx]
    parts = {"development": np.array([i < holdout_from for i in idx]), "holdout": np.array([i >= holdout_from for i in idx])}
    table = {}
    for model, p in preds.items():
        p = np.array(p)
        entry = {}
        for part, mask in parts.items():
            if mask.sum() < 20:
                entry[part] = None
                continue
            pp, tt = p[mask], truth[mask]
            mz = stats.linregress(pp, tt)
            entry[part] = {
                "n": int(mask.sum()),
                "mse_log_var": float(np.mean((pp - tt) ** 2)),
                "qlike": float(np.mean(qlike(pp, tt))),
                "mincer_zarnowitz_r2": float(mz.rvalue ** 2),
                "_loss": qlike(pp, tt),
            }
        table[model] = entry
    # Significance against the naive forecast and (when available) against VIX
    for model, entry in table.items():
        for part in parts:
            if entry.get(part) is None:
                continue
            for ref in ("naive_rv1", "vix_implied"):
                if ref == model or ref not in table or table[ref].get(part) is None:
                    continue
                entry[part][f"dm_vs_{ref}"] = diebold_mariano(entry[part]["_loss"], table[ref][part]["_loss"])
    for entry in table.values():
        for part in parts:
            if entry.get(part):
                entry[part].pop("_loss", None)
    best_dev = min(table, key=lambda m: table[m]["development"]["qlike"] if table[m]["development"] else float("inf"))
    return {
        "status": "EVALUATED", "rows": len(data), "first": data[0]["day"], "last": data[-1]["day"],
        "vix_available": vix_available, "models": table, "selected_on_development": best_dev,
    }


# ----------------------------------------------------------------------------- report

def summarize(direction: list[dict], volatility: dict) -> dict:
    evaluated = [r for r in direction if r.get("status") == "EVALUATED"]
    add_deflated_sharpe(evaluated, partition="development")
    best = max(evaluated, key=lambda r: r["development"].get("deflated_sharpe") or -1.0, default=None)
    edge = bool(
        best and (best["development"].get("deflated_sharpe") or 0) >= 0.95
        and (best["holdout"].get("psr_vs_zero") or 0) >= 0.9
    )
    vol_verdict = None
    if volatility.get("status") == "EVALUATED":
        sel = volatility["selected_on_development"]
        hold = volatility["models"][sel]["holdout"] or {}
        dm = hold.get("dm_vs_naive_rv1") or {}
        vol_verdict = {
            "selected_model": sel,
            "holdout_qlike": hold.get("qlike"),
            "beats_naive_holdout": bool(dm.get("stat") is not None and dm["stat"] < 0 and (dm.get("p_value") or 1) < 0.05),
            "dm_vs_naive_holdout": dm,
            "dm_vs_vix_holdout": hold.get("dm_vs_vix_implied"),
        }
    return {
        "direction_best_on_development": None if best is None else {
            "horizon": best["horizon"], "feature_set": best["feature_set"], "model": best["model"],
            "dev_deflated_sharpe": best["development"].get("deflated_sharpe"),
            "holdout_return_pct": best["holdout"].get("total_return_pct"),
            "holdout_accuracy": best["holdout"]["directional_accuracy"],
        },
        "direction_edge_supported": edge,
        "direction_trials": len(evaluated),
        "volatility": vol_verdict,
    }


def run_research(
    *,
    nifty_daily: list[Bar],
    nifty_half_day: list[Bar] | None = None,
    vix: list[Bar] | None = None,
    banknifty: list[Bar] | None = None,
    sensex: list[Bar] | None = None,
    pcr: dict[str, dict] | None = None,
    cfg: WalkForwardConfig | None = None,
    half_day_cfg: WalkForwardConfig | None = None,
) -> dict[str, Any]:
    cfg = cfg or WalkForwardConfig()
    daily_rows = build_rows(nifty_daily, vix=vix, banknifty=banknifty, sensex=sensex, pcr=pcr)
    sets = {k: v for k, v in FEATURE_SETS.items() if pcr or "pcr" not in v}
    direction = run_direction(daily_rows, horizon="next_day", feature_sets=sets, cfg=cfg)
    if nifty_half_day:
        hd_rows = build_rows(nifty_half_day)  # cross-asset series are daily; half-day uses price features
        direction += run_direction(hd_rows, horizon="next_half_day", feature_sets={"price": FEATURE_SETS["price"]},
                                   cfg=half_day_cfg or WalkForwardConfig(initial_train=1000, step=40),
                                   periods_per_year=2 * TRADING_DAYS)
    volatility = run_volatility(daily_rows, cfg=cfg)
    return {
        "schema": "daily-research-1",
        "inputs": {
            "nifty_daily_bars": len(nifty_daily),
            "nifty_half_day_bars": len(nifty_half_day or []),
            "vix_bars": len(vix or []), "banknifty_bars": len(banknifty or []), "sensex_bars": len(sensex or []),
            "pcr_days": len(pcr or {}),
            "unavailable": ["MCX crude (not served by Groww historical API)", "USD/INR", "FII/DII flows"],
        },
        "config": cfg.__dict__,
        "cost_per_side": FuturesCostModel().per_side(),
        "summary": summarize(direction, volatility),
        "direction": direction,
        "volatility": volatility,
    }
