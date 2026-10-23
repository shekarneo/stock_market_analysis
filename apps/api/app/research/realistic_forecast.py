"""Tuned, honestly evaluated forecast for the next NIFTY session (and next half-day).

What it produces, and why it can be trusted only as far as stated:
- Expected range for the next session: a volatility model chosen on the development
  period (QLIKE) from a small grid, refitted on all history. Its bands come from the
  model's own out-of-sample errors, and their historical holdout coverage is reported.
- Typical close-to-close move: the empirical ratio of realized |return| to forecast
  volatility on out-of-sample rows (no distributional assumption).
- Direction: every (feature set, model, hyperparameters, deadband) combination is one
  walk-forward trial; selection uses development data only and the deflated Sharpe
  counts every trial. Only when the selected trial also holds up on the final holdout
  is its probability published. Otherwise the forecast is the historical up-day rate,
  labelled NO_RELIABLE_EDGE, and the raw model output is shown as unreliable.

Nothing here places or proposes orders.
"""

from __future__ import annotations

import math
import warnings
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np

from app.forecasting.evaluation import FuturesCostModel, OOSBar, add_deflated_sharpe, evaluate_partition
from app.research import daily_research as dr

LN2 = math.log(2.0)

# --------------------------------------------------------------------------- direction


def _logistic_spec(c: float) -> dict:
    return {"model": "logistic", "params": {"C": c}}


def _lightgbm_spec(n_estimators: int, min_child_samples: int) -> dict:
    return {"model": "lightgbm", "params": {"n_estimators": n_estimators, "min_child_samples": min_child_samples}}


DIRECTION_GRID = [
    _logistic_spec(0.01), _logistic_spec(0.1), _logistic_spec(1.0),
    _lightgbm_spec(100, 50), _lightgbm_spec(300, 50), _lightgbm_spec(100, 150),
]
HALF_DAY_GRID = [_logistic_spec(0.1), _logistic_spec(1.0), _lightgbm_spec(100, 50)]
DEADBANDS = [(0.45, 0.55), (0.40, 0.60)]
EDGE_DEV_DSR = 0.95
EDGE_HOLDOUT_PSR = 0.90


