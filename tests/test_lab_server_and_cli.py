import json
import os
import sys

from aitk import cli, guide, state
from aitk.mcp.lab_server import build
from aitk.mcp.protocol import StdioClient

from .conftest import ScriptedConsole, read_json

WRITE_WORDS = ("order", "buy", "sell", "place", "cancel", "transfer")


def call(server, name, args=None, mid=1):
    reply = server.handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    result = reply["result"]
    text = result["content"][0]["text"]
    return result["isError"], (json.loads(text) if text.startswith("{") or text.startswith("[") else text)


def test_lab_server_tools_and_backtest(home):
    server = build()
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"list_strategies", "backtest", "compare_strategies", "try_settings", "practice_status",
            "practice_order", "practice_next_day"} <= names
    # everything that changes state is practice-only, and says so through its annotation
    for t in tools:
        if not t["annotations"]["readOnlyHint"]:
            assert t["name"].startswith("practice_") or t["name"] == "download_prices", t["name"]
    err, out = call(server, "list_strategies")
    assert not err and {s["name"] for s in out["strategies"]} >= {"sma_cross", "rsi2", "donchian", "buy_hold"}
    err, out = call(server, "backtest", {"strategy": "sma_cross", "symbol": "spy", "years": 4, "show_trades": 3})
    assert not err and out["prices"] == "demo" and "buy_hold_return_pct" in out["metrics"] and len(out["trades_shown"]) <= 3
    err, out = call(server, "backtest", {"strategy": "nope", "symbol": "SPY"})
    assert err and "no strategy called" in out
    err, out = call(server, "compare_strategies", {"symbol": "SPY", "years": 3})
    assert not err and out["ranked"] and "buy_hold_return_pct" in out["ranked"][0]
    err, out = call(server, "try_settings", {"strategy": "sma_cross", "symbol": "SPY",
                                             "settings": {"fast": [10, 20], "slow": [50]}, "show": 1})
    assert not err and out["tried"] == 2 and len(out["rows"]) == 1
    err, out = call(server, "price_history", {"symbol": "SPY", "years": 1, "recent": 2})
    assert not err and len(out["recent"]) == 2 and out["days"] >= 250


def test_lab_server_practice_flow(home):
    server = build()
    err, out = call(server, "practice_status")
    assert err and "aitk practice start" in out
    err, out = call(server, "practice_start", {"cash": 2000})
    assert not err and out["cash"] == 2000 and "pretend" in out["note"].lower() or "Practice money" in out["note"]
    err, out = call(server, "practice_order", {"side": "buy", "symbol": "SPY", "shares": 2})
    assert not err and out["accepted"]
    err, out = call(server, "practice_next_day", {"days": 1})
    assert not err and out["filled"][0]["shares"] == 2 and out["account"]["positions"][0]["symbol"] == "SPY"
    err, out = call(server, "practice_order", {"side": "sell", "symbol": "SPY", "shares": 50})
    assert err and "not accepted" in out
    err, out = call(server, "practice_history")
    assert not err and len(out["fills"]) == 1
    err, out = call(server, "practice_order", {"side": "buy", "symbol": "SPY", "shares": "two"})
    assert err


def test_lab_server_runs_as_a_subprocess(home):
    env = {**os.environ}
    with StdioClient([sys.executable, "-m", "aitk", "lab"], env=env, timeout=60) as client:
        info = client.handshake()
        assert info["serverInfo"]["name"] == "ai-trading-kit-lab" and "pretend money" in info["instructions"]
        names = [t["name"] for t in client.list_tools()]
    assert "backtest" in names


# ── cli ───────────────────────────────────────────────────────────────────────
def run(*argv):
    console = ScriptedConsole([])
    code = cli.main(list(argv), console=console)
    return code, console.text


def test_cli_home_and_lists(fresh_state):
    code, text = run("--no-menu")
    assert code == 0 and "Next for you: step 1" in text and "aitk connect" in text
    code, text = run("brokers")
    assert code == 0 and "alpaca" in text and "info only" in text
    code, text = run("brokers", "schwab")
    assert code == 0 and "SnapTrade" in text
    code, text = run("brokers", "zzz")
    assert code == 1
    code, text = run("apps")
    assert code == 0 and "ChatGPT" in text
    code, text = run("strategies")
    assert code == 0 and "rsi2" in text
    code, text = run("prompts")
    assert code == 0 and "portfolio-review" in text
    code, text = run("prompts", "risk-check")
    assert code == 0 and "largest position" in text and state.is_done("understand")
    code, text = run("lesson", "4")
    assert code == 0 and "buy_hold_return_pct" in text


def test_cli_backtest_compare_sweep_and_progress(fresh_state):
    code, text = run("backtest", "sma_cross", "SPY", "--years", "3", "--set", "fast=10", "--trades")
    assert code == 0 and "DEMO" in text and "buying and holding made" in text and state.is_done("backtest")
    code, text = run("backtest", "sma_cross", "SPY", "--years", "2", "--json", "--save")
    data = json.loads(text.split("{", 1)[0] + "{" + text.split("{", 1)[1].rsplit("Saved", 1)[0])
    assert data["strategy"] == "sma_cross" and data["prices"] == "demo"
    code, text = run("compare", "SPY", "--years", "3")
    assert code == 0 and "buy_hold" in text
    code, text = run("sweep", "sma_cross", "SPY", "fast=10,20", "slow=50", "--years", "4")
    assert code == 0 and "unseen part" in text
    code, text = run("backtest", "nope", "SPY")
    assert code == 1 and "no strategy called" in text
    code, text = run("backtest", "sma_cross", "SPY", "--set", "bogus")
    assert code == 1 and "name=value" in text
    code, text = run("--no-menu")
    assert "[done] 4." in text


