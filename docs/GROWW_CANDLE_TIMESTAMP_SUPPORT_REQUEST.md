# Support request: historical candle timestamp semantics

Prepared 14 Oct 2026 from the official pages listed below. This file is a request to send. It is not a reply from Groww, and Groww has not confirmed any answer in it.

M7.2 reviewed the repository on 14 Oct 2026. No support reply, email, or other authoritative contract note is stored. Every confirmation below remains unanswered. A passing test does not change that status.

Send it through Groww Trading API support from the Trading APIs section of the Groww account. The introduction page read on 14 Oct 2026 does not publish a support address, so this file does not invent one.

## Pages already read

- https://groww.in/trade-api/docs/curl/backtesting
- https://groww.in/trade-api/docs/python-sdk/backtesting
- https://groww.in/trade-api/docs/curl/changelog
- https://groww.in/trade-api/docs/curl/annexures

Those pages document `GET /v1/historical/candles`, the query fields, the candle array, and `candle_interval` values including `15minute`. The candle timestamp is described as `yyyy-MM-dd HH:mm:ss`. Sample rows use a `T` and no offset. The pages do not state a timezone, whether the timestamp is the bar start or the bar end, whether `start_time` and `end_time` are inclusive, how partial candles are marked, or how the session open and close are timestamped. The worked example requests `5minute` and shows 30-minute rows, so the example is not being treated as the contract.

## Observed read, without credentials

One read-only request:

- `GET /v1/historical/candles`
- `exchange=NSE`, `segment=CASH`, `groww_symbol=NSE-NIFTY`, `candle_interval=15minute`
- `start_time=2026-10-13 09:15:00`
- `end_time=2026-10-13 15:30:00`

Result: HTTP 200, provider status `SUCCESS`, 26 candles, `interval_in_minutes` 15. The first raw timestamp was `2026-10-13T09:15:00` and the last was `2026-10-13T15:30:00`. Payload `start_time` and `end_time` were those same strings. None of the timestamps included an offset. Raw body SHA-256: `b05d4e5ca8db74f57af533a05dd49d518b5ed80866c4bee1c2ab52a075f121dd`.

## Outstanding confirmations

| Id | Status | What must be confirmed before a mapping exists |
|---|---|---|
| `timestamp_timezone` | UNANSWERED | Timezone of `start_time`, `end_time`, candle timestamps, payload range, and epoch seconds |
| `candle_boundary` | UNANSWERED | Whether the candle timestamp is the bar start or the bar end |
| `request_boundary` | UNANSWERED | Whether request `start_time` and `end_time` are inclusive or exclusive |
| `session_open_candle` | UNANSWERED | Timestamp used for the opening 15-minute NSE cash candle |
| `session_close_candle` | UNANSWERED | Timestamp used for the closing 15-minute NSE cash candle |
| `partial_candles` | UNANSWERED | Whether an unfinished candle is returned, and how it is identified |
| `index_timestamp_behavior` | UNANSWERED | Whether `NSE-NIFTY` uses the same timestamp rules as equities, and what index volume and open interest mean |

## Questions

1. Which timezone applies to `start_time`, `end_time`, each candle timestamp, and the payload `start_time` and `end_time`? If a caller sends epoch seconds, what instant do those seconds represent, and does the string form use the same clock?
2. Does each candle timestamp denote the start of the interval or the end of the interval?
3. Are the request `start_time` and `end_time` inclusive or exclusive?
4. For an NSE cash session, what timestamp is used for the opening 15-minute candle, and what timestamp is used for the closing 15-minute candle?
5. Does the response include a candle that has not finished? If it does, how is that partial candle identified?
6. Do index candles such as `NSE-NIFTY` use the same timestamp rules as equity candles? What does the volume field mean for an index, and is open interest always null for an index?

Until Groww answers, this application will not treat the timestamps as IST and will not treat them as bar starts or bar ends.

M10 fetched the curl backtesting page again on 14 Oct 2026. The page text still does not name a timezone, a bar start, a bar end, request inclusivity, a partial candle, or a session-open or session-close rule. NSE daily index files and paid NSE feeds were reviewed and were not used. No trusted dataset was created. This paragraph is not a Groww reply.

A later local read of the quarantined files still found no support reply in the repository. The request above has not been sent. The evidence that would answer each question is a written Groww statement for that question. Even spacing and a matching first and last timestamp do not answer them.

On 14 Oct 2026 the current page `GET /v1/historical/candles` was read again. Its limits table allows 30 days for 1-, 2-, 3-, and 5-minute requests and 90 days for 10-, 15-, and 30-minute requests. The deprecated page `GET /v1/historical/candle/range` still documents different limits, including 7 days and the last 3 months for 1-minute data. A one-minute NIFTY read was not sent: the saved Groww integration is disabled. Enabling it, or sending the request while it is disabled, was not done. No quarantine file was changed. The stored token expiry `2026-10-15T06:00:00` has no offset. The Groww API dashboard resets API keys daily at 6:00 AM IST, so that value is read as Asia/Kolkata. It does not start a token exchange. A separate one-minute diagnostic can send one read-only candle request only when the integration is enabled and the expiry is timezone-aware and unexpired. That diagnostic was not executed.
