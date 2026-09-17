class ContextAssembler:
    """Projects all unseen, visible project events into one agent turn."""

    def __init__(self, sinaxa, store, project, session):
        self.sinaxa = sinaxa
        self.store = store
        self.project = project
        self.session = session

    def context_for(self, seat, through):
        member = self.sinaxa.member(seat.occupant)
        member_seats = {one.id for one in self.project.seats
                        if one.occupant == member.id}
        checkpoint = self.store.agent_contexts(self.project).get(member.id, {})
        delivered = checkpoint.get("delivered") or {}
        batch = []
        for session in self.project.sessions:
            if not member_seats.intersection(session.participants):
                continue
            cursor = int(delivered.get(session.id, 0))
            for stored in self.store.messages(self.project, session):
                seq = stored.get("seq", 0)
                if seq <= cursor or seq < session.context_start_seq:
                    continue
                if stored.get("kind") in ("boundary", "compaction"):
                    continue
                if session.id == self.session.id and seq > through["seq"]:
                    continue
                if stored.get("ts", 0) > through.get("ts", float("inf")):
                    continue
                message = dict(stored)
                message["_session_id"] = session.id
                message["_session_name"] = (
                    "Main" if session.kind == "team" else session.name)
                message["_visibility"] = (
                    "private" if session.kind == "direct" else
                    "team" if session.kind == "team" else "group")
                batch.append(message)
        return sorted(batch, key=lambda item: (
            item.get("ts", 0), item["_session_id"], item.get("seq", 0)))

    def line(self, message, carried=True):
        count = len(message.get("images", []))
        note = ""
        if count:
            note = " [%d image%s %s]" % (
                count, "" if count == 1 else "s",
                "attached" if carried else "not supported by this engine")
        session_name = message.get("_session_name", self.session.name)
        visibility = message.get("_visibility", "session")
        return "[%s · %s] %s: %s%s" % (
            session_name, visibility, message.get("author_name", "?"),
            message.get("text", ""), note)

    def image_paths(self, batch, carried):
        if not carried:
            return []
        paths = []
        for item in batch:
            source = self.project.session(item["_session_id"])
            paths.extend(self.store.image_paths(self.project, source, item))
        return paths
