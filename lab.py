#!/usr/bin/env python3
"""kenbet MVP 2 — you, Claude and Codex, in rooms.

    /usr/bin/python3 lab.py --codex mcp     # codex mcp-server   (stable)
    /usr/bin/python3 lab.py --codex app     # codex app-server   (experimental)

Same code either way; only the Codex adapter changes, so the two runs are
comparable. Each backend keeps its own transcript under state/.

Rooms:
    main        you + Claude + Codex
    claude      you + Claude
    codex       you + Codex

Who answers: name someone with @ and only they answer; name nobody and every
agent in the room answers. Agents address each other the same way, up to
MAX_HOPS times per message you send, so a politeness loop cannot run away.
"""

import argparse
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 8789
ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
UI = os.path.join(ROOT, "ui", "lab.html")
MAX_HOPS = 3
TURN_TIMEOUT = 600

HUMAN = "Marian"

SYSTEM = """You are {name}, a member of the room "# {room}" in kenbet, \
a workspace where every participant is an AI agent plus one human.

Members of this room: {members}. {HUMAN} is the human and the lead.

To address another member, write @TheirName in your reply — the server \
delivers your message to them and their answer comes back into this room. \
Only do that when you actually need them; every mention costs a model call.

Keep replies short — a few sentences unless asked for more. Do not greet \
repeatedly. You are talking to colleagues, not writing documentation."""


# ------------------------------------------------------------------ model
class Room:
    """A room behaves like a Teams channel.

    Everything written here is visible to every member. If you name someone
    with @, only they answer. If you name nobody, every agent answers —
    order does not matter, except that the lead's message comes first, which
    it does anyway because the lead is the one writing.
    """

    def __init__(self, key, name, members):
        self.key = key
        self.name = name
        self.members = members          # member keys, lead first
        self.messages = []
        self.busy = False


