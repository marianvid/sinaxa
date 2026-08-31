"""Codex over `codex mcp-server`.

One server process hosts every conversation. A conversation is created by
calling the `codex` tool and continued with `codex-reply`, keyed by the
conversationId the first call returns.

Streams `codex/event` notifications: enough for a live "working…" state and
a token counter, but the answer text arrives once, at the end.

Cannot be resumed after a restart — the conversation registry lives in the
server's memory. Recovery means replaying from the room.
"""

import json
import os
import subprocess
import threading
import time
from queue import Empty, Queue

START_TIMEOUT = 60
TURN_TIMEOUT = 600


class CodexMcpBackend:
    """One `codex mcp-server` process, many conversations."""

    label = "codex mcp-server"
    can_resume = False

    def __init__(self, cwd=None, binary="codex"):
        self.cwd = cwd or os.getcwd()
        self.binary = binary
        self._proc = None
        self._next_id = 1
        self._pending = {}                 # request id -> Queue
        self._listeners = {}               # conversation id -> callback
        self._unrouted = []                # events before we know the id
        self._lock = threading.Lock()
        self._stderr = []

    # ---------------------------------------------------------- lifecycle
    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    @property
    def pids(self):
        return [self._proc.pid] if self.alive else []

    def start(self):
        if self.alive:
            return self
        self._proc = subprocess.Popen(
            [self.binary, "mcp-server"], cwd=self.cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self._request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sinaxa", "version": "0.0.1"}},
            timeout=START_TIMEOUT)
        self._notify("notifications/initialized", {})
        return self

    def stop(self):
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stderr_tail(self, n=4):
        return " | ".join(self._stderr[-n:])

    # ---------------------------------------------------------- plumbing
    def _read(self):
        proc = self._proc
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                q = self._pending.pop(msg["id"], None)
                if q:
                    q.put(msg)
            elif msg.get("method") == "codex/event":
                self._dispatch_event(msg.get("params") or {})

    def _read_err(self):
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-40]

    def _dispatch_event(self, params):
        inner = params.get("msg") if isinstance(params.get("msg"), dict) else params
        conv = (params.get("conversationId") or params.get("conversation_id")
                or inner.get("session_id") or inner.get("conversation_id"))
        cb = self._listeners.get(conv)
        if cb:
            cb(inner)
        else:
            self._unrouted.append((conv, inner))
            del self._unrouted[:-50]

    def _notify(self, method, params):
        with self._lock:
            self._proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            self._proc.stdin.flush()

    def _request(self, method, params, timeout=TURN_TIMEOUT):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            q = Queue()
            self._pending[rid] = q
            self._proc.stdin.write(json.dumps(
                {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n")
            self._proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                return q.get(timeout=1.0)
            except Empty:
                if not self.alive:
                    raise RuntimeError("codex mcp-server died. " + self.stderr_tail())
        raise TimeoutError("%s took more than %ds" % (method, timeout))

    # ---------------------------------------------------------- agents
    def agent(self, name, model=None, instructions=None):
        return CodexMcpAgent(self, name, model, instructions)


def _text_of(result):
    if not isinstance(result, dict):
        return str(result)[:2000]
    out = [b.get("text", "") for b in (result.get("content") or [])
           if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(out).strip()


def _find_id(blob):
    for key in ("conversationId", "conversation_id", "threadId", "sessionId"):
        i = blob.find('"%s"' % key)
        if i < 0:
            continue
        val = blob[i:].split(":", 1)[1].lstrip().lstrip('\\"').split('"')[0].split("\\")[0]
        if val and val != "null":
            return val
    return None


class CodexMcpAgent:
    """One conversation on a shared mcp-server."""

    provider = "codex-cli"

    def __init__(self, backend, name, model=None, instructions=None):
        self.backend = backend
        self.name = name
        self.model = model
        self.instructions = instructions
        self.conversation_id = None
        self.activity = ""
        self.tokens = 0
        self.turns = 0
        self._lock = threading.Lock()

    def _on_event(self, ev):
        kind = ev.get("type") or ""
        if kind == "task_started":
            self.activity = "thinking"
        elif kind == "item_started":
            self.activity = "working"
        elif kind == "token_count":
            usage = ev.get("info") or ev.get("usage") or {}
            total = usage.get("total_token_usage") or usage
            if isinstance(total, dict) and total.get("total_tokens"):
                self.tokens = total["total_tokens"]
            self.activity = "working"
        elif kind == "task_complete":
            self.activity = ""

    def ask(self, text, timeout=TURN_TIMEOUT):
        with self._lock:
            self.backend.start()
            started = time.time()
            self.activity = "starting"
            if self.conversation_id is None:
                args = {"prompt": text, "cwd": self.backend.cwd,
                        "approval-policy": "never", "sandbox": "read-only"}
                if self.model:
                    args["model"] = self.model
                if self.instructions:
                    args["base-instructions"] = self.instructions
                reply = self.backend._request(
                    "tools/call", {"name": "codex", "arguments": args}, timeout)
                if "error" in reply:
                    self.activity = ""
                    return None, {"error": json.dumps(reply["error"])[:400]}
                self.conversation_id = _find_id(json.dumps(reply.get("result") or {}))
                if self.conversation_id:
                    self.backend._listeners[self.conversation_id] = self._on_event
            else:
                reply = self.backend._request("tools/call", {
                    "name": "codex-reply",
                    "arguments": {"conversationId": self.conversation_id,
                                  "prompt": text}}, timeout)
                if "error" in reply:
                    self.activity = ""
                    return None, {"error": json.dumps(reply["error"])[:400]}

            self.activity = ""
            self.turns += 1
            answer = _text_of(reply.get("result") or {})
            return answer or "(empty answer)", {
                "elapsed": round(time.time() - started, 1),
                "tokens": self.tokens or None}

    def status(self):
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.conversation_id or "")[:8],
                "activity": self.activity, "turns": self.turns,
                "tokens": self.tokens, "alive": self.backend.alive,
                "pids": self.backend.pids, "shared_process": True}

    def stop(self):
        self.conversation_id = None
