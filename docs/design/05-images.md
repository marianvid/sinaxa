# Pasting an image into a room

Paste a screenshot into the composer and it goes to the room like anything
else: a thumbnail waits above the box, the message carries it, and the seats
that were asked look at it.

## What each engine will take

Measured, not assumed. `tools/probe_images.py` draws a yellow circle on a
blue square -- something a model can only describe if it actually looked --
and offers it to all three in every plausible shape.

| engine | the shape that works | measured |
|---|---|---|
| claude | a base64 block in the stream-json envelope | described it |
| codex | `{"type":"localImage","path":"/abs/path"}` | described it |
| opencode | `prompt.files[{"uri":"data:image/png;base64,…"}]` | reached the provider |

And the shapes that do not, which is the more useful half:

```
codex     {"type":"image","imageUrl":"data:…"}   -> missing field `url`
codex     {"type":"image","path":"/abs/path"}    -> missing field `url`
opencode  {"uri":"file:///abs/path"}             -> accepted by the endpoint,
opencode  {"uri":"/abs/path"}                       then dies inside opencode
                                                    with "OpenAI Chat media
                                                    must contain valid base64"
```

Both opencode failures are the bad kind: the request is accepted, nothing
errors where you can see it, and the turn simply never produces an answer.
The reason is only in `~/.local/share/opencode/log`.

**codex decides the design.** It will not take an image any way but as a
file on disk, so a file on disk is what everything gets, and the other two
read that file when they need it.

## Where they live

```
projects/<id>/sessions/<id>/files/<sha256[:16]>.png
```

Named by the hash of their own bytes, so pasting the same screenshot twice
stores it once and both messages point at the same file. The transcript line
carries only the names:

```json
{"seq": 12, "author": "lead", "text": "what is this?",
 "images": ["76a2227c29731c47.png"]}
```

An image is part of the transcript, so it lives beside it and goes when the
session goes. The name is checked against `^[0-9a-f]{16}\.[a-z0-9]{2,5}$`
before it is joined to a path: it arrives over HTTP.

Nothing is resized. A screenshot is pasted to be read, and shrinking it to
save tokens is the kind of help that loses the line of code you were
pointing at. The limit is 24 MB, and over it you get a sentence saying so.

## Catching up

A seat that was not addressed is caught up on its next turn, and **the
images come with it**. A picture referred to but never shown is worse than
no picture at all.

Every message says in its text whether it had one, so the model can tell
which picture belongs to which line:

```
[main - Marian] what do you make of this?  [1 image attached]
```

## A seat that cannot see

It is not given the image. It is told there was one:

```
[main - Marian] what do you make of this?  [1 image here, which you cannot read]
```

so it answers "I cannot see it" rather than answering as though the picture
had gone missing by accident. Its reply is marked `meta.blind`, and the
interface puts a small tag on that answer.

Today all three adapters declare `accepts_images = True`; whether the model
behind opencode reads it is the model's business. On the AI-Lab box,
`llama-gemma-31b` is a multimodal model served without its vision projector,
and llama.cpp says so plainly:

```
HTTP 500: image input is not supported -- hint: if this is unexpected, you
may need to provide the mmproj
```

That is a box configuration, not a sinaxa one.
