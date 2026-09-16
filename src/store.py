"""Versioned, atomic persistence owned by Sinaxa.

Configuration is small JSON. A session transcript is append-only JSONL and
native provider identifiers are disposable checkpoints: the transcript is
the source of truth. Nothing outside this state root is ever deleted.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading

from .model import (EngineConfig, Member, Project, ProjectType, SeatTemplate,
                    Sinaxa)

SCHEMA_VERSION = 3
REMOVED = ".removed"
IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{2,5}$")


class Store:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.projects_dir = os.path.join(self.root, "projects")
        self._lock = threading.RLock()

    def load(self):
        engines = [EngineConfig.from_dict(one) for one in
                   self._read("engines.json", self.default_engines())]
        members = [Member.from_dict(one) for one in self._read("members.json", [])]
        seat_templates = [SeatTemplate.from_dict(one) for one in
                          self._read("seat_templates.json",
                                     self.default_seat_templates())]
        project_types = [ProjectType.from_dict(one) for one in
                         self._read("project_types.json",
                                    self.default_project_types())]
        projects = []
        if os.path.isdir(self.projects_dir):
            for project_id in sorted(os.listdir(self.projects_dir)):
                if project_id.endswith(REMOVED):
                    continue
                raw = self._read(os.path.join("projects", project_id,
                                              "project.json"))
                if raw:
                    projects.append(Project.from_dict(raw))
        return Sinaxa(engines=engines, members=members, projects=projects,
                      seat_templates=seat_templates,
                      project_types=project_types)

    @staticmethod
    def default_engines():
        return [
            {"id": "claude", "kind": "claude", "name": "Claude CLI",
             "enabled": True, "executable": "claude", "mode": "persistent",
             "streaming": True, "max_concurrency": 4, "mcp_servers": [],
             "options": {}},
            {"id": "codex", "kind": "codex", "name": "Codex CLI",
             "enabled": True, "executable": "codex", "mode": "persistent",
             "streaming": True, "max_concurrency": 4, "mcp_servers": [],
             "options": {}},
            {"id": "opencode", "kind": "opencode", "name": "OpenCode CLI",
             "enabled": True, "executable": "opencode", "mode": "persistent",
             "streaming": True, "max_concurrency": 4, "mcp_servers": [],
             "options": {"base_port": 4096}},
        ]

    @staticmethod
    def default_seat_templates():
        return [
            {"id": "seat_architect", "role": "Architect",
             "category": "software",
             "prompt": "Shape the system design, boundaries and technical decisions.",
             "default_agent": None},
            {"id": "seat_developer", "role": "Developer",
             "category": "software",
             "prompt": "Implement scoped changes and keep the code maintainable.",
             "default_agent": None},
            {"id": "seat_tester", "role": "Tester",
             "category": "software",
             "prompt": "Verify behavior, expose risks and report reproducible failures.",
             "default_agent": None},
            {"id": "seat_researcher", "role": "Researcher",
             "category": "general",
             "prompt": "Gather evidence, compare sources and make uncertainty explicit.",
             "default_agent": None},
            {"id": "seat_writer", "role": "Writer",
             "category": "creative",
             "prompt": "Develop clear, engaging prose consistent with the project voice.",
             "default_agent": None},
            {"id": "seat_editor", "role": "Editor",
             "category": "editorial",
             "prompt": "Improve structure, accuracy, clarity and consistency.",
             "default_agent": None},
        ]

    @staticmethod
    def default_project_types():
        return [
            {"id": "type_blank", "name": "Blank project",
             "category": "general",
             "description": "Start without predefined seats.",
             "seat_templates": []},
            {"id": "type_software", "name": "Software development",
             "category": "software",
             "description": "A compact product team for building and validating software.",
             "seat_templates": ["seat_architect", "seat_developer",
                                "seat_tester"]},
        ]

    def _read(self, relative, fallback=None):
        path = os.path.join(self.root, relative)
        if not os.path.exists(path):
            return fallback
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    def _write(self, relative, payload):
        path = os.path.join(self.root, relative)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".sinaxa-", dir=folder)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_engines(self, sinaxa):
        with self._lock:
            self._write("engines.json", [e.as_dict() for e in sinaxa.engines])

    def save_members(self, sinaxa):
        with self._lock:
            self._write("members.json", [m.as_dict() for m in sinaxa.members])

    def save_seat_templates(self, sinaxa):
        with self._lock:
            self._write("seat_templates.json",
                        [t.as_dict() for t in sinaxa.seat_templates])

    def save_project_types(self, sinaxa):
        with self._lock:
            self._write("project_types.json",
                        [t.as_dict() for t in sinaxa.project_types])

    def save_project(self, project):
        with self._lock:
            self._write(os.path.join("projects", project.id, "project.json"),
                        project.as_dict())

    def save_all(self, sinaxa):
        self.save_engines(sinaxa)
        self.save_members(sinaxa)
        self.save_seat_templates(sinaxa)
        self.save_project_types(sinaxa)
        for project in sinaxa.projects:
            self.save_project(project)
        self._write("meta.json", {"schema": SCHEMA_VERSION})

    def project_dir(self, project):
        return os.path.join(self.projects_dir, project.id)

    def session_dir(self, project, session):
        return os.path.join(self.project_dir(project), "sessions", session.id)

    def transcript_path(self, project, session):
        return os.path.join(self.session_dir(project, session), "messages.jsonl")

    def append(self, project, session, message):
        path = self.transcript_path(project, session)
        with self._lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(message, ensure_ascii=False) + "\n")
                stream.flush()
        return message

    def messages(self, project, session):
        path = self.transcript_path(project, session)
        with self._lock:
            if not os.path.exists(path):
                return []
            with open(path, encoding="utf-8") as stream:
                return [json.loads(line) for line in stream if line.strip()]

    def clear_history(self, project, session):
        path = self.transcript_path(project, session)
        with self._lock:
            if os.path.exists(path):
                os.unlink(path)
            files = os.path.join(self.session_dir(project, session), "files")
            if os.path.isdir(files):
                shutil.rmtree(files)
            self.clear_checkpoints(project, session)

    def checkpoints(self, project, session):
        relative = os.path.relpath(os.path.join(
            self.session_dir(project, session), "conversations.json"), self.root)
        return self._read(relative, {})

    def save_checkpoint(self, project, session, seat_id, checkpoint):
        with self._lock:
            records = self.checkpoints(project, session)
            if checkpoint:
                records[seat_id] = checkpoint
            else:
                records.pop(seat_id, None)
            relative = os.path.relpath(os.path.join(
                self.session_dir(project, session), "conversations.json"), self.root)
            self._write(relative, records)

    def clear_checkpoints(self, project, session):
        path = os.path.join(self.session_dir(project, session),
                            "conversations.json")
        with self._lock:
            if os.path.exists(path):
                os.unlink(path)

    def erase_session(self, project, session):
        path = self.session_dir(project, session)
        with self._lock:
            if os.path.isdir(path):
                shutil.rmtree(path)

    def archive_project(self, project):
        path = self.project_dir(project)
        with self._lock:
            if os.path.isdir(path):
                os.replace(path, path + REMOVED)

    def erase_project(self, project):
        with self._lock:
            for suffix in ("", REMOVED):
                path = self.project_dir(project) + suffix
                if os.path.isdir(path):
                    shutil.rmtree(path)

    def images_dir(self, project, session):
        return os.path.join(self.session_dir(project, session), "files")

    def save_image(self, project, session, blob, suffix=".png"):
        name = hashlib.sha256(blob).hexdigest()[:16] + suffix
        folder = self.images_dir(project, session)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            with open(path, "wb") as stream:
                stream.write(blob)
        return name

    def image_path(self, project, session, name):
        if not IMAGE_NAME.match(name or ""):
            return None
        path = os.path.join(self.images_dir(project, session), name)
        return path if os.path.exists(path) else None

    def image_paths(self, project, session, message):
        return [path for path in (self.image_path(project, session, name)
                                  for name in message.get("images", [])) if path]

    def storage(self, project, session=None):
        target = self.session_dir(project, session) if session else self.project_dir(project)
        total = 0
        if os.path.isdir(target):
            for folder, _, names in os.walk(target):
                for name in names:
                    try:
                        total += os.path.getsize(os.path.join(folder, name))
                    except OSError:
                        pass
        return total
