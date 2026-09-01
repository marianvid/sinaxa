"""HTTP. It parses, it calls App, it serialises. No rules live here.

    GET    /                                the page
    GET    /api/state?project=&session=&room=
    GET    /api/models?engine=
    POST   /api/say            {project, session, room, text}

    POST   /api/projects       {name, cwd}
    DELETE /api/projects/<id>?erase=1

    POST   /api/members        {name, kind, engine, model, effort, binary}
    PATCH  /api/members/<id>
    DELETE /api/members/<id>

    POST   /api/seatdefs       {role, prompt, default_member}
    PATCH  /api/seatdefs/<id>
    DELETE /api/seatdefs/<id>

    POST   /api/sessions       {project, name}
    PATCH  /api/sessions/<id>  {project, name}
    DELETE /api/sessions/<id>?project=&erase=1

    POST   /api/seats          {project, session, seat_def, occupant, prompt}
    PATCH  /api/seats/<id>     {project, session, occupant, prompt, clear_prompt}
    DELETE /api/seats/<id>?project=&session=
    POST   /api/seats/<id>/clear   {project, session}

    POST   /api/rooms          {project, session, name, seats[]}
    DELETE /api/rooms/<id>?project=&session=&erase=1
    POST   /api/rooms/<id>/seats     {project, session, seat}
    DELETE /api/rooms/<id>/seats/<seat_id>?project=&session=
"""

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .app import App
from .model import ModelError

HOST, PORT = "127.0.0.1", 8789
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UI = os.path.join(ROOT, "ui")
PAGE = os.path.join(UI, "sinaxa.html")
STYLE = os.path.join(UI, "sinaxa.css")


