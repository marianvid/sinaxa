#!/usr/bin/env python3
"""Stands in for `opencode serve`.

Answers the handful of endpoints the adapter uses, with the real shapes --
newest-first transcripts, an assistant reply under content[], token counts
split into input/output/cache. The point is the order and the nesting, which
is where the traps are.

    FAKE_LOG      argv, one JSON line per spawn
    FAKE_WARMUP   seconds during which the port answers but the provider list
                  is empty -- the window in which a real turn dies silently
    FAKE_MODE     normal | mute (accept prompts, never answer)

Prompt keywords: SLOW (no reply at all), FAIL (an assistant message that
never carries `finish`).
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = os.environ.get("FAKE_LOG")
WARMUP = float(os.environ.get("FAKE_WARMUP", "0"))
MODE = os.environ.get("FAKE_MODE", "normal")

if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")

BOOTED = time.time()
SESSIONS = {}          # id -> {"model": ..., "messages": [newest first]}
COUNTER = [0]

PROVIDERS = [{"id": "ai-lab", "models": {"llama-qwen36-35b": {}, "llama-gemma-26b": {}}},
             {"id": "mac", "models": {"llama-glm-air": {}}}]


def port_from_argv():
    if "--port" in sys.argv:
        return int(sys.argv[sys.argv.index("--port") + 1])
    return 4096


def answer(session, prompt):
    """Runs in the background, like a real turn does."""
    time.sleep(0.05)
    if "SLOW" in prompt:
        return
    text = "turn %d: %s" % (len(session["messages"]) // 2 + 1, prompt[:60])
    message = {"id": "msg_%d" % len(session["messages"]), "type": "assistant",
               "model": session.get("model"),
               "content": [{"type": "reasoning", "text": "thinking"},
                           {"type": "text", "text": text}],
               "tokens": {"input": 10, "output": 5, "reasoning": 0,
                          "cache": {"read": 100, "write": 0}}}
    if "FAIL" not in prompt:
        message["finish"] = "stop"
    session["messages"].insert(0, message)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, body):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/config/providers":
            warm = time.time() - BOOTED >= WARMUP
            return self.reply(200, {"data": PROVIDERS if warm else []})
        if self.path.startswith("/api/session/") and self.path.endswith("/message"):
            sid = self.path.split("/")[3]
            if sid not in SESSIONS:
                return self.reply(404, {"error": "no such session"})
            return self.reply(200, {"data": SESSIONS[sid]["messages"]})
        return self.reply(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/api/session":
            COUNTER[0] += 1
            sid = "ses_fake%d" % COUNTER[0]
            SESSIONS[sid] = {"model": payload.get("model"), "messages": []}
            return self.reply(200, {"id": sid})

        parts = self.path.split("/")
        if len(parts) >= 5 and parts[1] == "api" and parts[2] == "session":
            sid, action = parts[3], parts[4]
            if sid not in SESSIONS:
                return self.reply(404, {"error": "no such session"})
            session = SESSIONS[sid]

            if action == "prompt":
                text = payload["prompt"]["text"]
                session["messages"].insert(0, {"id": "msg_u", "type": "user",
                                               "text": text})
                if MODE != "mute":
                    threading.Thread(target=answer, args=(session, text),
                                     daemon=True).start()
                return self.reply(200, {"data": {"admittedSeq": 1}})

            if action == "compact":
                session["messages"] = []
                return self.reply(200, {"data": {"ok": True}})

        return self.reply(404, {"error": "not found"})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", port_from_argv()), Handler).serve_forever()
