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
        from .codex_mcp_agent import CodexMcpAgent

        return CodexMcpAgent(self, name, model, instructions)


from .codex_mcp_agent import CodexMcpAgent  # compatibility export
