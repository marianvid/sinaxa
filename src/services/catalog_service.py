from ..domain import EngineConfig, ModelError


class CatalogService:
    """Use-cases for engines, members, reusable seats and project types."""

    def __init__(self, sinaxa, store, runtimes, lock,
                 engine_changed, member_changed):
        self.sinaxa = sinaxa
        self.store = store
        self.runtimes = runtimes
        self.lock = lock
        self.engine_changed = engine_changed
        self.member_changed = member_changed

    def update_engine(self, engine_id, **fields):
        with self.lock:
            engine = self.sinaxa.engine(engine_id)
            allowed = {"name", "enabled", "executable", "mode", "streaming",
                       "max_concurrency", "mcp_servers", "options"}
            candidate = engine.as_dict()
            candidate.update({key: value for key, value in fields.items()
                              if key in allowed})
            if candidate.get("mode") != "persistent":
                raise ModelError(
                    "non-persistent engine mode is not yet implemented")
            replacement = EngineConfig.from_dict(candidate)
            self.sinaxa.engines[self.sinaxa.engines.index(engine)] = replacement
            self.store.save_engines(self.sinaxa)
            self.engine_changed()
            return replacement

    def models_for(self, engine_id, project_id=None):
        engine = self.sinaxa.engine(engine_id)
        project = (self.sinaxa.project(project_id) if project_id else
                   next((item for item in self.sinaxa.projects
                         if item.is_open), None))
        if not project:
            return []
        return self.runtimes.for_project(project).models_for(engine.id)

    def add_member(self, **fields):
        with self.lock:
            member = self.sinaxa.add_member(**fields)
            self.store.save_members(self.sinaxa)
            return member

    def update_member(self, member_id, **fields):
        with self.lock:
            member = self.sinaxa.update_member(member_id, **fields)
            self.store.save_members(self.sinaxa)
            self.member_changed(member_id)
            return member

    def remove_member(self, member_id):
        with self.lock:
            member = self.sinaxa.remove_member(member_id)
            self.store.save_members(self.sinaxa)
            return member

    def add_seat_template(self, **fields):
        with self.lock:
            template = self.sinaxa.add_seat_template(**fields)
            self.store.save_seat_templates(self.sinaxa)
            return template

    def update_seat_template(self, template_id, **fields):
        with self.lock:
            template = self.sinaxa.update_seat_template(template_id, **fields)
            self.store.save_seat_templates(self.sinaxa)
            return template

    def remove_seat_template(self, template_id):
        with self.lock:
            template = self.sinaxa.remove_seat_template(template_id)
            self.store.save_seat_templates(self.sinaxa)
            return template

    def add_project_type(self, **fields):
        with self.lock:
            project_type = self.sinaxa.add_project_type(**fields)
            self.store.save_project_types(self.sinaxa)
            return project_type

    def update_project_type(self, type_id, **fields):
        with self.lock:
            project_type = self.sinaxa.update_project_type(type_id, **fields)
            self.store.save_project_types(self.sinaxa)
            return project_type

    def remove_project_type(self, type_id):
        with self.lock:
            project_type = self.sinaxa.remove_project_type(type_id)
            self.store.save_project_types(self.sinaxa)
            return project_type
