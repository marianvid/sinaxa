from ..runtime import describe


class ReadModel:
    """Builds HTTP-facing projections without mutating application state."""

    def __init__(self, sinaxa, store, runtimes, talks):
        self.sinaxa = sinaxa
        self.store = store
        self.runtimes = runtimes
        self.talks = talks

    def state(self, project_id=None, session_id=None, search=None,
              before=None, after=None, anchor=None, limit=60):
        projects = [self._project(project) for project in self.sinaxa.projects]
        out = {"engines": [describe(item) for item in self.sinaxa.engines],
               "members": [item.as_dict() for item in self.sinaxa.members],
               "seat_templates": [item.as_dict()
                                  for item in self.sinaxa.seat_templates],
               "project_types": [item.as_dict()
                                 for item in self.sinaxa.project_types],
               "projects": projects,
               "lead": (self.sinaxa.lead.as_dict()
                        if self.sinaxa.lead else None)}
        if not self.sinaxa.projects:
            return out
        project = (self.sinaxa.project(project_id) if project_id
                   else self.sinaxa.projects[0])
        session = (project.session(session_id) if session_id
                   else project.team_session)
        page = self.store.message_page(
            project, session, before=before, after=after, anchor=anchor,
            limit=limit, search=search)
        talk = self.talks.get((project.id, session.id))
        out.update({"project": project.id, "session": session.id,
                    "seats": [dict(
                        seat.as_dict(),
                        name=self.sinaxa.seat_name(project, seat),
                        trouble=self.sinaxa.seat_trouble(project, seat))
                        for seat in project.seats],
                    "messages": page["messages"],
                    "message_page": {key: value
                                     for key, value in page.items()
                                     if key != "messages"},
                    "status": talk.status() if talk else {
                        "busy": [], "agents": [],
                        "engines": self.runtimes.status(project.id)}})
        return out

    def _project(self, project):
        return {"id": project.id, "name": project.name,
                "cwd": project.cwd, "state": project.state,
                "type_id": project.type_id,
                "storage": self.store.storage(project),
                "sessions": [dict(
                    session.as_dict(),
                    storage=self.store.storage(project, session),
                    **self.store.session_metrics(project, session))
                    for session in project.sessions]}
