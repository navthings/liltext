from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from .config import DEFAULT_CONTEXT, DEFAULT_MAX_CHAIN, DEFAULT_POLL, LOG_PATH, STATE_PATH, ChatConfig, load_config, load_state, save_config
from .daemon import Daemon
from .messages import MessagesError, connect, list_chats, latest_rowid
from .ollama import OllamaError, models as ollama_models
from .service import install, restart, start, status as service_status, stop, uninstall

B = "\033[1m"
D = "\033[2m"
R = "\033[0m"
C = "\033[36m"
G = "\033[32m"
Y = "\033[33m"


def title(text: str) -> None:
    print(f"\n{B}{text}{R}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="liltext", description="Local Ollama bots for Messages")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chats")
    sub.add_parser("models")
    sub.add_parser("status")
    logs = sub.add_parser("logs")
    logs.add_argument("--follow", action="store_true")
    chat = sub.add_parser("chat")
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)
    for name in ("add", "remove", "models", "enable", "disable", "settings"):
        p = chat_sub.add_parser(name)
        p.add_argument("guid", nargs="?")
        if name == "add":
            p.add_argument("--name")
            p.add_argument("--model", action="append", dest="models")
            p.add_argument("--context", type=int, default=DEFAULT_CONTEXT)
            p.add_argument("--max-chain", type=int, default=DEFAULT_MAX_CHAIN)
        elif name == "models":
            p.add_argument("--add")
            p.add_argument("--remove")
        elif name == "settings":
            p.add_argument("--context", type=int)
            p.add_argument("--max-chain", type=int)
    service = sub.add_parser("service")
    service_sub = service.add_subparsers(dest="service_command", required=True)
    for name in ("install", "uninstall", "start", "stop", "restart", "status"):
        service_sub.add_parser(name)
    daemon = sub.add_parser("watch", help="run the daemon in the foreground")
    daemon.add_argument("--poll", type=float, default=DEFAULT_POLL)
    args = parser.parse_args()
    try:
        if not args.command:
            interactive()
        elif args.command == "chats":
            show_chats()
        elif args.command == "models":
            show_models()
        elif args.command == "status":
            show_status()
        elif args.command == "logs":
            show_logs(args.follow)
        elif args.command == "chat":
            chat_command(args)
        elif args.command == "service":
            service_command(args.service_command)
        elif args.command == "watch":
            Daemon(args.poll).run()
    except (MessagesError, OllamaError, ValueError) as exc:
        print(f"{Y}error:{R} {exc}", file=sys.stderr)
        raise SystemExit(1)


def show_chats() -> None:
    configs = load_config()
    db = connect()
    try:
        title("configured chats")
        if not configs:
            print(f"{D}none — use `liltext chat add`{R}")
            return
        for guid, cfg in configs.items():
            state = f"{G}on{R}" if cfg.enabled else f"{D}off{R}"
            models = ", ".join(cfg.models) or "—"
            print(f"  {state:<16} {B}{cfg.name}{R}  {D}{guid}{R}")
            print(f"      {models}  · context {cfg.context_messages} · chain {cfg.max_chain}")
    finally:
        db.close()


def show_models() -> None:
    title("ollama models")
    for i, model in enumerate(ollama_models(), 1):
        print(f"  {i:>2}  {model}")


def show_status() -> None:
    configs = load_config()

    print(f"\n{B}liltext{R}  {D}local Messages ↔ Ollama bridge{R}")
    print(
        f"  chats     {len(configs)} configured / "
        f"{sum(c.enabled for c in configs.values())} enabled"
    )

    service = service_status()
    print(
        f"  service   {G}running{R}"
        if service != "not running"
        else f"  service   {D}not running{R}"
    )

    try:
        db = connect()
        db.close()
        print(f"  health    {G}healthy{R}")
        print(f"  Messages  {G}accessible{R}")
    except MessagesError as exc:
        print(f"  health    {Y}error{R}")
        print(f"  Messages  {Y}inaccessible{R}")
        print(f"  error     {exc}")

    from .config import CONFIG_PATH
    print(f"  config    {CONFIG_PATH}")
    print(f"  state     {STATE_PATH}")
    print(f"  logs      {LOG_PATH}")

