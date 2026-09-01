"""An image pasted into a room.

Three engines take an image three different ways, and only one of them takes
it inline; the shapes are checked against the fake binaries, and against the
real protocols in tools/probe_images.py. Above the adapters the rules are the
ones we settled on: an image is stored beside the transcript, it is sent
again when a seat is caught up, a seat that cannot read one is not given it,
and nothing is resized on the way.
"""

import base64
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fakes.fake_engines import FakeEngines            # noqa: E402
from src.app import App                               # noqa: E402
from src.server import decode_images                  # noqa: E402
from src.model import ModelError                      # noqa: E402


def png(colour=(255, 215, 0), size=8):
    """A real PNG, small enough to hold in a test and valid enough to open."""
    raw = bytearray()
    for _ in range(size):
        raw.append(0)
        raw += bytes(colour) * size

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


class Room(unittest.TestCase):
    blind = ()

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.engines = FakeEngines(blind=self.blind)
        self.app = App(self.root, cwd=self.root, engines=self.engines)
        self.app.add_member(name="Marian", kind="human")
        for name, role in (("Claude", "architect"), ("Codex", "backend")):
            member = self.app.add_member(name=name, engine="claude")
            self.app.add_seat_def(role=role, prompt="You are the %s." % role,
                                  default_member=member.id)
        self.project = self.app.add_project("sinaxa")
        self.session = self.project.sessions[0]
        self.seat = {self.app.sinaxa.seat_name(s): s
                     for s in self.session.seats}

    def say(self, text, images=None, room=None):
        return self.app.say(self.project.id, self.session.id,
                            (room or self.session.all_room).id, text,
                            images=images)

    def transcript(self, room=None):
        return self.app.messages(self.project.id, self.session.id,
                                 (room or self.session.all_room).id)

    def files(self):
        folder = self.app.store.images_dir(self.project, self.session)
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


class Storing(Room):
    def test_an_image_is_kept_beside_the_transcript(self):
        self.say("look at this", [(png(), ".png")])
        stored = self.files()
        self.assertEqual(len(stored), 1)
        self.assertEqual(self.transcript()[0]["images"], stored)
        folder = self.app.store.images_dir(self.project, self.session)
        self.assertTrue(os.path.isdir(folder))
        self.assertIn("files", folder)

    def test_the_same_image_twice_is_stored_once(self):
        blob = png()
        self.say("once", [(blob, ".png")])
        self.say("again", [(blob, ".png")])
        self.assertEqual(len(self.files()), 1)
        mine = [m for m in self.transcript() if m["author"] == "lead"]
        self.assertEqual(mine[0]["images"], mine[1]["images"])

    def test_two_different_images_are_two_files(self):
        self.say("two", [(png((255, 0, 0)), ".png"), (png((0, 0, 255)), ".png")])
        self.assertEqual(len(self.files()), 2)
        self.assertEqual(len(self.transcript()[0]["images"]), 2)

    def test_nothing_is_resized_on_the_way_in(self):
        blob = png(size=64)
        self.say("as it is", [(blob, ".png")])
        name = self.transcript()[0]["images"][0]
        path = self.app.image(self.project.id, self.session.id, name)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), blob)

    def test_an_image_survives_a_restart(self):
        self.say("look", [(png(), ".png")])
        name = self.transcript()[0]["images"][0]
        again = App(self.root, cwd=self.root, engines=FakeEngines())
        self.assertTrue(again.image(self.project.id, self.session.id, name))

    def test_a_name_from_outside_is_not_trusted(self):
        """The name arrives over HTTP; it is checked, not joined blindly."""
        self.say("look", [(png(), ".png")])
        for bad in ("../../../etc/passwd", "..%2fsecret", "notahash.png",
                    "", None):
            self.assertIsNone(
                self.app.image(self.project.id, self.session.id, bad))


