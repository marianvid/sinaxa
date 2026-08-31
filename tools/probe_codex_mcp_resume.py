#!/usr/bin/env python3
"""Can a FRESH `codex mcp-server` pick up a conversation started by a dead one?

Skips the `codex` tool entirely: spawns a new server and calls `codex-reply`
straight away with a conversationId from an earlier process.

    /usr/bin/python3 tools/probe_codex_mcp_resume.py <conversationId>
"""

import json
import subprocess
import sys
import threading
import time
from queue import Empty, Queue

events, seen = Queue(), []


def pump(stream):
    for line in stream:
        line = line.strip()
        if line:
            try:
                events.put(json.loads(line))
            except json.JSONDecodeError:
                pass


def send(proc, obj):
    obj.setdefault("jsonrpc", "2.0")
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def wait_id(rid, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except Empty:
            continue
        seen.append(ev)
        if ev.get("id") == rid:
            return ev
    raise SystemExit("timed out waiting for id=%s" % rid)


def text_of(result):
    if not isinstance(result, dict):
        return str(result)[:400]
    out = [b.get("text", "") for b in (result.get("content") or [])
           if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(out).strip() or json.dumps(result)[:400]


conv = sys.argv[1]
print("resuming conversation %s in a brand new mcp-server" % conv)
proc = subprocess.Popen(["codex", "mcp-server"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1)
threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
print("spawned pid", proc.pid)

send(proc, {"id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "sinaxa", "version": "0.0.1"}}})
wait_id(1, 30)
send(proc, {"method": "notifications/initialized"})

for attempt, args in enumerate([
        {"conversationId": conv, "prompt": "What word did I ask you to remember? Reply with just that word."},
        {"threadId": conv, "prompt": "What word did I ask you to remember? Reply with just that word."}], start=2):
    key = "conversationId" if "conversationId" in args else "threadId"
    t0 = time.time()
    send(proc, {"id": attempt, "method": "tools/call",
                "params": {"name": "codex-reply", "arguments": args}})
    r = wait_id(attempt)
    if "error" in r:
        print("  %-14s -> error: %s" % (key, json.dumps(r["error"])[:200]))
        continue
    answer = text_of(r.get("result") or {})
    print("  %-14s -> %s   (%.1fs)" % (key, answer[:120], time.time() - t0))
    print()
    print("VERDICT: resume into a fresh mcp-server %s"
          % ("WORKS" if "pelican" in answer.lower() else "answered but lost context"))
    break
else:
    print()
    print("VERDICT: a fresh mcp-server cannot resume an old conversation")

proc.terminate()
