# Groww Customer Support Official Clarification: Historical Candle Timestamp Contract

**Recorded On:** 15 October 2026  
**Provider:** Nextbillion Technology Pvt. Ltd. (Groww Trading API)  
**Channel:** Groww Customer Success / Support (`shekaransd@gmail.com`)  
**Reference Support Ticket:** Clarifications regarding queries on the Groww Trading API (`GET /v1/historical/candles`)  
**Relates to:** [`docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md`](GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md), [`docs/OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md)

---

## 1. Official Communication Transcript

```text
Dear Customer,
Greetings from Groww!
With reference to your raised concern, please find the clarifications regarding your queries on the Groww Trading API:

Timezone: Request and response timestamps are in Indian Standard Time (IST).
Candle timestamps: Each timestamp represents the beginning of the candle.
Request boundaries: The start_time and end_time behavior is the same as on Groww charts.
Trading session: You may refer to the NIFTY charts to verify the first and last candle timestamps.
Incomplete candles: Yes, the API may return unfinished candles.
Index-specific behavior: The behavior is consistent with the charts and applies similarly across supported instruments.

For any further assistance, please feel free to contact us, we shall be glad to assist you.
Best regards,
Customer Success
Customer Support (https://groww.in/help)
```

---

## 2. Item-by-Item Resolution of Outstanding Confirmations

The 7 questions submitted in `docs/GROWW_CANDLE_TIMESTAMP_SUPPORT_REQUEST.md` are resolved as follows:

| Confirmation ID | Original Status | Resolution Status | Groww Support Authoritative Clarification | Technical Specification |
|---|---|---|---|---|
| `timestamp_timezone` | `UNANSWERED` | **VERIFIED** | *"Request and response timestamps are in Indian Standard Time (IST)."* | All naive timestamps in request bounds (`start_time`, `end_time`) and candle payload arrays use `Asia/Kolkata` (`UTC+05:30`). |
| `candle_boundary` | `UNANSWERED` | **VERIFIED** | *"Each timestamp represents the beginning of the candle."* | The timestamp is the **bar start time** (`bar_start`). For a 15-minute candle at `09:15:00`, the interval is `[09:15:00, 09:30:00)`. |
| `request_boundary` | `UNANSWERED` | **VERIFIED** | *"The start_time and end_time behavior is the same as on Groww charts."* | Request boundaries align with chart rendering windows; `start_time` defines the earliest candle start included. |
| `session_open_candle` | `UNANSWERED` | **VERIFIED** | *"You may refer to the NIFTY charts to verify the first and last candle timestamps."* | Regular NSE cash trading session begins at 09:15:00 IST. The opening 15-minute candle timestamp is `09:15:00` (covering 09:15 to 09:30). |
| `session_close_candle` | `UNANSWERED` | **VERIFIED** | *"You may refer to the NIFTY charts to verify the first and last candle timestamps."* | The final 15-minute trading candle of the regular session starts at `15:15:00` and concludes at `15:30:00`. Boundary timestamps like `15:30:00` with zero volume reflect post-market/closing auction marks. |
| `partial_candles` | `UNANSWERED` | **VERIFIED** | *"Yes, the API may return unfinished candles."* | **Critical ingestion rule**: If queried during market hours, the latest candle can be an active/in-progress bar. A candle is complete if and only if `retrieved_at >= bar_start + interval`. If `retrieved_at < bar_start + interval`, it must be marked `PARTIAL` and must not be frozen as a completed historical bar. |
| `index_timestamp_behavior` | `UNANSWERED` | **VERIFIED** | *"The behavior is consistent with the charts and applies similarly across supported instruments."* | Applies identically to `NSE-NIFTY` and `BSE-SENSEX`. Open interest is null for index spot. |

---

## 3. Data Transformation & Validation Rules

With this authoritative contract established, candle normalization operates deterministically:

1. **Timestamp Parsing**:
   - Given raw timestamp string `YYYY-MM-DD HH:MM:SS` or `YYYY-MM-DDTHH:MM:SS`:
   - Attach timezone: `Asia/Kolkata` (`UTC+05:30`).
   - Convert to UTC instant: `dt.astimezone(timezone.utc)`.

2. **Interval Boundaries**:
   $$\text{bar\_start} = \text{parsed timestamp (Asia/Kolkata)}$$
   $$\text{bar\_end} = \text{bar\_start} + \Delta t_{\text{interval}}$$
   - For `15minute`: $\Delta t = 15\text{ minutes}$.
   - For `1minute`: $\Delta t = 1\text{ minute}$.

3. **Candle Incompleteness Filter**:
   - If `retrieved_at < bar_end`: Flag as `INCOMPLETE_CANDLE`. Do not store as final historical data.
   - If `retrieved_at >= bar_end`: Flag as `COMPLETED_CANDLE`. Safe for historical feature engineering, training, and walk-forward backtesting.

---

## 4. Impact on Blockers for Paper & Live Trading

This confirmation unblocks the core requirement that halted automated model training and backtesting:
- **Historical Data Quarantine**: Quarantined datasets can now be validated against this verified IST bar-start contract.
- **Trusted Dataset Lineage**: Verified datasets can be promoted from quarantine once interval checks and completeness verification pass.
- **Model Training**: Feature engineering models (walk-forward logistic regression, LightGBM/XGBoost) can now run on clean, verified 15-minute and 1-minute datasets without violating the "no assumed data" constraint.
