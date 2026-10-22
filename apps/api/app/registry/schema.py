"""Names shared by the registry. Spec family ids stay distinct from M3 experiment keys."""

from __future__ import annotations

from app.features.definitions import FEATURE_SET_VERSION

from app.instruments import TRADABLE_UNDERLYINGS

SCHEMA_VERSION = "m5-registry-1"

EXPERIMENT_KEYS = {
    "majority_class": {
        "family": "base_rate",
        "entry_point": "app.forecasting.models:fit_majority",
        "model_version": "majority-train-prevalence-1",
    },
    "last_return_sign": {
        "family": "persistence",
        "entry_point": "app.forecasting.models:fit_last_return_sign",
        "model_version": "last-return-sign-laplace-1",
    },
    "logistic_regression": {
        "family": "logistic_regression",
        "entry_point": "app.forecasting.models:fit_logistic",
        "model_version": "logistic-l2-newton-1",
    },
}

FAMILY_TO_KEY = {
    "base_rate": "majority_class",
    "persistence": "last_return_sign",
    "majority_class": "majority_class",
    "last_return_sign": "last_return_sign",
    "logistic_regression": "logistic_regression",
}

NOT_IMPLEMENTED_FAMILIES = frozenset(
    {
        "lightgbm",
        "xgboost",
        "random_forest",
        "tcn",
        "lstm_gru",
        "small_transformer",
        "timesfm",
        "chronos2",
        "ensemble",
    }
)

INSTRUMENTS = frozenset(TRADABLE_UNDERLYINGS)
HORIZON = "M15"
FEATURE_SET = FEATURE_SET_VERSION
TARGET_VERSION = "binary-1"
TARGET_ID = "m15_next_close_direction"

STATUSES = frozenset(
    {"REGISTERED", "TRAINED", "EVALUATED", "APPROVED_FOR_RESEARCH", "DEPRECATED", "DISABLED"}
)
SELECTABLE = frozenset({"EVALUATED", "APPROVED_FOR_RESEARCH"})
TRADING_STATUSES = frozenset({"APPROVED_FOR_PAPER", "APPROVED_FOR_LIVE"})

ALLOWED_TRANSITIONS = {
    ("TRAINED", "EVALUATED"),
    ("EVALUATED", "APPROVED_FOR_RESEARCH"),
    ("REGISTERED", "DEPRECATED"),
    ("TRAINED", "DEPRECATED"),
    ("EVALUATED", "DEPRECATED"),
    ("APPROVED_FOR_RESEARCH", "DEPRECATED"),
    ("REGISTERED", "DISABLED"),
    ("TRAINED", "DISABLED"),
    ("EVALUATED", "DISABLED"),
    ("APPROVED_FOR_RESEARCH", "DISABLED"),
}

METRIC_NAMES = ("accuracy", "balanced_accuracy", "precision", "recall", "f1", "log_loss", "brier")
MODEL_NAMES = ("majority_class", "last_return_sign", "logistic_regression")

LIMITATIONS = (
    "binary-1 is an experimental next-close direction label. "
    "Synthetic and documented-sample runs are not market performance. "
    "A provider origin is not verified market data. "
    "Log loss and Brier score do not mean the probabilities are calibrated. "
    "Research selection does not approve paper trading, live trading, or order execution."
)
