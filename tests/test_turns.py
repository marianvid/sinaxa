"""Who answers, and how far a chain of mentions may run."""

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


class Turns(unittest.TestCase):
    answers = None

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.engines = FakeEngines(self.answers)
        self.app = App(self.root, cwd=self.root, engines=self.engines)
        self.app.add_member(name="Marian", kind="human")
        for name, role in (("Claude", "architect"), ("Codex", "backend")):
            member = self.app.add_member(name=name, engine="claude")
            self.app.add_seat_def(role=role, prompt="You are the %s." % role,
                                  default_member=member.id)
        self.project = self.app.add_project("sinaxa")
        self.session = self.project.sessions[0]
        self.room = self.session.all_room
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def say(self, text):
        return self.app.say(self.project.id, self.session.id, self.room.id,
                            text)

    def transcript(self):
        return self.app.messages(self.project.id, self.session.id,
                                 self.room.id)

    def turns(self, name):
        return self.engines.agents[name].turns if name in self.engines.agents \
            else 0


class Broadcast(Turns):
    def test_naming_nobody_asks_every_seat_in_the_room(self):
        self.say("status please")
        self.assertEqual(self.turns("Claude"), 1)
        self.assertEqual(self.turns("Codex"), 1)

    def test_naming_someone_asks_only_them(self):
        self.say("@Codex how is the server")
        self.assertEqual(self.turns("Claude"), 0)
        self.assertEqual(self.turns("Codex"), 1)

    def test_naming_two_asks_both_and_nobody_else(self):
        spare = self.app.add_member(name="Third", engine="claude")
        definition = self.app.add_seat_def(role="reviewer", prompt="review",
                                           default_member=spare.id)
        self.app.add_seat(self.project.id, self.session.id, definition.id,
                          spare.id)
        self.say("@Claude @Codex both of you")
        self.assertEqual(self.turns("Claude"), 1)
        self.assertEqual(self.turns("Codex"), 1)
        self.assertEqual(self.turns("Third"), 0)

    def test_every_answer_is_written_into_the_room(self):
        self.say("status please")
        authors = [m["author_name"] for m in self.transcript()]
        self.assertEqual(authors, ["Marian", "Claude", "Codex"])

    def test_what_a_turn_cost_is_written_down_with_the_answer(self):
        """It used to be hung on the message after it had been written, so
        it lived until the next reload and no longer."""
        self.say("status please")
        answers = [m for m in self.transcript() if m["author"] != "lead"]
        for answer in answers:
            self.assertIn("tokens", answer.get("meta", {}),
                          "the cost of the turn was lost on the way to disk")

        again = App(self.root, cwd=self.root, engines=FakeEngines())
        reloaded = again.messages(self.project.id, self.session.id,
                                  self.room.id)
        self.assertEqual([m.get("meta") for m in reloaded],
                         [m.get("meta") for m in self.transcript()])

    def test_the_messages_are_numbered_in_the_order_they_were_said(self):
        self.say("one")
        self.say("two")
        seqs = [m["seq"] for m in self.transcript()]
        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), len(seqs))


class BetweenAgents(Turns):
    answers = {("Claude", 1): "I need @Codex for the schema",
               "Codex": "Codex: here it is"}

    def test_an_answer_that_names_someone_reaches_only_them(self):
        self.say("@Claude design it")
        self.assertEqual(self.turns("Codex"), 1)
        delivered = self.engines.heard_by("Codex")[0]
        self.assertIn("I need @Codex for the schema", delivered)

    def test_the_answer_to_a_mention_is_not_re_broadcast(self):
        """Without this the room re-asks everyone and the same question is
        put twice."""
        self.say("@Claude design it")
        self.assertEqual(self.turns("Claude"), 1,
                         "Claude was asked again about its own question")


class HopCap(Turns):
    answers = {"Claude": "over to @Codex", "Codex": "back to @Claude"}

    def test_a_chain_of_mentions_cannot_run_away(self):
        self.say("@Claude start")
        total = self.turns("Claude") + self.turns("Codex")
        self.assertLessEqual(total, 4, "the hop cap did not hold")
        self.assertGreater(total, 1, "the chain did not run at all")


class Errors(Turns):
    answers = {"Codex": RuntimeError("the process died")}

    def test_a_failed_answer_is_written_into_the_room_not_swallowed(self):
        self.say("everyone")
        errors = [m for m in self.transcript() if m.get("kind") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("the process died", errors[0]["text"])

    def test_the_other_seats_still_answer(self):
        self.say("everyone")
        said = [m["author_name"] for m in self.transcript()]
        self.assertIn("Claude", said)


if __name__ == "__main__":
    unittest.main()
