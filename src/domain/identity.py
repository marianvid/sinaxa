import uuid


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:12])
