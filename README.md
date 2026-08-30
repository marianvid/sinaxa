# kenbet

A workspace where every participant is an AI agent — plus you.

*A kenbet was the local council in ancient Egypt: the body that heard the
parties and decided. Small, seated, and answerable to whoever convened it.*

Projects hold sessions. A session is a saved snapshot of a *team*: which
seats existed, who sat in each one, and the conversation each seat had.
Reopen a session and the team comes back. If a member is no longer
available, you assign someone else to the seat — the seat keeps its
history, the replacement inherits it.

## Model

    Project
      Session            snapshot of a team at a point in time
        Seat             a role: "backend", "reviewer", "architect"
          binding    ->  Member
          thread         the seat's own conversation
        group thread     the shared room, with @mentions

    Member               provider + model + settings + system prompt

The seat's thread is the source of truth. A provider's native session id
(claude --resume, codex conversation id) is a cache: if the process dies
or the member is swapped, we replay from the thread.

## Status

Early. Design and mockups only.
