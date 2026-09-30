"""Where broker keys are kept: the operating system's own password vault (Windows Credential Manager,
macOS Keychain, the Linux Secret Service) through `keyring`.

Keys are never written into the repository and never into an AI app's settings file. When a computer
has no vault (a bare server, some Linux desktops) the kit falls back to one file in the kit's home
folder that only the owner can read, and says so."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from . import paths

SERVICE = "ai-trading-kit"


class SecretStoreError(RuntimeError):
    pass


def _name(broker: str, key: str) -> str:
    return f"{broker}:{key}"


class KeyringStore:
    kind = "vault"
    label = "your computer's password vault"

    def __init__(self, backend=None):
        if backend is None:
            import keyring
            from keyring.backends import fail
            backend = keyring.get_keyring()
            if isinstance(backend, fail.Keyring):
                raise SecretStoreError("no password vault is available on this computer")
        self._kr = backend

    def get(self, broker: str, key: str) -> str | None:
        return self._kr.get_password(SERVICE, _name(broker, key))

    def set(self, broker: str, key: str, value: str) -> None:
        self._kr.set_password(SERVICE, _name(broker, key), value)

    def delete(self, broker: str, key: str) -> bool:
        if self.get(broker, key) is None:
            return False
        self._kr.delete_password(SERVICE, _name(broker, key))
        return True


class FileStore:
    kind = "file"

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.fallback_secrets_file()
        self.label = f"a private file ({self.path})"

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecretStoreError(f"could not read {self.path}: {exc}") from exc

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def get(self, broker: str, key: str) -> str | None:
        return self._load().get(_name(broker, key))

    def set(self, broker: str, key: str, value: str) -> None:
        data = self._load()
        data[_name(broker, key)] = value
        self._save(data)

    def delete(self, broker: str, key: str) -> bool:
        data = self._load()
        if _name(broker, key) not in data:
            return False
        del data[_name(broker, key)]
        self._save(data)
        return True


def open_store():
    """The vault when there is one, else the private file. AITK_SECRETS=file forces the file."""
    if os.environ.get("AITK_SECRETS", "").strip().lower() == "file":
        return FileStore()
    try:
        return KeyringStore()
    except Exception:
        return FileStore()


def mask(value: str) -> str:
    """For showing that a key is stored without showing the key."""
    value = str(value or "")
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:2]}{'*' * 8}{value[-2:]}"
