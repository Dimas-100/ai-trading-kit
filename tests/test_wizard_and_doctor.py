import json
import sys
import urllib.error

from aitk import state
from aitk.connect import apps as apps_mod
from aitk.connect import doctor, wizard
from aitk.connect.doctor import ConnectionReport
from aitk.connect.recipes import get

from .conftest import FAKE_BROKER, MemoryStore, read_json


def good_report(recipe, store, **_):
    return ConnectionReport(True, "Connected. 3 tools are available", "fake", ("get_account",), (("place_order", "x"),))


def test_wizard_full_run_with_cursor(fresh_state, user_home, scripted, monkeypatch):
    monkeypatch.setattr(doctor, "check_connection", good_report)
    monkeypatch.setattr(wizard.launcher, "missing_programs", lambda r, which=None: [])
    # answers: app=cursor(3), broker=alpaca(1), pause, key, secret, paper=true(1), add it? y
    console = scripted(["3", "1", "", "my-key", "my-secret", "1", "y"])
    store = MemoryStore()
    result = wizard.run(console, store=store)
    assert result.ok, console.text
    assert store.data["alpaca:ALPACA_API_KEY"] == "my-key" and store.data["alpaca:ALPACA_PAPER_TRADE"] == "true"
    servers = read_json(user_home / ".cursor" / "mcp.json")["mcpServers"]
    entry = servers["alpaca-readonly"]
    assert entry["command"] == sys.executable and entry["args"][-2:] == ["run-connector", "alpaca"]
    assert "my-secret" not in console.text and "my-secret" not in json.dumps(servers)
    assert "removed" in console.text.lower() and "place_order" in console.text
    assert state.load()["connections"][0]["broker"] == "alpaca" and state.is_done("connect")


def test_wizard_presets_and_yes_skip_prompts(fresh_state, user_home, scripted, monkeypatch):
    monkeypatch.setattr(wizard.launcher, "missing_programs", lambda r, which=None: [])
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    console = scripted([])
    result = wizard.run(console, broker="alpaca", app_id="cursor", yes=True, skip_test=True, store=store)
    assert result.ok, console.text
    assert "alpaca-readonly" in read_json(user_home / ".cursor" / "mcp.json")["mcpServers"]


def test_wizard_declines_a_not_read_only_broker_by_default(fresh_state, user_home, scripted):
    console = scripted([""])           # Continue anyway? -> default No
    result = wizard.run(console, broker="robinhood", app_id="cursor", store=MemoryStore())
    assert not result.ok and "NOT read-only" in console.text and "Nothing was changed" in console.text
    assert not (user_home / ".cursor" / "mcp.json").exists()


def test_wizard_sign_in_broker_gives_steps_for_claude_desktop(fresh_state, user_home, scripted, monkeypatch):
    monkeypatch.setattr(doctor, "check_reachable", lambda r, **k: ConnectionReport(True, "The address answers."))
    console = scripted(["", "y"])      # pause; (no keys); add? not asked for remote
    result = wizard.run(console, broker="snaptrade", app_id="claude-desktop", store=MemoryStore())
    assert result.ok, console.text
    assert "Add custom connector" in console.text and "https://mcp.snaptrade.com/mcp" in console.text
    assert state.load()["connections"][0]["server_name"] == "snaptrade-readonly"


def test_wizard_chatgpt_cannot_use_a_local_broker(fresh_state, scripted):
    console = scripted([])
    result = wizard.run(console, broker="alpaca", app_id="chatgpt", store=MemoryStore())
    assert not result.ok and "sign in" in console.text.lower()


def test_wizard_other_broker_path_explains_fidelity(fresh_state, user_home, scripted, monkeypatch):
    monkeypatch.setattr(doctor, "check_reachable", lambda r, **k: ConnectionReport(True, "ok"))
    # app cursor(3); broker "other" is the last choice; type fidelity; set up snaptrade? y; pause
    ready = [r for r in wizard.load_all().values()]
    console = scripted(["3", str(len([r for r in ready if r.status == "ready"
                                      and wizard._usable(r, apps_mod.Cursor())[0]]) + 1), "fidelity", "y", ""])
    result = wizard.run(console, store=MemoryStore())
    assert result.ok and result.broker == "snaptrade", console.text
    assert "no official connector" in console.text


