# Provider runtimes

The runtime boundary is a project. `RuntimeManager` creates a `ProjectEngines`
only when an open project receives work.

| Engine | Project backend | Member context |
|---|---|---|
| Claude CLI | none shared | one CLI process per `(project, member)` |
| Codex CLI | one `app-server` | one thread per `(project, member)` |
| OpenCode | one local `serve` process and port | one provider session per `(project, member)` |

Every engine has an executable, enabled flag, mode, streaming preference,
concurrency limit, MCP registry and provider-specific options.
Members select the model/effort and may restrict the global MCP set. Native
conversation IDs are persisted only under Sinaxa's own state directory.

Persistent mode is the only enabled mode in the current product. The retained
non-persistent option is disabled and labelled “Not yet implemented”. A live
agent handle and native context are reused across all of a member's project
sessions. The native ID is resumed only after process/application/project
restart. An invalid checkpoint falls back to replaying visible, non-cleared
events from Sinaxa's transcripts.
