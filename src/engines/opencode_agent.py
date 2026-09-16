import base64
import os
import threading
import time
import urllib.error

from .opencode_http import TURN_TIMEOUT

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp"}


def data_uri(path):
    with open(path, "rb") as stream:
        blob = stream.read()
    kind = MEDIA.get(os.path.splitext(path)[1].lower(), "image/png")
    return {"uri": "data:%s;base64,%s" %
                   (kind, base64.b64encode(blob).decode()),
            "name": os.path.basename(path)}


def model_ref(model):
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
    accepts_images = True

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

    def messages(self):
        answer = self.backend.call("/api/session/%s/message" % self.session_id)
        return answer.get("data") if isinstance(answer, dict) else (answer or [])

    @staticmethod
    def text_of(message):
        parts = [block.get("text", "") for block in message.get("content", [])
                 if block.get("type") == "text"]
        return " ".join(part for part in parts if part).strip() or message.get(
            "text", "")

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
        self.backend.start()
        self.session_id = session_id
        try:
            self.messages()
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
            self.session_id = None
            return False
        return True

    def compact(self):
        if not self.session_id:
            return False
        self.backend.call("/api/session/%s/compact" % self.session_id, {})
        return True

    def ask(self, text, timeout=TURN_TIMEOUT, images=()):
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
            payload = {"text": prompt}
            if images:
                payload["files"] = [data_uri(path) for path in images]
            try:
                self.backend.call("/api/session/%s/prompt" % self.session_id,
                                  {"prompt": payload}, timeout=60)
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
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(self.backend.poll)
            seen = self.messages()
            if (len(seen) > before and seen[0].get("type") == "assistant"
                    and seen[0].get("finish")):
                return seen[0]
        return None

    def status(self):
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.session_id or "")[:12],
                "activity": self.activity, "turns": self.turns,
                "tokens": self.tokens, "alive": self.backend.alive,
                "pids": self.backend.pids, "shared_process": True}

    def stop(self):
        self.session_id = None
