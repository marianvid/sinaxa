"""What each seat may read, and what it must never see.

The whole context model is one rule -- a seat sees every message of every
room it belongs to -- so these tests are the rule, stated as consequences:
the common room reaches everyone, a private room reaches its own, and a seat
that was not asked anything still catches up on what it was entitled to hear.
"""

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


class Furnished(unittest.TestCase):
    """Three seats in one session: Claude, Codex and Opencode."""

    answers = None

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.engines = FakeEngines(self.answers)
        self.app = App(self.root, cwd=self.root, engines=self.engines)
        self.app.add_member(name="Marian", kind="human")
        people = {}
        for name, engine in (("Claude", "claude"), ("Codex", "codex"),
                             ("Opencode", "opencode")):
            people[name] = self.app.add_member(name=name, engine=engine)
        for role, who in (("architect", "Claude"), ("backend", "Codex"),
                          ("reviewer", "Opencode")):
            self.app.add_seat_def(role=role, prompt="You are the %s." % role,
                                  default_member=people[who].id)
        self.project = self.app.add_project("sinaxa")
        self.session = self.project.sessions[0]
        self.seat = {self.app.sinaxa.seat_name(s): s for s in self.session.seats}
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def say(self, room, text):
        return self.app.say(self.project.id, self.session.id, room.id, text)

    def private(self, name):
        return self.session.private_room_of(self.seat[name].id)

    def heard(self, name):
        return self.engines.everything_heard_by(name)


class CommonRoom(Furnished):
    def test_what_is_said_to_everyone_reaches_everyone(self):
        self.say(self.session.all_room, "morning all")
        for name in ("Claude", "Codex", "Opencode"):
            self.assertIn("morning all", self.heard(name))

    def test_each_message_says_which_room_it_was_said_in(self):
        self.say(self.session.all_room, "morning all")
        self.assertIn("[main - Marian] morning all", self.heard("Claude"))

    def test_a_seat_hears_the_others_answers_in_the_same_room(self):
        self.say(self.session.all_room, "morning all")
        self.say(self.session.all_room, "and again")
        self.assertIn("Codex: ok", self.heard("Claude"))
        self.assertIn("Claude: ok", self.heard("Codex"))


class PrivateRoom(Furnished):
    def test_a_room_of_two_stays_between_the_two(self):
        self.say(self.private("Claude"), "just between us: the build is broken")
        self.assertIn("the build is broken", self.heard("Claude"))
        self.assertNotIn("the build is broken", self.heard("Codex"))
        self.assertNotIn("the build is broken", self.heard("Opencode"))

    def test_one_seat_carries_both_rooms_in_a_single_context(self):
        """Same colleague, same memory, different rooms."""
        self.say(self.session.all_room, "public thing")
        self.say(self.private("Claude"), "private thing")
        heard = self.heard("Claude")
        self.assertIn("public thing", heard)
        self.assertIn("private thing", heard)
        self.assertEqual(len(self.engines.agents["Claude"].heard), 2,
                         "one agent, not one per room")

    def test_the_private_room_is_named_so_the_seat_can_tell_them_apart(self):
        self.say(self.private("Claude"), "quiet word")
        self.assertIn("[architect - Marian] quiet word", self.heard("Claude"))


class CatchingUp(Furnished):
    answers = {"Claude": "Claude: ok", "Codex": "Codex: ok"}

    def test_a_seat_that_was_not_asked_is_caught_up_on_its_next_turn(self):
        self.say(self.session.all_room, "@Claude only you")
        self.assertEqual(self.engines.heard_by("Codex"), [],
                         "Codex was not addressed and must not have been called")

        self.say(self.session.all_room, "@Codex now you")
        caught_up = self.engines.heard_by("Codex")[0]
        self.assertIn("only you", caught_up, "Codex missed the earlier message")
        self.assertIn("Claude: ok", caught_up, "Codex missed Claude's answer")
        self.assertIn("now you", caught_up)

    def test_nothing_is_delivered_twice(self):
        self.say(self.session.all_room, "one")
        self.say(self.session.all_room, "two")
        heard = self.heard("Claude")
        self.assertEqual(heard.count("[main - Marian] one"), 1)

    def test_a_seat_is_never_caught_up_on_a_room_it_is_not_in(self):
        self.say(self.private("Claude"), "secret")
        self.say(self.session.all_room, "@Codex hello")
        self.assertNotIn("secret", self.heard("Codex"))


class CustomRoom(Furnished):
    def test_a_room_made_from_a_selection_reaches_only_that_selection(self):
        room = self.app.add_room(self.project.id, self.session.id, "api",
                                 [self.seat["Claude"].id,
                                  self.seat["Codex"].id])
        self.say(room, "the two of you")
        self.assertIn("the two of you", self.heard("Claude"))
        self.assertIn("the two of you", self.heard("Codex"))
        self.assertNotIn("the two of you", self.heard("Opencode"))

    def test_a_seat_added_later_is_caught_up_from_the_transcript(self):
        room = self.app.add_room(self.project.id, self.session.id, "api",
                                 [self.seat["Claude"].id])
        self.say(room, "early news")
        self.app.add_seat_to_room(self.project.id, self.session.id, room.id,
                                  self.seat["Opencode"].id)
        self.say(room, "@Opencode what do you think")
        self.assertIn("early news", self.heard("Opencode"),
                      "joining a room means reading what it said")


