"""Compatibility facade composing the filesystem persistence adapters.

Callers keep one stable repository surface while each storage concern lives in
its own class. The persisted layout and JSON formats remain unchanged.
"""

import hashlib
import threading
import time

from .domain import SeatTemplate, Sinaxa
from .persistence import (AgentContextRepository, AttachmentStore,
                          CatalogRepository, JsonDocuments, ProjectRepository,
                          StatePaths, TranscriptRepository)

SCHEMA_VERSION = 6
REMOVED = ".removed"


class Store:
    """Persistence facade and transaction boundary for application services."""

    def __init__(self, root):
        self._lock = threading.RLock()
        self.paths = StatePaths(root)
        self.root = self.paths.root
        self.projects_dir = self.paths.projects
        self.documents = JsonDocuments(self.paths, self._lock)
        self.catalog = CatalogRepository(self.documents, self._lock)
        self.projects = ProjectRepository(
            self.paths, self.documents, self._lock, REMOVED)
        self.attachments = AttachmentStore(self.paths, self._lock)
        self.transcripts = TranscriptRepository(
            self.paths, self.documents, self.attachments, self._lock)
        self.contexts = AgentContextRepository(
            self.paths, self.documents, self._lock)

    def load(self):
        catalog = self.catalog.load(
            self.default_engines(), self.default_seat_templates(),
            self.default_project_types())
        projects = self.projects.load_all()
        migrated = False
        by_role = {template.role.casefold(): template
                   for template in catalog["seat_templates"]}
        for project in projects:
            changed = False
            for seat in project.seats:
                if seat.template_id:
                    continue
                template = by_role.get(seat.role.casefold())
                if not template:
                    digest = hashlib.sha1(
                        seat.role.casefold().encode("utf-8")).hexdigest()[:12]
                    template = SeatTemplate(
                        id="stp_" + digest, role=seat.role,
                        prompt=seat.prompt, category="general")
                    catalog["seat_templates"].append(template)
                    by_role[template.role.casefold()] = template
                seat.template_id = template.id
                changed = migrated = True
            for session in project.sessions:
                metrics = self.transcripts.metrics(project, session)
                if (session.unread_count != metrics["unread"]
                        or session.closed_contexts
                        != metrics["closed_contexts"]):
                    session.unread_count = metrics["unread"]
                    session.closed_contexts = metrics["closed_contexts"]
                    changed = migrated = True
            if changed:
                self.projects.save(project)
        if migrated:
            self.documents.write("seat_templates.json", [
                template.as_dict()
                for template in catalog["seat_templates"]])
            self.documents.write("meta.json", {"schema": SCHEMA_VERSION})
        return Sinaxa(projects=projects, **catalog)

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
            {"id": "seat_tester", "role": "Tester", "category": "software",
             "prompt": "Verify behavior, expose risks and report reproducible failures.",
             "default_agent": None},
            {"id": "seat_researcher", "role": "Researcher",
             "category": "general",
             "prompt": "Gather evidence, compare sources and make uncertainty explicit.",
             "default_agent": None},
            {"id": "seat_writer", "role": "Writer", "category": "creative",
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
        return self.documents.read(relative, fallback)

    def _write(self, relative, payload):
        return self.documents.write(relative, payload)

    def save_engines(self, sinaxa):
        return self.catalog.save_engines(sinaxa)

    def save_members(self, sinaxa):
        return self.catalog.save_members(sinaxa)

    def save_seat_templates(self, sinaxa):
        return self.catalog.save_seat_templates(sinaxa)

    def save_project_types(self, sinaxa):
        return self.catalog.save_project_types(sinaxa)

    def save_project(self, project):
        return self.projects.save(project)

    def save_all(self, sinaxa):
        self.save_engines(sinaxa)
        self.save_members(sinaxa)
        self.save_seat_templates(sinaxa)
        self.save_project_types(sinaxa)
        for project in sinaxa.projects:
            self.save_project(project)
        self.documents.write("meta.json", {"schema": SCHEMA_VERSION})

    def project_dir(self, project):
        return self.paths.project(project)

    def session_dir(self, project, session):
        return self.paths.session(project, session)

    def transcript_path(self, project, session):
        return self.paths.transcript(project, session)

    def agent_contexts_path(self, project):
        return self.paths.agent_contexts(project)

    def agent_contexts(self, project):
        return self.contexts.all(project)

    def save_agent_context(self, project, member_id, checkpoint):
        return self.contexts.save(project, member_id, checkpoint)

    def forget_agent_session(self, project, session_id):
        return self.contexts.forget_session(project, session_id)

    def append(self, project, session, message):
        return self.transcripts.append(project, session, message)

    def commit_message(self, project, session, message):
        """Atomically append a message and persist its session metadata."""
        with self._lock:
            session.seq += 1
            now = time.time()
            session.last_activity_at = now
            committed = dict(message, seq=session.seq, ts=now)
            self.transcripts.append(project, session, committed)
            if committed.get("author") not in ("lead", "system"):
                session.unread_count += 1
            self.projects.save(project)
            return committed

    def mark_read(self, project, session, seq):
        """Atomically advance the cursor and retain later unread events."""
        with self._lock:
            session.read_seq = max(
                session.read_seq, min(max(0, int(seq)), session.seq))
            session.unread_count = self.transcripts.metrics(
                project, session)["unread"]
            self.projects.save(project)
            return session.read_seq

    def messages(self, project, session):
        return self.transcripts.messages(project, session)

    def message_page(self, project, session, before=None, after=None,
                     anchor=None, limit=60, search=None):
        return self.transcripts.page(project, session, before=before,
                                     after=after, anchor=anchor, limit=limit,
                                     search=search)

    def session_metrics(self, project, session):
        del project
        return {"unread": session.unread_count,
                "closed_contexts": session.closed_contexts}

    def _scan_session_metrics(self, project, session):
        return self.transcripts.metrics(project, session)

    def clear_history(self, project, session):
        return self.transcripts.clear(project, session)

    @staticmethod
    def is_context_boundary(message):
        return TranscriptRepository.is_context_boundary(message)

    def clear_context_history(self, project, session, boundary_seq=None):
        return self.transcripts.clear_closed(
            project, session, boundary_seq=boundary_seq)

    def checkpoints(self, project, session):
        return self.transcripts.checkpoints(project, session)

    def save_checkpoint(self, project, session, seat_id, checkpoint):
        return self.transcripts.save_checkpoint(
            project, session, seat_id, checkpoint)

    def clear_checkpoints(self, project, session):
        return self.transcripts.clear_checkpoints(project, session)

    def erase_session(self, project, session):
        return self.projects.erase_session(project, session)

    def archive_project(self, project):
        return self.projects.archive(project)

    def erase_project(self, project):
        return self.projects.erase(project)

    def images_dir(self, project, session):
        return self.paths.attachments(project, session)

    def save_image(self, project, session, blob, suffix=".png"):
        return self.attachments.save(project, session, blob, suffix)

    def image_path(self, project, session, name):
        return self.attachments.path(project, session, name)

    def image_paths(self, project, session, message):
        return self.attachments.paths_for(project, session, message)

    def storage(self, project, session=None):
        return self.projects.storage(project, session)
