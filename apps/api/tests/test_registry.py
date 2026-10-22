from __future__ import annotations

from app.features.definitions import FEATURE_SET_VERSION

import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.forecasting.experiment import run_experiment
from app.forecasting.splits import SplitConfig
from app.forecasting.store import ExperimentStore, WalkForwardStore
from app.forecasting.walkforward import WalkForwardConfig, run_walk_forward
from app.market.schemas import DataOrigin
from app.registry.service import apply, compare_artifacts, register_artifact, register_definition, select_for_research, transition
from app.registry.store import RegistryError, RegistryStore
from tests.conftest import login
from tests.test_forecasting import alternating, series

HOLDOUT = SplitConfig(min_train=6, min_validation=2, min_test=3)
SMALL = WalkForwardConfig(
    initial_train_size=6,
    validation_size=3,
    test_size=3,
    step_size=3,
    min_train=4,
    min_validation=2,
    min_test=3,
)


def _holdout(**kwargs):
    result = run_experiment(series(alternating(), **kwargs), config=HOLDOUT)
    assert result["ok"] is True
    return result["artifact"]


def _walk(**kwargs):
    result = run_walk_forward(series(alternating(), **kwargs), config=SMALL)
    assert result["ok"] is True
    return result["artifact"]


def _store(tmp_path):
    return RegistryStore(tmp_path / "registry")


def test_definition_is_registered_not_trained_and_is_immutable(tmp_path):
    store = _store(tmp_path)
    created = apply(
        store,
        lambda document: register_definition(
            document,
            family="base_rate",
            instrument="NIFTY",
            horizon="M15",
            feature_schema_version=FEATURE_SET_VERSION,
            target_version="binary-1",
            actor="operator",
            recorded_at="2026-01-05T15:30:00+05:30",
            expected_revision=0,
        ),
        idempotency_key=None,
        body={"family": "base_rate"},
    )
    version = created["version"]
    assert version["status"] == "REGISTERED"
    assert version["trained_at"] is None
    assert version["training_dataset_id"] is None
    assert version["artifact_uri"] is None
    assert version["forecast_ready"] is False
    again = apply(
        store,
        lambda document: register_definition(
            document,
            family="majority_class",
            instrument="NIFTY",
            horizon="M15",
            feature_schema_version=FEATURE_SET_VERSION,
            target_version="binary-1",
            actor="operator",
            recorded_at="2026-01-05T15:30:00+05:30",
            expected_revision=None,
        ),
        idempotency_key=None,
        body={"family": "majority_class"},
    )
    assert again["duplicate"] is True
    assert again["version"]["version"] == "v1"
    assert store.read()["revision"] == 1


def test_m3_registration_preserves_fit_provenance_and_does_not_approve(tmp_path):
    artifact = _holdout()
    before = json.dumps(artifact, sort_keys=True)
    store = _store(tmp_path)
    result = apply(
        store,
        lambda document: register_artifact(document, artifact, kind="m3", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"experiment_id": artifact["experiment_id"]},
    )
    assert json.dumps(artifact, sort_keys=True) == before
    assert result["forecast_ready"] is False
    assert result["real_market_data_verified"] is False
    document = store.read()
    logistic = document["models"]["logistic_regression:NIFTY:M15"]["versions"]["v1"]
    majority = document["models"]["majority_class:NIFTY:M15"]["versions"]["v1"]
    assert logistic["status"] == "TRAINED"
    assert logistic["fitted_state"]["weights"]
    assert logistic["fitted_state"]["intercept"] is not None
    assert "weights" not in majority["fitted_state"]
    assert majority["fitted_state"]["positive_probability"] is not None
    assert logistic["training_dataset_id"] == artifact["training_dataset_id"]
    assert logistic["artifact_checksum"] == artifact["experiment_id"]
    assert logistic["origin"] == "SYNTHETIC"
    assert logistic["paper_approved"] is False
    assert logistic["live_approved"] is False
    experiment = document["experiments"][f"m3:{artifact['experiment_id']}"]
    assert experiment["model_outcomes"]["logistic_regression"]["validation"]["log_loss"]["value"] is not None
    assert experiment["model_outcomes"]["logistic_regression"]["test"] is not experiment["model_outcomes"]["logistic_regression"]["validation"]
    duplicate = apply(
        store,
        lambda document: register_artifact(document, artifact, kind="m3", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"again": True},
    )
    assert duplicate["duplicate"] is True
    assert len(store.read()["models"]["logistic_regression:NIFTY:M15"]["versions"]) == 1


