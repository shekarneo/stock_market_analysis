"""Offline one-minute diagnostic. These tests do not call Groww."""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.tables import IntegrationCredential
from app.integrations.crypto import encrypt_secrets
from app.integrations.http import HttpResult
from app.integrations.service import save_groww
from app.market.history import HistoryStoreError
from app.market.minute_diagnostic import minute_query, run_minute_diagnostic
from app.market.retrieval import QuarantineStore, candle_query
from app.db import get_session_factory
from app.settings import REPO_ROOT, get_settings
from tests.test_integrations import ACCESS, API_KEY, API_SECRET

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 10, 13, 9, 15, tzinfo=IST)
END = datetime(2026, 10, 13, 9, 30, tzinfo=IST)
WHEN = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
QUARANTINE_HASHES = {
    "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057.json":
        "40ec5199e8a5f1059ce941d04a1a60ef15af6973286354ca1d8ecb7224f79075",
    "5edd4d3543825aa3a385092b9d16b3938e5995e026cbf3b2ade0872c18414a5d.json":
        "878e6b0406f83c8009cd0e47f9cd1466662b7125ed06b065ad9c828bca4bea7b",
    "f161aeef9e2846e74a3d200f4507ec3a9948b5d50b528eac227242efe65ec8e8.json":
        "af2f5a8c73f16b40ed7b7b7744b58acea16264b32c6a6ac338829aa8d48c778e",
}


@pytest.fixture
def session(db):
    db_session = get_session_factory()()
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


class Caller:
    def __init__(self, result=None, responses=None) -> None:
        self.result = result
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []
        self.urls: list[str] = []

    def send(self, method, url, *, headers, json_body, timeout):
        self.calls.append((method, url.split("?", 1)[0]))
        self.urls.append(url)
        assert "/v1/order/" not in url
        assert "/v1/token/" not in url
        if self.responses:
            return self.responses.pop(0)
        return self.result


def _prepare(session, *, enabled: bool, expiry: str, token: str | None = ACCESS):
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    row = session.get(IntegrationCredential, "groww")
    secrets = {"api_key": API_KEY, "api_secret": API_SECRET}
    if token:
        secrets["access_token"] = token
    row.ciphertext = encrypt_secrets(get_settings(), secrets)
    row.token_expiry = expiry
    row.derived_access_token = True
    row.enabled = enabled
    session.flush()
    return row


def _run(session, caller, store, **overrides):
    return run_minute_diagnostic(
        session,
        get_settings(),
        overrides.pop("start", START),
        overrides.pop("end", END),
        caller=caller,
        quarantine=store,
        retrieved_at=WHEN,
        parameters=overrides.pop("parameters", None),
    )


def test_disabled_integration_does_not_execute(session, tmp_path):
    row = _prepare(session, enabled=False, expiry="2099-01-01T00:00:00+00:00")
    caller = Caller()
    result = _run(session, caller, QuarantineStore(tmp_path))
    assert result["code"] == "INTEGRATION_DISABLED"
    assert result["network_calls"] == 0
    assert result["token_refreshed"] is False
    assert caller.calls == []
    assert row.enabled is False
    assert result["forecast_ready"] is False
    assert result["paper_approved"] is False
    assert result["live_approved"] is False
    assert result["real_market_data_verified"] is False


def test_one_minute_query_is_fixed_and_invalid_input_is_rejected():
    query = minute_query(START, END)
    assert query == {
        "exchange": "NSE",
        "segment": "CASH",
        "groww_symbol": "NSE-NIFTY",
        "start_time": "2026-10-13 09:15:00",
        "end_time": "2026-10-13 09:30:00",
        "candle_interval": "1minute",
    }
    assert candle_query("NIFTY", START, END)["candle_interval"] == "15minute"
    with pytest.raises(HistoryStoreError) as inverted:
        minute_query(END, START)
    assert inverted.value.code == "INVALID_RANGE"
    with pytest.raises(HistoryStoreError) as naive:
        minute_query(datetime(2026, 10, 13, 9, 15), END)
    assert naive.value.code == "INVALID_RANGE"
    with pytest.raises(HistoryStoreError) as broad:
        minute_query(START, START + timedelta(minutes=31))
    assert broad.value.code == "RANGE_TOO_LONG"
    with pytest.raises(HistoryStoreError) as interval:
        minute_query(START, END, {"candle_interval": "15minute"})
    assert interval.value.code == "UNSUPPORTED_QUERY"
    with pytest.raises(HistoryStoreError) as extra:
        minute_query(START, END, {"trading_symbol": "NIFTY", "url": "https://api.groww.in/v1/order/create"})
    assert extra.value.code == "UNSUPPORTED_QUERY"


