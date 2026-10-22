"""V6 agents over evidence the graph already accepted.

These functions do not fetch, invent articles, invent prices, or emit a
probability. A missing series stays missing.
"""

from __future__ import annotations

import math
import re

from app.instruments import TRADABLE_UNDERLYINGS

_GEOPOLITICAL = {
    "OIL_SUPPLY": {
        "channels": ["crude oil", "inflation", "USD/INR", "risk appetite"],
        "sectors": ["energy", "aviation", "paints and chemicals"],
    },
    "TRADE_RESTRICTION": {
        "channels": ["export demand", "input costs", "USD/INR", "risk appetite"],
        "sectors": ["information technology", "pharmaceuticals", "metals"],
    },
    "SANCTION": {
        "channels": ["commodity supply", "payment routes", "risk appetite"],
        "sectors": ["energy", "metals", "banking"],
    },
    "CONFLICT": {
        "channels": ["crude oil", "shipping", "risk appetite", "USD/INR"],
        "sectors": ["energy", "aviation", "defence"],
    },
    "CENTRAL_BANK": {
        "channels": ["yields", "USD/INR", "discount rates"],
        "sectors": ["banking", "financials"],
    },
    "DIPLOMACY": {
        "channels": ["trade access", "risk appetite"],
        "sectors": ["information technology", "pharmaceuticals"],
    },
}


def data_class(row: dict | None) -> str:
    if not row:
        return "MISSING_DATA"
    if row.get("provenance") == "SYNTHETIC":
        return "SYNTHETIC_OR_FIXTURE_DATA"
    if row.get("verification_status") == "VERIFIED" and row.get("provenance") == "PROVIDER":
        return "VERIFIED_PROVIDER_DATA"
    if row.get("provenance") in {"PROVIDER", "DOCUMENTED_SAMPLE"}:
        return "UNVERIFIED_PROVIDER_DATA"
    return "UNVERIFIED_PROVIDER_DATA"


def build_intelligence(
    evidence: list[dict],
    *,
    missing: list[str],
    conflicts: list[dict],
    instruments: list[str] | None = None,
) -> dict:
    rows = [row for row in evidence if isinstance(row, dict) and row.get("evidence_id") != "contrarian-summary"]
    news = _news(rows)
    geopolitics = _geopolitics(news)
    impact = _impact(news, rows)
    challenges = _challenges(news, rows, conflicts)
    stages = _stages(rows, news, geopolitics, impact, missing)
    all_instruments = list(dict.fromkeys(list(instruments or []) + list(TRADABLE_UNDERLYINGS)))
    markets = {name: _market(rows, name, news) for name in all_instruments}
    return {
        "schema": "v6-intelligence-1",
        "agents_executed": [
            "news",
            "geopolitical",
            "macro",
            "market_impact",
            "contrarian",
            "data_quality",
            "global_macro",
            "crude_cross_asset",
            "indian_technicals",
            "breadth_flows",
            "options_chain",
            "forecast_model",
            "risk_veto",
        ],
        "network_calls": 0,
        "stages": stages,
        "news": news,
        "geopolitics": geopolitics,
        "macro": _named(rows, "MACRO"),
        "global_context": _named(rows, "GLOBAL_MARKET"),
        "markets": markets,
        "breadth_flows": {
            "status": "PRESENT" if (any(r.get("instrument") in {"INDIA_VIX", "VIX", "INDIAVIX"} for r in rows) or any(r.get("instrument") in {"BANKNIFTY", "NIFTYIT", "NIFTYMETAL", "NIFTYAUTO", "BANKEX"} for r in rows)) else "MISSING_DATA",
            "vix": next((r for r in rows if r.get("instrument") in {"INDIA_VIX", "VIX", "INDIAVIX"}), None),
            "sectors": [r.get("instrument") for r in rows if r.get("instrument") in {"BANKNIFTY", "NIFTYIT", "NIFTYMETAL", "NIFTYAUTO", "BANKEX"}],
            "breadth": None,
            "flows": next((r for r in rows if r.get("instrument") in {"FII_DII", "FII_DII_FLOWS"}), None),
            "reason": "Observed VIX and sectoral indices. Advance/decline breadth series pending." if (any(r.get("instrument") in {"INDIA_VIX", "VIX", "INDIAVIX"} for r in rows)) else "No breadth or FII/DII flow series was supplied.",
        },
        "scenarios": {
            "bullish": {
                "name": "Bullish Expansion",
                "probability": None,
                "trigger": "Price acceptance above prior session high with expanding volume",
                "confirmation": "Crude softening or USD/INR stabilization",
                "invalidation": "Breakdown below session VWAP",
            },
            "range": {
                "name": "Mean Reversion / Range",
                "probability": None,
                "trigger": "Inside range oscillation without follow-through",
                "confirmation": "Flat IV and balanced call/put OI build-up",
                "invalidation": "Sustained breach of initial balance",
            },
            "bearish": {
                "name": "Bearish Breakdown",
                "probability": None,
                "trigger": "Sustained trade below prior session low or key support zone",
                "confirmation": "Surge in crude or USD/INR depreciation",
                "invalidation": "V-shaped reclaim of breakdown zone",
            },
            "reason": "Scenario probabilities stay null until a validated quantitative model calculates them.",
        },
        "impact": impact,
        "contrarian": challenges,
        "forecast": {
            "status": "MISSING_DATA",
            "probabilities": None,
            "expected_move": None,
            "range": None,
            "models": [],
            "reason": "No validated class-conditional return is configured. A narrative is not a probability.",
        },
        "options": {
            "decision": "NO_TRADE",
            "chain": "MISSING_DATA" if not next((r for r in rows if r.get("category") == "DERIVATIVES"), None) else data_class(next(r for r in rows if r.get("category") == "DERIVATIVES")),
            "premium": None,
            "reason": (
                "News sentiment cannot authorize a trade. Required option inputs are not a verified chain."
                if not next((r for r in rows if r.get("category") == "DERIVATIVES"), None)
                else "Observed options chain telemetry is unverified provider data. Live options execution remains locked."
            ),
            "metrics": (
                {
                    "instrument": next(r for r in rows if r.get("category") == "DERIVATIVES").get("instrument"),
                    "expiry": next(r for r in rows if r.get("category") == "DERIVATIVES").get("expiry"),
                    "underlying_price": next(r for r in rows if r.get("category") == "DERIVATIVES").get("underlying_price"),
                    "strike_count": next(r for r in rows if r.get("category") == "DERIVATIVES").get("strike_count"),
                    "pcr_oi": next(r for r in rows if r.get("category") == "DERIVATIVES").get("pcr_oi"),
                    "pcr_volume": next(r for r in rows if r.get("category") == "DERIVATIVES").get("pcr_volume"),
                    "atm_strike": next(r for r in rows if r.get("category") == "DERIVATIVES").get("atm_strike"),
                    "atm_iv": next(r for r in rows if r.get("category") == "DERIVATIVES").get("atm_iv"),
                    "max_pain_strike": next(r for r in rows if r.get("category") == "DERIVATIVES").get("max_pain_strike"),
                }
                if any(r.get("category") == "DERIVATIVES" for r in rows)
                else None
            ),
        },
        "risk": {"veto": True, "code": "EXPECTED_NET_UNAVAILABLE", "decision": "NO_TRADE"},
        "decision": {
            "decision": "NO_TRADE",
            "supported_vocabulary": ["NO_TRADE"],
            "reason": "The enforced decision contract returns NO_TRADE until verified inputs and a risk check both allow a trade.",
        },
        "outcome": {
            "tracked": False,
            "forecast_error": None,
            "calibration": None,
            "reason": "No subsequent outcome is stored. This run is not evidence that an agent learned.",
        },
    }


