import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434"
DB = os.path.expanduser("~/Library/Messages/chat.db")

# bots can trigger each other, but only this many times in a row before a human speaks
MAX_CHAIN = 4

SEND = '''
on run argv
    tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run
'''


# open chat.db read only
def connect():
    try:
        db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        db.execute("select 1 from message limit 1")
        return db
    except sqlite3.OperationalError as e:
        sys.exit(f"can't read chat.db ({e}). give your terminal Full Disk Access in "
                 "System Settings > Privacy & Security, then restart the terminal")


# numbered menu, returns the index picked
def pick(title, options):
    print(f"\n{title}")
    for i, label in enumerate(options, 1):
        print(f"  {i:>2}. {label}")
    while True:
        choice = input("> ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return int(choice) - 1
        print("type a number from the list")


# pick one or more downloaded ollama models
def pick_model():
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            models = sorted(m["name"] for m in json.load(r)["models"])
    except urllib.error.URLError as e:
        sys.exit(f"ollama not reachable ({e}), run `ollama serve`")
    if not models:
        sys.exit("no ollama models downloaded")

    print("\nwhich models? (numbers separated by commas, e.g. 1,3)")
    for i, m in enumerate(models, 1):
        print(f"  {i:>2}. {m}")
    while True:
        nums = [n.strip() for n in input("> ").split(",")]
        if nums and all(n.isdigit() and 1 <= int(n) <= len(models) for n in nums):
            return [models[int(n) - 1] for n in dict.fromkeys(nums)]
        print("type numbers from the list, like 1,3")


# most recent chats first, named by group name or the people in it
def pick_chat(db):
    rows = db.execute("""
        select c.guid, c.display_name,
               (select group_concat(h.id, ', ') from chat_handle_join ch
                join handle h on h.ROWID = ch.handle_id where ch.chat_id = c.ROWID),
               (select max(m.date) from chat_message_join cm
                join message m on m.ROWID = cm.message_id where cm.chat_id = c.ROWID) as last
        from chat c order by last desc limit 40
    """).fetchall()

    labels = []
    for guid, name, people, _ in rows:
        people = people or "?"
        if len(people) > 50:
            people = people[:50] + "..."
        labels.append(f"{name}  ({people})" if name else people)

    guid, name, people, _ = rows[pick("which chat?", labels)]
    return guid, name or people


# newer macos stores the text inside attributedBody instead of the text column
def decode_body(blob):
    if not blob or b"NSString" not in blob:
        return None
    rest = blob.split(b"NSString", 1)[1][5:]
    if rest[0] == 0x81:
        n, start = int.from_bytes(rest[1:3], "little"), 3
    else:
        n, start = rest[0], 1
    return rest[start:start + n].decode("utf-8", errors="replace")


def new_messages(db, guid, after):
    rows = db.execute("""
        select m.ROWID, m.text, m.attributedBody
        from message m join chat_message_join j on j.message_id = m.ROWID
        join chat c on c.ROWID = j.chat_id
        where c.guid = ? and m.ROWID > ?
        order by m.ROWID
    """, (guid, after)).fetchall()
    return [(rowid, text or decode_body(body)) for rowid, text, body in rows]


def generate(model, prompt):
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps({
            "model": model, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"num_predict": 200},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["message"]["content"]


def send(text, guid):
    subprocess.run(["osascript", "-e", SEND, text, guid], check=True)


def main():
    db = connect()
    models = pick_model()
    guid, chat_name = pick_chat(db)

    # trigger word is the model's short name, e.g. navthings/lilchat:q8_0 -> lilchat
    bots = [(m, m.split("/")[-1].split(":")[0].lower()) for m in models]
    last = db.execute("select max(ROWID) from message").fetchone()[0] or 0
    print(f"\nwatching {chat_name}. triggers: {', '.join(t for _, t in bots)}")

    # replies we sent, so a bot message can't be confused with you typing "lilchat: ..."
    sent = {}
    chain = 0

    while True:
        for rowid, text in new_messages(db, guid, last):
            last = rowid
            if not text:
                continue

            # work out who spoke and cap bot to bot chains
            speaker = sent.pop(text.strip(), None)
            if speaker:
                text = text.split(":", 1)[1].strip()
                chain += 1
                if chain > MAX_CHAIN:
                    continue
            else:
                chain = 0

            for model, trigger in bots:
                if trigger == speaker or trigger not in text.lower():
                    continue

                # "lilchat, how are you" -> "how are you", otherwise send the whole message
                if text.lower().startswith(trigger):
                    prompt = text[len(trigger):].strip(" ,:?") or "hi"
                else:
                    prompt = text

                try:
                    reply = f"{trigger}: {generate(model, prompt).strip()}"
                    send(reply, guid)
                    sent[reply] = trigger
                    print(f"{trigger} replied to {text!r}")
                except urllib.error.URLError as e:
                    print(f"ollama not reachable ({e}), run `ollama serve`")
                except subprocess.CalledProcessError as e:
                    print(f"couldn't send to Messages ({e}), check Automation permission for your terminal")

        time.sleep(3)


if __name__ == "__main__":
    main()