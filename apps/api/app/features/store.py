"""JSON dataset artifacts.

The manifest and the feature rows live in one file. Postgres is not used: these
artifacts are derived from the candles stored inside them, and a checksum detects
tampering. No object store is added.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.features.pipeline import content_hash

_ID = re.compile(r"^[a-f0-9]{64}$")


class DatasetStoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DatasetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, artifact: dict) -> Path:
        dataset_id = artifact.get("dataset_id")
        if not isinstance(dataset_id, str) or _ID.fullmatch(dataset_id) is None:
            raise DatasetStoreError("INVALID_DATASET_ID", "Dataset id is not a content hash.")
        if artifact.get("checksum") != dataset_id:
            raise DatasetStoreError("CHECKSUM_MISMATCH", "Dataset id and checksum disagree.")
        self._verify(artifact)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{dataset_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        return path

    def read(self, dataset_id: str) -> dict:
        if _ID.fullmatch(dataset_id) is None:
            raise DatasetStoreError("INVALID_DATASET_ID", "Dataset id is not a content hash.")
        path = self.root / f"{dataset_id}.json"
        if not path.is_file():
            raise DatasetStoreError("NOT_FOUND", "Dataset artifact was not found.")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self._verify(artifact)
        if artifact.get("dataset_id") != dataset_id:
            raise DatasetStoreError("CHECKSUM_MISMATCH", "Artifact id does not match the requested id.")
        return artifact

    def _verify(self, artifact: dict) -> None:
        body = {key: value for key, value in artifact.items() if key not in {"dataset_id", "checksum"}}
        digest = content_hash(body)
        if artifact.get("checksum") != digest or artifact.get("dataset_id") != digest:
            raise DatasetStoreError("CHECKSUM_MISMATCH", "Dataset checksum does not match its contents.")


def compare_manifests(left: dict, right: dict) -> dict:
    ignored = {"rows", "source_candles"}
    keys = sorted((set(left) | set(right)) - ignored)
    differing = [key for key in keys if left.get(key) != right.get(key)]
    return {
        "equal": left.get("checksum") == right.get("checksum") and not differing,
        "differing_fields": differing,
        "left_id": left.get("dataset_id"),
        "right_id": right.get("dataset_id"),
    }
