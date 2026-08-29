# Data model (draft)

    Project
      Session                     a theme of work; the restorable unit
        Member[]                  the team for this session
          binding -> Provider     provider + model + settings + prompt
          cursor                  native session id; a cache, droppable
          summary                 compacted history, filled lazily
          watermark               replay starts here
        Room(kind, members[])     team = everyone; group = a subset;
                                  direct = one agent. You are in all of them.
          lead                    inherits the session lead, may override
          turn_policy             broadcast | mention | round_robin | lead
          Message(seq, author, body)

Rules:
- You (human) are a member of every room and cannot be removed.
- Exactly one member of a room is lead. Default is you; it may be an
  agent. The lead is per room, not per session — you can hand
  `# schema` to an agent while keeping `# Team room`.
- turn_policy decides who answers a message:
    broadcast     every agent answers (brainstorm; costs N inferences)
    mention       only who is named answers
    round_robin   fixed order, one at a time
    lead          the lead receives first and nominates the speaker
  With a human lead, `lead` degrades to manual @mention.
- Messages live in rooms. A member's context is the projection over the
  rooms it belongs to, in time order. That projection is also the
  visibility rule: members outside a room never learn it exists.
- Rebinding a member keeps the seat, its rooms and all history. Only
  the binding and the cursor change.
- "Clear context" moves the watermark; room messages are never deleted,
  they are not one member's to delete.
- On restore each member resolves to available | degraded | missing.
  Only missing ones block; assign a replacement or skip.

Open questions:
- daemon shape and per-member launch configuration (idea carried over
  from agent-bridge, not code)
- storage: one SQLite per install vs one per project
- does a private room appear, greyed, to non-members? (leaning: no —
  an agent that sees "a discussion I cannot read" will talk about it)
- can an agent lead create a room, or only nominate speakers?
