# MVP — run it

On the Mac, in a terminal:

    cd /Volumes/Marian_Backup/work/foundry-lab
    /usr/bin/python3 app.py

Then open http://127.0.0.1:8788

Use `/usr/bin/python3`, not the anaconda one.

## What it is

One project (foundry-lab), one session (main), one room (Team room),
two members: you and the Claude CLI. No daemon, no database, no
dependencies — the standard library only.

## What it proves

- the room owns the history: `state/main.jsonl`, one JSON object per line
- the CLI session id is only a cache: `state/claude_session.txt`
- "Clear context" deletes that cache. The next message starts a fresh
  CLI session and the room keeps every message. That is the watermark
  idea, in its smallest possible form.

Delete `state/` to start over.

## How it talks to Claude

One `claude -p` per message:

    claude -p "<text>" --output-format json --session-id <uuid>     # first
    claude -p "<text>" --output-format json --resume <uuid>         # after

That reloads the context on every turn, which costs tokens. It is the
simplest thing that works; a persistent process comes later, once the
shape is proven.
