"""JSON registry. Writes are locked, checksummed, and replaced atomically.

The fitted artifact stays in the M3 or M4 store. This file stores the registry
row, its status history, and the research pointer. It does not store a
filesystem path or a trading approval.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
from pathlib import Path

from app.features.pipeline import content_hash
from app.registry.schema import SCHEMA_VERSION
from app.settings import REPO_ROOT

_FALSE_FLAGS = (
    "forecast_ready",
    "paper_approved",
    "live_approved",
    "real_market_data_verified",
)


class RegistryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def registry_store() -> RegistryStore:
    return RegistryStore(REPO_ROOT / "var" / "registry")


def empty_document() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "forecast_ready": False,
        "paper_approved": False,
        "live_approved": False,
        "real_market_data_verified": False,
        "performance_claim_allowed": False,
        "paper_slot": None,
        "live_slot": None,
        "models": {},
        "experiments": {},
        "research_selections": [],
        "idempotency": {},
    }


class RegistryStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.path = self.root / "registry.json"
        self.lock_path = self.root / "registry.lock"

    def read(self) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock() as handle:
            return self._read_unlocked(handle)

    def update(self, mutator):
        """Apply mutator under an exclusive lock.

        The mutator receives a deep copy and returns either `(None, result)`
        when nothing should be written, or `(document, result)`. A new document
        must increment `revision` by one. A raised RegistryError writes nothing.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock() as handle:
            current = self._read_unlocked(handle)
            updated, result = mutator(copy.deepcopy(current))
            if updated is None:
                return result
            if updated.get("revision") != current["revision"] + 1:
                raise RegistryError("REVISION_CONFLICT", "The registry revision was not advanced exactly once.")
            sealed = _seal(updated)
            self._write_atomic(sealed)
            return result

    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            handle.close()
            raise
        return _Locked(handle)

    def _read_unlocked(self, _handle) -> dict:
        if not self.path.is_file():
            return empty_document()
        if self.path.resolve().parent != self.root:
            raise RegistryError("UNSAFE_PATH", "The registry file would leave the store root.")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RegistryError("MALFORMED_REGISTRY", "The registry file is not valid JSON.") from exc
        _verify(document)
        return document

    def _write_atomic(self, document: dict) -> None:
        if self.path.resolve().parent != self.root:
            raise RegistryError("UNSAFE_PATH", "The registry file would leave the store root.")
        temporary = self.root / "registry.json.tmp"
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


class _Locked:
    def __init__(self, handle) -> None:
        self.handle = handle

    def __enter__(self):
        return self.handle

    def __exit__(self, *_args) -> None:
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def _seal(document: dict) -> dict:
    _reject_trading_flags(document)
    body = {key: value for key, value in document.items() if key != "registry_checksum"}
    frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":")))
    frozen["registry_checksum"] = content_hash(frozen)
    return frozen


def _verify(document: dict) -> None:
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("MALFORMED_REGISTRY", "The registry schema is not m5-registry-1.")
    body = {key: value for key, value in document.items() if key != "registry_checksum"}
    frozen = json.loads(json.dumps(body, sort_keys=True, separators=(",", ":")))
    if document.get("registry_checksum") != content_hash(frozen):
        raise RegistryError("CHECKSUM_MISMATCH", "The registry checksum does not match its contents.")
    _reject_trading_flags(document)


def _reject_trading_flags(document: dict) -> None:
    for flag in _FALSE_FLAGS:
        if document.get(flag) is not False:
            raise RegistryError("APPROVAL_REFUSED", "The registry cannot claim a trading-readiness flag.")
    if document.get("paper_slot") is not None or document.get("live_slot") is not None:
        raise RegistryError("APPROVAL_REFUSED", "The registry has no paper or live slot.")
    if document.get("performance_claim_allowed") is not False:
        raise RegistryError("APPROVAL_REFUSED", "The registry cannot claim market performance.")
    for model in document.get("models", {}).values():
        for version in model.get("versions", {}).values():
            for flag in _FALSE_FLAGS:
                if version.get(flag) is not False:
                    raise RegistryError("APPROVAL_REFUSED", "A model version cannot claim a trading-readiness flag.")
            if version.get("status") in {"APPROVED_FOR_PAPER", "APPROVED_FOR_LIVE"}:
                raise RegistryError("APPROVAL_REFUSED", "Paper and live approval are not registry states in this milestone.")
