from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.features.definitions import FEATURE_SET_VERSION
from app.features.pipeline import (
    build_dataset,
    candle_is_complete,
    compute_feature_row,
    content_hash,
    select_available,
)
from app.features.service import build_from_provider, rebuild_from_artifact
from app.features.store import DatasetStore, DatasetStoreError, compare_manifests
from app.market.calendar import ExchangeCalendar
from app.market.fixtures import fixture_calendar, quiet_day_candles
from app.market.schemas import IST, Candle, DataOrigin, MarketSession
from tests.conftest import login

RETRIEVED = datetime(2026, 1, 5, 12, 0, tzinfo=IST)


def bars(
    closes: list[float],
    *,
    day: datetime | None = None,
    origin: DataOrigin = DataOrigin.SYNTHETIC,
    source_id: str = "unit",
    instrument: str = "NIFTY",
    retrieved_at: datetime = RETRIEVED,
    provider_timestamp: datetime | None = None,
    open_delta: float = 0,
    high_delta: float = 2,
    low_delta: float = -2,
) -> list[Candle]:
    start = day or datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    built = []
    for step, close in enumerate(closes):
        bar_start = start + timedelta(minutes=15 * step)
        built.append(
            Candle(
                instrument_id=instrument,
                underlying=instrument,
                exchange=None,
                interval="M15",
                bar_start=bar_start,
                bar_end=bar_start + timedelta(minutes=15),
                provider_timestamp=provider_timestamp,
                retrieved_at=retrieved_at,
                open=close + open_delta,
                high=close + high_delta,
                low=close + low_delta,
                close=close,
                volume=None,
                source_id=source_id,
                origin=origin,
                session=MarketSession.OPEN,
            )
        )
    return built


def _row(result, index: int) -> dict:
    assert result.ok and result.artifact is not None
    return result.artifact["rows"][index]


def test_known_returns_means_volatility_momentum_and_candle_shape():
    closes = [100, 110, 120, 130, 140, 150]
    result = build_dataset(bars(closes), fixture_calendar())
    assert result.forecast_ready is False
    second = _row(result, 1)["values"]
    assert second["ret_1"] == {"value": pytest.approx(0.1), "status": "VALID"}
    assert second["oc_return"] == {"value": 0.0, "status": "VALID"}
    assert second["close_position"] == {"value": 0.5, "status": "VALID"}
    assert second["hl_range_vs_prev_close"] == {"value": pytest.approx(0.04), "status": "VALID"}
    third = _row(result, 2)["values"]
    assert third["sma_3"]["value"] == pytest.approx(110)
    fourth = _row(result, 3)["values"]
    assert fourth["ret_3"]["value"] == pytest.approx(0.3)
    assert fourth["atr_3"]["value"] == pytest.approx(12)
    fifth = _row(result, 4)["values"]
    assert fifth["sma_5"]["value"] == pytest.approx(120)
    assert fifth["close_vs_sma_5"]["value"] == pytest.approx(140 / 120 - 1)
    assert fifth["sma_3_minus_sma_5"]["value"] == pytest.approx(10)
    returns = [110 / 100 - 1, 120 / 110 - 1, 130 / 120 - 1, 140 / 130 - 1, 150 / 140 - 1]
    assert _row(result, 5)["values"]["ret_std_5"]["value"] == pytest.approx(statistics.stdev(returns))


def test_warmup_is_distinct_from_a_valid_zero():
    result = build_dataset(bars([100, 100, 100]), fixture_calendar())
    first = _row(result, 0)["values"]
    assert first["ret_1"] == {"value": None, "status": "WARMUP"}
    assert first["sma_3"]["status"] == "WARMUP"
    assert first["ret_std_5"]["status"] == "WARMUP"
    assert first["atr_3"]["status"] == "WARMUP"
    assert first["oc_return"] == {"value": 0.0, "status": "VALID"}
    assert first["close_position"]["status"] == "VALID"
    assert result.partial is True
    assert result.artifact["forecast_ready"] is False


def test_flat_range_is_invalid_input_and_not_zero():
    candles = bars([100], high_delta=0, low_delta=0)
    result = build_dataset(candles, fixture_calendar())
    position = _row(result, 0)["values"]["close_position"]
    assert position == {"value": None, "status": "INVALID_INPUT"}


