import json
import os
import sys
from pathlib import Path

import pytest

from aitk import state, strategies
from aitk.ui import Console

ROOT = Path(__file__).resolve().parent.parent
FAKE_BROKER = Path(__file__).resolve().parent / "fake_broker_mcp.py"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An isolated kit home, secrets file and user home so no test can touch real settings."""
    kit_home = tmp_path / "kit-home"
    user_home = tmp_path / "user-home"
    user_home.mkdir()
    monkeypatch.setenv("AITK_HOME", str(kit_home))
    monkeypatch.setenv("AITK_SECRETS", "file")
    monkeypatch.setenv("AITK_USER_HOME", str(user_home))
    monkeypatch.setenv("AITK_NO_COLOR", "1")
    monkeypatch.setenv("APPDATA", str(user_home / "AppData" / "Roaming"))
    strategies._loaded.clear()
    strategies.load_errors.clear()
    for name in [m for m in sys.modules if m.startswith("aitk_user_strategy_")]:
        del sys.modules[name]
    from aitk.engine import strategy as registry
    for name in [n for n in registry._REGISTRY if n not in ("buy_hold", "donchian", "rsi2", "sma_cross")]:
        del registry._REGISTRY[name]
    return kit_home


@pytest.fixture
def user_home(home):
    return Path(os.environ["AITK_USER_HOME"])


class ScriptedConsole(Console):
    """A console fed a list of answers. Output is collected in `text`."""

    def __init__(self, answers=()):
        import io
        self._in = io.StringIO("".join(a + "\n" for a in answers))
        self._out = io.StringIO()
        super().__init__(stdin=self._in, stdout=self._out, width=100, color=False)

    @property
    def text(self) -> str:
        return self._out.getvalue()


@pytest.fixture
def scripted():
    return ScriptedConsole


class MemoryStore:
    kind = "memory"
    label = "a test store"

    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, broker, key):
        return self.data.get(f"{broker}:{key}")

    def set(self, broker, key, value):
        self.data[f"{broker}:{key}"] = value

    def delete(self, broker, key):
        return self.data.pop(f"{broker}:{key}", None) is not None


@pytest.fixture
def store():
    return MemoryStore()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fresh_state(home):
    state.save({"connections": [], "done": {}})
    return home
