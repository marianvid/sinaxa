#!/usr/bin/env python3
"""Can a FRESH `codex app-server` resume a thread from an earlier process?

    /usr/bin/python3 tools/probe_codex_appserver_resume.py <threadId>
"""

import json
import os
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
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def wait_id(rid, timeout=120):
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


def collect_turn(timeout=120):
    text, t0 = [], time.time()
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except Empty:
            continue
        seen.append(ev)
        m, p = ev.get("method", ""), ev.get("params") or {}
        if "delta" in m.lower():
            text.append(p.get("delta") or p.get("text") or "")
        elif "turn/completed" in m:
            return "".join(text).strip(), round(time.time() - t0, 1)
        elif "error" in ev:
            return "ERROR " + json.dumps(ev["error"])[:200], round(time.time() - t0, 1)
    return "".join(text).strip() or "(no turn/completed)", round(time.time() - t0, 1)


tid = sys.argv[1]
print("resuming thread %s in a brand new app-server" % tid)
proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1)
threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
print("spawned pid", proc.pid)

send(proc, {"id": 1, "method": "initialize", "params": {
    "clientInfo": {"name": "foundry-lab", "title": "probe", "version": "0.0.1"},
    "capabilities": {"experimentalApi": True}}})
wait_id(1, 30)
send(proc, {"method": "initialized", "params": {}})

send(proc, {"id": 2, "method": "thread/resume",
            "params": {"threadId": tid, "cwd": os.getcwd()}})
r = wait_id(2, 60)
if "error" in r:
    print("thread/resume error:", json.dumps(r["error"])[:300])
    print("\nVERDICT: a fresh app-server cannot resume this thread")
    proc.terminate()
    raise SystemExit(0)
print("thread/resume ok:", json.dumps(r.get("result", {}))[:200])

send(proc, {"id": 3, "method": "turn/start", "params": {
    "threadId": tid, "clientUserMessageId": "resume-probe",
    "input": [{"type": "text",
               "text": "What word did I ask you to remember? Reply with just that word."}]}})
answer, secs = collect_turn()
print("answer (%ss): %s" % (secs, answer[:160]))
print()
print("VERDICT: resume into a fresh app-server %s"
      % ("WORKS" if "pelican" in answer.lower() else "answered but lost context"))
proc.terminate()