class ClearingContext(Furnished):
    def test_clearing_forgets_the_model_and_keeps_the_transcript(self):
        self.say(self.session.all_room, "remember this")
        first = self.engines.agents["Claude"]

        self.app.clear_seat_context(self.project.id, self.session.id,
                                    self.seat["Claude"].id)
        self.assertTrue(first.stopped)

        self.say(self.session.all_room, "and now")
        second = self.engines.agents["Claude"]
        self.assertIsNot(first, second, "a cleared seat starts a new agent")
        self.assertIn("remember this", second.heard[0],
                      "the room's history is what a fresh agent is given")

    def test_changing_the_prompt_restarts_the_process_at_once(self):
        """A model is told its prompt when its process starts and never
        again, so saving a new one has to replace the process there and
        then -- not next time, and not silently never."""
        self.say(self.session.all_room, "hello")
        first = self.engines.agents["Claude"]

        _, restarted = self.app.update_seat(
            self.project.id, self.session.id, self.seat["Claude"].id,
            prompt="Be blunt.")

        self.assertTrue(restarted, "the interface was not told to warn")
        self.assertTrue(first.stopped, "the old process was left running")
        second = self.engines.agents["Claude"]
        self.assertIsNot(first, second)
        self.assertIn("Be blunt.", second.instructions)

    def test_the_replacement_reads_the_rooms_back(self):
        self.say(self.session.all_room, "remember this")
        self.app.update_seat(self.project.id, self.session.id,
                             self.seat["Claude"].id, prompt="Be blunt.")
        self.say(self.session.all_room, "and now")
        self.assertIn("remember this",
                      self.engines.agents["Claude"].heard[0])

    def test_saving_the_same_prompt_again_leaves_the_process_alone(self):
        """Nothing changed, so nothing is thrown away."""
        self.say(self.session.all_room, "hello")
        first = self.engines.agents["Claude"]
        _, restarted = self.app.update_seat(
            self.project.id, self.session.id, self.seat["Claude"].id,
            occupant=self.seat["Claude"].occupant, prompt=None)
        self.assertFalse(restarted)
        self.assertFalse(first.stopped)

    def test_emptying_the_prompt_puts_the_roles_own_back(self):
        self.app.update_seat(self.project.id, self.session.id,
                             self.seat["Claude"].id, prompt="Be blunt.")
        self.app.update_seat(self.project.id, self.session.id,
                             self.seat["Claude"].id, prompt="   ")
        self.say(self.session.all_room, "hello")
        self.assertIn("You are the architect.",
                      self.engines.agents["Claude"].instructions)

    def test_changing_the_occupant_retires_the_agent_too(self):
        self.say(self.session.all_room, "hello")
        first = self.engines.agents["Claude"]
        spare = self.app.add_member(name="Spare", engine="opencode")
        self.app.update_seat(self.project.id, self.session.id,
                             self.seat["Claude"].id, occupant=spare.id)
        self.say(self.session.all_room, "again")
        self.assertTrue(first.stopped)
        self.assertIn("Spare", self.engines.agents)


class Prompts(Furnished):
    def test_a_seat_is_told_its_role_its_room_mates_and_the_lead(self):
        self.say(self.session.all_room, "hello")
        told = self.engines.agents["Claude"].instructions
        self.assertIn("You are the architect.", told)
        self.assertIn("Marian is the human and the lead", told)
        self.assertIn("Codex (backend)", told)

    def test_the_session_override_replaces_the_roles_default(self):
        self.app.update_seat(self.project.id, self.session.id,
                             self.seat["Codex"].id,
                             prompt="You own the database. Nothing else.")
        self.say(self.session.all_room, "hello")
        told = self.engines.agents["Codex"].instructions
        self.assertIn("You own the database.", told)
        self.assertNotIn("You are the backend.", told)


class Trouble(Furnished):
    def test_a_seat_whose_occupant_vanished_reports_it_in_the_room(self):
        seat = self.seat["Codex"]
        seat.occupant = "mem_gone"
        self.say(self.session.all_room, "@backend are you there")
        messages = self.app.messages(self.project.id, self.session.id,
                                     self.session.all_room.id)
        errors = [m for m in messages if m.get("kind") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("no longer exists", errors[0]["text"])
        self.assertEqual(errors[0]["author"], seat.id)

    def test_one_seat_in_trouble_does_not_stop_the_others(self):
        self.seat["Codex"].occupant = "mem_gone"
        self.say(self.session.all_room, "everyone")
        self.assertIn("everyone", self.heard("Claude"))
        self.assertIn("everyone", self.heard("Opencode"))


if __name__ == "__main__":
    unittest.main()
