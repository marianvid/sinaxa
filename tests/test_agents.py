"""What each adapter must do with its provider.

These run the real adapters against fake binaries in tests/fakes/ -- real
subprocesses, real pipes, real framing, no network and no subscription. What
is checked is the plumbing we actually got wrong: which flags are passed,
whether the process is reused between turns, where the answer text is read
from, and where in the reply the ids and the token counts sit.
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from claude_session import ClaudeSession, SessionDied, TurnTimedOut   # noqa: E402
from codex_app import CodexAppBackend                                 # noqa: E402
from opencode_http import OpencodeBackend, model_ref                  # noqa: E402

FAKES = os.path.join(ROOT, "tests", "fakes")


def executable(name):
    """A fake binary, made runnable in a scratch copy so the repo stays clean."""
    src = os.path.join(FAKES, name)
    tmp = tempfile.mkdtemp(prefix="sinaxa-fake-")
    dst = os.path.join(tmp, name.replace("fake_", "").replace(".py", ""))
    shutil.copy(src, dst)
    os.chmod(dst, 0o755)
    return dst, tmp


class FakeBinary(unittest.TestCase):
    """Copies the fake next to a log file and cleans up after itself."""

    fake = None

    def setUp(self):
        self.binary, self._tmp = executable(self.fake)
        self.log = os.path.join(self._tmp, "argv.log")
        os.environ["FAKE_LOG"] = self.log
        os.environ.pop("FAKE_MODE", None)
        os.environ.pop("FAKE_WARMUP", None)

    def tearDown(self):
        os.environ.pop("FAKE_LOG", None)
        os.environ.pop("FAKE_MODE", None)
        os.environ.pop("FAKE_WARMUP", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def logged(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def spawns(self):
        return [entry for entry in self.logged() if isinstance(entry, list)]

    def rpcs(self):
        return [entry["rpc"] for entry in self.logged()
                if isinstance(entry, dict) and "rpc" in entry]


# --------------------------------------------------------------- claude

class Claude(FakeBinary):
    fake = "fake_claude.py"

    def session(self, **kw):
        s = ClaudeSession(binary=self.binary, **kw)
        self.addCleanup(s.stop)
        return s

    def test_the_first_spawn_mints_a_session_id_rather_than_resuming(self):
        s = self.session()
        s.ask("hello")
        argv = self.spawns()[0]
        self.assertIn("--session-id", argv)
        self.assertNotIn("--resume", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], s.session_id)

    def test_the_member_definition_reaches_the_command_line(self):
        s = self.session(model="haiku", instructions="you are the reviewer",
                         allowed_tools=["Read", "Grep"])
        s.ask("hello")
        argv = self.spawns()[0]
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1],
                         "you are the reviewer")
        cut = argv.index("--allowedTools")
        self.assertEqual(argv[cut + 1:cut + 3], ["Read", "Grep"])

    def test_the_answer_and_its_meta_come_from_the_result_event(self):
        answer, meta = self.session().ask("hello")
        self.assertIn("you said 'hello'", answer)
        self.assertEqual(meta["elapsed"], 1.2)
        self.assertEqual(meta["cost"], 0.0102)
        self.assertNotIn("error", meta)

    def test_tokens_add_input_output_and_cache_reads(self):
        s = self.session()
        s.ask("hello")
        self.assertEqual(s.tokens, 115)

    def test_one_process_serves_every_turn_and_keeps_the_context(self):
        s = self.session()
        s.ask("first")
        pid = s.pid
        answer, _ = s.ask("second")
        self.assertEqual(s.pid, pid, "the process was respawned between turns")
        self.assertIn("turn 2", answer)
        self.assertIn("first was 'first'", answer)
        self.assertEqual(len(self.spawns()), 1)
        self.assertEqual(s.turns, 2)

    def test_a_dead_process_is_respawned_and_resumed_not_started_fresh(self):
        s = self.session()
        s.ask("first")
        first_id = s.session_id
        s._proc.kill()
        s._proc.wait(timeout=5)
        s.ask("second")
        argv = self.spawns()[1]
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], first_id)

    def test_switching_session_resumes_the_other_one_in_a_new_process(self):
        s = self.session()
        s.ask("first")
        s.switch_to("11111111-2222-3333-4444-555555555555")
        turns_after_switch = s.turns
        s.ask("hello")                      # makes sure the new process ran
        argv = self.spawns()[1]
        self.assertEqual(argv[argv.index("--resume") + 1],
                         "11111111-2222-3333-4444-555555555555")
        self.assertEqual(turns_after_switch, 0,
                         "the turn count belongs to the session, not the member")

    def test_reset_forgets_the_session_so_the_next_start_is_a_new_one(self):
        s = self.session()
        s.ask("first")
        old = s.session_id
        s.reset()
        self.assertIsNone(s.session_id)
        s.ask("again")
        self.assertNotEqual(s.session_id, old)
        self.assertIn("--session-id", self.spawns()[1])

    def test_a_binary_that_refuses_to_start_is_reported_not_hung(self):
        os.environ["FAKE_MODE"] = "die"
        with self.assertRaises(SessionDied):
            self.session().ask("hello")

    def test_a_process_that_never_answers_times_out(self):
        os.environ["FAKE_MODE"] = "silent"
        with self.assertRaises(TurnTimedOut):
            self.session().ask("hello", timeout=2)

    def test_a_turn_that_ends_without_a_result_event_is_a_timeout_not_an_answer(self):
        os.environ["FAKE_MODE"] = "noresult"
        with self.assertRaises(TurnTimedOut):
            self.session().ask("hello", timeout=2)


# ---------------------------------------------------------------- codex

class Codex(FakeBinary):
    fake = "fake_codex.py"

    def backend(self):
        b = CodexAppBackend(binary=self.binary)
        self.addCleanup(b.stop)
        return b

    def test_the_handshake_happens_once_and_in_order(self):
        b = self.backend()
        one, two = b.agent("claude"), b.agent("codex")
        one.ask("hello")
        two.ask("hello")
        self.assertEqual(self.rpcs()[:2], ["initialize", "initialized"])
        self.assertEqual(self.rpcs().count("initialize"), 1)
        self.assertEqual(len(self.spawns()), 1, "one process for both agents")

    def test_the_thread_id_is_read_from_the_nested_reply(self):
        a = self.backend().agent("codex")
        a.ask("hello")
        self.assertEqual(a.thread_id, "th-1")

    def test_the_token_total_is_read_one_level_down_under_total(self):
        """Regression: we used to read tokenUsage.totalTokens and got nothing."""
        a = self.backend().agent("codex")
        _, meta = a.ask("hello")
        self.assertEqual(a.tokens, 1000)
        self.assertEqual(meta["tokens"], 1000)
        _, meta = a.ask("again")
        self.assertEqual(meta["tokens"], 2000)

    def test_the_answer_is_assembled_from_the_deltas(self):
        a = self.backend().agent("codex")
        answer, _ = a.ask("hello")
        self.assertIn("turn 1 on th-1", answer)
        self.assertNotIn("IGNORED", answer,
                         "item/completed must not be appended after deltas")

    def test_a_provider_that_sends_no_deltas_still_yields_an_answer(self):
        a = self.backend().agent("codex")
        answer, _ = a.ask("NODELTA please")
        self.assertIn("turn 1 on th-1", answer)

    def test_two_agents_get_separate_threads_in_the_same_process(self):
        b = self.backend()
        one, two = b.agent("one"), b.agent("two")
        first, _ = one.ask("hello")
        second, _ = two.ask("hello")
        self.assertNotEqual(one.thread_id, two.thread_id)
        self.assertIn(one.thread_id, first)
        self.assertIn(two.thread_id, second)
        self.assertEqual(one.status()["pids"], two.status()["pids"])

    def test_each_agent_keeps_its_own_context(self):
        b = self.backend()
        one, two = b.agent("one"), b.agent("two")
        one.ask("a")
        one.ask("b")
        answer, _ = two.ask("c")
        self.assertIn("turn 1", answer, "the second agent inherited a turn count")
        self.assertEqual(one.turns, 2)
        self.assertEqual(two.turns, 1)

    def test_the_system_prompt_is_sent_once_not_on_every_turn(self):
        a = self.backend().agent("codex", instructions="ROLE-REVIEWER")
        first, _ = a.ask("hello")
        second, _ = a.ask("hello")
        self.assertIn("ROLE-REVIEWER", first)
        self.assertNotIn("ROLE-REVIEWER", second)

    def test_a_failed_turn_is_reported_as_an_error_not_as_an_answer(self):
        a = self.backend().agent("codex")
        answer, meta = a.ask("FAIL now")
        self.assertIsNone(answer)
        self.assertIn("nope", meta["error"])

    def test_a_turn_that_never_completes_times_out_with_a_readable_reason(self):
        a = self.backend().agent("codex")
        answer, meta = a.ask("SLOW down", timeout=2)
        self.assertIsNone(answer)
        self.assertIn("turn/completed", meta["error"])

    def test_a_known_thread_can_be_resumed_and_an_unknown_one_cannot(self):
        b = self.backend()
        self.assertTrue(b.agent("codex").resume("th-7"))
        self.assertFalse(b.agent("codex").resume("nonsense"))

    def test_status_reports_what_the_ui_puts_in_the_bar(self):
        a = self.backend().agent("codex", model="gpt-5")
        a.ask("hello")
        status = a.status()
        self.assertEqual(status["provider"], "codex-cli")
        self.assertEqual(status["model"], "gpt-5")
        self.assertEqual(status["turns"], 1)
        self.assertEqual(status["tokens"], 1000)
        self.assertTrue(status["alive"])
        self.assertTrue(status["shared_process"])
        self.assertEqual(status["activity"], "", "no work should be in flight")

    def test_stopping_the_backend_leaves_no_process_behind(self):
        b = self.backend()
        a = b.agent("codex")
        a.ask("hello")
        pid = b.pids[0]
        b.stop()
        time.sleep(0.5)
        self.assertFalse(b.alive)
        with self.assertRaises(OSError):
            os.kill(pid, 0)


# ------------------------------------------------------------- opencode

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Opencode(FakeBinary):
    fake = "fake_opencode.py"

    def backend(self, **kw):
        b = OpencodeBackend(port=free_port(), binary=self.binary, poll=0.05, **kw)
        self.addCleanup(b.stop)
        return b

    def test_a_model_is_written_provider_slash_id(self):
        self.assertEqual(model_ref("ai-lab/llama-gemma-26b"),
                         {"providerID": "ai-lab", "id": "llama-gemma-26b"})
        self.assertIsNone(model_ref(None))
        with self.assertRaises(ValueError):
            model_ref("llama-gemma-26b")

    def test_the_server_is_started_with_the_port_we_asked_for(self):
        b = self.backend()
        b.start()
        argv = self.spawns()[0]
        self.assertEqual(argv[0], "serve")
        self.assertEqual(argv[argv.index("--port") + 1], str(b.port))
        self.assertTrue(b.ours, "we started this one, so we own it")

    def test_readiness_waits_for_the_providers_not_for_the_port(self):
        """The window in which a real turn dies with nothing in the transcript."""
        os.environ["FAKE_WARMUP"] = "1.5"
        b = self.backend()
        started = time.time()
        b.start()
        self.assertGreaterEqual(time.time() - started, 1.5)
        self.assertTrue(b.ready())

    def test_a_server_already_running_is_used_rather_than_duplicated(self):
        first = self.backend()
        first.start()
        second = OpencodeBackend(port=first.port, binary=self.binary, poll=0.05)
        self.addCleanup(second.stop)
        second.start()
        self.assertEqual(len(self.spawns()), 1, "a second server was spawned")
        self.assertFalse(second.ours)
        self.assertEqual(second.pids, [])

    def test_stopping_leaves_a_server_we_did_not_start_alone(self):
        first = self.backend()
        first.start()
        second = OpencodeBackend(port=first.port, binary=self.binary, poll=0.05)
        second.start()
        second.stop()
        self.assertTrue(first.ready(), "it killed a server it did not own")

    def test_the_declared_models_are_the_ones_the_config_lists(self):
        b = self.backend()
        b.start()
        self.assertIn(("ai-lab", "llama-qwen36-35b"), b.models())
        self.assertIn(("mac", "llama-glm-air"), b.models())

    def test_the_answer_is_the_reply_not_the_question_we_just_asked(self):
        """The transcript is newest first; reading [-1] gives back the prompt."""
        a = self.backend().agent("opencode")
        answer, meta = a.ask("hello")
        self.assertIn("turn 1: hello", answer)
        self.assertNotEqual(answer, "hello")
        self.assertNotIn("thinking", answer, "reasoning is not the answer")
        self.assertNotIn("error", meta)

    def test_tokens_add_up_across_turns(self):
        a = self.backend().agent("opencode")
        _, meta = a.ask("hello")
        self.assertEqual(meta["tokens"], 115)
        _, meta = a.ask("again")
        self.assertEqual(meta["tokens"], 230)
        self.assertEqual(a.turns, 2)

    def test_one_session_holds_the_context_across_turns(self):
        a = self.backend().agent("opencode")
        a.ask("first")
        session = a.session_id
        answer, _ = a.ask("second")
        self.assertEqual(a.session_id, session, "a new session per turn loses it")
        self.assertIn("turn 2", answer)

    def test_the_system_prompt_is_sent_once_not_on_every_turn(self):
        a = self.backend().agent("opencode", instructions="ROLE-REVIEWER")
        first, _ = a.ask("hello")
        second, _ = a.ask("hello")
        self.assertIn("ROLE-REVIEWER", first)
        self.assertNotIn("ROLE-REVIEWER", second)

    def test_the_model_reaches_the_session_it_creates(self):
        b = self.backend()
        a = b.agent("opencode", model="ai-lab/llama-gemma-26b")
        a.ask("hello")
        newest = a.messages()[0]
        self.assertEqual(newest["model"],
                         {"providerID": "ai-lab", "id": "llama-gemma-26b"})

    def test_two_agents_get_separate_sessions_in_the_same_server(self):
        b = self.backend()
        one, two = b.agent("one"), b.agent("two")
        one.ask("a")
        one.ask("b")
        answer, _ = two.ask("c")
        self.assertNotEqual(one.session_id, two.session_id)
        self.assertIn("turn 1", answer, "the second agent inherited a history")
        self.assertEqual(one.status()["pids"], two.status()["pids"])

    def test_a_turn_that_never_finishes_says_to_check_the_model(self):
        """opencode fails silently on an undeclared model; say so out loud."""
        a = self.backend().agent("opencode", model="ai-lab/llama-gemma-26b")
        answer, meta = a.ask("SLOW down", timeout=1)
        self.assertIsNone(answer)
        self.assertIn("not declared in its config", meta["error"])
        self.assertIn("ai-lab/llama-gemma-26b", meta["error"])

    def test_a_reply_without_finish_is_not_taken_for_an_answer(self):
        a = self.backend().agent("opencode")
        answer, meta = a.ask("FAIL please", timeout=1)
        self.assertIsNone(answer)
        self.assertIn("no answer", meta["error"])

    def test_compact_clears_the_providers_context(self):
        a = self.backend().agent("opencode")
        a.ask("hello")
        self.assertTrue(a.compact())
        self.assertEqual(a.messages(), [])

    def test_a_session_can_be_adopted_and_a_bogus_one_cannot(self):
        b = self.backend()
        a = b.agent("opencode")
        a.ask("hello")
        left_behind = a.session_id

        other = b.agent("later")
        self.assertTrue(other.resume(left_behind))
        self.assertFalse(other.resume("ses_nonsense"))
        self.assertIsNone(other.session_id)

    def test_status_reports_what_the_ui_puts_in_the_bar(self):
        b = self.backend()
        a = b.agent("opencode", model="ai-lab/llama-gemma-26b")
        a.ask("hello")
        status = a.status()
        self.assertEqual(status["provider"], "opencode")
        self.assertEqual(status["model"], "ai-lab/llama-gemma-26b")
        self.assertEqual(status["turns"], 1)
        self.assertEqual(status["tokens"], 115)
        self.assertEqual(status["activity"], "")
        self.assertTrue(status["alive"])
        self.assertTrue(status["shared_process"])

    def test_a_server_that_will_not_start_is_reported_not_hung(self):
        b = OpencodeBackend(port=free_port(), binary="/nonexistent/opencode")
        with self.assertRaises(OSError):
            b.start()


if __name__ == "__main__":
    unittest.main()