def fit_predict(spec: dict, train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray | None:
    if len(set(train_y.tolist())) < 2:
        return None
    with warnings.catch_warnings():
        # sklearn / lightgbm feature-name notices on plain arrays; numerical warnings stay visible
        warnings.filterwarnings("ignore", message=".*feature names.*")
        return _fit_predict(spec, train_x, train_y, test_x)


def _fit_predict(spec: dict, train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray | None:
    if spec["model"] == "logistic":
        from sklearn.linear_model import LogisticRegression

        xs, ts = dr._standardize(train_x, test_x)
        model = LogisticRegression(C=spec["params"]["C"], max_iter=1000)
        model.fit(xs, train_y)
        return model.predict_proba(ts)[:, 1]
    if spec["model"] == "lightgbm":
        try:
            import lightgbm as lgb
        except ImportError:
            return None
        p = spec["params"]
        model = lgb.LGBMClassifier(n_estimators=p["n_estimators"], learning_rate=0.03, num_leaves=4, max_depth=2,
                                   min_child_samples=p["min_child_samples"], subsample=0.8, subsample_freq=1,
                                   colsample_bytree=0.8, reg_lambda=5.0, verbose=-1, random_state=7)
        model.fit(train_x, train_y)
        return model.predict_proba(test_x)[:, 1]
    raise ValueError(f"unknown model {spec['model']}")


def _label(spec: dict) -> str:
    return spec["model"] + "(" + ",".join(f"{k}={v}" for k, v in spec["params"].items()) + ")"


def tune_direction(
    rows: list[dict],
    *,
    horizon: str,
    feature_sets: dict[str, tuple[str, ...]],
    grid: list[dict],
    cfg: dr.WalkForwardConfig,
    periods_per_year: int = dr.TRADING_DAYS,
    deadbands: list[tuple[float, float]] = DEADBANDS,
) -> dict:
    """Every combination is one trial; the best is chosen on development DSR only."""
    cost = FuturesCostModel().per_side()
    trials: list[dict] = []
    prior_done = False
    for set_name, names in feature_sets.items():
        data = dr.usable(rows, names)
        if len(data) < cfg.initial_train + 2 * cfg.step:
            continue
        x, y = dr._matrix(data, names), np.array([r["dir_next"] for r in data])
        fold_list = dr.folds(len(data), cfg)
        holdout_from = fold_list[int(len(fold_list) * (1 - cfg.holdout_fraction))][1]
        specs = list(grid) + ([] if prior_done else [{"model": "empirical_prior", "params": {}}])
        prior_done = True
        for spec in specs:
            probs: list[tuple[int, float]] = []
            for train_end, test_start, test_end in fold_list:
                if spec["model"] == "empirical_prior":
                    p = np.full(test_end - test_start, y[:train_end].mean())
                else:
                    p = fit_predict(spec, x[:train_end], y[:train_end], x[test_start:test_end])
                if p is None:
                    continue
                probs.extend((test_start + i, float(v)) for i, v in enumerate(p))
            if not probs:
                continue
            for band in deadbands:
                series = []
                for idx, prob in probs:
                    r = data[idx]
                    pos = 1.0 if prob > band[1] else (-1.0 if prob < band[0] else 0.0)
                    series.append(OOSBar(r["key"], "holdout" if idx >= holdout_from else "development",
                                         pos, math.expm1(r["ret_next"]), prob, r["dir_next"]))
                trials.append({
                    "horizon": horizon, "feature_set": set_name, "spec": spec, "label": _label(spec), "deadband": band,
                    "development": evaluate_partition([b for b in series if b.partition == "development"],
                                                      cost_per_side=cost, periods_per_year=periods_per_year),
                    "holdout": evaluate_partition([b for b in series if b.partition == "holdout"],
                                                  cost_per_side=cost, periods_per_year=periods_per_year),
                })
    if not trials:
        return {"status": "INSUFFICIENT_ROWS", "trials": 0}
    add_deflated_sharpe(trials, partition="development")
    best = max(trials, key=lambda t: t["development"].get("deflated_sharpe") or -1.0)
    edge = bool((best["development"].get("deflated_sharpe") or 0) >= EDGE_DEV_DSR
                and (best["holdout"].get("psr_vs_zero") or 0) >= EDGE_HOLDOUT_PSR)
    return {"status": "EVALUATED", "trials": len(trials), "best": best, "edge_supported": edge,
            "table": [_trial_row(t) for t in sorted(trials, key=lambda t: -(t["development"].get("deflated_sharpe") or -1))]}


def _trial_row(t: dict) -> dict:
    hold = t["holdout"]
    return {
        "feature_set": t["feature_set"], "model": t["label"], "deadband": list(t["deadband"]),
        "dev_deflated_sharpe": t["development"].get("deflated_sharpe"),
        "holdout_return_pct": hold.get("total_return_pct"), "holdout_sharpe": hold.get("sharpe_annualized"),
        "holdout_psr": hold.get("psr_vs_zero"),
        "holdout_accuracy": hold["directional_accuracy"].get("accuracy"),
        "holdout_accuracy_p": hold["directional_accuracy"].get("p_value_vs_50pct"),
        "holdout_trades": hold.get("trades"),
    }


# -------------------------------------------------------------------------- volatility

VOL_GRID: dict[str, tuple[str, ...]] = {
    "naive_rv1": (),
    "har": ("log_rv1", "log_rv5", "log_rv20"),
    "har_vix": ("log_rv1", "log_rv5", "log_rv20", "log_vix_var"),
    "har_vix_leverage": ("log_rv1", "log_rv5", "log_rv20", "log_vix_var", "neg_r1"),
    "har_vix_leverage_gap": ("log_rv1", "log_rv5", "log_rv20", "log_vix_var", "neg_r1", "abs_gap"),
}


def _vol_value(features: dict, name: str) -> float | None:
    if name == "neg_r1":
        r = features.get("r1")
        return None if r is None else min(r, 0.0)
    if name == "abs_gap":
        g = features.get("gap")
        return None if g is None else abs(g)
    return features.get(name)


def _vol_matrix(rows: list[dict], names: tuple[str, ...]) -> np.ndarray:
    return np.array([[_vol_value(r["features"], n) for n in names] for r in rows], dtype=float)


def tune_volatility(rows: list[dict], *, cfg: dr.WalkForwardConfig) -> dict:
    """Walk-forward OLS on log variance; choose on development QLIKE; test on holdout."""
    needed = ("log_rv1", "log_rv5", "log_rv20", "log_vix_var", "r1", "gap")
    data = dr.usable(rows, needed)
    if len(data) < cfg.initial_train + 2 * cfg.step:
        return {"status": "INSUFFICIENT_ROWS", "rows": len(data)}
    y = np.array([r["log_var_next"] for r in data])
    fold_list = dr.folds(len(data), cfg)
    holdout_from = fold_list[int(len(fold_list) * (1 - cfg.holdout_fraction))][1]
    idx: list[int] = []
    preds: dict[str, list[float]] = {m: [] for m in VOL_GRID}
    for train_end, test_start, test_end in fold_list:
        idx.extend(range(test_start, test_end))
        for model, names in VOL_GRID.items():
            if not names:
                preds[model].extend(r["features"]["log_rv1"] for r in data[test_start:test_end])
                continue
            preds[model].extend(dr._ols(_vol_matrix(data[:train_end], names), y[:train_end],
                                        _vol_matrix(data[test_start:test_end], names)).tolist())
    truth = y[idx]
    is_hold = np.array([i >= holdout_from for i in idx])
    table: dict[str, dict] = {}
    for model, p in preds.items():
        p = np.array(p)
        table[model] = {}
        for part, mask in (("development", ~is_hold), ("holdout", is_hold)):
            loss = dr.qlike(p[mask], truth[mask])
            table[model][part] = {"n": int(mask.sum()), "qlike": float(loss.mean()),
                                  "mse_log_var": float(np.mean((p[mask] - truth[mask]) ** 2)), "_loss": loss}
    selected = min((m for m in VOL_GRID if m != "naive_rv1"), key=lambda m: table[m]["development"]["qlike"])
    for model in table:
        for ref in ("naive_rv1", "har_vix"):
            if model != ref:
                table[model]["holdout"][f"dm_vs_{ref}"] = dr.diebold_mariano(
                    table[model]["holdout"]["_loss"], table[ref]["holdout"]["_loss"])
    for model in table:
        for part in table[model].values():
            part.pop("_loss", None)
    p_sel = np.array(preds[selected])
    resid = truth - p_sel
    dev_resid, hold_resid = resid[~is_hold], resid[is_hold]
    # Interval quantiles from development errors only; their coverage is checked on the holdout
    q = {k: float(np.quantile(dev_resid, v)) for k, v in (("q05", 0.05), ("q16", 0.16), ("q84", 0.84), ("q95", 0.95))}
    coverage = {
        "band68": float(np.mean((hold_resid >= q["q16"]) & (hold_resid <= q["q84"]))),
        "band90": float(np.mean((hold_resid >= q["q05"]) & (hold_resid <= q["q95"]))),
    }
    # |close-to-close return| relative to forecast daily volatility, out of sample (development rows)
    sd = np.sqrt(np.exp(p_sel))
    abs_ret = np.array([abs(data[i]["ret_next"]) for i in idx])
    ratio_dev = (abs_ret / sd)[~is_hold]
    move = {"median": float(np.median(ratio_dev)), "p90": float(np.quantile(ratio_dev, 0.9))}
    move_cov = float(np.mean((abs_ret / sd)[is_hold] <= move["p90"]))
    improvement = 1 - table[selected]["holdout"]["qlike"] / table["naive_rv1"]["holdout"]["qlike"]
    return {
        "status": "EVALUATED", "rows": len(data), "selected_on_development": selected, "models": table,
        "residual_quantiles": q, "holdout_band_coverage": coverage,
        "move_ratio": move, "holdout_move_p90_coverage": move_cov,
        "holdout_qlike_improvement_vs_naive_pct": improvement * 100,
        "_data": data, "_names": VOL_GRID[selected], "_y": y,
    }


# ---------------------------------------------------------------------------- forecast

def next_weekday(day: str) -> str:
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _vol_forecast(vol: dict, latest: dict) -> dict:
    names = vol["_names"]
    x_new = np.array([[_vol_value(latest["features"], n) for n in names]], dtype=float)
    if np.isnan(x_new).any():
        return {"status": "MISSING_INPUTS", "missing": [n for n in names if _vol_value(latest["features"], n) is None]}
    log_var = float(dr._ols(_vol_matrix(vol["_data"], names), vol["_y"], x_new)[0])
    close = latest["close"]

    def rng_pct(lv: float) -> float:  # expected log(high/low) for a Parkinson variance
        return math.expm1(math.sqrt(4 * LN2 * math.exp(lv))) * 100

    q = vol["residual_quantiles"]
    sd = math.sqrt(math.exp(log_var))
    move = vol["move_ratio"]
    return {
        "status": "OK",
        "model": vol["selected_on_development"],
        "daily_vol_pct": sd * 100,
        "expected_range_pct": rng_pct(log_var),
        "expected_range_points": close * rng_pct(log_var) / 100,
        "range_band68_pct": [rng_pct(log_var + q["q16"]), rng_pct(log_var + q["q84"])],
        "range_band90_pct": [rng_pct(log_var + q["q05"]), rng_pct(log_var + q["q95"])],
        "typical_close_move_pct": move["median"] * sd * 100,
        "typical_close_move_points": close * move["median"] * sd,
        "close_move_p90_pct": move["p90"] * sd * 100,
        "close_move_p90_points": close * move["p90"] * sd,
        "holdout_band_coverage": vol["holdout_band_coverage"],
        "holdout_move_p90_coverage": vol["holdout_move_p90_coverage"],
        "holdout_qlike_improvement_vs_naive_pct": vol["holdout_qlike_improvement_vs_naive_pct"],
        "dm_vs_naive_holdout": vol["models"][vol["selected_on_development"]]["holdout"].get("dm_vs_naive_rv1"),
    }


def _direction_forecast(tuned: dict, rows: list[dict], latest: dict | None, feature_sets: dict) -> dict:
    if tuned.get("status") != "EVALUATED" or latest is None:
        return {"status": tuned.get("status") or "NO_LATEST_FEATURES"}
    best = tuned["best"]
    names = feature_sets[best["feature_set"]]
    base_rate = float(np.mean([r["dir_next"] for r in rows]))
    hold_acc = best["holdout"]["directional_accuracy"]
    out = {
        "historical_up_rate": base_rate,
        "best_trial": _trial_row(best),
        "trials": tuned["trials"],
        "holdout_accuracy": hold_acc.get("accuracy"),
        "holdout_accuracy_ci95": hold_acc.get("ci95"),
        "holdout_accuracy_p": hold_acc.get("p_value_vs_50pct"),
    }
    raw = None
    if all(n in latest["features"] for n in names) and best["spec"]["model"] != "empirical_prior":
        data = dr.usable(rows, names)
        x, y = dr._matrix(data, names), np.array([r["dir_next"] for r in data])
        x_new = np.array([[latest["features"][n] for n in names]], dtype=float)
        p = fit_predict(best["spec"], x, y, x_new)
        raw = None if p is None else float(p[0])
    if tuned["edge_supported"] and raw is not None:
        out.update(status="EDGE_SUPPORTED", probability_up=raw, basis="Selected model (passed development DSR and holdout PSR).")
    else:
        out.update(status="NO_RELIABLE_EDGE", probability_up=base_rate, model_output_unreliable=raw,
                   basis="No model beat chance after costs on unseen data; the historical up-day rate is shown.")
    return out


def build_forecast(
    *,
    nifty_daily: list[dr.Bar],
    nifty_half_day: list[dr.Bar] | None,
    vix: list[dr.Bar] | None,
    banknifty: list[dr.Bar] | None,
    sensex: list[dr.Bar] | None,
    cfg: dr.WalkForwardConfig | None = None,
    half_day_cfg: dr.WalkForwardConfig | None = None,
    log: Callable[[str], None] = lambda m: None,
) -> dict[str, Any]:
    cfg = cfg or dr.WalkForwardConfig()
    half_day_cfg = half_day_cfg or dr.WalkForwardConfig(initial_train=1000, step=40)
    rows = dr.build_rows(nifty_daily, vix=vix, banknifty=banknifty, sensex=sensex)
    latest = dr.latest_features(nifty_daily, vix=vix, banknifty=banknifty, sensex=sensex)
    sets = {k: v for k, v in dr.FEATURE_SETS.items() if "pcr" not in v}

    log("tuning volatility models")
    vol = tune_volatility(rows, cfg=cfg)
    log("tuning next-session direction models")
    direction = tune_direction(rows, horizon="next_session", feature_sets=sets, grid=DIRECTION_GRID, cfg=cfg)

    half = {"status": "NO_DATA"}
    if nifty_half_day:
        log("tuning next half-day direction models")
        hd_rows = dr.build_rows(nifty_half_day)
        hd_tuned = tune_direction(hd_rows, horizon="next_half_day", feature_sets={"price": dr.FEATURE_SETS["price"]},
                                  grid=HALF_DAY_GRID, cfg=half_day_cfg, periods_per_year=2 * dr.TRADING_DAYS)
        hd_latest = dr.latest_features(nifty_half_day)
        half = _direction_forecast(hd_tuned, hd_rows, hd_latest, {"price": dr.FEATURE_SETS["price"]})
        half["as_of_bar"] = hd_latest["key"] if hd_latest else None

    vol_out = _vol_forecast(vol, latest) if vol.get("status") == "EVALUATED" and latest else {"status": vol.get("status") or "NO_LATEST_FEATURES"}
    as_of = latest["day"] if latest else None
    report = {
        "schema": "realistic-forecast-1",
        "instrument": "NIFTY",
        "as_of_session": as_of,
        "for_session": next_weekday(as_of) if as_of else None,
        "for_session_note": "Next weekday after the last completed session; exchange holidays are not checked.",
        "last_close": latest["close"] if latest else None,
        "range": vol_out,
        "direction_next_session": _direction_forecast(direction, rows, latest, sets),
        "direction_next_half_day": half,
        "volatility_evaluation": {k: v for k, v in vol.items() if not k.startswith("_")},
        "direction_trials_top": (direction.get("table") or [])[:10],
        "inputs": {"nifty_daily_bars": len(nifty_daily), "vix_bars": len(vix or []), "half_day_bars": len(nifty_half_day or []),
                   "first_session": nifty_daily[0].day if nifty_daily else None},
        "caveats": [
            "Research output, not investment advice. It never places or proposes orders.",
            "Ranges are statistical expectations; about 1 session in 10 falls outside the 90% band.",
            "Direction is shown as a model probability only when it beat chance after costs on unseen data.",
        ],
    }
    return report
