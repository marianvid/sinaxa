# Domain model

The vocabulary is deliberately small:

- An **engine** is one global CLI installation and its process policy.
- A **member** is a reusable identity selecting an engine, model and effort.
- A **project** owns a working directory, seats, sessions and open/closed state.
- A **seat** is a project role with instructions and one occupying member.
- A **session** selects seats and owns one transcript plus a context boundary.

Team and direct sessions are derived project infrastructure. The team session
tracks every current seat. Adding a seat creates its direct session; removing
the seat removes that direct history. Custom and team histories remain after a
participant is removed, because old messages carry their author identity.

Clear context is not clear history. It appends a visible boundary, drops native
checkpoints and starts fresh provider conversations on the next message.
