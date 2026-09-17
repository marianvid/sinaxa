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
    └── Sessions            transcript and routing views
        ├── Team            all current seats; managed, never deleted
        ├── Direct          one seat; managed with that seat
        └── Custom          an explicit seat selection
```

`Session` is the only visible conversation container. There are no rooms.
Removing a seat removes its direct session and history, while team/custom
transcripts remain. Runtime context belongs to `(project, member)`: one agent
keeps a single native context across Main, direct and custom sessions. Native
provider IDs are restart checkpoints; Sinaxa's transcripts remain the durable
source of truth.

## Run

### From VS Code

Open this repository as the workspace, then use **Run and Debug → Sinaxa: Run
server**. `F5` starts it in the integrated terminal and the red Stop button or
`Shift+F5` stops it cleanly. Because the server stays in the foreground, its
output and any exception remain visible while you inspect the implementation.

Without the debugger, run **Terminal → Run Task… → Sinaxa: Run**. Stop it with
`Ctrl+C` in its dedicated terminal. **Sinaxa: Test** is also available as the
default test task.

### From a terminal

```bash
python -m src.server
```

Open `http://127.0.0.1:8789`. The UI has four independent pages: Projects,
Members, Engines and Settings. Projects owns seat and session management.

## Runtime lifecycle

No provider process starts merely because Sinaxa or a project opens. The first
new message starts a project-local runtime lazily. Codex and OpenCode use one
backend per active project. Each member uses one persistent native agent
context per project; for Claude that means one CLI process per active member.
Closing a project waits for its current turn, rejects new messages and stops
everything owned by that project. Application shutdown stops all processes but
does not rewrite the project's logical open/closed state.

## Test

```bash
pytest -q
```

The suite exercises domain invariants, atomic persistence, the HTTP surface,
turn orchestration and all three provider adapters through executable fakes.
