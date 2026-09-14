# Sinaxa

A local workspace for exploratory conversations with several subscription-
authenticated CLI agents. Sinaxa does not require provider API keys: Claude
Code, Codex and OpenCode run with the login already present on the host.

## Product model

```text
Workspace
├── Engines                 global CLI installation and runtime policy
├── Members                 reusable agent identity + model preferences
└── Projects                working folder + logical open/closed state
    ├── Seats               project role + instructions + occupying member
    └── Sessions            independent transcript and context
        ├── Team            all current seats; managed, never deleted
        ├── Direct          one seat; managed with that seat
        └── Custom          an explicit seat selection
```

`Session` is the only conversation container. There are no rooms. Removing a
seat removes its direct session and history, while team/custom transcripts
remain. Context belongs to `(session, seat)` and native provider IDs are only
restart checkpoints; Sinaxa's transcript remains the source of truth.

## Run

```bash
python -m src.server
```

Open `http://127.0.0.1:8789`. The UI has four independent pages: Projects,
Members, Engines and Settings. Projects owns seat and session management.

## Runtime lifecycle

No provider process starts merely because Sinaxa or a project opens. The first
new message starts a project-local runtime lazily. Codex and OpenCode use one
backend per active project; Claude uses a process per active conversation.
Closing a project waits for its current turn, rejects new messages and stops
everything owned by that project. Application shutdown stops all processes but
does not rewrite the project's logical open/closed state.

## Test

```bash
pytest -q
```

The suite exercises domain invariants, atomic persistence, the HTTP surface,
turn orchestration and all three provider adapters through executable fakes.
