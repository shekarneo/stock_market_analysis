"""Production training routes reach fitters only after sealed lineage is checked."""

from __future__ import annotations

from pathlib import Path

from app.features.store import DatasetStore
from app.forecasting.store import ExperimentStore, WalkForwardStore
from app.market.history import HistoryStore, store_source_candles
from app.market.schemas import DataOrigin
from app.settings import REPO_ROOT
from tests.conftest import login
from tests.test_history import bars

APP = REPO_ROOT / "apps" / "api" / "app"
ROUTE_FILES = (
    APP / "main.py",
    APP / "market" / "history_routes.py",
    APP / "registry" / "routes.py",
    APP / "analysis" / "routes.py",
    APP / "integrations" / "routes.py",
)
FITTERS = ("fit_majority(", "fit_last_return_sign(", "fit_logistic(")


def _headers(client) -> dict[str, str]:
    token = login(client)
    return {"x-csrf-token": token}


def test_api_routes_do_not_call_numeric_fitters():
    for path in ROUTE_FILES:
        text = path.read_text(encoding="utf-8")
        for name in FITTERS:
            assert name not in text, f"{path.name} calls {name}"


def test_walk_forward_api_does_not_fit_groww_and_keeps_flags_false(client):
    headers = _headers(client)
    groww = client.post("/api/walk-forward", headers=headers, json={"instrument": "NIFTY", "provider": "groww"})
    assert groww.status_code == 501
    body = groww.json()
    assert body["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    assert body["artifact"] is None
    assert "models" not in body
    assert "test_metrics" not in body
    assert body["forecast_ready"] is False
    assert body["paper_approved"] is False
    assert body["live_approved"] is False
    assert body["real_market_data_verified"] is False


def test_history_evaluation_rejects_a_quarantine_id_and_trains_only_a_sealed_synthetic_source(client, tmp_path, monkeypatch):
    headers = _headers(client)
    quarantine_id = "0105c2cfde527068e24b576e089b4dabfccda734fd20167ae28419a3e2e98057"
    missing = client.post(
        f"/api/history/datasets/{quarantine_id}/evaluations",
        headers=headers,
        json={"kind": "m4"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert "test_metrics" not in missing.json()
    assert "models" not in missing.json()

    store = HistoryStore(tmp_path / "history")
    monkeypatch.setattr("app.market.history_routes.history_store", lambda: store)
    monkeypatch.setattr("app.market.history_routes.feature_store", lambda: DatasetStore(tmp_path / "features"))
    monkeypatch.setattr("app.market.history_routes.experiment_store", lambda: ExperimentStore(tmp_path / "experiments"))
    monkeypatch.setattr("app.market.history_routes.walkforward_store", lambda: WalkForwardStore(tmp_path / "walkforward"))

    provider = store_source_candles(bars(25, origin=DataOrigin.PROVIDER), instrument="NIFTY", store=store)
    assert provider["forecast_eligible"] is False
    refused = client.post(
        f"/api/history/datasets/{provider['dataset_id']}/evaluations",
        headers=headers,
        json={"kind": "m3"},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "DATASET_REJECTED"
    assert "models" not in refused.json()

    source = store_source_candles(bars(25), instrument="NIFTY", store=store)
    trained = client.post(
        f"/api/history/datasets/{source['dataset_id']}/evaluations",
        headers=headers,
        json={
            "kind": "m4",
            "initial_train_size": 6,
            "validation_size": 3,
            "test_size": 3,
            "step_size": 3,
            "min_train": 4,
            "min_validation": 2,
            "min_test": 3,
        },
    )
    assert trained.status_code == 200
    payload = trained.json()
    assert payload["ok"] is True
    assert payload["artifact"]["lineage"]["research_declaration"] == "SYNTHETIC"
    assert payload["artifact"]["lineage"]["market_data_verified"] is False
    assert payload["forecast_ready"] is False
    assert payload["paper_approved"] is False
    assert payload["live_approved"] is False
    assert payload["real_market_data_verified"] is False
    assert Path(REPO_ROOT / "var" / "history" / f"{source['dataset_id']}.json").exists() is False
