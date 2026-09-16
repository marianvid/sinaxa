# Domain model

The vocabulary is deliberately small:

- An **engine** is one global CLI installation and its process policy.
- A **member** is a reusable identity selecting an engine, model and effort.
- A **seat template** is a reusable role, prompt and optional default agent.
- A **project type** is an ordered recipe of seat templates.
- A **project** owns a working directory, seats, sessions and open/closed state.
- A **seat** is a project-local copy of a role and may be unassigned.
- A **session** selects seats and owns one transcript plus a context boundary.

A session also owns its conversational safety policy: response timeout and the
maximum number of agent turns in one human-initiated round. These values can be
overridden per session because a quick review and a long research task have
different execution profiles.

Team and direct sessions are derived project infrastructure. The team session
tracks every current seat. Adding a seat creates its direct session; removing
the seat removes that direct history. Custom and team histories remain after a
participant is removed, because old messages carry their author identity.

Clear context is not clear history. It appends a visible boundary, drops native
checkpoints and starts fresh provider conversations on the next message.

Messages from the human lead fan out to every runnable seat concurrently.
Unmentioned agents may decline internally with `[NO_REPLY]`; mentioned agents
must answer. Agent replies are immediately appended to the shared transcript.
Only explicit `@Name` mentions schedule another agent turn, and messages for a
busy agent accumulate until its current turn finishes.

Project types are used only when a project is created. Their templates are
copied, not referenced as live configuration, so changing the global catalog
cannot silently rewrite an existing project's team or instructions.