class Handler(BaseHTTPRequestHandler):
    app = None
    lock = threading.Lock()

    # ------------------------------------------------------------ replies
    def send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, mime):
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ reading
    @property
    def parts(self):
        return [p for p in urlparse(self.path).path.strip("/").split("/") if p]

    @property
    def query(self):
        return {k: v[0] for k, v in
                parse_qs(urlparse(self.path).query).items()}

    def payload(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def where(self, body):
        """Every write says which project and session it means."""
        query = self.query
        return (body.get("project") or query.get("project"),
                body.get("session") or query.get("session"))

    # ------------------------------------------------------------ routing
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send_file(PAGE, "text/html; charset=utf-8")
        if path == "/sinaxa.css":
            return self.send_file(STYLE, "text/css; charset=utf-8")
        if path == "/api/state":
            query = self.query
            with self.lock:
                return self.guarded(lambda: self.app.state(
                    query.get("project"), query.get("session"),
                    query.get("room")))
        if path == "/api/models":
            engine = self.query.get("engine")
            return self.guarded(lambda: {"models":
                                         self.app.models_for(engine)})
        return self.send(404, {"error": "not found"})

    def do_POST(self):
        body = self.payload()
        with self.lock:
            return self.guarded(lambda: self.post(self.parts, body))

    def do_PATCH(self):
        body = self.payload()
        with self.lock:
            return self.guarded(lambda: self.patch(self.parts, body))

    def do_DELETE(self):
        with self.lock:
            return self.guarded(lambda: self.delete(self.parts, self.query))

    def guarded(self, work):
        try:
            return self.send(200, work())
        except ModelError as exc:
            return self.send(400, {"error": str(exc)})
        except KeyError as exc:
            return self.send(404, {"error": str(exc)})
        except Exception as exc:                       # pragma: no cover
            return self.send(500, {"error": "%s: %s"
                                            % (type(exc).__name__, exc)})

    # ------------------------------------------------------------ writing
    def post(self, parts, body):
        app = self.app
        if parts[:2] == ["api", "say"]:
            project, session = self.where(body)
            message = app.say(project, session, body["room"], body["text"])
            return {"ok": True, "message": message}

        if parts[:2] == ["api", "projects"]:
            project = app.add_project(body["name"], cwd=body.get("cwd"))
            return {"ok": True, "project": project.as_dict()}

        if parts[:2] == ["api", "members"]:
            member = app.add_member(**self.member_fields(body))
            return {"ok": True, "member": member.as_dict()}

        if parts[:2] == ["api", "seatdefs"]:
            definition = app.add_seat_def(
                role=body["role"], prompt=body.get("prompt", ""),
                default_member=body.get("default_member") or None)
            return {"ok": True, "seat_def": definition.as_dict()}

        if parts[:2] == ["api", "sessions"]:
            session = app.add_session(body["project"], body["name"])
            return {"ok": True, "session": {"id": session.id,
                                            "name": session.name}}

        if parts[:2] == ["api", "seats"]:
            project, session = self.where(body)
            if len(parts) == 4 and parts[3] == "clear":
                app.clear_seat_context(project, session, parts[2])
                return {"ok": True}
            seat = app.add_seat(project, session, body["seat_def"],
                                body["occupant"], body.get("prompt"))
            return {"ok": True, "seat": seat.as_dict()}

        if parts[:2] == ["api", "rooms"]:
            project, session = self.where(body)
            if len(parts) == 4 and parts[3] == "seats":
                room = app.add_seat_to_room(project, session, parts[2],
                                            body["seat"])
                return {"ok": True, "room": room.as_dict()}
            room = app.add_room(project, session, body["name"],
                                body.get("seats") or [])
            return {"ok": True, "room": room.as_dict()}

        raise KeyError("no such endpoint")

    def patch(self, parts, body):
        app = self.app
        if parts[:2] == ["api", "members"] and len(parts) == 3:
            fields = self.member_fields(body, partial=True)
            member = app.update_member(parts[2], **fields)
            return {"ok": True, "member": member.as_dict()}

        if parts[:2] == ["api", "seatdefs"] and len(parts) == 3:
            fields = {k: body[k] for k in ("role", "prompt", "default_member")
                      if k in body}
            definition = app.update_seat_def(parts[2], **fields)
            return {"ok": True, "seat_def": definition.as_dict()}

        if parts[:2] == ["api", "sessions"] and len(parts) == 3:
            session = app.rename_session(body["project"], parts[2],
                                         body["name"])
            return {"ok": True, "session": {"id": session.id,
                                            "name": session.name}}

        if parts[:2] == ["api", "seats"] and len(parts) == 3:
            project, session = self.where(body)
            seat, restarted = app.update_seat(project, session, parts[2],
                                              occupant=body.get("occupant"),
                                              prompt=body.get("prompt"))
            answer = {"ok": True, "seat": seat.as_dict(),
                      "restarted": restarted}
            if restarted:
                answer["warning"] = (
                    "the seat's process was restarted -- a running model is "
                    "only ever told its prompt once. It reads the rooms back "
                    "on its next turn.")
            return answer

        raise KeyError("no such endpoint")

    def delete(self, parts, query):
        app = self.app
        erase = query.get("erase") in ("1", "true", "yes")
        project, session = query.get("project"), query.get("session")

        if parts[:2] == ["api", "projects"] and len(parts) == 3:
            app.remove_project(parts[2], erase=erase)
            return {"ok": True}
        if parts[:2] == ["api", "members"] and len(parts) == 3:
            app.remove_member(parts[2])
            return {"ok": True}
        if parts[:2] == ["api", "seatdefs"] and len(parts) == 3:
            app.remove_seat_def(parts[2])
            return {"ok": True}
        if parts[:2] == ["api", "sessions"] and len(parts) == 3:
            app.remove_session(project, parts[2], erase=erase)
            return {"ok": True}
        if parts[:2] == ["api", "seats"] and len(parts) == 3:
            app.remove_seat(project, session, parts[2])
            return {"ok": True}
        if parts[:2] == ["api", "rooms"]:
            if len(parts) == 5 and parts[3] == "seats":
                room = app.remove_seat_from_room(project, session, parts[2],
                                                 parts[4])
                return {"ok": True, "room": room.as_dict()}
            if len(parts) == 3:
                app.remove_room(project, session, parts[2], erase=erase)
                return {"ok": True}
        raise KeyError("no such endpoint")

    @staticmethod
    def member_fields(body, partial=False):
        names = ("name", "kind", "engine", "model", "effort", "binary",
                 "colour")
        fields = {k: body[k] for k in names if k in body}
        if not partial:
            fields.setdefault("kind", "agent")
        return fields

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(prog="sinaxa")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--state", default=os.path.join(ROOT, "state"))
    parser.add_argument("--cwd", default=ROOT)
    parser.add_argument("--opencode-port", type=int, default=4096)
    args = parser.parse_args()

    Handler.app = App(args.state, cwd=args.cwd,
                      opencode_port=args.opencode_port)
    print("sinaxa     ->  http://%s:%d" % (HOST, args.port))
    print("state      ->  %s" % args.state)
    print("projects   ->  %d" % len(Handler.app.sinaxa.projects))
    try:
        ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopping agents...")
        Handler.app.stop()


if __name__ == "__main__":
    main()
