# The structure

```
Sinaxa
 |- members[]     Member    an engine plus a model: how an occupant starts
 |- seat_defs[]   SeatDef   a role plus its default prompt
 +- projects[]    Project
      +- sessions[]  Session    seats live here; the prompt is overridden here
           |- seats[]  Seat     a role, taken by a member, inside one session
           +- rooms[]  Room     a grouping of seats, nothing more
```

Six classes in `src/model.py`. None of them knows about Claude, Codex,
opencode or any person: they hold lists. Talking to a provider is
`src/engines/`, disk is `src/store.py`, turn-taking is `src/talk.py`, the
actions the interface can take are `src/app.py`, and HTTP is
`src/server.py`.

## Two prompts, not three

```
SeatDef.prompt    the role's default, defined once for all of sinaxa
      v  overridden in
Seat.prompt       this session's version of that role
```

A room does not override anything. A room decides who is in the
conversation, and that is all it decides.

`Seat.prompt` is `None` when the role's default applies. An empty string is
an override that says nothing -- blanking a prompt means blank, not "go back
to the default". Going back is a separate action.

## Seats

A seat exists because somebody occupies it; there is no empty seat. What can
happen is that an occupant goes **missing** -- the member deleted, its binary
moved, its model gone from opencode's config. The seat then says so, in the
room, and waits to be given another. It does not guess a replacement and it
does not fail silently.

Adding a seat to a session also gives it a private room. Removing the seat
takes that room with it, and takes the seat out of every other room it was
in.

## Rooms

```
all       every seat of the session. Named after the session. Maintained
          by sinaxa: it cannot be edited or removed, so "who is in the team
          room" is never a second answer to "who is in the team".
private   one seat. Created and removed with it.
custom    yours. Any selection of seats; seats go in and out; remove it and
          the seats stay.
```

The lead is in every room and is not a seat. There is nothing to start and
nothing to instruct: it is you.

## Context

One rule:

> a seat sees every message of every room it belongs to

Everything else follows. The common room reaches everyone in it. A private
room reaches its two. A room made from a selection reaches that selection.
No further rule is needed, and none exists in the code.

A seat is therefore **one conversation per session**, not one per room --
the same colleague, the same memory, several rooms. Because it reads several
rooms, every message is delivered saying where it was said:

```
[main - Marian] status please
[architect - Marian] between us, the build is broken
```

Messages reach a seat when it is asked something, not when they are written.
A seat nobody addressed accumulates what it has not seen and is caught up on
its next turn, so silence costs nothing. `seq` -- a number given to every
message, session-wide -- is what makes "what did I miss" answerable across
several rooms.

Clearing a seat's context stops its agent and forgets `delivered`. The
transcript is untouched, so the next turn rebuilds the context from the
rooms. Changing a seat's prompt or its occupant does the same thing on
purpose: the prompt is only ever sent at the first turn, so an agent kept
alive would never read the new one.

## Cost

```
conversations = occupied seats x open sessions
```

For claude that is the same number of processes, around 430 MB each; codex
and opencode share one. Measured figures are in `03-providers.md`.

## Members

A member is how an occupant is started, not what it is told. The form
differs per engine, and each engine describes its own
(`src/engines/__init__.py`):

| | claude | codex | opencode |
|---|---|---|---|
| model | four aliases, or a full name typed in | typed in | **chosen from what opencode declares** |
| effort | a flag, so per seat | a config key read at process start, so the same for every codex seat -- medium for now | a property of the model, set in opencode |
| binary | yes | yes | yes |

sinaxa does not configure opencode. It asks what opencode has and lets you
choose among it.

## On disk

```
state/
  members.json                         defined once
  seats.json                           defined once
  projects/<prj_id>/project.json
                    sessions/<ses_id>/session.json    seats, occupants, prompts
                                      rooms/<room_id>.jsonl
```

Folders are named by generated id and names live inside the JSON, so
renaming a project, a session or a room moves nothing and breaks no link.

Configuration is JSON, rewritten whole: it is small, and it is edited.
Transcripts are JSONL, only ever appended: they are large, and they are
history.

Removing a project takes it out of the picture and renames its folder to
`<id>.removed`, keeping the history. Removing it *from disk* is a separate
choice, and there is no undo. Sessions and rooms offer the same choice.

## Views

```
Projects   the tree: projects -> sessions -> rooms, and the room itself
Members    the definitions: name, engine, model, effort, binary
Seats      the roles: role, default prompt, default member
           and what is live: occupant, turns, tokens, trouble
```

Manage session is where a session's seats are dealt with: who occupies them,
what their prompt is here, clear one context, remove a seat, add one.

There is no Settings view yet, deliberately: we do not know what belongs in
it.