class Delivering(Room):
    def test_the_image_reaches_the_seats_that_were_asked(self):
        self.say("what is this?", [(png(), ".png")])
        for name in ("Claude", "Codex"):
            paths = self.engines.seen_by(name)
            self.assertEqual(len(paths), 1)
            self.assertTrue(os.path.exists(paths[0]))

    def test_the_message_says_an_image_is_attached(self):
        self.say("what is this?", [(png(), ".png")])
        self.assertIn("[1 image attached]", self.engines.heard_by("Claude")[0])

    def test_several_images_are_all_handed_over(self):
        self.say("two of them",
                 [(png((1, 2, 3)), ".png"), (png((4, 5, 6)), ".png")])
        self.assertEqual(len(self.engines.seen_by("Claude")), 2)
        self.assertIn("[2 images attached]", self.engines.heard_by("Claude")[0])

    def test_a_message_with_no_image_hands_over_none(self):
        self.say("just words")
        self.assertEqual(self.engines.seen_by("Claude"), [])
        self.assertNotIn("image", self.engines.heard_by("Claude")[0])

    def test_an_image_may_be_sent_with_no_words_at_all(self):
        self.say("", [(png(), ".png")])
        self.assertEqual(len(self.engines.seen_by("Claude")), 1)


class CatchingUp(Room):
    def test_a_seat_that_was_silent_is_shown_the_image_it_missed(self):
        """Decided: resend. A picture referred to but never shown is worse
        than no picture at all."""
        self.say("@Claude look at this", [(png(), ".png")])
        self.assertEqual(self.engines.seen_by("Codex"), [],
                         "Codex was not addressed and must not have been called")

        self.say("@Codex what do you make of it?")
        paths = self.engines.seen_by("Codex")
        self.assertEqual(len(paths), 1, "the missed image was not resent")
        self.assertTrue(os.path.exists(paths[0]))

    def test_an_image_already_shown_is_not_shown_again(self):
        self.say("everyone, look", [(png(), ".png")])
        self.say("and now?")
        self.assertEqual(len(self.engines.seen_by("Claude")), 1)

    def test_an_image_in_a_room_a_seat_is_not_in_never_reaches_it(self):
        private = self.session.private_room_of(self.seat["Claude"].id)
        self.say("between us", [(png(), ".png")], room=private)
        self.say("@Codex hello")
        self.assertEqual(self.engines.seen_by("Codex"), [])


class WithoutVision(Room):
    blind = ("Codex",)

    def test_a_seat_that_cannot_read_an_image_is_not_given_one(self):
        self.say("look at this", [(png(), ".png")])
        self.assertEqual(len(self.engines.seen_by("Claude")), 1)
        self.assertEqual(self.engines.seen_by("Codex"), [],
                         "an image was handed to an engine that cannot read it")

    def test_it_is_told_there_was_an_image_rather_than_left_to_guess(self):
        self.say("look at this", [(png(), ".png")])
        self.assertIn("which you cannot read",
                      self.engines.heard_by("Codex")[0])

    def test_the_answer_is_marked_so_the_interface_can_say_so(self):
        self.say("look at this", [(png(), ".png")])
        answers = {m["author_name"]: m for m in self.transcript()
                   if m["author"] != "lead"}
        self.assertEqual(answers["Codex"]["meta"]["blind"], 1)
        self.assertNotIn("blind", answers["Claude"].get("meta", {}))

    def test_a_message_without_images_is_not_marked(self):
        self.say("just words")
        answers = {m["author_name"]: m for m in self.transcript()
                   if m["author"] != "lead"}
        self.assertNotIn("blind", answers["Codex"].get("meta", {}))


class OverTheWire(unittest.TestCase):
    """What the page sends, and what the server makes of it."""

    def test_base64_becomes_bytes_and_a_suffix(self):
        blob = png()
        items = [{"type": "image/png", "data": base64.b64encode(blob).decode()},
                 {"type": "image/jpeg", "data": base64.b64encode(b"x").decode()}]
        self.assertEqual(decode_images(items),
                         [(blob, ".png"), (b"x", ".jpg")])

    def test_an_unknown_type_is_treated_as_a_png_rather_than_refused(self):
        item = [{"type": "image/heic", "data": base64.b64encode(b"x").decode()}]
        self.assertEqual(decode_images(item)[0][1], ".png")

    def test_nothing_at_all_is_no_images(self):
        for empty in (None, [], [{"type": "image/png", "data": ""}]):
            self.assertEqual(decode_images(empty), [])

    def test_an_image_too_large_is_refused_with_a_readable_reason(self):
        huge = base64.b64encode(b"\0" * (25 * 1024 * 1024)).decode()
        with self.assertRaises(ModelError) as caught:
            decode_images([{"type": "image/png", "data": huge}])
        self.assertIn("MB", str(caught.exception))


