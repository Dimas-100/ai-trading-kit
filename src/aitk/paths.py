"""Where the kit keeps a person's own files. Everything lives under one home folder, outside the
repository, so nothing personal can be committed by accident and an AI app that starts the kit from
any working directory still finds the same practice account.

Set AITK_HOME to move it (the tests do)."""
from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "AITK_HOME"


def home() -> Path:
    raw = os.environ.get(ENV_HOME, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".ai-trading-kit"


def kit_command(*args: str) -> tuple[str, list[str]]:
    """How another program (an AI app) starts the kit: the frozen one-file build runs itself, a normal
    install runs `python -m aitk`."""
    import sys
    if getattr(sys, "frozen", False):
        return sys.executable, list(args)
    return sys.executable, ["-m", "aitk", *args]


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file() -> Path:
    return home() / "state.json"


def paper_file() -> Path:
    return home() / "practice" / "account.json"


def prices_dir() -> Path:
    return home() / "prices"


def reports_dir() -> Path:
    return home() / "reports"


def strategies_dir() -> Path:
    return home() / "strategies"


def backups_dir() -> Path:
    return home() / "backups"


def fallback_secrets_file() -> Path:
    return home() / "keys.json"
