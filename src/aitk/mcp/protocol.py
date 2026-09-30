"""The smallest correct piece of the Model Context Protocol the kit needs, over stdio.

MCP's stdio transport is JSON-RPC 2.0, one JSON object per line, UTF-8, no embedded newlines. This
module has both halves: a `Server` (the kit's own practice-lab tools) and a `StdioClient` (used by
`aitk doctor` to start a broker's connector and look at the tools it offers). No dependencies."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


class ToolError(Exception):
    """A tool could not do what was asked. The message is shown to the AI, so write it for a person."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], object]
    read_only: bool = True


@dataclass
class Server:
    name: str
    version: str
    instructions: str = ""
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    # ── one message in, zero or one message out ───────────────────────────────
    def handle(self, message: dict) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        method, mid = message.get("method"), message.get("id")
        is_notification = "id" not in message
        if method is None:
            return None                       # a response to something we never asked: ignore
        params = message.get("params") or {}
        try:
            result = self._dispatch(method, params)
        except _RpcError as exc:
            return None if is_notification else _error(mid, exc.code, exc.message)
        except Exception as exc:              # never let a bug take the connection down
            return None if is_notification else _error(mid, INTERNAL_ERROR, f"internal error: {exc}")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _dispatch(self, method: str, params: dict):
        if method == "initialize":
            asked = str(params.get("protocolVersion") or "")
            version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
            out = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": self.name, "version": self.version}}
            if self.instructions:
                out["instructions"] = self.instructions
            return out
        if method == "ping":
            return {}
        if method.startswith("notifications/"):
            return {}
        if method == "tools/list":
            return {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema,
                               "annotations": {"readOnlyHint": t.read_only, "destructiveHint": False,
                                               "openWorldHint": False}}
                              for t in self.tools.values()]}
        if method == "tools/call":
            name = params.get("name")
            tool = self.tools.get(name)
            if tool is None:
                raise _RpcError(INVALID_PARAMS, f"unknown tool: {name}")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                raise _RpcError(INVALID_PARAMS, "arguments must be an object")
            try:
                value = tool.handler(args)
            except ToolError as exc:
                return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            except Exception as exc:
                return {"content": [{"type": "text", "text": f"{name} failed: {exc}"}], "isError": True}
            text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        if method in ("resources/list", "prompts/list"):
            return {method.split("/")[0]: []}
        raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")

    # ── the stdio loop ────────────────────────────────────────────────────────
    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin if stdin is not None else sys.stdin
        stdout = stdout if stdout is not None else sys.stdout
        for stream in (stdin, stdout):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure:
                try:
                    reconfigure(encoding="utf-8", newline="\n")
                except (ValueError, OSError):
                    pass
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                reply = _error(None, PARSE_ERROR, "could not parse JSON")
            else:
                if isinstance(message, list):
                    replies = [r for r in (self.handle(m) for m in message) if r is not None]
                    reply = replies or None
                else:
                    reply = self.handle(message)
            if reply is not None:
                stdout.write(json.dumps(reply, separators=(",", ":"), ensure_ascii=False) + "\n")
                stdout.flush()


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


# ── client ────────────────────────────────────────────────────────────────────
class ClientError(RuntimeError):
    pass


class StdioClient:
    """Start a connector, shake hands, list its tools, stop it. Used only to CHECK a connection."""

    def __init__(self, command: list[str], env: dict | None = None, timeout: float = 45.0, cwd: str | None = None):
        self.command, self.env, self.timeout, self.cwd = command, env, timeout, cwd
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._stderr: list[str] = []
        self._next_id = 0

    def __enter__(self):
        try:
            self._proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, env=self.env, cwd=self.cwd,
                                          text=True, encoding="utf-8", errors="replace", bufsize=1)
        except (OSError, ValueError) as exc:
            raise ClientError(f"could not start {self.command[0]}: {exc}") from exc
        threading.Thread(target=self._pump, args=(self._proc.stdout, self._lines.put), daemon=True).start()
        threading.Thread(target=self._pump, args=(self._proc.stderr, self._stderr.append), daemon=True).start()
        return self

    @staticmethod
    def _pump(stream, sink) -> None:
        try:
            for line in stream:
                sink(line)
        except (OSError, ValueError):
            pass
        if sink.__name__ == "put":
            sink(None)

    def __exit__(self, *exc) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass

    def stderr_tail(self, lines: int = 6) -> str:
        return "".join(self._stderr[-lines:]).strip()

    def _send(self, payload: dict) -> None:
        try:
            self._proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise ClientError(f"the connector stopped before it answered. {self.stderr_tail()}".strip()) from exc

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        mid = self._next_id
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
        while True:
            try:
                line = self._lines.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise ClientError(f"no answer within {self.timeout:.0f} seconds") from exc
            if line is None:
                tail = self.stderr_tail()
                raise ClientError("the connector stopped before it answered" + (f": {tail}" if tail else ""))
            line = line.strip()
            if not line.startswith("{"):
                continue                      # a log line on stdout: not ours
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") != mid:
                continue                      # a notification or a request to us: not needed for a check
            if "error" in message:
                raise ClientError(str(message["error"].get("message", message["error"])))
            return message.get("result") or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def handshake(self) -> dict:
        info = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": {"name": "ai-trading-kit-doctor", "version": "0.1.0"}})
        self.notify("notifications/initialized")
        return info

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(50):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools
