"""A registry holding one plumbing-only logistic model on the current feature set.

Live-forecast plumbing tests use it instead of the operator's var/registry, so they do not
depend on which model (or feature-set version) happens to be registered on the machine.
The weights are fixed fixtures; nothing about forecast quality is implied.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.forecasting.targets import MODEL_FEATURES


def write_fixture_registry(folder: Path) -> Path:
    names = list(MODEL_FEATURES)
    n = len(names)
    entry = {
        "status": "TRAINED", "family": "logistic_regression", "model_version": "logistic-l2-newton-1",
        "model_id": "logistic_regression:NIFTY:M15",
        "fitted_state": {"ok": True, "family": "logistic_regression", "feature_names": names,
                         "scaler": {"means": [0.0] * n, "scales": [1.0] * n},
                         "weights": [0.1 * ((i % 3) - 1) for i in range(n)], "intercept": 0.05},
    }
    path = Path(folder) / "registry.json"
    path.write_text(json.dumps({"models": {"logistic_regression:NIFTY:M15": {"versions": {"v1": entry}}}}),
                    encoding="utf-8")
    return path
