"""Build a feature dataset from an existing market-data provider.

The provider name is the configured synthetic or groww adapter. Callers do not
pass file paths or URLs.
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.pipeline import DatasetBuildResult, _failure, build_dataset
from app.features.store import DatasetStore
from app.market.calendar import ExchangeCalendar
from app.market.fixtures import fixture_calendar
from app.market.providers import GrowwReadProvider, SyntheticProvider
from app.market.schemas import Candle, RetrievalFailure
from app.market.service import assert_provider_name
from app.settings import REPO_ROOT


def feature_store() -> DatasetStore:
    return DatasetStore(REPO_ROOT / "var" / "datasets")


def _provider(name: str):
    assert_provider_name(name)
    if name == "synthetic":
        return SyntheticProvider()
    if name == "groww":
        return GrowwReadProvider()
    raise ValueError(f"Unknown provider: {name}")


def build_from_provider(
    instrument: str,
    *,
    provider_name: str,
    retrieved_at: datetime,
    as_of: datetime | None = None,
    store: DatasetStore | None = None,
) -> DatasetBuildResult | RetrievalFailure:
    provider = _provider(provider_name)
    loaded = provider.get_candles(instrument, retrieved_at=retrieved_at)
    if isinstance(loaded, RetrievalFailure):
        return loaded
    result = build_dataset(loaded, fixture_calendar(), as_of=as_of)
    if result.ok and result.artifact is not None and store is not None:
        store.write(result.artifact)
    return result


def rebuild_from_artifact(artifact: dict) -> DatasetBuildResult:
    from app.market.provenance import lineage_block, quarantine_training_block

    blocked = quarantine_training_block(artifact)
    if blocked is not None:
        return _failure(blocked[0], blocked[1])
    lineage_error = lineage_block(artifact)
    if lineage_error is not None:
        return _failure(lineage_error[0], lineage_error[1])
    if "source_candles" not in artifact or "feature_set_version" not in artifact:
        return _failure("NOT_REPRODUCIBLE", "The artifact does not contain source candles and feature configuration.")
    calendar = ExchangeCalendar(
        listed_sessions={date.fromisoformat(day) for day in artifact["calendar_listed_sessions"]},
        closed_dates={date.fromisoformat(day) for day in artifact["calendar_closed_dates"]},
    )
    candles = [Candle.model_validate(row) for row in artifact["source_candles"]]
    return build_dataset(
        candles,
        calendar,
        feature_set_version=artifact["feature_set_version"],
        history_dataset_id=artifact.get("dataset_id"),
        history_checksum=artifact.get("checksum"),
    )
