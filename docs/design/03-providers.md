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

|                          | mcp-server            | app-server                 |
|--------------------------|-----------------------|----------------------------|
| context across turns     | yes                   | yes                        |
| progress during a turn   | yes (`codex/event`)   | yes                        |
| token-by-token text      | **no**                | yes (deltas)               |
| recovery after a restart | **no**                | yes (`thread/resume`)      |
| contract                 | stable                | experimental               |
| approvals                | `approval-policy` arg | events you must handle     |
| system prompt            | `base-instructions`   | via config                 |

An earlier version of this table said mcp-server does not stream. That was
wrong. Measured with tools/probe_codex_mcp_events.py, one turn emits:

    0.7s  session_configured / task_started
    0.7s  mcp_startup_update    node_repl, codex_apps: starting
    1.8s  mcp_startup_complete  ready: [node_repl, codex_apps]
    2.3s  raw_response_item x5
          item_started x2, item_completed x2
          agent_message x1, token_count x1, task_complete

Enough for a live "working…" state, tool-call visibility and a cost meter.
What is missing is per-token deltas: `agent_message` arrives once, at the
end, so the text cannot be rendered as it is written — and a long turn cannot
be read from the start while it finishes.

Streaming and context are independent axes. Streaming is how the answer
arrives; context is what the model remembers. Do not conflate them.

Also measured: 1.8s of every new conversation goes to codex booting its own
MCP servers (node_repl, codex_apps). That is per-conversation overhead.

### Restart recovery — measured (the deciding fact)

    codex-reply in a fresh mcp-server  -> "Session not found for thread_id"
    codex exec resume <id>             -> PELICAN  (3.9s)
    app-server thread/resume, new proc -> PELICAN  (5.3s)

`codex-reply` only looks in its own process's in-memory registry. But the
conversation is an ordinary session on disk
(`~/.codex/sessions/2026/08/30/rollout-*.jsonl`), and `thread/resume` in a
brand new app-server picks it up intact, returning `sessionId`,
`forkedFromId`, `parentThreadId` and a preview.

`mcp-server` is NOT marked experimental in `codex --help` — unlike
`app-server`, `remote-control`, `cloud`, `exec-server`. It is a first-class
subcommand speaking standard MCP (2025-06-18).

So the choice is not simple-vs-complex. It is:

    mcp-server : stable contract, no way back in after a restart
    app-server : experimental contract, cheap recovery and streaming

With mcp-server every application restart costs a full replay from our room,
per Codex member. With app-server we carry the risk of an experimental
protocol moving under us — which the probes in tools/ will detect the moment
it does.

Leaning: app-server, with mcp-server as the fallback if it is withdrawn.
The two cannot be mixed: a thread resumed in app-server cannot be moved back
into mcp-server.

Older note (before the recovery test), kept for the reasoning:
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
