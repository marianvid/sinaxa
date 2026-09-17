# Domain model

The vocabulary is deliberately small:

- An **engine** is one global CLI installation and its process policy.
- A **member** is a reusable identity selecting an engine, model and effort.
- A **seat template** is a reusable role, prompt and optional default agent.
- A **project type** is an ordered recipe of seat templates.
- A **project** owns a working directory, seats, sessions and open/closed state.
- A **seat** is a project-local copy of a role and may be unassigned.
- A **session** selects seats and owns one transcript plus a context boundary.
- An **agent context** belongs to one `(project, member)` and consumes visible
  events from every session in that project.

A session also owns its conversational safety policy: response timeout and the
maximum number of agent turns in one human-initiated round. These values can be
overridden per session because a quick review and a long research task have
different execution profiles.

Team and direct sessions are derived project infrastructure. The team session
tracks every current seat. Adding a seat creates its direct session; removing
the seat removes that direct history. Custom and team histories remain after a
participant is removed, because old messages carry their author identity.

Clear context is not clear history. It appends a visible boundary and resets
the affected persistent project agents. On their next activation, Sinaxa
rebuilds them from still-visible transcript events while excluding the cleared
session's earlier epoch.

An unaddressed human message fans out concurrently to every runnable seat in
that session. A human message containing `@Name` activates only the mentioned
members. Other eligible members receive that visible event lazily on their next
activation but do not answer it. Agent replies are immediately appended to the
session transcript, and only explicit `@Name` mentions schedule another agent
turn. Messages for a busy agent accumulate until its current turn finishes.

Main events are visible to all project members, direct events only to their
member and the human lead, and custom-session events only to their participants.
Sinaxa sends only unseen deltas to the persistent native context. Consequently,
knowledge acquired in Main and direct conversation remains available to the
same agent without replaying the entire transcript on every turn.

Project types are used only when a project is created. Their templates are
copied, not referenced as live configuration, so changing the global catalog
cannot silently rewrite an existing project's team or instructions.
