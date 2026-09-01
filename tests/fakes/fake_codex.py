#!/usr/bin/env python3
"""Stands in for `codex app-server`.

Replies with the shapes the real 0.144.5 server sends -- which is the point:
the nesting is where the bugs were. `thread/start` answers with the id under
`thread.id`, and token usage arrives under `tokenUsage.total.totalTokens`.

Prompt keywords steer a turn:
    FAIL      -> turn/failed instead of an answer
    NODELTA   -> no deltas, the text only in item/completed
    SLOW      -> events, but never turn/completed
"""

import json
import os
import sys
import time

LOG = os.environ.get("FAKE_LOG")
if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")

threads = {}          # thread id -> number of turns so far
counter = [0]


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def event(method, params):
    emit({"method": method, "params": params})


def turn(tid, prompt):
    threads[tid] = threads.get(tid, 0) + 1
    event("turn/started", {"threadId": tid})
    event("item/started", {"threadId": tid, "item": {"type": "agentMessage"}})

    if "FAIL" in prompt:
        event("turn/failed", {"threadId": tid, "error": {"message": "nope"}})
        return
    if "SLOW" in prompt:
        return

    answer = "turn %d on %s: %s" % (threads[tid], tid, prompt[:40])
    if "NODELTA" in prompt:
        event("item/completed", {"threadId": tid,
                                 "item": {"type": "agentMessage", "text": answer}})
    else:
        for piece in (answer[:10], answer[10:]):
            event("item/agentMessage/delta", {"threadId": tid, "delta": piece})
        event("item/completed", {"threadId": tid,
                                 "item": {"type": "agentMessage",
                                          "text": "SHOULD BE IGNORED"}})

    event("thread/tokenUsage/updated", {
        "threadId": tid,
        "tokenUsage": {"total": {"totalTokens": 1000 * threads[tid],
                                 "inputTokens": 900, "outputTokens": 100},
                       "last": {"totalTokens": 7}}})
    event("turn/completed", {"threadId": tid, "turn": {"status": "completed"}})


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method, params, rid = msg.get("method"), msg.get("params") or {}, msg.get("id")
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"rpc": method}) + "\n")

    if method == "initialize":
        emit({"id": rid, "result": {"userAgent": "fake/0"}})
    elif method == "initialized":
        pass
    elif method == "thread/start":
        counter[0] += 1
        tid = "th-%d" % counter[0]
        threads[tid] = 0
        emit({"id": rid, "result": {"thread": {"id": tid, "sessionId": tid}}})
        event("thread/started", {"thread": {"id": tid}})
    elif method == "thread/resume":
        tid = params.get("threadId", "")
        if tid.startswith("th-"):
            threads.setdefault(tid, 9)
            emit({"id": rid, "result": {"thread": {"id": tid}}})
        else:
            emit({"id": rid, "error": {"code": -32602, "message": "no such thread"}})
    elif method == "turn/start":
        emit({"id": rid, "result": {}})
        tid = params.get("threadId")
        prompt = "".join(p.get("text", "") for p in params.get("input", []))
        turn(tid, prompt)
    else:
        emit({"id": rid, "error": {"code": -32601, "message": "unknown " + str(method)}})
