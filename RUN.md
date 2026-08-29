# Running foundry-lab

Use `/usr/bin/python3`, never the anaconda one.

## MVP 2 — you, Claude and Codex, in rooms

    cd /Volumes/Marian_Backup/work/foundry-lab
    /usr/bin/python3 lab.py --codex mcp     # codex mcp-server   (stable contract)
    /usr/bin/python3 lab.py --codex app     # codex app-server   (experimental)

Then http://127.0.0.1:8789

Same code both ways — only the Codex adapter changes, so the two runs are
comparable. Each keeps its own transcript: `state/lab-mcp.jsonl`,
`state/lab-app.jsonl`. Run them one at a time (same port), or add `--port`.

Rooms: `# team` (both agents), `↳ claude`, `↳ codex`.
The chip in the header cycles turn-taking: broadcast → mention →
round_robin → lead.

Agents address each other by writing `@Claude` / `@Codex`. A reply is
delivered ONLY to the members it names, never re-broadcast, and the chain is
capped at 3 hops per message you send.

`--scope member` gives each member one conversation across all its rooms
instead of one per room. Untested beyond starting up; the default is
`--scope room`.

## MVP 1 — the two-member version, kept

    /usr/bin/python3 app.py        # http://127.0.0.1:8788

One room, you and Claude, one `claude -p` per message (`--resume`). Kept as
the reference for what the cheap-and-simple version costs.

## What the smoke test showed

    /usr/bin/python3 tools/smoke_lab.py mcp
    /usr/bin/python3 tools/smoke_lab.py app

Both backends, same script, first turn each:

    broadcast to # team     Claude 2.1s   Codex 4.8s
    agent to agent          Claude "that's for Codex" -> Codex asks Claude
                            -> Claude answers                 total 8.9s

    mcp   2 conversations, 2 processes, 533 MB
    app   2 conversations, 2 processes, 618 MB

Memory is dominated by Claude: ~430 MB for one `claude` process against
~117 MB for a `codex mcp-server` hosting every Codex conversation. On a
128 GB machine neither matters yet, but the shape is worth remembering: each
extra Claude conversation costs a whole process, each extra Codex one costs
almost nothing.

## Known rough edges

- Codex token counts read 0 in the status bar; the `token_count` event shape
  did not match what codex_mcp.py expects. Cosmetic, not yet chased.
- No streaming to the browser. The UI polls every 700ms while a room is
  working and shows each member's activity (thinking / working / writing).
- `claude` is started with read-only tools and codex with
  `approval-policy: never`, `sandbox: read-only`. Nothing writes to disk.
- **Process leak.** After a smoke run one `claude -p ... --resume` survived
  the shutdown (600 MB, found with `ps`). `ClaudeSession.stop()` closes stdin
  and kills after 5s, so something escaped it — most likely a session
  restarted by the retry path in `ClaudeAgent.ask` after the original died.
  Until it is fixed, check for strays:

      ps -eo pid,rss,command | grep "allowedTools Read Grep Glob" | grep -v grep

  A leaked process costs no tokens, only memory. Note that the ChatGPT
  desktop app runs its own `codex app-server --listen stdio://` — that one is
  not ours, leave it alone.
