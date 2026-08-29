# Data model (draft)

    Project
      Session
        Seat                    a role, not a person
          binding -> Member     who currently sits here
          provider_cursor       opaque; native session id, a cache
          summary               compacted history, filled lazily
          context_watermark     replay starts here
        Room(kind, members[])   team = every seat; group = a subset;
                                direct = one seat. You are always a member.
          Message(seq, author, body)

    Member    provider + model + settings + system prompt

Rules:
- Messages live in rooms. A seat's context is the projection over the
  rooms it belongs to, in time order. That projection is also the
  visibility rule: seats outside a room never learn it exists.
- `provider_cursor` may be dropped at any time; we replay the
  projection (or `summary`) instead.
- Rebinding a seat to another member keeps every room membership and
  all history. The replacement inherits the seat, not the cursor.
- "Clear context" moves `context_watermark`; it never deletes group
  messages, because they are not the seat's to delete.
- On restore each seat resolves to available | degraded | missing.
  Only missing seats block; assign a replacement or skip.

Open questions (not yet decided):
- daemon shape and per-member launch configuration (carried over from
  agent-bridge as an idea, not as code)
- storage: single SQLite per install vs one per project
- group turn-taking: broadcast, round-robin, or explicit @mention only
- does a private room show up at all in a non-member's UI
