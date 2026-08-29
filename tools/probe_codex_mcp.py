#!/usr/bin/env python3
"""Same question, asked of `codex mcp-server` instead of app-server.

MCP over stdio: initialize -> notifications/initialized -> tools/list ->
tools/call codex -> tools/call codex-reply (same conversationId).

    /usr/bin/python3 tools/probe_codex_mcp.py
"""

import json
import os
import subprocess
import threading
import time
from queue import Empty, Queue

TIMEOUT = 180
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
    obj.setdefault("jsonrpc", "2.0")
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def wait_id(rid, what, timeout=TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ev = events.get(timeout=1.0)
        except Empty:
            continue
        seen.append(ev)
        if ev.get("id") == rid:
            return ev
    raise SystemExit("timed out waiting for %s; last:\n%s"
                     % (what, "\n".join(json.dumps(e)[:200] for e in seen[-10:])))


def text_of(result):
    """Pull the text out of an MCP tools/call result."""
    if not isinstance(result, dict):
        return str(result)[:400]
    out = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text", ""))
    return "\n".join(out).strip() or json.dumps(result)[:400]


def find_conversation_id(result):
    blob = json.dumps(result)
    for key in ("conversationId", "conversation_id", "sessionId", "threadId"):
        idx = blob.find('"%s"' % key)
        if idx >= 0:
            tail = blob[idx:]
            start = tail.find(":") + 1
            val = tail[start:].lstrip().lstrip('\\"').split('"')[0].split("\\")[0]
            if val:
                return val
    return None


def main():
    print("codex mcp-server probe")
    stderr_lines = []
    proc = subprocess.Popen(["codex", "mcp-server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    threading.Thread(target=pump, args=(proc.stdout,), daemon=True).start()
    threading.Thread(target=pump_err, args=(proc.stderr, stderr_lines), daemon=True).start()
    print("1. spawned, pid %d" % proc.pid)

    send(proc, {"id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "foundry-lab", "version": "0.0.1"}}})
    r = wait_id(1, "initialize", 30)
    print("2. initialize:", json.dumps(r.get("result", {}))[:200])

    send(proc, {"method": "notifications/initialized"})

    send(proc, {"id": 2, "method": "tools/list", "params": {}})
    r = wait_id(2, "tools/list", 30)
    tools = (r.get("result") or {}).get("tools") or []
    print("3. tools:", ", ".join(t.get("name", "?") for t in tools) or "(none)")
    names = [t.get("name") for t in tools]
    start_tool = "codex" if "codex" in names else (names[0] if names else None)
    reply_tool = "codex-reply" if "codex-reply" in names else None
    if not start_tool:
        raise SystemExit("no tools exposed")
    for t in tools:
        if t.get("name") == start_tool:
            props = ((t.get("inputSchema") or {}).get("properties") or {})
            print("   %s args: %s" % (start_tool, ", ".join(sorted(props))[:200]))

    t0 = time.time()
    send(proc, {"id": 3, "method": "tools/call", "params": {
        "name": start_tool,
        "arguments": {"prompt": "Remember this word: PELICAN. Reply with just: ok",
                      "cwd": os.getcwd()}}})
    r = wait_id(3, "first codex call")
    res1 = r.get("result") or r.get("error") or {}
    a1, s1 = text_of(res1), round(time.time() - t0, 1)
    conv = find_conversation_id(res1)
    print("4. turn 1 (%ss): %s" % (s1, a1[:160]))
    print("   conversationId:", conv)

    if not reply_tool or not conv:
        print("\nVERDICT: cannot continue — reply tool %s, conversationId %s"
              % (reply_tool, conv))
        proc.terminate()
        return

    t0 = time.time()
    send(proc, {"id": 4, "method": "tools/call", "params": {
        "name": reply_tool,
        "arguments": {"conversationId": conv,
                      "prompt": "What word did I ask you to remember? Reply with just that word."}}})
    r = wait_id(4, "codex-reply")
    res2 = r.get("result") or r.get("error") or {}
    a2, s2 = text_of(res2), round(time.time() - t0, 1)
    print("5. turn 2 (%ss): %s" % (s2, a2[:160]))

    alive = proc.poll() is None
    print()
    print("VERDICT")
    print("  one process for both turns : %s" % ("YES" if alive else "NO"))
    print("  context survived the turn  : %s"
          % ("YES" if "pelican" in a2.lower() else "NO — answer was: " + a2[:120]))
    print("  first turn / second turn   : %ss / %ss" % (s1, s2))
    if stderr_lines:
        print("  stderr tail: " + " | ".join(stderr_lines[-3:])[:300])

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    main()
