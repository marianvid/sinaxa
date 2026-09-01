#!/usr/bin/env python3
"""Will each engine take an image, and in what shape?

    python3 tools/probe_images.py

Draws a yellow circle on a blue square -- something a model can only
describe if it actually looked -- and offers it to all three, each in the
forms its protocol might plausibly accept. What came back, on codex 0.144.5
and opencode 1.18.15:

    claude    base64 block in the stream-json envelope   -> described it
    codex     {"type":"localImage","path":"/abs/path"}    -> described it
              {"type":"image","imageUrl":"data:..."}      -> missing field `url`
              {"type":"image","path":"..."}               -> missing field `url`
    opencode  prompt.files[{"uri":"data:image/png;base64,..."}] -> reaches
              the provider; a bare path or a file:// uri is taken by the
              endpoint and then dies inside opencode with "media must
              contain valid base64", which reaches you as no answer at all

So codex decides the design: an image has to be a file on disk, because that
is the only way codex will take one.
"""

import base64
import json
import os
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zlib

SHOT = "/tmp/sinaxa-probe.png"
ASK = "What shape and colours are in this image? One short line."


def draw(path=SHOT, size=220):
    """A yellow circle on a blue square, written by hand: no dependencies."""
    rows = bytearray()
    middle = size // 2
    radius = int(size * 0.32)
    for y in range(size):
        rows.append(0)
        for x in range(size):
            dx, dy = x - middle, y - middle
            inside = dx * dx + dy * dy < radius * radius
            rows += bytes((255, 215, 0) if inside else (20, 40, 160))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n"
                 + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
                 + chunk(b"IEND", b""))
    return path


# ---------------------------------------------------------------- claude
def claude(path):
    data = base64.b64encode(open(path, "rb").read()).decode()
    proc = subprocess.Popen(
        ["claude", "-p", "--input-format", "stream-json",
         "--output-format", "stream-json", "--verbose", "--model", "haiku"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd="/tmp")
    proc.stdin.write(json.dumps({"type": "user", "message": {
        "role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                                         "media_type": "image/png",
                                         "data": data}},
            {"type": "text", "text": ASK}]}}) + "\n")
    proc.stdin.flush()
    answer = "no answer"
    started = time.time()
    for line in proc.stdout:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if message.get("type") == "result":
            answer = str(message.get("result"))[:120]
            break
        if time.time() - started > 180:
            break
    proc.kill()
    print("claude    base64 block          -> %s" % answer, flush=True)


# ----------------------------------------------------------------- codex
def codex(path):
    proc = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, bufsize=1, cwd="/tmp")
    seen, deltas = [], []

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def read():
        for line in proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            seen.append(message)
            if "delta" in (message.get("method") or "").lower():
                deltas.append((message.get("params") or {}).get("delta", ""))

    threading.Thread(target=read, daemon=True).start()
    send({"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "probe", "title": "probe", "version": "0"}}})
    time.sleep(1.5)
    send({"method": "initialized", "params": {}})
    time.sleep(0.5)
    send({"id": 2, "method": "thread/start", "params": {"cwd": "/tmp"}})
    time.sleep(3)
    thread = [m for m in seen if m.get("id") == 2][0]["result"]["thread"]["id"]

    blob = base64.b64encode(open(path, "rb").read()).decode()
    shapes = [("localImage path", {"type": "localImage", "path": path}),
              ("image data url", {"type": "image",
                                  "imageUrl": "data:image/png;base64," + blob}),
              ("image path", {"type": "image", "path": path})]
    for index, (name, item) in enumerate(shapes):
        deltas.clear()
        rid = 100 + index
        send({"id": rid, "method": "turn/start", "params": {
            "threadId": thread, "input": [item, {"type": "text", "text": ASK}]}})
        deadline = time.time() + 90
        while time.time() < deadline:
            time.sleep(1)
            reply = [m for m in seen if m.get("id") == rid]
            if reply and "error" in reply[0]:
                print("codex     %-21s -> REFUSED: %s"
                      % (name, reply[0]["error"].get("message")), flush=True)
                break
            if "".join(deltas).strip():
                print("codex     %-21s -> %s"
                      % (name, "".join(deltas).strip()[:100]), flush=True)
                break
        else:
            print("codex     %-21s -> no answer in 90s" % name, flush=True)
    proc.kill()


# -------------------------------------------------------------- opencode
def opencode(path, port=4096, model=None):
    base = "http://127.0.0.1:%d" % port

    def call(where, body=None, timeout=120):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + where, data,
                                         {"Content-Type": "application/json"})
        raw = urllib.request.urlopen(request, timeout=timeout).read()
        return json.loads(raw) if raw.strip() else None

    payload = {}
    if model:
        provider, _, ident = model.partition("/")
        payload["model"] = {"providerID": provider, "id": ident}
    created = call("/api/session", payload)
    sid = (created.get("data") or created)["id"]

    blob = base64.b64encode(open(path, "rb").read()).decode()
    for name, files in (("data: uri", [{"uri": "data:image/png;base64," + blob,
                                        "name": "probe.png"}]),
                        ("file:// uri", [{"uri": "file://" + path,
                                          "name": "probe.png"}]),
                        ("bare path", [{"uri": path, "name": "probe.png"}])):
        before = len(call("/api/session/%s/message" % sid)["data"])
        try:
            call("/api/session/%s/prompt" % sid,
                 {"prompt": {"text": ASK, "files": files}}, timeout=30)
        except Exception as exc:
            print("opencode  %-21s -> REFUSED: %s" % (name, exc), flush=True)
            continue
        deadline = time.time() + 180
        while time.time() < deadline:
            time.sleep(3)
            seen = call("/api/session/%s/message" % sid)["data"]
            if len(seen) > before and seen[0].get("type") == "assistant" \
                    and seen[0].get("finish"):
                text = " ".join(c.get("text", "") for c in seen[0]["content"]
                                if c.get("type") == "text").strip()
                print("opencode  %-21s -> %s"
                      % (name, text[:100] or "(empty: a model without vision?)"),
                      flush=True)
                break
        else:
            print("opencode  %-21s -> no answer" % name, flush=True)


def main():
    path = draw()
    print("a yellow circle on a blue square: %s\n" % path, flush=True)
    which = sys.argv[1:] or ["claude", "codex", "opencode"]
    if "claude" in which:
        claude(path)
    if "codex" in which:
        codex(path)
    if "opencode" in which:
        model = os.environ.get("SINAXA_OPENCODE_MODEL")
        try:
            opencode(path, model=model)
        except Exception as exc:
            print("opencode  not reachable: %s "
                  "(start it with `opencode serve --port 4096`)" % exc)


if __name__ == "__main__":
    main()
