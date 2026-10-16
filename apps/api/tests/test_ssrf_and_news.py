from __future__ import annotations

import socket

import pytest

from app.config.schemas import DataSource
from app.errors import ConnectorNotImplemented, SourceDisabled, SsrfError
from app.news.fetch import fetch_news_source
from app.security.ssrf import assert_public_http_url
from tests.conftest import login


def _public_resolver(host, port, type=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _private_resolver(host, port, type=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0))]


def test_private_and_link_local_urls_are_refused():
    for url in (
        "http://127.0.0.1/feed",
        "http://10.1.1.1/feed",
        "http://169.254.169.254/latest",
        "http://[::1]/feed",
        "http://user:pass@example.com/feed",
        "file:///etc/passwd",
    ):
        with pytest.raises(SsrfError):
            assert_public_http_url(url, resolver=_public_resolver)


def test_private_dns_answer_is_refused():
    with pytest.raises(SsrfError):
        assert_public_http_url("https://news.example/rss", resolver=_private_resolver)


def test_redirect_target_is_rechecked():
    with pytest.raises(SsrfError):
        assert_public_http_url("http://127.0.0.1/after-redirect", resolver=_public_resolver)


def test_disabled_news_source_is_not_fetched():
    source = DataSource(
        id="desk",
        name="Desk",
        enabled=False,
        kind="news",
        connector="rss",
        endpoint="https://news.example/rss",
        poll_seconds=300,
        timeout_seconds=5,
        max_items=20,
        tier="SECONDARY",
    )
    called = {"value": False}

    def reader(_source):
        called["value"] = True
        raise AssertionError("disabled source was fetched")

    with pytest.raises(SourceDisabled):
        fetch_news_source(source, reader)
    assert called["value"] is False


def test_private_url_does_not_call_reader():
    source = DataSource(
        id="local",
        name="Local",
        enabled=True,
        kind="news",
        connector="rss",
        endpoint="http://127.0.0.1/rss",
        poll_seconds=300,
        timeout_seconds=5,
        max_items=20,
        tier="CONTEXT",
    )
    called = {"value": False}

    def reader(_source):
        called["value"] = True

    with pytest.raises(SsrfError):
        fetch_news_source(source, reader)
    assert called["value"] is False


def test_enabled_source_does_not_invent_articles():
    source = DataSource(
        id="fixture_news",
        name="Fixture",
        enabled=True,
        kind="news",
        connector="fixture",
        endpoint="fixtures/none",
        poll_seconds=300,
        timeout_seconds=5,
        max_items=20,
        tier="CONTEXT",
    )

    def reader(_source):
        raise ConnectorNotImplemented()

    with pytest.raises(ConnectorNotImplemented):
        fetch_news_source(source, reader)


def test_api_refuses_private_source_and_skips_disabled(client):
    token = login(client)
    private = client.post(
        "/api/config/sources",
        json={
            "id": "blocked",
            "name": "Blocked",
            "enabled": True,
            "kind": "news",
            "connector": "rss",
            "endpoint": "http://127.0.0.1/rss",
            "poll_seconds": 300,
            "timeout_seconds": 5,
            "max_items": 20,
            "tier": "CONTEXT",
        },
        headers={"x-csrf-token": token},
    )
    assert private.status_code == 400
    assert private.json()["code"] == "SSRF_REFUSED"
    created = client.post(
        "/api/config/sources",
        json={
            "id": "desk",
            "name": "Desk",
            "enabled": False,
            "kind": "news",
            "connector": "fixture",
            "endpoint": "fixtures/none",
            "poll_seconds": 300,
            "timeout_seconds": 5,
            "max_items": 20,
            "tier": "SECONDARY",
        },
        headers={"x-csrf-token": token},
    )
    assert created.status_code == 200, created.text
    tested = client.post("/api/config/sources/desk/test", headers={"x-csrf-token": token})
    assert tested.status_code == 409
    assert tested.json()["code"] == "SOURCE_DISABLED"
