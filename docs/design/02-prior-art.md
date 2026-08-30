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

---

## turma — turma.sh, github.com/turma-dev/turma (MIT, Apr–Jul 2026)

Found while checking whether the name was free. It is not: `turma` on PyPI is
"Provider-pool-aware multi-agent coding orchestration", built on LangGraph,
with `claude-code`, `codex` and `opencode` worker backends — the same three
CLIs we use.

Different product, though. Theirs is a pipeline:

    turma plan          author/critic loop with a human approval gate
    turma plan-to-beads turn the approved plan into tasks
    turma run           swarm, one PR per task
    turma status        Beads + PR + worktree state

plan -> tasks -> PRs. Ours is room -> members -> conversation. They automate
the work; we build the place where it is discussed.

### Worth taking

**1. Completion by sentinel file, not by reading text.** The worker writes
`.task_complete` or `.task_failed` into its worktree; their docstring says
outright that the orchestrator "does not parse the worker's stdout for
success/failure". Compare CAO, which regex-scrapes a terminal. This is
model-agnostic and survives CLI version changes. It matters for us the moment
an agent *does* something rather than only talking.

**2. Provider pools with a concurrency cap.** A pool binds a backend to a set
of task types and a cap; the scheduler picks a task whose pool has a free slot
instead of blocking on the head of the queue, so a rate-limited provider never
stalls work another provider could take. We need this as soon as a message
with no @ wakes every agent at once.

**3. A git worktree per task.** Isolation for when agents write. Not needed
while everything is read-only, but the right shape later.

### What it does NOT offer

Nothing on the question we spent a day measuring. Their workers are one-shot:

    claude -p <prompt> --dangerously-skip-permissions
    codex exec <prompt> --cd <worktree> --sandbox workspace-write

One `subprocess.run` per task. No `--resume`, no session id, no persistent
process. Every task is a fresh agent with no memory — which is fine when a
task is atomic, and useless for a conversation. They side-stepped the problem
rather than solving it.

Their concurrency machinery (a global mutation lock, per-pool semaphores,
draining in-flight workers on halt) exists to serialise parallel git writes.
Not our problem.

### Intel worth keeping

They deferred a Gemini backend because Google is retiring the `gemini` CLI in
favour of an Antigravity CLI, and it is not a drop-in replacement.
