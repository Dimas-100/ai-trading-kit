"""Checks that say in plain words what works and what does not.

`check_connection` starts the broker's connector the same way the AI app will, asks it which tools it
offers, and reports how many the guard keeps and which it removes. It reads nothing from the account."""
from __future__ import annotations

import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from ..mcp.protocol import PROTOCOL_VERSION, ClientError, StdioClient
from . import guard as guard_mod
from . import launcher
from .recipes import RO_NONE, Recipe

INSTALL_HELP = {
    "uvx": ("uv (it provides the 'uvx' command)",
            "Install it from https://docs.astral.sh/uv/getting-started/installation/ then open a NEW terminal."),
    "node": ("Node.js", "Install the LTS version from https://nodejs.org then open a NEW terminal."),
    "npx": ("Node.js (it provides the 'npx' command)",
            "Install the LTS version from https://nodejs.org then open a NEW terminal."),
    "kraken": ("Kraken's command-line tool",
               "Follow https://github.com/krakenfx/kraken-cli then open a NEW terminal."),
}


@dataclass(frozen=True)
class Check:
    ok: bool
    title: str
    detail: str = ""
    fix: str = ""
    warn: bool = False


@dataclass(frozen=True)
class ConnectionReport:
    ok: bool
    message: str
    server: str = ""
    kept: tuple[str, ...] = ()
    removed: tuple[tuple[str, str], ...] = ()     # (tool, reason)
    fix: str = ""
    checks: tuple[Check, ...] = field(default_factory=tuple)


def check_python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return Check(ok, f"Python {v.major}.{v.minor}.{v.micro}",
                 "" if ok else "The kit needs Python 3.11 or newer.",
                 "" if ok else "Install Python 3.11+ from https://www.python.org/downloads/")


def check_program(name: str, which=shutil.which) -> Check:
    found = which(name)
    label, fix = INSTALL_HELP.get(name, (name, f"Install '{name}' and open a NEW terminal."))
    if found:
        return Check(True, f"{label} is installed", found)
    return Check(False, f"{label} is not installed", f"The '{name}' command was not found.", fix)


def check_platform(recipe: Recipe) -> Check:
    here = launcher.current_platform()
    if here in recipe.platforms:
        return Check(True, f"{recipe.name} works on this computer")
    return Check(False, f"{recipe.name} does not run on {here}",
                 f"Its connector supports: {', '.join(recipe.platforms)}.",
                 "Choose another broker, or use a computer it supports.")


def check_keys(recipe: Recipe, store) -> Check:
    try:
        launcher.collect_fields(recipe, store)
    except launcher.LaunchError as exc:
        return Check(False, f"Keys for {recipe.name}", str(exc), f"Run: aitk keys {recipe.id}")
    if not recipe.fields:
        return Check(True, f"{recipe.name} needs no keys", "You sign in at the broker instead.")
    return Check(True, f"Keys for {recipe.name} are stored", f"Kept in {store.label}.")


def _report(recipe: Recipe, server: str, tools: list[dict]) -> ConnectionReport:
    the_guard = launcher.make_guard(recipe)
    kept, removed = [], []
    for tool in tools:
        decision = the_guard.decide(tool)
        (kept if decision.allowed else removed).append((str(tool.get("name", "")), decision.reason))
    if not tools:
        return ConnectionReport(False, "The connector started but offers no tools.", server,
                                fix="The keys may lack permission. Check them at the broker and try again.")
    if not kept:
        return ConnectionReport(False, "The connector offers only tools that change the account, so the guard "
                                       "removed all of them.", server, removed=tuple(removed),
                                fix="This usually means the keys have no read permission.")
    message = (f"Connected. {len(kept)} tools are available to your AI; {len(removed)} that could change the "
               "account were removed.")
    return ConnectionReport(True, message, server, tuple(n for n, _ in kept), tuple(removed))


def check_connection(recipe: Recipe, store, timeout: float = 60.0, client_factory=StdioClient,
                     poster=guard_mod.post) -> ConnectionReport:
    if recipe.transport == "oauth":
        return check_reachable(recipe)
    try:
        values = launcher.collect_fields(recipe, store)
    except launcher.LaunchError as exc:
        return ConnectionReport(False, str(exc), fix=f"Run: aitk keys {recipe.id}")
    init = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "ai-trading-kit-doctor", "version": "0.1.0"}}
    if recipe.transport == "http":
        headers = {k: v for k, v in values.items() if k in recipe.header_fields}
        session: dict = {}
        try:
            first = poster(recipe.url, headers, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": init},
                           session, timeout=timeout)
            info = next((m["result"] for m in first if isinstance(m, dict) and "result" in m), {})
            session["version"] = info.get("protocolVersion", "")
            poster(recipe.url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session,
                   timeout=timeout)
            listed = poster(recipe.url, headers, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                            session, timeout=timeout)
        except urllib.error.HTTPError as exc:
            return ConnectionReport(False, f"Could not connect: {guard_mod._http_problem(exc.code)}.",
                                    fix=f"Run: aitk keys {recipe.id}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return ConnectionReport(False, f"Could not reach {recipe.url} ({getattr(exc, 'reason', exc)}).",
                                    fix="Check your internet connection and try again.")
        tools = next((m["result"].get("tools", []) for m in listed
                      if isinstance(m, dict) and isinstance(m.get("result"), dict)), [])
        return _report(recipe, str((info.get("serverInfo") or {}).get("name", "")), tools)

    missing = launcher.missing_programs(recipe)
    if missing:
        c = check_program(missing[0])
        return ConnectionReport(False, f"{c.title}.", fix=c.fix)
    try:
        command = launcher.resolve_command(recipe)
    except launcher.LaunchError as exc:
        return ConnectionReport(False, str(exc))
    env = launcher.build_env(recipe, values)
    try:
        with client_factory(command, env=env, timeout=timeout) as client:
            info = client.handshake()
            tools = client.list_tools()
    except ClientError as exc:
        return ConnectionReport(False, f"The connector did not answer: {exc}",
                                fix="If this is the first run it may still be downloading: try once more. "
                                    "Otherwise check the keys at the broker.")
    return _report(recipe, str((info.get("serverInfo") or {}).get("name", "")), tools)


def check_reachable(recipe: Recipe, timeout: float = 15.0, opener=None) -> ConnectionReport:
    """A hosted, sign-in connector cannot be tested without signing in. The kit checks that the address
    answers; the sign-in happens inside the AI app."""
    request = urllib.request.Request(recipe.url, method="GET",
                                     headers={"Accept": "application/json, text/event-stream",
                                              "User-Agent": "ai-trading-kit"})
    do = opener or urllib.request.urlopen
    try:
        with do(request, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            return ConnectionReport(False, f"{recipe.name}'s connector is having trouble (HTTP {exc.code}).",
                                    fix="Try again later.")
        if exc.code == 404:
            return ConnectionReport(False, f"Nothing answers at {recipe.url}. The address may have changed.",
                                    fix=f"Check {recipe.docs_url} for the current address.")
    except (urllib.error.URLError, OSError) as exc:
        return ConnectionReport(False, f"Could not reach {recipe.url} ({getattr(exc, 'reason', exc)}).",
                                fix="Check your internet connection and try again.")
    note = "The address answers. You will sign in at the broker from inside your AI app."
    if recipe.read_only == RO_NONE:
        note += " This connection is NOT read-only."
    return ConnectionReport(True, note)


def environment(recipes: list[Recipe], which=shutil.which) -> list[Check]:
    out = [check_python()]
    for name in sorted({n for r in recipes for n in r.needs}):
        out.append(check_program(name, which))
    return out
