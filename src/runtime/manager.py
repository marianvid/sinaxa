from .project_engines import ProjectEngines


class RuntimeManager:
    """Lazily owns one independent engine set per logically open project."""

    def __init__(self, sinaxa, factory=None):
        self.sinaxa = sinaxa
        self.factory = factory
        self._projects = {}

    def for_project(self, project, checkpoint=None):
        if not project.is_open:
            raise RuntimeError("project is closed")
        if project.id not in self._projects:
            if self.factory:
                runtime = self.factory(project)
            else:
                index = sorted(project.id for project in
                               self.sinaxa.projects).index(project.id)
                runtime = ProjectEngines(project, self.sinaxa.engines,
                                         port_offset=index,
                                         checkpoint=checkpoint)
            self._projects[project.id] = runtime
        return self._projects[project.id]

    def close(self, project_id):
        runtime = self._projects.pop(project_id, None)
        if runtime:
            runtime.stop()

    def status(self, project_id):
        runtime = self._projects.get(project_id)
        return runtime.status() if runtime else []

    def stop(self):
        for project_id in list(self._projects):
            self.close(project_id)