def test_m4_registration_keeps_fold_metrics_and_failed_models(tmp_path):
    artifact = _walk()
    rising = run_walk_forward(series([1000.0 + index for index in range(25)]), config=SMALL)["artifact"]
    store = _store(tmp_path)
    apply(
        store,
        lambda document: register_artifact(document, artifact, kind="m4", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"id": artifact["walkforward_id"]},
    )
    apply(
        store,
        lambda document: register_artifact(document, rising, kind="m4", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"id": rising["walkforward_id"]},
    )
    document = store.read()
    record = document["experiments"][f"m4:{artifact['walkforward_id']}"]
    assert record["folds"]
    assert record["aggregate"]["macro_selected_model"] is not None
    assert record["aggregate"]["pooled_selected_model"] is not None
    assert record["aggregate"]["macro_selected_model"] is not record["aggregate"]["pooled_selected_model"]
    failed = document["experiments"][f"m4:{rising['walkforward_id']}"]
    assert failed["failures"]["logistic_regression"] == "SINGLE_CLASS"
    assert "logistic_regression:NIFTY:M15" not in {
        model_id for model_id, model in document["models"].items() if rising["walkforward_id"] in json.dumps(model)
    }
    logistic = document["models"]["logistic_regression:NIFTY:M15"]["versions"]["v1"]
    assert logistic["fitted_state"]["refit_each_fold"] is True
    assert logistic["status"] == "TRAINED"
    assert logistic["real_market_data_verified"] is False


def test_tampered_artifact_is_rejected(tmp_path):
    artifact = _holdout()
    artifact["selected_model"] = "tampered"
    store = _store(tmp_path)
    with pytest.raises(RegistryError) as caught:
        apply(
            store,
            lambda document: register_artifact(document, artifact, kind="m3", actor="operator", expected_revision=None),
            idempotency_key=None,
            body={"bad": True},
        )
    assert caught.value.code == "CHECKSUM_MISMATCH"
    assert store.read()["revision"] == 0


