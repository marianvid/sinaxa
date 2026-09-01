# Running sinaxa

```
./sinaxa                 start it and open the browser
./sinaxa start           the same, without opening anything
./sinaxa stop            stop it, and check nothing was left behind
./sinaxa restart
./sinaxa status          is it up, and what is it holding open
./sinaxa test            run the tests
./sinaxa log             follow the log
```

Options, or the same names as environment variables (`SINAXA_PORT` and so
on): `--port 8789`, `--state ./state`, `--cwd .`, `--opencode-port 4096`.

The script finds a python 3.8 or newer for itself, makes `state/` if it is
not there, and refuses to open a browser tab on a server that failed to
start -- it prints the end of the log instead.

`status` and `stop` only ever look at sinaxa's own children. A codex inside
ChatGPT.app, or an `opencode serve` you are running in a terminal, are not
sinaxa's to report and not sinaxa's to kill.

## The first five minutes

Nothing is hardcoded, so a fresh install is empty and the order matters:

1. **Members** -- add yourself first, as the human lead. Then an agent per
   engine you have: pick the engine, and the form changes to fit it.
2. **Seats** -- add a role and write its prompt (a role without one is
   refused: the prompt is what its occupant is told it does). Give it a
   default member.
3. **Projects** -- add one. It arrives with a session called `main`, a seat
   for every role that has a default member, and a room each.

Then write in a room. Naming nobody asks everyone in it; `@Name` asks only
them. Paste a screenshot into the box and it goes with the message --
docs/design/05-images.md says what each engine does with one.

## Tests

```
./sinaxa test
```

193 of them, and none needs a subscription: the engine tests run the real
adapters against fake binaries in `tests/fakes/`, and the model, context and
API tests run against a fake engine that starts nothing.

To exercise the real ones, the probes in `tools/` each talk to one provider
and print what it does.

## Things to keep an eye on

**Leftover processes.** Claude spawns one per seat, around 430 MB each. Every
adapter's `stop()` closes all three pipes, waits for the process and reaps
it; the server turns SIGTERM and SIGHUP into an ordinary exit so that `kill`
runs the same shutdown as Ctrl-C; and `App.stop()` is registered with atexit
for whatever is left. `tests/test_cleanup.py` counts open descriptors and
process-table entries around every start and stop, and one of its tests
starts a real server, terminates it, and checks its agents died with it.

`./sinaxa stop` says so if anything outlived the server. If it ever does,
that is a bug worth reporting rather than a chore to repeat.

**codex effort.** Fixed at medium. It is a config key read when the process
starts, and one process serves every codex seat, so per-seat effort would
mean one process per effort level. To be revisited.

**opencode models.** A model must be declared in opencode's own config, not
merely served by the provider. sinaxa lists what opencode declares, so
choosing from the list is safe; a name typed in elsewhere is not.
