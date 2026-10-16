from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import pytest

from app.db import get_session_factory
from app.domain.tables import IntegrationCredential
from app.integrations.crypto import decrypt_secrets, encrypt_secrets
from app.integrations.groww import checksum, classify_token_expiry, totp_code
from app.integrations.groww import historical_candles_url
from app.integrations.http import GROWW_MARGIN_URL, GROWW_TOKEN_URL, HttpResult, UrlRejected, assert_allowed
from app.integrations.openai_client import model_url
from app.integrations.service import (
    clear_provider,
    groww_read_token,
    read_status,
    run_groww_test,
    run_openai_test,
    save_groww,
    save_openai,
    set_openai_enabled,
)
from app.settings import get_settings
from tests.conftest import login

API_KEY = "groww-test-api-key"
API_SECRET = "groww-test-api-secret"
ACCESS = "groww-test-access-token"
OPENAI_KEY = "sk-test-openai-key"


class Caller:
    def __init__(self, responses: list[HttpResult] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def send(self, method, url, *, headers, json_body, timeout):
        assert_allowed(method, url)
        self.calls.append((method, url))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


@pytest.fixture
def session(db):
    db_session = get_session_factory()()
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


def test_checksum_matches_the_documented_sha256_concatenation():
    timestamp = "1719830400"
    expected = hashlib.sha256(f"abc{timestamp}".encode("utf-8")).hexdigest()
    assert checksum("abc", timestamp) == expected


def test_totp_matches_the_rfc_sha1_six_digit_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp_code(secret, timestamp=59) == "287082"


def test_order_urls_are_rejected():
    with pytest.raises(UrlRejected):
        assert_allowed("POST", "https://api.groww.in/v1/order/create")
    with pytest.raises(UrlRejected):
        assert_allowed("POST", "https://example.com/v1/token/api/access")
    assert_allowed("GET", GROWW_MARGIN_URL)
    assert_allowed("POST", GROWW_TOKEN_URL)
    assert_allowed("GET", model_url("gpt-4.1-mini"))
    candle_url = historical_candles_url(
        {
            "exchange": "NSE",
            "segment": "CASH",
            "groww_symbol": "NSE-NIFTY",
            "start_time": "2026-10-13 09:15:00",
            "end_time": "2026-10-13 15:30:00",
            "candle_interval": "15minute",
        }
    )
    assert_allowed("GET", candle_url)
    with pytest.raises(UrlRejected):
        assert_allowed("GET", candle_url + "&url=https://evil.example")


def test_read_status_never_returns_saved_secrets(session):
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "label": "desk", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    save_openai(session, get_settings(), {"api_key": OPENAI_KEY, "model": "gpt-4.1-mini", "enabled": False})
    session.commit()
    status = read_status(session)
    rendered = str(status)
    assert API_KEY not in rendered
    assert API_SECRET not in rendered
    assert OPENAI_KEY not in rendered
    assert status["groww"]["configured"] is True
    assert status["groww"]["last_test_ok"] is None
    assert status["groww"]["api_secret_configured"] is True
    assert status["openai"]["api_key_configured"] is True
    assert status["live_trading_enabled"] is False
    assert status["forecast_ready"] is False
    row = session.get(__import__("app.domain.tables", fromlist=["IntegrationCredential"]).IntegrationCredential, "groww")
    assert API_KEY not in row.ciphertext
    assert decrypt_secrets(get_settings(), row.ciphertext)["api_key"] == API_KEY


def test_replace_and_clear_credentials(session):
    save_groww(session, get_settings(), {"method": "access_token", "access_token": ACCESS, "label": "first"})
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET, "label": "second"},
    )
    session.commit()
    status = read_status(session)
    assert status["groww"]["auth_method"] == "api_key_secret"
    assert status["groww"]["label"] == "second"
    assert ACCESS not in str(status)
    clear_provider(session, "groww")
    session.commit()
    assert read_status(session)["groww"]["configured"] is False


def test_missing_secret_is_rejected(session):
    with pytest.raises(Exception) as caught:
        save_groww(session, get_settings(), {"method": "api_key_secret", "api_key": API_KEY})
    assert caught.value.code == "MISSING_CREDENTIAL"


