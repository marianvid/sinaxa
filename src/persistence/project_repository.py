import os
import shutil

from ..domain import Project


class ProjectRepository:
    """Project metadata, lifecycle and storage accounting."""

    def __init__(self, paths, documents, lock, removed_suffix=".removed"):
        self.paths = paths
        self.documents = documents
        self.lock = lock
        self.removed_suffix = removed_suffix

    def load_all(self):
        projects = []
        if not os.path.isdir(self.paths.projects):
            return projects
        for project_id in sorted(os.listdir(self.paths.projects)):
            if project_id.endswith(self.removed_suffix):
                continue
            raw = self.documents.read(os.path.join(
                "projects", project_id, "project.json"))
            if raw:
                projects.append(Project.from_dict(raw))
        return projects

    def save(self, project):
        with self.lock:
            self.documents.write(os.path.join(
                "projects", project.id, "project.json"), project.as_dict())

    def archive(self, project):
        path = self.paths.project(project)
        with self.lock:
            if os.path.isdir(path):
                os.replace(path, path + self.removed_suffix)

    def erase(self, project):
        with self.lock:
            for suffix in ("", self.removed_suffix):
                path = self.paths.project(project) + suffix
                if os.path.isdir(path):
                    shutil.rmtree(path)

    def erase_session(self, project, session):
        path = self.paths.session(project, session)
        with self.lock:
            if os.path.isdir(path):
                shutil.rmtree(path)

    def storage(self, project, session=None):
        target = (self.paths.session(project, session) if session
                  else self.paths.project(project))
        total = 0
        if os.path.isdir(target):
            for folder, _, names in os.walk(target):
                for name in names:
                    try:
                        total += os.path.getsize(os.path.join(folder, name))
                    except OSError:
                        pass
        return total