def show_logs(follow: bool) -> None:
    if not LOG_PATH.exists():
        print(f"{D}no log yet: {LOG_PATH}{R}")
        return
    if follow:
        os.execvp("tail", ["tail", "-f", str(LOG_PATH)])
    os.system(f"tail -n 80 {shlex_quote(str(LOG_PATH))}")


def shlex_quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def _choose_guid() -> str:
    db = connect()
    try:
        chats = list_chats(db, 100)
    finally:
        db.close()
    if not chats:
        raise ValueError("no Messages chats found")
    for i, chat in enumerate(chats, 1):
        label = chat.name or chat.participants
        print(f"  {i:>2}. {label}  {D}{chat.guid}{R}")
    raw = input("\n  choose chat › ").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(chats):
        raise ValueError("choose a valid chat number")
    return chats[int(raw) - 1].guid


def chat_command(args: argparse.Namespace) -> None:
    configs = load_config()
    guid = args.guid or _choose_guid()
    if args.chat_command == "add":
        db = connect()
        try:
            chat = next((c for c in list_chats(db, 1000) if c.guid == guid), None)
            if chat is None:
                raise ValueError("chat GUID not found in Messages")
            name = args.name or chat.name or chat.participants
            configs[guid] = ChatConfig(name, args.models or [], max(1, args.context), max(0, args.max_chain), True)
            save_config(configs)
            state = load_state()
            from .state import set_chat_rowid
            if guid not in state.get("chats", {}):
                set_chat_rowid(state, guid, latest_rowid(db, guid))
        finally:
            db.close()
        print(f"{G}configured{R} {name}")
    elif args.chat_command == "remove":
        if guid not in configs:
            raise ValueError("chat is not configured")
        configs.pop(guid)
        save_config(configs)
        print(f"{G}removed{R} {guid}")
    elif args.chat_command == "enable":
        configs[guid].enabled = True
        save_config(configs)
        print(f"{G}enabled{R} {configs[guid].name}")
    elif args.chat_command == "disable":
        configs[guid].enabled = False
        save_config(configs)
        print(f"{D}disabled{R} {configs[guid].name}")
    elif args.chat_command == "models":
        if guid not in configs:
            raise ValueError("chat is not configured")
        if args.add:
            if args.add not in configs[guid].models:
                configs[guid].models.append(args.add)
        if args.remove:
            configs[guid].models = [m for m in configs[guid].models if m != args.remove]
        save_config(configs)
        print(f"{B}{configs[guid].name}{R}: {', '.join(configs[guid].models) or 'no models'}")
    elif args.chat_command == "settings":
        if guid not in configs:
            raise ValueError("chat is not configured")
        if args.context is not None:
            if args.context < 1:
                raise ValueError("context must be at least 1")
            configs[guid].context_messages = args.context
        if args.max_chain is not None:
            if args.max_chain < 0:
                raise ValueError("max-chain cannot be negative")
            configs[guid].max_chain = args.max_chain
        save_config(configs)
        cfg = configs[guid]
        print(f"{B}{cfg.name}{R}: context {cfg.context_messages} · max chain {cfg.max_chain}")


def service_command(command: str) -> None:
    {"install": install, "uninstall": uninstall, "start": start, "stop": stop, "restart": restart}.get(command, lambda: print(service_status()))()
    if command == "install":
        print(f"{G}installed{R} launch agent")
    elif command == "uninstall":
        print(f"{G}uninstalled{R} launch agent")


def interactive() -> None:
    print(f"\n{B}{C}liltext{R} {D}local bots for Messages{R}")
    print("\n  1  configure a chat")
    print("  2  list chats")
    print("  3  list Ollama models")
    print("  4  service status")
    print("  q  quit")
    choice = input("\n  › ").strip().lower()
    if choice == "1":
        guid = _choose_guid()
        models = ollama_models()
        for i, model in enumerate(models, 1):
            print(f"  {i:>2}. {model}")
        raw = input("  models › ").strip()
        picked = [models[int(n)-1] for n in raw.split(",") if n.strip().isdigit() and 1 <= int(n) <= len(models)]
        chat_command(argparse.Namespace(chat_command="add", guid=guid, name=None, models=picked, context=DEFAULT_CONTEXT, max_chain=DEFAULT_MAX_CHAIN))
        print(f"\n  {D}Start it in the background with `liltext service install`.{R}")
    elif choice == "2":
        show_chats()
    elif choice == "3":
        show_models()
    elif choice == "4":
        print(service_status())
