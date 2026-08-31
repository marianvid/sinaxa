#!/usr/bin/env python3
"""Does `codex mcp-server` stream anything during a turn?

Logs every notification received while one `codex` tool call runs, then
asks a second question to confirm the context accumulated.

    /usr/bin/python3 tools/probe_codex_mcp_events.py
"""

import json
import os
import subprocess
import threading
import time
from queue import Empty, Queue

events = Queue()
notes = []          # (seconds, method, short payload)


def pump(stream):
    for line in stream:
        line = line.strip()
        if line:
            try:
                events.put((time.time(), json.loads(line)))
            except json.JSONDecodeError:
                pass


def send(proc, obj):
    obj.setdefault("jsonrpc", "2.0")
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def call(proc, rid, name, args, t0, log=False):
    send(proc, {"id": rid, "method": "tools/call",
                "params": {"name": name, "arguments": args}})
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            ts, ev = events.get(timeout=1.0)
        except Empty:
            continue
        if ev.get("id") == rid:
            return ev
        m = ev.get("method")
        if m and log:
            p = ev.get("params") or {}
            inner = p.get("msg") or p
            kind = inner.get("type") if isinstance(inner, dict) else "?"
            body = json.dumps(inner)[:90] if isinstance(inner, dict) else ""
            notes.append((round(ts - t0, 1), m, kind, body))
    raise SystemExit("timed out on id=%s" % rid)


def text_of(r):
    res = r.get("result") or {}
    out = [b.get("text", "") for b in (res.get("content") or [])
           if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(out).strip() or json.dumps(r)[:300]


proc = subprocess.Popen(["codex", "mcp-server"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1)
threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()

send(proc, {"id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "sinaxa", "version": "0.0.1"}}})
while True:
    _, ev = events.get(timeout=30)
    if ev.get("id") == 1:
        break
send(proc, {"method": "notifications/initialized"})

t0 = time.time()
r = call(proc, 2, "codex", {
    "prompt": "Remember the word PELICAN. Then count slowly from 1 to 5, "
              "one number per line, with a short sentence about each number.",
    "cwd": os.getcwd(), "approval-policy": "never", "sandbox": "read-only"},
    t0, log=True)
a1 = text_of(r)
conv = None
blob = json.dumps(r)
for key in ("conversationId", "threadId"):
    i = blob.find('"%s"' % key)
    if i >= 0:
        conv = blob[i:].split(":", 1)[1].lstrip().lstrip('\\"').split('"')[0].split("\\")[0]
        break

print("notifications during the turn: %d" % len(notes))
kinds = {}
for secs, method, kind, body in notes:
    kinds[(method, kind)] = kinds.get((method, kind), 0) + 1
for (method, kind), n in sorted(kinds.items(), key=lambda kv: -kv[1]):
    print("   %-16s %-28s x%d" % (method, kind, n))
print()
print("first 12, with timing:")
for secs, method, kind, body in notes[:12]:
    print("   %5ss  %-14s %s" % (secs, kind, body[:80]))
print()
print("final answer (%.1fs): %s" % (time.time() - t0, a1[:100].replace("\n", " / ")))
print("conversationId:", conv)

if conv:
    t1 = time.time()
    r2 = call(proc, 3, "codex-reply", {
        "conversationId": conv,
        "prompt": "What word did I ask you to remember? Reply with just that word."}, t1)
    a2 = text_of(r2)
    print("second turn (%.1fs): %s" % (time.time() - t1, a2[:80]))
    print()
    print("VERDICT")
    print("  streams during a turn : %s" % ("YES" if notes else "NO"))
    print("  context accumulates   : %s" % ("YES" if "pelican" in a2.lower() else "NO"))
proc.terminate()