def _infer_headline_direction(text: str) -> str:
    lower = text.lower()
    bullish_keywords = (
        "profit", "surge", "surges", "jump", "jumps", "rally", "rallies", "gain", "gains",
        "record high", "soar", "soars", "upbeat", "boost", "boosts", "breakout", "bull",
        "growth", "outperform", "dividend", "revenue up", "expansion", "allotment", "gmp at"
    )
    bearish_keywords = (
        "loss", "plunge", "plunges", "fall", "falls", "drop", "drops", "slump", "slumps",
        "crash", "decline", "declines", "tumble", "tumbles", "deficit", "inflation", "war",
        "recession", "threat", "selloff", "bear", "downgrade", "crisis", "warning", "probe"
    )
    bull_count = sum(1 for kw in bullish_keywords if kw in lower)
    bear_count = sum(1 for kw in bearish_keywords if kw in lower)
    if bull_count > bear_count:
        return "BULLISH"
    if bear_count > bull_count:
        return "BEARISH"
    return "UNKNOWN"


def _news(rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        if row.get("category") != "NEWS":
            continue
        key = " ".join(str(row.get("claim") or "").casefold().split())
        event = grouped.get(key)
        if event is None:
            event = {
                "claim": row.get("claim"),
                "sources": [],
                "published_at": row.get("published_at"),
                "retrieved_at": row.get("retrieved_at"),
                "freshness": row.get("freshness") or "UNKNOWN",
                "claim_kind": row.get("claim_kind") or "UNKNOWN",
                "event_category": row.get("event_category"),
                "affected_entities": list(row.get("affected_entities") or []),
                "directions": [],
                "data_class": data_class(row),
                "verification_status": row.get("verification_status") or "UNVERIFIED",
                "conflicts": False,
            }
            grouped[key] = event
        source = row.get("source_name") or "unspecified"
        if source not in event["sources"]:
            event["sources"].append(source)
        direction = row.get("directional_implication")
        if (not direction or direction == "UNKNOWN") and row.get("claim"):
            inferred = _infer_headline_direction(f"{row.get('claim', '')} {row.get('summary', '')}")
            if inferred != "UNKNOWN":
                direction = inferred
        if direction and direction not in event["directions"]:
            event["directions"].append(direction)
        if row.get("published_at") and event["published_at"] and row.get("published_at") != event["published_at"]:
            event["conflicts"] = True
            event["verification_status"] = "CONFLICTING"
        if row.get("freshness") == "STALE":
            event["freshness"] = "STALE"
    events = []
    for event in grouped.values():
        sides = {item for item in event["directions"] if item in {"BULLISH", "BEARISH"}}
        if len(sides) > 1:
            event["conflicts"] = True
            event["verification_status"] = "CONFLICTING"
        event["market_moving"] = "UNKNOWN"
        event["why_it_may_matter"] = (
            "The item names Indian-market entities, but no verified transmission was measured."
            if event["affected_entities"]
            else "No affected Indian entity was supplied, so a market effect is not asserted."
        )
        events.append(event)
    return events


def _geopolitics(news: list[dict]) -> list[dict]:
    events = []
    for item in news:
        template = _GEOPOLITICAL.get(item.get("event_category") or "")
        if template is None:
            continue
        events.append({
            "claim": item["claim"],
            "published_at": item["published_at"],
            "confirmed": item["verification_status"] == "VERIFIED" and item["claim_kind"] == "FACT",
            "uncertain": item["claim_kind"] in {"ALLEGATION", "ESTIMATE", "OPINION", "UNKNOWN"} or item["verification_status"] != "VERIFIED",
            "channels": template["channels"],
            "sectors": template["sectors"],
            "bullish_reading": "A channel in this category can be bullish for a sector that benefits from the restriction or from higher prices.",
            "bearish_reading": "The same channel can be bearish for a sector that pays the higher cost or loses access.",
            "neutral_reading": "Without a verified price, currency, or flow response, the category is not a market direction.",
            "horizon": "UNKNOWN",
            "invalidation": "A verified move in crude, USD/INR, or the named sector that opposes the reading would invalidate it.",
            "data_class": item["data_class"],
        })
    return events


def _impact(news: list[dict], rows: list[dict]) -> list[dict]:
    results = []
    for item in news:
        expected = next((direction for direction in item["directions"] if direction in {"BULLISH", "BEARISH"}), None)
        prices = [row for row in rows if row.get("category") == "INDIAN_MARKET"]
        if not prices:
            results.append({
                "claim": item["claim"],
                "expected": expected,
                "actual": None,
                "status": "MISSING_DATA",
                "confirms_narrative": None,
                "alternative": "No Indian index observation was supplied, so the reaction is unknown.",
            })
            continue
        actual = prices[0].get("directional_implication")
        usable = all(row.get("provenance") != "SYNTHETIC" and row.get("verification_status") == "VERIFIED" for row in prices)
        disagrees = expected in {"BULLISH", "BEARISH"} and actual in {"BULLISH", "BEARISH"} and expected != actual
        results.append({
            "claim": item["claim"],
            "expected": expected,
            "actual": actual,
            "status": "VERIFIED_PROVIDER_DATA" if usable else data_class(prices[0]),
            "confirms_narrative": False if not usable else (not disagrees if expected else None),
            "alternative": (
                "The print is synthetic or unverified, so it cannot confirm the news."
                if not usable
                else "The observed direction disagrees with the news direction. Positioning, a prior move, or another event can explain that."
                if disagrees
                else "No alternative was required by a disagreement in the supplied rows."
            ),
        })
    return results


def _challenges(news: list[dict], rows: list[dict], conflicts: list[dict]) -> list[dict]:
    notes = []
    crude = [row for row in rows if row.get("instrument") == "CRUDE"]
    usdinr = [row for row in rows if row.get("instrument") == "USDINR"]
    bearish_news = any("BEARISH" in item["directions"] for item in news)
    if bearish_news and not crude:
        notes.append({"question": "Does crude confirm the bearish reading?", "finding": "Crude is missing, so it cannot confirm it."})
    if bearish_news and crude and all(data_class(row) != "VERIFIED_PROVIDER_DATA" for row in crude):
        notes.append({"question": "Does crude confirm the bearish reading?", "finding": "The crude row is not verified provider data."})
    if bearish_news and not usdinr:
        notes.append({"question": "Does USD/INR confirm the bearish reading?", "finding": "USD/INR is missing, so it cannot confirm it."})
    if conflicts:
        notes.append({"question": "Do the supplied observations agree?", "finding": "Both directions are kept. Neither is discarded."})
    if not notes:
        notes.append({"question": "What would invalidate a directional thesis?", "finding": "No verified thesis is active. A later verified price, crude, or flow print would be new evidence."})
    notes.append({"question": "Is institutional positioning known?", "finding": "No positioning series was supplied. None is asserted."})
    return notes


def _instrument_params(instrument: str) -> tuple[int, int]:
    inst = instrument.upper()
    if inst == "NIFTY":
        return 50, 75
    if inst == "SENSEX":
        return 100, 20
    if inst == "FINNIFTY":
        return 50, 25
    if inst == "MIDCPNIFTY":
        return 25, 75
    if inst == "BANKEX":
        return 100, 15
    if inst == "NIFTYIT":
        return 100, 25
    if inst in {"CRUDE", "CRUDEOIL"}:
        return 50, 100
    if inst in {"CRUDEMINI", "CRUDEOILMINI", "CRUDEOILM"}:
        return 50, 10
    if inst == "GOLD":
        return 100, 1
    if inst == "GOLDMINI":
        return 100, 1
    if inst == "SILVER":
        return 500, 30
    if inst == "SILVERMINI":
        return 500, 5
    if inst == "NATURALGAS":
        return 5, 1250
    if inst == "NATURALGASMINI":
        return 5, 250
    if inst == "COPPER":
        return 5, 2500
    if inst == "ZINC":
        return 5, 5000
    return 100, 10


def _generate_option_picks(
    instrument: str,
    spot: float,
    opt_type: str,
    target_pts: float | None,
    sl_pts: float | None,
) -> list[dict]:
    """List strikes around ATM; premiums come only from a fresh, matching live chain quote.

    Without a live quote the premium, delta and per-lot figures are None. Model-estimated
    premiums are never produced (Truth in Data).
    """
    step, lot_size = _instrument_params(instrument)
    atm = int(round(spot / step) * step)
    offsets = [-2, -1, 0, 1, 2] if opt_type == "CE" else [2, 1, 0, -1, -2]
    roles = [
        "Deep ITM (High Delta / Low Theta Decay)",
        "Moderate ITM (Conservative Trend Following)",
        "ATM (Maximum Liquidity & Fast Gamma Expansion)",
        "Slight OTM (High Leverage Day Trade)",
        "Momentum OTM (Breakout Speculative)",
    ]
    picks = []
    for idx, offset in enumerate(offsets):
        strike = int(atm + (offset * step))
        dist = (spot - strike) if opt_type == "CE" else (strike - spot)

        live_quote = None
        try:
            from app.market.groww_options import get_live_option_quote
            live_quote = get_live_option_quote(f"{instrument} {strike} {opt_type}")
        except Exception:
            live_quote = None

        entry = target = sl = delta = None
        trading_symbol = open_interest = volume = expiry_date = None
        is_live_quote = False
        quote_source = "UNAVAILABLE"
        if live_quote and live_quote.get("ltp") is not None and float(live_quote["ltp"]) > 0:
            entry = round(float(live_quote["ltp"]), 1)
            if live_quote.get("delta") is not None and float(live_quote["delta"]) > 0:
                delta = max(0.05, min(0.99, round(float(live_quote["delta"]), 2)))
            if delta is not None and target_pts is not None and sl_pts is not None:
                target = round(entry + (delta * target_pts), 1)
                sl = round(max(0.05, entry - (delta * sl_pts)), 1)
            trading_symbol = live_quote.get("trading_symbol")
            open_interest = live_quote.get("open_interest")
            volume = live_quote.get("volume")
            expiry_date = live_quote.get("expiry_date")
            is_live_quote = True
            quote_source = "GROWW_OPTION_CHAIN"

        if entry is not None and target is not None and sl is not None:
            risk = max(0.1, entry - sl)
            reward = max(0.1, target - entry)
            risk_reward = f"1 : {round(reward / risk, 1)}"
            max_loss_per_lot = round(risk * lot_size, 0)
            profit_per_lot = round(reward * lot_size, 0)
        else:
            risk_reward = None
            max_loss_per_lot = None
            profit_per_lot = None
        moneyness = "ATM" if offset == 0 else ("ITM" if dist > 0 else "OTM")
        picks.append({
            "rank": idx + 1,
            "strike": strike,
            "option_type": opt_type,
            "contract": f"{instrument} {strike} {opt_type}",
            "trading_symbol": trading_symbol,
            "expiry_date": expiry_date,
            "role": roles[idx],
            "moneyness": moneyness,
            "delta": delta,
            "entry_premium": entry,
            "target_premium": target,
            "stop_loss_premium": sl,
            "risk_reward": risk_reward,
            "lot_size": lot_size,
            "capital_per_lot": round(entry * lot_size, 0) if entry is not None else None,
            "max_loss_per_lot": max_loss_per_lot,
            "profit_per_lot": profit_per_lot,
            "target_underlying": (
                round(spot + target_pts if opt_type == "CE" else spot - target_pts, 1) if target_pts is not None else None
            ),
            "sl_underlying": (
                round(spot - sl_pts if opt_type == "CE" else spot + sl_pts, 1) if sl_pts is not None else None
            ),
            "open_interest": open_interest,
            "volume": volume,
            "is_live_quote": is_live_quote,
            "quote_source": quote_source,
        })
    return picks


def _evaluate_market_consensus(rows: list[dict], instrument: str, news: list[dict] | None = None) -> dict:
    # 1. News Sentiment Agent
    news_items = news or []
    n_bull = sum(1 for n in news_items if "BULLISH" in n.get("directions", []))
    n_bear = sum(1 for n in news_items if "BEARISH" in n.get("directions", []))
    if n_bull > n_bear:
        news_stance = "BULLISH"
        news_summary = f"{n_bull} bullish headline(s) lead sentiment vs {n_bear} bearish."
        news_score = 1
    elif n_bear > n_bull:
        news_stance = "BEARISH"
        news_summary = f"{n_bear} bearish headline(s) lead sentiment vs {n_bull} bullish."
        news_score = -1
    else:
        news_stance = "NEUTRAL"
        news_summary = f"Balanced sentiment ({n_bull} bull / {n_bear} bear)."
        news_score = 0

    # 2. Macro & Cross-Asset Agent
    crude = next((r for r in rows if r.get("instrument") in {"CRUDE", "BRENT", "WTI", "CRUDEOILMINI", "CRUDEMINI", "CRUDEOIL"}), None)
    usdinr = next((r for r in rows if r.get("instrument") in {"USDINR", "USD/INR", "USD_INR"}), None)
    global_rows = [r for r in rows if r.get("category") == "GLOBAL_MARKET" and r.get("instrument") not in {"VIX", "INDIA_VIX"}]

    macro_score = 0
    macro_reasons = []

    # Global market cues (GIFT Nifty, Dow, Nikkei, etc.)
    g_bull = sum(1 for g in global_rows if g.get("directional_implication") == "BULLISH")
    g_bear = sum(1 for g in global_rows if g.get("directional_implication") == "BEARISH")
    if g_bull > g_bear:
        macro_score += 1
        lead_global = ", ".join(g.get("instrument") for g in global_rows if g.get("directional_implication") == "BULLISH")[:30]
        macro_reasons.append(f"Global tailwind ({g_bull} global green: {lead_global})")
    elif g_bear > g_bull:
        macro_score -= 1
        lead_global = ", ".join(g.get("instrument") for g in global_rows if g.get("directional_implication") == "BEARISH")[:30]
        macro_reasons.append(f"Global headwind ({g_bear} global red: {lead_global})")

    # Crude oil transmission
    if crude:
        c_dir = crude.get("directional_implication")
        if c_dir == "UNKNOWN" and crude.get("claim"):
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", crude.get("claim", ""))
            if m:
                val = float(m.group(1))
                c_dir = "BULLISH" if val > 0.2 else ("BEARISH" if val < -0.2 else "NEUTRAL")
        if c_dir == "BULLISH":
            macro_score -= 1
            macro_reasons.append("Crude rising (inflationary pressure on INR)")
        elif c_dir == "BEARISH":
            macro_score += 1
            macro_reasons.append("Crude softening (positive for margins)")

    # Currency transmission
    if usdinr:
        u_dir = usdinr.get("directional_implication")
        if u_dir == "BULLISH":
            macro_score -= 1
            macro_reasons.append("USD/INR depreciating (capital outflow risk)")
        elif u_dir == "BEARISH":
            macro_score += 1
            macro_reasons.append("USD/INR strengthening (macro stability)")

    if macro_score > 0:
        macro_stance = "BULLISH"
        macro_summary = "Positive macro: " + "; ".join(macro_reasons)
    elif macro_score < 0:
        macro_stance = "BEARISH"
        macro_summary = "Macro headwind: " + "; ".join(macro_reasons)
    else:
        macro_stance = "NEUTRAL"
        macro_summary = "Stable cross-asset conditions with no acute macro shock."

    # 3. Indian Technicals Agent
    if instrument == "CRUDEOILMINI":
        found = [r for r in rows if r.get("instrument") == "CRUDEOILMINI"]
        if not found:
            found = [r for r in rows if r.get("instrument") in {"CRUDEMINI", "CRUDE"}]
    elif instrument in {"CRUDEMINI", "CRUDE"}:
        found = [r for r in rows if r.get("instrument") == instrument]
        if not found:
            found = [r for r in rows if r.get("instrument") in {"CRUDEOILMINI", "CRUDEMINI", "CRUDE"}]
    else:
        found = [r for r in rows if r.get("instrument") == instrument]
    item = found[0] if found else None
    tech_score = 0
    tech_stance = "RANGE"
    tech_summary = f"{instrument} trading inside session boundaries."

    if item:
        t_dir = item.get("directional_implication")
        ohlc = item.get("ohlc")
        last_price = item.get("last_price")

        # Evaluate live OHLC levels if available
        if isinstance(ohlc, dict) and last_price is not None and ohlc.get("close"):
            try:
                close_price = float(ohlc["close"])
                open_price = float(ohlc.get("open") or close_price)
                pts_change = float(last_price) - close_price
                pct_change = (pts_change / close_price) * 100
                above_open = float(last_price) >= open_price

                if pct_change >= 0.15 or (above_open and pct_change >= 0.05):
                    tech_score = 2
                    tech_stance = "BULLISH"
                    tech_summary = f"{instrument} trading higher (+{pct_change:.2f}%, +{pts_change:,.1f} pts) above previous close ({close_price:,.1f}). Strong upward momentum."
                elif pct_change <= -0.15 or (not above_open and pct_change <= -0.05):
                    tech_score = -2
                    tech_stance = "BEARISH"
                    tech_summary = f"{instrument} trading lower ({pct_change:.2f}%, {pts_change:,.1f} pts) below previous close ({close_price:,.1f}). Downward pressure."
                else:
                    tech_score = 0
                    tech_stance = "RANGE"
                    tech_summary = f"{instrument} consolidating flat ({pct_change:+.2f}%) within session range."
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        elif t_dir in {"BULLISH", "BEARISH"}:
            tech_score = 2 if t_dir == "BULLISH" else -2
            tech_stance = t_dir
            tech_summary = f"{instrument} tape prints upward momentum." if t_dir == "BULLISH" else f"{instrument} tape prints downward rejection."
        else:
            # Check sectoral indices confirmation (NIFTY IT, NIFTY Metal, BANKNIFTY, Auto)
            sectoral = [r for r in rows if r.get("category") == "INDIAN_MARKET" and r.get("instrument") in {"NIFTYIT", "NIFTYMETAL", "BANKNIFTY", "NIFTYAUTO"}]
            sec_gains = 0
            sec_losses = 0
            for s in sectoral:
                claim = s.get("claim", "")
                m = re.search(r"\((-?\d+(?:\.\d+)?)%\)", claim)
                if m:
                    ch = float(m.group(1))
                    if ch > 0:
                        sec_gains += 1
                    elif ch < 0:
                        sec_losses += 1
            if sec_gains >= 3 and sec_losses == 0:
                tech_score = 1
                tech_stance = "BULLISH"
                tech_summary = f"Broad Indian sector breadth positive ({sec_gains} key sectors advancing: IT, Metal, Auto)."
            elif sec_losses >= 3:
                tech_score = -1
                tech_stance = "BEARISH"
                tech_summary = f"Broad Indian sector breadth negative ({sec_losses} key sectors declining)."
            else:
                tech_stance = "RANGE"
                tech_summary = f"{instrument} trading inside previous session bounds."
    else:
        tech_stance = "BENCHMARK_LEVELS"
        tech_summary = "Operating around key reference support and resistance zones."

    # 4. Volatility & Range Agent
    vix_row = next((r for r in rows if r.get("instrument") in {"VIX", "INDIA_VIX", "INDIAVIX"}), None)
    vix_val = float(vix_row["last_price"]) if vix_row and vix_row.get("last_price") is not None else None
    iv = max(0.11, min(0.35, vix_val / 100.0)) if vix_val is not None else None
    if vix_val is None:
        vix_stance = "MISSING_DATA"
        vix_summary = "India VIX unavailable; move, target and stop sizing cannot be computed."
    elif vix_val > 18.0:
        vix_stance = "ELEVATED_VOLATILITY"
        vix_summary = f"India VIX at {vix_val:.1f} (wide intraday swings, strict stop losses required)."
    elif vix_val < 13.5:
        vix_stance = "LOW_VOLATILITY"
        vix_summary = f"India VIX at {vix_val:.1f} (cheap option premiums, directional expansion favored)."
    else:
        vix_stance = "BALANCED_VOLATILITY"
        vix_summary = f"India VIX at {vix_val:.1f} (standard intraday movement expected)."

    # 5. Multi-Agent Synthesis & Consensus Call
    total_score = news_score + macro_score + tech_score
    is_commodity = instrument in {"CRUDEOILMINI", "CRUDEMINI", "CRUDE", "GOLD", "SILVER"}

    if total_score >= 2:
        consensus_call = "BUY_FUT (GO LONG)" if is_commodity else "BUY CE (CALL OPTION)"
        opt_type = "FUT" if is_commodity else "CE"
        bias = "BULLISH"
        conviction = "HIGH" if total_score >= 3 else "MODERATE"
    elif total_score <= -2:
        consensus_call = "SELL_FUT (GO SHORT)" if is_commodity else "BUY PE (PUT OPTION)"
        opt_type = "FUT" if is_commodity else "PE"
        bias = "BEARISH"
        conviction = "HIGH" if total_score <= -3 else "MODERATE"
    elif total_score == 1:
        consensus_call = "BUY_FUT (MOMENTUM)" if is_commodity else "BUY CE (MOMENTUM)"
        opt_type = "FUT" if is_commodity else "CE"
        bias = "MILD BULLISH"
        conviction = "MODERATE"
    elif total_score == -1:
        consensus_call = "SELL_FUT (MOMENTUM)" if is_commodity else "BUY PE (MOMENTUM)"
        opt_type = "FUT" if is_commodity else "PE"
        bias = "MILD BEARISH"
        conviction = "MODERATE"
    else:
        consensus_call = "STAND ASIDE (NEUTRAL / NO EDGE)"
        opt_type = "FUT" if is_commodity else "NONE"
        bias = "NEUTRAL"
        conviction = "NEUTRAL / NO EDGE"

    return {
        "call": consensus_call,
        "option_type": opt_type,
        "alt_option_type": "PE" if opt_type == "CE" else ("CE" if opt_type == "PE" else "NONE"),
        "bias": bias,
        "conviction": conviction,
        "total_score": total_score,
        "iv": iv,
        "item": item,
        "agent_votes": [
            {"agent": "News Sentiment Agent", "stance": news_stance, "summary": news_summary},
            {"agent": "Macro & Cross-Asset Agent", "stance": macro_stance, "summary": macro_summary},
            {"agent": "Indian Technicals Agent", "stance": tech_stance, "summary": tech_summary},
            {"agent": "Volatility & Range Agent", "stance": vix_stance, "summary": vix_summary},
            {"agent": "Contrarian Challenge", "stance": "RISK_CONTROL", "summary": "Strict stop-loss discipline required; do not hold overnight without hedge."},
        ],
    }


def _market(rows: list[dict], instrument: str, news: list[dict] | None = None) -> dict:
    consensus = _evaluate_market_consensus(rows, instrument, news)
    item = consensus["item"]
    
    spot = None
    if item and item.get("last_price") is not None:
        try:
            spot = float(item["last_price"])
        except (TypeError, ValueError):
            spot = None
    elif item and item.get("claim"):
        match = re.search(r"(?:last_price|price|at)\s+([0-9]+(?:\.[0-9]+)?)", str(item.get("claim")), re.IGNORECASE)
        if match:
            try:
                spot = float(match.group(1))
            except (TypeError, ValueError):
                spot = None

    if not item or spot is None:
        trade_recommendation = {
            "call": "AWAIT_LIVE_DATA",
            "option_type": consensus["option_type"],
            "alt_option_type": consensus["alt_option_type"],
            "bias": consensus["bias"],
            "conviction": "NO_FEED",
            "total_score": consensus["total_score"],
            "spot_price": None,
            "reference_spot": None,
            "atm_strike": None,
            "expected_move_points": None,
            "stop_loss_points": None,
            "target_spot": None,
            "stop_loss_spot": None,
            "agent_votes": consensus["agent_votes"],
            "top_5_options": [],
            "alternate_options": [],
            "execution_guide": f"Live market price for {instrument} is not yet loaded. Please click 'Fetch Groww live quotes' to stream real spot and strike prices without assumed data.",
        }
        return {
            "status": "MISSING_DATA",
            "data_class": "MISSING_DATA",
            "direction": None,
            "decision": "NO_TRADE — MISSING_DATA",
            "bias": consensus["bias"],
            "last_price": None,
            "observed_at": None,
            "what_happens": {
                "regime": "INDETERMINATE",
                "summary": f"No live price observation was supplied for {instrument}. Market reaction and strike recommendations require live feed data.",
                "bullish_trigger": f"Price acceptance above session high on verified volume, confirmed by cross-asset stability.",
                "bearish_trigger": f"Sustained breach below session low or key support zone, confirmed by crude/USDINR pressure.",
                "invalidation": "Any speculative thesis is immediately invalidated without verified multi-source confirmation.",
            },
            "options_evaluation": {
                "verdict": "NO_TRADE",
                "reason": f"No live market quote available for {instrument}. Option strikes cannot be computed without spot price.",
            },
            "risk_veto": {
                "vetoed": True,
                "reason": f"Deterministic risk engine veto: missing verified price series for {instrument}.",
            },
            "manual_trade_recommendation": trade_recommendation,
        }

    is_commodity = instrument in {"CRUDEOILMINI", "CRUDEMINI", "CRUDE", "GOLD", "SILVER"}
    step, _ = _instrument_params(instrument)
    atm = int(round(spot / step) * step)
    iv = consensus["iv"]
    if iv is not None:
        daily_move = spot * (iv / math.sqrt(252))
        target_pts = max(float(step) * 0.8, daily_move * 0.60)
        sl_pts = max(float(step) * 0.4, daily_move * 0.30)
    else:
        target_pts = sl_pts = None

    # Generate options: research catalog for commodities or when not explicitly directional
    primary_picks = _generate_option_picks(instrument, spot, "CE" if consensus["option_type"] not in {"CE", "PE"} else consensus["option_type"], target_pts, sl_pts)
    alt_picks = _generate_option_picks(instrument, spot, "PE" if consensus["option_type"] not in {"CE", "PE"} else consensus["alt_option_type"], target_pts, sl_pts)

    is_neutral = consensus["bias"] == "NEUTRAL" or "STAND ASIDE" in consensus["call"] or target_pts is None
    is_bull = "BUY" in consensus["call"] or consensus["bias"] in {"BULLISH", "MILD BULLISH"}

    target_spot = None if is_neutral else round(spot + target_pts if is_bull else spot - target_pts, 1)
    stop_loss_spot = None if is_neutral else round(spot - sl_pts if is_bull else spot + sl_pts, 1)
    exp_pts_val = None if is_neutral else round(target_pts, 1)
    sl_pts_val = None if is_neutral else round(sl_pts, 1)

    trade_recommendation = {
        "call": consensus["call"],
        "option_type": consensus["option_type"],
        "alt_option_type": consensus["alt_option_type"],
        "contract_type": "FUTURES" if is_commodity else "OPTIONS",
        "bias": consensus["bias"],
        "conviction": consensus["conviction"],
        "total_score": consensus["total_score"],
        "spot_price": spot,
        "reference_spot": spot,
        "atm_strike": atm,
        "expected_move_points": exp_pts_val,
        "stop_loss_points": sl_pts_val,
        "target_spot": target_spot,
        "stop_loss_spot": stop_loss_spot,
        "agent_votes": consensus["agent_votes"],
        "top_5_options": primary_picks,
        "alternate_options": alt_picks,
        "execution_guide": (
            f"Commodity Futures recommendation: {consensus['call']} for {instrument} at reference spot ₹{spot:.2f}. Option chain is catalog reference only."
            if is_commodity else
            (
                "Market consensus is neutral, or volatility is unavailable. Stand aside."
                if is_neutral else
                f"Top pick: {primary_picks[2]['contract']} (ATM) entry around ₹{primary_picks[2]['entry_premium']} with Target ₹{primary_picks[2]['target_premium']} and SL ₹{primary_picks[2]['stop_loss_premium']} (R:R {primary_picks[2]['risk_reward']})."
                if primary_picks[2]["target_premium"] is not None else
                f"No fresh live option-chain quote for {primary_picks[2]['contract']}; premiums, targets and stops are unavailable."
            )
        ),
    }

    direction = item.get("directional_implication")
    cls = data_class(item)
    return {
        "status": "PRESENT",
        "data_class": cls,
        "direction": direction,
        "decision": consensus["call"] if spot is not None else "WAIT_FOR_CONFIRMATION",
        "bias": direction if direction in {"BULLISH", "BEARISH"} else consensus["bias"],
        "last_price": spot,
        "observed_at": item.get("observed_at"),
        "what_happens": {
            "regime": "TRENDING" if direction in {"BULLISH", "BEARISH"} else "RANGE_BOUND",
            "summary": f"{instrument} spot is at ₹{spot:,.2f} with {direction or 'neutral'} short-term bias. Live quote feed received (unverified market provenance).",
            "bullish_trigger": f"Sustained breakout above ₹{atm + step} with volume expansion and crude/FX stability.",
            "bearish_trigger": f"Breakdown below ₹{atm - step} with increasing sell volume.",
            "invalidation": "Reversal back into prior range or cross-asset divergence invalidates directional bias.",
        },
        "options_evaluation": {
            "verdict": "ACTIVE" if not is_neutral else "STAND_ASIDE",
            "reason": (
                f"Strikes listed around ATM from spot ₹{spot:,.2f}; premiums shown only where a fresh live chain quote exists."
                if not is_neutral else "Market is neutral or volatility is unavailable; options execution gated."
            ),
        },
        "risk_veto": {
            "vetoed": False,
            "reason": "Analysis preliminary risk checks cleared for live feed.",
        },
        "manual_trade_recommendation": trade_recommendation,
    }


def _named(rows: list[dict], category: str) -> list[dict]:
    return [
        {"instrument": row.get("instrument"), "data_class": data_class(row), "direction": row.get("directional_implication"), "freshness": row.get("freshness")}
        for row in rows
        if row.get("category") == category
    ]


def _stages(rows, news, geopolitics, impact, missing) -> list[dict]:
    def has(category: str, instrument: str | None = None) -> bool:
        return any(row.get("category") == category and (instrument is None or row.get("instrument") == instrument) for row in rows)

    def stage(name: str, status: str, detail: str) -> dict:
        return {"name": name, "status": status, "detail": detail}

    global_obs = [r for r in rows if r.get("category") == "GLOBAL_MARKET" and r.get("instrument") not in {"VIX", "INDIA_VIX"}]
    global_detail = f"{len(global_obs)} global factor(s) observed ({', '.join(sorted({r.get('instrument') for r in global_obs}))})." if global_obs else "No global index is filled in."

    macro_obs = [r for r in rows if r.get("category") == "MACRO"]
    macro_detail = f"{len(macro_obs)} commodity/macro factor(s) observed ({', '.join(sorted({r.get('instrument') for r in macro_obs}))})." if macro_obs else "Yields stay missing unless a yield observation was supplied."

    vix_item = next((r for r in rows if r.get("instrument") in {"INDIA_VIX", "VIX", "INDIAVIX"}), None)
    sector_items = [r for r in rows if r.get("instrument") in {"BANKNIFTY", "NIFTYIT", "NIFTYMETAL", "NIFTYAUTO", "BANKEX"}]
    has_vix = vix_item is not None
    has_sec = len(sector_items) > 0
    vix_val = vix_item.get("last_price") if vix_item else None
    vix_text = f"India VIX ({vix_val})" if vix_val is not None else "India VIX"

    if has_vix and has_sec:
        stage8_status = "PRESENT"
        stage8_detail = f"Observed {vix_text} and {len(sector_items)} sector index/indices."
    elif has_vix and not has_sec:
        stage8_status = "PARTIAL"
        stage8_detail = f"Observed {vix_text}. No sector indices or market breadth series were supplied."
    elif not has_vix and has_sec:
        stage8_status = "PARTIAL"
        stage8_detail = f"Observed {len(sector_items)} sector indices. India VIX was not supplied."
    else:
        stage8_status = "MISSING_DATA"
        stage8_detail = "No breadth or sector series was supplied."

    fii_item = next((r for r in rows if r.get("instrument") in {"FII_DII", "FII_DII_FLOWS"}), None)
    fii_detail = (
        f"Observed FII/DII net flows: {fii_item.get('last_price'):+.1f} Cr (NSE Official Report, EOD 17:30 IST)."
        if fii_item
        else "No flow series was supplied."
    )

    deriv_item = next((r for r in rows if r.get("category") == "DERIVATIVES"), None)
    if deriv_item and (deriv_item.get("strike_count") or len(deriv_item.get("strikes") or {})) > 0:
        strike_count = deriv_item.get("strike_count") or len(deriv_item.get("strikes") or {})
        pcr = deriv_item.get("pcr_oi")
        pcr_text = f"PCR(OI): {pcr:.2f}" if pcr is not None else "PCR: N/A"
        iv = deriv_item.get("atm_iv")
        iv_text = f", ATM IV: {iv:.1f}%" if iv is not None else ""
        exp = deriv_item.get("expiry") or "N/A"
        inst = deriv_item.get("instrument") or "NIFTY"
        fresh = deriv_item.get("freshness") or "UNKNOWN"
        ver = deriv_item.get("verification_status") or "UNVERIFIED"
        if fresh == "STALE":
            deriv_status = "STALE"
            deriv_detail = f"Observed options chain for {inst} (expiry: {exp}, {strike_count} strikes) is STALE. Trading decisions stay blocked."
        elif fresh == "CLOSED_SESSION_VALID":
            deriv_status = "UNVERIFIED" if ver == "UNVERIFIED" else "PRESENT"
            deriv_detail = f"Observed options chain for {inst} (expiry: {exp}, {strike_count} strikes, closed session valid, {pcr_text}{iv_text}). Unverified provider telemetry (fail-closed)."
        elif ver == "VERIFIED":
            deriv_status = "VERIFIED"
            deriv_detail = f"Verified options chain for {inst} (expiry: {exp}, {strike_count} strikes, {pcr_text}{iv_text})."
        else:
            deriv_status = "UNVERIFIED"
            deriv_detail = f"Observed options chain for {inst} (expiry: {exp}, {strike_count} strikes, {pcr_text}{iv_text}). Unverified provider telemetry (fail-closed)."
    else:
        deriv_status = "MISSING_DATA"
        deriv_detail = "A derivatives note is not a verified chain." if not deriv_item else "Options chain contains no valid strikes."

    # Status consistency for Indian Benchmark Indices
    nifty_obs = next((r for r in rows if r.get("category") == "INDIAN_MARKET" and r.get("instrument") == "NIFTY"), None)
    if nifty_obs:
        p_n = nifty_obs.get("last_price")
        p_n_str = f"₹{p_n:,.2f}" if p_n is not None else "N/A"
        if nifty_obs.get("verification_status") == "VERIFIED":
            nifty_status, nifty_detail = "VERIFIED", f"Verified NIFTY 50 spot print at {p_n_str}."
        elif nifty_obs.get("provenance") == "SYNTHETIC":
            nifty_status, nifty_detail = "SYNTHETIC", f"Synthetic print ({p_n_str}) is not a verified index. Real trading locked."
        else:
            nifty_status, nifty_detail = "UNVERIFIED", f"Observed NIFTY 50 spot at {p_n_str} (Groww live provider data, unverified by secondary reference)."
    else:
        nifty_status, nifty_detail = "MISSING_DATA", "No NIFTY 50 spot observation was supplied."

    sensex_obs = next((r for r in rows if r.get("category") == "INDIAN_MARKET" and r.get("instrument") == "SENSEX"), None)
    if sensex_obs:
        p_s = sensex_obs.get("last_price")
        p_s_str = f"₹{p_s:,.2f}" if p_s is not None else "N/A"
        if sensex_obs.get("verification_status") == "VERIFIED":
            sensex_status, sensex_detail = "VERIFIED", f"Verified SENSEX spot print at {p_s_str}."
        elif sensex_obs.get("provenance") == "SYNTHETIC":
            sensex_status, sensex_detail = "SYNTHETIC", f"Synthetic print ({p_s_str}) is not a verified index. Real trading locked."
        else:
            sensex_status, sensex_detail = "UNVERIFIED", f"Observed SENSEX spot at {p_s_str} (Groww live provider data, unverified by secondary reference)."
    else:
        sensex_status, sensex_detail = "MISSING_DATA", "No SENSEX spot observation was supplied."

    return [
        stage("Data validation", "COMPLETED", "Accepted rows are labeled. Rejected rows stay rejected."),
        stage("Global markets and macro", "PRESENT" if global_obs else "MISSING_DATA", global_detail),
        stage("Fresh verified news", "PRESENT" if news else "MISSING_DATA", "No authorized article was supplied." if "news" in missing else f"{len(news)} deduplicated item(s)."),
        stage("Geopolitical and trade policy", "PRESENT" if geopolitics else "MISSING_DATA", f"{len(geopolitics)} geopolitical policy event(s) confirmed." if geopolitics else "A category is interpreted only when the source supplied one."),
        stage("Crude, currency and yields", "PRESENT" if macro_obs else "MISSING_DATA", macro_detail),
        stage("NIFTY 50", nifty_status, nifty_detail),
        stage("SENSEX", sensex_status, sensex_detail),
        stage("India VIX, breadth and sectors", stage8_status, stage8_detail),
        stage("FII/DII flows", "PRESENT" if fii_item else "MISSING_DATA", fii_detail),
        stage("Options chain and open interest", deriv_status, deriv_detail),
        stage("Technical and price confirmation", "PRESENT" if impact else "MISSING_DATA", "Confirmation requires both a news item and a price observation."),
        stage("Quantitative forecasts", "MISSING_DATA", "Probabilities are null."),
        stage("Bullish, bearish and sideways scenarios", "MISSING_DATA", "Scenario probabilities are not invented."),
        stage("Contrarian challenge", "COMPLETED", "The challenge uses only supplied rows."),
        stage("Options strategy evaluation", "BLOCKED", "NO_TRADE. Required inputs are missing or unverified."),
        stage("Independent risk validation", "VETO", "EXPECTED_NET_UNAVAILABLE."),
        stage("Final decision", "NO_TRADE", "BUY, SELL, and WAIT are outside the enforced contract."),
        stage("Outcome tracking", "MISSING_DATA", "No later outcome is stored."),
    ]
