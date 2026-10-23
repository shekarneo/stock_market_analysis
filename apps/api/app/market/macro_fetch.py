"""Fetch official macro releases into var/market/macro_series.json.

Sources (public, unauthenticated reads; no CAPTCHA is involved or bypassed):
1. NSE FII/DII provisional cash-market flows: GET https://www.nseindia.com/api/fiidiiTradeReact
   (NSE requires the cookies set by its home page, so the home page is requested first.)
2. FBIL USD/INR reference rate: GET https://www.fbil.org.in/wasdm/refrates/fetchfiltered
   ?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD&authenticated=false (the endpoint behind FBIL's
   public reference-rate table).
   When FBIL's public table lags, the ECB daily euro reference rates give the USD/INR cross
   (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml); the fresher release is kept.
3. US Treasury daily par yield curve CSV (10 Yr column):
   https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<year>/all

A source that fails keeps its previous entry, which then ages into STALE by its own
release date (app.market.macro_series); nothing is filled in or defaulted.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from app.market.macro_series import MACRO_SERIES_PATH, load_macro_series, save_macro_series

NSE_HOME = "https://www.nseindia.com/"
NSE_FIIDII_URL = "https://www.nseindia.com/api/fiidiiTradeReact"
FBIL_REFRATES_URL = "https://www.fbil.org.in/wasdm/refrates/fetchfiltered"
ECB_RATES_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
TREASURY_CSV_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"

BROWSER_HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "accept-language": "en-US,en;q=0.9",
}
VERIFICATION = "OFFICIAL_SOURCE_UNRECONCILED"  # fetched from the publisher, not cross-checked


class MacroFetchError(Exception):
    pass


@dataclass
class Response:
    status_code: int
    text: str


Getter = Callable[[str, dict | None, dict | None], Response]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return out if out == out else None


# ----------------------------------------------------------------------------- parsers

def parse_nse_fiidii(body: Any) -> dict:
    """[{category: "FII/FPI"|"DII", date: "22-Oct-2026", netValue: "-3458.7", ...}] -> series entry."""
    if not isinstance(body, list):
        raise MacroFetchError("NSE FII/DII response is not a list.")
    fii = next((r for r in body if isinstance(r, dict) and str(r.get("category", "")).upper().startswith("FII")), None)
    dii = next((r for r in body if isinstance(r, dict) and str(r.get("category", "")).upper().startswith("DII")), None)
    if fii is None or dii is None:
        raise MacroFetchError("NSE FII/DII response lacks the FII or DII row.")
    fii_net, dii_net = _num(fii.get("netValue")), _num(dii.get("netValue"))
    if fii_net is None or dii_net is None:
        raise MacroFetchError("NSE FII/DII net values are missing or not numeric.")
    try:
        fii_day = datetime.strptime(str(fii.get("date")), "%d-%b-%Y").date()
        dii_day = datetime.strptime(str(dii.get("date")), "%d-%b-%Y").date()
    except ValueError as exc:
        raise MacroFetchError(f"NSE FII/DII date is not DD-Mon-YYYY: {exc}") from exc
    if fii_day != dii_day:
        raise MacroFetchError(f"NSE FII ({fii_day}) and DII ({dii_day}) rows are for different days.")
    return {
        "instrument": "FII_DII_FLOWS",
        "fii_net_crores": fii_net,
        "dii_net_crores": dii_net,
        "net_total_crores": round(fii_net + dii_net, 2),
        "fii_buy_crores": _num(fii.get("buyValue")),
        "fii_sell_crores": _num(fii.get("sellValue")),
        "dii_buy_crores": _num(dii.get("buyValue")),
        "dii_sell_crores": _num(dii.get("sellValue")),
        "as_of_date": fii_day.isoformat(),
        "source": "NSE (provisional FII/DII cash market)",
        "source_url": NSE_FIIDII_URL,
        "verification_status": VERIFICATION,
    }


def parse_fbil_usdinr(body: Any) -> dict:
    """Latest "INR / 1 USD" row from FBIL's reference-rate list."""
    if not isinstance(body, list):
        raise MacroFetchError("FBIL response is not a list.")
    rows = []
    for r in body:
        if not isinstance(r, dict) or str(r.get("subProdName", "")).replace(" ", "").upper() != "INR/1USD":
            continue
        rate = _num(r.get("rate"))
        try:
            day = date.fromisoformat(str(r.get("processRunDate", ""))[:10])
        except ValueError:
            continue
        if rate is not None and rate > 0:
            rows.append((day, rate))
    if not rows:
        raise MacroFetchError("FBIL response has no INR / 1 USD reference rate.")
    day, rate = max(rows)
    return {
        "instrument": "USDINR_REF",
        "rate": rate,
        "as_of_date": day.isoformat(),
        "source": "FBIL USD/INR reference rate",
        "source_url": FBIL_REFRATES_URL,
        "verification_status": VERIFICATION,
    }


