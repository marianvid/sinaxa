import json
import threading
import time

from .codex_mcp import TURN_TIMEOUT


def _text_of(result):
    if not isinstance(result, dict):
        return str(result)[:2000]
    out = [block.get("text", "") for block in (result.get("content") or [])
           if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(out).strip()


def _find_id(blob):
    for key in ("conversationId", "conversation_id", "threadId", "sessionId"):
        index = blob.find('"%s"' % key)
        if index < 0:
            continue
        value = (blob[index:].split(":", 1)[1].lstrip().lstrip('\\"')
                 .split('"')[0].split("\\")[0])
        if value and value != "null":
            return value
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
        self._compaction = None

    def _on_event(self, event):
        kind = event.get("type") or ""
        if "compact" in kind.replace("_", "").lower():
            self._compaction = {"trigger": event.get("trigger") or "auto"}
        if kind == "task_started":
            self.activity = "thinking"
        elif kind == "item_started":
            self.activity = "working"
        elif kind == "token_count":
            usage = event.get("info") or event.get("usage") or {}
            total = usage.get("total_token_usage") or usage
            if isinstance(total, dict) and total.get("total_tokens"):
                self.tokens = total["total_tokens"]
            self.activity = "working"
        elif kind == "task_complete":
            self.activity = ""

    def ask(self, text, timeout=TURN_TIMEOUT):
        with self._lock:
            self._compaction = None
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
                self.conversation_id = _find_id(
                    json.dumps(reply.get("result") or {}))
                if self.conversation_id:
                    self.backend._listeners[
                        self.conversation_id] = self._on_event
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
            meta = {"elapsed": round(time.time() - started, 1),
                    "tokens": self.tokens or None}
            if self._compaction is not None:
                meta["compacted"] = True
                meta["compaction"] = self._compaction
            return answer or "(empty answer)", meta

    def status(self):
        return {"provider": self.provider, "model": self.model or "default",
                "conversation": (self.conversation_id or "")[:8],
                "activity": self.activity, "turns": self.turns,
                "tokens": self.tokens, "alive": self.backend.alive,
                "pids": self.backend.pids, "shared_process": True}

    def stop(self):
        self.conversation_id = None
