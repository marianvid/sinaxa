"""The room model: seats, who is visible where, who gets woken.

No agent is started here — the backends are replaced with fakes, so these
run in milliseconds and cost nothing.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab as L


class FakeAgent:
    """Answers instantly, records what it was asked."""

    provider = "fake"

    def __init__(self, name, reply=""):
        self.name = name
        self.reply = reply
        self.asked = []

    def ask(self, text, timeout=None):
        self.asked.append(text)
        return (self.reply or "ok from %s" % self.name), {"elapsed": 0.0}

    def status(self):
        return {"provider": self.provider, "model": "fake", "conversation": "",
                "activity": "", "turns": len(self.asked), "tokens": 0,
                "alive": True, "pids": [], "shared_process": True}

    def stop(self):
        pass


def make_lab(replies=None):
    """A Lab whose transcript goes to a temp file and whose agents are fakes."""
    tmp = tempfile.mkdtemp()
    L.STATE = tmp
    lab = L.Lab("fake", tmp)
    lab.log = os.path.join(tmp, "t.jsonl")
    agents = {m: FakeAgent(m, (replies or {}).get(m, "")) for m in ("claude", "codex")}
    lab.agent_for = lambda member, room: agents[member]
    lab._agents = agents
    return lab


class Seats(unittest.TestCase):
    def test_every_seat_has_a_role_and_the_lead_is_unique(self):
        lab = make_lab()
        self.assertEqual([s["role"] for s in lab.seats],
                         ["cto", "architect", "backend", "reviewer"])
        self.assertEqual(sum(1 for s in lab.seats if s["lead"]), 1)

    def test_an_empty_seat_opens_no_room(self):
        lab = make_lab()
        reviewer = next(s for s in lab.seats if s["id"] == "reviewer")
        self.assertIsNone(reviewer["occupant"])
        self.assertIsNone(reviewer["room"])

    def test_each_occupied_seat_opens_a_room_that_exists(self):
        lab = make_lab()
        for seat in lab.seats:
            if seat["occupant"]:
                self.assertIn(seat["room"], lab.rooms, seat["role"])

    def test_main_shows_every_seat_a_subroom_only_its_own(self):
        lab = make_lab()
        self.assertEqual(len(lab.seats_of(lab.rooms["main"])), 4)
        claude_room = lab.seats_of(lab.rooms["claude"])
        self.assertEqual({s["id"] for s in claude_room}, {"cto", "architect"})

    def test_notes_belong_to_the_lead_alone(self):
        lab = make_lab()
        notes = lab.rooms["notes"]
        self.assertEqual(notes.members, ["you"])
        self.assertEqual(notes.kind, "notes")


class WhoAnswers(unittest.TestCase):
    def test_naming_nobody_wakes_every_agent(self):
        lab = make_lab()
        who = lab.speakers_for(lab.rooms["main"], "how are we doing?", "you")
        self.assertEqual(set(who), {"claude", "codex"})

    def test_naming_one_wakes_only_that_one(self):
        lab = make_lab()
        who = lab.speakers_for(lab.rooms["main"], "@Codex what about the store?", "you")
        self.assertEqual(who, ["codex"])

    def test_the_author_never_answers_itself(self):
        lab = make_lab()
        who = lab.speakers_for(lab.rooms["main"], "@Claude and @Codex", "claude")
        self.assertEqual(who, ["codex"])

    def test_a_mention_is_a_whole_word(self):
        lab = make_lab()
        self.assertEqual(lab.mentioned("@Codexander", lab.rooms["main"]), [])
        self.assertEqual(lab.mentioned("@Codex.", lab.rooms["main"]), ["codex"])

    def test_a_room_with_no_agents_wakes_nobody(self):
        lab = make_lab()
        self.assertEqual(lab.speakers_for(lab.rooms["notes"], "a note", "you"), [])


class Transcript(unittest.TestCase):
    def test_a_message_survives_a_reload(self):
        lab = make_lab()
        lab.append(lab.rooms["main"], "you", "remember this")
        again = L.Lab("fake", os.path.dirname(lab.log))
        again.log = lab.log
        for room in again.rooms.values():
            room.messages = []
        again._load()
        self.assertEqual([m["text"] for m in again.rooms["main"].messages],
                         ["remember this"])

    def test_a_message_is_one_json_object_per_line(self):
        lab = make_lab()
        lab.append(lab.rooms["main"], "you", "first")
        lab.append(lab.rooms["claude"], "you", "second")
        with open(lab.log, encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh if x.strip()]
        self.assertEqual([l["room"] for l in lines], ["main", "claude"])

    def test_notes_are_kept_like_anything_else(self):
        lab = make_lab()
        lab.append(lab.rooms["notes"], "you", "buy milk")
        self.assertEqual(lab.rooms["notes"].messages[0]["text"], "buy milk")


if __name__ == "__main__":
    unittest.main()
