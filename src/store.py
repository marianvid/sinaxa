"""Disk.

    state/
      members.json                        defined once
      seats.json                          defined once
      projects/<prj_id>/project.json
                        sessions/<ses_id>/session.json
                                          rooms/<room_id>.jsonl

Folders are named by generated id, names live inside the JSON, so renaming a
project or a room moves nothing and breaks no link.

Configuration is JSON, rewritten whole -- it is small and it is edited.
Transcripts are JSONL, only ever appended -- they are large and they are
history. Every message carries a session-wide `seq`, so the rooms of one
session can be merged back into the single order in which things were said.
"""

import hashlib
import json
import os
import re
import shutil

from .model import Member, Project, SeatDef, Session, Sinaxa

REMOVED = ".removed"      # a project taken out of the picture, kept on disk
IMAGE_NAME = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{2,5}$")


class Store:
    def __init__(self, root):
        self.root = root
        self.projects_dir = os.path.join(root, "projects")

    # ----------------------------------------------------------- reading
    def load(self):
        sinaxa = Sinaxa(
            members=[Member.from_dict(r) for r in self._read("members.json", [])],
            seat_defs=[SeatDef.from_dict(r) for r in self._read("seats.json", [])])
        if os.path.isdir(self.projects_dir):
            for project_id in sorted(os.listdir(self.projects_dir)):
                if project_id.endswith(REMOVED):
                    continue          # taken out of the picture, kept on disk
                project = self._load_project(project_id)
                if project:
                    sinaxa.projects.append(project)
        return sinaxa

    def _load_project(self, project_id):
        raw = self._read(os.path.join("projects", project_id, "project.json"))
        if not raw:
            return None
        project = Project(raw["name"], id=raw["id"], cwd=raw.get("cwd"))
        sessions_dir = os.path.join(self.projects_dir, project_id, "sessions")
        if os.path.isdir(sessions_dir):
            for session_id in sorted(os.listdir(sessions_dir)):
                path = os.path.join(sessions_dir, session_id, "session.json")
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as fh:
                        project.sessions.append(Session.from_dict(json.load(fh)))
        return project

    def _read(self, relative, fallback=None):
        path = os.path.join(self.root, relative)
        if not os.path.exists(path):
            return fallback
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # ----------------------------------------------------------- writing
    def _write(self, relative, payload):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def save_members(self, sinaxa):
        self._write("members.json", [m.as_dict() for m in sinaxa.members])

    def save_seat_defs(self, sinaxa):
        self._write("seats.json", [d.as_dict() for d in sinaxa.seat_defs])

    def save_project(self, project):
        self._write(os.path.join("projects", project.id, "project.json"),
                    project.as_dict())
        for session in project.sessions:
            self.save_session(project, session)

    def save_session(self, project, session):
        self._write(os.path.join("projects", project.id, "sessions",
                                 session.id, "session.json"),
                    session.as_dict())

    def save_all(self, sinaxa):
        self.save_members(sinaxa)
        self.save_seat_defs(sinaxa)
        for project in sinaxa.projects:
            self.save_project(project)

    # ---------------------------------------------------------- removing
    def forget_project(self, project):
        """Take the project out of the picture but leave its history alone."""
        path = os.path.join(self.projects_dir, project.id)
        if os.path.isdir(path):
            os.rename(path, path + REMOVED)

    def erase_project(self, project):
        """Take it off the disk, transcripts and all. There is no undo."""
        for suffix in ("", REMOVED):
            path = os.path.join(self.projects_dir, project.id + suffix)
            if os.path.isdir(path):
                shutil.rmtree(path)

    def erase_session(self, project, session):
        path = os.path.join(self.projects_dir, project.id, "sessions",
                            session.id)
        if os.path.isdir(path):
            shutil.rmtree(path)

    def erase_room(self, project, session, room):
        path = self.room_path(project, session, room)
        if os.path.exists(path):
            os.remove(path)

    # ------------------------------------------------------------ images
    # An image pasted into a room is part of the transcript, so it lives
    # beside it. Named by the hash of its own bytes: paste the same
    # screenshot twice and it is stored once. codex will not take an image
    # any other way than as a file on disk, so a file is what everything
    # gets.
    def images_dir(self, project, session):
        return os.path.join(self.projects_dir, project.id, "sessions",
                            session.id, "files")

    def save_image(self, project, session, blob, suffix=".png"):
        name = hashlib.sha256(blob).hexdigest()[:16] + suffix
        folder = self.images_dir(project, session)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(blob)
        return name

    def image_path(self, project, session, name):
        """The path of one stored image, or None. The name is checked rather
        than trusted: it arrives over HTTP."""
        if not IMAGE_NAME.match(name or ""):
            return None
        path = os.path.join(self.images_dir(project, session), name)
        return path if os.path.exists(path) else None

    def image_paths(self, project, session, message):
        found = []
        for name in message.get("images") or []:
            path = self.image_path(project, session, name)
            if path:
                found.append(path)
        return found

    # ------------------------------------------------------- transcripts
    def room_path(self, project, session, room):
        return os.path.join(self.projects_dir, project.id, "sessions",
                            session.id, "rooms", room.id + ".jsonl")

    def append(self, project, session, room, message):
        path = self.room_path(project, session, room)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(message, ensure_ascii=False) + "\n")
        return message

    def messages(self, project, session, room):
        path = self.room_path(project, session, room)
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def session_messages(self, project, session, rooms=None):
        """Every message of the given rooms, back in the order they were
        said. This is what a seat's context is built from: pass it the rooms
        that seat belongs to and it sees exactly what it is allowed to."""
        wanted = rooms if rooms is not None else session.rooms
        merged = []
        for room in wanted:
            merged.extend(self.messages(project, session, room))
        merged.sort(key=lambda m: m.get("seq", 0))
        return merged
