# How each provider holds a conversation

Measured, not assumed. Probe: `tools/probe_codex.py`.

## Claude CLI

One process = one conversation, for the process's lifetime. There is no
session field in the stdin envelope and no server mode. The Agent SDK does
not change this: their hosting docs say "One agent session maps to one
subprocess. Running N concurrent sessions means N subprocesses."

    claude -p --input-format stream-json --output-format stream-json --verbose
           --session-id <uuid>     # first run
           --resume <uuid>         # after a restart or a death

So: N conversations = N processes. Not negotiable.

## Codex CLI

`codex app-server` hosts many threads in ONE process. Verified on this
machine with codex-cli 0.144.5:

    initialize -> initialized -> thread/start -> turn/start -> turn/start

    thread/start  -> 01a04fcd-7feb-75e2-afc6-aa4e2f2ba8f2
    turn 1 (3.5s) -> "ok"
    turn 2 (2.3s) -> "PELICAN"     (asked what it was told to remember)
    one process, still alive, nothing resent

`thread/resume` is only for after the server or the worker restarts.

Caveats:
- `codex app-server` is marked [experimental] in `codex --help`, and the docs
  say "The app-server command and WebSocket transport are experimental and
  aren't supported for production workloads."
- 75 `#[experimental(...)]` annotations in protocol v2.
- The stable documented surface is `codex exec` (+ `--json`, `--output-schema`,
  `-o`) and `codex exec resume`; OpenAI points automation at the Codex SDK.
- `codex mcp-server` is a third path: two tools, `codex` (returns a
  conversationId) and `codex-reply` — a persistent conversation over a
  stabler contract. Verified empirically during agent-bridge.

## Consequence for the design

The adapter interface is "a conversation". Each provider maps it however it
can, and nothing above the adapter knows the difference:

    claude  -> one process
    codex   -> one thread inside a shared app-server

Do not build the architecture around Codex's multiplexing: Claude cannot do
it, so the common denominator is one conversation per member per session.
Codex's ability to share a process is an optimisation inside its adapter.

If app-server is withdrawn, the Codex adapter falls back to `mcp-server`
(persistent) or `exec resume` (a process per message). Nothing else moves.

## Probe hygiene

`probe_codex.py` double-counts the answer (it collects both the deltas and
the final item). Take one or the other in the real client.
