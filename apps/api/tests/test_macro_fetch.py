"""Official macro release fetcher: parsers, merge, failure handling, CLI.

Response bodies mirror what NSE, FBIL and the US Treasury returned on 2026-10-23.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.market import macro_fetch as mf
from app.market.macro_series import IST, get_macro_observations

NSE_BODY = [
    {"buyValue": "16242.83", "category": "DII", "date": "22-Oct-2026", "netValue": "2891.32", "sellValue": "13351.51"},
    {"buyValue": "13627.54", "category": "FII/FPI", "date": "22-Oct-2026", "netValue": "-3458.7", "sellValue": "17086.24"},
]
FBIL_BODY = [
    {"processRunDate": "2026-10-14 00:00:00", "subProdName": "INR / 1 USD", "displayTime": "2026-10-14 13:00:00", "rate": 95.0012},
    {"processRunDate": "2026-10-22 00:00:00", "subProdName": "INR / 1 GBP", "displayTime": "2026-10-22 13:00:00", "rate": 125.8},
    {"processRunDate": "2026-10-22 00:00:00", "subProdName": "INR / 1 USD", "displayTime": "2026-10-22 13:00:00", "rate": 95.4321},
]
TREASURY_CSV = (
    'Date,"1 Mo","2 Mo","3 Mo","10 Yr","30 Yr"\n'
    "10/22/2026,4.11,4.16,4.22,4.96,5.29\n"
    "10/21/2026,4.09,4.16,4.25,5.13,5.42\n"
)
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=IST)


def test_parse_nse_fiidii():
    entry = mf.parse_nse_fiidii(NSE_BODY)
    assert entry["fii_net_crores"] == -3458.7 and entry["dii_net_crores"] == 2891.32
    assert entry["net_total_crores"] == pytest.approx(-567.38)
    assert entry["as_of_date"] == "2026-10-22"


@pytest.mark.parametrize("body", [
    {}, [NSE_BODY[0]], [NSE_BODY[0], {**NSE_BODY[1], "netValue": "-"}], [NSE_BODY[0], {**NSE_BODY[1], "date": "21-Oct-2026"}],
])
def test_parse_nse_rejects_incomplete_or_inconsistent(body):
    with pytest.raises(mf.MacroFetchError):
        mf.parse_nse_fiidii(body)


def test_parse_fbil_picks_latest_usd_row():
    entry = mf.parse_fbil_usdinr(FBIL_BODY)
    assert entry["rate"] == 95.4321 and entry["as_of_date"] == "2026-10-22"
    with pytest.raises(mf.MacroFetchError):
        mf.parse_fbil_usdinr([FBIL_BODY[1]])


def test_parse_treasury_latest_10y():
    entry = mf.parse_treasury_10y(TREASURY_CSV)
    assert entry["yield_pct"] == 4.96 and entry["as_of_date"] == "2026-10-22"
    with pytest.raises(mf.MacroFetchError):
        mf.parse_treasury_10y("Date,1 Mo\n10/22/2026,4.1\n")


def _ecb_xml(day: str, usd: str = "1.1205", inr: str = "106.2490") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
        'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
        f"<Cube><Cube time='{day}'><Cube currency='USD' rate='{usd}'/><Cube currency='JPY' rate='170.1'/>"
        f"<Cube currency='INR' rate='{inr}'/></Cube></Cube></gesmes:Envelope>"
    )


def test_parse_ecb_usdinr_cross_rate():
    entry = mf.parse_ecb_usdinr(_ecb_xml("2026-10-22"))
    assert entry["rate"] == pytest.approx(106.249 / 1.1205, abs=1e-4)  # INR per USD
    assert entry["as_of_date"] == "2026-10-22" and entry["source"].startswith("ECB")
    with pytest.raises(mf.MacroFetchError):
        mf.parse_ecb_usdinr(_ecb_xml("2026-10-22").replace("currency='INR'", "currency='XXX'"))
    with pytest.raises(mf.MacroFetchError):
        mf.parse_ecb_usdinr("not xml")


LAGGING_FBIL = [FBIL_BODY[0]]  # newest FBIL row 2026-10-14, as FBIL's public table lagged on 23-Oct-2026


@pytest.mark.parametrize(("fbil", "ecb_day", "fail", "source", "as_of"), [
    (LAGGING_FBIL, "2026-10-22", (), "ECB", "2026-10-22"),     # FBIL lags: the fresher ECB release wins
    (FBIL_BODY, "2026-10-22", (), "FBIL", "2026-10-22"),       # same day: FBIL is kept
    (FBIL_BODY, "2026-10-22", ("fbil",), "ECB", "2026-10-22"),  # FBIL down: ECB alone
])
def test_usdinr_keeps_the_freshest_official_release(fbil, ecb_day, fail, source, as_of):
    web = FakeWeb(fail=fail, fbil=fbil, ecb=_ecb_xml(ecb_day))
    entry = mf.fetch_usdinr(web, NOW.date())
    assert entry["source"].startswith(source) and entry["as_of_date"] == as_of


def test_ecb_usdinr_observation_names_its_source(tmp_path):
    path = tmp_path / "macro_series.json"
    mf.refresh_macro_series(get=FakeWeb(fbil=LAGGING_FBIL, ecb=_ecb_xml("2026-10-22")), path=path, now=NOW, log=lambda m: None)
    fx = next(o for o in get_macro_observations(path, now=NOW) if o["instrument"] == "USDINR_REF")
    assert fx["claim"].startswith("ECB USD/INR cross rate for 2026-10-22")
    assert fx["source_name"].startswith("ECB") and fx["stale"] is False


class FakeWeb:
    def __init__(self, fail=(), fbil=None, ecb=None):
        self.fail = set(fail)
        self.fbil = FBIL_BODY if fbil is None else fbil
        self.ecb = ecb
        self.calls = []

    def __call__(self, url, params=None, headers=None):
        self.calls.append(url)
        if url == mf.NSE_HOME:
            return mf.Response(200, "<html></html>")
        if url == mf.NSE_FIIDII_URL:
            return mf.Response(503, "") if "nse" in self.fail else mf.Response(200, json.dumps(NSE_BODY))
        if url == mf.FBIL_REFRATES_URL:
            return mf.Response(500, "{}") if "fbil" in self.fail else mf.Response(200, json.dumps(self.fbil))
        if url == mf.ECB_RATES_URL and self.ecb is not None:
            return mf.Response(200, self.ecb)
        if "treasury.gov" in url:
            return mf.Response(200, TREASURY_CSV)
        return mf.Response(404, "")


def test_refresh_writes_all_series_and_observations_follow(tmp_path):
    path = tmp_path / "macro_series.json"
    web = FakeWeb()
    doc = mf.refresh_macro_series(get=web, path=path, now=NOW, log=lambda m: None)
    assert doc["errors"] == {} and set(doc["series"]) == {"FII_DII_FLOWS", "USDINR_REF", "US10Y_YIELD"}
    assert web.calls[0] == mf.NSE_HOME  # cookies first
    obs = {o["instrument"]: o for o in get_macro_observations(path, now=NOW)}
    assert obs["FII_DII_FLOWS"]["stale"] is False
    assert obs["FII_DII_FLOWS"]["directional_implication"] == "BEARISH"  # FII sold more than DII bought
    assert obs["USDINR_REF"]["last_price"] == 95.4321


def test_failed_source_keeps_previous_entry_and_never_invents(tmp_path):
    path = tmp_path / "macro_series.json"
    old = {"fii_net_crores": 100.0, "dii_net_crores": 50.0, "net_total_crores": 150.0, "as_of_date": "2026-10-15"}
    path.write_text(json.dumps({"retrieved_at": "2026-10-15T12:00:00+00:00", "series": {"FII_DII_FLOWS": old}}), encoding="utf-8")
    doc = mf.refresh_macro_series(get=FakeWeb(fail={"nse", "fbil"}), path=path, now=NOW, log=lambda m: None)
    assert "HTTP 503" in doc["errors"]["FII_DII_FLOWS"] and "HTTP 500" in doc["errors"]["USDINR_REF"]
    assert doc["series"]["FII_DII_FLOWS"] == old  # kept unchanged, not refreshed or zeroed
    assert "USDINR_REF" not in doc["series"]  # never existed: nothing invented
    fii = next(o for o in get_macro_observations(path, now=NOW) if o["instrument"] == "FII_DII_FLOWS")
    assert fii["stale"] is True and fii["directional_implication"] == "UNKNOWN"


def test_cli_fetch_macro(tmp_path, monkeypatch, capsys):
    from app import cli

    original = mf.refresh_macro_series
    monkeypatch.setattr(mf, "refresh_macro_series",
                        lambda **kw: original(get=FakeWeb(), now=datetime.now(timezone.utc), log=lambda m: None, **kw))
    out = tmp_path / "m.json"
    assert cli.main(["fetch-macro", "--output", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "FII_DII_FLOWS" in printed and str(out) in printed
    assert json.loads(out.read_text(encoding="utf-8"))["schema"] == "macro-series-2"
