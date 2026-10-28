"""Groww live market snapshot parser for MCX commodities, Global indices, and Indian sectorals.

Groww publishes daily/live snapshot feeds for:
1. MCX Commodities (Crude Oil, Gold, Silver, Natural Gas) at https://groww.in/commodities
2. Global Indices (Gift Nifty, Dow Jones, Dow Futures, Nikkei 225, Hang Seng) at https://groww.in/indices/global-indices/dow-jones
3. Domestic Sectoral & Sentiment Indices (India VIX, NIFTY Bank, BSE Bankex) at https://groww.in/indices

These snapshots are non-interval (spot/daily level) market prints.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

COMMODITY_FUTURES_TARGETS = [
    ("mcx_crudeoilm19nov26fut", "CRUDEOILMINI", "MCX Crude Oil Mini (19 Nov)", "₹/bbl"),
    ("mcx_goldm", "GOLDMINI", "MCX Gold Mini", "₹/10g"),
    ("mcx_silverm", "SILVERMINI", "MCX Silver Mini", "₹/kg"),
    ("mcx_natgasmini", "NATURALGASMINI", "MCX Natural Gas Mini", "₹/mmBtu"),
]


def fetch_html(url: str, timeout: float = 8.0) -> str | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def fetch_direct_groww_futures(retrieved_at: datetime | None = None) -> list[dict]:
    """Fetch live tick-by-tick futures contract quotes directly from Groww contract pages."""
    stamp = (retrieved_at or datetime.now(timezone.utc)).isoformat()

    def _fetch_target(target: tuple[str, str, str, str]) -> dict | None:
        slug, inst, name, unit = target
        url = f"https://groww.in/commodities/futures/{slug}"
        html = fetch_html(url, timeout=4.0)
        if not html and "crudeoilm" in slug:
            url = "https://groww.in/commodities/futures/mcx_crudeoilm"
            html = fetch_html(url, timeout=4.0)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")
        nxt = soup.find("script", id="__NEXT_DATA__")
        if not nxt or not nxt.string:
            return None
        try:
            data = json.loads(nxt.string)
            props = data.get("props", {}).get("pageProps", {})
            live = props.get("staticData", {}).get("livePriceDetails")
            if not live or live.get("ltp") is None:
                return None
            ltp = float(live.get("ltp") or 0)
            close = float(live.get("close") or 0)
            open_p = float(live.get("open") or ltp)
            high = float(live.get("high") or ltp)
            low = float(live.get("low") or ltp)
            chg = float(live.get("dayChange") or (round(ltp - close, 2) if close else 0.0))
            pct = round((chg / close) * 100, 2) if close else 0.0
            return {
                "instrument": inst,
                "name": name,
                "exchange": "MCX",
                "segment": "COMMODITY",
                "last_price": ltp,
                "day_change": chg,
                "percent_change": f"{pct:+.2f}%",
                "ohlc": {"open": open_p, "high": high, "low": low, "close": close},
                "unit": unit,
                "retrieved_at": stamp,
                "source": url,
                "data_class": "UNVERIFIED_PROVIDER_DATA",
                "verification_status": "UNVERIFIED",
                "limitations": ["Live active futures contract feed from Groww MCX market page."],
            }
        except Exception as exc:
            logger.debug("Failed parsing direct futures for %s: %s", slug, exc)
            return None

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            res = list(filter(None, pool.map(_fetch_target, COMMODITY_FUTURES_TARGETS)))
        if any(r["instrument"] == "CRUDEOILMINI" for r in res):
            return res
    except Exception as exc:
        logger.warning("Direct groww futures fetch failed: %s", exc)

    return []


def fetch_official_groww_mcx_quote(trading_symbol: str | None = None, retrieved_at: datetime | None = None) -> dict | None:
    """Fetch live quote from Groww official Trading API for the active high-volume contract."""
    try:
        from app.db import get_session_factory
        from app.domain.tables import IntegrationCredential
        from app.integrations.crypto import decrypt_secrets
        from app.settings import Settings

        settings = Settings()
        session = get_session_factory()()
        try:
            row = session.get(IntegrationCredential, "groww")
            if not row or not row.ciphertext or not row.enabled:
                return None
            secrets = decrypt_secrets(settings, row.ciphertext)
            token = secrets.get("access_token")
            if not token:
                return None
        finally:
            session.close()

        candidates = [trading_symbol] if trading_symbol else ["CRUDEOILM19NOV26FUT", "CRUDEOILM19OCT26FUT"]
        best_quote = None
        best_vol = -1

        for sym in candidates:
            url = f"https://api.groww.in/v1/live-data/quote?exchange=MCX&segment=COMMODITY&trading_symbol={sym}"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-API-VERSION": "1.0",
                "User-Agent": "Mozilla/5.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=3.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "SUCCESS" and isinstance(data.get("payload"), dict):
                    p = data["payload"]
                    ltp = float(p.get("last_price") or 0)
                    vol = int(p.get("volume") or 0)
                    if ltp > 0 and vol > best_vol:
                        best_vol = vol
                        label = "19 Nov" if "NOV" in sym else "19 Oct" if "OCT" in sym else sym
                        # A missing change stays missing (never zero-filled)
                        chg = p.get("day_change")
                        pct = p.get("day_change_perc")
                        best_quote = {
                            "instrument": "CRUDEOILMINI",
                            "name": f"MCX Crude Oil Mini ({label})",
                            "trading_symbol": sym,
                            "exchange": "MCX",
                            "segment": "COMMODITY",
                            "last_price": ltp,
                            "day_change": float(chg) if isinstance(chg, (int, float)) else None,
                            "percent_change": f"{float(pct):+.2f}%" if isinstance(pct, (int, float)) else "N/A",
                            "ohlc": p.get("ohlc") or {},
                            "volume": vol,
                            "open_interest": p.get("open_interest"),
                            "unit": "₹/bbl",
                            "retrieved_at": (retrieved_at or datetime.now(timezone.utc)).isoformat(),
                            "source": f"GET /v1/live-data/quote ({sym})",
                            "data_class": "UNVERIFIED_PROVIDER_DATA",
                            "verification_status": "VERIFIED_STREAM",
                            "limitations": [f"Live active contract {sym} directly from Groww Official Trade API."],
                        }
            except Exception:
                pass

        return best_quote
    except Exception as exc:
        logger.debug("Official Groww MCX quote failed, falling back to direct contract: %s", exc)
    return None


def parse_mcx_commodities(html: str | None = None, retrieved_at: datetime | None = None) -> list[dict]:
    if html is None:
        direct = fetch_direct_groww_futures(retrieved_at)
        official = fetch_official_groww_mcx_quote(retrieved_at=retrieved_at)
        if official and direct:
            direct = [official if x.get("instrument") == "CRUDEOILMINI" else x for x in direct]
            return direct
        elif official:
            return [official]
        elif direct:
            return direct
        html = fetch_html("https://groww.in/commodities")
    if not html:
        return _fallback_commodities(retrieved_at)

    soup = BeautifulSoup(html, "html.parser")
    stamp = (retrieved_at or datetime.now(timezone.utc)).isoformat()

    # Extract live active futures prices directly from page links (Groww updates these in real time)
    slug_map = {
        "mcx_crudeoilm": "CRUDEOILMINI",
        "mcx_goldm": "GOLDMINI",
        "mcx_silverm": "SILVERMINI",
        "mcx_natgasmini": "NATURALGASMINI",
    }
    live_futures_prices: dict[str, float] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for slug, inst in slug_map.items():
            if f"/commodities/futures/{slug}" in href:
                txt = a.get_text(" ", strip=True)
                m = re.search(r"₹([\d,]+\.?\d*)", txt)
                if m and inst not in live_futures_prices:
                    try:
                        live_futures_prices[inst] = float(m.group(1).replace(",", ""))
                    except ValueError:
                        pass

    # 1. Primary: Extract from Groww NEXT_DATA JSON payload + live futures prices
    try:
        nxt = soup.find("script", id="__NEXT_DATA__")
        if nxt and nxt.string:
            data = json.loads(nxt.string)
            ticker = data.get("props", {}).get("pageProps", {}).get("commoditiesTickerData", [])
            sym_map = {
                "CRUDEOILM": ("CRUDEOILMINI", "MCX Crude Oil Mini", "₹/bbl"),
                "GOLDM": ("GOLDMINI", "MCX Gold Mini", "₹/10g"),
                "SILVERM": ("SILVERMINI", "MCX Silver Mini", "₹/kg"),
                "NATGASMINI": ("NATURALGASMINI", "MCX Natural Gas Mini", "₹/mmBtu"),
            }
            res = []
            for item in ticker:
                sym = item.get("symbol")
                if sym in sym_map:
                    mapped_inst, name, unit = sym_map[sym]
                    prev = float(item.get("lastDayClosePrice", 0))
                    # Prioritize live active futures price over static ticker spotPrice
                    spot = live_futures_prices.get(mapped_inst) or float(item.get("spotPrice", 0))
                    chg = round(spot - prev, 2) if prev else 0.0
                    pct = round((chg / prev) * 100, 2) if prev else 0.0
                    obj = {
                        "instrument": mapped_inst,
                        "name": name,
                        "exchange": "MCX",
                        "segment": "COMMODITY",
                        "last_price": spot,
                        "day_change": chg,
                        "percent_change": f"{pct:+.2f}%",
                        "ohlc": {"open": spot, "high": spot, "low": spot, "close": prev},
                        "unit": unit,
                        "retrieved_at": stamp,
                        "source": "https://groww.in/commodities",
                        "data_class": "UNVERIFIED_PROVIDER_DATA",
                        "verification_status": "UNVERIFIED",
                        "limitations": ["Spot / futures snapshot feed from Groww MCX market page (non-interval based)."],
                    }
                    res.append(obj)
            if res:
                return res
    except Exception as exc:
        logger.debug("Failed NEXT_DATA parse for commodities: %s", exc)

    found: dict[str, dict] = {}
    targets = [
        ("Crude Oil Mini", "CRUDEOILMINI", "MCX Crude Oil Mini", "₹/bbl"),
        ("Gold Mini", "GOLDMINI", "MCX Gold Mini", "₹/10g"),
        ("Silver Mini", "SILVERMINI", "MCX Silver Mini", "₹/kg"),
        ("Natural Gas Mini", "NATURALGASMINI", "MCX Natural Gas Mini", "₹/mmBtu"),
    ]

    for div in soup.find_all(["div", "a"]):
        txt = div.get_text(" ", strip=True)
        for name, sym, label, unit in targets:
            if name in txt and "₹" in txt and len(txt) < 80:
                m = re.search(r"₹([\d,]+\.?\d*)", txt)
                if m and sym not in found:
                    val = float(m.group(1).replace(",", ""))
                    found[sym] = {
                        "instrument": sym,
                        "name": label,
                        "exchange": "MCX",
                        "segment": "COMMODITY",
                        "last_price": val,
                        "unit": unit,
                        "retrieved_at": stamp,
                        "source": "https://groww.in/commodities",
                        "data_class": "UNVERIFIED_PROVIDER_DATA",
                        "verification_status": "UNVERIFIED",
                        "limitations": ["Spot / futures snapshot feed from Groww MCX market page (non-interval based)."],
                    }

    if not found:
        return []

    return list(found.values())


def _fallback_commodities(retrieved_at: datetime | None = None) -> list[dict]:
    """Return empty list when commodity retrieval fails. Do not invent prices."""
    return []


def fetch_live_usdinr(retrieved_at: datetime | None = None) -> dict | None:
    """Fetch live USD/INR FX spot/reference rate from public FX APIs."""
    stamp = (retrieved_at or datetime.now(timezone.utc)).isoformat()
    for url, source_label in [
        ("https://open.er-api.com/v6/latest/USD", "ExchangeRate-API Live FX"),
        ("https://api.frankfurter.app/latest?from=USD&to=INR", "ECB reference rate (via Frankfurter)"),
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            rate = (payload.get("rates") or {}).get("INR")
            if isinstance(rate, (int, float)) and rate > 0:
                return {
                    "instrument": "USDINR",
                    "name": "USD / INR Exchange Rate",
                    "segment": "GLOBAL_MARKET",
                    "last_price": round(float(rate), 2),
                    "day_change": None,  # the feed gives no change; unknown is not zero
                    "percent_change": "Live FX",
                    "unit": "INR/USD",
                    "retrieved_at": stamp,
                    "source": source_label,
                    "data_class": "UNVERIFIED_PROVIDER_DATA",
                    "verification_status": "UNVERIFIED",
                    "limitations": ["Public FX reference rate feed."],
                }
        except Exception as exc:
            logger.debug("FX fetch failed for %s: %s", url, exc)
    return None


def parse_global_indices(html: str | None = None, retrieved_at: datetime | None = None) -> list[dict]:
    is_live_fetch = html is None
    if html is None:
        html = fetch_html("https://groww.in/indices/global-indices/dow-jones")
    stamp = (retrieved_at or datetime.now(timezone.utc)).isoformat()
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 1. Primary: Extract from Groww NEXT_DATA JSON payload
    try:
        nxt = soup.find("script", id="__NEXT_DATA__")
        if nxt and nxt.string:
            data = json.loads(nxt.string)
            g = data.get("props", {}).get("pageProps", {}).get("globalIndicesData", {})
            insts = g.get("globalInstruments", [])
            sym_map = {
                "SGX NIFTY": ("GIFTNIFTY", "GIFT Nifty (NSE IX)"),
                "^DJI": ("DJI", "Dow Jones Industrial Average"),
                "DOW FUTURES": ("DOWFUTURES", "Dow Jones Futures"),
                "^N225": ("NIKKEI", "Nikkei 225 (Japan)"),
                "^HSI": ("HANGSENG", "Hang Seng (Hong Kong)"),
            }
            res = []
            for item in insts:
                det = item.get("instrumentDetailDto") or {}
                lp = item.get("livePriceDto") or {}
                sym = det.get("symbol")
                if sym in sym_map:
                    mapped, name = sym_map[sym]
                    val = float(lp.get("value", 0))
                    chg = float(lp.get("dayChange", 0))
                    pct = float(lp.get("dayChangePerc", 0))
                    res.append({
                        "instrument": mapped,
                        "name": name,
                        "segment": "GLOBAL_MARKET",
                        "last_price": val,
                        "day_change": chg,
                        "percent_change": f"{pct:+.2f}%",
                        "ohlc": {
                            "open": lp.get("open", val),
                            "high": lp.get("high", val),
                            "low": lp.get("low", val),
                            "close": lp.get("close", val),
                        },
                        "unit": "pts",
                        "retrieved_at": stamp,
                        "source": "https://groww.in/indices/global-indices/dow-jones",
                        "data_class": "UNVERIFIED_PROVIDER_DATA",
                        "verification_status": "UNVERIFIED",
                        "limitations": ["Global market snapshot from Groww portal (non-interval, snapshot quote)."],
                    })
            if res:
                if is_live_fetch:
                    fx = fetch_live_usdinr(retrieved_at)
                    if fx:
                        res.append(fx)
                return res
    except Exception as exc:
        logger.debug("Failed NEXT_DATA parse for global indices: %s", exc)

    found: dict[str, dict] = {}
    targets = [
        ("GIFT NIFTY", "GIFTNIFTY", "GIFT Nifty (NSE IX)", "pts"),
        ("Dow Futures", "DOW_FUT", "Dow Jones Futures", "pts"),
        ("Dow", "DJI", "Dow Jones Industrial Average", "pts"),
        ("NIKKEI", "NIKKEI", "Nikkei 225 (Japan)", "pts"),
        ("HANG SENG", "HANGSENG", "Hang Seng (Hong Kong)", "pts"),
    ]

    for div in soup.find_all("div"):
        txt = div.get_text(" ", strip=True)
        for name, sym, label, unit in targets:
            if name in txt and len(txt) < 80:
                m = re.search(rf"{re.escape(name)}\s+([\d,]+\.\d{{2}})\s+([+-]?[\d,]+\.\d{{2}})\s*\(\s*([+-]?[\d,]+\.\d{{2}}%)\s*\)", txt)
                if m and sym not in found:
                    val = float(m.group(1).replace(",", ""))
                    chg = float(m.group(2).replace(",", ""))
                    pct = m.group(3)
                    found[sym] = {
                        "instrument": sym,
                        "name": label,
                        "segment": "GLOBAL_MARKET",
                        "last_price": val,
                        "day_change": chg,
                        "percent_change": pct,
                        "unit": unit,
                        "retrieved_at": stamp,
                        "source": "https://groww.in/indices/global-indices/dow-jones",
                        "data_class": "UNVERIFIED_PROVIDER_DATA",
                        "verification_status": "UNVERIFIED",
                        "limitations": ["Global market snapshot from Groww portal (non-interval, snapshot quote)."],
                    }

    if not found:
        return []

    out = list(found.values())
    if is_live_fetch:
        fx = fetch_live_usdinr(retrieved_at)
        if fx:
            out.append(fx)
    return out


def _fallback_global_indices(retrieved_at: datetime | None = None) -> list[dict]:
    """Return empty list when global index retrieval fails. Do not invent prices."""
    return []


def parse_sectoral_indices(html: str | None = None, retrieved_at: datetime | None = None) -> list[dict]:
    if html is None:
        html = fetch_html("https://groww.in/indices")
    stamp = (retrieved_at or datetime.now(timezone.utc)).isoformat()
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 1. Primary: Extract from Groww NEXT_DATA JSON payload
    try:
        nxt = soup.find("script", id="__NEXT_DATA__")
        if nxt and nxt.string:
            data = json.loads(nxt.string)
            dto = data.get("props", {}).get("pageProps", {}).get("data", {}).get("aggregatedGlobalInstrumentDto", [])
            sym_map = {
                "NIFTY": ("NIFTY", "NIFTY 50", "INDIAN_MARKET"),
                "1": ("SENSEX", "BSE SENSEX", "INDIAN_MARKET"),
                "NIFTYMETAL": ("NIFTYMETAL", "NIFTY Metal", "INDIAN_MARKET"),
                "14": ("BANKEX", "BSE BANKEX", "INDIAN_MARKET"),
                "NIFTYIT": ("NIFTYIT", "NIFTY IT", "INDIAN_MARKET"),
                "INDIAVIX": ("VIX", "India VIX (Volatility Index)", "GLOBAL_MARKET"),
                "BANKNIFTY": ("BANKNIFTY", "NIFTY Bank", "INDIAN_MARKET"),
                "NIFTYAUTO": ("NIFTYAUTO", "NIFTY Auto", "INDIAN_MARKET"),
            }
            res = []
            for item in dto:
                det = item.get("instrumentDetailDto") or {}
                lp = item.get("livePriceDto") or {}
                sym = det.get("symbol")
                name_cand = det.get("name", "")
                if sym in sym_map or ("VIX" in (sym or "")) or ("VIX" in name_cand):
                    mapped, name, cat = sym_map.get(sym, ("VIX", "India VIX (Volatility Index)", "GLOBAL_MARKET"))
                    val = float(lp.get("value", 0))
                    chg = float(lp.get("dayChange", 0))
                    pct = float(lp.get("dayChangePerc", 0))
                    res.append({
                        "instrument": mapped,
                        "name": name,
                        "category": cat,
                        "last_price": val,
                        "day_change": chg,
                        "percent_change": f"{pct:+.2f}%",
                        "day_change_text": f"{chg:+.2f} ({pct:+.2f}%)",
                        "ohlc": {
                            "open": lp.get("open", val),
                            "high": lp.get("high", val),
                            "low": lp.get("low", val),
                            "close": lp.get("close", val),
                        },
                        "unit": "pts",
                        "retrieved_at": stamp,
                        "source": "https://groww.in/indices",
                        "data_class": "UNVERIFIED_PROVIDER_DATA",
                        "verification_status": "UNVERIFIED",
                        "limitations": ["Sectoral snapshot from Groww indices page."],
                    })
            if res:
                return res
    except Exception as exc:
        logger.debug("Failed NEXT_DATA parse for sectoral indices: %s", exc)

    found: dict[str, dict] = {}
    targets = {
        "NIFTY 50": ("NIFTY", "NIFTY 50", "pts", "INDIAN_MARKET"),
        "Bse Sensex": ("SENSEX", "BSE SENSEX", "pts", "INDIAN_MARKET"),
        "India Vix": ("VIX", "India VIX (Volatility Index)", "pts", "GLOBAL_MARKET"),
        "NIFTY Bank": ("BANKNIFTY", "NIFTY Bank", "pts", "INDIAN_MARKET"),
        "Bse Bankex": ("BANKEX", "BSE BANKEX", "pts", "INDIAN_MARKET"),
        "NIFTY IT": ("NIFTYIT", "NIFTY IT", "pts", "INDIAN_MARKET"),
        "NIFTY Auto": ("NIFTYAUTO", "NIFTY Auto", "pts", "INDIAN_MARKET"),
        "NIFTY Metal": ("NIFTYMETAL", "NIFTY Metal", "pts", "INDIAN_MARKET"),
    }

    for tr in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) >= 3:
            raw_name = cells[0].split("15 Oct")[0].split("23 Jan")[0].strip()
            for key, (sym, label, unit, cat) in targets.items():
                if key.casefold() in raw_name.casefold() and sym not in found:
                    try:
                        val = float(cells[1].replace(",", ""))
                        day_chg_raw = cells[2]
                        found[sym] = {
                            "instrument": sym,
                            "name": label,
                            "category": cat,
                            "last_price": val,
                            "day_change_text": day_chg_raw,
                            "unit": unit,
                            "retrieved_at": stamp,
                            "source": "https://groww.in/indices",
                            "data_class": "UNVERIFIED_PROVIDER_DATA",
                            "verification_status": "UNVERIFIED",
                            "limitations": ["Sectoral snapshot from Groww indices page."],
                        }
                    except ValueError:
                        pass

    if not found:
        return []

    return list(found.values())


def _fallback_sectoral_indices(retrieved_at: datetime | None = None) -> list[dict]:
    """Return empty list when sectoral index retrieval fails. Do not invent prices."""
    return []


def _price_direction(change: object) -> str:
    """UP / DOWN / FLAT from a day change; UNKNOWN when the change is missing or invalid."""
    if change is None or isinstance(change, bool):
        return "UNKNOWN"
    try:
        value = float(change)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if value != value:  # NaN
        return "UNKNOWN"
    return "UP" if value > 0 else "DOWN" if value < 0 else "FLAT"


def build_groww_market_observations(
    commodities: list[dict],
    global_indices: list[dict],
    sectoral_indices: list[dict],
) -> list[dict]:
    """Build analysis observation records from Groww commodities and global snapshots."""
    from app.instruments import CRUDE_FAMILY, canonical_underlying, is_vix_row
    import math

    obs = []
    for c in commodities:
        lp = c.get("last_price")
        if lp is None or not isinstance(lp, (int, float)) or not math.isfinite(lp) or lp <= 0:
            continue
        inst = canonical_underlying(c.get("instrument")) or c.get("instrument")
        chg = c.get("day_change")
        # price_direction is the commodity's own move; directional_implication is the
        # implication for Indian equities (rising crude is a headwind). Other commodities
        # have no established equity implication. A missing change is UNKNOWN, never 0.
        price_direction = _price_direction(chg)
        if str(inst or "").upper() in CRUDE_FAMILY:
            direction = {"UP": "BEARISH", "DOWN": "BULLISH"}.get(price_direction, "UNKNOWN")
        else:
            direction = "UNKNOWN"
        obs.append({
            "instrument": inst,
            "category": "MACRO",
            "claim": f"Groww MCX reported {c.get('name', inst)} price {lp} {c.get('unit', '')}.",
            "claim_type": "OBSERVATION",
            "source_name": c.get("source", "Groww MCX"),
            "provenance": "PROVIDER",
            "last_price": lp,
            "unit": c.get("unit"),
            "observed_at": c.get("retrieved_at"),
            "published_at": None,
            "retrieved_at": c.get("retrieved_at"),
            "freshness": "FRESH",
            "directional_implication": direction,
            "price_direction": price_direction,
            "time_horizon": "INTRADAY",
        })

    for g in global_indices:
        lp = g.get("last_price")
        if lp is None or not isinstance(lp, (int, float)) or not math.isfinite(lp) or lp <= 0:
            continue
        inst = g.get("instrument")
        price_direction = _price_direction(g.get("day_change"))
        if is_vix_row(g):
            # Rising volatility is risk-off for equities
            direction = {"UP": "BEARISH", "DOWN": "BULLISH"}.get(price_direction, "UNKNOWN")
        else:
            direction = {"UP": "BULLISH", "DOWN": "BEARISH"}.get(price_direction, "UNKNOWN")
        obs.append({
            "instrument": inst,
            "category": "GLOBAL_MARKET",
            "claim": f"Groww reported global benchmark {g.get('name', inst)} at {lp} {g.get('unit', 'pts')} ({g.get('percent_change', '')}).",
            "claim_type": "OBSERVATION",
            "source_name": g.get("source", "Groww Global"),
            "provenance": "PROVIDER",
            "last_price": lp,
            "unit": g.get("unit", "pts"),
            "observed_at": g.get("retrieved_at"),
            "published_at": None,
            "retrieved_at": g.get("retrieved_at"),
            "directional_implication": direction,
            "price_direction": price_direction,
            "time_horizon": "INTRADAY",
        })

    for s in sectoral_indices:
        lp = s.get("last_price")
        if lp is None or not isinstance(lp, (int, float)) or not math.isfinite(lp) or lp <= 0:
            continue
        inst = s.get("instrument")
        obs.append({
            "instrument": inst,
            "category": s.get("category", "INDIAN_MARKET"),
            "claim": f"Groww reported indicator {s.get('name', inst)} at {lp} {s.get('unit', 'pts')} ({s.get('day_change_text', '')}).",
            "claim_type": "OBSERVATION",
            "source_name": s.get("source", "Groww Indices"),
            "provenance": "PROVIDER",
            "last_price": lp,
            "unit": s.get("unit", "pts"),
            "observed_at": s.get("retrieved_at"),
            "published_at": None,
            "retrieved_at": s.get("retrieved_at"),
            "directional_implication": "UNKNOWN",
            "price_direction": _price_direction(s.get("day_change")),
            "time_horizon": "INTRADAY",
        })

    return obs
