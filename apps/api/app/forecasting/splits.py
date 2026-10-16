"""One chronological train, validation, and test split.

Rows are ordered by prediction time. They are not shuffled.

The one-bar embargo exists because a binary-1 label is the next candle's close.
A training row is removed when its label becomes available at or after the first
validation row's as_of. On a contiguous M15 series that row is the last training
row, and its label candle is the first validation candle. A validation row is
removed on the same rule at the test boundary. Those labels are not used to fit
or to choose the model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

EVALUATION_VERSION = "m3-holdout-1"
EMBARGO_RULE = (
    "Remove a training row when label_available_at is at or after the first validation as_of, "
    "and a validation row when label_available_at is at or after the first test as_of. "
    "For contiguous M15 bars this removes the last raw training row and the last raw validation row, "
    "because those labels are the first candle of the next period."
)


class SplitConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    train_fraction: float = 0.6
    validation_fraction: float = 0.2
    embargo_bars: int = 1
    min_train: int = 8
    min_validation: int = 4
    min_test: int = 4
    seed: int = 0


def chronological_split(rows: list[dict], config: SplitConfig | None = None) -> dict:
    config = config or SplitConfig()
    if config.embargo_bars != 1:
        return _failure(
            "UNSUPPORTED_EMBARGO",
            "binary-1 overlaps by one bar. The embargo must stay one bar until a longer horizon exists.",
        )
    if config.train_fraction <= 0 or config.validation_fraction <= 0:
        return _failure("INVALID_SPLIT", "Train and validation fractions must be positive.")
    if config.train_fraction + config.validation_fraction >= 1:
        return _failure("INVALID_SPLIT", "The fractions leave no untouched test period.")
    ordered = sorted(rows, key=lambda row: _parse(row["as_of"]))
    keys = [row["key"] for row in ordered]
    if len(keys) != len(set(keys)):
        return _failure("DUPLICATE_OBSERVATION", "Eligible rows repeat a join key.")
    count = len(ordered)
    train_count = int(count * config.train_fraction)
    validation_count = int(count * config.validation_fraction)
    if train_count < 1 or validation_count < 1 or train_count + validation_count >= count:
        return _insufficient(config, count, 0, 0, 0)
    train_rows = ordered[:train_count]
    validation_rows = ordered[train_count : train_count + validation_count]
    test_rows = ordered[train_count + validation_count :]
    validation_start = _parse(validation_rows[0]["as_of"])
    test_start = _parse(test_rows[0]["as_of"])
    train_kept, train_embargo = _purge(train_rows, validation_start)
    validation_kept, validation_embargo = _purge(validation_rows, test_start)
    if (
        len(train_kept) < config.min_train
        or len(validation_kept) < config.min_validation
        or len(test_rows) < config.min_test
    ):
        return _insufficient(config, count, len(train_kept), len(validation_kept), len(test_rows))
    if not _strictly_before(train_kept, validation_kept) or not _strictly_before(validation_kept, test_rows):
        return _failure("SPLIT_ORDER", "The split did not keep train before validation before test.")
    return {
        "ok": True,
        "code": None,
        "evaluation_version": EVALUATION_VERSION,
        "seed": config.seed,
        "seed_draws_rows": False,
        "shuffled": False,
        "config": config.model_dump(mode="json"),
        "dataset_rows": count,
        "train": train_kept,
        "validation": validation_kept,
        "test": test_rows,
        "embargo_train": len(train_embargo),
        "embargo_validation": len(validation_embargo),
        "manifest": {
            "evaluation_version": EVALUATION_VERSION,
            "train_start": train_kept[0]["as_of"],
            "train_end": train_kept[-1]["as_of"],
            "validation_start": validation_kept[0]["as_of"],
            "validation_end": validation_kept[-1]["as_of"],
            "test_start": test_rows[0]["as_of"],
            "test_end": test_rows[-1]["as_of"],
            "train_count": len(train_kept),
            "validation_count": len(validation_kept),
            "test_count": len(test_rows),
            "embargo_train": len(train_embargo),
            "embargo_validation": len(validation_embargo),
            "excluded_by_embargo": len(train_embargo) + len(validation_embargo),
            "embargo_train_keys": [row["key"] for row in train_embargo],
            "embargo_validation_keys": [row["key"] for row in validation_embargo],
            "embargo_rule": EMBARGO_RULE,
            "seed": config.seed,
            "shuffled": False,
        },
    }


def _purge(rows: list[dict], boundary: datetime) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    embargo: list[dict] = []
    for row in rows:
        if _parse(row["label_available_at"]) >= boundary:
            embargo.append(row)
        else:
            kept.append(row)
    return kept, embargo


def _strictly_before(left: list[dict], right: list[dict]) -> bool:
    return _parse(left[-1]["label_available_at"]) < _parse(right[0]["as_of"]) and _parse(left[-1]["as_of"]) < _parse(
        right[0]["as_of"]
    )


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _failure(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "message": message, "forecast_ready": False}


def _insufficient(config: SplitConfig, available: int, train: int, validation: int, test: int) -> dict:
    return {
        "ok": False,
        "code": "INSUFFICIENT_DATA",
        "message": "The series cannot fill the train, validation, and test minimums after the embargo.",
        "forecast_ready": False,
        "available_rows": available,
        "train_count": train,
        "validation_count": validation,
        "test_count": test,
        "required": {
            "min_train": config.min_train,
            "min_validation": config.min_validation,
            "min_test": config.min_test,
        },
    }


def window_split(rows: list[dict], *, train_end: int, validation_end: int, test_end: int, embargo_bars: int = 1) -> dict:
    """Slice a sorted series and apply the M3 embargo. The indexes are not resized."""
    if embargo_bars != 1:
        return _failure(
            "UNSUPPORTED_EMBARGO",
            "binary-1 overlaps by one bar. The embargo must stay one bar until a longer horizon exists.",
        )
    ordered = sorted(rows, key=lambda row: _parse(row["as_of"]))
    if len({row["key"] for row in ordered}) != len(ordered):
        return _failure("DUPLICATE_OBSERVATION", "Eligible rows repeat a join key.")
    times = [_parse(row["as_of"]) for row in ordered]
    if any(times[index] >= times[index + 1] for index in range(len(times) - 1)):
        return _failure("AMBIGUOUS_TIME", "Observation times are not strictly increasing.")
    count = len(ordered)
    if not (0 < train_end < validation_end < test_end <= count):
        return _failure("INVALID_BOUNDARY", "The fold indexes are not a train, validation, then test span.")
    train_rows = ordered[:train_end]
    validation_rows = ordered[train_end:validation_end]
    test_rows = ordered[validation_end:test_end]
    train_kept, train_embargo = _purge(train_rows, _parse(validation_rows[0]["as_of"]))
    validation_kept, validation_embargo = _purge(validation_rows, _parse(test_rows[0]["as_of"]))
    return {
        "ok": True,
        "code": None,
        "shuffled": False,
        "train": train_kept,
        "validation": validation_kept,
        "test": test_rows,
        "raw_train_count": len(train_rows),
        "raw_validation_count": len(validation_rows),
        "raw_test_count": len(test_rows),
        "embargo_train_keys": [row["key"] for row in train_embargo],
        "embargo_validation_keys": [row["key"] for row in validation_embargo],
        "embargo_rule": EMBARGO_RULE,
        "train_start": train_rows[0]["as_of"],
        "train_end": train_rows[-1]["as_of"],
        "validation_start": validation_rows[0]["as_of"],
        "validation_end": validation_rows[-1]["as_of"],
        "test_start": test_rows[0]["as_of"],
        "test_end": test_rows[-1]["as_of"],
    }
