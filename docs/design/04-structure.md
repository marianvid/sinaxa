# Architecture

Dependency direction is inward:

```text
UI pages -> HTTP adapter -> App facade
                           ├── domain model
                           ├── Store
                           ├── Talk
                           └── RuntimeManager -> provider adapters
```

`model.py` contains invariants and no I/O. `store.py` owns atomic JSON,
append-only JSONL, attachments, storage accounting and destructive operations
scoped to its state root. `talk.py` owns context projection, mentions and turn
propagation, including concurrent fan-out and per-seat pending mailboxes.
`engines/` owns processes and project isolation. `server.py` only
parses/serializes requests. Long turns run in an executor, outside HTTP request
threads, and return an accepted job immediately.

The web UI is physically split into Chats, Agents, Seat Templates, Project
Types, Engines and Settings; each page owns its HTML, CSS and JavaScript.
Project selection renders concrete seats and offers managed direct/team
sessions plus user-created sessions.

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
