import json
import os
import threading
import time

from .codex_app import START_TIMEOUT, TURN_TIMEOUT


class CodexAppAgent:
    provider = "codex-cli"
    accepts_images = True

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
        self._compaction = None

    def _on_event(self, method, params):
        low = method.lower()
        if "delta" in low:
            piece = params.get("delta") or params.get("text") or ""
            if piece:
                self._chunks.append(piece)
                self.activity = "writing"
        elif "tokenusage" in low.replace("/", "").replace("_", ""):
            usage = params.get("tokenUsage") or {}
            total = usage.get("total") or usage
            self.tokens = (total.get("totalTokens") or total.get("total_tokens")
                           or self.tokens)
        elif "turn/started" in low or "turnstarted" in low:
            self.activity = "thinking"
        elif "item/started" in low:
            item = params.get("item") or {}
            item_type = str(item.get("type", "")).replace("_", "").lower()
            self.activity = ("compacting" if item_type == "contextcompaction"
                             else "working")
        elif "item/completed" in low:
            item = params.get("item") or {}
            item_type = str(item.get("type", "")).replace("_", "").lower()
            if item_type == "contextcompaction":
                self._compaction = {"trigger": item.get("trigger") or "auto"}
            if (item.get("type") in ("agentMessage", "agent_message")
                    and item.get("text") and not self._chunks):
                self._chunks.append(item["text"])
        elif "turn/failed" in low:
            self._error = json.dumps(params)[:400]
            self._done.set()
        elif "turn/completed" in low:
            self._done.set()

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
            raise RuntimeError(
                "thread/start returned no id: " + json.dumps(result)[:300])
        self.backend._threads[self.thread_id] = self

    def resume(self, thread_id, timeout=START_TIMEOUT):
        self.backend.start()
        reply = self.backend._request(
            "thread/resume",
            {"threadId": thread_id, "cwd": self.backend.cwd}, timeout)
        if "error" in reply:
            return False
        self.thread_id = thread_id
        self.backend._threads[thread_id] = self
        return True

    def ask(self, text, timeout=TURN_TIMEOUT, images=()):
        with self._lock:
            self.backend.start()
            started = time.time()
            self.activity = "starting"
            self._chunks, self._error, self._compaction = [], None, None
            self._done.clear()
            try:
                self._ensure_thread(timeout)
            except RuntimeError as exc:
                self.activity = ""
                return None, {"error": str(exc)}

            prompt = text
            if self.instructions and self.turns == 0:
                prompt = self.instructions + "\n\n---\n\n" + text
            items = [{"type": "localImage", "path": os.path.abspath(path)}
                     for path in images]
            items.append({"type": "text", "text": prompt})
            reply = self.backend._request("turn/start", {
                "threadId": self.thread_id,
                "clientUserMessageId": "%s-%d" % (self.name, self.turns + 1),
                "input": items}, timeout)
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
            meta = {"elapsed": round(time.time() - started, 1),
                    "tokens": self.tokens or None}
            if self._compaction is not None:
                meta["compacted"] = True
                meta["compaction"] = self._compaction
            return answer or "(empty answer)", meta

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
