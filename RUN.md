# Running sinaxa

```
/usr/bin/python3 -m src.server
/usr/bin/python3 -m src.server --port 8789 --state ./state --cwd /path/to/work
```

Then open http://127.0.0.1:8789.

`--state` is where everything is kept, `--cwd` is the folder the agents read.
`--opencode-port` (default 4096) says where `opencode serve` is, or should be
started.

## The first five minutes

Nothing is hardcoded, so a fresh install is empty and the order matters:

1. **Members** -- add yourself first, as the human lead. Then an agent per
   engine you have: pick the engine, and the form changes to fit it.
2. **Seats** -- add a role, write its default prompt, give it a default
   member.
3. **Projects** -- add one. It arrives with a session called `main`, a seat
   for every role that has a default member, and a room each.

Then write in a room. Naming nobody asks everyone in it; `@Name` asks only
them.

## Tests

```
/usr/bin/python3 -W ignore::ResourceWarning -m unittest discover -s tests
```

144 of them, and none needs a subscription: the engine tests run the real
adapters against fake binaries in `tests/fakes/`, and the model, context and
API tests run against a fake engine that starts nothing.

To exercise the real ones, the probes in `tools/` each talk to one provider
and print what it does.

## Things to keep an eye on

**Leftover processes.** Claude spawns one per seat. After a session with
several seats, check nothing was left behind:

```
ps -eo pid,rss,command | grep "[a]llowedTools Read Grep Glob"
ps -eo pid,rss,command | grep "[c]odex app-server"
ps -eo pid,rss,command | grep "[o]pencode serve"
```

sinaxa only ever kills an `opencode serve` it started itself, so one you are
running in a terminal is safe.

**Unclosed pipes.** `src/engines/claude_session.py` does not close the old
process's stdout/stderr in `stop()`; the tests print `ResourceWarning` about
it. Not fixed yet -- it is the same shape as the 600 MB leak from an earlier
session.

**codex effort.** Fixed at medium. It is a config key read when the process
starts, and one process serves every codex seat, so per-seat effort would
mean one process per effort level. To be revisited.

**opencode models.** A model must be declared in opencode's own config, not
merely served by the provider. sinaxa lists what opencode declares, so
choosing from the list is safe; a name typed in elsewhere is not.