def test_groww_success_uses_margin_and_reuses_an_unexpired_token(session):
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    session.commit()
    caller = Caller(
        [
            HttpResult(200, {"token": ACCESS, "expiry": "2099-01-01T00:00:00+00:00", "isActive": True}, ""),
            HttpResult(200, {"status": "SUCCESS", "payload": {"clear_cash": 1}}, ""),
            HttpResult(200, {"status": "SUCCESS", "payload": {"clear_cash": 1}}, ""),
        ]
    )
    first = run_groww_test(session, get_settings(), caller=caller)
    second = run_groww_test(session, get_settings(), caller=caller)
    session.commit()
    assert first["result"]["ok"] is True
    assert second["result"]["ok"] is True
    assert caller.calls == [("POST", GROWW_TOKEN_URL), ("GET", GROWW_MARGIN_URL), ("GET", GROWW_MARGIN_URL)]
    assert "clear_cash" not in str(first)
    assert ACCESS not in str(first)


def test_pasted_access_token_does_not_call_the_token_endpoint(session):
    save_groww(session, get_settings(), {"method": "access_token", "access_token": ACCESS})
    session.commit()
    caller = Caller([HttpResult(401, {"status": "FAILURE", "error": {"message": "nope"}}, "")])
    result = run_groww_test(session, get_settings(), caller=caller)
    assert result["result"]["code"] == "AUTHENTICATION_FAILED"
    assert caller.calls == [("GET", GROWW_MARGIN_URL)]
    reused = Caller(error=AssertionError("token exchange"))
    assert groww_read_token(session, get_settings(), reused) == ACCESS
    assert reused.calls == []


def test_groww_timeout_rate_limit_and_log_redaction(session, caplog):
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    session.commit()
    timed = Caller(error=TimeoutError("timed out"))
    timeout_result = run_groww_test(session, get_settings(), caller=timed)
    assert timeout_result["result"]["code"] == "TIMEOUT"
    assert timed.calls == [("POST", GROWW_TOKEN_URL)]
    limited = Caller([HttpResult(429, {"status": "FAILURE"}, "")])
    limited_result = run_groww_test(session, get_settings(), caller=limited)
    assert limited_result["result"]["code"] == "RATE_LIMITED"
    assert limited.calls == [("POST", GROWW_TOKEN_URL)]
    echoed = Caller(
        [
            HttpResult(200, {"token": ACCESS, "expiry": "2099-01-01T00:00:00+00:00", "isActive": True}, ""),
            HttpResult(200, {"status": "FAILURE", "error": {"message": f"rejected {API_KEY}"}}, ""),
        ]
    )
    with caplog.at_level(logging.INFO, logger="imm.integrations"):
        echoed_result = run_groww_test(session, get_settings(), caller=echoed)
    assert echoed_result["result"]["ok"] is False
    assert API_KEY not in echoed_result["result"]["message"]
    assert API_KEY not in caplog.text
    assert API_SECRET not in caplog.text


def test_openai_success_failure_quota_and_disabled(session):
    save_openai(session, get_settings(), {"api_key": OPENAI_KEY, "model": "gpt-4.1-mini", "enabled": False})
    session.commit()
    caller = Caller([HttpResult(200, {"id": "gpt-4.1-mini"}, "")])
    disabled = run_openai_test(session, get_settings(), caller=caller)
    assert disabled["result"]["code"] == "INTEGRATION_DISABLED"
    assert caller.calls == []
    set_openai_enabled(session, True)
    session.commit()
    success = run_openai_test(session, get_settings(), caller=Caller([HttpResult(200, {"id": "gpt-4.1-mini"}, "")]))
    assert success["result"]["ok"] is True
    assert success["result"]["message"].startswith("The model record")
    invalid = run_openai_test(
        session,
        get_settings(),
        caller=Caller(
            [
                HttpResult(
                    401,
                    {
                        "error": {
                            "message": f"Incorrect API key provided: {OPENAI_KEY[:8]}*********mple.",
                            "code": "invalid_api_key",
                        }
                    },
                    "",
                )
            ]
        ),
    )
    assert invalid["result"]["code"] == "INVALID_CREDENTIALS"
    assert invalid["result"]["message"] == "OpenAI rejected the API key."
    assert OPENAI_KEY not in invalid["result"]["message"]
    assert "sk-" not in invalid["result"]["message"]
    quota = run_openai_test(
        session,
        get_settings(),
        caller=Caller([HttpResult(429, {"error": {"code": "insufficient_quota", "message": "billing"}}, "")]),
    )
    assert quota["result"]["code"] == "QUOTA_EXCEEDED"
    missing_model = run_openai_test(
        session,
        get_settings(),
        caller=Caller([HttpResult(404, {"error": {"message": "missing"}}, "")]),
    )
    assert missing_model["result"]["code"] == "MODEL_UNAVAILABLE"
    timed = run_openai_test(session, get_settings(), caller=Caller(error=TimeoutError("slow")))
    assert timed["result"]["code"] == "TIMEOUT"


