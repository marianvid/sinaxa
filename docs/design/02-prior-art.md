# Prior art — read before writing the daemon

Nothing found does exactly this, but two projects solve parts of it and
one of them solves the part that cost us the most in agent-bridge.

## awslabs/cli-agent-orchestrator          STUDY THIS ONE
https://github.com/awslabs/cli-agent-orchestrator

Open-source multi-agent orchestration for coding CLIs (Claude Code,
Kiro, Codex, ...). Each agent runs in its own tmux session under a
supervisor/worker pattern. Three MCP primitives: handoff (synchronous),
assign (async, fire-and-forget), send_message (inbox). Local HTTP
server on :9889 routes by terminal id. Bundled web dashboard.
Auth is each CLI's own subscription login, not API keys.

Why it matters to us: they already solved process launch, isolation and
lifecycle for CLI agents — exactly what ate v1. Read it after the
concept is settled, not before.

What it is not: no projects, no rooms, no group conversation. The model
is one boss and N executors, not equal members in a room.

## xintaofei/codeg
https://github.com/xintaofei/codeg

Aggregates existing sessions from ~/.claude/projects, ~/.codex/sessions
and others into one workspace. Has projects and sessions. But the model
is "a main agent delegating to sub-agents", not peers in a room.

## Also seen
- SeemSeam/claude_codex_bridge   — visible multi-agent CLI workspace
- yeachan-heo/oh-my-claudecode   — "teams-first" orchestration for CC
- bradAGI/awesome-cli-coding-agents — the full directory

## Conclusion

The common shape everywhere is an orchestrator: a boss and executors.
Nobody offers a room of equal members with subrooms, a movable lead and
history that belongs to the room. That is the gap foundry-lab fills.
It is narrow, and it is empty.

---

## What CAO actually does (read from the source, not the README)

### Process model
One **interactive** `claude` TUI per agent, each in its own tmux pane, alive
for the whole CAO session. Not `-p`. Input is typed into the pane; output is
read back with `capture-pane` and parsed with regexes hunting the response
glyph (`⏺` / `●`). `providers/claude_code.py` is hundreds of lines of that,
with comments citing GitHub issues — the cost of screen-scraping a TUI that
changes every release.

One conversation per terminal. Never mixed. Switching context means a
different terminal, a different process. Nobody swaps a conversation inside a
live process — the model gets confused, so they don't try.

`--resume` appears once in the whole codebase, and the comment says why:
"re-open a supervisor conversation inside a new CAO session (durable-orchestra
recovery)". Restart recovery, not normal operation.

### Agent-to-agent communication
Agents never address each other. They call **MCP tools** served by CAO:

  send_message(receiver_id, message)   inbox; omit receiver -> the "recorded
                                       caller", i.e. whoever spawned you
  handoff(profile, message, timeout)   sync: spawn a terminal, wait, return output
  assign(...)                          async, fire-and-forget with callback
  answer_user_prompt(terminal_id, ...) answer an approval prompt in another terminal
  emit_ui(component, props)            draw a card in the operator dashboard,
                                       from a server-side allow-list

The agent knows nothing about topology. Routing lives entirely in the server.

Delivery: persist to SQLite first, then deliver by typing the message into the
target's tmux pane as a bracketed paste — but only while the target is IDLE or
COMPLETED. Plus a 5s watchdog polling log files to retry. Plus an eager path
for Claude, whose Ink TUI buffers input while processing. Plus two bracketing
strategies depending on the tmux version.

### What we take
1. An MCP tool surface for agents. It is the only clean way one agent reaches
   another — a tool call, not a convention in prose we hope the model honours.
2. Persist the message before delivering it; it survives a dead process.
3. Implicit reply-to.

### What we skip
tmux, screen scraping, the status machine, the delivery watchdog. With
`-p --input-format stream-json` a message is one line on stdin and the answer
is a `result` event. The whole of their inbox-delivery.md collapses into
`stdin.write()`.
