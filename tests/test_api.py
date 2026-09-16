import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.fakes.fake_engines import FakeEngines
from src.app import App
from src.server import Handler


def call(base, method, path, body=None):
    request = urllib.request.Request(base + path,
        json.dumps(body).encode() if body is not None else None,
        {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(request) as answer:
            return answer.status, json.loads(answer.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_http_crud_and_fast_turn_acceptance(tmp_path):
    app = App(tmp_path, engines=FakeEngines())
    Handler.app = app
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = "http://127.0.0.1:%d" % port
    try:
        assert call(base, "GET", "/api/state")[0] == 200
        _, lead = call(base, "POST", "/api/members", {"name": "Marian", "kind": "human"})
        _, agent = call(base, "POST", "/api/members", {"name": "Astra", "engine": "claude"})
        _, template = call(base, "POST", "/api/seat-templates", {
            "role": "API reviewer", "prompt": "Review API changes",
            "category": "software", "default_agent": agent["member"]["id"]})
        _, project_type = call(base, "POST", "/api/project-types", {
            "name": "API product", "category": "software",
            "description": "Test recipe",
            "seat_templates": [template["seat_template"]["id"]]})
        _, project = call(base, "POST", "/api/projects", {
            "name": "Sinaxa", "type_id": project_type["project_type"]["id"]})
        _, seat = call(base, "POST", "/api/seats", {"project": project["project"]["id"], "role": "Architect", "prompt": "Design", "occupant": agent["member"]["id"]})
        state = call(base, "GET", "/api/state?project=" + project["project"]["id"])[1]
        assert [item["role"] for item in state["seats"]] == [
            "API reviewer", "Architect"]
        team = next(s for s in state["projects"][0]["sessions"] if s["kind"] == "team")
        status, accepted = call(base, "POST", "/api/say", {"project": project["project"]["id"], "session": team["id"], "text": "hello"})
        assert status == 200 and accepted["accepted"]
    finally:
        server.shutdown(); server.server_close(); app.stop()
