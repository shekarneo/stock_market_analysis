from __future__ import annotations

from sqlalchemy import select

from app.account import hash_password, verify_password
from app.db import get_session_factory
from app.domain.tables import AuditEvent, OperatorAccount
from app.execution.paper import PAPER_TRADING_ACTIVE
from tests.conftest import login


def test_password_hash_round_trip_and_rejects_tampering():
    stored = hash_password("correct horse battery")
    assert "correct horse battery" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("correct horse battery", "plain$1$00$00")


def test_environment_password_signs_in_until_an_account_exists(client):
    status = client.get("/api/account/status").json()
    assert status == {"account_exists": False, "signup_open": True, "storage_ready": True, "login_source": "environment"}
    token = login(client)
    me = client.get("/api/session").json()
    assert me["username"] == "operator"
    assert me["source"] == "environment"
    assert me["stored"] is False
    denied = client.put("/api/account/profile", headers={"x-csrf-token": token}, json={"display_name": "Neo"})
    assert denied.status_code == 409
    assert denied.json()["code"] == "ACCOUNT_REQUIRED"


def test_signup_persists_a_hashed_account_and_profile(client):
    weak = client.post("/api/account/signup", json={"username": "neo", "password": "short"})
    assert weak.status_code == 422
    assert weak.json()["code"] == "WEAK_PASSWORD"
    bad_name = client.post("/api/account/signup", json={"username": "Bad Name!", "password": "longenough1"})
    assert bad_name.status_code == 422
    created = client.post("/api/account/signup", json={"username": "Neo", "password": "longenough1", "display_name": "  Neo  Desk "})
    assert created.status_code == 201, created.text
    assert created.json()["username"] == "neo"
    assert created.json()["display_name"] == "Neo Desk"
    assert client.cookies.get("imm_session")
    again = client.post("/api/account/signup", json={"username": "other", "password": "longenough1"})
    assert again.status_code == 409
    assert client.get("/api/account/status").json()["signup_open"] is False

    session = get_session_factory()()
    try:
        row = session.execute(select(OperatorAccount)).scalar_one()
        assert row.username == "neo"
        assert row.password_hash.startswith("pbkdf2_sha256$")
        assert "longenough1" not in row.password_hash
        assert row.timezone == "Asia/Kolkata"
        actions = {item.action for item in session.execute(select(AuditEvent)).scalars()}
        assert "account.created" in actions
    finally:
        session.close()

    client.post("/api/session/logout")
    assert client.get("/api/session").status_code == 401
    env_now_rejected = client.post("/api/session/login", json={"password": "test-password"})
    assert env_now_rejected.status_code == 401
    wrong_user = client.post("/api/session/login", json={"username": "someone", "password": "longenough1"})
    assert wrong_user.status_code == 401
    signed = client.post("/api/session/login", json={"username": "neo", "password": "longenough1"})
    assert signed.status_code == 200
    assert signed.json()["source"] == "database"
    token = client.cookies.get("imm_csrf")
    me = client.get("/api/session").json()
    assert me["username"] == "neo"
    assert me["stored"] is True
    assert me["last_login_at"] is not None

    updated = client.put("/api/account/profile", headers={"x-csrf-token": token}, json={"display_name": "Neo", "timezone": "Europe/London"})
    assert updated.status_code == 200
    assert updated.json()["timezone"] == "Europe/London"
    bad_zone = client.put("/api/account/profile", headers={"x-csrf-token": token}, json={"timezone": "Mars/Olympus"})
    assert bad_zone.status_code == 422
    no_csrf = client.put("/api/account/profile", json={"display_name": "x"})
    assert no_csrf.status_code == 403
    assert client.get("/api/account/profile").json()["display_name"] == "Neo"

    wrong_current = client.post("/api/account/password", headers={"x-csrf-token": token}, json={"current_password": "nope", "new_password": "anotherlong1"})
    assert wrong_current.status_code == 401
    changed = client.post("/api/account/password", headers={"x-csrf-token": token}, json={"current_password": "longenough1", "new_password": "anotherlong1"})
    assert changed.status_code == 200
    client.post("/api/session/logout")
    assert client.post("/api/session/login", json={"password": "longenough1"}).status_code == 401
    assert client.post("/api/session/login", json={"password": "anotherlong1"}).status_code == 200
    assert PAPER_TRADING_ACTIVE is False
