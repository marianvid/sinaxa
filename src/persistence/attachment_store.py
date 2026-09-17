import hashlib
import os
import re


class AttachmentStore:
    """Content-addressed files owned by one session transcript."""

    NAME = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{2,5}$")

    def __init__(self, paths, lock):
        self.paths = paths
        self.lock = lock

    def save(self, project, session, blob, suffix=".png"):
        name = hashlib.sha256(blob).hexdigest()[:16] + suffix
        folder = self.paths.attachments(project, session)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            with open(path, "wb") as stream:
                stream.write(blob)
        return name

    def path(self, project, session, name):
        if not self.NAME.match(name or ""):
            return None
        path = os.path.join(self.paths.attachments(project, session), name)
        return path if os.path.exists(path) else None

    def paths_for(self, project, session, message):
        return [path for path in (
            self.path(project, session, name)
            for name in message.get("images", [])) if path]

    def remove_orphans(self, project, session, messages):
        folder = self.paths.attachments(project, session)
        if not os.path.isdir(folder):
            return 0
        retained = {name for message in messages
                    for name in message.get("images", [])}
        removed = 0
        for name in os.listdir(folder):
            if name not in retained and self.NAME.match(name):
                os.unlink(os.path.join(folder, name))
                removed += 1
        return removed
