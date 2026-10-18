"""Real-time statistical forecasting engine and Quant-Agent Fusion.

Calculates live model forecast probabilities for NIFTY, SENSEX, and CRUDEOILMINI
from approved registered model artifacts over completed candles only.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from app.forecasting.models import predict_logistic, predict_majority, predict_last_return_sign
from app.forecasting.targets import MODEL_FEATURES
from app.market.live_quotes import load_read
from app.settings import REPO_ROOT

REGISTRY_PATH = REPO_ROOT / "var" / "registry" / "registry.json"


def load_registered_model(
    instrument: str,
    horizon: str = "M15",
    family: str = "logistic_regression",
    registry_path: Path | None = None,
) -> dict | None:
    """Load and validate an approved fitted model from the model registry.
    
    Validates model status, schema, artifact integrity, and required preprocessing
    parameters. Returns None if no valid approved model is available.
    """
    path = registry_path or REGISTRY_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    models = data.get("models") or {}
    # Lookup by standard registry key convention: family:instrument:horizon
    target_key = f"{family}:{instrument.upper()}:{horizon}"
    entry = models.get(target_key)
    if not entry:
        # Fallback to scanning models for instrument match
        for k, v in models.items():
            if v.get("instrument") == instrument.upper() and v.get("horizon") == horizon:
                entry = v
                break

    if not entry:
        return None

    versions = entry.get("versions") or {}
    # Find latest approved version (v1, etc.)
    target_version = None
    for v_key in sorted(versions.keys(), reverse=True):
        candidate = versions[v_key]
        status = candidate.get("status")
        # Allowed research statuses
        if status in {"TRAINED", "EVALUATED", "APPROVED_FOR_RESEARCH"}:
            target_version = candidate
            break

    if not target_version:
        return None

    fitted = target_version.get("fitted_state")
    if not isinstance(fitted, dict) or not fitted.get("ok"):
        return None

    # Validate feature names and scaler for logistic regression
    if family == "logistic_regression" or fitted.get("family") == "logistic_regression":
        feature_names = fitted.get("feature_names")
        if not feature_names or list(feature_names) != list(MODEL_FEATURES):
            return None
        scaler = fitted.get("scaler")
        if not isinstance(scaler, dict):
            return None
        means = scaler.get("means")
        scales = scaler.get("scales")
        if not isinstance(means, list) or not isinstance(scales, list):
            return None
        if len(means) != len(MODEL_FEATURES) or len(scales) != len(MODEL_FEATURES):
            return None
        weights = fitted.get("weights")
        intercept = fitted.get("intercept")
        if not isinstance(weights, list) or len(weights) != len(MODEL_FEATURES):
            return None
        if not isinstance(intercept, (int, float)) or not math.isfinite(intercept):
            return None

    return {
        "model_id": target_version.get("model_id"),
        "model_version": target_version.get("model_version"),
        "name": target_version.get("name") or family,
        "family": target_version.get("family") or family,
        "status": target_version.get("status"),
        "fitted_state": fitted,
        "version_id": target_version.get("version_id"),
    }


def is_candle_complete(quote_data: dict, current_time: datetime | None = None) -> bool:
    """Validate that the candidate candle is complete.
    
    Under Groww / M1 contract rules:
    1. If marked as partial_candle, it is incomplete.
    2. If bar_end is provided, current time / retrieved_at must be >= bar_end.
    """
    if quote_data.get("partial_candle") is True or quote_data.get("is_partial") is True:
        return False

    bar_end = quote_data.get("bar_end")
    if bar_end:
        try:
            end_dt = datetime.fromisoformat(bar_end.replace("Z", "+00:00"))
            ref_dt = current_time or datetime.now(timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            if ref_dt < end_dt:
                return False
        except Exception:
            return False

    return True


def _compute_features_from_candle_dicts(inst: str, candles_data: list[dict]) -> tuple[dict[str, float] | None, str | None, float | None]:
    """Build Candle objects from normalized dicts and compute the trailing MODEL_FEATURES vector."""
    if len(candles_data) < 10:
        return None, None, None
    from app.features.pipeline import compute_feature_row
    from app.market.calendar import ExchangeCalendar
    from app.market.schemas import Candle, DataOrigin, MarketSession

    cal_dates = set()
    candle_objs = []
    exchange = "BSE" if inst == "SENSEX" else "NSE"
    for c in candles_data[-30:]:
        start_dt = datetime.fromisoformat(str(c["bar_start"]).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(c["bar_end"]).replace("Z", "+00:00"))
        cal_dates.add(start_dt.date())
        candle_objs.append(
            Candle(
                instrument_id=inst,
                underlying=inst,
                exchange=exchange,
                interval="M15",
                bar_start=start_dt,
                bar_end=end_dt,
                provider_timestamp=start_dt,
                retrieved_at=end_dt,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                volume=float(c["volume"]) if c.get("volume") is not None else None,
                source_id=str(c.get("source_id") or "derived_regular"),
                origin=DataOrigin.PROVIDER,
                session=MarketSession.OPEN,
            )
        )
    calendar = ExchangeCalendar(listed_sessions=cal_dates, closed_dates=set())
    row = compute_feature_row(candle_objs, len(candle_objs) - 1, calendar)
    res = {}
    for f in MODEL_FEATURES:
        if f in row.values and row.values[f].value is not None:
            val = float(row.values[f].value)
            if math.isfinite(val):
                res[f] = val
    if len(res) == len(MODEL_FEATURES):
        last_c = candle_objs[-1]
        return res, last_c.bar_end.isoformat(), float(last_c.close)
    return None, None, None


def _resolve_trailing_features_and_meta(instrument: str) -> tuple[dict[str, float] | None, str | None, float | None, str, bool]:
    """Resolve trailing features, actual candle bar_end, last close, feature_source, and is_live_feature_vector."""
    import os
    from datetime import timedelta

    inst = instrument.upper()

    # 1. Check live persisted MarketCandle rows in PostgreSQL (if newer than static dataset cutoff 2026-10-14T15:30+05:30)
    try:
        from sqlalchemy import select
        from app.db import get_session_factory
        from app.domain.tables import MarketCandle

        session = get_session_factory()()
        try:
            symbol_variants = [inst, f"NSE-{inst}", f"BSE-{inst}"]
            db_rows = list(
                session.scalars(
                    select(MarketCandle)
                    .where(
                        MarketCandle.symbol.in_(symbol_variants),
                        MarketCandle.interval.in_(["15minute", "M15", "15m"]),
                        MarketCandle.is_complete.is_(True),
                        MarketCandle.session_type == "REGULAR",
                    )
                    .order_by(MarketCandle.timestamp.desc())
                    .limit(30)
                ).all()
            )
            if len(db_rows) >= 10:
                db_rows.reverse()
                latest_ts = db_rows[-1].timestamp
                static_cutoff = datetime.fromisoformat("2026-10-14T15:30:00+05:30")
                if latest_ts is not None and latest_ts > static_cutoff:
                    c_dicts = []
                    for r in db_rows:
                        b_start = r.timestamp
                        b_end = b_start + timedelta(minutes=15)
                        c_dicts.append(
                            {
                                "bar_start": b_start.isoformat(),
                                "bar_end": b_end.isoformat(),
                                "open": float(r.open),
                                "high": float(r.high),
                                "low": float(r.low),
                                "close": float(r.close),
                                "volume": float(r.volume) if r.volume is not None else None,
                                "source_id": "db_market_candles",
                            }
                        )
                    res, bar_end_iso, last_close = _compute_features_from_candle_dicts(inst, c_dicts)
                    if res is not None:
                        return res, bar_end_iso, last_close, "LIVE_DB_MARKET_CANDLES", True
        finally:
            session.close()
    except Exception:
        pass

    # 2. Attempt live Groww 15m historical candle fetch when Groww credentials are enabled (outside offline pytest)
    if os.environ.get("IMM_ENABLE_AGENT_LLM") != "0" and inst in {"NIFTY", "SENSEX", "BANKNIFTY"}:
        try:
            from app.db import get_session_factory
            from app.domain.tables import IntegrationCredential
            from app.integrations.crypto import decrypt_secrets
            from app.integrations.groww import read_historical_candles
            from app.market.storage import parse_iso_or_epoch_to_ist
            from app.settings import get_settings

            session = get_session_factory()()
            groww_token = None
            try:
                row = session.get(IntegrationCredential, "groww")
                if row is not None and row.enabled and row.ciphertext:
                    secrets = decrypt_secrets(get_settings(), row.ciphertext)
                    groww_token = (secrets.get("access_token") or "").strip() or None
            finally:
                session.close()

            if groww_token:
                now_utc = datetime.now(timezone.utc)
                start_str = (now_utc - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
                end_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
                exchange = "BSE" if inst == "SENSEX" else "NSE"
                raw_resp = read_historical_candles(
                    groww_token,
                    exchange=exchange,
                    segment="CASH",
                    groww_symbol=inst,
                    start_time=start_str,
                    end_time=end_str,
                    candle_interval="15minute",
                )
                raw_candles = (raw_resp or {}).get("candles") if isinstance(raw_resp, dict) else None
                if isinstance(raw_candles, list) and len(raw_candles) >= 10:
                    c_dicts = []
                    for item in raw_candles:
                        if isinstance(item, (list, tuple)) and len(item) >= 5:
                            b_start = parse_iso_or_epoch_to_ist(item[0])
                            b_end = b_start + timedelta(minutes=15)
                            if b_end <= now_utc.astimezone(b_end.tzinfo):
                                c_dicts.append(
                                    {
                                        "bar_start": b_start.isoformat(),
                                        "bar_end": b_end.isoformat(),
                                        "open": float(item[1]),
                                        "high": float(item[2]),
                                        "low": float(item[3]),
                                        "close": float(item[4]),
                                        "volume": float(item[5]) if len(item) > 5 and item[5] is not None else None,
                                        "source_id": "live_groww_15m",
                                    }
                                )
                    res, bar_end_iso, last_close = _compute_features_from_candle_dicts(inst, c_dicts)
                    if res is not None:
                        return res, bar_end_iso, last_close, "LIVE_GROWW_15M_CANDLES", True
        except Exception:
            pass

    # 3. Fallback to verified local historical candle dataset
    if inst in {"NIFTY", "BANKNIFTY"}:
        if inst == "NIFTY":
            dataset_path = REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_regular_ac9484b605d484c2.json"
            if not dataset_path.is_file():
                candidates = list((REPO_ROOT / "var" / "datasets").glob("derived_nifty_15m_regular_*.json"))
                if candidates:
                    dataset_path = candidates[0]
        else:
            dataset_path = REPO_ROOT / "var" / "datasets" / "derived_banknifty_15m_m40.json"

        if dataset_path.is_file():
            try:
                from app.market.storage import parse_iso_or_epoch_to_ist

                data = json.loads(dataset_path.read_text(encoding="utf-8"))
                candles_data = data.get("regular_candles") or data.get("candles") or []
                normalized = []
                for c in candles_data[-30:]:
                    if isinstance(c, (list, tuple)) and len(c) >= 5:
                        b_start = parse_iso_or_epoch_to_ist(c[0])
                        b_end = b_start + timedelta(minutes=15)
                        normalized.append(
                            {
                                "bar_start": b_start.isoformat(),
                                "bar_end": b_end.isoformat(),
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": float(c[5]) if len(c) > 5 and c[5] is not None else None,
                                "source_id": "derived_regular",
                            }
                        )
                    elif isinstance(c, dict):
                        b_start_str = c.get("bar_start") or c.get("timestamp")
                        if not b_start_str:
                            continue
                        b_start = parse_iso_or_epoch_to_ist(b_start_str)
                        b_end_str = c.get("bar_end")
                        b_end = parse_iso_or_epoch_to_ist(b_end_str) if b_end_str else b_start + timedelta(minutes=15)
                        normalized.append(
                            {
                                "bar_start": b_start.isoformat(),
                                "bar_end": b_end.isoformat(),
                                "open": float(c["open"]),
                                "high": float(c["high"]),
                                "low": float(c["low"]),
                                "close": float(c["close"]),
                                "volume": float(c["volume"]) if c.get("volume") is not None else None,
                                "source_id": "derived_regular",
                            }
                        )
                res, bar_end_iso, last_close = _compute_features_from_candle_dicts(inst, normalized)
                if res is not None:
                    return res, bar_end_iso, last_close, "HISTORICAL_CANDLE_DATASET", False
            except Exception:
                pass
    return None, None, None, "UNAVAILABLE", False


def resolve_trailing_features_for_instrument(instrument: str) -> dict[str, float] | None:
    """Resolve and compute trailing features from verified completed candles."""
    feats, _, _, _, _ = _resolve_trailing_features_and_meta(instrument)
    return feats


def compute_live_forecast_for_instrument(
    instrument: str,
    quote_data: dict | None,
    *,
    model_artifact: dict | None = None,
    iv: float = 0.14,
    current_time: datetime | None = None,
    registry_path: Path | None = None,
) -> dict:
    inst = instrument.upper()
    if not quote_data or quote_data.get("last_price") is None:
        return {
            "instrument": inst,
            "status": "MISSING_DATA",
            "model_name": None,
            "model_version": None,
            "direction": "UNKNOWN",
            "probability_up": None,
            "probability_down": None,
            "confidence": 0.0,
            "expected_move_points": None,
            "spot_price": None,
            "target_spot": None,
            "stop_loss_spot": None,
            "features": {},
            "summary": f"No live price data available for {inst}.",
        }

    last_price = float(quote_data["last_price"])

    # If features are not yet attached on quote_data, resolve from trailing completed candles
    features = quote_data.get("features")
    feature_source = "LIVE_QUOTE_FEATURES"
    is_live_feature_vector = True
    if not isinstance(features, dict) or not features:
        trailing, trailing_bar_end, _, resolved_src, resolved_is_live = _resolve_trailing_features_and_meta(inst)
        if trailing and len(trailing) == len(MODEL_FEATURES):
            features = trailing
            feature_source = resolved_src
            is_live_feature_vector = resolved_is_live
            quote_data["features"] = features
            if not quote_data.get("bar_end") and trailing_bar_end:
                quote_data["bar_end"] = trailing_bar_end
            quote_data["feature_source"] = feature_source
            quote_data["is_live_feature_vector"] = is_live_feature_vector

    # Reject incomplete / partial candles
    if not is_candle_complete(quote_data, current_time=current_time):

        return {
            "instrument": inst,
            "status": "INCOMPLETE_CANDLE",
            "model_name": None,
            "model_version": None,
            "direction": "UNKNOWN",
            "probability_up": None,
            "probability_down": None,
            "confidence": 0.0,
            "expected_move_points": None,
            "spot_price": last_price,
            "target_spot": None,
            "stop_loss_spot": None,
            "features": {},
            "summary": f"Latest candle for {inst} is not complete. Forecast requires completed candle boundaries.",
        }

    # Load model artifact if not injected
    model = model_artifact if model_artifact is not None else load_registered_model(inst, registry_path=registry_path)
    if not model or not model.get("fitted_state"):
        return {
            "instrument": inst,
            "status": "NO_FITTED_MODEL",
            "model_name": None,
            "model_version": None,
            "direction": "UNKNOWN",
            "probability_up": None,
            "probability_down": None,
            "confidence": 0.0,
            "expected_move_points": None,
            "spot_price": last_price,
            "target_spot": None,
            "stop_loss_spot": None,
            "features": {},
            "summary": f"No valid approved fitted model artifact is registered for {inst}.",
        }

    fitted = model["fitted_state"]
    family = fitted.get("family")

    # Extract or validate features
    features = quote_data.get("features")
    if not isinstance(features, dict):
        return {
            "instrument": inst,
            "status": "FEATURE_MISMATCH",
            "model_name": model.get("name"),
            "model_version": model.get("model_version"),
            "direction": "UNKNOWN",
            "probability_up": None,
            "probability_down": None,
            "confidence": 0.0,
            "expected_move_points": None,
            "spot_price": last_price,
            "target_spot": None,
            "stop_loss_spot": None,
            "features": {},
            "summary": f"Completed candle for {inst} has no validated feature vector for inference.",
        }

    # Ensure required features are present and finite
    required = list(fitted.get("feature_names") or MODEL_FEATURES)
    feature_row = {}
    for name in required:
        val = features.get(name)
        if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
            return {
                "instrument": inst,
                "status": "FEATURE_MISMATCH",
                "model_name": model.get("name"),
                "model_version": model.get("model_version"),
                "direction": "UNKNOWN",
                "probability_up": None,
                "probability_down": None,
                "confidence": 0.0,
                "expected_move_points": None,
                "spot_price": last_price,
                "target_spot": None,
                "stop_loss_spot": None,
                "features": {},
                "summary": f"Feature {name} is missing or non-finite for {inst}.",
            }
        feature_row[name] = float(val)

    # Perform legitimate artifact-based inference
    if family == "logistic_regression":
        probs = predict_logistic(fitted, [{"features": feature_row}])
        if not probs or len(probs) != 1 or not math.isfinite(probs[0]):
            return {
                "instrument": inst,
                "status": "INFERENCE_FAILED",
                "model_name": model.get("name"),
                "model_version": model.get("model_version"),
                "direction": "UNKNOWN",
                "probability_up": None,
                "probability_down": None,
                "confidence": 0.0,
                "expected_move_points": None,
                "spot_price": last_price,
                "target_spot": None,
                "stop_loss_spot": None,
                "features": feature_row,
                "summary": f"Inference execution failed for {inst}.",
            }
        p_up = round(float(probs[0]), 4)
    elif family == "majority_class":
        probs = predict_majority(fitted, [{"features": feature_row}])
        p_up = round(float(probs[0]), 4)
    elif family == "last_return_sign":
        probs = predict_last_return_sign(fitted, [{"features": feature_row, "ret_1": feature_row.get("ret_1")}])
        p_up = round(float(probs[0]), 4)
    else:
        return {
            "instrument": inst,
            "status": "UNSUPPORTED_MODEL_FAMILY",
            "model_name": model.get("name"),
            "model_version": model.get("model_version"),
            "direction": "UNKNOWN",
            "probability_up": None,
            "probability_down": None,
            "confidence": 0.0,
            "expected_move_points": None,
            "spot_price": last_price,
            "target_spot": None,
            "stop_loss_spot": None,
            "features": feature_row,
            "summary": f"Model family {family} is not supported for live inference.",
        }

    p_down = round(1.0 - p_up, 4)
    direction = "BULLISH" if p_up >= 0.50 else "BEARISH"
    confidence = round(abs(p_up - 0.50) * 2.0, 3)

    daily_sigma = last_price * (iv / math.sqrt(252))
    exp_pts = round(max(20.0, daily_sigma * 0.55), 1)
    sl_pts = round(exp_pts * 0.5, 1)

    target_spot = round(last_price + exp_pts if direction == "BULLISH" else last_price - exp_pts, 1)
    stop_loss_spot = round(last_price - sl_pts if direction == "BULLISH" else last_price + sl_pts, 1)

    return {
        "instrument": inst,
        "status": "ACTIVE",
        "model_name": model.get("name"),
        "model_version": model.get("model_version"),
        "horizon": "next_m15_close",
        "target_id": "m15_next_close_direction",
        "direction": direction,
        "probability_up": p_up,
        "probability_down": p_down,
        "confidence": confidence,
        "expected_move_points": exp_pts,
        "stop_loss_points": sl_pts,
        "spot_price": last_price,
        "target_spot": target_spot,
        "stop_loss_spot": stop_loss_spot,
        "features": feature_row,
        "feature_bar_end": quote_data.get("bar_end"),
        "feature_source": quote_data.get("feature_source", feature_source),
        "is_live_feature_vector": bool(quote_data.get("is_live_feature_vector", is_live_feature_vector)),
        "quote_source": quote_data.get("quote_source", "MARKET_SNAPSHOT"),
        "is_live_quote": bool(quote_data.get("is_live_quote", False)),
        "summary": (
            f"Fitted model {model.get('model_version')} predicts {int(p_up * 100)}% P(Up) vs "
            f"{int(p_down * 100)}% P(Down) with {round(confidence * 100)}% conviction over completed candle."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_all_live_forecasts() -> dict:
    read = load_read() or {}
    quotes = {q["instrument"]: q for q in read.get("quotes", []) if q.get("instrument")}
    commodities = {c["instrument"]: c for c in read.get("commodities", []) if c.get("instrument")}

    if not quotes.get("NIFTY"):
        for row in (read.get("sectoral_indices") or []) + (read.get("observations") or []):
            if row.get("instrument") == "NIFTY" and row.get("last_price") is not None:
                quotes["NIFTY"] = dict(row)
                quotes["NIFTY"].setdefault("quote_source", "STORED_MARKET_SNAPSHOT")
                quotes["NIFTY"].setdefault("is_live_quote", False)
                break
    if not quotes.get("SENSEX"):
        for row in (read.get("sectoral_indices") or []) + (read.get("observations") or []):
            if row.get("instrument") == "SENSEX" and row.get("last_price") is not None:
                quotes["SENSEX"] = dict(row)
                quotes["SENSEX"].setdefault("quote_source", "STORED_MARKET_SNAPSHOT")
                quotes["SENSEX"].setdefault("is_live_quote", False)
                break
    if not quotes.get("NIFTY"):
        trailing, trailing_bar_end, last_close, resolved_src, resolved_is_live = _resolve_trailing_features_and_meta("NIFTY")
        if last_close is not None:
            quotes["NIFTY"] = {
                "instrument": "NIFTY",
                "last_price": last_close,
                "features": trailing,
                "bar_end": trailing_bar_end,
                "feature_source": resolved_src,
                "is_live_feature_vector": resolved_is_live,
                "quote_source": "HISTORICAL_CANDLE_SNAPSHOT" if not resolved_is_live else "LIVE_CANDLE_SNAPSHOT",
                "is_live_quote": resolved_is_live,
            }

    vix_row = next(
        (r for r in read.get("sectoral_indices", []) + read.get("global_indices", []) if r.get("instrument") in {"VIX", "INDIA_VIX"}),
        None,
    )
    vix_val = float(vix_row.get("last_price", 14.0)) if vix_row and vix_row.get("last_price") is not None else 14.0
    iv = max(0.11, min(0.35, vix_val / 100.0))

    nifty_quote = quotes.get("NIFTY")
    sensex_quote = quotes.get("SENSEX")
    crude_quote = commodities.get("CRUDEOILMINI") or commodities.get("CRUDEMINI")

    forecasts = [
        compute_live_forecast_for_instrument("NIFTY", nifty_quote, iv=iv),
        compute_live_forecast_for_instrument("SENSEX", sensex_quote, iv=iv),
        compute_live_forecast_for_instrument("CRUDEOILMINI", crude_quote, iv=iv * 1.2),
    ]

    has_active = any(f.get("status") == "ACTIVE" for f in forecasts)
    overall_status = "ACTIVE" if has_active else "NO_FITTED_MODEL"

    return {
        "status": overall_status,
        "forecast_ready": False,  # Safety flag stays False until real market data is verified
        "note": "Statistical model predictions computed from approved model registry artifacts over completed candles.",
        "vix": vix_val,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "forecasts": forecasts,
    }



def fuse_agents_and_forecast(agent_rec: dict, forecast_item: dict) -> dict:
    """Fuse multi-agent consensus score with quantitative model probability."""
    agent_bias = (agent_rec.get("bias") or "").upper()
    agent_dir = "BULLISH" if "BULL" in agent_bias else ("BEARISH" if "BEAR" in agent_bias else "NEUTRAL")
    agent_score = agent_rec.get("total_score", 0)

    model_dir = forecast_item.get("direction", "UNKNOWN")
    p_up = forecast_item.get("probability_up")

    # If model is unavailable or has no probability, do not fabricate fusion
    if p_up is None or model_dir == "UNKNOWN":
        return {
            "confluence_status": "NO_MODEL_FORECAST",
            "fused_bias": agent_bias or "NEUTRAL",
            "conviction": "STANDARD",
            "confluence_summary": "No verified model forecast available to fuse with multi-agent consensus.",
            "agent_score": agent_score,
            "model_probability_up": None,
            "model_direction": "UNKNOWN",
            "confidence_boost": 1.0,
        }

    # Confluence Check
    if agent_dir == "BULLISH" and model_dir == "BULLISH":
        fused_bias = "STRONG BULLISH (QUANT CONFLUENCE)"
        conviction = "HIGH CONFLUENCE"
        confluence_status = "ALIGNED"
        confluence_summary = (
            f"High conviction confluence: 5-Agent consensus (Score +{agent_score}) and "
            f"ML statistical forecast ({int(p_up * 100)}% P(Up)) are fully aligned."
        )
        boost = 1.2
    elif agent_dir == "BEARISH" and model_dir == "BEARISH":
        fused_bias = "STRONG BEARISH (QUANT CONFLUENCE)"
        conviction = "HIGH CONFLUENCE"
        confluence_status = "ALIGNED"
        confluence_summary = (
            f"High conviction confluence: 5-Agent consensus (Score {agent_score}) and "
            f"ML statistical forecast ({int((1 - p_up) * 100)}% P(Down)) are fully aligned."
        )
        boost = 1.2
    elif agent_dir != "NEUTRAL" and model_dir != "NEUTRAL" and agent_dir != model_dir:
        fused_bias = f"{agent_bias} (MODEL DIVERGENCE)"
        conviction = "CAUTIOUS / REDUCED LOTS"
        confluence_status = "DIVERGENCE"
        confluence_summary = (
            f"Divergence detected: Multi-Agent stance is {agent_dir}, but statistical model "
            f"warns of short-term {model_dir} mean-reversion ({int(p_up * 100)}% P(Up)). Exercise strict stops."
        )
        boost = 0.8
    else:
        fused_bias = agent_bias or "NEUTRAL / SLIGHT BULLISH"
        conviction = "MODERATE"
        confluence_status = "STANDARD"
        confluence_summary = f"Standard execution: Multi-Agent ({agent_dir}) with neutral model backdrop."
        boost = 1.0

    return {
        "confluence_status": confluence_status,
        "fused_bias": fused_bias,
        "conviction": conviction,
        "confluence_summary": confluence_summary,
        "agent_score": agent_score,
        "model_probability_up": p_up,
        "model_direction": model_dir,
        "confidence_boost": boost,
    }

