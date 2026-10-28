from __future__ import annotations

import os
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://imm:imm@localhost:54329/imm_test"
)
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["OPERATOR_PASSWORD"] = "test-password"
os.environ["LIVE_ORDER_SERVER_FLAG"] = "false"
os.environ["WEB_ORIGIN"] = "http://localhost:3000"
os.environ["INTEGRATIONS_SECRET_KEY"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
os.environ["IMM_ENABLE_AGENT_LLM"] = "0"
os.environ["ENABLE_AGENT_LLM"] = "0"

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.db import get_engine, reset_engine
from app.main import app
from app.settings import get_settings


@pytest.fixture
def validated_edge(monkeypatch):
    """For tests of the readiness plumbing: state that research found an edge after costs.

    Without it, Gate 3 reads the real research files, which (correctly) show no edge.
    """
    from app.research import paper_readiness_audit

    monkeypatch.setattr(paper_readiness_audit, "validated_net_edge",
                        lambda: {"supported": True, "sources": {"test_fixture": True}})


@pytest.fixture(autouse=True)
def isolated_forecast_log(tmp_path, monkeypatch):
    """The forecast log is the operator's record of what was shown; tests never write to it."""
    from app.research import forecast_log

    monkeypatch.setattr(forecast_log, "LOG_PATH", tmp_path / "forecast_log.jsonl")
    monkeypatch.setattr(forecast_log, "_logged_keys", None)


@pytest.fixture(scope="session", autouse=True)
def keep_real_quarantine_clean():
    """Some tests write fixture chunks into the real var/history/quarantine. Remove only the
    files created during this test session so the operator's real chunks are never mixed
    with fixtures; files that existed before the session are never touched."""
    from app.settings import REPO_ROOT

    folder = REPO_ROOT / "var" / "history" / "quarantine"
    before = {path.name for path in folder.glob("*")} if folder.is_dir() else set()
    yield
    if folder.is_dir():
        for path in folder.glob("*"):
            if path.name not in before and path.is_file():
                path.unlink()


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    get_settings.cache_clear()
    reset_engine()
    alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(alembic_ini_path))
    config.set_main_option("script_location", str(alembic_ini_path.parent / "alembic"))
    command.upgrade(config, "head")
    yield
    reset_engine()


@pytest.fixture
def db(migrated_database):
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "TRUNCATE audit_events, config_revisions, ops_state, integration_credentials, risk_events, risk_sessions, paper_transitions, paper_account_events, operator_accounts, worker_leases, watchlist_suggestions, raw_response_artifacts, market_candles, candle_conflict_audit, ingestion_runs, dataset_provenance, benchmark_cache RESTART IDENTITY"
            )
        )
    yield


@pytest.fixture
def client(db):
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient) -> str:
    response = client.post("/api/session/login", json={"password": "test-password"})
    assert response.status_code == 200, response.text
    token = client.cookies.get("imm_csrf")
    assert token
    return token
