from ..domain import EngineConfig, Member, ProjectType, SeatTemplate


class CatalogRepository:
    """Global engine, member, seat-template and project-type documents."""

    def __init__(self, documents, lock):
        self.documents = documents
        self.lock = lock

    def load(self, default_engines, default_templates, default_types):
        return {
            "engines": [EngineConfig.from_dict(one) for one in
                        self.documents.read("engines.json", default_engines)],
            "members": [Member.from_dict(one) for one in
                        self.documents.read("members.json", [])],
            "seat_templates": [SeatTemplate.from_dict(one) for one in
                               self.documents.read("seat_templates.json",
                                                   default_templates)],
            "project_types": [ProjectType.from_dict(one) for one in
                              self.documents.read("project_types.json",
                                                  default_types)],
        }

    def save_engines(self, sinaxa):
        with self.lock:
            self.documents.write(
                "engines.json", [item.as_dict() for item in sinaxa.engines])

    def save_members(self, sinaxa):
        with self.lock:
            self.documents.write(
                "members.json", [item.as_dict() for item in sinaxa.members])

    def save_seat_templates(self, sinaxa):
        with self.lock:
            self.documents.write("seat_templates.json", [
                item.as_dict() for item in sinaxa.seat_templates])

    def save_project_types(self, sinaxa):
        with self.lock:
            self.documents.write("project_types.json", [
                item.as_dict() for item in sinaxa.project_types])
