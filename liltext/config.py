from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / "Library" / "Application Support" / "liltext"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LOG_PATH = Path.home() / "Library" / "Logs" / "liltext.log"
DEFAULT_CONTEXT = 12
DEFAULT_MAX_CHAIN = 4
DEFAULT_POLL = 3.0


@dataclass
class ChatConfig:
    name: str
    models: list[str] = field(default_factory=list)
    context_messages: int = DEFAULT_CONTEXT
    max_chain: int = DEFAULT_MAX_CHAIN
    enabled: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChatConfig":
        return cls(
            name=str(value.get("name") or "Unnamed chat"),
            models=[str(x) for x in value.get("models", []) if str(x).strip()],
            context_messages=max(1, int(value.get("context_messages", DEFAULT_CONTEXT))),
            max_chain=max(0, int(value.get("max_chain", DEFAULT_MAX_CHAIN))),
            enabled=bool(value.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "models": self.models,
            "context_messages": self.context_messages,
            "max_chain": self.max_chain,
            "enabled": self.enabled,
        }


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, value: Any) -> None:
    ensure_dirs()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def load_config() -> dict[str, ChatConfig]:
    ensure_dirs()
    if not CONFIG_PATH.exists():
        return {}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        chats = raw.get("chats", {})
        return {guid: ChatConfig.from_dict(value) for guid, value in chats.items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid liltext config at {CONFIG_PATH}: {exc}") from exc


def save_config(chats: dict[str, ChatConfig]) -> None:
    _atomic_write(CONFIG_PATH, {"chats": {guid: chat.to_dict() for guid, chat in chats.items()}})


def load_state() -> dict[str, Any]:
    ensure_dirs()
    if not STATE_PATH.exists():
        return {"chats": {}, "generated": {}}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        raw.setdefault("chats", {})
        raw.setdefault("generated", {})
        return raw
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"invalid liltext state at {STATE_PATH}: {exc}") from exc


def save_state(state: dict[str, Any]) -> None:
    _atomic_write(STATE_PATH, state)
