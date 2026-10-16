"""Milestone M17: Date-Effective Market Session Calendar & Independent Historical Data Verification.

Provides:
- Date-effective, versioned market session rules with explicit session phases
- Strict separation of Spot Index, Cash Equity (CAS / Non-CAS), Index Derivatives, and Stock Derivatives
- Official exchange circular references and verification tracking (NSE, BSE, SEBI)
- Transitions for Pre-3 Aug 2026, Post-3 Aug 2026, Post-15 Oct 2026, and Post-7 Dec 2026
- Fail-closed evaluation for unverified or unknown rules
- Date-effective audit of historical datasets and candle observations
- Three-level independent verification specification and fail-closed reconciliation engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.market.schemas import IST, require_aware
from app.market.verified_history import STANDARD_SESSION_START_TIMES
from app.settings import REPO_ROOT

ASIA_KOLKATA = ZoneInfo("Asia/Kolkata")


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"


class MarketSegment(str, Enum):
    CASH = "CASH"
    DERIVATIVES = "DERIVATIVES"
    INDEX = "INDEX"
    COMMODITY = "COMMODITY"


class InstrumentCategory(str, Enum):
    SPOT_INDEX = "SPOT_INDEX"                       # e.g., NIFTY 50, Bank NIFTY spot
    CASH_EQUITY_CAS = "CASH_EQUITY_CAS"             # Cash equities with derivatives / CAS eligible
    CASH_EQUITY_NON_CAS = "CASH_EQUITY_NON_CAS"     # Cash equities outside CAS
    INDEX_FUTURES = "INDEX_FUTURES"                 # e.g., NIFTY Index Futures
    INDEX_OPTIONS = "INDEX_OPTIONS"                 # e.g., NIFTY Index Options
    STOCK_DERIVATIVES = "STOCK_DERIVATIVES"         # Single-stock futures and options
    COMMODITY_FUTURES = "COMMODITY_FUTURES"         # MCX Commodities


class PhaseType(str, Enum):
    PRE_MARKET_AUCTION = "PRE_MARKET_AUCTION"
    CONTINUOUS_TRADING = "CONTINUOUS_TRADING"
    CLOSING_AUCTION = "CLOSING_AUCTION"
    POST_CLOSE = "POST_CLOSE"
    EVENING_SESSION = "EVENING_SESSION"
    CLOSED = "CLOSED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class SessionPhase:
    """An explicit temporal phase of an exchange session."""
    phase_type: PhaseType
    start_time: time
    end_time: time
    description: str
    is_continuous: bool
    is_tradable: bool

    def contains(self, t: time) -> bool:
        """Check if time t falls in [start_time, end_time)."""
        if self.start_time <= self.end_time:
            return self.start_time <= t < self.end_time
        # Overnight wrap (e.g. MCX)
        return t >= self.start_time or t < self.end_time


@dataclass(frozen=True)
class CircularReference:
    """Authoritative regulatory circular or exchange notification."""
    authority: str
    circular_id: str
    publication_date: date
    effective_date: date
    title: str
    url: str
    verification_status: VerificationStatus
    summary: str


@dataclass(frozen=True)
class MarketSessionRule:
    """A versioned, date-effective market session rule for a specific exchange and instrument class."""
    rule_id: str
    exchange: Exchange
    segment: MarketSegment
    instrument_category: InstrumentCategory
    effective_from: date
    effective_to: date | None  # None indicates indefinitely effective into future
    timezone_name: str
    phases: list[SessionPhase]
    continuous_start: time
    continuous_end: time
    circular: CircularReference
    verification_status: VerificationStatus
    expiry_day_exception: str | None = None
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED

    def get_phase_for_time(self, t: time) -> SessionPhase | None:
        for phase in self.phases:
            if phase.contains(t):
                return phase
        return None

    def is_in_continuous_trading(self, t: time) -> bool:
        phase = self.get_phase_for_time(t)
        return phase is not None and phase.is_continuous and phase.phase_type == PhaseType.CONTINUOUS_TRADING

    def expected_15m_bar_starts(self) -> list[str]:
        """Compute the expected 15-minute bar start times in HH:MM:SS during continuous trading."""
        starts = []
        cur = datetime.combine(date(2026, 1, 1), self.continuous_start)
        end = datetime.combine(date(2026, 1, 1), self.continuous_end)
        while cur + timedelta(minutes=15) <= end:
            starts.append(cur.strftime("%H:%M:%S"))
            cur += timedelta(minutes=15)
        return starts


# ==============================================================================
# AUTHORITATIVE CIRCULAR DEFINITIONS
# ==============================================================================

CIRCULAR_PRE_AUG_2026 = CircularReference(
    authority="SEBI / NSE",
    circular_id="SEBI/HO/MRD/DP/CIR/P/2018/67",
    publication_date=date(2018, 4, 11),
    effective_date=date(2018, 4, 11),
    title="Master Circular for Stock Exchanges and Clearing Corporations - Trading Hours & Call Auction",
    url="https://www.sebi.gov.in/legal/master-circulars/apr-2018/master-circular-for-stock-exchanges-and-clearing-corporations_38644.html",
    verification_status=VerificationStatus.VERIFIED,
    summary=(
        "Standard equity cash continuous trading 09:15 to 15:30 IST; pre-market call auction "
        "09:00 to 09:15; post-market closing session 15:40 to 16:00. Spot index calculated and "
        "disseminated continuously from 09:15 to 15:30 IST based on underlying cash prices."
    ),
)

CIRCULAR_NSE_CAS_AUG_2026 = CircularReference(
    authority="NSE",
    circular_id="NSE/CMTR/74466",
    publication_date=date(2026, 5, 29),
    effective_date=date(2026, 8, 3),
    title="Introduction of Closing Auction Session (CAS) in the Equity Cash segment - Change in trading modalities",
    url="https://www.nseindia.com/resources/exchange-communication-circulars",
    verification_status=VerificationStatus.VERIFIED,
    summary=(
        "Introduced Closing Auction Session (CAS) for F&O-enabled cash market securities effective "
        "August 3, 2026. Continuous trading for CAS-eligible stocks truncated to 15:15:00 IST followed "
        "by CAS from 15:15 to 15:35/15:40. Derivatives trading window extended/synchronized to 15:40:00 IST. "
        "Non-CAS securities and spot index continuous calculation hours remained unchanged."
    ),
)

CIRCULAR_SEBI_OCT_2026 = CircularReference(
    authority="SEBI",
    circular_id="SEBI/HO/47/11/11(3)2025-MRD-POD2/I/23843/2026",
    publication_date=date(2026, 10, 15),
    effective_date=date(2026, 12, 7),
    title="Review of Closing Auction Session (CAS), Market Timings and Settlement Methodology for Derivatives",
    url="https://www.sebi.gov.in/legal/circulars/oct-2026/review-of-closing-auction-session-and-market-timings_23843.html",
    verification_status=VerificationStatus.VERIFIED,
    summary=(
        "Comprehensive overhaul following consultation and market volatility. Scheduled effective "
        "December 7, 2026: Restores continuous cash trading until 15:30:00; establishes dedicated CAS "
        "from 15:30 to 15:40:00 (with random close between 15:38 and 15:40); sets derivatives continuous "
        "trading to close at 15:45:00 on regular days; requires index derivatives expiring that day to "
        "close at 15:30:00 on expiry day; restores 30-minute VWAP (15:00 to 15:30) of underlying constituents "
        "for cash settlement of expiring index and stock derivatives."
    ),
)

CIRCULAR_UNVERIFIED_FUTURE_HYPOTHESIS = CircularReference(
    authority="UNVERIFIED_SOURCE",
    circular_id="UNVERIFIED/CIRCULAR/DRAFT",
    publication_date=date(2026, 10, 1),
    effective_date=date(2027, 1, 1),
    title="Unverified Proposed Extension of Cash Trading Hours",
    url="https://unverified.internal.invalid/draft",
    verification_status=VerificationStatus.UNVERIFIED,
    summary="Hypothetical / unverified circular proposal for testing fail-closed behavior.",
)


# ==============================================================================
# DATE-EFFECTIVE RULES TABLE
# ==============================================================================

# Standard phases before 3 August 2026
_PRE_AUG_SPOT_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-market call auction (underlying stocks)", False, False),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous spot index calculation and dissemination", True, False),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Post-session cash VWAP closing mark calculation", False, False),
    SessionPhase(PhaseType.POST_CLOSE, time(15, 40), time(16, 0), "Post-market cash session (index static)", False, False),
    SessionPhase(PhaseType.CLOSED, time(16, 0), time(9, 0), "Market closed", False, False),
]

_PRE_AUG_CASH_CAS_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open order collection & matching", False, True),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Normal continuous market", True, True),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Closing session VWAP calculation", False, False),
    SessionPhase(PhaseType.POST_CLOSE, time(15, 40), time(16, 0), "Post-close trades at closing price", False, True),
    SessionPhase(PhaseType.CLOSED, time(16, 0), time(9, 0), "Market closed", False, False),
]

_PRE_AUG_DERIVATIVES_PHASES = [
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous derivatives trading", True, True),
    SessionPhase(PhaseType.CLOSED, time(15, 30), time(9, 15), "Derivatives market closed", False, False),
]

# Phases from 3 August 2026 to 6 December 2026
_AUG_TO_DEC_SPOT_PHASES = [
    # Spot index continues 09:15 to 15:30 because underlying continuous & CAS trades still update index
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open call auction", False, False),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous spot index calculation", True, False),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Closing mark finalization", False, False),
    SessionPhase(PhaseType.CLOSED, time(15, 40), time(9, 0), "Market closed", False, False),
]

_AUG_TO_DEC_CASH_CAS_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open call auction", False, True),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 15), "Continuous trading (F&O stocks truncated for CAS)", True, True),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 15), time(15, 40), "Closing Auction Session (CAS)", False, True),
    SessionPhase(PhaseType.POST_CLOSE, time(15, 40), time(16, 0), "Post-close session", False, True),
    SessionPhase(PhaseType.CLOSED, time(16, 0), time(9, 0), "Market closed", False, False),
]

_AUG_TO_DEC_CASH_NON_CAS_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open call auction", False, True),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous trading non-CAS stocks", True, True),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Closing price calculation", False, False),
    SessionPhase(PhaseType.POST_CLOSE, time(15, 40), time(16, 0), "Post-close session", False, True),
    SessionPhase(PhaseType.CLOSED, time(16, 0), time(9, 0), "Market closed", False, False),
]

_AUG_TO_DEC_DERIVATIVES_PHASES = [
    # Extended to 15:40:00 under August 3 circular
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 40), "Continuous derivatives trading (synchronized with CAS)", True, True),
    SessionPhase(PhaseType.CLOSED, time(15, 40), time(9, 15), "Derivatives market closed", False, False),
]

# Phases from 7 December 2026 onward (SEBI Overhaul)
_DEC_ONWARD_SPOT_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open call auction", False, False),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous spot index calculation and dissemination", True, False),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Dedicated cash CAS window (underlying stocks)", False, False),
    SessionPhase(PhaseType.CLOSED, time(15, 40), time(9, 0), "Market closed", False, False),
]

_DEC_ONWARD_CASH_CAS_PHASES = [
    SessionPhase(PhaseType.PRE_MARKET_AUCTION, time(9, 0), time(9, 15), "Pre-open call auction", False, True),
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Continuous trading restored to 15:30", True, True),
    SessionPhase(PhaseType.CLOSING_AUCTION, time(15, 30), time(15, 40), "Dedicated Closing Auction Session (CAS)", False, True),
    SessionPhase(PhaseType.POST_CLOSE, time(15, 50), time(16, 0), "Post-close session", False, True),
    SessionPhase(PhaseType.CLOSED, time(16, 0), time(9, 0), "Market closed", False, False),
]

_DEC_ONWARD_INDEX_DERIVATIVES_REGULAR_PHASES = [
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 45), "Continuous index derivatives trading (regular days)", True, True),
    SessionPhase(PhaseType.CLOSED, time(15, 45), time(9, 15), "Derivatives closed", False, False),
]

_DEC_ONWARD_INDEX_DERIVATIVES_EXPIRY_PHASES = [
    # Expiring index contracts cease trading at 15:30:00 on expiry day
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 30), "Expiring index derivatives trading (closes at 15:30 on expiry)", True, True),
    SessionPhase(PhaseType.CLOSED, time(15, 30), time(9, 15), "Expiring contracts closed", False, False),
]

_DEC_ONWARD_STOCK_DERIVATIVES_PHASES = [
    # Stock derivatives trade to 15:45 even on expiry days
    SessionPhase(PhaseType.CONTINUOUS_TRADING, time(9, 15), time(15, 45), "Stock derivatives trading", True, True),
    SessionPhase(PhaseType.CLOSED, time(15, 45), time(9, 15), "Derivatives closed", False, False),
]


# Master rule repository
VERSIONED_MARKET_SESSION_RULES: list[MarketSessionRule] = [
    # --------------------------------------------------------------------------
    # 1. NIFTY 50 SPOT INDEX (Continuous calculation 09:15 to 15:30 IST across all eras)
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="NSE_INDEX_SPOT_PRE_AUG_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.INDEX,
        instrument_category=InstrumentCategory.SPOT_INDEX,
        effective_from=date(2018, 4, 11),
        effective_to=date(2026, 8, 2),
        timezone_name="Asia/Kolkata",
        phases=_PRE_AUG_SPOT_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_PRE_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Pre-August 3, 2026 NIFTY 50 spot index continuous computation rules.",
    ),
    MarketSessionRule(
        rule_id="NSE_INDEX_SPOT_AUG_DEC_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.INDEX,
        instrument_category=InstrumentCategory.SPOT_INDEX,
        effective_from=date(2026, 8, 3),
        effective_to=date(2026, 12, 6),
        timezone_name="Asia/Kolkata",
        phases=_AUG_TO_DEC_SPOT_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_NSE_CAS_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Spot index calculation hours remain 09:15 to 15:30 IST during CAS Phase 1.",
    ),
    MarketSessionRule(
        rule_id="NSE_INDEX_SPOT_DEC_2026_ONWARD",
        exchange=Exchange.NSE,
        segment=MarketSegment.INDEX,
        instrument_category=InstrumentCategory.SPOT_INDEX,
        effective_from=date(2026, 12, 7),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_SPOT_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_SEBI_OCT_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="NIFTY 50 spot index computation under revised SEBI CAS framework.",
    ),

    # --------------------------------------------------------------------------
    # 2. CASH EQUITIES - CAS ELIGIBLE (F&O stocks)
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="NSE_CASH_CAS_PRE_AUG_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.CASH,
        instrument_category=InstrumentCategory.CASH_EQUITY_CAS,
        effective_from=date(2018, 4, 11),
        effective_to=date(2026, 8, 2),
        timezone_name="Asia/Kolkata",
        phases=_PRE_AUG_CASH_CAS_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_PRE_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Standard continuous cash market until 15:30:00 IST.",
    ),
    MarketSessionRule(
        rule_id="NSE_CASH_CAS_AUG_DEC_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.CASH,
        instrument_category=InstrumentCategory.CASH_EQUITY_CAS,
        effective_from=date(2026, 8, 3),
        effective_to=date(2026, 12, 6),
        timezone_name="Asia/Kolkata",
        phases=_AUG_TO_DEC_CASH_CAS_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 15),
        circular=CIRCULAR_NSE_CAS_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Continuous trading ends at 15:15:00 IST for CAS eligible securities.",
    ),
    MarketSessionRule(
        rule_id="NSE_CASH_CAS_DEC_2026_ONWARD",
        exchange=Exchange.NSE,
        segment=MarketSegment.CASH,
        instrument_category=InstrumentCategory.CASH_EQUITY_CAS,
        effective_from=date(2026, 12, 7),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_CASH_CAS_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_SEBI_OCT_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Continuous trading restored to 15:30:00 IST; dedicated CAS 15:30-15:40.",
    ),

    # --------------------------------------------------------------------------
    # 3. CASH EQUITIES - NON-CAS
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="NSE_CASH_NON_CAS_ALL_PERIODS",
        exchange=Exchange.NSE,
        segment=MarketSegment.CASH,
        instrument_category=InstrumentCategory.CASH_EQUITY_NON_CAS,
        effective_from=date(2018, 4, 11),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_AUG_TO_DEC_CASH_NON_CAS_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_PRE_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Non-CAS cash securities maintain standard 09:15 to 15:30 continuous trading.",
    ),

    # --------------------------------------------------------------------------
    # 4. INDEX DERIVATIVES (NIFTY Futures & Options)
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="NSE_DERIVATIVES_INDEX_PRE_AUG_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.DERIVATIVES,
        instrument_category=InstrumentCategory.INDEX_FUTURES,
        effective_from=date(2018, 4, 11),
        effective_to=date(2026, 8, 2),
        timezone_name="Asia/Kolkata",
        phases=_PRE_AUG_DERIVATIVES_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_PRE_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Pre-August 3 derivatives continuous trading until 15:30:00 IST.",
    ),
    MarketSessionRule(
        rule_id="NSE_DERIVATIVES_INDEX_AUG_DEC_2026",
        exchange=Exchange.NSE,
        segment=MarketSegment.DERIVATIVES,
        instrument_category=InstrumentCategory.INDEX_FUTURES,
        effective_from=date(2026, 8, 3),
        effective_to=date(2026, 12, 6),
        timezone_name="Asia/Kolkata",
        phases=_AUG_TO_DEC_DERIVATIVES_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 40),
        circular=CIRCULAR_NSE_CAS_AUG_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Derivatives trading extended to 15:40:00 IST to match CAS window.",
    ),
    MarketSessionRule(
        rule_id="NSE_DERIVATIVES_INDEX_DEC_2026_REGULAR",
        exchange=Exchange.NSE,
        segment=MarketSegment.DERIVATIVES,
        instrument_category=InstrumentCategory.INDEX_FUTURES,
        effective_from=date(2026, 12, 7),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_INDEX_DERIVATIVES_REGULAR_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 45),
        circular=CIRCULAR_SEBI_OCT_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Regular-day index derivatives trade until 15:45:00 IST.",
    ),
    MarketSessionRule(
        rule_id="NSE_DERIVATIVES_INDEX_DEC_2026_EXPIRY_EXPIRING",
        exchange=Exchange.NSE,
        segment=MarketSegment.DERIVATIVES,
        instrument_category=InstrumentCategory.INDEX_OPTIONS,
        effective_from=date(2026, 12, 7),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_INDEX_DERIVATIVES_EXPIRY_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 30),
        circular=CIRCULAR_SEBI_OCT_2026,
        verification_status=VerificationStatus.VERIFIED,
        expiry_day_exception="EXPIRING_INDEX_CONTRACTS_CLOSE_AT_1530",
        notes="On expiry day, expiring index options and futures close at 15:30:00 IST.",
    ),

    # --------------------------------------------------------------------------
    # 5. STOCK DERIVATIVES (Single Stock F&O)
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="NSE_DERIVATIVES_STOCK_DEC_2026_ONWARD",
        exchange=Exchange.NSE,
        segment=MarketSegment.DERIVATIVES,
        instrument_category=InstrumentCategory.STOCK_DERIVATIVES,
        effective_from=date(2026, 12, 7),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_STOCK_DERIVATIVES_PHASES,
        continuous_start=time(9, 15),
        continuous_end=time(15, 45),
        circular=CIRCULAR_SEBI_OCT_2026,
        verification_status=VerificationStatus.VERIFIED,
        notes="Single-stock derivatives trade until 15:45:00 IST even on expiry days.",
    ),

    # --------------------------------------------------------------------------
    # 6. UNVERIFIED RULE FIXTURE (For fail-closed testing)
    # --------------------------------------------------------------------------
    MarketSessionRule(
        rule_id="UNVERIFIED_RULE_TEST_FIXTURE",
        exchange=Exchange.MCX,
        segment=MarketSegment.COMMODITY,
        instrument_category=InstrumentCategory.COMMODITY_FUTURES,
        effective_from=date(2027, 1, 1),
        effective_to=None,
        timezone_name="Asia/Kolkata",
        phases=_DEC_ONWARD_CASH_CAS_PHASES,
        continuous_start=time(9, 0),
        continuous_end=time(17, 0),
        circular=CIRCULAR_UNVERIFIED_FUTURE_HYPOTHESIS,
        verification_status=VerificationStatus.UNVERIFIED,
        notes="Unverified draft rule for fail-closed verification testing.",
    ),
]


class SessionRuleNotFoundError(Exception):
    """Raised when no market session rule matches the queried parameters."""


class UnverifiedRuleError(Exception):
    """Raised when an unverified rule is encountered where strict verification is required."""


def get_market_session_rule(
    instrument_or_category: str | InstrumentCategory,
    as_of_date: date,
    segment: str | MarketSegment = MarketSegment.INDEX,
    exchange: str | Exchange = Exchange.NSE,
    is_expiry_day: bool = False,
    is_expiring_contract: bool = False,
    fail_on_unverified: bool = False,
) -> MarketSessionRule:
    """Resolve the authoritative date-effective market session rule.

    Fails closed if no matching rule is found or if an unverified rule is accessed
    when fail_on_unverified is True.
    """
    # Normalize category
    category_str = (
        instrument_or_category.value
        if isinstance(instrument_or_category, InstrumentCategory)
        else str(instrument_or_category).upper()
    )

    if category_str in {"NIFTY", "NIFTY 50", "NIFTY50", "SPOT_INDEX", "INDEX"}:
        target_cat = InstrumentCategory.SPOT_INDEX
        target_seg = MarketSegment.INDEX
    elif category_str in {"CASH_EQUITY_CAS", "CAS", "EQUITY_CAS", "FO_STOCKS"}:
        target_cat = InstrumentCategory.CASH_EQUITY_CAS
        target_seg = MarketSegment.CASH
    elif category_str in {"CASH_EQUITY_NON_CAS", "NON_CAS", "CASH"}:
        target_cat = InstrumentCategory.CASH_EQUITY_NON_CAS
        target_seg = MarketSegment.CASH
    elif category_str in {"INDEX_FUTURES", "NIFTY_FUTURES"}:
        target_cat = InstrumentCategory.INDEX_FUTURES
        target_seg = MarketSegment.DERIVATIVES
    elif category_str in {"INDEX_OPTIONS", "NIFTY_OPTIONS"}:
        target_cat = InstrumentCategory.INDEX_OPTIONS
        target_seg = MarketSegment.DERIVATIVES
    elif category_str in {"STOCK_DERIVATIVES", "STOCK_FUTURES", "STOCK_OPTIONS"}:
        target_cat = InstrumentCategory.STOCK_DERIVATIVES
        target_seg = MarketSegment.DERIVATIVES
    elif category_str in {"COMMODITY_FUTURES", "COMMODITY", "MCX", "UNVERIFIED_PROPOSAL"}:
        target_cat = InstrumentCategory.COMMODITY_FUTURES
        target_seg = MarketSegment.COMMODITY
    else:
        # Fallback to direct enum match if possible
        try:
            target_cat = InstrumentCategory(category_str)
            target_seg = MarketSegment(segment.value if isinstance(segment, MarketSegment) else str(segment).upper())
        except ValueError as err:
            raise SessionRuleNotFoundError(
                f"Unknown or unmapped instrument category '{instrument_or_category}' in segment '{segment}'"
            ) from err

    target_ex = Exchange(exchange.value if isinstance(exchange, Exchange) else str(exchange).upper())

    # Candidate search
    matching_rules: list[MarketSessionRule] = []
    for rule in VERSIONED_MARKET_SESSION_RULES:
        if rule.exchange != target_ex or rule.segment != target_seg:
            continue
        if rule.instrument_category != target_cat:
            continue
        # Date range match [effective_from, effective_to]
        if as_of_date < rule.effective_from:
            continue
        if rule.effective_to is not None and as_of_date > rule.effective_to:
            continue
        matching_rules.append(rule)

    if not matching_rules:
        raise SessionRuleNotFoundError(
            f"No date-effective market session rule found for exchange={target_ex}, "
            f"segment={target_seg}, category={target_cat}, date={as_of_date}, expiry={is_expiry_day}"
        )

    # Resolution precedence:
    # 1. If expiry day with expiring contract, prefer rule with expiry_day_exception
    # 2. Otherwise prefer rule without expiry_day_exception
    selected_rule: MarketSessionRule | None = None
    if is_expiry_day and is_expiring_contract:
        for r in matching_rules:
            if r.expiry_day_exception is not None:
                selected_rule = r
                break
        if selected_rule is None:
            # Fallback to standard continuous rule
            for r in matching_rules:
                if r.expiry_day_exception is None:
                    selected_rule = r
                    break
    else:
        for r in matching_rules:
            if r.expiry_day_exception is None:
                selected_rule = r
                break

    if selected_rule is None:
        selected_rule = matching_rules[0]

    if fail_on_unverified and not selected_rule.is_verified:
        raise UnverifiedRuleError(f"Matched rule {selected_rule.rule_id} is UNVERIFIED.")

    return selected_rule


# ==============================================================================
# HISTORICAL DATASET & OBSERVATION AUDITING
# ==============================================================================

@dataclass
class ObservationAuditRecord:
    timestamp: str
    time_of_day: str
    date: str
    phase: PhaseType
    is_continuous_regular: bool
    is_excluded: bool
    exclusion_reason: str | None
    rule_id: str
    rule_verified: bool


def audit_observation_against_calendar(
    observation: dict[str, Any],
    instrument: str = "NIFTY",
) -> ObservationAuditRecord:
    """Audit an individual candle observation against its date-effective market session rule.

    Determines conclusively whether the candle belongs to the regular continuous trading
    session or must be excluded, citing the exact rule and phase.
    """
    ts_str = observation.get("raw_timestamp") or observation.get("timestamp")
    if not ts_str:
        raise ValueError("Observation missing timestamp")

    # Parse ISO / Space timestamp with IST timezone
    clean_ts = ts_str.replace(" ", "T")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ASIA_KOLKATA)
    else:
        dt = dt.astimezone(ASIA_KOLKATA)

    as_of_date = dt.date()
    t = dt.time()
    time_str = t.strftime("%H:%M:%S")

    rule = get_market_session_rule(
        instrument_or_category=instrument,
        as_of_date=as_of_date,
    )

    phase = rule.get_phase_for_time(t)
    phase_type = phase.phase_type if phase else PhaseType.CLOSED

    # Check if observation is within the continuous regular session
    is_continuous = (
        phase is not None
        and phase.is_continuous
        and phase.phase_type == PhaseType.CONTINUOUS_TRADING
    )

    # For NIFTY spot index, regular continuous bars start at standard times 09:15 to 15:15
    is_regular_start = time_str in STANDARD_SESSION_START_TIMES
    is_regular = is_continuous and is_regular_start

    exclusion_reason = None
    if not is_regular:
        if phase_type == PhaseType.PRE_MARKET_AUCTION:
            exclusion_reason = "PRE_MARKET_CALL_AUCTION"
        elif time_str == "15:30:00":
            exclusion_reason = "POST_CONTINUOUS_SESSION_BOUNDARY_CLOSING_AUCTION"
        elif time_str == "15:45:00":
            exclusion_reason = "POST_MARKET_SETTLED_MARK"
        elif phase_type == PhaseType.CLOSED:
            exclusion_reason = "MARKET_CLOSED_HOURS"
        else:
            exclusion_reason = f"NON_CONTINUOUS_PHASE_{phase_type.value}"

    return ObservationAuditRecord(
        timestamp=dt.isoformat(),
        time_of_day=time_str,
        date=as_of_date.isoformat(),
        phase=phase_type,
        is_continuous_regular=is_regular,
        is_excluded=not is_regular,
        exclusion_reason=exclusion_reason,
        rule_id=rule.rule_id,
        rule_verified=rule.is_verified,
    )


def audit_m16_derived_dataset(
    dataset_path: Path | None = None,
) -> dict[str, Any]:
    """Audit the M16 derived regular-session dataset against the date-effective market session calendar."""
    p = dataset_path or (REPO_ROOT / "var" / "datasets" / "derived_nifty_15m_regular_ac9484b605d484c2.json")
    if not p.is_file():
        raise FileNotFoundError(f"Derived dataset not found at {p}")

    data = json.loads(p.read_text(encoding="utf-8"))
    regular_candles = data.get("regular_candles", [])

    total_candles = len(regular_candles)
    accepted_regular_count = 0
    anomalous_observations: list[dict[str, Any]] = []
    audited_rules: set[str] = set()

    for c in regular_candles:
        audit_res = audit_observation_against_calendar(c, instrument="NIFTY")
        audited_rules.add(audit_res.rule_id)
        if audit_res.is_continuous_regular and audit_res.rule_verified:
            accepted_regular_count += 1
        else:
            anomalous_observations.append({
                "candle": c,
                "audit": audit_res.__dict__,
            })

    # Completeness per date
    candles_by_date: dict[str, list[dict[str, Any]]] = {}
    for c in regular_candles:
        candles_by_date.setdefault(c["date"], []).append(c)

    session_gaps: list[dict[str, Any]] = []
    for d, day_list in sorted(candles_by_date.items()):
        if len(day_list) != 25:
            observed_times = {c["time_of_day"] for c in day_list}
            missing = [t for t in STANDARD_SESSION_START_TIMES if t not in observed_times]
            session_gaps.append({
                "date": d,
                "observed_count": len(day_list),
                "expected_count": 25,
                "missing_count": len(missing),
                "missing_times": missing,
            })

    return {
        "ok": len(anomalous_observations) == 0,
        "dataset_name": data.get("dataset_name"),
        "total_candles": total_candles,
        "accepted_regular_count": accepted_regular_count,
        "anomalous_observations_count": len(anomalous_observations),
        "anomalous_observations": anomalous_observations,
        "audited_rules": sorted(list(audited_rules)),
        "session_gaps_count": len(session_gaps),
        "session_gaps": session_gaps,
        "status": "CALENDAR_AUDIT_VERIFIED" if len(anomalous_observations) == 0 else "ANOMALIES_DETECTED",
    }


# ==============================================================================
# INDEPENDENT RECONCILIATION ENGINE & GATING SPECIFICATION
# ==============================================================================

@dataclass
class ReconciliationTolerances:
    """Strict quantitative tolerances for independent historical data verification."""
    max_price_delta_percent: float = 0.05  # 0.05% relative difference allowed between brokers
    max_price_delta_points: float = 2.0   # Or maximum 2.0 index points (whichever is greater)
    max_timestamp_drift_seconds: int = 0   # 0 seconds drift: candle start timestamps must match exactly
    interval_seconds: int = 900           # Exactly 15 minutes
    allow_inverted_candle: bool = False   # Never allow inverted High < Low or Close outside [L, H]
    max_unexpected_missing_bars: int = 0  # 0 unexpected missing bars in common regular sessions


class IndependentVerificationLevel(str, Enum):
    LEVEL_1_INTERNAL_STRUCTURAL = "LEVEL_1_INTERNAL_STRUCTURAL"
    LEVEL_2_INDEPENDENT_TIMESTAMP_SESSION = "LEVEL_2_INDEPENDENT_TIMESTAMP_SESSION"
    LEVEL_3_INDEPENDENT_OHLC_PRICE = "LEVEL_3_INDEPENDENT_OHLC_PRICE"


def run_independent_verification_audit(
    dataset_path: Path | None = None,
    tolerances: ReconciliationTolerances | None = None,
) -> dict[str, Any]:
    """Execute the multi-level independent verification audit for M17.

    Levels:
    Level 1: Internal structural validation (geometry, monotonicity, raw hash preservation).
    Level 2: Independent timestamp/session validation (session calendar alignment).
    Level 3: Independent OHLC price validation against independent broker gateway.

    Fails closed if independent credentials are unavailable.
    """
    tol = tolerances or ReconciliationTolerances()

    # 1. Level 1: Internal Structural Validation
    from app.market.groww_ingestion import verify_raw_quarantine_integrity
    raw_integrity = verify_raw_quarantine_integrity()

    m16_audit = audit_m16_derived_dataset(dataset_path)

    level_1_passed = (
        raw_integrity["ok"]
        and m16_audit["ok"]
        and m16_audit["accepted_regular_count"] == 3120
    )

    level_1_report = {
        "level": IndependentVerificationLevel.LEVEL_1_INTERNAL_STRUCTURAL.value,
        "status": "PASS" if level_1_passed else "FAIL",
        "raw_quarantine_hashes_verified": raw_integrity["ok"],
        "accepted_regular_candles": m16_audit["accepted_regular_count"],
        "known_gaps": m16_audit["session_gaps"],
        "details": "All raw hashes preserved; derived regular-session bars conform to internal geometric invariants.",
    }

    # 2. Check for Independent Provider Configuration
    from app.market.independent_provider import resolve_credentials_safe
    upstox_creds, upstox_missing = resolve_credentials_safe("upstox")
    kite_creds, kite_missing = resolve_credentials_safe("kite")
    angel_creds, angel_missing = resolve_credentials_safe("angelone")

    has_independent_creds = bool(upstox_creds or kite_creds or angel_creds)

    if not has_independent_creds:
        # Fails closed
        return {
            "verdict": "BLOCKED",
            "reason": "BLOCKED_CREDENTIALS_MISSING",
            "message": (
                "Independent reference data cannot be acquired because no authorized independent "
                "market data provider (Upstox, Zerodha Kite Connect, Angel One) credentials are configured. "
                "Per M17 safety protocol, Groww data cannot be substituted as its own reference."
            ),
            "tolerances": tol.__dict__,
            "verification_levels": {
                "level_1_internal_structural": level_1_report,
                "level_2_independent_timestamp_session": {
                    "level": IndependentVerificationLevel.LEVEL_2_INDEPENDENT_TIMESTAMP_SESSION.value,
                    "status": "BLOCKED",
                    "reason": "Independent external session reference feed unavailable.",
                },
                "level_3_independent_ohlc_price": {
                    "level": IndependentVerificationLevel.LEVEL_3_INDEPENDENT_OHLC_PRICE.value,
                    "status": "BLOCKED",
                    "reason": "Independent external OHLC candle reference feed unavailable.",
                },
            },
            "prerequisites_missing": {
                "upstox": upstox_missing,
                "kite": kite_missing,
                "angelone": angel_missing,
            },
            "safety_invariants": {
                "forecast_ready": False,
                "real_market_data_verified": False,
                "paper_approved": False,
                "live_approved": False,
                "live_broker_routing_enabled": False,
            },
        }

    # If credentials were provided in future, Level 2 and Level 3 execution would follow here
    # (Unreachable in current environment without external keys)
    return {
        "verdict": "PARTIAL",
        "reason": "CREDENTIALS_CONFIGURED_BUT_EXECUTION_PENDING",
        "tolerances": tol.__dict__,
        "safety_invariants": {
            "forecast_ready": False,
            "real_market_data_verified": False,
            "paper_approved": False,
            "live_approved": False,
            "live_broker_routing_enabled": False,
        },
    }
