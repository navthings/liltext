from __future__ import annotations

from typing import Any

from .config import save_state


def chat_rowid(state: dict[str, Any], guid: str) -> int:
    return int(state.setdefault("chats", {}).get(guid, 0))


def set_chat_rowid(state: dict[str, Any], guid: str, rowid: int) -> None:
    state.setdefault("chats", {})[guid] = int(rowid)
    save_state(state)


def mark_generated(state: dict[str, Any], rowid: int, model: str, chain: int, chain_models: list[str] | None = None) -> None:
    state.setdefault("generated", {})[str(rowid)] = {"model": model, "chain": int(chain), "chain_models": list(chain_models or [model])}
    # Keep this bounded; old generated-message IDs are no longer useful.
    generated = state["generated"]
    if len(generated) > 512:
        for key in sorted(generated, key=lambda x: int(x))[:-512]:
            generated.pop(key, None)
    save_state(state)


def generated_info(state: dict[str, Any], rowid: int) -> dict[str, Any] | None:
    return state.setdefault("generated", {}).get(str(rowid))