def test_lifecycle_requires_walkforward_evidence_and_explicit_research_approval(tmp_path):
    holdout = _holdout()
    walked = _walk()
    store = _store(tmp_path)
    apply(
        store,
        lambda document: register_artifact(document, holdout, kind="m3", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"holdout": holdout["experiment_id"]},
    )
    apply(
        store,
        lambda document: register_artifact(document, walked, kind="m4", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"walk": walked["walkforward_id"]},
    )
    document = store.read()
    selected = walked["folds"][0]["selected_model"]
    assert document["models"][f"{selected}:NIFTY:M15"]["versions"]["v1"]["status"] == "TRAINED"
    with pytest.raises(RegistryError) as holdout_only:
        apply(
            store,
            lambda document: transition(
                document,
                model_id="majority_class:NIFTY:M15",
                version="v1",
                to_status="EVALUATED",
                reason="holdout only",
                confirm=True,
                actor="operator",
                experiment_ids=[holdout["experiment_id"]],
                recorded_at=None,
                acknowledge_not_market_evidence=False,
                claim_market_performance=False,
                real_market_data_verified=False,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"bad": "holdout"},
        )
    assert holdout_only.value.code == "EVALUATION_EVIDENCE_INSUFFICIENT"
    weights = store.read()["models"]["logistic_regression:NIFTY:M15"]["versions"]["v2"]["fitted_state"]
    evaluated = apply(
        store,
        lambda document: transition(
            document,
            model_id="logistic_regression:NIFTY:M15",
            version="v2",
            to_status="EVALUATED",
            reason="walk-forward report cited",
            confirm=True,
            actor="operator",
            experiment_ids=[walked["walkforward_id"]],
            recorded_at="2026-01-05T16:00:00+05:30",
            acknowledge_not_market_evidence=False,
            claim_market_performance=False,
            real_market_data_verified=False,
            expected_revision=None,
        ),
        idempotency_key=None,
        body={"evaluate": walked["walkforward_id"]},
    )
    assert evaluated["version"]["status"] == "EVALUATED"
    assert store.read()["models"]["logistic_regression:NIFTY:M15"]["versions"]["v2"]["fitted_state"] == weights
    with pytest.raises(RegistryError) as synthetic:
        apply(
            store,
            lambda document: transition(
                document,
                model_id="logistic_regression:NIFTY:M15",
                version="v2",
                to_status="APPROVED_FOR_RESEARCH",
                reason="best score",
                confirm=True,
                actor="operator",
                experiment_ids=[walked["walkforward_id"]],
                recorded_at=None,
                acknowledge_not_market_evidence=False,
                claim_market_performance=False,
                real_market_data_verified=False,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"approve": False},
        )
    assert synthetic.value.code == "SYNTHETIC_NOT_MARKET_EVIDENCE"
    with pytest.raises(RegistryError) as claim:
        apply(
            store,
            lambda document: transition(
                document,
                model_id="logistic_regression:NIFTY:M15",
                version="v2",
                to_status="APPROVED_FOR_RESEARCH",
                reason="claim",
                confirm=True,
                actor="operator",
                experiment_ids=[walked["walkforward_id"]],
                recorded_at=None,
                acknowledge_not_market_evidence=True,
                claim_market_performance=True,
                real_market_data_verified=False,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"claim": True},
        )
    assert claim.value.code == "VERIFICATION_REFUSED"
    approved = apply(
        store,
        lambda document: transition(
            document,
            model_id="logistic_regression:NIFTY:M15",
            version="v2",
            to_status="APPROVED_FOR_RESEARCH",
            reason="operator reviewed the walk-forward report",
            confirm=True,
            actor="operator",
            experiment_ids=[walked["walkforward_id"]],
            recorded_at="2026-01-05T16:05:00+05:30",
            acknowledge_not_market_evidence=True,
            claim_market_performance=False,
            real_market_data_verified=False,
            expected_revision=None,
        ),
        idempotency_key=None,
        body={"approve": True},
    )
    assert approved["version"]["status"] == "APPROVED_FOR_RESEARCH"
    assert approved["version"]["forecast_ready"] is False
    assert approved["version"]["paper_approved"] is False
    assert approved["version"]["live_approved"] is False
    assert approved["version"]["real_market_data_verified"] is False
    with pytest.raises(RegistryError) as paper:
        apply(
            store,
            lambda document: transition(
                document,
                model_id="logistic_regression:NIFTY:M15",
                version="v2",
                to_status="APPROVED_FOR_PAPER",
                reason="no",
                confirm=True,
                actor="operator",
                experiment_ids=[],
                recorded_at=None,
                acknowledge_not_market_evidence=True,
                claim_market_performance=False,
                real_market_data_verified=False,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"paper": True},
        )
    assert paper.value.code == "PAPER_APPROVAL_DISABLED"


def test_research_selection_does_not_touch_trading_slots(tmp_path):
    walked = _walk()
    store = _store(tmp_path)
    apply(
        store,
        lambda document: register_artifact(document, walked, kind="m4", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"walk": walked["walkforward_id"]},
    )
    with pytest.raises(RegistryError) as too_early:
        apply(
            store,
            lambda document: select_for_research(
                document,
                model_id="majority_class:NIFTY:M15",
                version="v1",
                instrument="NIFTY",
                horizon="M15",
                reason="too early",
                confirm=True,
                actor="operator",
                recorded_at=None,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"early": True},
        )
    assert too_early.value.code == "MODEL_NOT_SELECTABLE"
    apply(
        store,
        lambda document: transition(
            document,
            model_id="majority_class:NIFTY:M15",
            version="v1",
            to_status="EVALUATED",
            reason="evidence",
            confirm=True,
            actor="operator",
            experiment_ids=[walked["walkforward_id"]],
            recorded_at=None,
            acknowledge_not_market_evidence=False,
            claim_market_performance=False,
            real_market_data_verified=False,
            expected_revision=None,
        ),
        idempotency_key=None,
        body={"evaluate": True},
    )
    selected = apply(
        store,
        lambda document: select_for_research(
            document,
            model_id="majority_class:NIFTY:M15",
            version="v1",
            instrument="NIFTY",
            horizon="M15",
            reason="inspect this baseline",
            confirm=True,
            actor="operator",
            recorded_at="2026-01-05T16:10:00+05:30",
            expected_revision=None,
        ),
        idempotency_key=None,
        body={"select": True},
    )
    document = store.read()
    assert selected["paper_slot"] is None
    assert selected["live_slot"] is None
    assert document["paper_slot"] is None
    assert document["live_slot"] is None
    assert document["research_selections"][-1]["activates_trading"] is False


