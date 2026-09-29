# liltext

put local ollama models in your iMessage group chats.



https://github.com/user-attachments/assets/752d8f0c-bd56-404a-8e72-c333a70b2c3d



pick one or more models, pick a chat, and liltext watches it. say a model's name in a message and it replies in the chat, sent from your account.

# goals

liltext is my most ambitious swift project yet. its goals are:
1. create a easily usable gui for users.
2. make it fast, minimal, and simple.
3. keep it functional and usefull.

## how it works

liltext reads `~/Library/Messages/chat.db` (read only) every 3 seconds for new messages. if a message mentions a model's trigger word, it sends the text to ollama and posts the reply back through Messages with AppleScript.

the trigger word is the model's short name, so `navthings/lilchat:q8_0` answers to `lilchat` and `llama3.2:3b` answers to `llama3.2`.

- start a message with the trigger and it's stripped off: `lilchat, how are you` sends `how are you`
- mention it anywhere else and the whole message is sent as the prompt
- replies are capped at 200 tokens

with more than one model running, bots can reply to each other. that's capped at 4 bot messages in a row, then they stop until a human says something.

## setup

needs macOS, Messages signed in, and [ollama](https://ollama.com) with at least one model pulled.

```sh
ollama serve
ollama pull llama3.2
```

your terminal needs two permissions:

- **Full Disk Access** so it can read chat.db. System Settings > Privacy & Security > Full Disk Access, add your terminal, then restart it
- **Automation for Messages** so it can send. macOS asks the first time a reply goes out

no dependencies outside the standard library.

## run

```sh
python chatbots.py
```

choose models by number (`1,3` for two), choose a chat, and leave it running. ctrl+c to stop.

## notes

replies come from your own Apple ID, so everyone in the chat sees them as you with a `name:` prefix. tell people before you drop a bot in.

it only sees messages that arrive after it starts, nothing older.
