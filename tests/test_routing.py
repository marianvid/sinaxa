"""Who gets woken, and how far a conversation between agents can run.

The expensive mistake this guards against: an agent's reply being
re-broadcast to the whole room, so the same question is asked twice and
billed twice.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab as L
from test_lab import make_lab


def texts(room, author=None):
    return [m["text"] for m in room.messages
            if not m.get("kind") and (author is None or m["author"] == author)]


class Broadcast(unittest.TestCase):
    def test_a_message_with_no_mention_reaches_both_agents_once(self):
        lab = make_lab()
        lab.send(lab.rooms["main"], "status please")
        self.assertEqual(len(lab._agents["claude"].asked), 1)
        self.assertEqual(len(lab._agents["codex"].asked), 1)

    def test_the_reply_is_written_into_the_room(self):
        lab = make_lab()
        lab.send(lab.rooms["main"], "status please")
        self.assertIn("ok from claude", texts(lab.rooms["main"]))
        self.assertIn("ok from codex", texts(lab.rooms["main"]))

    def test_the_agent_sees_who_wrote_to_it(self):
        lab = make_lab()
        lab.send(lab.rooms["main"], "status please")
        self.assertEqual(lab._agents["claude"].asked[0], "[Marian] status please")


class Mentions(unittest.TestCase):
    def test_naming_one_agent_leaves_the_other_asleep(self):
        lab = make_lab()
        lab.send(lab.rooms["main"], "@Codex only you")
        self.assertEqual(lab._agents["codex"].asked, ["[Marian] @Codex only you"])
        self.assertEqual(lab._agents["claude"].asked, [])


class AgentToAgent(unittest.TestCase):
    def test_a_reply_naming_someone_reaches_only_them(self):
        # Claude names Codex; Codex must be woken exactly once, by that reply,
        # and the reply must not go back out to the whole room.
        lab = make_lab(replies={"claude": "@Codex what do you think?",
                                "codex": "fine by me"})
        lab.send(lab.rooms["main"], "@Claude start")
        self.assertEqual(lab._agents["claude"].asked, ["[Marian] @Claude start"])
        self.assertEqual(lab._agents["codex"].asked,
                         ["[Claude] @Codex what do you think?"])

    def test_a_politeness_loop_cannot_run_away(self):
        # Both agents keep naming each other. Without a cap this never ends.
        lab = make_lab(replies={"claude": "@Codex thanks", "codex": "@Claude thanks"})
        lab.send(lab.rooms["main"], "@Claude go")
        total = len(lab._agents["claude"].asked) + len(lab._agents["codex"].asked)
        self.assertLessEqual(total, L.MAX_HOPS + 1)
        self.assertGreater(total, 1)

    def test_an_agent_naming_itself_is_not_woken_again(self):
        lab = make_lab(replies={"claude": "@Claude note to self"})
        lab.send(lab.rooms["main"], "@Claude go")
        self.assertEqual(len(lab._agents["claude"].asked), 1)


class Notes(unittest.TestCase):
    def test_writing_a_note_wakes_nobody(self):
        lab = make_lab()
        lab.send(lab.rooms["notes"], "remember to update the readme")
        self.assertEqual(lab._agents["claude"].asked, [])
        self.assertEqual(lab._agents["codex"].asked, [])

    def test_the_note_is_still_written_down(self):
        lab = make_lab()
        lab.send(lab.rooms["notes"], "remember to update the readme")
        self.assertEqual(texts(lab.rooms["notes"]), ["remember to update the readme"])


class Failure(unittest.TestCase):
    def test_an_agent_that_cannot_answer_is_reported_not_silent(self):
        lab = make_lab()

        class Broken:
            def ask(self, text, timeout=None):
                return None, {"error": "the process died"}
            def status(self):
                return {"turns": 0, "tokens": 0, "alive": False, "pids": []}
            def stop(self):
                pass

        lab.agent_for = lambda member, room: Broken()
        lab.send(lab.rooms["main"], "@Claude hello")
        errors = [m for m in lab.rooms["main"].messages if m.get("kind") == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("the process died", errors[0]["text"])


if __name__ == "__main__":
    unittest.main()
