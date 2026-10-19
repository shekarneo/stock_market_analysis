from __future__ import annotations

from pathlib import Path
from app.settings import REPO_ROOT


def resolve_dataset_file(inst: str) -> Path | None:
    sym = inst.upper().strip()
    if sym in {"NIFTY", "NSE-NIFTY", "NIFTY 50", "NIFTY50"}:
        p = REPO_ROOT / "var/datasets/derived_nifty_15m_m23_bc7d31bceebf13a3.json"
        return p if p.exists() else None
    elif sym in {"BANKNIFTY", "NSE-BANKNIFTY", "BANK NIFTY", "BANK"}:
        p = REPO_ROOT / "var/datasets/derived_banknifty_15m_m40.json"
        return p if p.exists() else None
    elif sym in {"SENSEX", "BSE-SENSEX"}:
        p = REPO_ROOT / "var/datasets/derived_sensex_15m.json"
        return p if p.exists() else None
    elif sym in {"CRUDEOILMINI", "MCX-CRUDEOILMINI", "CRUDE", "CRUDEOIL"}:
        p = REPO_ROOT / "var/datasets/derived_crude_15m.json"
        return p if p.exists() else None
    return None
