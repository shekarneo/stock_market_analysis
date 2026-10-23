"""Fixed Groww and OpenAI URLs. Callers cannot supply a host."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlsplit

import httpx

GROWW_ORIGIN = "https://api.groww.in"
GROWW_TOKEN_URL = f"{GROWW_ORIGIN}/v1/token/api/access"
GROWW_MARGIN_URL = f"{GROWW_ORIGIN}/v1/margins/detail/user"
GROWW_CANDLES_URL = f"{GROWW_ORIGIN}/v1/historical/candles"
GROWW_QUOTE_URL = f"{GROWW_ORIGIN}/v1/live-data/quote"
GROWW_LTP_URL = f"{GROWW_ORIGIN}/v1/live-data/ltp"
QUOTE_PARAMS = {"exchange": "NSE", "segment": "CASH", "trading_symbol": "NIFTY"}
# Read-only index quotes (with the day's OHLC); each query is fixed, callers pick only the instrument
INDEX_QUOTE_PARAMS = {
    "NIFTY": QUOTE_PARAMS,
    "BANKNIFTY": {"exchange": "NSE", "segment": "CASH", "trading_symbol": "BANKNIFTY"},
    "SENSEX": {"exchange": "BSE", "segment": "CASH", "trading_symbol": "SENSEX"},
}
LTP_PARAMS = {"segment": "CASH", "exchange_symbols": "BSE_SENSEX"}
OPENAI_MODELS_URL = "https://api.openai.com/v1/models/"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
ORDER_PATHS = ("/v1/order/create", "/v1/order/modify", "/v1/order/cancel")
CANDLE_QUERY = ("exchange", "segment", "groww_symbol", "start_time", "end_time", "candle_interval")


class UrlRejected(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "URL_REJECTED"
        self.message = message


def assert_allowed(method: str, url: str) -> None:
    lowered = url.lower()
    if any(path in lowered for path in ORDER_PATHS):
        raise UrlRejected("Order placement, modification, and cancellation are not used here.")
    if method == "POST" and url == GROWW_TOKEN_URL:
        return
    if method == "GET" and url == GROWW_MARGIN_URL:
        return
    if method == "GET" and _historical_candles_url(url):
        return
    if method == "GET" and any(_exact_groww(url, "/v1/live-data/quote", p) for p in INDEX_QUOTE_PARAMS.values()):
        return
    if method == "GET" and _exact_groww(url, "/v1/live-data/ltp", LTP_PARAMS):
        return
    if method == "GET" and _is_groww_option_chain_url(url):
        return
    if method == "POST" and url == OPENAI_CHAT_URL:
        return
    if method == "GET" and (url == "https://api.openai.com/v1/models" or url == "https://api.openai.com/v1/models/"):
        return
    if method == "GET" and url.startswith(OPENAI_MODELS_URL) and url != OPENAI_MODELS_URL:
        rest = url[len(OPENAI_MODELS_URL) :]
        if rest and "/" not in rest and "?" not in rest:
            return
    if method == "GET" and _is_kite_historical_url(url):
        return
    if method == "GET" and _is_upstox_historical_url(url):
        return
    if method == "POST" and _is_angelone_historical_url(url):
        return
    if method in {"GET", "POST"} and _is_gemini_url(url):
        return
    raise UrlRejected("That host or path is not an allowed read endpoint.")


def _is_kite_historical_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "api.kite.trade" and (
        parts.path.startswith("/instruments/historical/") or parts.path == "/user/profile"
    )


def _is_upstox_historical_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "api.upstox.com" and (
        parts.path.startswith("/v2/historical-candle/") or parts.path == "/v2/user/profile"
    )


def _is_angelone_historical_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "apiconnect.angelbroking.com" and (
        parts.path == "/rest/secure/angelbroking/historical/v1/getCandleData"
        or parts.path == "/rest/secure/angelbroking/user/v1/getProfile"
    )


def _is_gemini_url(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.netloc == "generativelanguage.googleapis.com" and (
        parts.path.startswith("/v1beta/models")
    )



def _exact_groww(url: str, path: str, expected: dict[str, str]) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.groww.in" or parts.path != path or parts.fragment:
        return False
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    return len(pairs) == len(expected) and dict(pairs) == expected


def _historical_candles_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.groww.in" or parts.path != "/v1/historical/candles":
        return False
    if parts.fragment:
        return False
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    return len(keys) == len(CANDLE_QUERY) and set(keys) == set(CANDLE_QUERY)


def _is_groww_option_chain_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != "api.groww.in" or parts.fragment:
        return False
    segments = [s for s in parts.path.strip("/").split("/") if s]
    # Format: /v1/option-chain/exchange/{exchange}/underlying/{underlying}
    if len(segments) != 6:
        return False
    if segments[0] != "v1" or segments[1] != "option-chain" or segments[2] != "exchange" or segments[4] != "underlying":
        return False
    if segments[3] not in {"NSE", "BSE", "MCX"}:
        return False
    if not segments[5] or not segments[5].isalnum():
        return False
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if len(pairs) != 1 or pairs[0][0] != "expiry_date" or not pairs[0][1]:
        return False
    return True


@dataclass
class HttpResult:
    status_code: int
    body: dict | list | None
    text: str
    raw: bytes = field(default_factory=bytes)
    headers: dict[str, str] = field(default_factory=dict)


class HttpxCaller:
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict | None,
        timeout: float,
    ) -> HttpResult:
        assert_allowed(method, url)
        try:
            response = httpx.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError("provider timed out") from exc
        body = None
        try:
            parsed = response.json()
            if isinstance(parsed, (dict, list)):
                body = parsed
        except ValueError:
            body = None
        retry_after = response.headers.get("retry-after")
        safe_headers = {"retry-after": retry_after} if retry_after is not None else {}
        return HttpResult(status_code=response.status_code, body=body, text=response.text, raw=response.content, headers=safe_headers)

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 10.0) -> HttpResult:
        return self.send("GET", url, headers=headers or {}, json_body=None, timeout=timeout)

    def post(self, url: str, *, headers: dict[str, str] | None = None, json: dict | None = None, timeout: float = 10.0) -> HttpResult:
        return self.send("POST", url, headers=headers or {}, json_body=json, timeout=timeout)

