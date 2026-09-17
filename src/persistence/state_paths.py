import os


class StatePaths:
    """Owns the on-disk layout without performing I/O."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.projects = os.path.join(self.root, "projects")

    def project(self, project):
        return os.path.join(self.projects, project.id)

    def session(self, project, session):
        return os.path.join(self.project(project), "sessions", session.id)

    def transcript(self, project, session):
        return os.path.join(self.session(project, session), "messages.jsonl")

    def agent_contexts(self, project):
        return os.path.join(self.project(project), "agent_contexts.json")

    def checkpoints(self, project, session):
        return os.path.join(self.session(project, session),
                            "conversations.json")

    def attachments(self, project, session):
        return os.path.join(self.session(project, session), "files")

    def relative(self, path):
        return os.path.relpath(path, self.root)
