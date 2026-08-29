"""Codex over `codex app-server`.

Same shape as codex_mcp.py, different protocol underneath:

    initialize -> initialized -> thread/start -> turn/start -> turn/start

One server process hosts every thread. Notifications carry `threadId`, so
concurrent turns on different threads stay separable. Answers arrive as
deltas, so the text can be rendered while it is written.

Unlike mcp-server, a thread survives a restart: `thread/resume` in a brand
new process picks it up from disk.

`codex app-server` is marked [experimental] by its own CLI. The probes in
tools/ exist to tell us the moment the protocol moves.
"""

import json
import os
import subprocess
import threading
import time
from queue import Empty, Queue

START_TIMEOUT = 60
TURN_TIMEOUT = 600


class CodexAppBackend:
    label = "codex app-server"
    can_resume = True

    def __init__(self, cwd=None, binary="codex"):
        self.cwd = cwd or os.getcwd()
        self.binary = binary
        self._proc = None
        self._next_id = 1
        self._pending = {}                 # request id -> Queue
        self._threads = {}                 # thread id -> agent
        self._lock = threading.Lock()
        self._stderr = []

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
            [self.binary, "app-server"], cwd=self.cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        self._request("initialize", {
            "clientInfo": {"name": "foundry-lab", "title": "foundry-lab",
                           "version": "0.0.1"},
            "capabilities": {"experimentalApi": True}}, timeout=START_TIMEOUT)
        self._notify("initialized", {})
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
        for line in self._proc.stdout:
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
                continue
            params = msg.get("params") or {}
            tid = (params.get("threadId") or params.get("thread_id")
                   or (params.get("thread") or {}).get("id"))
            agent = self._threads.get(tid)
            if agent:
                agent._on_event(msg.get("method", ""), params)

    def _read_err(self):
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-40]

    def _notify(self, method, params):
        with self._lock:
            self._proc.stdin.write(json.dumps(
                {"method": method, "params": params}) + "\n")
            self._proc.stdin.flush()

    def _request(self, method, params, timeout=TURN_TIMEOUT):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            q = Queue()
            self._pending[rid] = q
            self._proc.stdin.write(json.dumps(
                {"id": rid, "method": method, "params": params}) + "\n")
            self._proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                return q.get(timeout=1.0)
            except Empty:
                if not self.alive:
                    raise RuntimeError("codex app-server died. " + self.stderr_tail())
        raise TimeoutError("%s took more than %ds" % (method, timeout))

    def agent(self, name, model=None, instructions=None):
        return CodexAppAgent(self, name, model, instructions)


class CodexAppAgent:
    provider = "codex-cli"

    def __init__(self, backend, name, model=None, instructions=None):
        self.backend = backend
        self.name = name
        self.model = model
        self.instructions = instructions
        self.thread_id = None
        self.activity = ""
        self.tokens = 0
        self.turns = 0
        self._chunks = []
        self._done = threading.Event()
        self._error = None
        self._lock = threading.Lock()

    # ------------------------------------------------------- event sink
    def _on_event(self, method, params):
        low = method.lower()
        if "delta" in low:
            piece = params.get("delta") or params.get("text") or ""
            if piece:
                self._chunks.append(piece)
                self.activity = "writing"
        elif "tokenusage" in low.replace("/", "").replace("_", ""):
            usage = params.get("tokenUsage") or {}
            self.tokens = usage.get("totalTokens") or usage.get("total_tokens") or self.tokens
        elif "turn/started" in low or "turnstarted" in low:
            self.activity = "thinking"
        elif "item/started" in low:
            self.activity = "working"
        elif "item/completed" in low:
            item = params.get("item") or {}
            if item.get("type") in ("agentMessage", "agent_message") and item.get("text") \
                    and not self._chunks:
                self._chunks.append(item["text"])
        elif "turn/failed" in low:
            self._error = json.dumps(params)[:400]
            self._done.set()
        elif "turn/completed" in low:
            self._done.set()

    # ------------------------------------------------------- one turn
    def _ensure_thread(self, timeout):
        if self.thread_id:
            return
        params = {"cwd": self.backend.cwd}
        if self.model:
            params["model"] = self.model
        reply = self.backend._request("thread/start", params, timeout)
        if "error" in reply:
            raise RuntimeError(json.dumps(reply["error"])[:400])
        result = reply.get("result") or {}
        self.thread_id = (result.get("threadId") or result.get("thread_id")
                          or (result.get("thread") or {}).get("id"))
        if not self.thread_id:
            raise RuntimeError("thread/start returned no id: " + json.dumps(result)[:300])
        self.backend._threads[self.thread_id] = self

    def resume(self, thread_id, timeout=START_TIMEOUT):
        """Pick up a thread from disk after a restart."""
        self.backend.start()
        reply = self.backend._request(
            "thread/resume", {"threadId": thread_id, "cwd": self.backend.cwd}, timeout)
        if "error" in reply:
            return False
        self.thread_id = thread_id
        self.backend._threads[thread_id] = self
        return True

    def ask(self, text, timeout=TURN_TIMEOUT):
        with self._lock:
            self.backend.start()
            started = time.time()
            self.activity = "starting"
            self._chunks, self._error = [], None
            self._done.clear()
            try:
                self._ensure_thread(timeout)
            except RuntimeError as exc:
                self.activity = ""
                return None, {"error": str(exc)}

            prompt = text
            if self.instructions and self.turns == 0:
                prompt = self.instructions + "\n\n---\n\n" + text

            reply = self.backend._request("turn/start", {
                "threadId": self.thread_id,
                "clientUserMessageId": "%s-%d" % (self.name, self.turns + 1),
                "input": [{"type": "text", "text": prompt}]}, timeout)
            if "error" in reply:
                self.activity = ""
                return None, {"error": json.dumps(reply["error"])[:400]}

            if not self._done.wait(timeout):
                self.activity = ""
                return None, {"error": "no turn/completed in %ds" % timeout}

            self.activity = ""
            self.turns += 1
            if self._error:
                return None, {"error": self._error}
            answer = "".join(self._chunks).strip()
            return answer or "(empty answer)", {
                "elapsed": round(time.time() - started, 1),
                "tokens": self.tokens or None}

    def status(self):
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.thread_id or "")[:8],
                "activity": self.activity, "turns": self.turns,
                "tokens": self.tokens, "alive": self.backend.alive,
                "pids": self.backend.pids, "shared_process": True}

    def stop(self):
        if self.thread_id:
            self.backend._threads.pop(self.thread_id, None)
        self.thread_id = None
