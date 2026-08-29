#!/usr/bin/env python3
"""Does `codex app-server` hold a conversation across turns, in one process?

Speaks the app-server protocol over stdio (newline-delimited JSON-RPC):
  initialize -> initialized -> thread/start -> turn/start -> turn/start

The second turn asks about the first. If the answer shows it remembers, the
context lives in the thread and we never have to resend history.

    /usr/bin/python3 tools/probe_codex.py
"""

import json
import os
import subprocess
import sys
import threading
import time
from queue import Empty, Queue

TIMEOUT = 120
events = Queue()
seen = []


def pump(stream):
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            events.put(json.loads(line))
        except json.JSONDecodeError:
            events.put({"_raw": line})


def pump_err(stream, sink):
    for line in stream:
        sink.append(line.rstrip())


def send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def wait_for(pred, what, timeout=TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except Empty:
            continue
        seen.append(ev)
        kind = ev.get("method") or ("response id=%s" % ev.get("id"))
        if "error" in ev:
            print("   ! error: %s" % json.dumps(ev["error"])[:300])
        if pred(ev):
            return ev
    raise SystemExit("timed out waiting for %s\nlast events:\n%s"
                     % (what, "\n".join(json.dumps(e)[:200] for e in seen[-12:])))


def collect_turn(label):
    """Gather agentMessage deltas until turn/completed."""
    text, t0 = [], time.time()
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except Empty:
            continue
        seen.append(ev)
        m = ev.get("method", "")
        p = ev.get("params", {}) or {}
        if "delta" in m.lower():
            text.append(p.get("delta") or p.get("text") or "")
        elif m.endswith("agentMessage") or m.endswith("item/completed"):
            item = p.get("item") or {}
            if item.get("text"):
                text.append(item["text"])
        elif "turn/completed" in m or m.endswith("turnCompleted"):
            return "".join(text).strip(), round(time.time() - t0, 1)
        elif "error" in ev:
            return "ERROR: " + json.dumps(ev["error"])[:300], round(time.time() - t0, 1)
    return "".join(text).strip() or "(no turn/completed seen)", round(time.time() - t0, 1)


def main():
    print("codex app-server probe")
    print("cwd:", os.getcwd())
    stderr_lines = []
    t0 = time.time()
    proc = subprocess.Popen(
        ["codex", "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)
    threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=pump_err, args=(proc.stderr, stderr_lines), daemon=True).start()
    print("1. spawned, pid %d (%.1fs)" % (proc.pid, time.time() - t0))

    send(proc, {"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "foundry-lab", "title": "foundry-lab probe", "version": "0.0.1"},
        "capabilities": {"experimentalApi": True}}})
    r = wait_for(lambda e: e.get("id") == 1, "initialize response", 30)
    print("2. initialize ok:", json.dumps(r.get("result", {}))[:200])

    send(proc, {"method": "initialized", "params": {}})
    print("3. initialized sent")

    send(proc, {"id": 2, "method": "thread/start", "params": {"cwd": os.getcwd()}})
    r = wait_for(lambda e: e.get("id") == 2, "thread/start response", 60)
    result = r.get("result") or {}
    thread_id = result.get("threadId") or result.get("thread_id") or (
        (result.get("thread") or {}).get("id"))
    print("4. thread/start ->", thread_id or json.dumps(result)[:200])
    if not thread_id:
        raise SystemExit("no thread id in response; full result:\n" + json.dumps(result)[:1000])

    send(proc, {"id": 3, "method": "turn/start", "params": {
        "threadId": thread_id, "clientUserMessageId": "probe-1",
        "input": [{"type": "text", "text":
                   "Remember this word: PELICAN. Reply with just: ok"}]}})
    answer, secs = collect_turn("turn 1")
    print("5. turn 1 (%ss): %s" % (secs, answer[:200]))

    send(proc, {"id": 4, "method": "turn/start", "params": {
        "threadId": thread_id, "clientUserMessageId": "probe-2",
        "input": [{"type": "text", "text":
                   "What word did I ask you to remember? Reply with just that word."}]}})
    answer2, secs2 = collect_turn("turn 2")
    print("6. turn 2 (%ss): %s" % (secs2, answer2[:200]))

    alive = proc.poll() is None
    print()
    print("VERDICT")
    print("  one process for both turns : %s (pid %d, %s)"
          % ("YES" if alive else "NO", proc.pid, "alive" if alive else "died"))
    print("  context survived the turn  : %s"
          % ("YES" if "pelican" in answer2.lower() else "NO — answer was: " + answer2[:120]))
    print("  first turn / second turn   : %ss / %ss" % (secs, secs2))
    if stderr_lines:
        print("  stderr tail: " + " | ".join(stderr_lines[-3:])[:300])

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print("FAILED:", exc)
        sys.exit(1)
