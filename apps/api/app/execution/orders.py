from __future__ import annotations

from app.config.schemas import OperatingMode
from app.errors import LiveOrderDisabled, ModeForbidden

# Calls recorded only when the live function is actually entered.
live_order_calls: list[dict] = []


def place_live_order(intent: dict) -> None:
    """Broker write entry point. M0 does not call Groww and does not place an order."""
    live_order_calls.append(dict(intent))
    raise LiveOrderDisabled()


def request_order(mode: OperatingMode, intent: dict, *, live_trading_enabled: bool, server_flag: bool) -> None:
    """Refuse every mode except a fully flagged LIVE_TRADING request.

    PAPER, REPLAY, and LIVE_READ_ONLY return before place_live_order is called.
    LIVE_TRADING still cannot place an order in M0: the function raises
    LiveOrderDisabled and no broker client is imported.
    """
    from app.risk.external_halt import external_halt_status

    halt = external_halt_status()
    if halt["halted"]:
        raise ModeForbidden(f"Entries are halted by the out-of-band switch ({', '.join(halt['reasons'])}).")
    if mode is not OperatingMode.LIVE_TRADING:
        raise ModeForbidden(f"{mode.value} cannot call the live broker order function.")
    if not live_trading_enabled or not server_flag:
        raise ModeForbidden("The live order path is disabled.")
    place_live_order(intent)
