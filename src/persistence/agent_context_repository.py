class AgentContextRepository:
    """Native provider session ids and per-Sinaxa-session delivery cursors."""

    def __init__(self, paths, documents, lock):
        self.paths = paths
        self.documents = documents
        self.lock = lock

    def all(self, project):
        return self.documents.read(
            self.paths.relative(self.paths.agent_contexts(project)), {})

    def save(self, project, member_id, checkpoint):
        with self.lock:
            records = self.all(project)
            if checkpoint:
                records[member_id] = checkpoint
            else:
                records.pop(member_id, None)
            self.documents.write(
                self.paths.relative(self.paths.agent_contexts(project)),
                records)

    def forget_session(self, project, session_id):
        with self.lock:
            records = self.all(project)
            changed = False
            for checkpoint in records.values():
                delivered = checkpoint.get("delivered") or {}
                if session_id in delivered:
                    delivered.pop(session_id, None)
                    changed = True
            if changed:
                self.documents.write(
                    self.paths.relative(self.paths.agent_contexts(project)),
                    records)
