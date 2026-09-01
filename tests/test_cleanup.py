"""Nothing is left behind: no process, no pipe, no thread.

A process opened by sinaxa has three pipes, and each one is a file
descriptor. A process gets a few hundred of those in total, so a stop() that
closes one pipe out of three is a machine that stops being able to open
files after a day of use -- and the error when it happens says "Too many
open files", which points nowhere near the cause.

These tests count. Open descriptors before, open descriptors after, and the
process table checked for anything of ours still standing.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from src.engines.claude_session import ClaudeSession                 # noqa: E402
from src.engines.claude_cli import ClaudeBackend                     # noqa: E402
from src.engines.codex_app import CodexAppBackend                    # noqa: E402
from test_agents import executable                                   # noqa: E402


def open_files():
    """How many file descriptors this process holds."""
    for folder in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(folder):
            return len(os.listdir(folder))
    raise unittest.SkipTest("no way to count file descriptors here")


def gone(pid):
    """True when nothing by that id is left in the process table.

    A zombie counts as not gone: it is a process that was never reaped, and
    it still holds an entry.
    """
    if pid is None:
        return True
    out = subprocess.run(["ps", "-o", "pid=,stat=", "-p", str(pid)],
                         capture_output=True, text=True).stdout.strip()
    return not out


class TheMeasureItself(unittest.TestCase):
    """A test that cannot fail proves nothing. Check the instruments."""

    def test_a_living_process_is_not_reported_as_gone(self):
        alive = subprocess.Popen([sys.executable, "-c", "import time;"
                                                       "time.sleep(30)"])
        self.addCleanup(alive.wait)
        self.addCleanup(alive.kill)
        self.assertFalse(gone(alive.pid))

    def test_an_unreaped_process_is_not_reported_as_gone(self):
        """A zombie holds a slot in the table just as a running one does."""
        dead = subprocess.Popen([sys.executable, "-c", ""])
        time.sleep(0.4)
        self.assertFalse(gone(dead.pid), "a zombie was counted as cleaned up")
        dead.wait()
        self.assertTrue(gone(dead.pid))

    def test_open_files_notices_a_file_being_opened(self):
        before = open_files()
        handle = open(__file__, encoding="utf-8")
        self.assertEqual(open_files(), before + 1)
        handle.close()
        self.assertEqual(open_files(), before)


class Leaks(unittest.TestCase):
    """Every fake binary here is a real process with real pipes."""

    def setUp(self):
        self.made = []
        self.addCleanup(self.tidy)

    def tidy(self):
        for folder in self.made:
            shutil.rmtree(folder, ignore_errors=True)

    def fake(self, name):
        binary, folder = executable(name)
        self.made.append(folder)
        return binary

    # ------------------------------------------------------------ claude
    def test_stopping_a_claude_session_closes_all_three_pipes(self):
        binary = self.fake("fake_claude.py")
        before = open_files()

        session = ClaudeSession(binary=binary)
        session.ask("hello")
        self.assertGreater(open_files(), before, "the test proves nothing "
                                                 "unless the pipes opened")
        pid = session.pid
        session.stop()
        time.sleep(0.3)

        self.assertEqual(open_files(), before,
                         "stop() left file descriptors open")
        self.assertTrue(gone(pid), "the process is still there")

    def test_a_hundred_starts_and_stops_do_not_pile_up(self):
        """The failure mode is slow: two descriptors per stop, unnoticed
        until the day nothing can be opened at all."""
        binary = self.fake("fake_claude.py")
        session = ClaudeSession(binary=binary)
        session.ask("warm up")
        session.stop()
        settled = open_files()

        for _ in range(10):
            session.reset()
            session.ask("again")
            session.stop()
        time.sleep(0.3)
        self.assertLessEqual(open_files(), settled,
                             "descriptors accumulated across restarts")

    def test_a_respawn_does_not_leave_the_old_process_behind(self):
        binary = self.fake("fake_claude.py")
        session = ClaudeSession(binary=binary)
        session.ask("hello")
        first = session.pid
        session.switch_to("11111111-2222-3333-4444-555555555555")
        session.ask("hello")
        second = session.pid
        self.assertNotEqual(first, second)
        self.assertTrue(gone(first), "the old process outlived the switch")
        session.stop()
        self.assertTrue(gone(second))

    def test_the_backend_takes_every_agent_down_with_it(self):
        binary = self.fake("fake_claude.py")
        before = open_files()
        backend = ClaudeBackend(binary=binary)
        agents = [backend.agent("one"), backend.agent("two"),
                  backend.agent("three")]
        for agent in agents:
            agent.ask("hello")
        pids = list(backend.pids)
        self.assertEqual(len(pids), 3, "one process per claude seat")

        backend.stop()
        time.sleep(0.3)
        for pid in pids:
            self.assertTrue(gone(pid), "a process survived the backend")
        self.assertEqual(open_files(), before)
        self.assertEqual(backend.pids, [])

    # ------------------------------------------------------------- codex
    def test_stopping_the_codex_server_closes_all_three_pipes(self):
        binary = self.fake("fake_codex.py")
        before = open_files()

        backend = CodexAppBackend(binary=binary)
        agent = backend.agent("codex")
        agent.ask("hello")
        pid = backend.pids[0]

        backend.stop()
        time.sleep(0.3)
        self.assertEqual(open_files(), before,
                         "stop() left file descriptors open")
        self.assertTrue(gone(pid))

    def test_stopping_twice_is_harmless(self):
        """stop() is called on the way out and again by atexit."""
        binary = self.fake("fake_codex.py")
        backend = CodexAppBackend(binary=binary)
        backend.agent("codex").ask("hello")
        backend.stop()
        backend.stop()
        self.assertFalse(backend.alive)

    def test_restarting_the_server_does_not_pile_up_descriptors(self):
        binary = self.fake("fake_codex.py")
        backend = CodexAppBackend(binary=binary)
        backend.agent("codex").ask("warm up")
        backend.stop()
        settled = open_files()

        for _ in range(5):
            backend.agent("codex").ask("again")
            backend.stop()
        time.sleep(0.3)
        self.assertLessEqual(open_files(), settled)


class AppShutdown(unittest.TestCase):
    """The whole thing, taken down from the top."""

    def test_stopping_the_app_leaves_no_process_and_no_pipe(self):
        from src.app import App

        root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        binary, folder = executable("fake_claude.py")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)

        before = open_files()
        app = App(root, cwd=root, binaries={"claude": binary})
        app.add_member(name="Marian", kind="human")
        member = app.add_member(name="Claude", engine="claude")
        definition = app.add_seat_def(role="architect", prompt="You design.",
                                      default_member=member.id)
        project = app.add_project("sinaxa")
        session = project.sessions[0]
        app.say(project.id, session.id, session.all_room.id, "hello")

        talk = app.talk(project, session)
        pids = talk.conversations[session.seats[0].id].agent.status()["pids"]
        self.assertTrue(pids, "no process was started")

        app.stop()
        time.sleep(0.3)
        for pid in pids:
            self.assertTrue(gone(pid), "an agent outlived the app")
        self.assertEqual(open_files(), before)

    def test_a_terminated_server_takes_its_agents_with_it(self):
        """`kill` sends SIGTERM, and python's default handler exits without
        running atexit. Without a handler of our own, every agent is
        orphaned -- which is exactly what the start script caught."""
        import json
        import socket
        import urllib.request

        root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        binary, folder = executable("fake_claude.py")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = subprocess.Popen(
            [sys.executable, "-m", "src.server", "--port", str(port),
             "--state", root, "--cwd", root],
            cwd=ROOT, env=dict(os.environ, FAKE_MODE="linger"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(server.wait)
        self.addCleanup(server.kill)

        base = "http://127.0.0.1:%d" % port
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/api/state", timeout=2).read()
                break
            except Exception:
                time.sleep(0.2)

        def call(path, body):
            request = urllib.request.Request(
                base + path, json.dumps(body).encode(),
                {"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(request, timeout=30).read())

        call("/api/members", {"name": "Marian", "kind": "human"})
        member = call("/api/members", {"name": "Claude", "engine": "claude",
                                       "binary": binary})["member"]
        call("/api/seatdefs", {"role": "architect", "prompt": "You design.",
                               "default_member": member["id"]})
        project = call("/api/projects", {"name": "sinaxa"})["project"]
        state = json.loads(urllib.request.urlopen(
            base + "/api/state?project=" + project["id"], timeout=10).read())
        room = next(r for r in state["rooms"] if r["kind"] == "all")
        call("/api/say", {"project": project["id"], "session": state["session"],
                          "room": room["id"], "text": "hello"})

        children = subprocess.run(
            ["ps", "-eo", "pid,ppid"], capture_output=True, text=True).stdout
        agents = [int(line.split()[0]) for line in children.splitlines()[1:]
                  if line.split() and line.split()[1] == str(server.pid)]
        self.assertTrue(agents, "the server started no agent to speak of")

        server.terminate()
        server.wait(timeout=15)
        time.sleep(0.5)
        for pid in agents:
            self.assertTrue(gone(pid),
                            "an agent outlived a terminated server")

    def test_stopping_the_app_twice_is_harmless(self):
        from src.app import App

        root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        app = App(root, cwd=root)
        app.stop()
        app.stop()


if __name__ == "__main__":
    unittest.main()
