import io
import json
import os
import sys

import pytest

from aitk.connect import apps as apps_mod
from aitk.connect import launcher
from aitk.connect.recipes import get

from .conftest import MemoryStore, read_json


# ── launcher ──────────────────────────────────────────────────────────────────
def test_collect_fields_reports_missing_and_applies_defaults():
    alpaca = get("alpaca")
    with pytest.raises(launcher.LaunchError) as exc:
        launcher.collect_fields(alpaca, MemoryStore())
    assert "Alpaca API key" in str(exc.value) and "aitk keys alpaca" in str(exc.value)
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    values = launcher.collect_fields(alpaca, store)
    assert values == {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_PAPER_TRADE": "true"}


def test_build_env_keeps_headers_out_and_read_only_switch_in():
    alpaca = get("alpaca")
    env = launcher.build_env(alpaca, {"ALPACA_API_KEY": "k", "ALPACA_TOOLSETS": "trading"}, base={"PATH": "p"})
    assert env["ALPACA_API_KEY"] == "k" and env["PATH"] == "p"
    assert "trading" not in env["ALPACA_TOOLSETS"]           # the recipe's switch always wins
    tradier = get("tradier")
    env = launcher.build_env(tradier, {"API_KEY": "t", "PAPER_TRADING": "true"}, base={})
    assert "API_KEY" not in env                                # header values never leak into the environment


def test_app_entry_holds_no_key_and_carries_the_home(monkeypatch):
    monkeypatch.setenv("AITK_HOME", "C:/kit-home")
    entry = launcher.app_entry(get("alpaca"))
    assert entry["command"] == sys.executable and entry["args"] == ["-m", "aitk", "run-connector", "alpaca"]
    assert entry["env"]["AITK_HOME"] == "C:/kit-home"
    assert "ALPACA" not in json.dumps(entry)


def test_run_refuses_without_keys_and_for_sign_in_brokers():
    err = io.StringIO()
    assert launcher.run("alpaca", store=MemoryStore(), stderr=err) == 2 and "missing" in err.getvalue()
    err = io.StringIO()
    assert launcher.run("snaptrade", store=MemoryStore(), stderr=err) == 2 and "address" in err.getvalue()
    err = io.StringIO()
    assert launcher.run("nope", store=MemoryStore(), stderr=err) == 2


def test_run_starts_a_stdio_connector_with_the_vault_keys(monkeypatch):
    """The Alpaca recipe with its command swapped for the fake broker: keys reach the child as environment."""
    from tests.conftest import FAKE_BROKER
    alpaca = get("alpaca")
    fake = alpaca.__class__(**{**alpaca.__dict__, "command": (sys.executable, str(FAKE_BROKER)), "needs": ()})
    monkeypatch.setattr(launcher, "get", lambda rid: fake)
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setenv("FAKE_KEY", "unused")
    assert launcher.run("alpaca", store=store, stdin=stdin, stdout=out, stderr=err) == 0
    names = [t["name"] for t in json.loads(out.getvalue())["result"]["tools"]]
    assert "place_order" not in names and "get_account" in names


def test_missing_programs_and_platform():
    assert launcher.missing_programs(get("alpaca"), which=lambda n: None) == ["uvx"]
    assert launcher.missing_programs(get("alpaca"), which=lambda n: "/bin/" + n) == []
    assert launcher.current_platform() in ("windows", "macos", "linux")


# ── apps ──────────────────────────────────────────────────────────────────────
def test_claude_desktop_writes_with_backup_and_keeps_other_entries(user_home):
    app = apps_mod.ClaudeDesktop()
    path = app.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")
    outcome = app.add_local("alpaca-readonly", {"command": "py", "args": ["-m", "aitk"]})
    assert outcome.done and outcome.backup and os.path.exists(outcome.backup) and "Quit" in outcome.restart
    data = read_json(path)
    assert data["theme"] == "dark" and set(data["mcpServers"]) == {"other", "alpaca-readonly"}
    assert app.existing("alpaca-readonly") == {"command": "py", "args": ["-m", "aitk"]}
    removed = app.remove("alpaca-readonly")
    assert removed.done and "alpaca-readonly" not in read_json(path)["mcpServers"]
    assert app.remove("alpaca-readonly").done                       # removing twice is fine


def test_claude_desktop_creates_the_file_when_absent_and_refuses_broken_json(user_home):
    app = apps_mod.ClaudeDesktop()
    outcome = app.add_local("x", {"command": "c"})
    assert outcome.done and outcome.backup == "" and read_json(app.config_path())["mcpServers"]["x"]["command"] == "c"
    app.config_path().write_text("{not json", encoding="utf-8")
    with pytest.raises(apps_mod.AppError) as exc:
        app.add_local("y", {"command": "c"})
    assert "Nothing was changed" in str(exc.value)
    assert app.config_path().read_text(encoding="utf-8") == "{not json"


def test_claude_desktop_remote_is_steps_not_a_file(user_home):
    outcome = apps_mod.ClaudeDesktop().add_remote("snaptrade", "https://mcp.snaptrade.com/mcp")
    assert outcome.done is False and any("https://mcp.snaptrade.com/mcp" in s for s in outcome.steps)


def test_cursor_writes_local_and_remote(user_home):
    app = apps_mod.Cursor()
    assert app.add_local("a", {"command": "c"}).done
    assert app.add_remote("b", "https://x/mcp").done
    data = read_json(app.config_path())["mcpServers"]
    assert data["a"] == {"command": "c"} and data["b"] == {"url": "https://x/mcp"}


def test_claude_code_uses_its_own_command():
    calls = []

    def runner(args):
        calls.append(args)
        if args[1:3] == ["mcp", "get"]:
            return 1, "not found"
        return 0, "ok"

    app = apps_mod.ClaudeCode(runner=runner, which=lambda n: "/bin/claude")
    outcome = app.add_local("alpaca-readonly", {"command": "py", "args": ["-m", "aitk"]})
    assert outcome.done
    add = next(c for c in calls if c[1:3] == ["mcp", "add-json"])
    assert add[3] == "alpaca-readonly" and json.loads(add[4]) == {"type": "stdio", "command": "py", "args": ["-m", "aitk"]}
    assert add[-2:] == ["--scope", "user"]
    remote = app.add_remote("snaptrade", "https://mcp.snaptrade.com/mcp")
    assert remote.done and any("/mcp" in s for s in remote.steps)
    assert json.loads(calls[-1][4]) == {"type": "http", "url": "https://mcp.snaptrade.com/mcp"}
    assert app.remove("alpaca-readonly").done
    assert "claude mcp add-json alpaca-readonly" in app.preview("alpaca-readonly", {"command": "py"})


def test_claude_code_missing_or_refusing():
    app = apps_mod.ClaudeCode(runner=lambda a: (0, ""), which=lambda n: None)
    assert app.add_local("x", {"command": "c"}).done is False
    app = apps_mod.ClaudeCode(runner=lambda a: (1, "boom") if "add-json" in a else (1, ""), which=lambda n: "c")
    with pytest.raises(apps_mod.AppError):
        app.add_local("x", {"command": "c"})


def test_chatgpt_gives_steps_only():
    app = apps_mod.ChatGPT()
    assert app.add_local("x", {"command": "c"}).done is False
    remote = app.add_remote("snaptrade", "https://mcp.snaptrade.com/mcp")
    assert remote.done is False and any("Developer mode" in s for s in remote.steps)
    assert app.remove("x").done is False


def test_get_app_unknown():
    with pytest.raises(apps_mod.AppError):
        apps_mod.get_app("nope")
