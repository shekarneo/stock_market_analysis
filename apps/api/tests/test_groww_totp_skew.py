"""TOTP exchange tolerates a local clock that is off by up to 90 seconds."""

from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.groww import exchange_token, totp_code
from app.integrations.http import HttpResult

SECRET = "JBSWY3DPEHPK3PXP"  # RFC 6238 style example secret, not a real credential


class SkewedGroww:
    """Accepts only the code for a server clock 60s ahead; answers others with 400."""

    def __init__(self, now: int, skew: int):
        self.good = totp_code(SECRET, timestamp=now + skew)
        self.calls = 0

    def send(self, method, url, *, headers, json_body, timeout):
        self.calls += 1
        if json_body["totp"] == self.good:
            return HttpResult(200, {"token": "t", "expiry": "2026-10-24T06:00:00"}, "")
        return HttpResult(400, {"error": {"errorCode": "400", "errorMessage": "Invalid credentials"}}, "")


def test_400_from_a_skewed_clock_is_retried_and_succeeds():
    now = datetime(2026, 10, 23, 6, 30, 10, tzinfo=timezone.utc)
    caller = SkewedGroww(int(now.timestamp()), 60)
    updated, expiry = exchange_token(caller, {"api_key": "k", "totp_secret": SECRET}, method="totp", now=now)
    assert updated["access_token"] == "t" and expiry
    assert caller.calls <= 4
