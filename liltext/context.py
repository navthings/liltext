from __future__ import annotations

from dataclasses import dataclass

from .messages import Message


@dataclass(frozen=True)
class Trigger:
    trigger: str
    prompt: str
    all_models: bool = False


def model_trigger(model: str) -> str:
    return model.rsplit("/", 1)[-1].split(":", 1)[0].lower()


def parse_trigger(text: str, configured_models: list[str]) -> Trigger | None:
    """Recognise @model, model:, and model, forms without accepting unconfigured bots."""
    lowered = text.lower().lstrip()
    if lowered.startswith("@all") and (len(text) == 4 or text[4].isspace() or text[4] in ",:?"):
        return Trigger("@all", text[4:].strip(" ,:?"), True)
    triggers = sorted({model_trigger(model) for model in configured_models}, key=len, reverse=True)
    for trigger in triggers:
        candidates = (f"@{trigger}", trigger)
        for prefix in candidates:
            if lowered.startswith(prefix) and (
                len(text) == len(prefix) or text[len(prefix)].isspace() or text[len(prefix)] in ",:"
            ):
                prompt = text[len(prefix):].strip(" ,:?") or "hi"
                return Trigger(trigger, prompt, False)
        if trigger in lowered:
            return Trigger(trigger, text.strip(), False)
    return None


def messages_to_ollama(messages: list[Message], generated: dict[int, dict]) -> list[dict]:
    """Turn recent Messages rows into stable user/assistant turns with speaker labels."""
    result: list[dict] = []
    seen: set[int] = set()
    for message in messages:
        if message.rowid in seen or not message.text:
            continue
        seen.add(message.rowid)
        info = generated.get(message.rowid)
        if info:
            role = "assistant"
            content = message.text
        else:
            role = "user"
            content = f"{message.sender}: {message.text}"
        result.append({"role": role, "content": content})
    return result


def build_messages(history: list[Message], current: Message, prompt: str, generated: dict[int, dict], image_b64: str | None = None) -> list[dict]:
    recent = [m for m in history if m.rowid != current.rowid]
    messages = messages_to_ollama(recent, generated)
    current_content = f"{current.sender}: {prompt}" if not current.is_from_me else prompt
    current_payload: dict = {"role": "user", "content": current_content}
    if image_b64:
        current_payload["images"] = [image_b64]
    messages.append(current_payload)
    return messages
