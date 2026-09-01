#!/usr/bin/env python3
"""Stands in for the `claude` binary.

Speaks the same stream-json dialect the real one does, so the adapter is
exercised for real -- a real subprocess, real pipes, real framing -- without
a network call or a subscription.

    FAKE_LOG    file to append the argv to, one JSON line per spawn
    FAKE_MODE   normal | die | silent | noresult | linger

`linger` keeps running after its input closes, the way a real process under
its own supervision may. It is what makes an orphan detectable: a fake that
politely dies with its parent would let a broken shutdown pass for a good
one.
"""

import json
import os
import sys
import time

LOG = os.environ.get("FAKE_LOG")
MODE = os.environ.get("FAKE_MODE", "normal")

if LOG:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")

if MODE == "die":
    sys.stderr.write("fake claude refused to start\n")
    sys.exit(3)


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def session_id_from_argv():
    for flag in ("--session-id", "--resume"):
        if flag in sys.argv:
            return sys.argv[sys.argv.index(flag) + 1]
    return "no-session"


SESSION = session_id_from_argv()
seen = []

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    envelope = json.loads(line)
    text = "".join(part.get("text", "") for part
                   in envelope.get("message", {}).get("content", []))
    seen.append(text)

    if MODE == "silent":
        time.sleep(30)
        continue

    emit({"type": "system", "subtype": "init", "session_id": SESSION})
    answer = "turn %d, you said %r, first was %r" % (len(seen), text, seen[0])
    emit({"type": "assistant",
          "message": {"content": [{"type": "text", "text": answer}]}})

    if MODE == "noresult":
        continue

    emit({"type": "result", "subtype": "success", "session_id": SESSION,
          "result": answer, "duration_ms": 1234, "total_cost_usd": 0.0102,
          "usage": {"input_tokens": 10, "output_tokens": 5,
                    "cache_read_input_tokens": 100}})

if MODE == "linger":
    time.sleep(120)