def test_expired_ist_expiry_does_not_refresh_or_call(session, tmp_path):
    row = _prepare(session, enabled=True, expiry="2000-01-01T06:00:00")
    caller = Caller()
    result = _run(session, caller, QuarantineStore(tmp_path))
    assert result["code"] == "TOKEN_EXPIRED"
    assert "Asia/Kolkata" in result["message"]
    assert result["network_calls"] == 0
    assert result["token_refreshed"] is False
    assert result["retry"] is False
    assert caller.calls == []
    assert row.enabled is True
    assert ACCESS not in json.dumps(result)


def test_failure_is_not_retried_and_secrets_are_absent_from_logs(session, tmp_path, caplog):
    _prepare(session, enabled=True, expiry="2099-01-01T00:00:00+00:00")
    caller = Caller(result=HttpResult(500, {"status": "FAILURE"}, "nope", raw=b"nope"))
    with caplog.at_level(logging.INFO, logger="imm.market.minute_diagnostic"):
        result = _run(session, caller, QuarantineStore(tmp_path))
    assert result["code"] == "PROVIDER_UNAVAILABLE"
    assert result["retry"] is False
    assert result["token_refreshed"] is False
    assert caller.calls == [("GET", "https://api.groww.in/v1/historical/candles")]
    rendered = json.dumps(result) + caplog.text
    assert ACCESS not in rendered
    assert API_KEY not in rendered
    assert API_SECRET not in rendered
    assert "Bearer" not in rendered


def test_success_stays_quarantined_for_one_minute(session, tmp_path):
    _prepare(session, enabled=True, expiry="2099-01-01T00:00:00+00:00")
    body = {
        "status": "SUCCESS",
        "payload": {
            "candles": [
                ["2026-10-13T09:15:00", 100, 101, 99, 100, None, None],
                ["2026-10-13T09:16:00", 100, 102, 100, 101, None, None],
            ],
            "start_time": "2026-10-13 09:15:00",
            "end_time": "2026-10-13 09:16:00",
            "interval_in_minutes": 1,
        },
    }
    raw = json.dumps(body).encode()
    caller = Caller(result=HttpResult(200, body, raw.decode(), raw=raw))
    store = QuarantineStore(tmp_path)
    result = _run(session, caller, store)
    assert result["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert result["candles"] == []
    assert result["trusted_dataset_created"] is False
    assert result["forecast_ready"] is False
    assert result["real_market_data_verified"] is False
    assert result["network_calls"] == 1
    assert result["retry"] is False
    assert result["token_refreshed"] is False
    assert caller.calls == [("GET", "https://api.groww.in/v1/historical/candles")]
    assert "candle_interval=1minute" in caller.urls[0]
    assert "groww_symbol=NSE-NIFTY" in caller.urls[0]
    saved = store.read(result["quarantine"][0]["quarantine_id"])
    assert saved["candle_interval"] == "1minute"
    assert saved["interval"] == "1minute"
    assert saved["label"] == "UNVERIFIED_PROVIDER"
    assert saved["raw_body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert saved["checksum"] == result["quarantine"][0]["checksum"]
    assert ACCESS not in json.dumps(saved)
    assert "raw_candles" not in result


def test_existing_quarantine_records_remain_unchanged(session, tmp_path):
    root = REPO_ROOT / "var" / "history" / "quarantine"
    before = {name: (root / name).read_bytes() for name in QUARANTINE_HASHES}
    row = _prepare(session, enabled=False, expiry="2026-10-15T06:00:00")
    _run(session, Caller(), QuarantineStore(tmp_path))
    assert row.enabled is False
    for name, digest in QUARANTINE_HASHES.items():
        current = (root / name).read_bytes()
        assert current == before[name]
        assert hashlib.sha256(current).hexdigest() == digest
    assert list(tmp_path.glob("*.json")) == []


