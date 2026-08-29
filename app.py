#!/usr/bin/env python3
"""foundry-lab MVP.

One project, one session, one room, two members: you and Claude CLI.
No daemon, no database, no dependencies. Run it and open the browser:

    /usr/bin/python3 app.py

Messages are appended to state/main.jsonl. The room owns them; the CLI
session id is only a cache, kept in state/claude_session.txt. Delete
that file and the next message starts a fresh CLI session — the room's
history is untouched.
"""

import json
import os
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8788
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
LOG = os.path.join(STATE, "main.jsonl")
SIDFILE = os.path.join(STATE, "claude_session.txt")
UI = os.path.join(ROOT, "ui", "index.html")
TIMEOUT = 300

MEMBERS = {
    "you": {"name": "Marian", "kind": "human", "initial": "M",
            "color": "#2f6fd0", "model": "human · cto"},
    "claude": {"name": "Claude", "kind": "agent", "initial": "A",
               "color": "#c96442", "model": "claude-cli"},
}


# --------------------------------------------------------------- storage
def load():
    if not os.path.exists(LOG):
        return []
    out = []
    with open(LOG, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def append(msg):
    os.makedirs(STATE, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg


def session_id():
    if os.path.exists(SIDFILE):
        return open(SIDFILE, encoding="utf-8").read().strip() or None
    return None


def remember_session(sid):
    os.makedirs(STATE, exist_ok=True)
    with open(SIDFILE, "w", encoding="utf-8") as fh:
        fh.write(sid)


# --------------------------------------------------------------- the agent
def ask_claude(prompt):
    """One turn. Returns (text, meta). Never raises."""
    sid = session_id()
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    cmd += ["--resume", sid] if sid else ["--session-id", str(uuid.uuid4())]
    started = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        return None, {"error": "`claude` is not on PATH"}
    except subprocess.TimeoutExpired:
        return None, {"error": "claude timed out after %ds" % TIMEOUT}

    raw = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()

    if proc.returncode != 0 and not raw:
        # a stale session id is the usual cause — drop it and say so
        if sid and ("session" in err.lower() or "resume" in err.lower()):
            os.remove(SIDFILE)
            return None, {"error": "the stored CLI session was gone; it has been "
                                   "cleared — send again to start a fresh one",
                          "stderr": err[:600]}
        return None, {"error": "claude exited %d" % proc.returncode, "stderr": err[:600]}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return (raw or err or "(empty answer)"), {"elapsed": round(time.time() - started, 1)}

    if isinstance(data, list):                       # stream-json fallback
        data = next((d for d in reversed(data) if d.get("type") == "result"), data[-1])
    if data.get("session_id"):
        remember_session(data["session_id"])
    text = data.get("result") or data.get("text") or json.dumps(data)[:2000]
    meta = {"elapsed": round(time.time() - started, 1)}
    if data.get("total_cost_usd") is not None:
        meta["cost"] = round(float(data["total_cost_usd"]), 4)
    if data.get("num_turns") is not None:
        meta["turns"] = data["num_turns"]
    if data.get("is_error"):
        meta["error"] = "claude reported an error"
    return text, meta


# --------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(UI, "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, {
                "project": "foundry-lab",
                "session": "main",
                "room": "Team room",
                "members": MEMBERS,
                "cli_session": session_id(),
                "messages": load(),
            })
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})

        if self.path == "/api/send":
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "empty message"})
            mine = append({"author": "you", "text": text, "ts": time.time()})
            answer, meta = ask_claude(text)
            if answer is None:
                return self._send(200, {"messages": [mine],
                                        "error": meta.get("error"),
                                        "detail": meta.get("stderr")})
            theirs = append({"author": "claude", "text": answer,
                             "ts": time.time(), "meta": meta})
            return self._send(200, {"messages": [mine, theirs]})

        if self.path == "/api/clear":
            # clears the CLI's context; the room's history stays on disk
            if os.path.exists(SIDFILE):
                os.remove(SIDFILE)
            append({"author": "system", "ts": time.time(),
                    "text": "context cleared — the next message starts a fresh CLI "
                            "session; the room keeps every message above"})
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):        # quiet
        pass


if __name__ == "__main__":
    os.makedirs(STATE, exist_ok=True)
    print("foundry-lab  →  http://%s:%d" % (HOST, PORT))
    print("messages     →  %s" % LOG)
    print("cli session  →  %s" % (session_id() or "(new on first message)"))
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        sys.exit(0)
