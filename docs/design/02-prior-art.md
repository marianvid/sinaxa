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
