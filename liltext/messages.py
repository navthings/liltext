from __future__ import annotations

import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"
SEND_SCRIPT = '''
on run argv
    tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run
'''


class MessagesError(RuntimeError):
    pass


@dataclass(frozen=True)
class Chat:
    guid: str
    name: str
    participants: str
    last_rowid: int


@dataclass(frozen=True)
class Attachment:
    path: Path
    mime_type: str | None
    transfer_name: str | None


@dataclass(frozen=True)
class Message:
    rowid: int
    guid: str | None
    text: str | None
    is_from_me: bool
    sender: str
    attachments: tuple[Attachment, ...] = ()


def decode_body(blob: bytes | None) -> str | None:
    """Best-effort extraction of NSString from Apple's NSAttributedString typedstream."""
    if not blob or b"NSString" not in blob:
        return None
    try:
        rest = blob.split(b"NSString", 1)[1][5:]
        if not rest:
            return None
        if rest[0] == 0x81 and len(rest) >= 3:
            length, start = int.from_bytes(rest[1:3], "little"), 3
        else:
            length, start = rest[0], 1
        return rest[start : start + length].decode("utf-8", errors="replace")
    except (IndexError, ValueError):
        return None


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
        db.execute("select 1 from message limit 1")
        return db
    except sqlite3.Error as exc:
        raise MessagesError(
            f"can't read {path}: {exc}. Give your terminal or Python executable "
            "Full Disk Access in System Settings > Privacy & Security > Full Disk Access."
        ) from exc


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"pragma table_info({table})")}


def list_chats(db: sqlite3.Connection, limit: int = 100) -> list[Chat]:
    rows = db.execute(
        """
        select c.guid, c.display_name,
               (select group_concat(h.id, ', ') from chat_handle_join ch
                join handle h on h.ROWID = ch.handle_id where ch.chat_id = c.ROWID),
               coalesce((select max(m.ROWID) from chat_message_join cm
                join message m on m.ROWID = cm.message_id where cm.chat_id = c.ROWID), 0) as last_rowid
        from chat c order by last_rowid desc limit ?
        """,
        (limit,),
    ).fetchall()
    return [Chat(guid, name or "", people or "?", int(last)) for guid, name, people, last in rows]


def chat_by_guid(db: sqlite3.Connection, guid: str) -> Chat | None:
    return next((chat for chat in list_chats(db, 1000) if chat.guid == guid), None)


def latest_rowid(db: sqlite3.Connection, guid: str) -> int:
    row = db.execute(
        """
        select coalesce(max(m.ROWID), 0)
        from message m join chat_message_join j on j.message_id = m.ROWID
        join chat c on c.ROWID = j.chat_id where c.guid = ?
        """,
        (guid,),
    ).fetchone()
    return int(row[0] or 0)


def _attachment_query(db: sqlite3.Connection) -> bool:
    return bool(
        {"message_attachment_join", "attachment"}
        and "filename" in _column_names(db, "attachment")
    )


def _attachments_for(db: sqlite3.Connection, message_id: int) -> tuple[Attachment, ...]:
    try:
        rows = db.execute(
            """
            select a.filename, a.mime_type, a.transfer_name
            from message_attachment_join maj
            join attachment a on a.ROWID = maj.attachment_id
            where maj.message_id = ?
            """,
            (message_id,),
        ).fetchall()
    except sqlite3.Error:
        return ()
    result: list[Attachment] = []
    for filename, mime_type, transfer_name in rows:
        if not filename:
            continue
        result.append(Attachment(Path(str(filename)).expanduser(), mime_type, transfer_name))
    return tuple(result)


def _sender(db: sqlite3.Connection, handle_id: int | None, is_from_me: bool) -> str:
    if is_from_me:
        return "Me"
    if handle_id:
        row = db.execute("select id from handle where ROWID = ?", (handle_id,)).fetchone()
        if row and row[0]:
            return str(row[0])
    return "Unknown"


def messages_for_chat(db: sqlite3.Connection, guid: str, *, after: int | None = None, limit: int | None = None) -> list[Message]:
    message_columns = _column_names(db, "message")
    has_handle = "handle_id" in message_columns
    handle_sql = "m.handle_id" if has_handle else "NULL"
    after_sql = "and m.ROWID > ?" if after is not None else ""
    params: list[object] = [guid]
    if after is not None:
        params.append(after)
    limit_sql = f"limit {int(limit)}" if limit else ""
    order = "desc" if limit else "asc"
    rows = db.execute(
        f"""
        select m.ROWID, m.guid, m.text, m.attributedBody, m.is_from_me, {handle_sql}
        from message m join chat_message_join j on j.message_id = m.ROWID
        join chat c on c.ROWID = j.chat_id
        where c.guid = ? {after_sql}
        order by m.ROWID {order} {limit_sql}
        """,
        params,
    ).fetchall()
    if limit:
        rows = list(reversed(rows))
    result = []
    for rowid, msg_guid, text, attributed, is_from_me, handle_id in rows:
        text = text or decode_body(attributed)
        result.append(
            Message(
                int(rowid), msg_guid, text, bool(is_from_me), _sender(db, handle_id, bool(is_from_me)),
                _attachments_for(db, int(rowid)),
            )
        )
    return result


def send(text: str, guid: str) -> None:
    try:
        subprocess.run(["osascript", "-e", SEND_SCRIPT, text, guid], check=True, timeout=15)
    except FileNotFoundError as exc:
        raise MessagesError("osascript is unavailable; liltext must run on macOS") from exc
    except subprocess.TimeoutExpired as exc:
        raise MessagesError("Messages did not respond to AppleScript within 15 seconds") from exc
    except subprocess.CalledProcessError as exc:
        raise MessagesError(
            f"couldn't send to Messages ({exc}). Check Automation permission for Messages."
        ) from exc


def find_sent_rowid(db: sqlite3.Connection, guid: str, text: str, after: int, timeout: float = 5.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = db.execute(
            """
            select m.ROWID from message m
            join chat_message_join j on j.message_id = m.ROWID
            join chat c on c.ROWID = j.chat_id
            where c.guid = ? and m.ROWID > ? and m.is_from_me = 1 and m.text = ?
            order by m.ROWID desc limit 1
            """,
            (guid, after, text),
        ).fetchone()
        if row:
            return int(row[0])
        time.sleep(0.25)
    return None
