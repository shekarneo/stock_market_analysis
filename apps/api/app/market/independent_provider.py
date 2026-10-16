"""Milestone M15: Independent Data Provider Integration and Verification.

Provides documented candidate evaluation, adapter scaffolding, schema validation,
pagination, rate limiting, raw-payload quarantine, separate normalization, and
reconciliation against quarantined Groww datasets for independent market data providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Protocol

from app.market.schemas import IST, require_aware
from app.settings import REPO_ROOT

# Regex for masking secret values
_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+)[^\s'\"]+|(token|api[_-]?key|secret|password|ciphertext)\s*[:=]\s*['\"]?[^\s'\",}]+['\"]?"
)


def mask_secrets(text: str) -> str:
    """Mask credentials and tokens in strings so they never leak into logs or errors."""
    return _SECRET_PATTERN.sub(r"\1[REDACTED]", text)


# Detailed candidate provider specifications
INDEPENDENT_PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "upstox": {
        "name": "Upstox Historical Candle API v3",
        "documentation_url": "https://upstox.com/developer/api-documentation/v3/get-historical-candle-data",
        "supported_intervals": ["1minute", "15minute", "30minute", "day"],
        "nifty_15m_supported": True,
        "nifty_instrument_key": "NSE_INDEX|Nifty 50",
        "required_credentials": ["access_token"],
        "auth_header_format": "Bearer {access_token}",
        "max_range_per_request_days": 30,
        "retention_intraday": "From January 2022 to present",
        "rate_limit_requests_per_sec": 5,
        "rate_limit_min_interval_sec": 0.20,
        "timestamp_semantics": "Start of candle timeframe (bar-start)",
        "timestamp_format": "ISO-8601 with offset (e.g., 2026-10-13T09:15:00+05:30)",
        "candles_per_normal_session": 25,
        "has_1530_candle": False,
        "independence": (
            "Genuinely independent broker infrastructure. Upstox operates separate exchange gateway "
            "and tick processing from Groww."
        ),
        "licensing": "Upstox Developer Terms of Service for non-redistribution automated trading.",
    },
    "kite": {
        "name": "Zerodha Kite Connect v3 Historical Data",
        "documentation_url": "https://kite.trade/docs/connect/v3/historical/",
        "supported_intervals": ["minute", "15minute", "30minute", "60minute", "day"],
        "nifty_15m_supported": True,
        "nifty_instrument_key": "256265",  # NIFTY 50 instrument token on NSE
        "required_credentials": ["api_key", "access_token"],
        "auth_header_format": "token {api_key}:{access_token}",
        "max_range_per_request_days": 60,
        "retention_intraday": "Several years continuous",
        "rate_limit_requests_per_sec": 3,
        "rate_limit_min_interval_sec": 0.35,
        "timestamp_semantics": "Start of candle timeframe (bar-start)",
        "timestamp_format": "ISO-8601 with offset (e.g., 2026-10-13T09:15:00+0530)",
        "candles_per_normal_session": 25,
        "has_1530_candle": False,
        "independence": (
            "Genuinely independent broker infrastructure. Zerodha OMS (Omnesys/Kite) and data pipeline "
            "are completely independent of Groww."
        ),
        "licensing": "Paid Kite Connect developer subscription + Historical Data add-on.",
    },
    "angelone": {
        "name": "Angel One SmartAPI Historical Data",
        "documentation_url": "https://smartapi.angelbroking.com/docs/Historical",
        "supported_intervals": ["ONE_MINUTE", "FIFTEEN_MINUTE", "ONE_DAY"],
        "nifty_15m_supported": True,
        "nifty_instrument_key": "99926000",
        "required_credentials": ["api_key", "client_code", "jwt_token"],
        "auth_header_format": "Bearer {jwt_token}",
        "max_range_per_request_days": 200,
        "retention_intraday": "Active instruments history",
        "rate_limit_requests_per_sec": 3,
        "rate_limit_min_interval_sec": 0.35,
        "timestamp_semantics": "Documented ISO string without explicit bar boundary contract",
        "timestamp_format": "ISO-8601 (e.g., 2026-10-13T09:15:00+05:30)",
        "candles_per_normal_session": 25,
        "has_1530_candle": False,
        "independence": "Independent broker infrastructure.",
        "licensing": "SmartAPI user agreement.",
    },
    "nse_official": {
        "name": "National Stock Exchange Official Reports",
        "documentation_url": "https://nseindia.com/reports-indices-historical-index-data",
        "supported_intervals": ["daily"],
        "nifty_15m_supported": False,
        "nifty_instrument_key": "NIFTY 50",
        "required_credentials": [],
        "max_range_per_request_days": 365,
        "retention_intraday": "Not available on free public portal",
        "timestamp_semantics": "Daily settlement date (DD-MM-YYYY)",
        "independence": "Exchange originator.",
        "licensing": "Public viewing only.",
    },
}


@dataclass
class ProviderCandleRequest:
    provider: str
    instrument: str = "NIFTY"
    interval: str = "15minute"
    from_date: date = field(default_factory=lambda: date(2026, 4, 14))
    to_date: date = field(default_factory=lambda: date(2026, 10, 13))


class TransportProtocol(Protocol):
    def fetch(self, url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> dict: ...


def resolve_credentials_safe(provider: str, session: Any = None, settings: Any = None) -> tuple[dict[str, str] | None, list[str]]:
    """Resolve credentials for an independent provider without exposing ciphertext or values.

    Returns:
        (credentials_dict or None, list_of_missing_keys)
    """
    spec = INDEPENDENT_PROVIDER_SPECS.get(provider.lower())
    if not spec:
        return None, [f"unknown_provider_{provider}"]

    required_keys = spec["required_credentials"]
    if not required_keys:
        return {}, []

    if session is None:
        try:
            from app.db import get_engine
            from sqlalchemy.orm import Session
            from app.domain.tables import IntegrationCredential

            with Session(get_engine()) as db_session:
                row = db_session.get(IntegrationCredential, provider.lower())
                if not row or not row.ciphertext:
                    return None, required_keys
                if not row.enabled:
                    return None, [f"{k} (provider disabled)" for k in required_keys]
                # Decrypt if settings provided
                if settings is not None:
                    from app.security import decrypt_secrets
                    decrypted = decrypt_secrets(settings, row.ciphertext)
                    missing = [k for k in required_keys if not decrypted.get(k)]
                    if missing:
                        return None, missing
                    return decrypted, []
                return None, required_keys
        except Exception:
            return None, required_keys

    return None, required_keys


def validate_provider_candle_payload(provider: str, payload: Any) -> tuple[bool, str, list[list[Any]]]:
    """Validate the raw JSON response schema from a candidate independent market data provider.

    Rejects malformed envelopes, non-numeric prices, boolean types, and geometric violations.
    """
    if not isinstance(payload, dict):
        return False, "Payload must be a JSON object dictionary.", []

    p_lower = provider.lower()
    raw_candles: list[list[Any]] = []

    if p_lower == "upstox":
        if payload.get("status") != "success":
            return False, f"Upstox status was not 'success': {payload.get('status')}", []
        data = payload.get("data")
        if not isinstance(data, dict) or "candles" not in data:
            return False, "Upstox payload missing 'data.candles' array.", []
        raw_candles = data.get("candles") or []
    elif p_lower == "kite":
        if payload.get("status") != "success":
            return False, f"Kite status was not 'success': {payload.get('status')}", []
        data = payload.get("data")
        if not isinstance(data, dict) or "candles" not in data:
            return False, "Kite payload missing 'data.candles' array.", []
        raw_candles = data.get("candles") or []
    elif p_lower == "angelone":
        if payload.get("status") is not True:
            return False, f"Angel One status was not True: {payload.get('status')}", []
        raw_candles = payload.get("data") or []
    else:
        # Generic envelope fallback
        raw_candles = payload.get("candles") or payload.get("data") or []

    if not isinstance(raw_candles, list):
        return False, "Candles structure is not an array.", []

    # Validate individual raw candle rows
    for i, row in enumerate(raw_candles):
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            return False, f"Candle at index {i} must be an array with at least 5 elements [timestamp, o, h, l, c].", []
        ts, o, h, l, c = row[0], row[1], row[2], row[3], row[4]
        if not isinstance(ts, str):
            return False, f"Candle at index {i} timestamp must be an ISO string.", []

        # Boolean protection: Python booleans are instances of int
        if any(isinstance(v, bool) for v in (o, h, l, c)):
            return False, f"Candle at index {i} contains forbidden boolean value in OHLC.", []

        try:
            fo, fh, fl, fc = float(o), float(h), float(l), float(c)
        except (ValueError, TypeError):
            return False, f"Candle at index {i} contains non-numeric OHLC values.", []

        if fo <= 0 or fh <= 0 or fl <= 0 or fc <= 0:
            return False, f"Candle at index {i} contains non-positive price values.", []

        if fh < max(fo, fc) or fl > min(fo, fc) or fh < fl:
            return False, f"Candle at index {i} violates geometric OHLC bounds (high={fh}, low={fl}, open={fo}, close={fc}).", []

    return True, "Schema valid", raw_candles


def split_date_range_chunks(from_date: date, to_date: date, max_days: int) -> list[tuple[date, date]]:
    """Split date range into non-overlapping chronological chunks adhering to provider limits."""
    if from_date > to_date:
        raise ValueError(f"from_date ({from_date}) cannot be after to_date ({to_date}).")
    chunks = []
    curr = from_date
    while curr <= to_date:
        chunk_end = min(curr + timedelta(days=max_days - 1), to_date)
        chunks.append((curr, chunk_end))
        curr = chunk_end + timedelta(days=1)
    return chunks


def quarantine_reference_response(
    provider: str,
    raw_payload: dict | list,
    request: ProviderCandleRequest,
    quarantine_dir: Path | None = None,
) -> tuple[str, Path]:
    """Preserve raw independent provider response into quarantine with immutable SHA-256 provenance."""
    q_dir = quarantine_dir or (REPO_ROOT / "var" / "history" / "quarantine")
    q_dir.mkdir(parents=True, exist_ok=True)

    raw_bytes = json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()

    meta_record = {
        "quarantine_id": raw_sha,
        "provider": provider.lower(),
        "instrument": request.instrument,
        "interval": request.interval,
        "from_date": request.from_date.isoformat(),
        "to_date": request.to_date.isoformat(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "raw_sha256": raw_sha,
        "schema_verified": True,
        "reconciled": False,
        "trusted": False,
        "raw_payload": raw_payload,
    }

    target_path = q_dir / f"ref_{provider.lower()}_{raw_sha}.json"
    target_path.write_text(json.dumps(meta_record, indent=2), encoding="utf-8")
    return raw_sha, target_path


def normalize_reference_candles(
    raw_candles: list[list[Any]],
    provider: str,
) -> list[dict[str, Any]]:
    """Traceable, separate transformation step converting raw provider tuples to standardized records.

    Verifies IST offset (+05:30) and detects duplicate or unexpected timestamps.
    """
    normalized = []
    seen_timestamps: set[str] = set()

    for idx, row in enumerate(raw_candles):
        ts_raw = row[0]
        try:
            # Parse ISO timestamp
            dt = datetime.fromisoformat(ts_raw)
            if dt.tzinfo is not None:
                offset_secs = dt.utcoffset().total_seconds()
                if offset_secs != 19800:  # 5.5 hours * 3600 = 19800s
                    raise ValueError(f"Non-IST timezone offset ({offset_secs}s) in candle {ts_raw}")
            else:
                # Require explicit timezone offset
                raise ValueError(f"Timestamp {ts_raw} lacks explicit timezone offset")
            iso_norm = dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")
        except Exception as exc:
            raise ValueError(f"Normalization failed at index {idx} ({ts_raw}): {exc}") from exc

        if iso_norm in seen_timestamps:
            raise ValueError(f"Duplicate timestamp {iso_norm} in provider response at index {idx}")
        seen_timestamps.add(iso_norm)

        vol = None
        if len(row) > 5 and row[5] is not None:
            try:
                vol = float(row[5])
            except (ValueError, TypeError):
                vol = None

        normalized.append({
            "index": idx,
            "raw_timestamp": ts_raw,
            "timestamp": iso_norm,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": vol,
            "provider": provider.lower(),
        })

    return normalized


def investigate_1530_observation(groww_1530_candle: dict[str, Any]) -> dict[str, Any]:
    """Examine the 15:30 observation without assuming closing-auction tick.

    M15 rule: Do not label it as a closing-auction tick solely because OHLC values
    are identical or volume is zero. Require documented provider semantics or
    independent authoritative evidence.
    """
    o, h, l, c = groww_1530_candle.get("open"), groww_1530_candle.get("high"), groww_1530_candle.get("low"), groww_1530_candle.get("close")
    vol = groww_1530_candle.get("volume")
    identical_ohlc = (o == h == l == c)
    zero_vol = (vol == 0 or vol is None)

    return {
        "timestamp": groww_1530_candle.get("raw_timestamp"),
        "empirical_properties": {
            "identical_ohlc": identical_ohlc,
            "zero_or_null_volume": zero_vol,
            "values": {"open": o, "high": h, "low": l, "close": c, "volume": vol},
        },
        "provider_documentation_status": "UNDOCUMENTED_BY_GROWW",
        "market_mechanics_evidence": (
            "NSE normal continuous trading closes at 15:30:00 IST. The 25 regular 15-minute bars "
            "span 09:15 to 15:15 (bar-start convention). Independent providers (Upstox, Zerodha Kite) "
            "do not emit a 26th continuous 15-minute candle for 15:30."
        ),
        "authoritative_classification": (
            "SESSION_BOUNDARY_OBSERVATION_UNDOCUMENTED_SEMANTICS"
            if not groww_1530_candle.get("authoritative_reference_verified")
            else "POST_SESSION_AUCTION_SETTLEMENT"
        ),
        "exclusion_policy": "EXCLUDE_FROM_CONTINUOUS_TRADING_BARS",
        "rationale": (
            "Excluded from regular feature generation and returns because continuous market trading "
            "is closed at 15:30. Labeling as closing auction tick is withheld until confirmed by an "
            "independent reference contract."
        ),
    }


class IndependentProviderAdapter:
    """Reusable adapter for independent market data providers (Upstox, Kite Connect, Angel One)."""

    def __init__(
        self,
        provider: str = "upstox",
        transport: TransportProtocol | None = None,
        rate_limiter: Callable[[], None] | None = None,
    ) -> None:
        p_clean = provider.lower()
        if p_clean not in INDEPENDENT_PROVIDER_SPECS:
            raise ValueError(f"Unsupported independent provider '{provider}'. Must be one of {list(INDEPENDENT_PROVIDER_SPECS.keys())}.")
        self.provider = p_clean
        self.spec = INDEPENDENT_PROVIDER_SPECS[p_clean]
        self.transport = transport
        self.rate_limiter = rate_limiter
        self._last_request_time: float = 0.0

    def get_spec(self) -> dict[str, Any]:
        return dict(self.spec)

    def _enforce_rate_limit(self) -> None:
        if self.rate_limiter is not None:
            self.rate_limiter()
            return
        min_interval = self.spec.get("rate_limit_min_interval_sec", 0.35)
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.monotonic()

    def fetch_reference_dataset(
        self,
        request: ProviderCandleRequest,
        credentials: dict[str, str] | None = None,
        quarantine: bool = True,
    ) -> dict[str, Any]:
        """Fetch, validate, quarantine, and normalize independent reference candles.

        Fails closed with BLOCKED_CREDENTIALS_MISSING if credentials are not configured.
        """
        # 1. Credential Check
        if credentials is None:
            creds, missing = resolve_credentials_safe(self.provider)
            if not creds:
                return {
                    "ok": False,
                    "code": "BLOCKED_CREDENTIALS_MISSING",
                    "status": "BLOCKED",
                    "provider": self.provider,
                    "message": (
                        f"Independent provider '{self.provider}' credentials missing or unconfigured: "
                        f"{missing}. Data acquisition is blocked."
                    ),
                    "required_credentials": self.spec["required_credentials"],
                    "missing_credentials": missing,
                    "data_acquired": False,
                    "forecast_ready": False,
                    "real_market_data_verified": False,
                    "paper_approved": False,
                    "live_approved": False,
                }
            credentials = creds

        # 2. Check Transport
        if self.transport is None:
            return {
                "ok": False,
                "code": "BLOCKED_TRANSPORT_UNAVAILABLE",
                "status": "BLOCKED",
                "provider": self.provider,
                "message": f"No active transport or network client configured for {self.provider}.",
                "data_acquired": False,
                "forecast_ready": False,
                "real_market_data_verified": False,
            }

        # 3. Chunking & Pagination
        max_chunk_days = self.spec.get("max_range_per_request_days", 30)
        chunks = split_date_range_chunks(request.from_date, request.to_date, max_chunk_days)

        all_raw_candles: list[list[Any]] = []
        raw_responses: list[dict] = []

        for chunk_idx, (c_from, c_to) in enumerate(chunks):
            self._enforce_rate_limit()
            url = f"https://api.{self.provider}.com/v3/historical/{request.instrument}"
            headers = {"Authorization": self.spec["auth_header_format"].format(**credentials)}
            params = {
                "interval": request.interval,
                "from_date": c_from.isoformat(),
                "to_date": c_to.isoformat(),
            }

            try:
                resp = self.transport.fetch(url, headers, params)
            except Exception as exc:
                clean_err = mask_secrets(str(exc))
                return {
                    "ok": False,
                    "code": "PROVIDER_FETCH_ERROR",
                    "status": "FAIL",
                    "provider": self.provider,
                    "chunk": chunk_idx,
                    "message": f"Provider fetch failed: {clean_err}",
                    "data_acquired": False,
                }

            valid, err_msg, chunk_candles = validate_provider_candle_payload(self.provider, resp)
            if not valid:
                return {
                    "ok": False,
                    "code": "INVALID_PROVIDER_PAYLOAD",
                    "status": "FAIL",
                    "provider": self.provider,
                    "chunk": chunk_idx,
                    "message": f"Payload schema validation failed: {err_msg}",
                    "data_acquired": False,
                }

            raw_responses.append(resp)
            all_raw_candles.extend(chunk_candles)

        # 4. Quarantine raw payload
        raw_sha, q_path = None, None
        if quarantine:
            raw_sha, q_path = quarantine_reference_response(
                self.provider,
                {"chunks": raw_responses, "total_raw_candles": len(all_raw_candles)},
                request,
            )

        # 5. Normalization Transformation
        try:
            normalized = normalize_reference_candles(all_raw_candles, self.provider)
        except ValueError as val_err:
            return {
                "ok": False,
                "code": "NORMALIZATION_ERROR",
                "status": "FAIL",
                "provider": self.provider,
                "message": f"Candle normalization failed: {val_err}",
                "raw_sha256": raw_sha,
                "data_acquired": False,
            }

        return {
            "ok": True,
            "code": "ACQUISITION_QUARANTINED",
            "status": "QUARANTINED",
            "provider": self.provider,
            "raw_sha256": raw_sha,
            "quarantine_path": str(q_path) if q_path else None,
            "total_candles": len(normalized),
            "normalized_candles": normalized,
            "data_acquired": True,
            "real_market_data_verified": False,
            "forecast_ready": False,
            "paper_approved": False,
            "live_approved": False,
        }