def test_wizard_failed_test_is_not_added_unless_asked(fresh_state, user_home, scripted, monkeypatch):
    monkeypatch.setattr(doctor, "check_connection",
                        lambda r, s, **k: ConnectionReport(False, "The connector did not answer", fix="try again"))
    monkeypatch.setattr(wizard.launcher, "missing_programs", lambda r, which=None: [])
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    console = scripted(["", "", ""])   # pause; enter keys again? No; add anyway? No
    result = wizard.run(console, broker="alpaca", app_id="cursor", store=store)
    assert not result.ok and "keys stay stored" in console.text
    assert not (user_home / ".cursor" / "mcp.json").exists()


def test_wizard_missing_program_stops_cleanly(fresh_state, scripted, monkeypatch):
    monkeypatch.setattr(wizard.launcher, "missing_programs", lambda r, which=None: ["uvx"])
    console = scripted([""])           # check again? -> No
    result = wizard.run(console, broker="alpaca", app_id="cursor", store=MemoryStore())
    assert not result.ok and "astral.sh/uv" in console.text


def test_wizard_cancel_at_a_question(fresh_state, scripted):
    console = scripted(["q"])
    from aitk.ui import Cancelled
    try:
        wizard.run(console, store=MemoryStore())
    except Cancelled:
        pass
    else:
        raise AssertionError("q should cancel")


# ── doctor ────────────────────────────────────────────────────────────────────
def test_check_connection_stdio_uses_the_fake_broker(monkeypatch):
    alpaca = get("alpaca")
    fake = alpaca.__class__(**{**alpaca.__dict__, "command": (sys.executable, str(FAKE_BROKER)), "needs": ()})
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    report = doctor.check_connection(fake, store)
    assert report.ok and report.server == "fake-broker"
    assert set(report.kept) == {"get_account", "get_positions", "stock_quote"}
    assert {n for n, _ in report.removed} == {"place_order", "cancel_order", "watchlist_add"}


def test_check_connection_without_keys_or_program():
    assert doctor.check_connection(get("alpaca"), MemoryStore()).ok is False
    store = MemoryStore({"alpaca:ALPACA_API_KEY": "k", "alpaca:ALPACA_SECRET_KEY": "s"})
    import aitk.connect.launcher as launcher
    original = launcher.missing_programs
    launcher.missing_programs = lambda r, which=None: ["uvx"]
    try:
        report = doctor.check_connection(get("alpaca"), store)
    finally:
        launcher.missing_programs = original
    assert not report.ok and "uv" in report.message


def test_check_connection_http_with_fake_poster():
    store = MemoryStore({"tradier:API_KEY": "t"})

    def poster(url, headers, message, session, timeout=0):
        assert headers["API_KEY"] == "t" and headers["PAPER_TRADING"] == "true"
        if message.get("method") == "initialize":
            return [{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18",
                                                          "serverInfo": {"name": "tradier"}}}]
        if message.get("method") == "tools/list":
            return [{"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "get_quotes"}, {"name": "place_order"}]}}]
        return []

    report = doctor.check_connection(get("tradier"), store, poster=poster)
    assert report.ok and report.kept == ("get_quotes",) and report.removed[0][0] == "place_order"

    def refused(url, headers, message, session, timeout=0):
        raise urllib.error.HTTPError(url, 401, "no", {}, None)
    report = doctor.check_connection(get("tradier"), store, poster=refused)
    assert not report.ok and "refused the key" in report.message


def test_check_reachable_reads_http_codes():
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def ok(request, timeout=0):
        return Resp()
    r = doctor.check_reachable(get("snaptrade"), opener=ok)
    assert r.ok and "sign in" in r.message
    r = doctor.check_reachable(get("robinhood"), opener=ok)
    assert r.ok and "NOT read-only" in r.message

    def gone(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)
    assert doctor.check_reachable(get("snaptrade"), opener=gone).ok is False

    def unauth(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "auth", {}, None)
    assert doctor.check_reachable(get("snaptrade"), opener=unauth).ok is True

    def down(request, timeout=0):
        raise urllib.error.URLError("no route")
    assert doctor.check_reachable(get("snaptrade"), opener=down).ok is False


def test_environment_checks():
    checks = doctor.environment([get("alpaca"), get("kraken")], which=lambda n: None)
    titles = [c.title for c in checks]
    assert titles[0].startswith("Python") and any("uvx" in t or "uv" in t for t in titles)
    assert all(not c.ok for c in checks[1:]) and all(c.fix for c in checks[1:])