def parse_ecb_usdinr(text: str) -> dict:
    """USD/INR from the ECB daily euro reference rates: (INR per EUR) / (USD per EUR), latest day."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise MacroFetchError(f"ECB reference rates are not XML: {exc}") from exc
    days = []
    for cube in root.iter():
        if not cube.tag.endswith("Cube") or "time" not in cube.attrib:
            continue
        rates = {c.attrib.get("currency"): _num(c.attrib.get("rate")) for c in cube}
        try:
            day = date.fromisoformat(cube.attrib["time"])
        except ValueError:
            continue
        if rates.get("USD") and rates.get("INR"):
            days.append((day, rates["INR"] / rates["USD"]))
    if not days:
        raise MacroFetchError("ECB reference rates have no day with both USD and INR.")
    day, rate = max(days)
    return {
        "instrument": "USDINR_REF",
        "rate": round(rate, 4),
        "as_of_date": day.isoformat(),
        "source": "ECB euro reference rates (USD/INR cross: INR per EUR / USD per EUR)",
        "source_url": ECB_RATES_URL,
        "verification_status": VERIFICATION,
    }


def parse_treasury_10y(text: str) -> dict:
    """Most recent dated row with a numeric "10 Yr" value from the par yield CSV."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "10 Yr" not in reader.fieldnames or "Date" not in reader.fieldnames:
        raise MacroFetchError("Treasury CSV has no Date / 10 Yr columns.")
    rows = []
    for r in reader:
        value = _num(r.get("10 Yr"))
        try:
            day = datetime.strptime(str(r.get("Date")), "%m/%d/%Y").date()
        except ValueError:
            continue
        if value is not None:
            rows.append((day, value))
    if not rows:
        raise MacroFetchError("Treasury CSV has no 10 Yr values.")
    day, value = max(rows)
    return {
        "instrument": "US10Y_YIELD",
        "yield_pct": value,
        "as_of_date": day.isoformat(),
        "source": "US Treasury daily par yield curve",
        "source_url": TREASURY_CSV_URL.format(year=day.year),
        "verification_status": VERIFICATION,
    }


# ------------------------------------------------------------------------------ fetch

def httpx_getter(timeout: float = 25.0) -> tuple[Getter, Callable[[], None]]:
    """A cookie-keeping GET; TLS is verified against the OS store when truststore is available."""
    import httpx

    verify: Any = True
    try:
        import ssl

        import truststore

        verify = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    client = httpx.Client(timeout=timeout, headers=BROWSER_HEADERS, follow_redirects=True, verify=verify)

    def get(url: str, params: dict | None = None, headers: dict | None = None) -> Response:
        r = client.get(url, params=params, headers=headers)
        return Response(r.status_code, r.text)

    return get, client.close


def _json(resp: Response, label: str) -> Any:
    if resp.status_code != 200:
        raise MacroFetchError(f"{label} returned HTTP {resp.status_code}.")
    try:
        return json.loads(resp.text)
    except ValueError as exc:
        raise MacroFetchError(f"{label} did not return JSON.") from exc


