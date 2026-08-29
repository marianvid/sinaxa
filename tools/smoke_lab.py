#!/usr/bin/env python3
"""Drive the lab without the browser: broadcast, then agent-to-agent.

    /usr/bin/python3 tools/smoke_lab.py mcp
    /usr/bin/python3 tools/smoke_lab.py app
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab as L

backend = sys.argv[1] if len(sys.argv) > 1 else "mcp"
L.SCOPE = "room"
L.STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
lab = L.Lab(backend, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
lab.log = os.path.join(L.STATE, "smoke-%s.jsonl" % backend)
for r in lab.rooms.values():
    r.messages = []

room = lab.rooms["team"]
print("== broadcast to # team (%s) ==" % backend)
t0 = time.time()
lab.send(room, "One sentence each: who are you and what model are you running?")
for m in room.messages:
    who = lab.members.get(m["author"], {}).get("name", m["author"])
    meta = m.get("meta") or {}
    print("  %-7s %s%s" % (who, (m["text"] or "")[:150].replace("\n", " "),
                           "  [%ss]" % meta["elapsed"] if meta.get("elapsed") else ""))
print("  total %.1fs" % (time.time() - t0))

print()
print("== agent to agent ==")
before = len(room.messages)
t0 = time.time()
lab.send(room, "@Codex — ask @Claude in one short question whether per-room "
               "sequence numbers should be gapless, then stop.")
for m in room.messages[before:]:
    who = lab.members.get(m["author"], {}).get("name", m["author"])
    print("  %-7s %s" % (who, (m["text"] or "")[:200].replace("\n", " ")))
print("  total %.1fs" % (time.time() - t0))

print()
print("== status ==")
print(json.dumps(lab.status(), indent=2)[:1200])

for a in lab.agents.values():
    a.stop()
for b in (lab.claude_backend, lab.codex_backend):
    if b:
        b.stop()
