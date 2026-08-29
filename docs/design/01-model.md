# Data model (draft)

    Project
      Session                      a saved team snapshot
        Seat                       a role, not a person
          binding -> Member        who currently sits here
          thread                   the seat's messages
          provider_cursor          opaque; native session id, a cache
          summary                  compacted history, filled lazily
        group thread               shared room, @mentions fan out

    Member    provider + model + settings + system prompt

Rules:
- The seat's thread is the source of truth. `provider_cursor` may be
  dropped at any time; we replay from the thread.
- Rebinding a seat to another member keeps the thread. The replacement
  is primed with `summary` (or the thread) and gets a fresh cursor.
- Clearing context truncates the thread; the seat survives.
- On restore each seat resolves to available | degraded | missing.
  Only missing seats block; the user assigns a replacement or skips.

Open questions (not yet decided):
- daemon shape and per-member launch configuration (carried over from
  agent-bridge as an idea, not as code)
- storage: single SQLite per install vs one per project
- group turn-taking: broadcast, round-robin, or explicit @mention only