def test_incompatible_protocols_are_not_ranked():
    holdout = _holdout()
    walked = _walk()
    compared = compare_artifacts(
        [
            {"kind": "m3", "artifact": holdout, "family": "logistic_regression"},
            {"kind": "m4", "artifact": walked, "family": "logistic_regression"},
        ]
    )
    assert compared["compatible"] is False
    assert compared["ranking"] is None
    assert compared["winner"] is None
    assert compared["profitability_claim"] is False
    assert any("walk-forward" in reason for reason in compared["reasons"])
    holdout_row = next(row for row in compared["results"] if row["kind"] == "m3")
    walk_row = next(row for row in compared["results"] if row["kind"] == "m4")
    assert holdout_row["holdout_validation"] is not None
    assert holdout_row["holdout_test"] is not None
    assert walk_row["walkforward_folds"]
    assert "mean" in walk_row["walkforward_macro"]["log_loss"]


def test_undefined_metric_stays_null():
    artifact = run_experiment(series([1000.0 + index for index in range(25)]), config=HOLDOUT)["artifact"]
    compared = compare_artifacts(
        [
            {"kind": "m3", "artifact": artifact, "family": "majority_class"},
            {"kind": "m3", "artifact": artifact, "family": "last_return_sign"},
        ]
    )
    assert compared["compatible"] is True
    for row in compared["results"]:
        assert row["holdout_test"]["balanced_accuracy"]["value"] is None
        assert row["holdout_test"]["balanced_accuracy"]["value"] != 0


def test_revision_conflict_and_atomic_failure(tmp_path):
    store = _store(tmp_path)
    apply(
        store,
        lambda document: register_definition(
            document,
            family="logistic_regression",
            instrument="SENSEX",
            horizon="M15",
            feature_schema_version=FEATURE_SET_VERSION,
            target_version="binary-1",
            actor="operator",
            recorded_at=None,
            expected_revision=0,
        ),
        idempotency_key=None,
        body={"one": True},
    )
    with pytest.raises(RegistryError) as stale:
        apply(
            store,
            lambda document: register_definition(
                document,
                family="logistic_regression",
                instrument="BANKNIFTY",
                horizon="M15",
                feature_schema_version=FEATURE_SET_VERSION,
                target_version="binary-1",
                actor="operator",
                recorded_at=None,
                expected_revision=0,
            ),
            idempotency_key=None,
            body={"two": True},
        )
    assert stale.value.code == "REVISION_CONFLICT"
    assert "BANKNIFTY" not in store.read()["models"]

    def explode(document):
        document["models"]["broken"] = {"versions": {}}
        raise RegistryError("NOPE", "stop before write")

    with pytest.raises(RegistryError):
        store.update(explode)
    assert "broken" not in store.read()["models"]
    document = store.read()
    document["forecast_ready"] = True
    body = {key: value for key, value in document.items() if key != "registry_checksum"}
    frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":")))
    from app.features.pipeline import content_hash

    frozen["registry_checksum"] = content_hash(frozen)
    (tmp_path / "registry" / "registry.json").write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(RegistryError) as refused:
        store.read()
    assert refused.value.code == "APPROVAL_REFUSED"


