"""Macro releases: no invented data, staleness by release schedule, FII-led direction."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.analysis.agent_nodes import global_macro_analyst_node
from app.market.macro_series import (
    IST,
    business_days_behind,
    fii_dii_direction,
    get_macro_observations,
    latest_expected_date,
)

FRI_NOON = datetime(2026, 10, 23, 12, 0, tzinfo=IST)


def _write(tmp_path, series):
    path = tmp_path / "macro_series.json"
    path.write_text(json.dumps({"retrieved_at": "2026-10-23T06:00:00+00:00", "series": series}), encoding="utf-8")
    return path


def _fii(as_of, fii=-1245.5, dii=1850.25, net=604.75):
    return {"FII_DII_FLOWS": {"fii_net_crores": fii, "dii_net_crores": dii, "net_total_crores": net, "as_of_date": as_of}}


def test_no_file_means_no_observations_and_nothing_is_written(tmp_path):
    path = tmp_path / "macro_series.json"
    assert get_macro_observations(path, now=FRI_NOON) == []
    assert not path.exists()


def test_release_schedule():
    from datetime import time

    assert latest_expected_date(FRI_NOON, time(17, 30)) == date(2026, 10, 22)  # before Friday's release
    assert latest_expected_date(datetime(2026, 10, 23, 18, 0, tzinfo=IST), time(17, 30)) == date(2026, 10, 23)
    assert latest_expected_date(datetime(2026, 10, 24, 10, 0, tzinfo=IST), time(17, 30)) == date(2026, 10, 23)  # Saturday
    assert latest_expected_date(datetime(2026, 10, 26, 9, 0, tzinfo=IST), time(17, 30)) == date(2026, 10, 23)  # Monday am
    assert business_days_behind(date(2026, 10, 16), date(2026, 10, 22)) == 4


def test_week_old_fii_flows_are_stale_and_carry_no_direction(tmp_path):
    (obs,) = get_macro_observations(_write(tmp_path, _fii("2026-10-16", fii=3000, dii=100, net=3100)), now=FRI_NOON)
    assert obs["stale"] is True and obs["business_days_behind"] == 4
    assert obs["directional_implication"] == "UNKNOWN"
    assert obs["limitations"][0].startswith("STALE")


def test_latest_release_is_fresh_and_fii_selling_offset_by_dii_is_mixed(tmp_path):
    (obs,) = get_macro_observations(_write(tmp_path, _fii("2026-10-22")), now=FRI_NOON)
    assert obs["stale"] is False
    assert obs["directional_implication"] == "MIXED"  # FII -1245 Cr offset by DII: not a bullish tailwind


@pytest.mark.parametrize("fii,net,expected", [
    (2000, 2500, "BULLISH"), (-2000, -1500, "BEARISH"), (-2000, 300, "MIXED"), (2000, -100, "MIXED"), (200, 900, "UNKNOWN"),
])
def test_fii_led_direction(fii, net, expected):
    assert fii_dii_direction(fii, net) == expected


def test_missing_values_are_not_filled_with_zero_or_defaults(tmp_path):
    series = {**_fii("2026-10-22", fii=None), "USDINR_REF": {"as_of_date": "2026-10-22"},
              "US10Y_YIELD": {"yield_pct": 4.1}}
    assert get_macro_observations(_write(tmp_path, series), now=FRI_NOON) == []


def _state(evidence):
    return {"instruments": ["NIFTY"], "evidence": evidence, "agent_outputs": {}}


def _ev(direction, *, stale_note=False, freshness="STALE", instrument="FII_DII_FLOWS"):
    return {"evidence_id": f"{instrument}-{direction}", "category": "MACRO", "instrument": instrument,
            "directional_implication": direction, "freshness": freshness,
            "limitations": ["STALE: release dated 2026-10-16 is 4 business day(s) behind."] if stale_note else []}


def test_agent_ignores_stale_release_and_casts_no_vote():
    out = global_macro_analyst_node(_state([_ev("BULLISH", stale_note=True)]))["agent_outputs"]["global_macro_analyst"]
    assert out["directional_bias"] == "UNKNOWN" and out["confidence"] is None
    assert any("Stale macro inputs excluded" in f and "FII_DII_FLOWS" in f for f in out["findings"])


def test_agent_counts_latest_daily_release_even_when_hours_old():
    # The evidence window labels yesterday's 17:30 release STALE intraday; the source check says it is current.
    out = global_macro_analyst_node(_state([_ev("BEARISH", freshness="STALE")]))["agent_outputs"]["global_macro_analyst"]
    assert out["directional_bias"] == "BEARISH"
