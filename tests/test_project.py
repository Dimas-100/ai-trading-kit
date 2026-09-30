"""The project folder: creation, discovery as the kit's home, journal and notes tools."""
import json
import os
from pathlib import Path

import pytest

from aitk import cli, paths, project, state
from aitk.mcp.lab_server import build

from .conftest import ScriptedConsole


def call(server, name, args=None):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    result = reply["result"]
    text = result["content"][0]["text"]
    return result["isError"], (json.loads(text) if text[:1] in "{[" else text)


def test_create_writes_the_files_and_a_git_commit(tmp_path):
    out = project.create("my-trading", parent=tmp_path)
    folder = Path(out["folder"])
    for name in ("plan.md", "journal.md", "AGENTS.md", "README.md", ".gitignore", project.MARKER, "strategies"):
        assert (folder / name).exists(), name
    assert out["git"] is True and (folder / ".git").exists()
    assert "prices/" in (folder / ".gitignore").read_text(encoding="utf-8")
    assert "never" in (folder / "AGENTS.md").read_text(encoding="utf-8").lower()
    with pytest.raises(project.ProjectError):
        project.create("my-trading", parent=tmp_path)            # not empty
    with pytest.raises(project.ProjectError):
        project.create("bad/name", parent=tmp_path)
    with pytest.raises(project.ProjectError):
        project.create("inner", parent=folder)                   # already inside a project


def test_project_is_the_home_when_inside_it(tmp_path, monkeypatch):
    monkeypatch.delenv("AITK_HOME", raising=False)
    out = project.create("proj", parent=tmp_path, git=False)
    folder = Path(out["folder"])
    monkeypatch.chdir(folder / "strategies")
    assert project.find() == folder
    assert paths.home() == folder and paths.strategies_dir() == folder / "strategies"
    monkeypatch.setenv("AITK_HOME", str(tmp_path / "elsewhere"))
    assert paths.home() == tmp_path / "elsewhere"                  # an explicit home still wins
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AITK_HOME", raising=False)
    assert project.find() is None


def test_journal_and_notes(tmp_path):
    folder = Path(project.create("p", parent=tmp_path, git=False)["folder"])
    project.journal_add(folder, "Bought 5 SPY because the rule triggered.", title="first trade")
    project.journal_add(folder, "Sold: the stop was hit.")
    with pytest.raises(project.ProjectError):
        project.journal_add(folder, "   ")
    text = (folder / "journal.md").read_text(encoding="utf-8")
    assert "first trade" in text and "the stop was hit" in text
    notes = project.read_notes(folder, journal_entries=1)
    assert notes["plan"].startswith("# Plan") and notes["journal_entries"] == 3
    assert len(notes["recent_journal"]) == 1 and "stop was hit" in notes["recent_journal"][0]


def test_lab_tools_inside_and_outside_a_project(tmp_path, monkeypatch):
    monkeypatch.setenv("AITK_HOME", str(tmp_path / "plain"))
    monkeypatch.setenv("AITK_SECRETS", "file")
    server = build()
    err, out = call(server, "journal_add", {"text": "x"})
    assert err and "aitk init" in out
    err, out = call(server, "where_am_i")
    assert not err and out["project"]["is_project"] is False
    folder = Path(project.create("p", parent=tmp_path, git=False)["folder"])
    monkeypatch.setenv("AITK_HOME", str(folder))
    server = build()
    err, out = call(server, "where_am_i")
    assert not err and out["project"]["is_project"] is True
    err, out = call(server, "journal_add", {"text": "Decided to wait.", "title": "patience"})
    assert not err and out["added_to"].endswith("journal.md")
    err, out = call(server, "read_notes", {"entries": 2})
    assert not err and any("patience" in e for e in out["recent_journal"])


def test_cli_init_and_connect_lab_pins_the_project(fresh_state, user_home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    console = ScriptedConsole([])
    assert cli.main(["init", "my-trading", "--no-git"], console=console) == 0 and "Project created" in console.text
    assert state.is_done("project")
    monkeypatch.delenv("AITK_HOME", raising=False)
    monkeypatch.chdir(tmp_path / "my-trading")
    console = ScriptedConsole([])
    assert cli.main(["--no-menu"], console=console) == 0 and "Project:" in console.text
    console = ScriptedConsole([])
    assert cli.main(["connect-lab", "--app", "cursor", "--yes"], console=console) == 0
    entry = json.loads((user_home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["ai-trading-kit-lab"]
    assert entry["env"]["AITK_HOME"] == str((tmp_path / "my-trading").resolve())
    console = ScriptedConsole([])
    assert cli.main(["init", "again"], console=console) == 1 and "already" in console.text
    assert os.path.isdir(tmp_path / "my-trading" / "strategies")
