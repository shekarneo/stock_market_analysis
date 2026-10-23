"""Out-of-band halt switch: stops new entries without the database, the API, or the UI.

Two independent inputs, both read from the local filesystem on every check:

1. Halt file (software sentinel). If the file exists, entries are halted.
   Path: IMM_HALT_FILE, default <repo>/var/run/HALT. Create it with
   `python -m app.cli halt trip --reason "..."` or simply `touch var/run/HALT`;
   remove it with `python -m app.cli halt clear` or `rm`.

2. GPIO-style input (hardware). Point IMM_HALT_GPIO_PATH at a file whose content
   is the input level, e.g. /sys/class/gpio/gpio17/value on a Raspberry Pi wired to
   a physical switch, or any file a watchdog writes. When its content equals
   IMM_HALT_GPIO_ACTIVE (default "1"), entries are halted. If the path is
   configured but cannot be read, entries are halted too (fail closed).

Exits are never blocked by this switch, so open positions can still be closed.
The app never clears a GPIO input; it only reads it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.settings import REPO_ROOT

HALT_FILE_ENV = "IMM_HALT_FILE"
GPIO_PATH_ENV = "IMM_HALT_GPIO_PATH"
GPIO_ACTIVE_ENV = "IMM_HALT_GPIO_ACTIVE"
DEFAULT_HALT_FILE = REPO_ROOT / "var" / "run" / "HALT"


def halt_file_path() -> Path:
    configured = os.environ.get(HALT_FILE_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_HALT_FILE


def external_halt_status() -> dict:
    """Current state of the out-of-band switch. Never raises."""
    reasons: list[str] = []
    notes: list[str] = []
    halt_file = halt_file_path()
    try:
        if halt_file.exists():
            reasons.append("HALT_FILE_PRESENT")
            try:
                first = halt_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                if first:
                    notes.append(first[0][:200])
            except OSError:
                pass
    except OSError:
        # Cannot even stat the path: treat as halted rather than assume it is clear
        reasons.append("HALT_FILE_UNREADABLE")

    gpio_path = os.environ.get(GPIO_PATH_ENV, "").strip()
    gpio_active = os.environ.get(GPIO_ACTIVE_ENV, "1").strip() or "1"
    gpio_level = None
    if gpio_path:
        try:
            gpio_level = Path(gpio_path).read_text(encoding="utf-8", errors="replace").strip()
            if gpio_level == gpio_active:
                reasons.append("HALT_GPIO_ACTIVE")
        except OSError:
            reasons.append("HALT_GPIO_UNREADABLE")

    return {
        "halted": bool(reasons),
        "reasons": reasons,
        "note": notes[0] if notes else None,
        "halt_file": str(halt_file),
        "gpio_path": gpio_path or None,
        "gpio_active_value": gpio_active if gpio_path else None,
        "gpio_level": gpio_level,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def trip_halt_file(reason: str, *, actor: str = "operator") -> Path:
    """Create the halt file with an audit line. Works without the database."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A reason is required to trip the halt switch.")
    path = halt_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    path.write_text(f"{reason.strip()} (by {actor} at {stamp})\n", encoding="utf-8")
    return path


def clear_halt_file() -> bool:
    """Remove the halt file. Returns False if it was not present. Does not touch GPIO."""
    path = halt_file_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
