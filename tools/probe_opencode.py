#!/usr/bin/env python3
"""Does `opencode serve` hold a conversation, and does it survive a restart?

    opencode serve --port 4096
    python3 tools/probe_opencode.py                     # a fresh session
    python3 tools/probe_opencode.py ses_xxx "question"  # resume one

Findings are written up in docs/design/03-providers.md.
"""

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:4096"
MODEL = {"providerID": "ai-lab", "id": "llama-qwen36-35b"}


def call(path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data,
                                 {"Content-Type": "application/json"})
    body = urllib.request.urlopen(req, timeout=timeout).read()
    return json.loads(body) if body.strip() else None


def messages(sid):
    """Newest first -- reading [-1] gives you your own question."""
    return call("/api/session/%s/message" % sid)["data"]


def text_of(message):
    return " ".join(c.get("text", "") for c in message.get("content", [])
                    if c.get("type") == "text") or message.get("text", "")


def ask(sid, question, limit=600):
    """POST /prompt returns at once; the turn is over when the newest message
    is an assistant one carrying `finish`."""
    before = len(messages(sid))
    started = time.time()
    call("/api/session/%s/prompt" % sid, {"prompt": {"text": question}}, timeout=30)
    while time.time() - started < limit:
        time.sleep(3)
        seen = messages(sid)
        if len(seen) > before and seen[0].get("type") == "assistant" \
                and seen[0].get("finish"):
            return time.time() - started, text_of(seen[0]), seen[0].get("tokens")
    return None, "TIMEOUT", None


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if sid:
        questions = [sys.argv[2] if len(sys.argv) > 2 else "Ce numar ti-am dat?"]
    else:
        created = call("/api/session", {"model": MODEL})
        sid = (created.get("data") or created)["id"]
        print("session", sid, flush=True)
        questions = ["Retine numarul 4271. Raspunde doar cu OK.",
                     "Ce numar ti-am dat?"]

    for question in questions:
        elapsed, answer, tokens = ask(sid, question)
        print("--- %s   %s" % (question, elapsed and "%.1fs" % elapsed), flush=True)
        print("    reply :", answer[:200], flush=True)
        print("    tokens:", json.dumps(tokens), flush=True)
    print("SID", sid, flush=True)


if __name__ == "__main__":
    main()