def test_trailing_mean_is_not_a_centered_window():
    result = build_dataset(bars([100, 110, 120, 130]), fixture_calendar())
    value = _row(result, 2)["values"]["sma_3"]["value"]
    assert value == pytest.approx((100 + 110 + 120) / 3)
    centered = (110 + 120 + 130) / 3
    assert value != pytest.approx(centered)


def test_future_close_does_not_change_an_earlier_row():
    original = bars([100, 110, 120, 130, 140, 150])
    left = build_dataset(original, fixture_calendar())
    changed = bars([100, 110, 120, 130, 140, 999])
    right = build_dataset(changed, fixture_calendar())
    assert _row(left, 2)["values"] == _row(right, 2)["values"]
    assert _row(left, 2)["as_of"] == original[2].bar_end.isoformat()


def test_as_of_excludes_later_candles_and_accepts_utc():
    candles = bars([100, 110, 120, 130])
    cutoff = candles[1].bar_end.astimezone(timezone.utc)
    result = build_dataset(candles, fixture_calendar(), as_of=cutoff)
    assert result.artifact["output_row_count"] == 2
    assert result.artifact["excluded_after_cutoff"] == 2
    assert result.artifact["rows"][-1]["values"]["ret_1"]["value"] == pytest.approx(0.1)
    earlier = cutoff - timedelta(seconds=1)
    excluded = select_available(candles, earlier)
    assert len(excluded) == 1


def test_provider_timestamp_is_not_the_completion_time():
    candles = bars([100, 110], provider_timestamp=datetime(2026, 1, 5, 9, 15, tzinfo=IST))
    assert candles[1].provider_timestamp < candles[1].bar_end
    assert candle_is_complete(candles[1])
    result = build_dataset(candles, fixture_calendar())
    assert result.ok
    assert _row(result, 1)["as_of"] == candles[1].bar_end.isoformat()
    assert _row(result, 1)["values"]["ret_1"]["status"] == "VALID"


def test_incomplete_candle_does_not_produce_a_dataset(tmp_path):
    candles = bars([100, 110])
    broken = candles[1].model_copy(update={"retrieved_at": candles[1].bar_end - timedelta(seconds=1)})
    assert candle_is_complete(broken) is False
    store = DatasetStore(tmp_path)
    result = build_dataset([candles[0], broken], fixture_calendar())
    assert result.ok is False
    assert result.code == "RETRIEVAL_BEFORE_EVENT"
    assert result.artifact is None
    assert result.rejected_row_count == 2
    assert list(tmp_path.iterdir()) == []
    row = compute_feature_row([candles[0], broken], 1, fixture_calendar())
    assert row.values["ret_1"].status == "INCOMPLETE_CANDLE"
    assert list(store.root.iterdir()) == [] if store.root.exists() else True


def test_out_of_order_and_duplicate_timestamps_are_rejected(tmp_path):
    candles = bars([100, 110, 120])
    store = DatasetStore(tmp_path)
    out_of_order = build_dataset(list(reversed(candles)), fixture_calendar())
    assert out_of_order.ok is False
    assert out_of_order.code == "OUT_OF_ORDER"
    duplicate = build_dataset([candles[0], candles[0], candles[1]], fixture_calendar())
    assert duplicate.ok is False
    assert duplicate.code == "DUPLICATE_TIMESTAMP"
    assert list(store.root.iterdir()) == []


