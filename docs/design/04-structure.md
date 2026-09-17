# Architecture

Dependency direction is inward:

```text
UI pages -> HTTP adapter -> App composition root
                           ├── domain/
                           ├── Store
                           ├── Talk -> conversation state
                           └── runtime/ -> engines/ provider adapters
```

`domain/` contains invariants and no I/O. Each entity or aggregate has its own
module. `model.py` is only a compatibility facade for older imports.
`store.py` owns atomic JSON,
append-only JSONL, attachments, storage accounting and destructive operations
scoped to its state root. `talk.py` owns visibility projection, mentions and
turn propagation, including concurrent fan-out and per-agent pending mailboxes.
`runtime/` owns project isolation and concurrency policy. `engines/` contains
only provider-specific process/protocol adapters; every Backend, Agent and
native Session is isolated in its own module. `ports/` documents the structural
contracts between these layers. `server.py` only parses/serializes requests.
Long turns run in an executor, outside HTTP request threads, and return an
accepted job immediately.

The deliberately small compatibility facades are `model.py` and
`engines/__init__.py`. They let existing integrations survive file moves but
are not imported by new internal code. Constants, helper functions and related
exception types may share a module; primary stateful classes do not.

This maps directly to a future Rust layout: `domain` becomes plain structs and
invariant methods, `ports` become traits, `runtime` and `engines` become trait
implementations, and `App` remains the composition root. Persistence formats
and HTTP payloads are kept outside the domain so they can survive that rewrite.

The web UI is physically split into Chats, Agents, Seat Templates, Project
Types, Engines and Settings; each page owns its HTML, CSS and JavaScript.
Project selection renders the managed Team session. Clicking one of its
members opens the managed direct session for that seat; the human lead's direct
session acts as personal notes. User-created sessions remain explicit groups.

## Transcript and context

Each session transcript is append-only and together they are the durable source
of truth. The live native context is project-member scoped. Per-session inbox
cursors record which visible events that agent already received, so normal
turns append only unseen deltas and preserve provider caching.

Clearing context does not delete history: it advances that session's context
boundary, resets affected native project-member contexts and appends a visible
boundary event. Detectable native CLI compactions are also appended as
transcript events but do not change Sinaxa's session boundary.

Closed transcript epochs may later be deleted individually from their boundary
or together from session management. Rewrites are atomic, sequence identifiers
remain stable, and attachment cleanup removes only files no longer referenced
by a retained message. The active epoch is never included in this cleanup.

The browser normally requests the latest transcript window. When an unread
session opens, it instead requests a window anchored at the durable human read
cursor: the last read message is shown first, older pages remain available
above it, and newer pages are fetched while the user scrolls toward the end.
Only reaching the newest message while that session and the application are in
focus advances the cursor and clears its unread marker. Search is applied
before paging and never advances the cursor. This keeps long conversations
usable without changing their durable history.

## Disk layout

```text
state/
├── meta.json
├── engines.json
├── members.json
├── seat_templates.json
├── project_types.json
└── projects/<project-id>/
    ├── project.json
    ├── agent_contexts.json
    └── sessions/<session-id>/
        ├── messages.jsonl
        └── files/
```

JSON writes use a temporary sibling, `fsync`, then atomic replacement. Deleting
a session/project touches only generated IDs below this root. Sinaxa never
deletes a provider's global history.