def test_concurrent_registrations_do_not_drop_a_write(tmp_path):
    store = _store(tmp_path)
    barrier = threading.Barrier(2)

    def register(instrument: str):
        barrier.wait()
        apply(
            store,
            lambda document: register_definition(
                document,
                family="majority_class",
                instrument=instrument,
                horizon="M15",
                feature_schema_version=FEATURE_SET_VERSION,
                target_version="binary-1",
                actor="operator",
                recorded_at=None,
                expected_revision=None,
            ),
            idempotency_key=None,
            body={"instrument": instrument},
        )

    threads = [threading.Thread(target=register, args=(name,)) for name in ("NIFTY", "SENSEX")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    document = store.read()
    assert "majority_class:NIFTY:M15" in document["models"]
    assert "majority_class:SENSEX:M15" in document["models"]
    assert document["revision"] == 2


def test_provider_origin_remains_unverified(tmp_path):
    artifact = _holdout(origin=DataOrigin.PROVIDER, source_id="provider-unverified")
    store = _store(tmp_path)
    result = apply(
        store,
        lambda document: register_artifact(document, artifact, kind="m3", actor="operator", expected_revision=None),
        idempotency_key=None,
        body={"provider": True},
    )
    assert result["real_market_data_verified"] is False
    version = store.read()["models"]["majority_class:NIFTY:M15"]["versions"]["v1"]
    assert version["origin"] == "PROVIDER"
    assert version["real_market_data_verified"] is False
    assert version["performance_claim_allowed"] is False


def test_registry_api_auth_registration_and_trading_refusal(client: TestClient, tmp_path, monkeypatch):
    registry = RegistryStore(tmp_path / "registry")
    experiments = ExperimentStore(tmp_path / "experiments")
    walks = WalkForwardStore(tmp_path / "walks")
    monkeypatch.setattr("app.registry.routes.registry_store", lambda: registry)
    monkeypatch.setattr("app.registry.routes.experiment_store", lambda: experiments)
    monkeypatch.setattr("app.registry.routes.walkforward_store", lambda: walks)
    denied = client.get("/api/models")
    assert denied.status_code == 401
    token = login(client)
    assert client.post("/api/models", json={"family": "majority_class", "instrument": "NIFTY", "horizon": "M15"}).status_code == 403
    headers = {"x-csrf-token": token}
    extra = client.post(
        "/api/models",
        headers=headers,
        json={"family": "majority_class", "instrument": "NIFTY", "horizon": "M15", "path": "/tmp/model.json"},
    )
    assert extra.status_code == 422
    unknown = client.post(
        "/api/models",
        headers=headers,
        json={"family": "lightgbm", "instrument": "NIFTY", "horizon": "M15"},
    )
    assert unknown.status_code == 501
    missing = client.get("/api/models/missing:NIFTY:M15")
    assert missing.status_code == 404
    assert missing.json()["code"] == "UNKNOWN_MODEL"
    holdout = _holdout()
    experiments.write(holdout)
    tampered = json.loads(json.dumps(holdout))
    tampered["selected_model"] = "tampered"
    (tmp_path / "experiments" / f"{holdout['experiment_id']}.json").write_text(json.dumps(tampered), encoding="utf-8")
    bad = client.post(
        "/api/models/registrations",
        headers=headers,
        json={"kind": "m3", "experiment_id": holdout["experiment_id"]},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "CHECKSUM_MISMATCH"
    experiments.write(holdout)
    first = client.post(
        "/api/models/registrations",
        headers={**headers, "idempotency-key": "register-1"},
        json={"kind": "m3", "experiment_id": holdout["experiment_id"]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["forecast_ready"] is False
    replay = client.post(
        "/api/models/registrations",
        headers={**headers, "idempotency-key": "register-1"},
        json={"kind": "m3", "experiment_id": holdout["experiment_id"]},
    )
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is False
    conflict = client.post(
        "/api/models/registrations",
        headers={**headers, "idempotency-key": "register-1"},
        json={"kind": "m3", "experiment_id": holdout["experiment_id"], "expected_revision": 99},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    listed = client.get("/api/models")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1
    assert listed.json()["paper_slot"] is None
    paper = client.post("/api/models/paper-activation", headers=headers, json={"model_id": "majority_class:NIFTY:M15"})
    assert paper.status_code == 403
    assert paper.json()["code"] == "MODEL_NOT_APPROVED"
    evaluate = client.post("/api/models/majority_class:NIFTY:M15/versions/v1/evaluate", headers=headers)
    assert evaluate.status_code == 501
    live = client.post("/api/models/live-activation", headers=headers, json={})
    assert live.status_code == 405
    activations = client.get("/api/models/activations")
    assert activations.json()["paper_slot"] is None
    assert activations.json()["live_slot"] is None
    forecasts = client.get("/api/forecasts")
    assert forecasts.json()["forecasts"] == []
    assert forecasts.json()["forecast_ready"] is False
    saved = client.get("/api/experiments")
    assert saved.json()["holdout"][0]["protocol"] == "holdout"
    scope = client.post(
        "/api/models",
        headers=headers,
        json={"family": "majority_class", "instrument": "NIFTY", "horizon": "H1"},
    )
    assert scope.status_code == 422
    assert scope.json()["code"] == "UNSUPPORTED_SCOPE"
