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
import urllib.error
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
                threading.Thread(target=self._read_err, daemon=True).start()
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
        """Only ever kills a server we started ourselves."""
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def _read_err(self):
        proc = self._proc
        if proc is None:
            return
        for line in proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-40]

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
        return OpencodeAgent(self, name, model, instructions)


def model_ref(model):
    """"ai-lab/llama-qwen36-35b" -> {"providerID": ..., "id": ...}"""
    if not model:
        return None
    if isinstance(model, dict):
        return model
    provider, _, ident = model.partition("/")
    if not ident:
        raise ValueError("a model must be written provider/id, got %r" % model)
    return {"providerID": provider, "id": ident}


class OpencodeAgent:
    provider = "opencode"

    def __init__(self, backend, name, model=None, instructions=None):
        self.backend = backend
        self.name = name
        self.model = model
        self.instructions = instructions
        self.session_id = None
        self.activity = ""
        self.tokens = 0
        self.turns = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------ helpers
    def messages(self):
        answer = self.backend.call("/api/session/%s/message" % self.session_id)
        return answer.get("data") if isinstance(answer, dict) else (answer or [])

    @staticmethod
    def text_of(message):
        """Assistant text lives in content[]; the user's is a bare field."""
        parts = [block.get("text", "") for block in message.get("content", [])
                 if block.get("type") == "text"]
        return " ".join(p for p in parts if p).strip() or message.get("text", "")

    @staticmethod
    def total_tokens(message):
        counts = message.get("tokens") or {}
        cache = counts.get("cache") or {}
        return (counts.get("input", 0) + counts.get("output", 0)
                + counts.get("reasoning", 0) + cache.get("read", 0)
                + cache.get("write", 0))

    def _ensure_session(self):
        if self.session_id:
            return
        payload = {}
        reference = model_ref(self.model)
        if reference:
            payload["model"] = reference
        created = self.backend.call("/api/session", payload)
        created = created.get("data") or created
        self.session_id = created["id"]

    def resume(self, session_id):
        """Adopt a session left behind by an earlier run, or by a restart."""
        self.backend.start()
        self.session_id = session_id
        try:
            self.messages()
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
            self.session_id = None
            return False
        return True

    def compact(self):
        """opencode's own context-clear. The room's transcript is untouched."""
        if not self.session_id:
            return False
        self.backend.call("/api/session/%s/compact" % self.session_id, {})
        return True

    # ---------------------------------------------------------- one turn
    def ask(self, text, timeout=TURN_TIMEOUT):
        with self._lock:
            started = time.time()
            self.activity = "starting"
            try:
                self.backend.start()
                self._ensure_session()
            except Exception as exc:
                self.activity = ""
                return None, {"error": str(exc)[:400]}

            prompt = text
            if self.instructions and self.turns == 0:
                prompt = self.instructions + "\n\n---\n\n" + text

            before = len(self.messages())
            try:
                self.backend.call("/api/session/%s/prompt" % self.session_id,
                                  {"prompt": {"text": prompt}}, timeout=60)
            except urllib.error.HTTPError as exc:
                self.activity = ""
                return None, {"error": "prompt refused: %s" % exc}

            self.activity = "thinking"
            answer = self._await_answer(before, timeout)
            self.activity = ""
            if answer is None:
                return None, {"error": (
                    "no answer in %ds. opencode fails a turn silently when the "
                    "model is not declared in its config -- check %s"
                    % (timeout, self.model or "the default model"))}

            self.turns += 1
            self.tokens += self.total_tokens(answer)
            return self.text_of(answer) or "(empty answer)", {
                "elapsed": round(time.time() - started, 1),
                "tokens": self.tokens or None}

    def _await_answer(self, before, timeout):
        """A turn is over when the newest message is a finished assistant one."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(self.backend.poll)
            seen = self.messages()
            if len(seen) > before and seen[0].get("type") == "assistant" \
                    and seen[0].get("finish"):
                return seen[0]
        return None

    # ------------------------------------------------------------ status
    def status(self):
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.session_id or "")[:12],
                "activity": self.activity, "turns": self.turns,
                "tokens": self.tokens, "alive": self.backend.alive,
                "pids": self.backend.pids, "shared_process": True}

    def stop(self):
        """The session stays on disk; only our handle on it goes."""
        self.session_id = None
