import json
import os
import tempfile


class JsonDocuments:
    """Atomic JSON documents below one state root."""

    def __init__(self, paths, lock):
        self.paths = paths
        self.lock = lock

    def read(self, relative, fallback=None):
        path = os.path.join(self.paths.root, relative)
        if not os.path.exists(path):
            return fallback
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)

    def write(self, relative, payload):
        path = os.path.join(self.paths.root, relative)
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".sinaxa-", dir=folder)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
