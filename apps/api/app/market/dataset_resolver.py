from __future__ import annotations

from pathlib import Path

# The 15-minute Groww candles saved by the multi-year history fetch (app.market.history_loader)
_GROWW_SYMBOLS = {
    "NIFTY": "NSE-NIFTY",
    "BANKNIFTY": "NSE-BANKNIFTY",
    "SENSEX": "BSE-SENSEX",
}
_ALIASES = {
    "NSE-NIFTY": "NIFTY", "NIFTY 50": "NIFTY", "NIFTY50": "NIFTY",
    "NSE-BANKNIFTY": "BANKNIFTY", "BANK NIFTY": "BANKNIFTY", "BANK": "BANKNIFTY",
    "BSE-SENSEX": "SENSEX",
}


# Older one-year Groww extracts, used only when the multi-year history has not been fetched
_LEGACY_GROWW_FILES = {
    "NIFTY": "derived_nifty_15m_m23_bc7d31bceebf13a3.json",
    "SENSEX": "derived_sensex_15m.json",
}


def resolve_dataset_file(inst: str) -> Path | None:
    """The saved Groww 15-minute history of an index, or None when it has not been fetched.

    Never served: derived_banknifty_15m_m40.json (SYNTHETIC: NIFTY returns plus noise, from
    m40_multi_asset_research) and derived_crude_15m.json (6,227 bars on NIFTY's exact dates in
    NSE hours, not MCX data). MCX crude has no Groww history.
    """
    from app.market import history_loader as hl
    from app.settings import REPO_ROOT

    sym = inst.upper().strip()
    sym = _ALIASES.get(sym, sym)
    symbol = _GROWW_SYMBOLS.get(sym)
    if symbol is None:
        return None
    path = hl.series_path(symbol, "15minute")
    if path.exists():
        return path
    legacy = _LEGACY_GROWW_FILES.get(sym)
    if legacy and (REPO_ROOT / "var" / "datasets" / legacy).exists():
        return REPO_ROOT / "var" / "datasets" / legacy
    return None
