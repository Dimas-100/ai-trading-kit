import io
import json
import sys

from aitk.mcp.protocol import PROTOCOL_VERSION, ClientError, Server, StdioClient, Tool, ToolError

from .conftest import FAKE_BROKER


def server() -> Server:
    s = Server("t", "1", "be careful")
    s.add(Tool("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}}, lambda a: a))
    s.add(Tool("boom", "fails", {"type": "object"}, lambda a: (_ for _ in ()).throw(ToolError("plain words"))))
    return s


def req(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}


def test_initialize_and_tools_list():
    s = server()
    out = s.handle(req("initialize", {"protocolVersion": "2024-11-05"}))
    assert out["result"]["protocolVersion"] == "2024-11-05"
    assert out["result"]["instructions"] == "be careful"
    out = s.handle(req("initialize", {"protocolVersion": "1900-01-01"}))
    assert out["result"]["protocolVersion"] == PROTOCOL_VERSION
    tools = s.handle(req("tools/list"))["result"]["tools"]
    assert [t["name"] for t in tools] == ["echo", "boom"]
    assert tools[0]["annotations"]["readOnlyHint"] is True


def test_tools_call_success_error_and_unknown():
    s = server()
    ok = s.handle(req("tools/call", {"name": "echo", "arguments": {"x": "1"}}))
    assert ok["result"]["isError"] is False and json.loads(ok["result"]["content"][0]["text"]) == {"x": "1"}
    bad = s.handle(req("tools/call", {"name": "boom", "arguments": {}}))
    assert bad["result"]["isError"] is True and "plain words" in bad["result"]["content"][0]["text"]
    unknown = s.handle(req("tools/call", {"name": "nope"}))
    assert unknown["error"]["code"] == -32602


def test_notifications_get_no_reply_and_bad_messages_get_errors():
    s = server()
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle({"jsonrpc": "2.0", "id": 5, "result": {}}) is None
    assert s.handle({"hello": 1})["error"]["code"] == -32600
    assert s.handle(req("nope/method"))["error"]["code"] == -32601


def test_serve_over_streams():
    s = server()
    lines = [json.dumps(req("initialize", mid=1)), "not json", "", json.dumps(req("ping", mid=2))]
    out = io.StringIO()
    s.serve(io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["id"] == 1 and replies[1]["error"]["code"] == -32700 and replies[2]["id"] == 2


def test_stdio_client_against_a_real_subprocess():
    with StdioClient([sys.executable, str(FAKE_BROKER)]) as client:
        info = client.handshake()
        assert info["serverInfo"]["name"] == "fake-broker"
        names = [t["name"] for t in client.list_tools()]
    assert "place_order" in names and "get_account" in names


def test_stdio_client_reports_a_program_that_dies():
    with StdioClient([sys.executable, "-c", "import sys; sys.stderr.write('bad key\\n'); sys.exit(3)"],
                     timeout=5) as client:
        try:
            client.handshake()
        except ClientError as exc:
            assert "stopped" in str(exc) and "bad key" in str(exc)
        else:
            raise AssertionError("expected ClientError")
