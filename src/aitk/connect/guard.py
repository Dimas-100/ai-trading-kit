"""The read-only guard.

The AI app does not talk to a broker's connector directly. It talks to this guard, which passes
messages through and does two things on the way:

1. it removes from the tool list every tool that could change an account, so the AI never sees them;
2. it refuses a call to such a tool even if one is attempted by name.

The rule is deliberately cautious: when the guard cannot tell, a tool whose name starts with a
change-word is removed. A recipe can correct single tools with allow_tools / deny_tools.

Pure logic lives in `Guard`; `run_stdio` and `run_http` are the two ways of reaching a connector."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field

READ_VERBS = frozenset("""get list read fetch search query show describe view lookup find check preview
    calculate compute estimate screen scan quote quotes""".split())
WRITE_WORDS = frozenset("""place submit create cancel replace modify update delete remove close liquidate buy
    sell transfer withdraw deposit exercise add set revoke send move edit amend execute rebalance allocate
    fund pay redeem convert swap stake unstake borrow repay enable disable reset link unlink approve sign
    write upload import register trade order new put post patch open short cover roll flatten exit square""".split())
# Words that count as a change only when they LEAD the name: "get_open_orders" is a read.
LEADING_ONLY = frozenset({"trade", "order", "new", "put", "post", "patch", "open", "short", "cover", "roll",
                          "set", "add", "link", "sign", "fund", "move", "close", "update", "import"})
# Leading words that are as often a noun as a verb ("order_history", "open_orders"). They are kept only
# when the rest of the name says it is a lookup, or the publisher marks the tool read-only.
AMBIGUOUS_LEAD = frozenset({"order", "trade", "open", "short", "put", "new", "post", "cover", "roll", "fund"})
READ_NOUNS = frozenset("""status history list detail details info orders trades positions interest book chain
    chains quote quotes summary preview activity activities balance balances""".split())

_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def words(name: str) -> list[str]:
    return [w.lower() for w in _SPLIT.split(str(name)) if w]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def classify(tool: dict, allow: frozenset = frozenset(), deny: frozenset = frozenset()) -> Decision:
    name = str(tool.get("name", ""))
    if name in deny:
        return Decision(False, "removed by this broker's recipe")
    if name in allow:
        return Decision(True, "kept by this broker's recipe")
    hints = tool.get("annotations") or {}
    parts = words(name)
    if not parts:
        return Decision(False, "it has no name")
    if hints.get("readOnlyHint") is False:
        return Decision(False, "its publisher marks it as able to change things")
    if hints.get("destructiveHint") is True and hints.get("readOnlyHint") is not True:
        return Decision(False, "its publisher marks it as destructive")
    first = parts[0]
    if first in READ_VERBS:
        return Decision(True, f"it starts with '{first}'")
    if first in AMBIGUOUS_LEAD and (hints.get("readOnlyHint") is True or READ_NOUNS.intersection(parts[1:])):
        return Decision(True, "its name reads as a lookup")
    if first in WRITE_WORDS:
        return Decision(False, f"its name starts with '{first}'")
    if parts[-1] in ("order", "trade") and hints.get("readOnlyHint") is not True:
        return Decision(False, f"its name ends with '{parts[-1]}', which usually means sending one")
    hit = next((w for w in parts[1:] if w in WRITE_WORDS and w not in LEADING_ONLY), None)
    if hit:
        return Decision(False, f"its name contains '{hit}'")
    return Decision(True, "nothing in its name or markings suggests a change")


def refusal_text(name: str, reason: str) -> str:
    return (f"'{name}' is not available: this connection is read-only, and the tool was removed because "
            f"{reason}. Nothing was sent to the broker. Reading balances, positions, orders and prices "
            "still works.")


@dataclass
class Guard:
    allow: frozenset = frozenset()
    deny: frozenset = frozenset()
    blocked: dict = field(default_factory=dict)        # tool name -> reason
    seen: set = field(default_factory=set)             # every tool name the connector has offered
    _list_ids: set = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def decide(self, tool: dict) -> Decision:
        return classify(tool, self.allow, self.deny)

    def outgoing(self, message) -> tuple[bool, dict | None]:
        """A message from the AI app. Returns (forward it?, a reply to send back instead)."""
        if not isinstance(message, dict):
            return True, None
        method = message.get("method")
        if method == "tools/list" and "id" in message:
            with self._lock:
                self._list_ids.add(_key(message["id"]))
            return True, None
        if method == "tools/call":
            params = message.get("params") or {}
            name = str(params.get("name", ""))
            with self._lock:
                reason = self.blocked.get(name)
                known = name in self.seen
            if reason is None and not known:
                decision = self.decide({"name": name})      # called before any list: judge by name alone
                reason = None if decision.allowed else decision.reason
            if reason is not None:
                if "id" not in message:
                    return False, None
                return False, {"jsonrpc": "2.0", "id": message["id"],
                               "result": {"content": [{"type": "text", "text": refusal_text(name, reason)}],
                                          "isError": True}}
        return True, None

    def incoming(self, message):
        """A message from the connector. Tool lists are filtered; everything else passes untouched."""
        if not isinstance(message, dict) or "id" not in message:
            return message
        with self._lock:
            is_list = _key(message["id"]) in self._list_ids
            if is_list:
                self._list_ids.discard(_key(message["id"]))
        result = message.get("result")
        if not is_list or not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return message
        kept = []
        for tool in result["tools"]:
            if not isinstance(tool, dict):
                continue
            decision = self.decide(tool)
            name = str(tool.get("name", ""))
            with self._lock:
                self.seen.add(name)
                if decision.allowed:
                    self.blocked.pop(name, None)
                else:
                    self.blocked[name] = decision.reason
            if decision.allowed:
                kept.append(tool)
        return {**message, "result": {**result, "tools": kept}}


def _key(mid) -> str:
    return json.dumps(mid, sort_keys=True)


def _dump(message) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"


def _utf8(stream):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure:
        try:
            reconfigure(encoding="utf-8", newline="\n", errors="replace")
        except (ValueError, OSError):
            pass
    return stream


# ── stdio connector ───────────────────────────────────────────────────────────
def run_stdio(guard: Guard, command: list[str], env: dict, stdin=None, stdout=None, stderr=None) -> int:
    stdin = _utf8(stdin if stdin is not None else sys.stdin)
    stdout = _utf8(stdout if stdout is not None else sys.stdout)
    stderr = stderr if stderr is not None else sys.stderr
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
    except (OSError, ValueError) as exc:
        stderr.write(f"ai-trading-kit: could not start {command[0]}: {exc}\n")
        return 127
    out_lock = threading.Lock()

    def emit(message) -> None:
        with out_lock:
            stdout.write(_dump(message))
            stdout.flush()

    def from_child() -> None:
        for line in child.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except ValueError:
                stderr.write(line if line.endswith("\n") else line + "\n")   # a stray log line: keep it off stdout
                continue
            if isinstance(message, list):
                emit([guard.incoming(m) for m in message])
            else:
                emit(guard.incoming(message))

    def child_stderr() -> None:
        for line in child.stderr:          # the connector's own log lines, passed through untouched
            try:
                stderr.write(line)
                stderr.flush()
            except (OSError, ValueError):
                break

    reader = threading.Thread(target=from_child, daemon=True)
    reader.start()
    threading.Thread(target=child_stderr, daemon=True).start()
    try:
        for line in stdin:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except ValueError:
                emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "could not parse JSON"}})
                continue
            batch = message if isinstance(message, list) else [message]
            forward = []
            for m in batch:
                ok, reply = guard.outgoing(m)
                if reply is not None:
                    emit(reply)
                if ok:
                    forward.append(m)
            if not forward:
                continue
            try:
                child.stdin.write(_dump(forward if isinstance(message, list) else forward[0]))
                child.stdin.flush()
            except (OSError, ValueError):
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            child.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
        reader.join(timeout=2)
    return child.returncode or 0


# ── http connector (streamable HTTP with header keys) ─────────────────────────
def _sse_messages(body) -> list:
    out, data = [], []
    for raw in body:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif line == "" and data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    if data:
        try:
            out.append(json.loads("\n".join(data)))
        except ValueError:
            pass
    return out


def _http_problem(code: int) -> str:
    if code in (401, 403):
        return ("the broker refused the key (it may be mistyped, expired, or for the other account type). "
                "Run 'aitk keys' to enter it again")
    if code == 404:
        return "the broker's connector was not found at this address (it may have moved)"
    if code == 429:
        return "the broker says too many requests were made; wait a minute and try again"
    if code >= 500:
        return "the broker's connector is having trouble right now; try again later"
    return f"the broker answered with HTTP {code}"


def post(url: str, headers: dict, message, session: dict, timeout: float = 60.0, opener=None) -> list:
    """Send one JSON-RPC message; return the messages that came back (possibly none)."""
    body = json.dumps(message).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": "ai-trading-kit", **headers}
    if session.get("id"):
        req_headers["Mcp-Session-Id"] = session["id"]
    if session.get("version"):
        req_headers["MCP-Protocol-Version"] = session["version"]
    request = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    do = opener or urllib.request.urlopen
    with do(request, timeout=timeout) as response:
        sid = response.headers.get("Mcp-Session-Id")
        if sid:
            session["id"] = sid
        if response.status == 202:
            return []
        kind = (response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in kind:
            return _sse_messages(response)
        raw = response.read()
        if not raw.strip():
            return []
        parsed = json.loads(raw.decode("utf-8", "replace"))
        return parsed if isinstance(parsed, list) else [parsed]


def run_http(guard: Guard, url: str, headers: dict, stdin=None, stdout=None, stderr=None, opener=None) -> int:
    stdin = _utf8(stdin if stdin is not None else sys.stdin)
    stdout = _utf8(stdout if stdout is not None else sys.stdout)
    stderr = stderr if stderr is not None else sys.stderr
    session: dict = {}

    def emit(message) -> None:
        stdout.write(_dump(message))
        stdout.flush()

    for line in stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except ValueError:
            emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "could not parse JSON"}})
            continue
        for m in (message if isinstance(message, list) else [message]):
            ok, reply = guard.outgoing(m)
            if reply is not None:
                emit(reply)
            if not ok:
                continue
            try:
                answers = post(url, headers, m, session, opener=opener)
            except urllib.error.HTTPError as exc:
                problem = _http_problem(exc.code)
            except (urllib.error.URLError, OSError, ValueError) as exc:
                problem = f"could not reach the broker's connector ({getattr(exc, 'reason', exc)})"
            else:
                for a in answers:
                    if isinstance(a, dict) and isinstance(a.get("result"), dict) and m.get("method") == "initialize":
                        session["version"] = a["result"].get("protocolVersion", "")
                    emit(guard.incoming(a))
                continue
            stderr.write(f"ai-trading-kit: {problem}\n")
            if isinstance(m, dict) and "id" in m:
                emit({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32000, "message": problem}})
    return 0
