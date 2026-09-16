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


def close(stream):
    try:
        if stream is not None:
            stream.close()
    except Exception:
        pass


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
        self._readers = []

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
        self._readers = [
            threading.Thread(target=self._read, args=(self._proc,), daemon=True),
            threading.Thread(target=self._read_err, args=(self._proc,),
                             daemon=True)]
        for reader in self._readers:
            reader.start()
        self._request("initialize", {
            "clientInfo": {"name": "sinaxa", "title": "sinaxa",
                           "version": "0.0.1"},
            "capabilities": {"experimentalApi": True}}, timeout=START_TIMEOUT)
        self._notify("initialized", {})
        return self

    def stop(self):
        """Every pipe closed, the process reaped, the readers wound down.

        One server holds every thread, so a leak here is a leak for the whole
        of sinaxa.
        """
        proc, self._proc = self._proc, None
        readers, self._readers = self._readers, []
        self._threads.clear()
        if proc is None:
            return

        close(proc.stdin)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        else:
            proc.wait()

        for reader in readers:
            reader.join(timeout=2)
        close(proc.stdout)
        close(proc.stderr)

    def stderr_tail(self, n=4):
        return " | ".join(self._stderr[-n:])

    # ---------------------------------------------------------- plumbing
    def _read(self, proc):
        try:
            self._read_lines(proc)
        except (ValueError, OSError):
            pass                    # the pipe was closed under us: we are done

    def _read_lines(self, proc):
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
                continue
            params = msg.get("params") or {}
            tid = (params.get("threadId") or params.get("thread_id")
                   or (params.get("thread") or {}).get("id"))
            agent = self._threads.get(tid)
            if agent:
                agent._on_event(msg.get("method", ""), params)

    def _read_err(self, proc):
        try:
            for line in proc.stderr:
                self._stderr.append(line.rstrip())
                del self._stderr[:-40]
        except (ValueError, OSError):
            pass

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
        from .codex_app_agent import CodexAppAgent

        return CodexAppAgent(self, name, model, instructions)


from .codex_app_agent import CodexAppAgent  # compatibility export
