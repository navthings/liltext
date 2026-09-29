from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .attachments import image_b64
from .config import DEFAULT_POLL, ChatConfig, LOG_PATH, load_config, load_state
from .context import build_messages, model_trigger, parse_trigger
from .messages import Message, MessagesError, connect, find_sent_rowid, latest_rowid, messages_for_chat, send
from .ollama import OllamaError, chat as ollama_chat
from .state import chat_rowid, generated_info, mark_generated, set_chat_rowid

LOG = logging.getLogger("liltext")


class Daemon:
    def __init__(self, poll: float = DEFAULT_POLL):
        self.poll = max(0.5, poll)
        self.stop_event = threading.Event()
        self.db = None
        self.state = load_state()
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="liltext-model")

    def stop(self, *_: Any) -> None:
        self.stop_event.set()

    def run(self) -> None:
        logging.basicConfig(filename=str(LOG_PATH), level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        try:
            self.db = connect()
            LOG.info("daemon started")
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except MessagesError as exc:
                    LOG.error("Messages: %s", exc)
                    self._reconnect()
                except Exception:
                    LOG.exception("unexpected daemon error")
                self.stop_event.wait(self.poll)
        finally:
            self.executor.shutdown(wait=False, cancel_futures=True)
            if self.db:
                self.db.close()
            LOG.info("daemon stopped")

    def _reconnect(self) -> None:
        if self.db:
            self.db.close()
        try:
            self.db = connect()
        except MessagesError:
            self.db = None
            time.sleep(min(self.poll * 2, 10))

    def tick(self) -> None:
        if self.db is None:
            self.db = connect()
        configs = load_config()
        for guid, config in configs.items():
            if not config.enabled or not config.models:
                continue
            self.process_chat(guid, config)

    def process_chat(self, guid: str, config: ChatConfig) -> None:
        assert self.db is not None
        last = chat_rowid(self.state, guid)
        messages = messages_for_chat(self.db, guid, after=last)
        if not messages:
            return
        # Advance the durable cursor only after each row has been considered. This means a crash
        # can repeat at most a single generation, and never causes older messages to be skipped.
        for message in messages:
            self.handle_message(guid, config, message)
            set_chat_rowid(self.state, guid, message.rowid)

    def handle_message(self, guid: str, config: ChatConfig, message: Message) -> None:
        assert self.db is not None
        info = generated_info(self.state, message.rowid)
        if info:
            # A generated message may be a human-visible chain hop. The model that produced it
            # is excluded, and a repeated model in the same chain is blocked.
            chain = int(info.get("chain", 0))
            source_model = str(info.get("model", ""))
            chain_models = [str(x) for x in info.get("chain_models", [])]
        else:
            chain = 0
            source_model = ""
            chain_models = []
        if not message.text:
            return
        trigger = parse_trigger(message.text, config.models)
        if not trigger:
            return
        if chain >= config.max_chain and source_model:
            LOG.info("chat %s: chain limit reached", guid)
            return

        targets = config.models if trigger.all_models else [
            model for model in config.models if model_trigger(model) == trigger.trigger and model != source_model
        ]
        if source_model and chain_models:
            targets = [model for model in targets if model not in chain_models]
        if not targets:
            return
        history = messages_for_chat(self.db, guid, limit=config.context_messages + 1)
        generated = {
            int(k): v for k, v in self.state.get("generated", {}).items()
            if isinstance(v, dict)
        }
        image = image_b64(message.attachments)
        futures = {
            self.executor.submit(self._generate, model, history, message, trigger.prompt, config, generated, image): model
            for model in targets
        }
        for future in as_completed(futures):
            model = futures[future]
            try:
                reply = future.result()
                if not reply:
                    continue
                text = f"{model_trigger(model)}: {reply}"
                before = latest_rowid(self.db, guid)
                send(text, guid)
                rowid = find_sent_rowid(self.db, guid, text, before)
                if rowid is not None:
                    next_chain = chain + 1 if source_model else 1
                    mark_generated(self.state, rowid, model, next_chain, chain_models + [model])
                else:
                    LOG.warning("sent reply for %s but could not observe its Messages ROWID", model)
                LOG.info("%s replied in %s", model, guid)
            except OllamaError as exc:
                LOG.error("%s: %s", model, exc)
            except MessagesError as exc:
                LOG.error("%s send failed: %s", model, exc)

    @staticmethod
    def _generate(model: str, history: list[Message], current: Message, prompt: str, config: ChatConfig, generated: dict[int, dict], image: str | None) -> str:
        messages = build_messages(history, current, prompt, generated, image)
        return ollama_chat(model, messages)


def main() -> None:
    Daemon().run()
