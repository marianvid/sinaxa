"""A long-lived `claude` process.

One process stays alive across messages, fed on stdin as stream-json.
The context lives in the process, so only the new turn is billed —
no --resume on every message.

--resume is still used, but only where it belongs:
  * switching to another session (switch_to)
  * recovering after the process died (respawn)

The CLI session id is a cache. The room's transcript on disk is the
source of truth; if the id is gone we mint a new one and lose nothing
but the model's warm context.
"""

import json
import os
import queue
import subprocess
import threading
import time
import uuid

DEFAULT_TIMEOUT = 300


def close(stream):
    """Shut a pipe and never make a fuss about it."""
    try:
        if stream is not None:
            stream.close()
    except Exception:
        pass


class SessionDied(RuntimeError):
    pass


class TurnTimedOut(RuntimeError):
    pass


class ClaudeSession:
    def __init__(self, session_id=None, cwd=None, binary="claude",
                 model=None, instructions=None, allowed_tools=None,
                 effort=None):
        self.session_id = session_id
        self.cwd = cwd or os.getcwd()
        self.binary = binary
        self.model = model
        self.instructions = instructions
        self.allowed_tools = allowed_tools
        self.effort = effort
        self.activity = ""
        self.tokens = 0
        self._proc = None
        self._events = queue.Queue()
        self._stderr = []
        self._readers = []
        self._lock = threading.Lock()
        self.started_at = None
        self.turns = 0

    # ------------------------------------------------------------ lifecycle
    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self):
        return self._proc.pid if self.alive else None

    def start(self, resume=False):
        """Spawn the process. resume=True continues self.session_id."""
        self.stop()
        if resume and not self.session_id:
            resume = False
        if not resume and not self.session_id:
            self.session_id = str(uuid.uuid4())

        cmd = [self.binary, "-p",
               "--input-format", "stream-json",
               "--output-format", "stream-json",
               "--verbose"]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        if self.instructions:
            cmd += ["--append-system-prompt", self.instructions]
        if self.allowed_tools is not None:
            cmd += ["--allowedTools", *self.allowed_tools]
        cmd += ["--resume", self.session_id] if resume else ["--session-id", self.session_id]

        self._events = queue.Queue()
        self._stderr = []
        self._proc = subprocess.Popen(
            cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self.started_at = time.time()
        self._readers = [
            threading.Thread(target=self._read_stdout, args=(self._proc,),
                             daemon=True),
            threading.Thread(target=self._read_stderr, args=(self._proc,),
                             daemon=True)]
        for reader in self._readers:
            reader.start()
        return self

    def stop(self):
        """Leave nothing behind: no process, no pipe, no reader thread.

        A process has three pipes and only one of them is stdin. Closing
        stdin alone leaves two file descriptors attached to a process that
        no longer exists, and a few hundred of those is a machine that
        cannot open a file any more. So: close stdin to say goodbye, wait
        for it to go, let the reader threads run out, then close what they
        were reading.
        """
        proc, self._proc = self._proc, None
        readers, self._readers = self._readers, []
        if proc is None:
            return

        close(proc.stdin)
        if proc.poll() is None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        else:
            proc.wait()                       # reap it, do not leave a zombie

        for reader in readers:
            reader.join(timeout=2)
        close(proc.stdout)
        close(proc.stderr)

    def switch_to(self, session_id):
        """Point at another session and resume it in a fresh process."""
        self.stop()
        self.session_id = session_id
        self.turns = 0
        return self.start(resume=bool(session_id))

    def reset(self):
        """Forget the session entirely; the next start is a new one."""
        self.stop()
        self.session_id = None
        self.turns = 0

    # ------------------------------------------------------------ plumbing
    def _read_stdout(self, proc):
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._events.put(json.loads(line))
                except json.JSONDecodeError:
                    self._events.put({"type": "raw", "text": line})
        except (ValueError, OSError):
            pass                      # the pipe was closed under us: we are done
        self._events.put({"type": "_eof"})

    def _read_stderr(self, proc):
        try:
            for line in proc.stderr:
                self._stderr.append(line.rstrip())
                del self._stderr[:-40]
        except (ValueError, OSError):
            pass

    def stderr_tail(self, n=8):
        return "\n".join(self._stderr[-n:])

    # ------------------------------------------------------------ one turn
    def ask(self, text, timeout=DEFAULT_TIMEOUT):
        """Send one message, wait for the result event. Returns (text, meta)."""
        with self._lock:
            if not self.alive:
                self.start(resume=bool(self.session_id) and self.turns > 0)

            while not self._events.empty():           # drop anything stale
                self._events.get_nowait()

            envelope = {"type": "user", "message": {
                "role": "user", "content": [{"type": "text", "text": text}]}}
            try:
                self._proc.stdin.write(json.dumps(envelope) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError, AttributeError):
                raise SessionDied("the claude process closed its input. "
                                  + (self.stderr_tail() or ""))

            return self._await_result(timeout)

    def _await_result(self, timeout):
        deadline = time.time() + timeout
        chunks = []
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise TurnTimedOut("no answer in %ds" % timeout)
            try:
                event = self._events.get(timeout=min(left, 1.0))
            except queue.Empty:
                if not self.alive:
                    raise SessionDied("the claude process exited. "
                                      + (self.stderr_tail() or ""))
                continue

            kind = event.get("type")
            if kind == "_eof":
                raise SessionDied("the claude process exited. "
                                  + (self.stderr_tail() or ""))
            if kind == "system" and event.get("session_id"):
                self.session_id = event["session_id"]
            if kind == "system":
                self.activity = "thinking"
            if kind == "assistant":
                self.activity = "writing" 
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        chunks.append(block["text"])
            if kind == "result":
                usage = event.get("usage") or {}
                total = (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                         + usage.get("cache_read_input_tokens", 0))
                if total:
                    self.tokens = total
                self.activity = ""
                if event.get("session_id"):
                    self.session_id = event["session_id"]
                self.turns += 1
                answer = event.get("result") or "\n".join(chunks) or "(empty answer)"
                meta = {"elapsed": round(event.get("duration_ms", 0) / 1000.0, 1)}
                if event.get("total_cost_usd") is not None:
                    meta["cost"] = round(float(event["total_cost_usd"]), 4)
                if event.get("is_error"):
                    meta["error"] = "claude reported an error"
                return answer, meta