def _derived_token(session, expiry: str):
    save_groww(
        session,
        get_settings(),
        {"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    row = session.get(IntegrationCredential, "groww")
    row.ciphertext = encrypt_secrets(
        get_settings(),
        {"api_key": API_KEY, "api_secret": API_SECRET, "access_token": ACCESS},
    )
    row.token_expiry = expiry
    row.derived_access_token = True
    row.enabled = False
    session.flush()
    return row


def test_offset_less_expiry_is_asia_kolkata_around_0600_and_does_not_refresh():
    from zoneinfo import ZoneInfo

    kolkata = ZoneInfo("Asia/Kolkata")
    expiry = "2026-10-15T06:00:00"
    before = classify_token_expiry(expiry, datetime(2026, 10, 15, 5, 59, 59, tzinfo=kolkata))
    at_reset = classify_token_expiry(expiry, datetime(2026, 10, 15, 6, 0, 0, tzinfo=kolkata))
    after = classify_token_expiry(expiry, datetime(2026, 10, 15, 6, 0, 1, tzinfo=kolkata))
    assert before["status"] == "VALID"
    assert at_reset["status"] == "EXPIRED"
    assert after["status"] == "EXPIRED"
    for item in (before, at_reset, after):
        assert item["reason"] == "ASIA_KOLKATA"
        assert item["refresh"] is False
    assert classify_token_expiry(expiry, datetime(2026, 10, 15, 0, 29, 59, tzinfo=timezone.utc))["status"] == "VALID"
    assert classify_token_expiry(expiry, datetime(2026, 10, 15, 0, 30, tzinfo=timezone.utc))["status"] == "EXPIRED"


def test_token_expiry_classification_keeps_aware_values_and_rejects_malformed_text():
    now = datetime(2026, 10, 14, 14, 8, tzinfo=timezone.utc)
    naive = classify_token_expiry("2026-10-15T06:00:00", now)
    assert naive["status"] == "VALID"
    assert naive["reason"] == "ASIA_KOLKATA"
    assert naive["refresh"] is False
    malformed = classify_token_expiry("tomorrow", now)
    assert malformed["status"] == "UNVERIFIABLE"
    assert malformed["reason"] == "MALFORMED"
    assert malformed["refresh"] is False
    expired = classify_token_expiry("2026-10-14T14:08:00+00:00", now)
    assert expired["status"] == "EXPIRED"
    assert expired["refresh"] is False
    unexpired = classify_token_expiry("2026-10-15T06:00:00+05:30", now)
    assert unexpired["status"] == "VALID"
    assert unexpired["refresh"] is False
    explicit_utc = classify_token_expiry("2026-10-15T06:00:00Z", now)
    assert explicit_utc["status"] == "VALID"


def test_unverifiable_or_expired_expiry_does_not_exchange_a_token(session):
    now_codes = {
        "2000-01-01T06:00:00": "TOKEN_EXPIRED",
        "tomorrow": "EXPIRY_UNVERIFIABLE",
        "2000-01-01T00:00:00+00:00": "TOKEN_EXPIRED",
    }
    for expiry, code in now_codes.items():
        row = _derived_token(session, expiry)
        caller = Caller(error=AssertionError("network"))
        result = run_groww_test(session, get_settings(), caller=caller)
        assert result["result"]["code"] == code
        assert caller.calls == []
        assert row.enabled is False
        assert ACCESS not in str(result)
        assert API_SECRET not in str(result)


def test_integrations_api_masks_secrets_and_requires_csrf(client):
    assert client.get("/api/integrations").status_code == 401
    token = login(client)
    denied = client.put(
        "/api/integrations/groww",
        json={"method": "access_token", "access_token": ACCESS},
    )
    assert denied.status_code == 403
    saved = client.put(
        "/api/integrations/groww",
        headers={"x-csrf-token": token},
        json={"method": "access_token", "access_token": ACCESS, "label": "desk", "url": "https://evil.example"},
    )
    assert saved.status_code == 422
    saved = client.put(
        "/api/integrations/groww",
        headers={"x-csrf-token": token},
        json={"method": "access_token", "access_token": ACCESS, "label": "desk"},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert ACCESS not in saved.text
    assert body["groww"]["configured"] is True
    assert body["groww"]["last_test_ok"] is None
    assert body["forecast_ready"] is False
    assert body["live_trading_enabled"] is False
    listed = client.get("/api/integrations")
    assert ACCESS not in listed.text
    cleared = client.post("/api/integrations/groww/clear", headers={"x-csrf-token": token})
    assert cleared.status_code == 200
    assert cleared.json()["groww"]["configured"] is False


def test_groww_enabled_is_separate_from_connection_and_requires_confirmation(client):
    token = login(client)
    saved = client.put(
        "/api/integrations/groww",
        headers={"x-csrf-token": token},
        json={"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET, "label": "desk"},
    )
    assert saved.status_code == 200
    body = saved.json()["groww"]
    assert body["configured"] is True
    assert body["enabled"] is False
    assert body["last_test_ok"] is None
    assert body["connectivity"]["last_result"] == "not_tested"
    assert body["permissions"]["live_trading"] == "disabled"
    assert body["permissions"]["historical_candles"] in {"not_tested", "quarantined_unverified"}
    assert body["token_status"]["refresh"] is False
    assert API_KEY not in saved.text
    assert API_SECRET not in saved.text
    before = client.get("/api/integrations").json()["groww"]["enabled"]
    loaded = client.get("/api/integrations")
    assert loaded.json()["groww"]["enabled"] is before
    assert loaded.json()["live_trading_enabled"] is False
    denied = client.post(
        "/api/integrations/groww/enabled",
        headers={"x-csrf-token": token},
        json={"enabled": True, "confirm": False},
    )
    assert denied.status_code == 422
    assert denied.json()["code"] == "CONFIRMATION_REQUIRED"
    assert client.get("/api/integrations").json()["groww"]["enabled"] is False
    enabled = client.post(
        "/api/integrations/groww/enabled",
        headers={"x-csrf-token": token},
        json={"enabled": True, "confirm": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["groww"]["enabled"] is True
    assert enabled.json()["live_trading_enabled"] is False
    assert enabled.json()["forecast_ready"] is False


def test_historical_diagnostic_needs_confirmation_and_does_not_enable_or_refresh(client, session, monkeypatch, tmp_path):
    import json

    from app.integrations.http import HttpResult
    from app.market.retrieval import QuarantineStore

    token = login(client)
    saved = client.put(
        "/api/integrations/groww",
        headers={"x-csrf-token": token},
        json={"method": "api_key_secret", "api_key": API_KEY, "api_secret": API_SECRET},
    )
    assert saved.status_code == 200
    caller = Caller()
    monkeypatch.setattr("app.integrations.routes.diagnostic_caller", lambda: caller)
    monkeypatch.setattr("app.integrations.routes.diagnostic_store", lambda: QuarantineStore(tmp_path))
    payload = {
        "exchange": "NSE",
        "segment": "CASH",
        "groww_symbol": "NSE-NIFTY",
        "candle_interval": "1minute",
        "start": "2026-10-13T09:15:00+05:30",
        "end": "2026-10-13T09:45:00+05:30",
        "confirm": False,
    }
    preview = client.post("/api/integrations/groww/historical-diagnostic", headers={"x-csrf-token": token}, json=payload)
    assert preview.status_code == 422
    assert preview.json()["code"] == "CONFIRMATION_REQUIRED"
    assert preview.json()["error_origin"] == "local"
    assert preview.json()["network_calls"] == 0
    assert caller.calls == []
    assert "candle_interval=1minute" in preview.json()["query"]["candle_interval"] or preview.json()["query"]["candle_interval"] == "1minute"
    too_long = dict(payload, end="2026-10-13T10:00:00+05:30", confirm=True)
    rejected = client.post("/api/integrations/groww/historical-diagnostic", headers={"x-csrf-token": token}, json=too_long)
    assert rejected.status_code == 422
    assert rejected.json()["error_origin"] == "local"
    assert caller.calls == []
    blocked = client.post(
        "/api/integrations/groww/historical-diagnostic",
        headers={"x-csrf-token": token},
        json=dict(payload, confirm=True),
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "INTEGRATION_DISABLED"
    assert blocked.json()["network_calls"] == 0
    assert caller.calls == []
    assert client.get("/api/integrations").json()["groww"]["enabled"] is False

    session.expire_all()
    row = session.get(IntegrationCredential, "groww")
    row.ciphertext = encrypt_secrets(
        get_settings(),
        {"api_key": API_KEY, "api_secret": API_SECRET, "access_token": ACCESS},
    )
    row.token_expiry = "2099-01-01T00:00:00+05:30"
    row.derived_access_token = True
    row.enabled = False
    session.commit()
    still_off = client.post(
        "/api/integrations/groww/historical-diagnostic",
        headers={"x-csrf-token": token},
        json=dict(payload, confirm=True),
    )
    assert still_off.status_code == 422
    assert still_off.json()["code"] == "INTEGRATION_DISABLED"
    assert still_off.json()["network_calls"] == 0
    turned_on = client.post(
        "/api/integrations/groww/enabled",
        headers={"x-csrf-token": token},
        json={"enabled": True, "confirm": True},
    )
    assert turned_on.status_code == 200
    assert turned_on.json()["groww"]["enabled"] is True
    assert turned_on.json()["live_trading_enabled"] is False
    raw_body = {
        "status": "SUCCESS",
        "payload": {
            "candles": [["2026-10-13T09:15:00", 100, 101, 99, 100, None, None]],
            "start_time": "2026-10-13 09:15:00",
            "end_time": "2026-10-13 09:15:00",
            "interval_in_minutes": 1,
        },
    }
    raw = json.dumps(raw_body).encode()

    class SuccessCaller:
        def __init__(self):
            self.calls = []

        def send(self, method, url, *, headers, json_body, timeout):
            self.calls.append((method, url.split("?", 1)[0]))
            assert "/v1/order/" not in url
            assert "/v1/token/" not in url
            return HttpResult(200, raw_body, raw.decode(), raw=raw)

    success = SuccessCaller()
    monkeypatch.setattr("app.integrations.routes.diagnostic_caller", lambda: success)
    ran = client.post(
        "/api/integrations/groww/historical-diagnostic",
        headers={"x-csrf-token": token},
        json=dict(payload, confirm=True),
    )
    assert ran.status_code == 200
    reported = ran.json()
    assert reported["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert reported["report"]["http_status"] == 200
    assert reported["report"]["provider_status"] == "SUCCESS"
    assert reported["report"]["candle_count"] == 1
    assert reported["report"]["trusted_dataset_created"] is False
    assert reported["enabled_after"] is True
    assert reported["live_trading_enabled"] is False
    assert reported["token_refreshed"] is False
    assert reported["retry"] is False
    assert success.calls == [("GET", "https://api.groww.in/v1/historical/candles")]
    assert ACCESS not in ran.text
    assert client.get("/api/integrations").json()["groww"]["enabled"] is True

    class DeniedCaller:
        def __init__(self):
            self.calls = []

        def send(self, method, url, *, headers, json_body, timeout):
            self.calls.append(method)
            return HttpResult(401, {"status": "FAILURE"}, "{}", raw=b"{}")

    denied_caller = DeniedCaller()
    monkeypatch.setattr("app.integrations.routes.diagnostic_caller", lambda: denied_caller)
    rejected_auth = client.post(
        "/api/integrations/groww/historical-diagnostic",
        headers={"x-csrf-token": token},
        json=dict(payload, confirm=True),
    )
    assert rejected_auth.status_code == 422
    assert rejected_auth.json()["error_origin"] == "provider"
    assert rejected_auth.json()["message"] == "Authentication rejected by provider."
    assert denied_caller.calls == ["GET"]
    assert client.get("/api/integrations").json()["live_trading_enabled"] is False


def test_openai_model_save_requires_confirmation_and_keeps_the_key(client):
    token = login(client)
    saved = client.put(
        "/api/integrations/openai",
        headers={"x-csrf-token": token},
        json={"api_key": OPENAI_KEY, "model": "gpt-4.1-mini", "label": "openai", "enabled": True},
    )
    assert saved.status_code == 200
    assert OPENAI_KEY not in saved.text
    denied = client.post(
        "/api/integrations/openai/profile",
        headers={"x-csrf-token": token},
        json={"model": "gpt-6-luna", "label": "research", "confirm": False},
    )
    assert denied.status_code == 422
    assert denied.json()["code"] == "CONFIRMATION_REQUIRED"
    assert client.get("/api/integrations").json()["openai"]["model"] == "gpt-4.1-mini"
    updated = client.post(
        "/api/integrations/openai/profile",
        headers={"x-csrf-token": token},
        json={"model": "gpt-6-luna", "label": "research", "confirm": True},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["openai"]["model"] == "gpt-6-luna"
    assert body["openai"]["enabled"] is True
    assert body["openai"]["api_key_configured"] is True
    assert body["live_trading_enabled"] is False
    assert OPENAI_KEY not in updated.text
