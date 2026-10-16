"""Offline Groww quote and LTP reads. These tests do not call Groww."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.domain.tables import IntegrationCredential, PaperAccountEvent, RiskEvent, RiskSession
from app.execution.orders import live_order_calls
from app.execution.paper import PAPER_TRADING_ACTIVE
from app.integrations.crypto import encrypt_secrets
from app.integrations.http import GROWW_LTP_URL, GROWW_QUOTE_URL, HttpResult, UrlRejected, assert_allowed
from app.integrations.service import save_groww
from app.market.live_quotes import run_live_read
from app.market.timestamp_contract import contract
import pytest

from app.db import get_session_factory
from app.settings import get_settings
from tests.conftest import login
from tests.test_integrations import API_KEY, API_SECRET

@pytest.fixture
def session(db):
    db_session = get_session_factory()()
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


NOW = datetime(2026, 10, 15, 4, 30, tzinfo=timezone.utc)
EXPIRY = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()


class Caller:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def send(self, method, url, *, headers, json_body, timeout):
        self.urls.append(url)
        assert method == "GET"
        assert "/v1/order/" not in url
        assert "/v1/token/" not in url
        assert "/v1/historical/candles" not in url
        return self.responses.pop(0)


def _quote_body(ohlc):
    return {
        "status": "SUCCESS",
        "payload": {"last_price": 24500.5, "last_trade_time": 1_760_500_800_000, "ohlc": ohlc},
    }


def _ltp_body():
    return {"status": "SUCCESS", "payload": {"BSE_SENSEX": 80123.25}}


def _prepare(session, *, enabled=True, token="test-access-token", expiry=EXPIRY):
    save_groww(session, get_settings(), {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET})
    row = session.get(IntegrationCredential, "groww")
    secrets = {"api_key": API_KEY, "api_secret": API_SECRET, "access_token": token}
    row.ciphertext = encrypt_secrets(get_settings(), secrets)
    row.token_expiry = expiry
    row.enabled = enabled
    session.flush()


def test_allowlist_accepts_only_the_documented_queries():
    assert_allowed("GET", GROWW_QUOTE_URL + "?exchange=NSE&segment=CASH&trading_symbol=NIFTY")
    assert_allowed("GET", GROWW_LTP_URL + "?segment=CASH&exchange_symbols=BSE_SENSEX")
    for url in (
        GROWW_QUOTE_URL + "?exchange=NSE&segment=CASH&trading_symbol=BANKNIFTY",
        GROWW_LTP_URL + "?segment=CASH&exchange_symbols=NSE_NIFTY",
        "https://api.groww.in/v1/order/create",
    ):
        try:
            assert_allowed("GET", url)
        except UrlRejected:
            continue
        raise AssertionError(url)
    facts = contract()
    assert facts["mapping_allowed"] is False
    assert facts["timestamp_timezone"] == "UNVERIFIED"


def test_documented_read_stores_unverified_prices_and_skips_text_ohlc(session, tmp_path):
    _prepare(session)
    caller = Caller([
        HttpResult(200, _quote_body("{open: 1,high: 2,low: 3,close: 4}"), ""),
        HttpResult(200, _ltp_body(), ""),
    ])
    before = len(live_order_calls)
    result = run_live_read(session, get_settings(), caller=caller, retrieved_at=NOW, path=tmp_path / "latest.json")
    assert result["status"] == "READ"
    assert result["network_calls"] == 2
    assert result["token_refreshed"] is False
    assert result["candles_requested"] is False
    assert result["real_market_data_verified"] is False
    nifty, sensex = result["quotes"]
    assert nifty["instrument"] == "NIFTY"
    assert nifty["last_price"] == 24500.5
    assert nifty["ohlc"] is None
    assert nifty["data_class"] == "UNVERIFIED_PROVIDER_DATA"
    assert nifty["event_timestamp"] == datetime.fromtimestamp(1_760_500_800_000 / 1000, tz=timezone.utc).isoformat()
    assert sensex["instrument"] == "SENSEX"
    assert sensex["event_timestamp"] is None
    assert "test-access-token" not in json.dumps(result)
    assert len(live_order_calls) == before
    assert PAPER_TRADING_ACTIVE is False
    assert "historical/candles" not in " ".join(caller.urls)


def test_disabled_or_rejected_credentials_do_not_send(session, tmp_path):
    _prepare(session, enabled=False)
    caller = Caller([])
    disabled = run_live_read(session, get_settings(), caller=caller, retrieved_at=NOW, path=tmp_path / "latest.json")
    assert disabled["status"] == "INTEGRATION_DISABLED"
    assert disabled["network_calls"] == 0
    assert caller.urls == []
    _prepare(session, enabled=True)
    rejected = Caller([HttpResult(401, {"status": "FAILURE"}, "")])
    failed = run_live_read(session, get_settings(), caller=rejected, retrieved_at=NOW, path=tmp_path / "latest.json")
    assert failed["status"] == "AUTHENTICATION_FAILED"
    assert failed["network_calls"] == 1
    assert len(rejected.urls) == 1
    assert not (tmp_path / "latest.json").exists()


def test_stored_quote_enters_analysis_and_stays_no_trade(client, session, tmp_path, monkeypatch):
    _prepare(session)
    session.commit()
    path = tmp_path / "latest.json"
    monkeypatch.setattr("app.market.live_quotes.READ_PATH", path)
    caller = Caller([
        HttpResult(200, _quote_body({"open": 24400, "high": 24600, "low": 24300, "close": 24500}), ""),
        HttpResult(200, _ltp_body(), ""),
    ])
    monkeypatch.setattr("app.market.history_routes.HttpxCaller", lambda: caller)
    assert client.get("/api/market/live-quotes").status_code == 401
    token = login(client)
    denied = client.post("/api/market/live-quotes", json={"confirm": True})
    assert denied.status_code == 403
    signed = client.get("/api/market/live-quotes")
    assert signed.status_code == 200
    assert signed.json()["status"] == "NOT_READ"
    refused = client.post("/api/market/live-quotes", headers={"x-csrf-token": token}, json={})
    assert refused.status_code == 422
    read = client.post("/api/market/live-quotes", headers={"x-csrf-token": token}, json={"confirm": True})
    assert read.status_code == 200
    body = read.json()
    assert body["status"] == "READ"
    assert body["quotes"][0]["ohlc"]["close"] == 24500
    assert body["real_market_data_verified"] is False
    assert "test-access-token" not in json.dumps(body)
    analysis = client.post("/api/market-analysis", headers={"x-csrf-token": token}, json={"instruments": ["NIFTY", "SENSEX", "BANKNIFTY"]})
    report = analysis.json()
    assert report["decision"] == "NO_TRADE"
    assert report["real_market_data_verified"] is False
    assert report["forecast_ready"] is False
    assert report["paper_approved"] is False
    assert report["live_approved"] is False
    markets = report["intelligence"]["markets"]
    assert markets["NIFTY"]["data_class"] == "UNVERIFIED_PROVIDER_DATA"
    assert markets["SENSEX"]["data_class"] == "UNVERIFIED_PROVIDER_DATA"
    assert markets["BANKNIFTY"]["status"] == "MISSING_DATA"
    assert report["intelligence"]["forecast"]["probabilities"] is None
    assert not any(row.get("category") == "DERIVATIVES" and row.get("verification_status") == "VERIFIED" for row in report["evidence"])
    assert session.query(RiskEvent).count() == 0
    assert session.query(RiskSession).count() == 0
    assert session.query(PaperAccountEvent).count() == 0


def test_poll_config_endpoints(client):
    assert client.get("/api/market/poll-config").status_code == 401
    token = login(client)
    res = client.get("/api/market/poll-config")
    assert res.status_code == 200
    cfg = res.json()
    assert "enabled" in cfg
    assert "interval_seconds" in cfg

    updated = client.post(
        "/api/market/poll-config",
        headers={"x-csrf-token": token},
        json={"enabled": True, "interval_seconds": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["interval_seconds"] == 120
    assert updated.json()["enabled"] is True

