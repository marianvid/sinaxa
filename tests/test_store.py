"""Disk: what is written, where, and whether it comes back the same."""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fakes.fake_engines import FakeEngines            # noqa: E402
from src.app import App                               # noqa: E402
from src.store import Store                           # noqa: E402


class OnDisk(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.app = self.build()

    def build(self):
        """A fresh App over the same folder -- as if sinaxa were restarted."""
        app = App(self.root, cwd=self.root, engines=FakeEngines())
        return app

    def furnish(self):
        self.app.add_member(name="Marian", kind="human")
        claude = self.app.add_member(name="Claude", engine="claude",
                                     model="sonnet", effort="high")
        self.app.add_seat_def(role="architect", prompt="You design.",
                              default_member=claude.id)
        return self.app.add_project("sinaxa")

    def test_the_folders_are_named_by_id_and_the_names_live_in_the_json(self):
        project = self.furnish()
        session = project.sessions[0]
        folder = os.path.join(self.root, "projects", project.id)
        self.assertTrue(os.path.isdir(folder))
        self.assertTrue(project.id.startswith("prj_"))
        with open(os.path.join(folder, "project.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["name"], "sinaxa")
        self.assertTrue(os.path.isdir(
            os.path.join(folder, "sessions", session.id)))

    def test_renaming_moves_nothing(self):
        project = self.furnish()
        session = project.sessions[0]
        before = os.listdir(os.path.join(self.root, "projects", project.id,
                                         "sessions"))
        self.app.rename_session(project.id, session.id, "renamed")
        after = os.listdir(os.path.join(self.root, "projects", project.id,
                                        "sessions"))
        self.assertEqual(before, after)
        self.assertEqual(self.build().sinaxa.projects[0].sessions[0].name,
                         "renamed")

    def test_everything_comes_back_after_a_restart(self):
        project = self.furnish()
        session = project.sessions[0]
        self.app.say(project.id, session.id, session.all_room.id, "hello")

        again = self.build()
        member = next(m for m in again.sinaxa.members if m.name == "Claude")
        self.assertEqual((member.engine, member.model, member.effort),
                         ("claude", "sonnet", "high"))
        self.assertEqual(again.sinaxa.lead.name, "Marian")
        reloaded = again.sinaxa.projects[0].sessions[0]
        self.assertEqual(len(reloaded.seats), 1)
        self.assertEqual(sorted(r.kind for r in reloaded.rooms),
                         ["all", "private"])
        messages = again.messages(project.id, reloaded.id,
                                  reloaded.all_room.id)
        self.assertEqual(messages[0]["text"], "hello")

    def test_the_message_numbering_carries_on_after_a_restart(self):
        project = self.furnish()
        session = project.sessions[0]
        self.app.say(project.id, session.id, session.all_room.id, "one")
        highest = max(m["seq"] for m in self.app.messages(
            project.id, session.id, session.all_room.id))

        again = self.build()
        reloaded = again.sinaxa.projects[0].sessions[0]
        again.say(project.id, reloaded.id, reloaded.all_room.id, "two")
        seqs = [m["seq"] for m in again.messages(project.id, reloaded.id,
                                                 reloaded.all_room.id)]
        self.assertEqual(sorted(seqs), seqs)
        self.assertGreater(max(seqs), highest, "the numbering restarted")

    def test_each_room_keeps_its_own_transcript(self):
        project = self.furnish()
        session = project.sessions[0]
        seat = session.seats[0]
        private = session.private_room_of(seat.id)
        self.app.say(project.id, session.id, session.all_room.id, "public")
        self.app.say(project.id, session.id, private.id, "private")

        rooms_dir = os.path.join(self.root, "projects", project.id, "sessions",
                                 session.id, "rooms")
        self.assertEqual(sorted(os.listdir(rooms_dir)),
                         sorted([session.all_room.id + ".jsonl",
                                 private.id + ".jsonl"]))
        store = Store(self.root)
        self.assertEqual(len(store.messages(project, session, private)), 2)

    def test_the_rooms_of_a_session_merge_back_into_one_order(self):
        project = self.furnish()
        session = project.sessions[0]
        private = session.private_room_of(session.seats[0].id)
        self.app.say(project.id, session.id, session.all_room.id, "first")
        self.app.say(project.id, session.id, private.id, "second")
        self.app.say(project.id, session.id, session.all_room.id, "third")

        merged = Store(self.root).session_messages(project, session)
        said = [m["text"] for m in merged if m["author_name"] == "Marian"]
        self.assertEqual(said, ["first", "second", "third"])

    def test_a_transcript_is_only_ever_appended_to(self):
        project = self.furnish()
        session = project.sessions[0]
        path = Store(self.root).room_path(project, session, session.all_room)
        self.app.say(project.id, session.id, session.all_room.id, "one")
        with open(path, encoding="utf-8") as fh:
            first = fh.read()
        self.app.say(project.id, session.id, session.all_room.id, "two")
        with open(path, encoding="utf-8") as fh:
            self.assertTrue(fh.read().startswith(first))


class Removing(OnDisk):
    def test_removing_a_project_keeps_its_history_unless_you_say_otherwise(self):
        project = self.furnish()
        self.app.remove_project(project.id)
        self.assertEqual(self.build().sinaxa.projects, [])
        self.assertTrue(os.path.isdir(
            os.path.join(self.root, "projects", project.id + ".removed")))

    def test_removing_from_disk_leaves_nothing_behind(self):
        project = self.furnish()
        self.app.remove_project(project.id, erase=True)
        self.assertEqual(os.listdir(os.path.join(self.root, "projects")), [])
        self.assertEqual(self.build().sinaxa.projects, [])

    def test_a_removed_session_can_take_its_transcripts_with_it(self):
        project = self.furnish()
        second = self.app.add_session(project.id, "spike")
        folder = os.path.join(self.root, "projects", project.id, "sessions",
                              second.id)
        self.assertTrue(os.path.isdir(folder))
        self.app.remove_session(project.id, second.id, erase=True)
        self.assertFalse(os.path.isdir(folder))
        self.assertEqual(len(self.build().sinaxa.projects[0].sessions), 1)

    def test_a_removed_room_can_keep_its_transcript(self):
        project = self.furnish()
        session = project.sessions[0]
        room = self.app.add_room(project.id, session.id, "api",
                                 [session.seats[0].id])
        self.app.say(project.id, session.id, room.id, "hello")
        path = Store(self.root).room_path(project, session, room)
        self.app.remove_room(project.id, session.id, room.id)
        self.assertTrue(os.path.exists(path), "the history was thrown away")
        self.app.remove_room  # the room itself is gone from the session
        self.assertNotIn(room.id, [r.id for r in
                                   self.build().sinaxa.projects[0]
                                   .sessions[0].rooms])


if __name__ == "__main__":
    unittest.main()