def fetch_fii_dii(get: Getter) -> dict:
    get(NSE_HOME, None, {"accept": "text/html"})  # sets the cookies the API requires
    resp = get(NSE_FIIDII_URL, None, {"accept": "application/json", "referer": "https://www.nseindia.com/reports/fii-dii"})
    return parse_nse_fiidii(_json(resp, "NSE FII/DII"))


def fetch_usdinr(get: Getter, today: date) -> dict:
    """FBIL first; the ECB cross rate when FBIL's public table is older or unavailable.

    FBIL's public endpoint can lag by several sessions (on 23-Oct-2026 its newest row was
    16-Oct), so the fresher official release wins; on the same day FBIL is kept.
    """
    candidates, errors = [], []
    try:
        params = {"fromDate": (today - timedelta(days=14)).isoformat(), "toDate": today.isoformat(), "authenticated": "false"}
        resp = get(FBIL_REFRATES_URL, params, {"accept": "application/json", "referer": "https://www.fbil.org.in/"})
        candidates.append(parse_fbil_usdinr(_json(resp, "FBIL reference rates")))
    except Exception as exc:  # noqa: BLE001 - the ECB release may still be available
        errors.append(f"FBIL: {exc}")
    try:
        resp = get(ECB_RATES_URL, None, {"accept": "application/xml"})
        if resp.status_code != 200:
            raise MacroFetchError(f"ECB reference rates returned HTTP {resp.status_code}.")
        candidates.append(parse_ecb_usdinr(resp.text))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ECB: {exc}")
    if not candidates:
        raise MacroFetchError("; ".join(errors))
    best = max(candidates, key=lambda c: (c["as_of_date"], c["source"].startswith("FBIL")))
    if errors:
        best["source_errors"] = errors
    return best


def fetch_us10y(get: Getter, today: date) -> dict:
    last_error: Exception | None = None
    for year in (today.year, today.year - 1):  # early January may have no rows yet
        resp = get(TREASURY_CSV_URL.format(year=year),
                   {"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(year), "page": "", "_format": "csv"},
                   {"accept": "text/csv"})
        if resp.status_code != 200:
            last_error = MacroFetchError(f"Treasury CSV returned HTTP {resp.status_code}.")
            continue
        try:
            return parse_treasury_10y(resp.text)
        except MacroFetchError as exc:
            last_error = exc
    raise last_error or MacroFetchError("Treasury CSV unavailable.")


def refresh_macro_series(
    *,
    get: Getter | None = None,
    path: Path | None = None,
    now: datetime | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Fetch every source; merge successes into the cached file, keep failures' old entries."""
    now = now or datetime.now(timezone.utc)
    closer = None
    if get is None:
        get, closer = httpx_getter()
    cached = load_macro_series(path) or {}
    series = dict(cached.get("series") or {})
    errors: dict[str, str] = {}
    today = now.astimezone(timezone(timedelta(hours=5, minutes=30))).date()
    jobs = {
        "FII_DII_FLOWS": lambda: fetch_fii_dii(get),
        "USDINR_REF": lambda: fetch_usdinr(get, today),
        "US10Y_YIELD": lambda: fetch_us10y(get, now.date()),
    }
    try:
        for key, job in jobs.items():
            try:
                entry = job()
                entry["retrieved_at"] = now.isoformat()
                series[key] = entry
                log(f"{key}: as of {entry['as_of_date']}")
            except Exception as exc:  # recorded; the previous entry (if any) is kept as-is
                errors[key] = f"{exc.__class__.__name__}: {exc}"[:300]
                log(f"{key}: FAILED ({errors[key]})" + (" - keeping previous entry" if key in series else ""))
    finally:
        if closer:
            closer()
    document = {"schema": "macro-series-2", "retrieved_at": now.isoformat(), "series": series, "errors": errors}
    save_macro_series(document, path or MACRO_SERIES_PATH)
    return document
