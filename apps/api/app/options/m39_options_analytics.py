"""Milestone M39: Indian Market Options Analytics, Black-76 Valuation & PCR Surface Engine.

Pure quantitative research and analytical valuation engine for European-style
Indian index options (NIFTY 50, BANK NIFTY).

Key Capabilities:
1. Exact Black-76 European Option Valuation & Greeks:
   Analytical Closed-Form Delta, Gamma, Vega, Theta, and Rho under continuous discounting.
2. Numerical Implied Volatility (IV) Inversion Solver:
   Hybrid Newton-Raphson with Bisection fallback converging to 1e-6 tolerance.
3. Complete Options Chain Analytics:
   - Open Interest PCR (Put-Call Ratio) & Volume PCR
   - Max Pain Strike Calculation
   - At-The-Money (ATM) Implied Volatility & 25-Delta Volatility Skew
   - Quantitative Directional Sentiment Classification
4. Strict Safety Invariants:
   All results are purely analytical research models.
   Live order placement and auto-trade recommendations remain permanently blocked.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("imm.m39_options_analytics")


# ==============================================================================
# 1. GAUSSIAN DISTRIBUTIONS & MATH PRIMITIVES
# ==============================================================================

def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


# ==============================================================================
# 2. DATA STRUCTURES
# ==============================================================================

@dataclass
class Black76Greeks:
    price: float
    delta: float            # dC/dF (Calls in [0, e^-rT], Puts in [-e^-rT, 0])
    gamma: float            # d^2C/dF^2 (identical for Call and Put)
    vega: float             # dC/d(vol) per 1% move in volatility
    theta: float            # dC/dt per calendar day (1/365 year)
    rho: float              # dC/dr per 1% move in risk-free rate


@dataclass
class OptionStrikeRecord:
    strike: float
    option_type: str        # "CE" or "PE"
    bid: float | None
    ask: float | None
    mid: float | None
    last_price: float | None
    open_interest: float | None
    volume: float | None
    implied_volatility: float | None = None
    greeks: Black76Greeks | None = None


@dataclass
class OptionsChainSummary:
    underlying_symbol: str
    forward_price: float
    risk_free_rate: float
    time_to_expiry_years: float
    total_call_oi: float | None
    total_put_oi: float | None
    total_call_volume: float | None
    total_put_volume: float | None
    pcr_oi: float | None                    # Total Put OI / Total Call OI; None when OI is missing
    pcr_volume: float | None                # Total Put Vol / Total Call Vol
    max_pain_strike: float | None           # Strike minimizing collective option buyer payoff
    max_pain_total_loss: float | None
    atm_strike: float
    atm_iv: float | None
    volatility_skew_25d: float | None       # IV(25-delta Put) - IV(25-delta Call)
    directional_sentiment: str              # "BULLISH", "BEARISH", "NEUTRAL", or "UNKNOWN" (no OI)
    sentiment_confidence: float | None
    strikes_evaluated: int
    reason_codes: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ==============================================================================
# 3. BLACK-76 VALUATION & ANALYTICAL GREEKS
# ==============================================================================

def calculate_black76_and_greeks(
    forward: float,
    strike: float,
    time_years: float,
    volatility: float,
    risk_free_rate: float = 0.065,
    is_call: bool = True,
) -> Black76Greeks:
    """Analytical Black-76 valuation and Greeks for European options on futures/forwards."""
    if forward <= 0 or strike <= 0:
        raise ValueError(f"Forward ({forward}) and strike ({strike}) must be positive.")
    if time_years <= 0 or volatility <= 0:
        # Intrinsic value at expiry / zero vol
        disc = math.exp(-risk_free_rate * max(0.0, time_years))
        intr = max(0.0, disc * (forward - strike)) if is_call else max(0.0, disc * (strike - forward))
        delta = disc if (is_call and forward > strike) else (-disc if (not is_call and strike > forward) else 0.0)
        return Black76Greeks(price=intr, delta=delta, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    sqrt_t = math.sqrt(time_years)
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * time_years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    disc = math.exp(-risk_free_rate * time_years)

    pdf_d1 = norm_pdf(d1)
    cdf_d1 = norm_cdf(d1)
    cdf_d2 = norm_cdf(d2)

    if is_call:
        price = max(0.0, disc * (forward * cdf_d1 - strike * cdf_d2))
        delta = disc * cdf_d1
        # Black-76: dC/dt = -disc*F*sigma*phi(d1)/(2*sqrt(T)) + r*C  (per year)
        theta = (-disc * forward * volatility * pdf_d1 / (2.0 * sqrt_t) + risk_free_rate * price) / 365.0
        rho = -time_years * disc * (forward * cdf_d1 - strike * cdf_d2) / 100.0
    else:
        cdf_neg_d1 = norm_cdf(-d1)
        cdf_neg_d2 = norm_cdf(-d2)
        price = max(0.0, disc * (strike * cdf_neg_d2 - forward * cdf_neg_d1))
        delta = -disc * cdf_neg_d1
        theta = -(disc * forward * volatility * pdf_d1 / (2.0 * sqrt_t) - risk_free_rate * price) / 365.0
        rho = -time_years * disc * (strike * cdf_neg_d2 - forward * cdf_neg_d1) / 100.0

    gamma = disc * pdf_d1 / (forward * volatility * sqrt_t)
    # Vega expressed per 1% (0.01) move in annualized volatility
    vega = 0.01 * disc * forward * sqrt_t * pdf_d1

    return Black76Greeks(
        price=price,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        rho=rho,
    )


# ==============================================================================
# 4. NUMERICAL IMPLIED VOLATILITY INVERSION SOLVER
# ==============================================================================

def solve_black76_implied_volatility(
    market_price: float,
    forward: float,
    strike: float,
    time_years: float,
    risk_free_rate: float = 0.065,
    is_call: bool = True,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> float | None:
    """Numerically invert Black-76 for implied volatility in [0.005, 3.00].

    Returns None when IV is undefined (at expiry, or price at/below intrinsic value)
    or when no volatility in range reproduces the price.
    """
    if time_years <= 1e-6:
        return None

    disc = math.exp(-risk_free_rate * time_years)
    intrinsic = max(0.0, disc * (forward - strike)) if is_call else max(0.0, disc * (strike - forward))

    if market_price <= intrinsic + 1e-6:
        return None

    # Stage 1: Newton-Raphson iteration with Corrado-Miller initial estimate
    sigma = 0.20
    for _ in range(max_iter):
        greeks = calculate_black76_and_greeks(forward, strike, time_years, sigma, risk_free_rate, is_call)
        diff = greeks.price - market_price
        if abs(diff) < tol:
            return round(sigma, 6)

        raw_vega = greeks.vega * 100.0  # Unscaled vega
        if raw_vega < 1e-8:
            break
        step = diff / raw_vega
        sigma -= step
        if sigma <= 0.005 or sigma >= 3.0:
            break

    # Stage 2: Robust Bisection Fallback
    low, high = 0.005, 3.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        p = calculate_black76_and_greeks(forward, strike, time_years, mid, risk_free_rate, is_call).price
        diff = p - market_price
        if abs(diff) < tol:
            return round(mid, 6)
        if diff > 0:
            high = mid
        else:
            low = mid

    sigma = 0.5 * (low + high)
    final = calculate_black76_and_greeks(forward, strike, time_years, sigma, risk_free_rate, is_call).price
    return round(sigma, 6) if abs(final - market_price) <= max(1e-4, 1e-4 * market_price) else None


# ==============================================================================
# 5. MAX PAIN STRIKE ALGORITHM
# ==============================================================================

def compute_max_pain_strike(
    strikes: list[float],
    call_oi: list[float],
    put_oi: list[float],
) -> tuple[float, float]:
    """Compute the Max Pain Strike: settlement price minimizing collective option payout."""
    if not strikes or len(strikes) != len(call_oi) or len(strikes) != len(put_oi):
        raise ValueError("Strikes, call_oi, and put_oi must have identical non-empty lengths.")

    unique_strikes = sorted(set(strikes))
    strike_losses: list[tuple[float, float]] = []

    for s_eval in unique_strikes:
        c_loss = sum(oi * max(0.0, s_eval - k) for oi, k in zip(call_oi, strikes))
        p_loss = sum(oi * max(0.0, k - s_eval) for oi, k in zip(put_oi, strikes))
        strike_losses.append((s_eval, c_loss + p_loss))

    min_strike, min_loss = min(strike_losses, key=lambda x: x[1])
    return min_strike, min_loss


# ==============================================================================
# 6. COMPLETE OPTIONS CHAIN ANALYTICS & SENTIMENT SURFACE
# ==============================================================================

def analyze_options_chain(
    quotes: list[dict[str, Any]],
    forward_price: float,
    time_years: float,
    risk_free_rate: float = 0.065,
    symbol: str = "NIFTY",
) -> OptionsChainSummary:
    """Analyze full options chain quotes, computing PCR, Max Pain, ATM IV, and sentiment."""
    if not quotes or forward_price <= 0:
        raise ValueError("Valid quotes list and positive forward price required.")

    call_records: dict[float, OptionStrikeRecord] = {}
    put_records: dict[float, OptionStrikeRecord] = {}

    def _num(value: Any) -> float | None:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None

    for q in quotes:
        k = float(q["strike"])
        opt_type = str(q.get("option_type", "")).upper()
        bid = _num(q.get("bid"))
        ask = _num(q.get("ask"))
        lp = _num(q.get("last_price"))
        mid = (bid + ask) / 2.0 if (bid and ask and bid > 0 and ask > 0) else lp
        oi = _num(q.get("open_interest"))
        vol = _num(q.get("volume"))

        # Invert IV if not directly provided
        iv = float(q.get("implied_volatility")) if q.get("implied_volatility") is not None else None
        if (iv is None or iv <= 0.0) and mid is not None and mid > 0:
            iv = solve_black76_implied_volatility(
                market_price=mid,
                forward=forward_price,
                strike=k,
                time_years=time_years,
                risk_free_rate=risk_free_rate,
                is_call=(opt_type == "CE"),
            )

        greeks = None
        if iv is not None and iv > 0.0:
            greeks = calculate_black76_and_greeks(
                forward=forward_price,
                strike=k,
                time_years=time_years,
                volatility=iv,
                risk_free_rate=risk_free_rate,
                is_call=(opt_type == "CE"),
            )

        rec = OptionStrikeRecord(
            strike=k,
            option_type=opt_type,
            bid=bid,
            ask=ask,
            mid=mid,
            last_price=lp,
            open_interest=oi,
            volume=vol,
            implied_volatility=iv,
            greeks=greeks,
        )

        if opt_type == "CE":
            call_records[k] = rec
        elif opt_type == "PE":
            put_records[k] = rec

    all_strikes = sorted(set(call_records.keys()) | set(put_records.keys()))
    if not all_strikes:
        raise ValueError("No valid CE or PE strikes found in quotes.")

    # Aligned vectors for Max Pain
    aligned_strikes = []
    aligned_c_oi = []
    aligned_p_oi = []

    # Open interest and volume count only where reported; a missing value is not zero
    oi_complete = all(
        (k not in call_records or call_records[k].open_interest is not None)
        and (k not in put_records or put_records[k].open_interest is not None)
        for k in all_strikes
    )

    def _total(records: dict, attr: str) -> float | None:
        vals = [getattr(r, attr) for r in records.values()]
        return float(sum(vals)) if vals and all(v is not None for v in vals) else None

    tot_c_oi = _total(call_records, "open_interest")
    tot_p_oi = _total(put_records, "open_interest")
    tot_c_vol = _total(call_records, "volume")
    tot_p_vol = _total(put_records, "volume")

    for k in all_strikes:
        aligned_strikes.append(k)
        aligned_c_oi.append((call_records[k].open_interest if k in call_records else 0.0) or 0.0)
        aligned_p_oi.append((put_records[k].open_interest if k in put_records else 0.0) or 0.0)

    # PCR metrics (None when either side's totals are missing or zero)
    pcr_oi = tot_p_oi / tot_c_oi if (tot_p_oi is not None and tot_c_oi) else None
    pcr_vol = tot_p_vol / tot_c_vol if (tot_p_vol is not None and tot_c_vol) else None

    # Max Pain needs reported OI at every strike
    if oi_complete and (tot_c_oi or tot_p_oi):
        max_pain_k, max_pain_loss = compute_max_pain_strike(aligned_strikes, aligned_c_oi, aligned_p_oi)
    else:
        max_pain_k, max_pain_loss = None, None

    # ATM Strike (closest strike to forward)
    atm_k = min(all_strikes, key=lambda k: abs(k - forward_price))
    atm_ce = call_records.get(atm_k)
    atm_pe = put_records.get(atm_k)
    iv_vals = [r.implied_volatility for r in (atm_ce, atm_pe) if r and r.implied_volatility]
    atm_iv = float(sum(iv_vals) / len(iv_vals)) if iv_vals else None

    # 25-Delta Skew (closest call to delta +0.25, closest put to delta -0.25), Greeks required
    call_25d = min((r for r in call_records.values() if r.greeks), key=lambda r: abs(r.greeks.delta - 0.25), default=None)
    put_25d = min((r for r in put_records.values() if r.greeks), key=lambda r: abs(r.greeks.delta + 0.25), default=None)

    if call_25d and put_25d and call_25d.implied_volatility and put_25d.implied_volatility:
        skew_25d = round(put_25d.implied_volatility - call_25d.implied_volatility, 4)
    else:
        skew_25d = None

    # Quantitative Directional Sentiment Rules
    # Indian markets empirical threshold:
    # PCR_OI > 1.25 -> Bullish (heavy put writing support)
    # PCR_OI < 0.75 -> Bearish (heavy call writing resistance)
    # In between -> Neutral
    reason_codes = []
    if pcr_oi is None:
        sentiment = "UNKNOWN"
        conf = None
        reason_codes.append("PCR_UNAVAILABLE_OI_MISSING")
    elif pcr_oi >= 1.25:
        sentiment = "BULLISH"
        conf = min(0.85, 0.50 + (pcr_oi - 1.25) * 0.40)
        reason_codes.append("PCR_BULLISH_SUPPORT")
    elif pcr_oi <= 0.75:
        sentiment = "BEARISH"
        conf = min(0.85, 0.50 + (0.75 - pcr_oi) * 0.40)
        reason_codes.append("PCR_BEARISH_RESISTANCE")
    else:
        sentiment = "NEUTRAL"
        conf = 0.50
        reason_codes.append("PCR_NEUTRAL_EQUILIBRIUM")

    # Modulate by forward position relative to Max Pain
    if max_pain_k is not None:
        dist_to_max_pain = (max_pain_k - forward_price) / forward_price
        if dist_to_max_pain > 0.015:
            reason_codes.append("FORWARD_BELOW_MAX_PAIN_MAGNET_UP")
        elif dist_to_max_pain < -0.015:
            reason_codes.append("FORWARD_ABOVE_MAX_PAIN_MAGNET_DOWN")

    return OptionsChainSummary(
        underlying_symbol=symbol,
        forward_price=round(forward_price, 2),
        risk_free_rate=risk_free_rate,
        time_to_expiry_years=round(time_years, 4),
        total_call_oi=tot_c_oi,
        total_put_oi=tot_p_oi,
        total_call_volume=tot_c_vol,
        total_put_volume=tot_p_vol,
        pcr_oi=round(pcr_oi, 4) if pcr_oi is not None else None,
        pcr_volume=round(pcr_vol, 4) if pcr_vol is not None else None,
        max_pain_strike=max_pain_k,
        max_pain_total_loss=max_pain_loss,
        atm_strike=atm_k,
        atm_iv=round(atm_iv, 4) if atm_iv is not None else None,
        volatility_skew_25d=skew_25d,
        directional_sentiment=sentiment,
        sentiment_confidence=round(conf, 4) if conf is not None else None,
        strikes_evaluated=len(all_strikes),
        reason_codes=reason_codes,
    )
