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
scoped to its state root. `talk.py` owns context projection, mentions and turn
propagation, including concurrent fan-out and per-seat pending mailboxes.
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

The transcript is append-only and is the source of truth. Clearing context
does not delete history: it advances the context boundary, clears disposable
native checkpoints and appends a visible boundary event. Detectable native CLI
compactions are also appended as transcript events but do not change Sinaxa's
session-wide context boundary.

The browser initially requests the latest transcript window and requests older
pages when the user scrolls to the top. Search is applied before paging. This
keeps long conversations usable without changing their durable history.

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
    └── sessions/<session-id>/
        ├── messages.jsonl
        ├── conversations.json
        └── files/
```

JSON writes use a temporary sibling, `fsync`, then atomic replacement. Deleting
a session/project touches only generated IDs below this root. Sinaxa never
deletes a provider's global history.
