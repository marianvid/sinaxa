"""Every action, driven over HTTP as the page drives it.

A real server on a real port, so a route that does not exist, a body the
handler cannot read, or a rule that only fires in App are all caught here
rather than in the browser.
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fakes.fake_engines import FakeEngines            # noqa: E402
from src.app import App                               # noqa: E402
from src.server import Handler                        # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class OverHttp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sinaxa-state-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.engines = FakeEngines()
        self.app = App(self.root, cwd=self.root, engines=self.engines)

        port = free_port()
        self.base = "http://127.0.0.1:%d" % port
        Handler.app = self.app
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    # ------------------------------------------------------------- wire
    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base + path, data, {"Content-Type": "application/json"})
        request.get_method = lambda: method
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return answer.status, json.loads(answer.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def state(self, **query):
        bits = "&".join("%s=%s" % pair for pair in query.items())
        return self.call("GET", "/api/state?" + bits)[1]

    # ------------------------------------------------------------ setup
    def furnish(self):
        self.call("POST", "/api/members", {"name": "Marian", "kind": "human"})
        claude = self.call("POST", "/api/members", {
            "name": "Claude", "engine": "claude", "model": "sonnet",
            "effort": "high"})[1]["member"]
        codex = self.call("POST", "/api/members", {
            "name": "Codex", "engine": "codex", "model": "gpt-5.6-sol"})[1]["member"]
        self.call("POST", "/api/seatdefs", {"role": "architect",
                                            "prompt": "You design.",
                                            "default_member": claude["id"]})
        self.call("POST", "/api/seatdefs", {"role": "backend",
                                            "prompt": "You build.",
                                            "default_member": codex["id"]})
        project = self.call("POST", "/api/projects", {"name": "sinaxa"})[1]["project"]
        state = self.state(project=project["id"])
        return project, state, claude, codex


class Page(OverHttp):
    def test_the_page_and_its_stylesheet_are_served(self):
        for path, marker in (("/", "sinaxa"), ("/sinaxa.css", "--accent")):
            with urllib.request.urlopen(self.base + path, timeout=10) as answer:
                self.assertEqual(answer.status, 200)
                self.assertIn(marker, answer.read().decode())

    def test_an_unknown_route_is_a_404_not_a_crash(self):
        code, _ = self.call("POST", "/api/nonsense", {})
        self.assertEqual(code, 404)

    def test_an_empty_sinaxa_still_answers(self):
        state = self.state()
        self.assertEqual(state["projects"], [])
        self.assertEqual(len(state["engines"]), 3)


class Members(OverHttp):
    def test_added_edited_and_removed(self):
        code, made = self.call("POST", "/api/members", {
            "name": "Claude", "engine": "claude", "model": "sonnet"})
        self.assertEqual(code, 200)
        member_id = made["member"]["id"]

        self.call("PATCH", "/api/members/" + member_id,
                  {"model": "opus", "effort": "high"})
        member = self.state()["members"][0]
        self.assertEqual((member["model"], member["effort"]), ("opus", "high"))

        self.assertEqual(self.call("DELETE", "/api/members/" + member_id)[0], 200)
        self.assertEqual(self.state()["members"], [])

    def test_a_broken_member_is_refused_with_a_readable_reason(self):
        code, answer = self.call("POST", "/api/members", {"name": "Ghost"})
        self.assertEqual(code, 400)
        self.assertIn("engine", answer["error"])

    def test_a_member_holding_a_seat_is_not_removed(self):
        _, _, claude, _ = self.furnish()
        code, answer = self.call("DELETE", "/api/members/" + claude["id"])
        self.assertEqual(code, 400)
        self.assertIn("sinaxa / main", answer["error"])

    def test_each_engine_describes_its_own_form(self):
        engines = {e["id"]: e for e in self.state()["engines"]}
        self.assertEqual(engines["claude"]["efforts"][0], "low")
        self.assertEqual(engines["codex"]["efforts"], ["medium"])
        self.assertTrue(engines["opencode"]["models_from_engine"])
        self.assertFalse(engines["opencode"]["models_are_a_hint"])


class Roles(OverHttp):
    def test_added_edited_and_removed(self):
        made = self.call("POST", "/api/seatdefs",
                         {"role": "reviewer", "prompt": "You review."})[1]
        def_id = made["seat_def"]["id"]

        self.call("PATCH", "/api/seatdefs/" + def_id, {"prompt": "Be harsh."})
        self.assertEqual(self.state()["seat_defs"][0]["prompt"], "Be harsh.")

        self.call("DELETE", "/api/seatdefs/" + def_id)
        self.assertEqual(self.state()["seat_defs"], [])

    def test_a_role_in_use_is_not_removed(self):
        _, state, _, _ = self.furnish()
        code, answer = self.call("DELETE",
                                 "/api/seatdefs/" + state["seat_defs"][0]["id"])
        self.assertEqual(code, 400)
        self.assertIn("in use", answer["error"])


class Projects(OverHttp):
    def test_a_new_project_arrives_seated(self):
        project, state, _, _ = self.furnish()
        self.assertEqual(len(state["seats"]), 2)
        self.assertEqual(sorted(r["kind"] for r in state["rooms"]),
                         ["all", "private", "private"])
        self.assertEqual(state["rooms"][0]["name"], "main")

    def test_removed_keeping_the_history(self):
        project, _, _, _ = self.furnish()
        self.assertEqual(self.call("DELETE", "/api/projects/" + project["id"])[0],
                         200)
        self.assertEqual(self.state()["projects"], [])
        self.assertTrue(os.path.isdir(os.path.join(
            self.root, "projects", project["id"] + ".removed")))

    def test_removed_from_the_disk_when_asked(self):
        project, _, _, _ = self.furnish()
        self.call("DELETE", "/api/projects/%s?erase=1" % project["id"])
        self.assertEqual(os.listdir(os.path.join(self.root, "projects")), [])

    def test_two_projects_of_the_same_name_are_refused(self):
        self.furnish()
        code, answer = self.call("POST", "/api/projects", {"name": "SINAXA"})
        self.assertEqual(code, 400)
        self.assertIn("already exists", answer["error"])


class Sessions(OverHttp):
    def test_added_renamed_and_removed(self):
        project, _, _, _ = self.furnish()
        made = self.call("POST", "/api/sessions",
                         {"project": project["id"], "name": "spike"})[1]
        session_id = made["session"]["id"]

        state = self.state(project=project["id"])
        self.assertEqual([s["name"] for s in state["projects"][0]["sessions"]],
                         ["main", "spike"])

        self.call("PATCH", "/api/sessions/" + session_id,
                  {"project": project["id"], "name": "spike-2"})
        state = self.state(project=project["id"], session=session_id)
        self.assertEqual(state["rooms"][0]["name"], "spike-2",
                         "the common room is named after its session")

        self.call("DELETE", "/api/sessions/%s?project=%s&erase=1"
                  % (session_id, project["id"]))
        state = self.state(project=project["id"])
        self.assertEqual([s["name"] for s in state["projects"][0]["sessions"]],
                         ["main"])

    def test_the_last_session_of_a_project_stays(self):
        project, state, _, _ = self.furnish()
        code, answer = self.call("DELETE", "/api/sessions/%s?project=%s"
                                 % (state["session"], project["id"]))
        self.assertEqual(code, 400)
        self.assertIn("at least one session", answer["error"])

    def test_a_new_session_starts_empty(self):
        project, _, _, _ = self.furnish()
        made = self.call("POST", "/api/sessions",
                         {"project": project["id"], "name": "spike"})[1]
        state = self.state(project=project["id"],
                           session=made["session"]["id"])
        self.assertEqual(state["seats"], [])
        self.assertEqual(len(state["rooms"]), 1)


class Seats(OverHttp):
    def setUp(self):
        super().setUp()
        self.project, self.first, self.claude, self.codex = self.furnish()
        self.session = self.first["session"]

    def where(self):
        return {"project": self.project["id"], "session": self.session}

    def test_a_seat_is_added_with_its_room_and_removed_with_it(self):
        made = self.call("POST", "/api/seatdefs",
                         {"role": "reviewer", "prompt": "You review."})[1]
        body = dict(self.where(), seat_def=made["seat_def"]["id"],
                    occupant=self.claude["id"])
        seat = self.call("POST", "/api/seats", body)[1]["seat"]

        state = self.state(project=self.project["id"], session=self.session)
        self.assertEqual(len(state["seats"]), 3)
        self.assertEqual(len([r for r in state["rooms"]
                              if r["kind"] == "private"]), 3)

        self.call("DELETE", "/api/seats/%s?project=%s&session=%s"
                  % (seat["id"], self.project["id"], self.session))
        state = self.state(project=self.project["id"], session=self.session)
        self.assertEqual(len(state["seats"]), 2)
        self.assertEqual(len([r for r in state["rooms"]
                              if r["kind"] == "private"]), 2)

    def test_the_occupant_and_the_prompt_are_changed_in_the_session(self):
        seat = self.first["seats"][0]
        self.call("PATCH", "/api/seats/" + seat["id"],
                  dict(self.where(), occupant=self.codex["id"],
                       prompt="You design, briefly."))
        state = self.state(project=self.project["id"], session=self.session)
        changed = next(s for s in state["seats"] if s["id"] == seat["id"])
        self.assertEqual(changed["occupant"], self.codex["id"])
        self.assertEqual(changed["prompt_effective"], "You design, briefly.")
        self.assertTrue(changed["overridden"])

    def test_the_override_is_dropped_back_to_the_roles_default(self):
        seat = self.first["seats"][0]
        self.call("PATCH", "/api/seats/" + seat["id"],
                  dict(self.where(), prompt="Something else."))
        self.call("PATCH", "/api/seats/" + seat["id"],
                  dict(self.where(), clear_prompt=True))
        state = self.state(project=self.project["id"], session=self.session)
        back = next(s for s in state["seats"] if s["id"] == seat["id"])
        self.assertFalse(back["overridden"])
        self.assertEqual(back["prompt_effective"], "You design.")

    def test_the_same_role_is_not_seated_twice(self):
        body = dict(self.where(), seat_def=self.first["seats"][0]["seat_def"],
                    occupant=self.codex["id"])
        code, answer = self.call("POST", "/api/seats", body)
        self.assertEqual(code, 400)
        self.assertIn("already a seat", answer["error"])

    def test_the_context_of_one_seat_is_cleared_on_its_own(self):
        self.call("POST", "/api/say",
                  dict(self.where(), room=self.first["rooms"][0]["id"],
                       text="hello"))
        code, _ = self.call("POST",
                            "/api/seats/%s/clear" % self.first["seats"][0]["id"],
                            self.where())
        self.assertEqual(code, 200)
        self.assertTrue(self.engines.history[0].stopped)
        messages = self.state(project=self.project["id"],
                              session=self.session)["messages"]
        self.assertTrue(any(m["text"] == "hello" for m in messages),
                        "clearing a context must not touch the transcript")


class Rooms(OverHttp):
    def setUp(self):
        super().setUp()
        self.project, self.first, _, _ = self.furnish()
        self.session = self.first["session"]
        self.seats = [s["id"] for s in self.first["seats"]]

    def where(self):
        return {"project": self.project["id"], "session": self.session}

    def state_now(self):
        return self.state(project=self.project["id"], session=self.session)

    def test_a_room_is_made_from_a_selection_and_removed_again(self):
        room = self.call("POST", "/api/rooms",
                         dict(self.where(), name="api",
                              seats=self.seats))[1]["room"]
        self.assertEqual(room["kind"], "custom")
        self.assertIn("api", [r["name"] for r in self.state_now()["rooms"]])

        self.call("DELETE", "/api/rooms/%s?project=%s&session=%s"
                  % (room["id"], self.project["id"], self.session))
        self.assertNotIn("api", [r["name"] for r in self.state_now()["rooms"]])

    def test_seats_go_in_and_out_of_a_room_of_your_own(self):
        room = self.call("POST", "/api/rooms",
                         dict(self.where(), name="api",
                              seats=[self.seats[0]]))[1]["room"]
        self.call("POST", "/api/rooms/%s/seats" % room["id"],
                  dict(self.where(), seat=self.seats[1]))
        after = next(r for r in self.state_now()["rooms"] if r["id"] == room["id"])
        self.assertEqual(after["seats"], self.seats)

        self.call("DELETE", "/api/rooms/%s/seats/%s?project=%s&session=%s"
                  % (room["id"], self.seats[0], self.project["id"],
                     self.session))
        after = next(r for r in self.state_now()["rooms"] if r["id"] == room["id"])
        self.assertEqual(after["seats"], [self.seats[1]])

    def test_the_common_room_cannot_be_edited_or_removed(self):
        common = next(r for r in self.first["rooms"] if r["kind"] == "all")
        self.assertFalse(common["editable"])
        code, answer = self.call("POST", "/api/rooms/%s/seats" % common["id"],
                                 dict(self.where(), seat=self.seats[0]))
        self.assertEqual(code, 400)
        code, _ = self.call("DELETE", "/api/rooms/%s?project=%s&session=%s"
                            % (common["id"], self.project["id"], self.session))
        self.assertEqual(code, 400)

    def test_a_room_with_no_seats_is_refused(self):
        code, answer = self.call("POST", "/api/rooms",
                                 dict(self.where(), name="empty", seats=[]))
        self.assertEqual(code, 400)
        self.assertIn("at least one seat", answer["error"])


class Talking(OverHttp):
    def test_a_message_is_answered_and_the_thread_comes_back(self):
        project, state, _, _ = self.furnish()
        room = state["rooms"][0]["id"]
        code, _ = self.call("POST", "/api/say",
                            {"project": project["id"],
                             "session": state["session"],
                             "room": room, "text": "status please"})
        self.assertEqual(code, 200)
        messages = self.state(project=project["id"], session=state["session"],
                              room=room)["messages"]
        self.assertEqual([m["author_name"] for m in messages],
                         ["Marian", "Claude", "Codex"])


if __name__ == "__main__":
    unittest.main()
