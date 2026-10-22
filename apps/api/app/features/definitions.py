"""Feature set ohlc-2.

ohlc-2 adds scale-free versions of the price-level features (close_vs_sma_3,
sma_3_vs_sma_5, atr_3_pct). Model inputs use only scale-free features, so a model
fitted on one price range is not pushed out of distribution as the index trends.
The raw sma_3, sma_5, sma_3_minus_sma_5 and atr_3 columns are kept for lineage.


These formulas describe the tape. They are not a claim that any feature predicts a return.
Windows are trailing and end at the observation candle. Nothing in this set is centered,
scaled from a future sample, or filled from a missing bar.
"""

from __future__ import annotations

FEATURE_SET_VERSION = "ohlc-2"
PIPELINE_VERSION = "m2"
DATASET_SCHEMA_VERSION = "1.0"
MISSING_DATA_POLICY = "explicit_status_no_fill"
INTERVAL_MINUTES = 15

# Sample standard deviation (divisor n-1), matching statistics.stdev.
RETURN_STD_SAMPLE = True

AVAILABILITY_CONVENTION = (
    "A completed M15 candle may be used only at its bar_end, and only when retrieved_at "
    "is greater than or equal to bar_end. The feature row as_of timestamp is that bar_end. "
    "Every contributing candle must have bar_end less than or equal to as_of. "
    "provider_timestamp is not a completion time. If retrieved_at is earlier than bar_end, "
    "completion is not established and the candle is rejected. Later revisions of a print "
    "are not stored, so this is not a full point-in-time exchange archive."
)

POINT_IN_TIME_LIMITATION = (
    "Availability is limited to bar_end and retrieved_at on the candle contract. "
    "The fixture calendar is not an official NSE or BSE calendar. "
    "No untouched test dates have been selected because no model is fit."
)


FEATURE_SPECS: dict[str, dict[str, str | int]] = {
    "ret_1": {
        "formula": "close[t] / close[t-1] - 1",
        "inputs": "close",
        "lookback_bars": 1,
        "warmup_bars": 1,
        "missing": "WARMUP when t-1 does not exist; MISSING_OBSERVATION when the prior bar is not one interval earlier",
    },
    "ret_3": {
        "formula": "close[t] / close[t-3] - 1",
        "inputs": "close",
        "lookback_bars": 3,
        "warmup_bars": 3,
        "missing": "WARMUP when fewer than three prior bars exist; MISSING_OBSERVATION when bar_end[t] - bar_end[t-3] is not three intervals",
    },
    "sma_3": {
        "formula": "mean(close[t-2], close[t-1], close[t])",
        "inputs": "close",
        "lookback_bars": 3,
        "warmup_bars": 2,
        "missing": "WARMUP until three closes exist; MISSING_OBSERVATION if that span is not continuous",
    },
    "sma_5": {
        "formula": "mean(close[t-4] .. close[t])",
        "inputs": "close",
        "lookback_bars": 5,
        "warmup_bars": 4,
        "missing": "WARMUP until five closes exist; MISSING_OBSERVATION if that span is not continuous",
    },
    "close_vs_sma_5": {
        "formula": "close[t] / sma_5[t] - 1",
        "inputs": "close, sma_5",
        "lookback_bars": 5,
        "warmup_bars": 4,
        "missing": "Same status as sma_5 when sma_5 is unavailable",
    },
    "sma_3_minus_sma_5": {
        "formula": "sma_3[t] - sma_5[t]",
        "inputs": "sma_3, sma_5",
        "lookback_bars": 5,
        "warmup_bars": 4,
        "missing": "Unavailable when either moving average is unavailable; the stronger status is kept",
    },
    "close_vs_sma_3": {
        "formula": "close[t] / sma_3[t] - 1",
        "inputs": "close, sma_3",
        "lookback_bars": 3,
        "warmup_bars": 2,
        "missing": "Same status as sma_3 when sma_3 is unavailable",
    },
    "sma_3_vs_sma_5": {
        "formula": "sma_3[t] / sma_5[t] - 1",
        "inputs": "sma_3, sma_5",
        "lookback_bars": 5,
        "warmup_bars": 4,
        "missing": "Unavailable when either moving average is unavailable; the stronger status is kept",
    },
    "ret_std_5": {
        "formula": "sample standard deviation (divisor n-1) of ret_1[t-4] .. ret_1[t]",
        "inputs": "close",
        "lookback_bars": 6,
        "warmup_bars": 5,
        "missing": "WARMUP until five one-bar returns exist; MISSING_OBSERVATION if any of those returns is missing",
    },
    "atr_3": {
        "formula": "mean of true range[t-2], true range[t-1], true range[t]; true range[t] = max(high-low, abs(high-close[t-1]), abs(low-close[t-1]))",
        "inputs": "high, low, close",
        "lookback_bars": 4,
        "warmup_bars": 3,
        "missing": "Arithmetic mean of three true ranges, not Wilder smoothing. WARMUP until three true ranges exist",
    },
    "atr_3_pct": {
        "formula": "atr_3[t] / close[t]",
        "inputs": "atr_3, close",
        "lookback_bars": 4,
        "warmup_bars": 3,
        "missing": "Same status as atr_3 when atr_3 is unavailable; INVALID_INPUT if close is not positive",
    },
    "hl_range_vs_prev_close": {
        "formula": "(high[t] - low[t]) / close[t-1]",
        "inputs": "high, low, previous close",
        "lookback_bars": 1,
        "warmup_bars": 1,
        "missing": "WARMUP on the first bar; MISSING_OBSERVATION if the previous bar is not one interval earlier",
    },
    "oc_return": {
        "formula": "close[t] / open[t] - 1",
        "inputs": "open, close",
        "lookback_bars": 0,
        "warmup_bars": 0,
        "missing": "Uses only the observation candle. INVALID_INPUT if open is not finite and positive",
    },
    "close_position": {
        "formula": "(close[t] - low[t]) / (high[t] - low[t])",
        "inputs": "high, low, close",
        "lookback_bars": 0,
        "warmup_bars": 0,
        "missing": "INVALID_INPUT when high equals low. The value is not replaced with zero",
    },
    "session_confirmed": {
        "formula": "1 when the fixture calendar lists bar_start as a session, otherwise unavailable",
        "inputs": "bar_start, fixture calendar",
        "lookback_bars": 0,
        "warmup_bars": 0,
        "missing": "CALENDAR_UNKNOWN when the date is not listed. This flag is not a price feature and is not a prediction",
    },
}