class Lab:
    def __init__(self, backend_name, cwd):
        self.backend_name = backend_name
        self.cwd = cwd
        self.log = os.path.join(STATE, "lab-%s.jsonl" % backend_name)
        self.claude_backend = None
        self.codex_backend = None
        self.agents = {}                # (member, room) -> agent
        self.members = {
            "you":    {"name": HUMAN, "kind": "human", "initial": "M",
                       "color": "#2f6fd0", "model": "human · cto"},
            "claude": {"name": "Claude", "kind": "agent", "initial": "A",
                       "color": "#c96442", "model": "claude-cli"},
            "codex":  {"name": "Codex", "kind": "agent", "initial": "C",
                       "color": "#3fbf7f", "model": "codex-cli"},
        }
        # Seats belong to the session, not to a room. A seat is a role; an
        # occupant fills it, or it stays empty. The lead seat is present in
        # main and in every subroom.
        self.seats = [
            {"id": "cto",       "role": "cto",       "occupant": "you",    "lead": True},
            {"id": "architect", "role": "architect", "occupant": "claude", "lead": False},
            {"id": "backend",   "role": "backend",   "occupant": "codex",  "lead": False},
            {"id": "reviewer",  "role": "reviewer",  "occupant": None,     "lead": False},
        ]
        self.rooms = {
            "main":   Room("main", "main", ["you", "claude", "codex"]),
            "claude": Room("claude", "claude", ["you", "claude"]),
            "codex":  Room("codex", "codex", ["you", "codex"]),
        }
        self.by_name = {m["name"].lower(): k for k, m in self.members.items()}
        self._load()

    # -------------------------------------------------------------- disk
    def _load(self):
        if not os.path.exists(self.log):
            return
        with open(self.log, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                room = self.rooms.get(msg.get("room"))
                if room:
                    room.messages.append(msg)

    def append(self, room, author, text, meta=None, kind=None):
        msg = {"room": room.key, "author": author, "text": text,
               "ts": time.time()}
        if meta:
            msg["meta"] = meta
        if kind:
            msg["kind"] = kind
        room.messages.append(msg)
        os.makedirs(STATE, exist_ok=True)
        with open(self.log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return msg

    # ------------------------------------------------------------ agents
    def agent_for(self, member, room):
        key = (member, room.key) if SCOPE == "room" else (member, "*")
        if key in self.agents:
            return self.agents[key]

        names = ", ".join(self.members[m]["name"] for m in room.members)
        prompt = SYSTEM.format(name=self.members[member]["name"],
                               room=room.name, members=names, HUMAN=HUMAN)
        if member == "claude":
            if self.claude_backend is None:
                from claude_cli import ClaudeBackend
                self.claude_backend = ClaudeBackend(cwd=self.cwd)
            agent = self.claude_backend.agent("claude", instructions=prompt)
        else:
            if self.codex_backend is None:
                if self.backend_name == "app":
                    from codex_app import CodexAppBackend
                    self.codex_backend = CodexAppBackend(cwd=self.cwd)
                else:
                    from codex_mcp import CodexMcpBackend
                    self.codex_backend = CodexMcpBackend(cwd=self.cwd)
            agent = self.codex_backend.agent("codex", instructions=prompt)
        self.agents[key] = agent
        return agent

    def seats_of(self, room):
        """Main shows every seat, empty ones included — it is the team.
        A subroom shows the seats whose occupant is in it, plus the lead."""
        if room.key == "main":
            return self.seats
        return [s for s in self.seats
                if s["lead"] or (s["occupant"] and s["occupant"] in room.members)]

    # ------------------------------------------------------- turn-taking
    def mentioned(self, text, room, exclude=()):
        out = []
        for member in room.members:
            if member in exclude or self.members[member]["kind"] != "agent":
                continue
            if re.search(r"@%s\b" % re.escape(self.members[member]["name"]),
                         text, re.IGNORECASE):
                out.append(member)
        return out

    def speakers_for(self, room, text, author):
        """Named with @ -> only them. Nobody named -> everyone."""
        agents = [m for m in room.members
                  if self.members[m]["kind"] == "agent" and m != author]
        named = self.mentioned(text, room, exclude=(author,))
        return named or agents

    def run_turn(self, room, author, text, hops, targets=None):
        """Ask everyone who should answer, then follow their @mentions.

        `targets` is set when one agent addressed another: the reply goes to
        exactly those members, never to the whole room. Without this, a
        broadcast room re-broadcasts every agent reply and the same question
        gets asked twice.
        """
        speakers = targets if targets is not None else self.speakers_for(room, text, author)
        if not speakers:
            return

        prefix = "[%s] " % self.members[author]["name"]
        results = {}

        def work(member):
            agent = self.agent_for(member, room)
            answer, meta = agent.ask(prefix + text, timeout=TURN_TIMEOUT)
            results[member] = (answer, meta)

        threads = [threading.Thread(target=work, args=(m,), daemon=True)
                   for m in speakers]
        for t in threads:
            t.start()
        for t in threads:
            t.join(TURN_TIMEOUT + 30)

        follow = []
        for member in speakers:
            answer, meta = results.get(member, (None, {"error": "no result"}))
            if answer is None:
                self.append(room, "system",
                            "%s could not answer: %s" % (self.members[member]["name"],
                                                         meta.get("error", "?")),
                            kind="error")
                continue
            self.append(room, member, answer, meta=meta)
            if hops > 0:
                for target in self.mentioned(answer, room, exclude=(member,)):
                    follow.append((member, target, answer))

        # Deliver each reply only to the members it named. Depth is capped by
        # hops, breadth by the fact that a reply reaches only its addressees.
        for source, target, answer in follow:
            self.run_turn(room, source, answer, hops - 1, targets=[target])

    def send(self, room, text):
        self.append(room, "you", text)
        room.busy = True
        room.busy_cancelled = False
        try:
            self.run_turn(room, "you", text, MAX_HOPS)
        finally:
            room.busy = False

    # ------------------------------------------------------------ status
    def status(self):
        agents = []
        total_rss = 0
        for (member, scope), agent in sorted(self.agents.items()):
            st = agent.status()
            st["member"] = self.members[member]["name"]
            st["scope"] = scope
            for pid in st.get("pids", []):
                if not st.get("shared_process") or member == "codex":
                    pass
            total_rss += st.get("rss_kb", 0)
            agents.append(st)
        shared = []
        for backend in (self.codex_backend,):
            if backend is not None and backend.alive:
                for pid in backend.pids:
                    rss = _rss_kb(pid)
                    total_rss += rss
                    shared.append({"label": backend.label, "pid": pid, "rss_kb": rss})
        return {"backend": self.backend_name, "agents": agents,
                "shared": shared, "total_rss_mb": round(total_rss / 1024.0, 1),
                "scope": SCOPE}


def _rss_kb(pid):
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


Room.busy_cancelled = False


# -------------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    lab = None

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
        if self.path == "/kenbet.css":
            with open(os.path.join(ROOT, "ui", "kenbet.css"), "rb") as fh:
                return self._send(200, fh.read(), "text/css; charset=utf-8")
        if self.path.startswith("/api/state"):
            lab = self.lab
            return self._send(200, {
                "members": lab.members,
                "seats": lab.seats,
                "rooms": [{"key": r.key, "name": r.name, "members": r.members,
                           "busy": r.busy, "messages": r.messages,
                           "seats": [s["id"] for s in lab.seats_of(r)]}
                          for r in lab.rooms.values()],
                "status": lab.status(),
            })
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        lab = self.lab

        if self.path == "/api/send":
            room = lab.rooms.get(body.get("room") or "main")
            text = (body.get("text") or "").strip()
            if not room or not text:
                return self._send(400, {"error": "room and text required"})
            if room.busy:
                return self._send(409, {"error": "that room is still working"})
            threading.Thread(target=lab.send, args=(room, text), daemon=True).start()
            return self._send(200, {"ok": True})

        if self.path == "/api/reset":
            member = body.get("member")
            room = lab.rooms.get(body.get("room") or "")
            if not room:
                return self._send(400, {"error": "bad room"})
            key = (member, room.key) if SCOPE == "room" else (member, "*")
            agent = lab.agents.pop(key, None)
            if agent:
                agent.stop()
            lab.append(room, "system",
                       "context cleared for %s — the room keeps its history"
                       % lab.members[member]["name"], kind="system")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    global SCOPE
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex", choices=["mcp", "app"], default="mcp")
    ap.add_argument("--scope", choices=["room", "member"], default="room")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--cwd", default=ROOT)
    args = ap.parse_args()
    SCOPE = args.scope

    os.makedirs(STATE, exist_ok=True)
    Handler.lab = Lab(args.codex, args.cwd)
    print("kenbet   →  http://%s:%d" % (HOST, args.port))
    print("codex backend →  %s" % ("codex app-server (experimental)"
                                   if args.codex == "app" else "codex mcp-server"))
    print("conversations →  one per (member x %s)" % args.scope)
    print("transcript    →  %s" % Handler.lab.log)
    try:
        ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopping agents…")
        for agent in Handler.lab.agents.values():
            agent.stop()
        for backend in (Handler.lab.claude_backend, Handler.lab.codex_backend):
            if backend:
                backend.stop()


SCOPE = "room"

if __name__ == "__main__":
    main()
