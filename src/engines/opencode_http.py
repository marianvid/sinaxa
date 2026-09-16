"""A seat filled by opencode.

`opencode serve` is an ordinary HTTP server -- OpenAPI at /doc, SSE at
/event -- so this adapter is a client, not a process manager. One server
holds many sessions, and a session survives the server being restarted,
which is more than either codex transport gives us.

    POST /api/session                 -> {"id": "ses_..."}
    POST /api/session/{id}/prompt     -> admitted at once, the turn runs on
    GET  /api/session/{id}/message    -> the transcript, NEWEST FIRST
    POST /api/session/{id}/compact    -> the context-clear primitive

Measured behaviour, and the traps, are written up in
docs/design/03-providers.md. Two of them shape the code below:

  * a model must be declared in the config, not merely served by the
    provider -- otherwise the turn dies silently, with no assistant message
    and nothing in the transcript to say why;
  * for a few seconds after the port opens the providers are not resolved
    yet, and a prompt sent in that window dies the same way. So readiness
    is "the providers answer", never "the port accepts".
"""

import json
import os
import subprocess
import threading
import time
import urllib.request

START_TIMEOUT = 90
TURN_TIMEOUT = 600
POLL = 1.0


class OpencodeBackend:
    label = "opencode serve"
    can_resume = True

    def __init__(self, port=4096, host="127.0.0.1", cwd=None, binary="opencode",
                 poll=POLL):
        self.host = host
        self.port = port
        self.base = "http://%s:%d" % (host, port)
        self.cwd = cwd or os.getcwd()
        self.binary = binary
        self.poll = poll
        self._proc = None          # None when we attached to somebody else's
        self._reader = None
        self._stderr = []
        self._lock = threading.Lock()

    # ---------------------------------------------------------- lifecycle
    @property
    def alive(self):
        if self._proc is not None and self._proc.poll() is not None:
            return False
        return self.ready()

    @property
    def pids(self):
        return [self._proc.pid] if self._proc and self._proc.poll() is None else []

    @property
    def ours(self):
        """False when we attached to a server the user was already running."""
        return self._proc is not None

    def ready(self):
        """The port is not the signal -- a resolved provider list is."""
        try:
            answer = self.call("/config/providers", timeout=5)
        except Exception:
            return False
        providers = answer.get("data") or answer.get("providers") or []
        return bool(providers)

    def start(self, timeout=START_TIMEOUT):
        with self._lock:
            if self.ready():
                return self
            if self._proc is None or self._proc.poll() is not None:
                self._proc = subprocess.Popen(
                    [self.binary, "serve", "--port", str(self.port),
                     "--hostname", self.host],
                    cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1)
                self._reader = threading.Thread(
                    target=self._read_err, args=(self._proc,), daemon=True)
                self._reader.start()
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._proc.poll() is not None:
                    raise RuntimeError("opencode serve exited. " + self.stderr_tail())
                if self.ready():
                    return self
                time.sleep(0.2)
            raise TimeoutError("opencode serve did not become ready in %ds. %s"
                               % (timeout, self.stderr_tail()))

    def stop(self):
        """Only ever kills a server we started ourselves -- and when it does,
        it takes the pipes and the reader with it."""
        proc, self._proc = self._proc, None
        reader, self._reader = self._reader, None
        if proc is None:
            return

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

        if reader:
            reader.join(timeout=2)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def _read_err(self, proc):
        try:
            for line in proc.stderr:
                self._stderr.append(line.rstrip())
                del self._stderr[:-40]
        except (ValueError, OSError):
            pass

    def stderr_tail(self, n=4):
        return " | ".join(self._stderr[-n:])

    # ------------------------------------------------------------ plumbing
    def call(self, path, payload=None, timeout=60):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data,
                                         {"Content-Type": "application/json"})
        body = urllib.request.urlopen(request, timeout=timeout).read()
        return json.loads(body) if body.strip() else None

    def models(self):
        """(providerID, modelID) pairs the config actually declares."""
        answer = self.call("/config/providers")
        found = []
        for provider in (answer.get("data") or answer.get("providers") or []):
            for model in (provider.get("models") or {}):
                found.append((provider.get("id"), model))
        return found

    def agent(self, name, model=None, instructions=None):
        from .opencode_agent import OpencodeAgent

        return OpencodeAgent(self, name, model, instructions)


from .opencode_agent import (OpencodeAgent, data_uri, model_ref)  # compatibility
