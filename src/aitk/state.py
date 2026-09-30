"""What the kit remembers between runs: which connections were set up and which steps of the path are
done. One small JSON file in the kit's home folder. It never holds a key."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from . import paths


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> dict:
    f = paths.state_file()
    if not f.exists():
        return {"connections": [], "done": {}}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"connections": [], "done": {}}
    data.setdefault("connections", [])
    data.setdefault("done", {})
    return data


def save(data: dict) -> None:
    f = paths.state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def add_connection(broker: str, app: str, server_name: str, detail: dict | None = None) -> None:
    data = load()
    data["connections"] = [c for c in data["connections"]
                           if not (c.get("broker") == broker and c.get("app") == app)]
    data["connections"].append({"broker": broker, "app": app, "server_name": server_name,
                                "at": _now(), **(detail or {})})
    save(data)


def remove_connection(broker: str, app: str) -> bool:
    data = load()
    before = len(data["connections"])
    data["connections"] = [c for c in data["connections"]
                           if not (c.get("broker") == broker and c.get("app") == app)]
    save(data)
    return len(data["connections"]) != before


def mark_done(step: str) -> None:
    data = load()
    data["done"].setdefault(step, _now())
    save(data)


def is_done(step: str) -> bool:
    return step in load()["done"]