def test_naive_as_of_is_rejected():
    with pytest.raises(ValidationError):
        Candle.model_validate(
            bars([100])[0].model_dump() | {"bar_end": datetime(2026, 1, 5, 9, 30)}
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        build_dataset(bars([100]), fixture_calendar(), as_of=datetime(2026, 1, 5, 9, 30))


def test_missing_interval_is_not_filled(tmp_path):
    candles = bars([100, 110, 120, 130])
    gapped = [candles[0], candles[2], candles[3]]
    result = build_dataset(gapped, fixture_calendar())
    assert result.ok is False
    assert result.code == "MISSING_CANDLE"
    assert result.artifact is None
    assert result.rejected_row_count == 3
    assert list(tmp_path.iterdir()) == []


def test_invalid_ohlc_does_not_emit_a_dataset():
    candle = bars([100])[0].model_copy(update={"high": 90})
    result = build_dataset([candle], fixture_calendar())
    assert result.ok is False
    assert result.code == "INVALID_OHLC"
    assert result.artifact is None
    assert result.forecast_ready is False


def test_unknown_calendar_is_not_a_confirmed_session():
    candles = bars(
        [100, 110],
        day=datetime(2026, 1, 6, 9, 15, tzinfo=IST),
        retrieved_at=datetime(2026, 1, 6, 12, 0, tzinfo=IST),
    )
    result = build_dataset(candles, fixture_calendar())
    assert result.ok is True
    assert result.artifact["calendar_authoritative"] is False
    row = _row(result, 1)["values"]
    assert row["session_confirmed"] == {"value": None, "status": "CALENDAR_UNKNOWN"}
    assert row["ret_1"]["status"] == "VALID"
    assert "CALENDAR_UNKNOWN" in result.artifact["readiness_reasons"]
    assert result.artifact["forecast_ready"] is False


def test_closed_fixture_day_is_rejected():
    candles = bars(
        [100, 110],
        day=datetime(2026, 1, 4, 9, 15, tzinfo=IST),
        retrieved_at=datetime(2026, 1, 4, 12, 0, tzinfo=IST),
    )
    result = build_dataset(candles, fixture_calendar())
    assert result.ok is False
    assert result.code == "NOT_A_SESSION"


def test_synthetic_provenance_survives_and_is_not_forecast_ready():
    result = build_dataset(quiet_day_candles("NIFTY", retrieved_at=RETRIEVED), fixture_calendar())
    artifact = result.artifact
    assert artifact["origin"] == "SYNTHETIC"
    assert artifact["synthetic"] is True
    assert artifact["live_market_data"] is False
    assert artifact["paper_approved"] is False
    assert artifact["live_approved"] is False
    assert artifact["forecast_ready"] is False
    assert artifact["untouched_test_start"] is None
    assert artifact["untouched_test_end"] is None
    assert all(row["origin"] == "SYNTHETIC" for row in artifact["rows"])
    assert "SYNTHETIC_INPUT" in artifact["readiness_reasons"]
    assert artifact["output_row_count"] == 4
    sensex = build_dataset(quiet_day_candles("SENSEX", retrieved_at=RETRIEVED), fixture_calendar())
    assert sensex.artifact["dataset_id"] != artifact["dataset_id"]
    assert sensex.artifact["rows"][0]["instrument_id"] == "SENSEX"


def test_documented_sample_is_not_promoted_to_provider():
    candles = bars([100, 110], origin=DataOrigin.DOCUMENTED_SAMPLE, source_id="groww-doc")
    result = build_dataset(candles, fixture_calendar())
    assert result.artifact["origin"] == "DOCUMENTED_SAMPLE"
    assert result.artifact["synthetic"] is False
    assert result.artifact["live_market_data"] is False
    assert result.artifact["forecast_ready"] is False


def test_mixed_origin_is_rejected(tmp_path):
    left = bars([100])[0]
    right = bars([110], origin=DataOrigin.PROVIDER, source_id="other")[0]
    result = build_dataset([left, right], fixture_calendar())
    assert result.ok is False
    assert result.code == "MIXED_ORIGIN"
    assert result.artifact is None
    assert DatasetStore(tmp_path).root.exists() is False or list(tmp_path.iterdir()) == []


def test_identical_inputs_are_stable_and_versions_change_the_id(tmp_path):
    candles = bars([100, 110, 120, 130, 140, 150])
    calendar = fixture_calendar()
    first = build_dataset(candles, calendar)
    second = build_dataset(candles, calendar)
    assert first.artifact["dataset_id"] == second.artifact["dataset_id"]
    assert first.artifact["checksum"] == first.artifact["dataset_id"]
    other = build_dataset(bars([100, 110, 120, 130, 140, 151]), calendar)
    assert other.artifact["dataset_id"] != first.artifact["dataset_id"]
    custom = ExchangeCalendar(listed_sessions={datetime(2026, 1, 5).date()}, closed_dates=set())
    shifted = build_dataset(candles, custom)
    assert shifted.artifact["dataset_id"] != first.artifact["dataset_id"]
    body = {key: value for key, value in first.artifact.items() if key not in {"dataset_id", "checksum"}}
    changed = {**body, "feature_set_version": "ohlc-2"}
    assert content_hash(changed) != first.artifact["dataset_id"]
    refused = build_dataset(candles, calendar, feature_set_version="ohlc-2")
    assert refused.ok is False
    assert refused.code == "UNKNOWN_FEATURE_SET"
    assert refused.artifact is None
    store = DatasetStore(tmp_path)
    store.write(first.artifact)
    loaded = store.read(first.artifact["dataset_id"])
    assert loaded["checksum"] == first.artifact["checksum"]
    rebuilt = rebuild_from_artifact(loaded)
    assert rebuilt.ok is True
    assert rebuilt.artifact["lineage"]["parent_dataset_id"] == loaded["dataset_id"]
    assert rebuilt.artifact["lineage"]["origin"] == loaded["lineage"]["origin"]
    assert rebuild_from_artifact(loaded).artifact["dataset_id"] == rebuilt.artifact["dataset_id"]
    path = tmp_path / f"{loaded['dataset_id']}.json"
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["rows"][1]["values"]["ret_1"]["value"] = 999
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(DatasetStoreError) as caught:
        store.read(loaded["dataset_id"])
    assert caught.value.code == "CHECKSUM_MISMATCH"
    with pytest.raises(DatasetStoreError):
        store.read("../etc/passwd")
    assert compare_manifests(first.artifact, second.artifact)["equal"] is True
    assert "dataset_id" in compare_manifests(first.artifact, other.artifact)["differing_fields"]
    assert FEATURE_SET_VERSION == first.artifact["feature_set_version"]


def test_feature_api_keeps_synthetic_data_unready(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.feature_store", lambda: DatasetStore(tmp_path))
    denied = client.post("/api/features/datasets", json={"instrument": "NIFTY"})
    assert denied.status_code == 401
    token = login(client)
    extra = client.post(
        "/api/features/datasets",
        json={"instrument": "NIFTY", "path": "/tmp/candles.json"},
        headers={"x-csrf-token": token},
    )
    assert extra.status_code == 422
    created = client.post(
        "/api/features/datasets",
        json={"instrument": "NIFTY"},
        headers={"x-csrf-token": token},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["forecast_ready"] is False
    assert payload["artifact"]["origin"] == "SYNTHETIC"
    assert payload["artifact"]["forecast_ready"] is False
    assert payload["artifact"]["live_market_data"] is False
    dataset_id = payload["artifact"]["dataset_id"]
    loaded = client.get(f"/api/features/datasets/{dataset_id}")
    assert loaded.status_code == 200
    assert loaded.json()["checksum"] == dataset_id
    sensex = client.post(
        "/api/features/datasets",
        json={"instrument": "SENSEX"},
        headers={"x-csrf-token": token},
    )
    assert sensex.status_code == 200
    comparison = client.get(
        "/api/features/datasets/compare",
        params={"left": dataset_id, "right": sensex.json()["artifact"]["dataset_id"]},
    )
    assert comparison.status_code == 200
    assert comparison.json()["equal"] is False
    groww = client.post(
        "/api/features/datasets",
        json={"instrument": "NIFTY", "provider": "groww"},
        headers={"x-csrf-token": token},
    )
    assert groww.status_code == 501
    assert groww.json()["code"] == "CANDLE_BOUNDARY_UNVERIFIED"
    url = client.post(
        "/api/features/datasets",
        json={"instrument": "NIFTY", "provider": "http://example.test"},
        headers={"x-csrf-token": token},
    )
    assert url.status_code == 400
    missing = client.get("/api/features/datasets/" + "a" * 64)
    assert missing.status_code == 404


def test_provider_builder_does_not_mark_the_quiet_day_forecast_ready():
    result = build_from_provider(
        "NIFTY",
        provider_name="synthetic",
        retrieved_at=RETRIEVED,
    )
    assert result.artifact["synthetic"] is True
    assert result.forecast_ready is False
    assert result.artifact["source_row_count"] == 4
