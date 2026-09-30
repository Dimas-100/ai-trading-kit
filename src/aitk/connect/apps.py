"""AI app adapters: how each app is told about a connection.

Three apps keep a settings file the kit can write (always after a backup, never touching entries it
did not make). ChatGPT keeps its connections inside its own settings screen, so for ChatGPT the kit
prints the exact steps instead.

A connection comes in one of two shapes:
- `local`: the app starts a program on this computer (the kit's launcher, with the guard inside);
- `remote`: the app connects to the broker's hosted address and the person signs in there."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import paths


class AppError(RuntimeError):
    pass


@dataclass(frozen=True)
class Outcome:
    done: bool                       # True: written for you. False: steps for you to follow.
    summary: str
    steps: tuple[str, ...] = ()
    backup: str = ""
    restart: str = ""


def _now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _home() -> Path:
    return Path(os.environ.get("AITK_USER_HOME") or Path.home())


def backup(path: Path) -> str:
    if not path.exists():
        return ""
    folder = paths.ensure(paths.backups_dir())
    target = folder / f"{path.name}.{_now()}.bak"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{path.name}.{_now()}-{n}.bak"
    shutil.copy2(path, target)
    return str(target)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AppError(f"{path} is not valid JSON ({exc}). Nothing was changed. Fix or remove that file, "
                       "then run the wizard again.") from exc
    if not isinstance(data, dict):
        raise AppError(f"{path} does not hold a settings object. Nothing was changed.")
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".aitk-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class JsonFileApp:
    """An app whose connections live under one key of one JSON file."""
    id = ""
    name = ""
    section = "mcpServers"
    supports_local = True
    supports_remote_in_file = False
    restart = ""

    def config_path(self) -> Path:
        raise NotImplementedError

    def installed(self) -> bool:
        return self.config_path().parent.exists()

    def remote_entry(self, url: str) -> dict:
        return {"url": url}

    def remote_steps(self, name: str, url: str) -> tuple[str, ...]:
        return ()

    def preview(self, name: str, entry: dict) -> str:
        return json.dumps({self.section: {name: entry}}, indent=2)

    def existing(self, name: str) -> dict | None:
        servers = read_json(self.config_path()).get(self.section)
        return servers.get(name) if isinstance(servers, dict) else None

    def add_local(self, name: str, entry: dict) -> Outcome:
        return self._write(name, entry)

    def add_remote(self, name: str, url: str) -> Outcome:
        if not self.supports_remote_in_file:
            return Outcome(False, f"{self.name} adds a hosted connection from its own settings screen.",
                           self.remote_steps(name, url))
        return self._write(name, self.remote_entry(url))

    def _write(self, name: str, entry: dict) -> Outcome:
        path = self.config_path()
        data = read_json(path)
        servers = data.get(self.section)
        if servers is None:
            servers = {}
        if not isinstance(servers, dict):
            raise AppError(f"'{self.section}' in {path} is not an object. Nothing was changed.")
        saved = backup(path)
        servers[name] = entry
        data[self.section] = servers
        write_json(path, data)
        return Outcome(True, f"Added '{name}' to {self.name} ({path}).", backup=saved, restart=self.restart)

    def remove(self, name: str) -> Outcome:
        path = self.config_path()
        data = read_json(path)
        servers = data.get(self.section)
        if not isinstance(servers, dict) or name not in servers:
            return Outcome(True, f"'{name}' was not in {self.name}.")
        saved = backup(path)
        del servers[name]
        write_json(path, data)
        return Outcome(True, f"Removed '{name}' from {self.name}.", backup=saved, restart=self.restart)


class ClaudeDesktop(JsonFileApp):
    id = "claude-desktop"
    name = "Claude Desktop"
    restart = "Quit Claude Desktop completely (from the tray or menu bar, not only the window) and open it again."

    def config_path(self) -> Path:
        home = _home()
        if sys.platform.startswith("win"):
            base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
            return base / "Claude" / "claude_desktop_config.json"
        if sys.platform == "darwin":
            return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        return home / ".config" / "Claude" / "claude_desktop_config.json"

    def remote_steps(self, name: str, url: str) -> tuple[str, ...]:
        return ("Open Claude Desktop (or claude.ai) and go to Settings > Connectors.",
                "Choose 'Add custom connector'.",
                f"Name: {name}",
                f"URL: {url}",
                "Choose Add, then Connect, and sign in at your broker when the page opens.",
                "When the broker asks what to allow, choose only the permissions that read.")


class Cursor(JsonFileApp):
    id = "cursor"
    name = "Cursor"
    supports_remote_in_file = True
    restart = "In Cursor, open Settings > MCP and check that the connection shows a green dot. Reload the window " \
              "if it does not."

    def config_path(self) -> Path:
        return _home() / ".cursor" / "mcp.json"

    def installed(self) -> bool:
        return (_home() / ".cursor").exists() or shutil.which("cursor") is not None


class ClaudeCode:
    """Claude Code is configured through its own command, which is the supported way."""
    id = "claude-code"
    name = "Claude Code"
    supports_local = True
    restart = "Start a new Claude Code session, then type /mcp to see the connection."

    def __init__(self, runner=None, which=shutil.which):
        self._run = runner or self._default_runner
        self._which = which

    @staticmethod
    def _default_runner(args: list[str]) -> tuple[int, str]:
        try:
            done = subprocess.run(args, capture_output=True, text=True, timeout=60, encoding="utf-8",
                                  errors="replace")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)
        return done.returncode, (done.stdout + done.stderr).strip()

    def program(self) -> str | None:
        return self._which("claude")

    def installed(self) -> bool:
        return self.program() is not None

    def preview(self, name: str, entry: dict) -> str:
        return f"claude mcp add-json {name} '{json.dumps(entry)}' --scope user"

    def remote_entry(self, url: str) -> dict:
        return {"type": "http", "url": url}

    def existing(self, name: str) -> dict | None:
        program = self.program()
        if not program:
            return None
        code, _ = self._run([program, "mcp", "get", name])
        return {"name": name} if code == 0 else None

    def _add(self, name: str, entry: dict) -> Outcome:
        program = self.program()
        if not program:
            return Outcome(False, "Claude Code is not installed on this computer (the 'claude' command was not "
                                  "found).", ("Install Claude Code, then run the wizard again.",))
        if self.existing(name):
            self._run([program, "mcp", "remove", name, "--scope", "user"])
        code, out = self._run([program, "mcp", "add-json", name, json.dumps(entry), "--scope", "user"])
        if code != 0:
            raise AppError(f"Claude Code refused the connection: {out or 'no message'}")
        return Outcome(True, f"Added '{name}' to Claude Code (for every project).", restart=self.restart)

    def add_local(self, name: str, entry: dict) -> Outcome:
        return self._add(name, {"type": "stdio", **entry})

    def add_remote(self, name: str, url: str) -> Outcome:
        outcome = self._add(name, self.remote_entry(url))
        if not outcome.done:
            return outcome
        return Outcome(True, outcome.summary,
                       ("In Claude Code, type /mcp, choose the connection and sign in at your broker.",
                        "When the broker asks what to allow, choose only the permissions that read."),
                       restart=self.restart)

    def remove(self, name: str) -> Outcome:
        program = self.program()
        if not program:
            return Outcome(True, "Claude Code is not installed.")
        code, out = self._run([program, "mcp", "remove", name, "--scope", "user"])
        if code != 0:
            return Outcome(True, f"'{name}' was not in Claude Code.")
        return Outcome(True, f"Removed '{name}' from Claude Code.", restart=self.restart)


class ChatGPT:
    """ChatGPT reaches connections from OpenAI's servers, so it can use hosted ones only."""
    id = "chatgpt"
    name = "ChatGPT"
    supports_local = False
    restart = ""

    def installed(self) -> bool:
        return True

    def existing(self, name: str) -> dict | None:
        return None

    def preview(self, name: str, entry: dict) -> str:
        return ""

    def add_local(self, name: str, entry: dict) -> Outcome:
        return Outcome(False, "ChatGPT cannot start a program on your computer, so it cannot use this "
                              "connection.",
                       ("Choose a broker with a hosted connection (the wizard marks them 'sign in'), or",
                        "use Claude Desktop, Claude Code or Cursor for this broker."))

    def add_remote(self, name: str, url: str) -> Outcome:
        return Outcome(False, "ChatGPT adds connections from its own settings screen.",
                       ("Open chatgpt.com in a browser (developer mode is a web feature on paid plans).",
                        "Go to Settings > Security and login, and turn on Developer mode.",
                        "Create a new app (connector) for a remote MCP server.",
                        f"Name: {name}",
                        f"URL: {url}",
                        "Authentication: OAuth. Save, then sign in at your broker when the page opens.",
                        "When the broker asks what to allow, choose only the permissions that read."))

    def remove(self, name: str) -> Outcome:
        return Outcome(False, "Remove it inside ChatGPT.",
                       ("Open ChatGPT > Settings > Apps (or Connectors), choose the connection and delete it.",))


def all_apps() -> dict:
    apps = [ClaudeDesktop(), ClaudeCode(), Cursor(), ChatGPT()]
    return {a.id: a for a in apps}


def get_app(app_id: str):
    apps = all_apps()
    try:
        return apps[app_id]
    except KeyError as exc:
        raise AppError(f"no AI app called '{app_id}'. Known: {', '.join(apps)}") from exc