class TheAdapters(unittest.TestCase):
    """Each engine takes an image in the one shape it accepts. Measured
    against the real ones in tools/probe_images.py; held here so a change
    in our code is caught without a subscription."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="sinaxa-img-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.path = os.path.join(self.folder, "shot.png")
        self.blob = png()
        with open(self.path, "wb") as fh:
            fh.write(self.blob)

    def test_claude_carries_it_inline_as_base64(self):
        from src.engines.claude_session import image_block
        block = image_block(self.path)
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["media_type"], "image/png")
        self.assertEqual(base64.b64decode(block["source"]["data"]), self.blob)

    def test_claude_names_the_media_type_from_the_suffix(self):
        from src.engines.claude_session import image_block
        for suffix, kind in ((".jpg", "image/jpeg"), (".gif", "image/gif"),
                             (".webp", "image/webp")):
            path = os.path.join(self.folder, "shot" + suffix)
            shutil.copy(self.path, path)
            self.assertEqual(image_block(path)["source"]["media_type"], kind)

    def test_codex_is_given_a_path_because_it_refuses_anything_else(self):
        """Measured: a data URL and a bare path under type "image" both come
        back "missing field `url`". localImage with a path is what works."""
        import src.engines.codex_app as codex
        sent = {}

        class Backend:
            cwd = self.folder
            _threads = {}
            def start(self): pass
            def _request(self, method, params, timeout):
                sent[method] = params
                if method == "thread/start":
                    return {"result": {"thread": {"id": "th-1"}}}
                return {"result": {}}

        agent = codex.CodexAppAgent(Backend(), "codex")
        agent._done.set()
        agent._chunks = ["ok"]
        agent.ask("what is this?", timeout=1, images=[self.path])
        items = sent["turn/start"]["input"]
        self.assertEqual(items[0], {"type": "localImage", "path": self.path})
        self.assertEqual(items[-1]["type"], "text")

    def test_opencode_is_given_a_data_uri_because_a_path_silently_fails(self):
        """Measured: a bare path and a file:// uri are taken by the endpoint
        and then die inside opencode with "media must contain valid base64",
        which reaches the room as an answer that never comes."""
        import src.engines.opencode_http as opencode
        sent = {}

        class Backend:
            poll = 0.01
            def start(self): pass
            def call(self, path, payload=None, timeout=None):
                if path.endswith("/prompt"):
                    sent["prompt"] = payload["prompt"]
                    return {}
                if path.endswith("/message"):
                    return {"data": [{"type": "assistant", "finish": "stop",
                                      "content": [{"type": "text", "text": "ok"}],
                                      "tokens": {"input": 1, "output": 1}}]}
                return {"id": "ses_1"}

        agent = opencode.OpencodeAgent(Backend(), "opencode")
        agent.session_id = "ses_1"
        agent.ask("what is this?", timeout=5, images=[self.path])
        attached = sent["prompt"]["files"]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["name"], "shot.png")
        head, _, payload = attached[0]["uri"].partition(",")
        self.assertEqual(head, "data:image/png;base64")
        self.assertEqual(base64.b64decode(payload), self.blob)

    def test_every_adapter_says_whether_it_can_carry_one(self):
        from src.engines.claude_cli import ClaudeAgent
        from src.engines.codex_app import CodexAppAgent
        from src.engines.opencode_http import OpencodeAgent
        for agent in (ClaudeAgent, CodexAppAgent, OpencodeAgent):
            self.assertTrue(getattr(agent, "accepts_images", None),
                            "%s does not declare it" % agent.__name__)


if __name__ == "__main__":
    unittest.main()
