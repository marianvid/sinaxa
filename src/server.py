"""Thin JSON/HTTP adapter. All application behaviour lives in App."""

import argparse
import base64
import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .app import App
from .domain import ModelError

HOST, PORT = "127.0.0.1", 8789
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "ui")
PAGES = ("projects", "members", "seats", "types", "engines", "settings")
STATIC = {"/%s.%s" % (page, ext): ("%s.%s" % (page, ext),
          {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
           "js": "text/javascript; charset=utf-8"}[ext])
          for page in PAGES for ext in ("html", "css", "js")}
STATIC["/base.css"] = ("base.css", "text/css; charset=utf-8")
STATIC["/base.js"] = ("base.js", "text/javascript; charset=utf-8")
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp"}
SUFFIX = {value: key for key, value in MIME.items()}
MAX_IMAGE = 24 * 1024 * 1024


def decode_images(items):
    out = []
    for item in items or []:
        blob = base64.b64decode(item.get("data") or "")
        if len(blob) > MAX_IMAGE:
            raise ModelError("an attachment exceeds the 24 MB limit")
        if blob:
            out.append((blob, SUFFIX.get(item.get("type"), ".png")))
    return out


class Handler(BaseHTTPRequestHandler):
    app = None

    @property
    def parts(self):
        return [part for part in urlparse(self.path).path.split("/") if part]

    @property
    def query(self):
        return {key: values[0] for key, values in
                parse_qs(urlparse(self.path).query).items()}

    def payload(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, mime):
        with open(path, "rb") as stream:
            body = stream.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guarded(self, action):
        try:
            self.send_json(200, action())
        except ModelError as exc:
            self.send_json(400, {"error": str(exc)})
        except KeyError as exc:
            self.send_json(404, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            path = "/projects.html"
        if path in STATIC:
            name, mime = STATIC[path]
            return self.send_file(os.path.join(UI, name), mime)
        if path == "/api/state":
            q = self.query
            return self.guarded(lambda: self.app.state(
                q.get("project"), q.get("session"), q.get("search"),
                q.get("before"), q.get("limit", 60)))
        if path == "/api/models":
            q = self.query
            return self.guarded(lambda: {"models": self.app.models_for(
                q["engine"], q.get("project"))})
        if path.startswith("/api/jobs/"):
            return self.guarded(lambda: self.app.job(self.parts[2]))
        if path.startswith("/api/files/"):
            q = self.query
            found = self.app.image(q["project"], q["session"], self.parts[2])
            if not found:
                return self.send_json(404, {"error": "no such attachment"})
            return self.send_file(found, MIME.get(os.path.splitext(found)[1],
                                                  "application/octet-stream"))
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        body = self.payload()
        self.guarded(lambda: self.post(self.parts, body))

    def do_PATCH(self):
        body = self.payload()
        self.guarded(lambda: self.patch(self.parts, body))

    def do_DELETE(self):
        self.guarded(lambda: self.delete(self.parts, self.query))

    def post(self, parts, body):
        if parts == ["api", "say"]:
            message, job = self.app.say(body["project"], body["session"],
                                        body.get("text", ""),
                                        decode_images(body.get("images")))
            return {"ok": True, "accepted": True, "message": message, "job": job}
        if parts == ["api", "projects"]:
            made = self.app.add_project(body["name"], body.get("cwd"),
                                        body.get("type_id"))
            return {"ok": True, "project": made.as_dict()}
        if parts == ["api", "members"]:
            made = self.app.add_member(**self.fields(body, (
                "name", "kind", "engine", "model", "effort", "colour",
                "options", "allowed_mcp_servers")))
            return {"ok": True, "member": made.as_dict()}
        if parts == ["api", "seats"]:
            made = self.app.add_seat(body["project"], body["template_id"],
                                     body.get("occupant"), body.get("prompt"))
            return {"ok": True, "seat": made.as_dict()}
        if parts == ["api", "seat-templates"]:
            made = self.app.add_seat_template(**self.fields(body, (
                "role", "prompt", "category", "default_agent")))
            return {"ok": True, "seat_template": made.as_dict()}
        if parts == ["api", "project-types"]:
            made = self.app.add_project_type(**self.fields(body, (
                "name", "category", "description", "seat_templates")))
            return {"ok": True, "project_type": made.as_dict()}
        if parts == ["api", "sessions"]:
            made = self.app.add_session(body["project"], body["name"],
                                        body.get("participants", []))
            return {"ok": True, "session": made.as_dict()}
        if len(parts) == 4 and parts[:2] == ["api", "sessions"]:
            project = body["project"]
            if parts[3] == "context":
                message = self.app.clear_context(project, parts[2])
                return {"ok": True, "message": message}
            if parts[3] == "history":
                self.app.clear_history(project, parts[2])
                return {"ok": True}
        raise KeyError("no such endpoint")

    def patch(self, parts, body):
        if len(parts) != 3 or parts[0] != "api":
            raise KeyError("no such endpoint")
        kind, ident = parts[1], parts[2]
        actions = {
            "engines": lambda: self.app.update_engine(ident, **body).as_dict(),
            "members": lambda: self.app.update_member(ident, **body).as_dict(),
            "projects": lambda: self.app.update_project(ident, **body).as_dict(),
            "seats": lambda: self.app.update_seat(body["project"], ident,
                                                   **{k: v for k, v in body.items()
                                                      if k != "project"}).as_dict(),
            "seat-templates": lambda: self.app.update_seat_template(
                ident, **body).as_dict(),
            "project-types": lambda: self.app.update_project_type(
                ident, **body).as_dict(),
            "sessions": lambda: self.app.update_session(body["project"], ident,
                                                         **{k: v for k, v in body.items()
                                                            if k != "project"}).as_dict(),
        }
        if kind not in actions:
            raise KeyError("no such endpoint")
        return {"ok": True, kind[:-1]: actions[kind]()}

    def delete(self, parts, query):
        if len(parts) != 3 or parts[0] != "api":
            raise KeyError("no such endpoint")
        kind, ident = parts[1], parts[2]
        if kind == "members":
            self.app.remove_member(ident)
        elif kind == "projects":
            self.app.remove_project(ident, query.get("erase") == "1")
        elif kind == "seats":
            self.app.remove_seat(query["project"], ident)
        elif kind == "seat-templates":
            self.app.remove_seat_template(ident)
        elif kind == "project-types":
            self.app.remove_project_type(ident)
        elif kind == "sessions":
            self.app.remove_session(query["project"], ident)
        else:
            raise KeyError("no such endpoint")
        return {"ok": True}

    @staticmethod
    def fields(body, names):
        return {name: body[name] for name in names if name in body}

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(prog="sinaxa")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--state", default=os.path.join(ROOT, "state"))
    parser.add_argument("--cwd", default=ROOT)
    args = parser.parse_args()
    Handler.app = App(args.state, cwd=args.cwd)

    def leave(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, leave)
    print("sinaxa -> http://%s:%d" % (HOST, args.port))
    try:
        ThreadingHTTPServer((HOST, args.port), Handler).serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        Handler.app.stop()


if __name__ == "__main__":
    main()
