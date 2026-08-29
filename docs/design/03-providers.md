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
### codex mcp-server — measured too (tools/probe_codex_mcp.py)

    tools: codex, codex-reply
    codex args: approval-policy, base-instructions, compact-prompt, config,
                cwd, developer-instructions, model, prompt, sandbox

    turn 1 (3.8s) -> "ok"      conversationId 01a04fce-f12d-7812-98c7-08aada7bd197
    turn 2 (1.6s) -> "PELICAN"
    one process, context intact, nothing resent

|                        | mcp-server            | app-server              |
|------------------------|-----------------------|-------------------------|
| contract               | standard MCP          | own protocol, experimental |
| answer                 | one call, final text  | deltas + turn/completed |
| "is typing"            | no                    | yes                     |
| recovery after a death | no resume tool        | thread/resume           |
| approvals              | `approval-policy` arg | events you must handle  |
| system prompt          | `base-instructions`   | via config              |

Leaning to mcp-server first:
- `approval-policy: never` removes the blocked-approval trap for free
- `model` + `sandbox` + `base-instructions` map one-to-one onto a member
  definition, no translation
- it is a standard contract, not an experimental one

What it costs: no streaming, and no cheap recovery — if the process dies the
conversation is gone and we replay from the room. Which is the safety net by
design anyway.

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
