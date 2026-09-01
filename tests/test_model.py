"""The rules the structures promise to keep."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.model import ALL, CUSTOM, PRIVATE, ModelError, Sinaxa   # noqa: E402


def furnished():
    """A sinaxa with two roles, each with a default occupant."""
    sinaxa = Sinaxa()
    sinaxa.add_member(name="Marian", kind="human")
    claude = sinaxa.add_member(name="Claude", engine="claude", model="sonnet",
                               effort="medium")
    codex = sinaxa.add_member(name="Codex", engine="codex", model="gpt-5.6-sol")
    sinaxa.add_seat_def(role="architect", prompt="You design.",
                        default_member=claude.id)
    sinaxa.add_seat_def(role="backend", prompt="You write the server.",
                        default_member=codex.id)
    return sinaxa


class Members(unittest.TestCase):
    def test_an_agent_without_an_engine_is_refused(self):
        with self.assertRaises(ModelError):
            Sinaxa().add_member(name="Ghost")

    def test_names_are_unique_because_mentions_are_by_name(self):
        sinaxa = furnished()
        with self.assertRaises(ModelError):
            sinaxa.add_member(name="claude", engine="codex")

    def test_there_is_only_one_human_lead(self):
        sinaxa = furnished()
        with self.assertRaises(ModelError):
            sinaxa.add_member(name="Someone", kind="human")
        self.assertEqual(sinaxa.lead.name, "Marian")

    def test_a_member_holding_a_seat_cannot_be_deleted_out_from_under_it(self):
        sinaxa = furnished()
        sinaxa.add_project("sinaxa")
        claude = next(m for m in sinaxa.members if m.name == "Claude")
        with self.assertRaises(ModelError) as caught:
            sinaxa.remove_member(claude.id)
        self.assertIn("sinaxa / main", str(caught.exception))

    def test_a_member_holding_nothing_is_deleted(self):
        sinaxa = furnished()
        spare = sinaxa.add_member(name="Spare", engine="opencode")
        sinaxa.remove_member(spare.id)
        self.assertNotIn(spare, sinaxa.members)


class Roles(unittest.TestCase):
    def test_a_role_in_use_cannot_be_deleted(self):
        sinaxa = furnished()
        sinaxa.add_project("sinaxa")
        architect = sinaxa.seat_defs[0]
        with self.assertRaises(ModelError):
            sinaxa.remove_seat_def(architect.id)

    def test_role_names_are_unique(self):
        sinaxa = furnished()
        with self.assertRaises(ModelError):
            sinaxa.add_seat_def(role="Architect")


class Projects(unittest.TestCase):
    def test_a_new_project_arrives_with_the_team_already_seated(self):
        sinaxa = furnished()
        project = sinaxa.add_project("sinaxa")
        session = project.sessions[0]
        self.assertEqual(session.name, "main")
        self.assertEqual(len(session.seats), 2)
        self.assertEqual(sorted(r.kind for r in session.rooms),
                         [ALL, PRIVATE, PRIVATE])

    def test_a_role_without_a_default_occupant_takes_no_seat(self):
        """A seat exists because somebody occupies it. There is no empty one."""
        sinaxa = furnished()
        sinaxa.add_seat_def(role="reviewer", prompt="You review.")
        session = sinaxa.add_project("sinaxa").sessions[0]
        self.assertEqual([sinaxa.seat_def(s.seat_def).role
                          for s in session.seats],
                         ["architect", "backend"])

    def test_every_seat_is_in_the_common_room_and_in_its_own(self):
        sinaxa = furnished()
        session = sinaxa.add_project("sinaxa").sessions[0]
        for seat in session.seats:
            rooms = session.rooms_of(seat.id)
            self.assertEqual(sorted(r.kind for r in rooms), [ALL, PRIVATE])

    def test_a_project_keeps_at_least_one_session(self):
        sinaxa = furnished()
        project = sinaxa.add_project("sinaxa")
        with self.assertRaises(ModelError):
            project.remove_session(project.sessions[0].id)


class Seats(unittest.TestCase):
    def setUp(self):
        self.sinaxa = furnished()
        self.project = self.sinaxa.add_project("sinaxa")
        self.session = self.project.sessions[0]

    def test_the_same_role_is_not_seated_twice_in_one_session(self):
        architect = self.sinaxa.seat_defs[0]
        codex = next(m for m in self.sinaxa.members if m.name == "Codex")
        with self.assertRaises(ModelError):
            self.sinaxa.add_seat(self.session, architect.id, codex.id)

    def test_the_prompt_falls_back_to_the_role_and_the_session_overrides_it(self):
        seat = self.session.seats[0]
        self.assertEqual(self.sinaxa.prompt_for(self.session, seat),
                         "You design.")
        seat.prompt = "You design, and you are blunt."
        self.assertEqual(self.sinaxa.prompt_for(self.session, seat),
                         "You design, and you are blunt.")

    def test_an_empty_override_is_an_override_not_a_fallback(self):
        """Blanking the prompt must mean blank, not 'use the default'."""
        seat = self.session.seats[0]
        seat.prompt = ""
        self.assertEqual(self.sinaxa.prompt_for(self.session, seat), "")

    def test_removing_a_seat_takes_its_rooms_with_it(self):
        seat = self.session.seats[0]
        private = self.session.private_room_of(seat.id)
        self.session.remove_seat(seat.id)
        self.assertNotIn(private, self.session.rooms)
        self.assertNotIn(seat.id, self.session.all_room.seats)

    def test_a_seat_whose_occupant_vanished_says_so_rather_than_going_empty(self):
        seat = self.session.seats[0]
        seat.occupant = "mem_gone"
        self.assertIn("no longer exists", self.sinaxa.seat_trouble(seat))
        self.assertEqual(self.sinaxa.seat_name(seat), "architect")


class Rooms(unittest.TestCase):
    def setUp(self):
        self.sinaxa = furnished()
        self.session = self.sinaxa.add_project("sinaxa").sessions[0]
        self.first, self.second = self.session.seats

    def test_a_room_is_made_from_a_selection_of_seats(self):
        room = self.session.add_room("api", [self.first.id, self.second.id])
        self.assertEqual(room.kind, CUSTOM)
        self.assertEqual(len(self.session.rooms_of(self.first.id)), 3)

    def test_a_room_without_seats_is_refused(self):
        with self.assertRaises(ModelError):
            self.session.add_room("empty", [])

    def test_the_common_room_and_the_private_ones_follow_the_session(self):
        for room in self.session.rooms:
            if room.managed:
                with self.assertRaises(ModelError):
                    self.session.remove_room(room.id)
                with self.assertRaises(ModelError):
                    self.session.add_seat_to_room(room.id, self.second.id)

    def test_seats_go_in_and_out_of_a_room_of_your_own(self):
        room = self.session.add_room("api", [self.first.id])
        self.session.add_seat_to_room(room.id, self.second.id)
        self.assertEqual(room.seats, [self.first.id, self.second.id])
        self.session.remove_seat_from_room(room.id, self.first.id)
        self.assertEqual(room.seats, [self.second.id])

    def test_the_last_seat_cannot_be_taken_out_of_a_room(self):
        room = self.session.add_room("api", [self.first.id])
        with self.assertRaises(ModelError):
            self.session.remove_seat_from_room(room.id, self.first.id)

    def test_a_room_of_your_own_is_removed_when_you_say_so(self):
        room = self.session.add_room("api", [self.first.id])
        self.session.remove_room(room.id)
        self.assertNotIn(room, self.session.rooms)


class Mentions(unittest.TestCase):
    def test_a_name_is_matched_whole_and_regardless_of_case(self):
        sinaxa = furnished()
        session = sinaxa.add_project("sinaxa").sessions[0]
        seats = session.seats
        self.assertEqual([s.id for s in sinaxa.mentioned("@claude look", seats)],
                         [seats[0].id])
        self.assertEqual(sinaxa.mentioned("@Claudette look", seats), [])
        self.assertEqual(len(sinaxa.mentioned("@Claude @Codex", seats)), 2)


if __name__ == "__main__":
    unittest.main()
