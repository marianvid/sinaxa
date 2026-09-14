# Provider runtimes

The runtime boundary is a project. `RuntimeManager` creates a `ProjectEngines`
only when an open project receives work.

| Engine | Project backend | Conversation |
|---|---|---|
| Claude CLI | none shared | one CLI process per `(session, seat)` |
| Codex CLI | one `app-server` | one thread per `(session, seat)` |
| OpenCode | one local `serve` process and port | one provider session per `(session, seat)` |

Every engine has an executable, enabled flag, persistent/resume mode, streaming
preference, concurrency limit, MCP registry and provider-specific options.
Members select the model/effort and may restrict the global MCP set. Native
conversation IDs are persisted only under Sinaxa's own state directory.

In persistent mode a live transport is reused. Resume mode releases the agent
handle after a turn and adopts its native ID on the next turn. An invalid
checkpoint falls back to replay from the Sinaxa transcript.
