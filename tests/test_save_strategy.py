"""An AI may write a strategy file; the kit fences what it may contain and test-runs it first."""
import json

import pytest

from aitk import lab, paths, strategies
from aitk.engine.data import SyntheticBars
from aitk.mcp.lab_server import build

GOOD = strategies.template("my_idea")
BARS = SyntheticBars(seed=3, n=900, start="2016-01-04").bars("SPY", 900)


def call(server, name, args=None):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    result = reply["result"]
    text = result["content"][0]["text"]
    return result["isError"], (json.loads(text) if text[:1] in "{[" else text)


def test_template_passes_validation_and_saves(home):
    assert strategies.validate_source(GOOD) == []
    out = strategies.save("my_idea", GOOD)
    assert out["saved"].endswith("my_idea.py") and out["smoke_test"]["trades"] >= 0
    assert "my_idea" in strategies.names()
    assert not list(paths.strategies_dir().glob("_checking_*"))
    report = lab.evaluate("my_idea", BARS, params={"period": 30})
    assert report.strategy == "my_idea"
    with pytest.raises(strategies.StrategyError):
        strategies.save("my_idea", GOOD)                         # exists
    assert strategies.save("my_idea", GOOD, overwrite=True)["name"] == "my_idea"
    assert strategies.read("my_idea") == GOOD


# The snippets below are strings the validator must REFUSE; none of them is ever executed.
@pytest.mark.parametrize("snippet, word", [
    ("import os\n", "imports 'os'"),
    ("import subprocess\n", "imports 'subprocess'"),
    ("from aitk.prices import download\n", "imports 'aitk.prices'"),
    ("import urllib.request\n", "imports 'urllib.request'"),
    ("x = open('a')\n", "uses 'open'"),
    ("y = eval('1')\n", "uses 'eval'"),
    ("z = __import__('os')\n", "uses '__import__'"),
    ("w = ().__class__.__subclasses__()\n", "uses '__class__'"),
])
def test_dangerous_source_is_refused(home, snippet, word):
    code = GOOD + "\n" + snippet
    problems = strategies.validate_source(code)
    assert any(word in p for p in problems), problems
    with pytest.raises(strategies.StrategyError) as exc:
        strategies.save("my_idea", code)
    assert "not saved" in str(exc.value)
    assert not (paths.strategies_dir() / "my_idea.py").exists()


def test_broken_or_mismatched_source_is_refused(home):
    with pytest.raises(strategies.StrategyError) as exc:
        strategies.save("my_idea", "def (:\n")
    assert "not valid Python" in str(exc.value)
    with pytest.raises(strategies.StrategyError) as exc:
        strategies.save("other_name", GOOD)
    assert "make them match" in str(exc.value)
    with pytest.raises(strategies.StrategyError):
        strategies.save("sma_cross", GOOD.replace('name = "my_idea"', 'name = "sma_cross"'))
    no_register = GOOD.replace("@register\n", "")
    with pytest.raises(strategies.StrategyError) as exc:
        strategies.save("my_idea", no_register)
    assert "@register" in str(exc.value)
    crashes = GOOD.replace("        return self.period + 1", "        return 1 / 0")
    with pytest.raises(strategies.StrategyError) as exc:
        strategies.save("my_idea", crashes)
    assert "failed when run" in str(exc.value) and "ZeroDivisionError" in str(exc.value)
    assert not (paths.strategies_dir() / "my_idea.py").exists()
    assert not list(paths.strategies_dir().glob("_checking_*"))
    assert "my_idea" not in strategies.names()


def test_lab_server_can_write_and_read_a_strategy(home):
    server = build()
    err, out = call(server, "strategy_template", {"name": "dip_buyer"})
    assert not err and 'name = "dip_buyer"' in out["template"] and out["rules"]
    err, out = call(server, "save_strategy", {"name": "dip_buyer", "code": out["template"]})
    assert not err and out["name"] == "dip_buyer" and "aitk backtest dip_buyer" in out["next"]
    err, out = call(server, "read_strategy", {"name": "dip_buyer"})
    assert not err and "@register" in out["code"]
    err, out = call(server, "backtest", {"strategy": "dip_buyer", "symbol": "SPY", "years": 3})
    assert not err and out["strategy"] == "dip_buyer"
    err, out = call(server, "save_strategy", {"name": "dip_buyer", "code": "import os\n" + GOOD})
    assert err and "imports 'os'" in out
    init = server.handle({"jsonrpc": "2.0", "id": 9, "method": "initialize", "params": {}})
    assert "save_strategy" in init["result"]["instructions"]
