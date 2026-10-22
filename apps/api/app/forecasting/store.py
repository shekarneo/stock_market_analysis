"""JSON experiment artifacts. Loading is by content id, never by a caller path."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.features.definitions import FEATURE_SET_VERSION
from app.features.pipeline import content_hash
from app.settings import REPO_ROOT

_ID = re.compile(r"^[a-f0-9]{64}$")


class ExperimentStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_UNSAFE_KEYS = {"path", "output_path", "artifact_path", "file"}


def experiment_store() -> ExperimentStore:
    return ExperimentStore(REPO_ROOT / "var" / "experiments")


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write(self, artifact: dict) -> None:
        if _UNSAFE_KEYS.intersection(artifact):
            raise ExperimentStoreError("UNSAFE_PATH", "An experiment artifact cannot name a file path.")
        experiment_id = artifact.get("experiment_id")
        if not isinstance(experiment_id, str) or _ID.fullmatch(experiment_id) is None:
            raise ExperimentStoreError("INVALID_EXPERIMENT_ID", "Experiment id is not a content hash.")
        self._verify(artifact)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(experiment_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def read(self, experiment_id: str) -> dict:
        if _ID.fullmatch(experiment_id) is None:
            raise ExperimentStoreError("INVALID_EXPERIMENT_ID", "Experiment id is not a content hash.")
        path = self._path(experiment_id)
        if not path.is_file():
            raise ExperimentStoreError("NOT_FOUND", "Experiment artifact was not found.")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self._verify(artifact)
        if artifact.get("experiment_id") != experiment_id:
            raise ExperimentStoreError("CHECKSUM_MISMATCH", "Artifact id does not match the requested id.")
        return artifact

    def _path(self, experiment_id: str) -> Path:
        path = (self.root / f"{experiment_id}.json").resolve()
        if path.parent != self.root:
            raise ExperimentStoreError("UNSAFE_PATH", "The experiment file would leave the store root.")
        return path

    def _verify(self, artifact: dict) -> None:
        body = {key: value for key, value in artifact.items() if key not in {"experiment_id", "checksum"}}
        digest = content_hash(body)
        if artifact.get("checksum") != digest or artifact.get("experiment_id") != digest:
            raise ExperimentStoreError("CHECKSUM_MISMATCH", "Experiment checksum does not match its contents.")
        if artifact.get("forecast_ready") is not False:
            raise ExperimentStoreError("APPROVAL_REFUSED", "An experiment cannot claim forecast readiness.")
        if artifact.get("target_version") != "binary-1" or artifact.get("feature_set_version") != FEATURE_SET_VERSION:
            raise ExperimentStoreError("VERSION_MISMATCH", "Artifact versions are not the implemented pair.")


class WalkForwardStore(ExperimentStore):
    """Same path rules as the M3 store. The id field is walkforward_id."""

    def write(self, artifact: dict) -> None:
        if _UNSAFE_KEYS.intersection(artifact):
            raise ExperimentStoreError("UNSAFE_PATH", "A walk-forward artifact cannot name a file path.")
        walkforward_id = artifact.get("walkforward_id")
        if not isinstance(walkforward_id, str) or _ID.fullmatch(walkforward_id) is None:
            raise ExperimentStoreError("INVALID_EXPERIMENT_ID", "Walk-forward id is not a content hash.")
        self._verify_walk(artifact)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(walkforward_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        temporary.replace(path)

    def read(self, walkforward_id: str) -> dict:
        if _ID.fullmatch(walkforward_id) is None:
            raise ExperimentStoreError("INVALID_EXPERIMENT_ID", "Walk-forward id is not a content hash.")
        path = self._path(walkforward_id)
        if not path.is_file():
            raise ExperimentStoreError("NOT_FOUND", "Walk-forward artifact was not found.")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self._verify_walk(artifact)
        if artifact.get("walkforward_id") != walkforward_id:
            raise ExperimentStoreError("CHECKSUM_MISMATCH", "Artifact id does not match the requested id.")
        return artifact

    def _verify_walk(self, artifact: dict) -> None:
        body = {key: value for key, value in artifact.items() if key not in {"walkforward_id", "checksum"}}
        digest = content_hash(body)
        if artifact.get("checksum") != digest or artifact.get("walkforward_id") != digest:
            raise ExperimentStoreError("CHECKSUM_MISMATCH", "Walk-forward checksum does not match its contents.")
        if artifact.get("forecast_ready") is not False or artifact.get("paper_approved") is not False:
            raise ExperimentStoreError("APPROVAL_REFUSED", "A walk-forward run cannot approve a model.")
        if artifact.get("live_approved") is not False or artifact.get("real_market_data_verified") is not False:
            raise ExperimentStoreError("APPROVAL_REFUSED", "A walk-forward run cannot claim verified market data.")
        if artifact.get("target_version") != "binary-1" or artifact.get("feature_set_version") != FEATURE_SET_VERSION:
            raise ExperimentStoreError("VERSION_MISMATCH", "Artifact versions are not the implemented pair.")
        if artifact.get("evaluation_version") != "m4-expanding-1":
            raise ExperimentStoreError("VERSION_MISMATCH", "The walk-forward evaluation version is not m4-expanding-1.")
