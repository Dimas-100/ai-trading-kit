import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aitk.connect.guard import Guard, classify, run_http, run_stdio
from aitk.mcp.protocol import Server, Tool

from .conftest import FAKE_BROKER

WRITE_NAMES = ["place_order", "placeStockOrder", "submit_order", "cancel_all_orders", "modify_order", "replace_order",
               "create_watchlist", "add_to_watchlist", "transfer_funds", "withdraw", "close_position", "exercise_option",
               "stock_order", "crypto_trade", "buy", "sell_shares", "liquidate_all", "order_stock", "open_position",
               "update_order", "delete_watchlist"]
READ_NAMES = ["get_account", "get_positions", "get_open_orders", "order_history", "open_orders", "stock_quote",
              "account_balance", "market_clock", "list_orders", "search_symbols", "preview_order", "quotes",
              "get_order_replace_history", "equity_orders", "portfolio_summary"]


@pytest.mark.parametrize("name", WRITE_NAMES)
def test_change_tools_are_blocked_by_name(name):
    assert classify({"name": name}).allowed is False


@pytest.mark.parametrize("name", READ_NAMES)
def test_read_tools_are_kept_by_name(name):
    assert classify({"name": name}).allowed is True


def test_publisher_hints_are_honoured_conservatively():
    assert classify({"name": "account_sync", "annotations": {"readOnlyHint": False}}).allowed is False
    assert classify({"name": "thing", "annotations": {"destructiveHint": True}}).allowed is False
    assert classify({"name": "order_status", "annotations": {"readOnlyHint": True}}).allowed is True
    # a change-word in the name wins over a friendly hint
    assert classify({"name": "place_order", "annotations": {"readOnlyHint": True}}).allowed is False


def test_recipe_overrides():
    assert classify({"name": "get_account"}, deny=frozenset({"get_account"})).allowed is False
    assert classify({"name": "add_note"}, allow=frozenset({"add_note"})).allowed is True


def _tools_reply(mid, names, hints=None):
    return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
        {"name": n, "inputSchema": {}, **({"annotations": hints[n]} if hints and n in hints else {})} for n in names]}}


def test_guard_filters_tool_lists_and_refuses_calls():
    g = Guard()
    fwd, reply = g.outgoing({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert fwd and reply is None
    filtered = g.incoming(_tools_reply(7, ["get_account", "place_order", "stock_quote"]))
    assert [t["name"] for t in filtered["result"]["tools"]] == ["get_account", "stock_quote"]
    assert g.blocked == {"place_order": "its name starts with 'place'"}
    fwd, reply = g.outgoing({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "place_order"}})
    assert fwd is False and reply["result"]["isError"] is True and "read-only" in reply["result"]["content"][0]["text"]
    fwd, reply = g.outgoing({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "get_account"}})
    assert fwd is True and reply is None


def test_guard_judges_by_name_before_any_list_and_ignores_other_messages():
    g = Guard()
    fwd, reply = g.outgoing({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "cancel_order"}})
    assert fwd is False and reply["id"] == 1
    fwd, reply = g.outgoing({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "cancel_order"}})
    assert fwd is False and reply is None          # a notification gets no reply
    assert g.outgoing({"jsonrpc": "2.0", "id": 2, "method": "resources/list"}) == (True, None)
    msg = {"jsonrpc": "2.0", "id": 2, "result": {"resources": []}}
    assert g.incoming(msg) is msg


def _lines(*messages):
    return io.StringIO("".join(json.dumps(m) + "\n" for m in messages))


def test_run_stdio_end_to_end_with_a_fake_broker(tmp_path):
    env = {**os.environ, "FAKE_KEY": "from-the-vault", "FAKE_LOG_ON_STDOUT": "1"}
    stdin = _lines({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "place_order", "arguments": {}}},
                   {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_account", "arguments": {}}})
    out, err = io.StringIO(), io.StringIO()
    code = run_stdio(Guard(), [sys.executable, str(FAKE_BROKER)], env, stdin, out, err)
    assert code == 0
    replies = {m["id"]: m for m in (json.loads(line) for line in out.getvalue().splitlines())}
    assert replies[1]["result"]["serverInfo"]["name"] == "fake-broker"
    assert sorted(t["name"] for t in replies[2]["result"]["tools"]) == ["get_account", "get_positions", "stock_quote"]
    assert replies[3]["result"]["isError"] is True
    assert json.loads(replies[4]["result"]["content"][0]["text"])["env_key"] == "from-the-vault"
    assert "stray log line" in err.getvalue() and "stray" not in out.getvalue()


def test_run_stdio_reports_a_missing_program():
    out, err = io.StringIO(), io.StringIO()
    code = run_stdio(Guard(), ["definitely-not-a-program-xyz"], dict(os.environ), io.StringIO(""), out, err)
    assert code == 127 and "could not start" in err.getvalue() and out.getvalue() == ""


# ── http ──────────────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    server_impl = None
    seen_headers = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        _Handler.seen_headers.append(dict(self.headers))
        raw = self.rfile.read(int(self.headers["Content-Length"]))     # always drain the body first
        if self.headers.get("API_KEY") != "good":
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.loads(raw)
        reply = _Handler.server_impl.handle(body)
        if reply is None:
            self.send_response(202)
            self.end_headers()
            return
        data = json.dumps(reply).encode()
        self.send_response(200)
        if body.get("method") == "tools/list":            # answer this one as an event stream
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"event: message\ndata: " + data + b"\n\n")
            return
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "sess-1")
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def http_broker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fake_broker_mcp", FAKE_BROKER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _Handler.server_impl = mod.build()
    _Handler.seen_headers = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_port}/mcp"
    httpd.shutdown()


def test_run_http_end_to_end(http_broker):
    stdin = _lines({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                   {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "cancel_order", "arguments": {}}},
                   {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "stock_quote", "arguments": {}}})
    out, err = io.StringIO(), io.StringIO()
    code = run_http(Guard(), http_broker, {"API_KEY": "good", "PAPER_TRADING": "true"}, stdin, out, err)
    assert code == 0
    replies = {m["id"]: m for m in (json.loads(line) for line in out.getvalue().splitlines())}
    assert replies[1]["result"]["serverInfo"]["name"] == "fake-broker"
    assert sorted(t["name"] for t in replies[2]["result"]["tools"]) == ["get_account", "get_positions", "stock_quote"]
    assert replies[3]["result"]["isError"] is True
    assert json.loads(replies[4]["result"]["content"][0]["text"]) == {"price": 1.0}
    later = {k.lower(): v for k, v in _Handler.seen_headers[-1].items()}
    assert later.get("mcp-session-id") == "sess-1" and later.get("mcp-protocol-version") == "2025-06-18"
    assert later.get("paper_trading") == "true"


def test_run_http_explains_a_refused_key(http_broker):
    stdin = _lines({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    out, err = io.StringIO(), io.StringIO()
    run_http(Guard(), http_broker, {"API_KEY": "bad"}, stdin, out, err)
    reply = json.loads(out.getvalue().splitlines()[0])
    assert "refused the key" in reply["error"]["message"] and "aitk keys" in err.getvalue()


def test_read_only_tools_annotation_from_own_server():
    s = Server("x", "1")
    s.add(Tool("practice_order", "d", {"type": "object"}, lambda a: 1, read_only=False))
    hint = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"][0]["annotations"]
    assert hint["readOnlyHint"] is False