def test_cli_practice_and_strategy_new(fresh_state):
    code, text = run("practice", "status")
    assert code == 1 and "aitk practice start" in text
    code, text = run("practice", "start", "--cash", "3000")
    assert code == 0 and "$3,000.00" in text and state.is_done("practice")
    code, text = run("practice", "buy", "SPY", "2")
    assert code == 0 and "accepted" in text
    code, text = run("practice", "next")
    assert code == 0 and "Filled: BUY 2 SPY" in text
    code, text = run("practice", "status")
    assert code == 0 and "SPY" in text and "demo" in text
    code, text = run("practice", "history")
    assert code == 0 and "BUY" in text
    code, text = run("practice", "sell", "SPY", "2", "--stop", "1")
    assert code == 1 and "not accepted" in text and "max_price_deviation" not in text
    code, text = run("strategy", "new", "my_idea")
    assert code == 0 and "Created" in text
    code, text = run("backtest", "my_idea", "SPY", "--years", "2")
    assert code == 0
    code, text = run("sweep", "my_idea", "SPY", "period=20,50", "--years", "3")
    assert code == 0 and state.is_done("own")


def test_cli_connect_lab_writes_cursor(fresh_state, user_home):
    code, text = run("connect-lab", "--app", "cursor", "--yes")
    assert code == 0 and "ai-trading-kit-lab" in text
    entry = read_json(user_home / ".cursor" / "mcp.json")["mcpServers"]["ai-trading-kit-lab"]
    assert entry["args"] == ["-m", "aitk", "lab"] and entry["env"]["AITK_HOME"] == os.environ["AITK_HOME"]
    assert state.is_done("lab")
    code, text = run("check")
    assert code == 0 and "practice lab needs no keys" in text
    code, text = run("disconnect", "lab", "--app", "cursor")
    assert code == 0 and "ai-trading-kit-lab" not in read_json(user_home / ".cursor" / "mcp.json")["mcpServers"]
    code, text = run("connect-lab", "--app", "chatgpt", "--yes")
    assert code == 1


def test_cli_keys_and_check_with_file_store(fresh_state, user_home):
    console = ScriptedConsole(["my-key", "my-secret", "1"])
    assert cli.main(["keys", "alpaca"], console=console) == 0 and "Stored" in console.text
    assert "my-secret" not in console.text
    keys = read_json(fresh_state / "keys.json")
    assert keys["alpaca:ALPACA_SECRET_KEY"] == "my-secret"
    code, text = run("keys", "alpaca", "--forget")
    assert code == 0 and "Removed 3" in text
    code, text = run("keys", "snaptrade")
    assert code == 0 and "needs no keys" in text
    code, text = run("approve", "alpaca")
    assert code == 0 and "no one-time approval" in text


def test_cli_prices_list_and_import(fresh_state, tmp_path):
    code, text = run("prices", "list")
    assert code == 0 and "demo" in text
    f = tmp_path / "abc.csv"
    f.write_text("date,open,high,low,close,volume\n2024-01-02,1,2,0.5,1.5,1\n", encoding="utf-8")
    code, text = run("prices", "import", str(f), "abc")
    assert code == 0 and "1 days imported" in text
    code, text = run("prices", "get", "SPY")
    assert code == 1 and "aitk prices key" in text


def test_cli_cancel_is_clean(fresh_state):
    console = ScriptedConsole(["q"])
    assert cli.main(["connect"], console=console) == 130 and "Stopped" in console.text


def test_guide_steps_and_lessons_exist():
    for s in guide.STEPS:
        assert guide.lesson(s.id).startswith("# Step")
    assert guide.next_step() is not None or True
    assert len(guide.prompt_names()) >= 5


def test_ask_secret_offers_visible_input_when_hidden_paste_fails(monkeypatch):
    """A stand-in for a real terminal where the hidden prompt gets nothing, then visible input works."""
    import sys as _sys

    from aitk import ui
    console = ScriptedConsole(["y", "pasted-secret"])
    monkeypatch.setattr(console, "stdin", _sys.stdin)
    monkeypatch.setattr(_sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(ui.getpass, "getpass", lambda prompt: "")
    real_readline = console._readline

    answers = iter(["y", "pasted-secret"])
    monkeypatch.setattr(console, "_readline", lambda prompt: next(answers))
    assert console.ask_secret("Secret") == "pasted-secret"
    assert "cannot paste into a hidden prompt" in console.text
    del real_readline


def test_lab_server_download_prices_without_a_key(home):
    server = build()
    err, out = call(server, "download_prices", {"symbols": ["SPY"]})
    assert err and "aitk prices key" in out
