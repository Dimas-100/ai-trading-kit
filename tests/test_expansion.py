"""The setup-guide tools, the reality check, scenarios and the report card."""
import json

import pytest

from aitk import cli, lab, practice, prices, state
from aitk.engine.data import SyntheticBars
from aitk.engine.models import Bar
from aitk.mcp.lab_server import build

from .conftest import ScriptedConsole

BARS = SyntheticBars(seed=3, n=1500, start="2016-01-04").bars("SPY", 1500)


def call(server, name, args=None):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    result = reply["result"]
    text = result["content"][0]["text"]
    return result["isError"], (json.loads(text) if text[:1] in "{[" else text)


def test_reality_check_metrics_and_verdict():
    r = lab.evaluate("sma_cross", BARS, symbol="SPY")
    m = r.metrics
    assert m["longest_underwater_days"] >= 0 and m["longest_losing_streak"] >= 0 and m["biggest_loss"] <= 0
    text = " ".join(r.verdict)
    assert "below a previous peak" in text or m["longest_underwater_days"] < 21
    if m["longest_losing_streak"] >= 3:
        assert "losing trades in a row" in text
    if m["biggest_loss"] < 0:
        assert "biggest single loss" in text


def test_lab_guide_tools(fresh_state):
    server = build()
    err, out = call(server, "where_am_i")
    assert not err and out["next"]["number"] == 1 and out["steps"][0]["done"] is False
    err, out = call(server, "list_brokers", {"query": "fidelity"})
    assert not err and out["brokers"][0]["id"] == "snaptrade"
    err, out = call(server, "list_brokers", {"query": "zzz"})
    assert not err and out["brokers"] == [] and "SnapTrade" in out["note"]
    err, out = call(server, "setup_guide", {"broker": "alpaca", "app": "cursor"})
    assert not err and out["then_run_in_a_terminal"] == "aitk connect --broker alpaca --app cursor"
    assert "Never paste a key" in out["rule"] and "Alpaca API secret" in out["the_wizard_will_ask_for"]
    err, out = call(server, "setup_guide", {"broker": "alpaca", "app": "chatgpt"})
    assert not err and "ChatGPT cannot" in out["note"]
    err, out = call(server, "setup_guide", {"broker": "tastytrade"})
    assert not err and out["ready"] is False and out["advice"]
    err, out = call(server, "setup_guide", {"broker": "nope"})
    assert err
    err, out = call(server, "check_connections")
    assert not err and out["connections"] == [] and "setup_guide" in out["note"]
    state.add_connection("lab", "cursor", "ai-trading-kit-lab")
    err, out = call(server, "check_connections")
    assert not err and out["connections"][0]["ok"] is True
    names = {t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"where_am_i", "list_brokers", "setup_guide", "check_connections", "practice_report",
            "practice_scenarios", "download_prices"} <= names
    # the instructions forbid asking for keys in chat
    init = server.handle({"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}})
    assert "NEVER ask the person to paste an API key" in init["result"]["instructions"]


def _real_spy(home):
    """A price file that covers the scenario dates, so scenarios work without demo prices."""
    bars = SyntheticBars(seed=5, n=2200, start="2019-01-02").bars("SPY", 2200)
    prices.write_csv("SPY", bars)


def test_scenarios_and_report(home):
    acct = practice.Practice()
    with pytest.raises(practice.PracticeError) as exc:
        acct.start(scenario="2022-bear")
    assert "real prices" in str(exc.value)
    _real_spy(home)
    acct = practice.Practice()
    with pytest.raises(practice.PracticeError):
        acct.start(scenario="nope")
    st = acct.start(scenario="2022-bear")
    assert st.today == "2022-01-03"
    rep = acct.report()
    assert rep["scenario"] == "2022-bear" and rep["trading_days"] == 0 and "Time has not moved" in rep["verdict"][0]
    acct.order("buy", "SPY", 5)
    acct.advance(20)
    rep = acct.report()
    assert rep["fills"] == 1 and rep["trading_days"] == 20 and rep["hold_symbol"] == "SPY"
    assert isinstance(rep["you_pct"], float) and isinstance(rep["hold_pct"], float)
    assert any("holding SPY" in v for v in rep["verdict"])
    acct.order("sell", "SPY", 5)
    acct.advance(1)
    rep = acct.report()
    assert rep["open_positions"] == 0 and rep["fills"] == 2 and "realized" in rep["verdict"][1]


def test_scenario_before_price_history(home):
    prices.write_csv("SPY", [Bar(f"2024-01-{d:02d}", 1, 2, 0.5, 1.5, 1) for d in range(2, 31) if d not in (6, 7, 13, 14, 20, 21, 27, 28)]
                     + SyntheticBars(seed=1, n=400, start="2024-02-01").bars("SPY", 400))
    with pytest.raises(practice.PracticeError) as exc:
        practice.Practice().start(scenario="2020-crash")
    assert "tiingo" in str(exc.value).lower()


def test_lab_server_scenarios_and_report(home):
    _real_spy(home)
    server = build()
    err, out = call(server, "practice_scenarios")
    assert not err and any(s["name"] == "2020-crash" for s in out["scenarios"])
    err, out = call(server, "practice_start", {"scenario": "2023-rally", "cash": 5000})
    assert not err and out["today"] == "2023-01-03"
    err, out = call(server, "practice_report")
    assert not err and out["scenario"] == "2023-rally"


def run(*argv):
    console = ScriptedConsole([])
    return cli.main(list(argv), console=console), console.text


def test_cli_new_commands(fresh_state):
    code, text = run("where")
    assert code == 0 and "price files" in text
    code, text = run("practice", "scenarios")
    assert code == 0 and "2022-bear" in text
    code, text = run("practice", "start", "--scenario", "2022-bear")
    assert code == 1 and "real prices" in text
    _real_spy(fresh_state)
    code, text = run("practice", "start", "--scenario", "2022-bear")
    assert code == 0 and "2022-01-03" in text and "grind" in text
    code, text = run("practice", "report")
    assert code == 0 and "Report card" in text and "Time has not moved" in text
    code, text = run("prompts", "retirement-check")
    assert code == 0 and "retire" in text
    code, text = run("--no-menu")
    assert "1 of 6 steps done" in text or "steps done" in text
