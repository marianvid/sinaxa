import json
import os
import shutil
import tempfile
from collections import deque


class TranscriptRepository:
    """Append-only transcript access, paging and controlled history cleanup."""

    def __init__(self, paths, documents, attachments, lock):
        self.paths = paths
        self.documents = documents
        self.attachments = attachments
        self.lock = lock

    def append(self, project, session, message):
        path = self.paths.transcript(project, session)
        with self.lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(message, ensure_ascii=False) + "\n")
                stream.flush()
        return message

    def messages(self, project, session):
        path = self.paths.transcript(project, session)
        with self.lock:
            if not os.path.exists(path):
                return []
            with open(path, encoding="utf-8") as stream:
                return [json.loads(line) for line in stream if line.strip()]

    def page(self, project, session, before=None, after=None, anchor=None,
             limit=60, search=None):
        path = self.paths.transcript(project, session)
        limit = max(1, min(int(limit), 200))
        before = int(before) if before is not None else None
        after = int(after) if after is not None else None
        anchor = int(anchor) if anchor is not None else None
        wanted = search.casefold() if search else None
        if after is not None or anchor is not None:
            return self._forward_page(path, limit, wanted, after, anchor)
        found = deque(maxlen=limit + 1)
        with self.lock:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        message = json.loads(line)
                        if before is not None and message.get("seq", 0) >= before:
                            continue
                        if wanted and wanted not in message.get(
                                "text", "").casefold():
                            continue
                        found.append(message)
        has_more = len(found) > limit
        if has_more:
            found.popleft()
        messages = list(found)
        return self._page_result(messages, has_more, False, limit)

    def _forward_page(self, path, limit, wanted, after, anchor):
        previous = None
        earlier = 0
        following = []
        with self.lock:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        message = json.loads(line)
                        if wanted and wanted not in message.get(
                                "text", "").casefold():
                            continue
                        seq = message.get("seq", 0)
                        if after is not None:
                            if seq <= after:
                                earlier += 1
                                continue
                        elif seq <= anchor:
                            previous = message
                            earlier += 1
                            continue
                        following.append(message)
                        capacity = limit if previous is None else limit - 1
                        if len(following) > capacity:
                            break
        capacity = limit if previous is None else limit - 1
        messages = ([previous] if previous else []) + following[:capacity]
        return self._page_result(
            messages, bool(earlier - (1 if previous else 0)),
            len(following) > capacity, limit)

    @staticmethod
    def _page_result(messages, has_more, has_newer, limit):
        return {"messages": messages, "has_more": has_more,
                "has_newer": has_newer,
                "oldest_seq": messages[0].get("seq") if messages else None,
                "newest_seq": messages[-1].get("seq") if messages else None,
                "limit": limit}

    @staticmethod
    def is_context_boundary(message):
        return (message.get("kind") == "boundary" and (
            (message.get("meta") or {}).get("boundary") == "context_clear"
            or message.get("text", "").startswith("Context cleared")))

    def metrics(self, project, session):
        messages = self.messages(project, session)
        unread = sum(1 for message in messages
                     if message.get("seq", 0) > session.read_seq
                     and message.get("author") not in ("lead", "system"))
        closed = sum(1 for message in messages
                     if self.is_context_boundary(message))
        return {"unread": unread, "closed_contexts": closed}

    def clear_closed(self, project, session, boundary_seq=None):
        with self.lock:
            messages = self.messages(project, session)
            boundaries = [message.get("seq", 0) for message in messages
                          if self.is_context_boundary(message)]
            if not boundaries:
                return {"removed": 0, "attachments": 0,
                        "removed_contexts": 0, "removed_unread": 0}
            if boundary_seq is None:
                lower, upper = 0, max(boundaries)
            else:
                upper = int(boundary_seq)
                if upper not in boundaries:
                    raise ValueError("no such cleared context section")
                earlier = [seq for seq in boundaries if seq < upper]
                lower = max(earlier) if earlier else 0
            removed = [message for message in messages
                       if lower < message.get("seq", 0) <= upper]
            kept = [message for message in messages
                    if not lower < message.get("seq", 0) <= upper]
            self._replace(project, session, kept)
            orphaned = self.attachments.remove_orphans(
                project, session, kept)
            removed_unread = sum(
                1 for message in removed
                if message.get("seq", 0) > session.read_seq
                and message.get("author") not in ("lead", "system"))
            return {"removed": len(removed), "attachments": orphaned,
                    "removed_contexts": (1 if boundary_seq is not None
                                         else len(boundaries)),
                    "removed_unread": removed_unread}

    def _replace(self, project, session, messages):
        path = self.paths.transcript(project, session)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".sinaxa-", dir=folder)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                for message in messages:
                    stream.write(json.dumps(message, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def checkpoints(self, project, session):
        return self.documents.read(
            self.paths.relative(self.paths.checkpoints(project, session)), {})

    def save_checkpoint(self, project, session, seat_id, checkpoint):
        with self.lock:
            records = self.checkpoints(project, session)
            if checkpoint:
                records[seat_id] = checkpoint
            else:
                records.pop(seat_id, None)
            self.documents.write(
                self.paths.relative(self.paths.checkpoints(project, session)),
                records)

    def clear_checkpoints(self, project, session):
        path = self.paths.checkpoints(project, session)
        with self.lock:
            if os.path.exists(path):
                os.unlink(path)

    def clear(self, project, session):
        with self.lock:
            transcript = self.paths.transcript(project, session)
            if os.path.exists(transcript):
                os.unlink(transcript)
            files = self.paths.attachments(project, session)
            if os.path.isdir(files):
                shutil.rmtree(files)
            self.clear_checkpoints(project, session)
