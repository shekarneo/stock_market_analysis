"""Register M3 and M4 artifacts and move immutable versions through research states.

Registration copies the fitted configuration. It does not rewrite the artifact
and it does not approve the model.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path

from app.features.pipeline import content_hash
from app.forecasting.store import ExperimentStore, WalkForwardStore
from app.instruments import TRADABLE_UNDERLYINGS, underlying_list_text
from app.market.schemas import IST
from app.registry.schema import (
    ALLOWED_TRANSITIONS,
    EXPERIMENT_KEYS,
    FAMILY_TO_KEY,
    FEATURE_SET,
    HORIZON,
    INSTRUMENTS,
    LIMITATIONS,
    METRIC_NAMES,
    MODEL_NAMES,
    NOT_IMPLEMENTED_FAMILIES,
    SELECTABLE,
    TARGET_ID,
    TARGET_VERSION,
)
from app.registry.store import RegistryError, RegistryStore

_HEX_ID = re.compile(r"^[a-f0-9]{64}$")
_UNSAFE_KEYS = {"path", "output_path", "artifact_path", "file", "password", "secret", "token", "api_key", "authorization"}
_CLAIM_FLAGS = {
    "forecast_ready",
    "paper_approved",
    "live_approved",
    "approved_for_paper",
    "approved_for_live",
    "real_market_data_verified",
    "production_approved",
    "performance_claim_allowed",
}


def apply(store: RegistryStore, mutator, *, idempotency_key: str | None, body: dict):
    body_hash = content_hash(body)

    def wrapped(document: dict):
        revision = document["revision"]
        if idempotency_key:
            prior = document["idempotency"].get(idempotency_key)
            if prior is not None:
                if prior["body_hash"] != body_hash:
                    raise RegistryError("IDEMPOTENCY_CONFLICT", "This idempotency key was used for a different request.")
                return None, prior["result"]
        updated, result = mutator(document)
        if idempotency_key:
            target = document if updated is None else updated
            target["idempotency"][idempotency_key] = {"body_hash": body_hash, "result": result}
            target["revision"] = revision + 1
            return target, result
        if updated is None:
            return None, result
        updated["revision"] = revision + 1
        return updated, result

    return store.update(wrapped)


def register_definition(
    document: dict,
    *,
    family: str,
    instrument: str,
    horizon: str,
    feature_schema_version: str,
    target_version: str,
    actor: str,
    recorded_at: str | None,
    expected_revision: int | None,
) -> tuple[dict | None, dict]:
    _expect(document, expected_revision)
    key = _resolve_family(family)
    _scope(instrument, horizon, feature_schema_version, target_version)
    identity = {
        "kind": "definition",
        "experiment_key": key,
        "instrument": instrument,
        "horizon": horizon,
        "feature_schema_version": feature_schema_version,
        "target_version": target_version,
    }
    version_key = content_hash(identity)
    existing = _find_key(document, version_key)
    if existing is not None:
        return None, {"ok": True, "duplicate": True, "version": _public_version(existing), "forecast_ready": False}
    spec = EXPERIMENT_KEYS[key]
    row = _blank_version(
        experiment_key=key,
        instrument=instrument,
        horizon=horizon,
        version_key=version_key,
        status="REGISTERED",
        actor=actor,
        at=_stamp(recorded_at),
        reason="Registered without a fitted artifact. This is not training and not approval.",
    )
    row["model_version"] = spec["model_version"]
    row["entry_point"] = spec["entry_point"]
    row["feature_schema_version"] = feature_schema_version
    row["target_version"] = target_version
    _put_version(document, row)
    return document, {"ok": True, "duplicate": False, "version": _public_version(row), "forecast_ready": False}


def register_artifact(
    document: dict,
    artifact: dict,
    *,
    kind: str,
    actor: str,
    expected_revision: int | None,
) -> tuple[dict | None, dict]:
    _expect(document, expected_revision)
    if kind not in {"m3", "m4"}:
        raise RegistryError("INVALID_KIND", "Registration accepts an M3 holdout or an M4 walk-forward artifact.")
    _reject_claims(artifact)
    if kind == "m3":
        record, versions = _from_holdout(artifact, actor)
    else:
        record, versions = _from_walkforward(artifact, actor)
    index = f"{kind}:{record['experiment_id']}"
    if index in document["experiments"]:
        return None, {
            "ok": True,
            "duplicate": True,
            "experiment": _public_experiment(document["experiments"][index]),
            "versions": [_public_version(_must_version(document, item)) for item in document["experiments"][index]["version_ids"]],
            "forecast_ready": False,
        }
    created = []
    version_ids = []
    for row in versions:
        existing = _find_key(document, row["version_key"])
        if existing is None:
            _put_version(document, row)
            created.append(row)
            version_ids.append(row["version_id"])
        else:
            version_ids.append(existing["version_id"])
    record["version_ids"] = version_ids
    document["experiments"][index] = record
    return document, {
        "ok": True,
        "duplicate": False,
        "experiment": _public_experiment(record),
        "versions": [_public_version(row) for row in created],
        "failures": record["failures"],
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def transition(
    document: dict,
    *,
    model_id: str,
    version: str,
    to_status: str,
    reason: str,
    confirm: bool,
    actor: str,
    experiment_ids: list[str],
    recorded_at: str | None,
    acknowledge_not_market_evidence: bool,
    claim_market_performance: bool,
    real_market_data_verified: bool,
    expected_revision: int | None,
) -> tuple[dict | None, dict]:
    _expect(document, expected_revision)
    if not confirm or not reason.strip():
        raise RegistryError("CONFIRMATION_REQUIRED", "A lifecycle change needs confirm=true and a reason.")
    if claim_market_performance or real_market_data_verified:
        raise RegistryError("VERIFICATION_REFUSED", "The registry cannot verify market data or claim performance.")
    if to_status == "APPROVED_FOR_PAPER":
        raise RegistryError("PAPER_APPROVAL_DISABLED", "Paper approval is not implemented.")
    if to_status == "APPROVED_FOR_LIVE":
        raise RegistryError("LIVE_APPROVAL_DISABLED", "Live approval is not implemented.")
    row = _version(document, model_id, version)
    before = copy.deepcopy(row["fitted_state"])
    pair = (row["status"], to_status)
    if pair not in ALLOWED_TRANSITIONS:
        raise RegistryError("INVALID_TRANSITION", f"{row['status']} cannot move to {to_status}.")
    if to_status == "EVALUATED":
        _require_walkforward_evidence(document, row, experiment_ids)
    if to_status == "APPROVED_FOR_RESEARCH":
        _require_research_acknowledgement(row, acknowledge_not_market_evidence)
    at = _stamp(recorded_at) or _evidence_time(document, experiment_ids)
    row["history"].append(
        {
            "from": row["status"],
            "to": to_status,
            "reason": reason.strip(),
            "experiment_ids": list(experiment_ids),
            "actor": actor,
            "at": at,
        }
    )
    row["status"] = to_status
    if to_status == "EVALUATED":
        row["evaluation_report_id"] = experiment_ids[0]
        row["last_evaluated_at"] = at
    if row["fitted_state"] != before:
        raise RegistryError("IMMUTABLE_VERSION", "A transition cannot change the fitted model.")
    row["forecast_ready"] = False
    row["paper_approved"] = False
    row["live_approved"] = False
    row["real_market_data_verified"] = False
    return document, {"ok": True, "version": _public_version(row), "forecast_ready": False}


def select_for_research(
    document: dict,
    *,
    model_id: str,
    version: str,
    instrument: str,
    horizon: str,
    reason: str,
    confirm: bool,
    actor: str,
    recorded_at: str | None,
    expected_revision: int | None,
) -> tuple[dict | None, dict]:
    _expect(document, expected_revision)
    if not confirm or not reason.strip():
        raise RegistryError("CONFIRMATION_REQUIRED", "Research selection needs confirm=true and a reason.")
    row = _version(document, model_id, version)
    if row["instrument"] != instrument or row["horizon"] != horizon:
        raise RegistryError("UNSUPPORTED_SCOPE", "The instrument or horizon is outside this version.")
    if row["status"] not in SELECTABLE:
        raise RegistryError("MODEL_NOT_SELECTABLE", "Only an evaluated or research-approved version can be selected.")
    event = {
        "model_id": model_id,
        "version": version,
        "version_id": row["version_id"],
        "instrument": instrument,
        "horizon": horizon,
        "reason": reason.strip(),
        "actor": actor,
        "at": _stamp(recorded_at),
        "status_at_selection": row["status"],
        "paper_slot": None,
        "live_slot": None,
        "forecast_ready": False,
        "activates_trading": False,
    }
    document["research_selections"].append(event)
    if document.get("paper_slot") is not None or document.get("live_slot") is not None:
        raise RegistryError("APPROVAL_REFUSED", "Research selection cannot fill a trading slot.")
    return document, {
        "ok": True,
        "selection": event,
        "paper_slot": None,
        "live_slot": None,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def list_models(document: dict, *, instrument: str | None, horizon: str | None) -> dict:
    rows = []
    for model in document["models"].values():
        if instrument and model["instrument"] != instrument:
            continue
        if horizon and model["horizon"] != horizon:
            continue
        for version in model["versions"].values():
            rows.append(_public_version(version))
    return {
        "ok": True,
        "count": len(rows),
        "models": rows,
        "paper_slot": None,
        "live_slot": None,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def model_detail(document: dict, model_id: str) -> dict:
    model = document["models"].get(model_id)
    if model is None:
        raise RegistryError("UNKNOWN_MODEL", "That model id is not registered.")
    versions = [_public_version(version, detail=True) for version in model["versions"].values()]
    return {
        "model_id": model_id,
        "family": model["family"],
        "experiment_key": model["experiment_key"],
        "instrument": model["instrument"],
        "horizon": model["horizon"],
        "versions": versions,
        "forecast_ready": False,
        "paper_slot": None,
        "live_slot": None,
    }


def compare_artifacts(items: list[dict]) -> dict:
    if len(items) < 2:
        raise RegistryError("NOT_COMPARABLE", "A comparison needs at least two results.")
    results = [_comparison_row(item) for item in items]
    keys = {_compatibility_key(row) for row in results}
    reasons = []
    if len(keys) > 1:
        protocols = sorted({row["evaluation_version"] for row in results})
        datasets = sorted({row["dataset_checksum"] for row in results})
        if len(protocols) > 1:
            reasons.append("Holdout results and walk-forward results are different protocols and are not ranked together.")
        if len(datasets) > 1:
            reasons.append("The dataset checksums differ, so the scored samples are not the same series.")
        scopes = {(row["instrument"], row["horizon"], row["target_version"], row["feature_set_version"], row["origin"]) for row in results}
        if len(scopes) > 1:
            reasons.append("Instrument, horizon, target, feature set, or origin differs.")
        if not reasons:
            reasons.append("The results do not share one compatibility key.")
    return {
        "ok": True,
        "compatible": not reasons,
        "reasons": reasons,
        "results": results,
        "ranking": None,
        "winner": None,
        "profitability_claim": False,
        "forecast_ready": False,
        "aggregation_note": (
            "Holdout validation, holdout test, walk-forward fold metrics, macro averages, "
            "and pooled test metrics stay in separate fields. They are not one score."
        ),
    }


def saved_experiments(experiment_root: ExperimentStore, walk_root: WalkForwardStore) -> dict:
    return {
        "ok": True,
        "holdout": [_saved_row(experiment_root, "m3", item) for item in _ids(experiment_root.root)],
        "walk_forward": [_saved_row(walk_root, "m4", item) for item in _ids(walk_root.root)],
        "forecast_ready": False,
    }


def read_saved(kind: str, experiment_id: str, experiment_root: ExperimentStore, walk_root: WalkForwardStore) -> dict:
    if _HEX_ID.fullmatch(experiment_id) is None:
        raise RegistryError("INVALID_EXPERIMENT_ID", "Experiment id is not a content hash.")
    if kind == "m3":
        artifact = experiment_root.read(experiment_id)
        record, _versions = _from_holdout(artifact, actor="reader")
    elif kind == "m4":
        artifact = walk_root.read(experiment_id)
        record, _versions = _from_walkforward(artifact, actor="reader")
    else:
        raise RegistryError("INVALID_KIND", "Kind must be m3 or m4.")
    return {"ok": True, "experiment": _public_experiment(record), "forecast_ready": False}


def _from_holdout(artifact: dict, actor: str) -> tuple[dict, list[dict]]:
    _require_checksum(artifact, "experiment_id")
    if artifact.get("evaluation_version") != "m3-holdout-1":
        raise RegistryError("VERSION_MISMATCH", "This is not an m3-holdout-1 artifact.")
    if artifact.get("target_version") != TARGET_VERSION or artifact.get("feature_set_version") != FEATURE_SET:
        raise RegistryError("VERSION_MISMATCH", "The holdout is not binary-1 on ohlc-1.")
    instrument = _instrument(artifact.get("instrument"))
    created_at = artifact.get("created_at")
    outcomes = {}
    failures = {}
    versions = []
    for name in MODEL_NAMES:
        fit = (artifact.get("models") or {}).get(name) or {}
        validation = (artifact.get("validation_metrics") or {}).get(name)
        test = (artifact.get("test_metrics") or {}).get(name)
        outcomes[name] = {
            "ok": bool(fit.get("ok")),
            "failure": None if fit.get("ok") else fit.get("code") or "MISSING_MODEL",
            "model_version": fit.get("model_version"),
            "validation": _slim(validation),
            "test": _slim(test),
            "protocol": "m3-holdout-1",
        }
        if not fit.get("ok"):
            failures[name] = outcomes[name]["failure"]
            continue
        versions.append(
            _trained_version(
                experiment_key=name,
                instrument=instrument,
                fit=fit,
                actor=actor,
                at=created_at,
                dataset_id=artifact.get("training_dataset_id"),
                dataset_checksum=artifact.get("training_dataset_id"),
                origin=artifact.get("origin"),
                source_id=artifact.get("source_id"),
                synthetic=bool(artifact.get("synthetic")),
                documented_sample=artifact.get("origin") == "DOCUMENTED_SAMPLE",
                training_experiment_id=artifact["experiment_id"],
                walkforward_ids=[],
                artifact_kind="m3",
                fitted_state=copy.deepcopy(fit),
                version_identity={"kind": "m3", "experiment_id": artifact["experiment_id"], "family": name},
                reason="Registered from a verified M3 holdout fit. The holdout does not by itself mark the model EVALUATED.",
            )
        )
    record = _experiment_record(
        kind="m3",
        experiment_id=artifact["experiment_id"],
        artifact=artifact,
        instrument=instrument,
        outcomes=outcomes,
        failures=failures,
        folds=[],
        aggregate=None,
        baselines_present=set(MODEL_NAMES).issubset((artifact.get("models") or {})),
        test_not_used_for_selection=artifact.get("test_used_for_selection") is False,
        selected_model=artifact.get("selected_model"),
    )
    return record, versions


def _from_walkforward(artifact: dict, actor: str) -> tuple[dict, list[dict]]:
    _require_checksum(artifact, "walkforward_id")
    if artifact.get("evaluation_version") != "m4-expanding-1":
        raise RegistryError("VERSION_MISMATCH", "This is not an m4-expanding-1 artifact.")
    if artifact.get("target_version") != TARGET_VERSION or artifact.get("feature_set_version") != FEATURE_SET:
        raise RegistryError("VERSION_MISMATCH", "The walk-forward run is not binary-1 on ohlc-1.")
    instrument = _instrument(artifact.get("instrument"))
    folds = artifact.get("folds") or []
    outcomes = {}
    failures = {}
    versions = []
    successful = [fold for fold in folds if fold.get("ok")]
    for name in MODEL_NAMES:
        fold_fits = []
        scored = 0
        validation_rows = []
        test_rows = []
        for fold in folds:
            results = (fold.get("model_results") or {}).get(name)
            fit = (results or {}).get("fit") or {}
            fold_fits.append(
                {
                    "fold_id": fold.get("fold_id"),
                    "fold_ok": bool(fold.get("ok")),
                    "failure": None if results is None else results.get("failure"),
                    "fit": copy.deepcopy(fit) if fit.get("ok") else None,
                    "validation": _slim((results or {}).get("validation")),
                    "test": _slim((results or {}).get("test")),
                }
            )
            if fold.get("ok") and fit.get("ok") and (results or {}).get("failure") is None:
                scored += 1
                validation_rows.append(_slim(results.get("validation")))
                test_rows.append(_slim(results.get("test")))
            elif fold.get("ok"):
                failures.setdefault(name, (results or {}).get("failure") or fit.get("code") or "SCORE_FAILED")
        any_fit = any(item["fit"] is not None for item in fold_fits)
        outcomes[name] = {
            "ok": any_fit,
            "failure": None if any_fit and scored == len(successful) and successful else failures.get(name),
            "scored_on_every_successful_fold": bool(successful) and scored == len(successful),
            "validation_by_fold": validation_rows,
            "test_by_fold": test_rows,
            "protocol": "m4-expanding-1",
        }
        if not any_fit:
            failures.setdefault(name, "NOT_FITTED")
            continue
        versions.append(
            _trained_version(
                experiment_key=name,
                instrument=instrument,
                fit=next(item["fit"] for item in fold_fits if item["fit"] is not None),
                actor=actor,
                at=artifact.get("created_at"),
                dataset_id=artifact.get("training_dataset_id"),
                dataset_checksum=artifact.get("dataset_checksum"),
                origin=artifact.get("origin"),
                source_id=artifact.get("source_id"),
                synthetic=bool(artifact.get("synthetic")),
                documented_sample=bool(artifact.get("documented_sample")),
                training_experiment_id=None,
                walkforward_ids=[artifact["walkforward_id"]],
                artifact_kind="m4",
                fitted_state={"refit_each_fold": True, "folds": fold_fits},
                version_identity={"kind": "m4", "experiment_id": artifact["walkforward_id"], "family": name},
                reason="Registered from a verified walk-forward fit. Each fold refits. Registration is not evaluation approval.",
            )
        )
    test_held = all(fold.get("test_used_for_selection") is False for fold in successful) if successful else False
    baselines = all(set(MODEL_NAMES).issubset((fold.get("model_results") or {})) for fold in successful) if successful else False
    record = _experiment_record(
        kind="m4",
        experiment_id=artifact["walkforward_id"],
        artifact=artifact,
        instrument=instrument,
        outcomes=outcomes,
        failures=failures,
        folds=[_fold_public(fold) for fold in folds],
        aggregate=_aggregate_public(artifact.get("aggregate") or {}),
        baselines_present=baselines,
        test_not_used_for_selection=test_held,
        selected_model=None,
    )
    record["selection_counts"] = artifact.get("selection_counts")
    record["successful_folds"] = artifact.get("successful_folds")
    record["failed_folds"] = artifact.get("failed_folds")
    return record, versions


def _experiment_record(*, kind, experiment_id, artifact, instrument, outcomes, failures, folds, aggregate, baselines_present, test_not_used_for_selection, selected_model) -> dict:
    return {
        "kind": kind,
        "experiment_id": experiment_id,
        "dataset_id": artifact.get("training_dataset_id"),
        "dataset_checksum": artifact.get("dataset_checksum") or artifact.get("training_dataset_id"),
        "origin": artifact.get("origin"),
        "source_id": artifact.get("source_id"),
        "synthetic": bool(artifact.get("synthetic")) or artifact.get("origin") == "SYNTHETIC",
        "documented_sample": artifact.get("origin") == "DOCUMENTED_SAMPLE" or bool(artifact.get("documented_sample")),
        "performance_claim_allowed": False,
        "real_market_data_verified": False,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "evaluation_version": artifact.get("evaluation_version"),
        "target_version": artifact.get("target_version"),
        "target_id": artifact.get("target_id") or TARGET_ID,
        "feature_set_version": artifact.get("feature_set_version"),
        "instrument": instrument,
        "horizon": HORIZON,
        "created_at": artifact.get("created_at"),
        "selected_model": selected_model,
        "model_outcomes": outcomes,
        "failures": failures,
        "incomplete": not outcomes or any(not item.get("ok") for item in outcomes.values()),
        "folds": folds,
        "aggregate": aggregate,
        "baselines_present": baselines_present,
        "test_not_used_for_selection": test_not_used_for_selection,
        "version_ids": [],
    }


def _trained_version(**kwargs) -> dict:
    spec = EXPERIMENT_KEYS[kwargs["experiment_key"]]
    fit = kwargs["fit"]
    row = _blank_version(
        experiment_key=kwargs["experiment_key"],
        instrument=kwargs["instrument"],
        horizon=HORIZON,
        version_key=content_hash(kwargs["version_identity"]),
        status="TRAINED",
        actor=kwargs["actor"],
        at=kwargs["at"],
        reason=kwargs["reason"],
        experiment_ids=[kwargs["training_experiment_id"] or kwargs["walkforward_ids"][0]],
    )
    row.update(
        {
            "model_version": fit.get("model_version") or spec["model_version"],
            "entry_point": spec["entry_point"],
            "feature_schema_version": FEATURE_SET,
            "target_version": TARGET_VERSION,
            "target_id": TARGET_ID,
            "training_dataset_id": kwargs["dataset_id"],
            "training_dataset_checksum": kwargs["dataset_checksum"],
            "training_experiment_id": kwargs["training_experiment_id"],
            "walkforward_experiment_ids": list(kwargs["walkforward_ids"]),
            "trained_at": kwargs["at"],
            "artifact_id": kwargs["training_experiment_id"] or kwargs["walkforward_ids"][0],
            "artifact_kind": kwargs["artifact_kind"],
            "artifact_checksum": kwargs["training_experiment_id"] or kwargs["walkforward_ids"][0],
            "artifact_uri": None,
            "origin": kwargs["origin"],
            "source_id": kwargs["source_id"],
            "synthetic": kwargs["synthetic"],
            "documented_sample": kwargs["documented_sample"],
            "configuration": _configuration(fit, spec["entry_point"]),
            "fitted_state": kwargs["fitted_state"],
            "training_config": _configuration(fit, spec["entry_point"]),
        }
    )
    return row


def _blank_version(*, experiment_key, instrument, horizon, version_key, status, actor, at, reason, experiment_ids=None) -> dict:
    spec = EXPERIMENT_KEYS[experiment_key]
    model_id = f"{experiment_key}:{instrument}:{horizon}"
    return {
        "model_id": model_id,
        "version": None,
        "version_id": None,
        "version_key": version_key,
        "family": spec["family"],
        "experiment_key": experiment_key,
        "name": experiment_key,
        "model_version": None,
        "entry_point": spec["entry_point"],
        "configuration": None,
        "training_config": None,
        "fitted_state": None,
        "feature_schema_version": None,
        "target_version": None,
        "target_id": None,
        "output_schema_version": None,
        "instrument": instrument,
        "horizon": horizon,
        "supported_underlyings": [instrument],
        "supported_horizons": [horizon],
        "training_dataset_id": None,
        "training_dataset_checksum": None,
        "training_experiment_id": None,
        "walkforward_experiment_ids": [],
        "trained_at": None,
        "last_evaluated_at": None,
        "artifact_id": None,
        "artifact_kind": None,
        "artifact_checksum": None,
        "artifact_uri": None,
        "origin": None,
        "source_id": None,
        "synthetic": None,
        "documented_sample": None,
        "performance_claim_allowed": False,
        "status": status,
        "history": [
            {
                "from": None,
                "to": status,
                "reason": reason,
                "experiment_ids": experiment_ids or [],
                "actor": actor,
                "at": at,
            }
        ],
        "created_at": at,
        "evaluation_report_id": None,
        "calibration_report_id": None,
        "limitations": LIMITATIONS,
        "last_successful_inference_at": None,
        "health": "UNKNOWN",
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
    }


def _put_version(document: dict, row: dict) -> None:
    model = document["models"].setdefault(
        row["model_id"],
        {
            "model_id": row["model_id"],
            "family": row["family"],
            "experiment_key": row["experiment_key"],
            "instrument": row["instrument"],
            "horizon": row["horizon"],
            "versions": {},
        },
    )
    number = len(model["versions"]) + 1
    row["version"] = f"v{number}"
    row["version_id"] = f"{row['model_id']}@{row['version']}"
    model["versions"][row["version"]] = row


def _configuration(fit: dict, entry_point: str) -> dict:
    return {
        "entry_point": entry_point,
        "model_version": fit.get("model_version"),
        "threshold": fit.get("threshold", 0.5),
        "threshold_rule": fit.get("threshold_rule") or "Class 1 only when the positive probability is greater than 0.5.",
        "l2": fit.get("l2"),
        "max_iter": fit.get("max_iter"),
        "seed": fit.get("seed", 0),
        "seed_draws_rows": False,
        "positive_probability": fit.get("positive_probability"),
        "hard_class": fit.get("hard_class"),
        "rule": fit.get("rule"),
    }


def _require_walkforward_evidence(document: dict, row: dict, experiment_ids: list[str]) -> None:
    linked = set(row.get("walkforward_experiment_ids") or [])
    if not experiment_ids or any(item not in linked for item in experiment_ids):
        raise RegistryError(
            "EVALUATION_EVIDENCE_INSUFFICIENT",
            "EVALUATED requires the linked m4-expanding-1 id. An M3 holdout is not that evidence.",
        )
    for item in experiment_ids:
        record = document["experiments"].get(f"m4:{item}")
        if record is None or record.get("evaluation_version") != "m4-expanding-1":
            raise RegistryError("EVALUATION_EVIDENCE_INSUFFICIENT", "The cited walk-forward result is not registered.")
        if not record.get("baselines_present") or not record.get("test_not_used_for_selection"):
            raise RegistryError("EVALUATION_EVIDENCE_INSUFFICIENT", "The walk-forward report is missing baselines or used the test for selection.")
        outcome = (record.get("model_outcomes") or {}).get(row["experiment_key"]) or {}
        if not outcome.get("scored_on_every_successful_fold"):
            raise RegistryError("EVALUATION_EVIDENCE_INSUFFICIENT", "This model did not score every successful walk-forward fold.")


def _require_research_acknowledgement(row: dict, acknowledge: bool) -> None:
    synthetic = row.get("origin") in {"SYNTHETIC", "DOCUMENTED_SAMPLE"} or row.get("synthetic") or row.get("documented_sample")
    if synthetic and not acknowledge:
        raise RegistryError(
            "SYNTHETIC_NOT_MARKET_EVIDENCE",
            "Synthetic or documented-sample results are not real-market evidence. Acknowledge that before research approval.",
        )


def _comparison_row(item: dict) -> dict:
    artifact = item["artifact"]
    family = _resolve_family(item["family"])
    kind = item["kind"]
    if kind == "m3":
        _require_checksum(artifact, "experiment_id")
        report_id = artifact["experiment_id"]
        protocol = artifact.get("evaluation_version")
        validation = _slim((artifact.get("validation_metrics") or {}).get(family))
        test = _slim((artifact.get("test_metrics") or {}).get(family))
        folds = None
        macro = None
        pooled = None
        dataset_checksum = artifact.get("training_dataset_id")
    else:
        _require_checksum(artifact, "walkforward_id")
        report_id = artifact["walkforward_id"]
        protocol = artifact.get("evaluation_version")
        validation = None
        test = None
        folds = [_fold_family(fold, family) for fold in artifact.get("folds") or []]
        aggregate = artifact.get("aggregate") or {}
        macro = (aggregate.get("macro") or {}).get(family)
        selected_names = {fold.get("selected_model") for fold in artifact.get("folds") or [] if fold.get("ok")}
        pooled = aggregate.get("pooled_selected_model") if selected_names == {family} else None
        dataset_checksum = artifact.get("dataset_checksum")
    return {
        "kind": kind,
        "experiment_id": report_id,
        "family": EXPERIMENT_KEYS[family]["family"],
        "experiment_key": family,
        "dataset_id": artifact.get("training_dataset_id"),
        "dataset_checksum": dataset_checksum,
        "origin": artifact.get("origin"),
        "target_version": artifact.get("target_version"),
        "feature_set_version": artifact.get("feature_set_version"),
        "instrument": artifact.get("instrument"),
        "horizon": HORIZON if artifact.get("interval", "M15") == "M15" else artifact.get("interval"),
        "evaluation_version": protocol,
        "holdout_validation": validation,
        "holdout_test": test,
        "walkforward_folds": folds,
        "walkforward_macro": macro,
        "walkforward_pooled": _slim(pooled) if isinstance(pooled, dict) and "observations" in pooled else pooled,
        "probabilities_are_calibrated": False,
        "profitability_claim": False,
    }


def _compatibility_key(row: dict) -> tuple:
    return (
        row["dataset_checksum"],
        row["target_version"],
        row["feature_set_version"],
        row["instrument"],
        row["horizon"],
        row["evaluation_version"],
        row["origin"],
    )


def _fold_public(fold: dict) -> dict:
    return {
        "fold_id": fold.get("fold_id"),
        "ok": fold.get("ok"),
        "code": fold.get("code"),
        "selected_model": fold.get("selected_model"),
        "test_used_for_selection": fold.get("test_used_for_selection"),
        "eligible_test_count": fold.get("eligible_test_count"),
        "positive_prevalence": fold.get("positive_prevalence"),
        "train_start": fold.get("train_start"),
        "train_end": fold.get("train_end"),
        "validation_start": fold.get("validation_start"),
        "validation_end": fold.get("validation_end"),
        "test_start": fold.get("test_start"),
        "test_end": fold.get("test_end"),
        "models": {
            name: {
                "failure": ((fold.get("model_results") or {}).get(name) or {}).get("failure"),
                "validation": _slim(((fold.get("model_results") or {}).get(name) or {}).get("validation")),
                "test": _slim(((fold.get("model_results") or {}).get(name) or {}).get("test")),
            }
            for name in MODEL_NAMES
            if name in (fold.get("model_results") or {})
        },
    }


def _fold_family(fold: dict, family: str) -> dict:
    results = (fold.get("model_results") or {}).get(family) or {}
    return {
        "fold_id": fold.get("fold_id"),
        "ok": fold.get("ok"),
        "code": fold.get("code"),
        "failure": results.get("failure"),
        "validation": _slim(results.get("validation")),
        "test": _slim(results.get("test")),
        "selected": fold.get("selected_model") == family,
    }


def _aggregate_public(aggregate: dict) -> dict:
    return {
        "fold_count": aggregate.get("fold_count"),
        "successful_folds": aggregate.get("successful_folds"),
        "failed_folds": aggregate.get("failed_folds"),
        "failed_fold_ids": aggregate.get("failed_fold_ids"),
        "total_scored_test_observations": aggregate.get("total_scored_test_observations"),
        "positive_prevalence_by_fold": aggregate.get("positive_prevalence_by_fold"),
        "macro_selected_model": aggregate.get("macro_selected_model"),
        "pooled_selected_model": _slim(aggregate.get("pooled_selected_model"))
        if isinstance(aggregate.get("pooled_selected_model"), dict)
        else None,
        "aggregation_notes": aggregate.get("aggregation_notes"),
    }


def _slim(report: dict | None) -> dict | None:
    if not isinstance(report, dict):
        return None
    slim = {
        "observations": report.get("observations"),
        "positive_prevalence": report.get("positive_prevalence"),
        "status": report.get("status") or "NOT_EVALUATED",
        "probabilities_are_calibrated": False,
    }
    for name in METRIC_NAMES:
        item = report.get(name) or {}
        slim[name] = {"value": item.get("value") if isinstance(item, dict) else None, "status": item.get("status") if isinstance(item, dict) else "NOT_EVALUATED"}
    return slim


def _public_version(row: dict, *, detail: bool = False) -> dict:
    public = {
        "model_id": row["model_id"],
        "version": row["version"],
        "version_id": row["version_id"],
        "family": row["family"],
        "experiment_key": row["experiment_key"],
        "name": row["name"],
        "model_version": row["model_version"],
        "status": row["status"],
        "instrument": row["instrument"],
        "horizon": row["horizon"],
        "feature_schema_version": row["feature_schema_version"],
        "target_version": row["target_version"],
        "origin": row["origin"],
        "synthetic": row["synthetic"],
        "documented_sample": row["documented_sample"],
        "training_dataset_id": row["training_dataset_id"],
        "training_dataset_checksum": row["training_dataset_checksum"],
        "training_experiment_id": row["training_experiment_id"],
        "walkforward_experiment_ids": row["walkforward_experiment_ids"],
        "artifact_id": row["artifact_id"],
        "artifact_checksum": row["artifact_checksum"],
        "artifact_uri": None,
        "created_at": row["created_at"],
        "trained_at": row["trained_at"],
        "last_evaluated_at": row["last_evaluated_at"],
        "evaluation_report_id": row["evaluation_report_id"],
        "calibration_report_id": row["calibration_report_id"],
        "health": row["health"],
        "output_schema_version": row["output_schema_version"] or "NOT_AVAILABLE",
        "last_successful_inference_at": row["last_successful_inference_at"],
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "performance_claim_allowed": False,
    }
    if detail:
        public["configuration"] = row["configuration"]
        public["fitted_state"] = row["fitted_state"]
        public["history"] = row["history"]
        public["limitations"] = row["limitations"]
        public["entry_point"] = row["entry_point"]
    return public


def _public_experiment(record: dict) -> dict:
    return {
        "kind": record["kind"],
        "protocol": "holdout" if record["kind"] == "m3" else "walk_forward",
        "experiment_id": record["experiment_id"],
        "dataset_id": record["dataset_id"],
        "dataset_checksum": record["dataset_checksum"],
        "origin": record["origin"],
        "synthetic": record["synthetic"],
        "documented_sample": record["documented_sample"],
        "evaluation_version": record["evaluation_version"],
        "target_version": record["target_version"],
        "feature_set_version": record["feature_set_version"],
        "instrument": record["instrument"],
        "horizon": record["horizon"],
        "created_at": record["created_at"],
        "selected_model": record["selected_model"],
        "failures": record["failures"],
        "incomplete": record["incomplete"],
        "model_outcomes": record["model_outcomes"],
        "folds": record["folds"],
        "aggregate": record["aggregate"],
        "version_ids": record["version_ids"],
        "successful_folds": record.get("successful_folds"),
        "failed_folds": record.get("failed_folds"),
        "forecast_ready": False,
        "real_market_data_verified": False,
        "performance_claim_allowed": False,
    }


def _saved_row(store, kind: str, experiment_id: str) -> dict:
    try:
        if kind == "m3":
            artifact = store.read(experiment_id)
            record, _versions = _from_holdout(artifact, actor="reader")
        else:
            artifact = store.read(experiment_id)
            record, _versions = _from_walkforward(artifact, actor="reader")
    except Exception as exc:
        code = getattr(exc, "code", "UNREADABLE")
        return {"ok": False, "kind": kind, "experiment_id": experiment_id, "code": code, "forecast_ready": False}
    public = _public_experiment(record)
    public["ok"] = True
    return public


def _ids(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    found = []
    for path in root.iterdir():
        if path.suffix != ".json" or not path.is_file():
            continue
        if path.resolve().parent != root.resolve():
            continue
        stem = path.name[:-5]
        if _HEX_ID.fullmatch(stem):
            found.append(stem)
    return sorted(found)


def _resolve_family(family: str) -> str:
    if family in NOT_IMPLEMENTED_FAMILIES:
        raise RegistryError("NOT_IMPLEMENTED", f"{family} is not implemented.")
    key = FAMILY_TO_KEY.get(family)
    if key is None:
        raise RegistryError("UNKNOWN_FAMILY", "That model family is not registered.")
    return key


def _scope(instrument: str, horizon: str, feature_schema_version: str, target_version: str) -> None:
    if instrument not in INSTRUMENTS or horizon != HORIZON:
        raise RegistryError("UNSUPPORTED_SCOPE", f"Supported scope is {underlying_list_text(TRADABLE_UNDERLYINGS)} at M15.")
    if feature_schema_version != FEATURE_SET or target_version != TARGET_VERSION:
        raise RegistryError("VERSION_MISMATCH", "The implemented pair is ohlc-1 and binary-1.")


def _instrument(value: str | None) -> str:
    if value not in INSTRUMENTS:
        raise RegistryError("UNSUPPORTED_SCOPE", f"The artifact instrument is outside {underlying_list_text(TRADABLE_UNDERLYINGS).replace(' or ', ' and ')}.")
    return value


def _expect(document: dict, expected: int | None) -> None:
    if expected is not None and expected != document["revision"]:
        raise RegistryError("REVISION_CONFLICT", "The registry changed before this update.")


def _find_key(document: dict, version_key: str) -> dict | None:
    for model in document["models"].values():
        for row in model["versions"].values():
            if row["version_key"] == version_key:
                return row
    return None


def _version(document: dict, model_id: str, version: str) -> dict:
    model = document["models"].get(model_id)
    if model is None:
        raise RegistryError("UNKNOWN_MODEL", "That model id is not registered.")
    row = model["versions"].get(version)
    if row is None:
        raise RegistryError("UNKNOWN_MODEL", "That model version is not registered.")
    return row


def _must_version(document: dict, version_id: str) -> dict:
    model_id, _, version = version_id.partition("@")
    return _version(document, model_id, version)


def _require_checksum(artifact: dict, id_field: str) -> None:
    if not isinstance(artifact, dict):
        raise RegistryError("CHECKSUM_MISMATCH", "The artifact is not an object.")
    body = {key: value for key, value in artifact.items() if key not in {id_field, "checksum"}}
    digest = content_hash(body)
    if artifact.get(id_field) != digest or artifact.get("checksum") != digest:
        raise RegistryError("CHECKSUM_MISMATCH", "The artifact checksum does not match its contents.")
    if not isinstance(artifact.get(id_field), str) or _HEX_ID.fullmatch(artifact[id_field]) is None:
        raise RegistryError("INVALID_EXPERIMENT_ID", "The artifact id is not a content hash.")


def _reject_claims(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _UNSAFE_KEYS:
                raise RegistryError("UNSAFE_FIELD", "Registry input cannot carry a path or a secret.")
            if key in _CLAIM_FLAGS and item is True:
                raise RegistryError("APPROVAL_REFUSED", f"{key} cannot be true on a registered artifact.")
            _reject_claims(item)
    elif isinstance(value, list):
        for item in value:
            _reject_claims(item)


def _stamp(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RegistryError("INVALID_TIMESTAMP", "The timestamp is not ISO-8601.") from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise RegistryError("INVALID_TIMESTAMP", "The timestamp must be timezone-aware.")
    return parsed.astimezone(IST).isoformat()


def _evidence_time(document: dict, experiment_ids: list[str]) -> str | None:
    for item in experiment_ids:
        record = document["experiments"].get(f"m4:{item}") or document["experiments"].get(f"m3:{item}")
        if record and record.get("created_at"):
            return record["created_at"]
    return None
