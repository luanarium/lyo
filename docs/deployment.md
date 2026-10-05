# Running it

## Installing

```bash
uv tool install --editable '.[discord]'    # lyo on PATH, following this checkout
uv tool upgrade lyo                        # after dependency changes
uv tool uninstall lyo                      # undo
```

This is how lyo is meant to be installed: `uv tool install` gives it an
environment of its own and puts the command on `PATH`, so every example here
is a bare `lyo`. `uv sync` builds the project's virtual environment but puts
nothing on `PATH`, so it needs `uv run lyo ...` or `source .venv/bin/activate`.

One thing to know about `--editable`: the tool follows this checkout, so
editing the source takes effect at once, but its dependencies were resolved
when it was installed. After adding or changing one, `uv tool upgrade lyo`.
The symptom otherwise is an `ImportError` from `lyo` while `uv run lyo` is
fine.

### Adapters that are not first-party

An adapter is a plugin found by entry point, so it has to live in the same
environment as the command. `--with` puts it there:

```bash
uv tool install --editable '.[discord]' --with lyo-matrix
lyo adapters                      # it appears, with its own settings
```

## By hand

```bash
lyo run                     # uses game.main.source and adapter.main.name
lyo run world/kairos.md     # or name the game
lyo run --check             # validate the game and the settings, then stop
```

## As a service

systemd user units on Linux, Task Scheduler on Windows. Neither needs
administrator rights.

```bash
lyo service install world/kairos.md --start
lyo service status
lyo service stop
lyo service uninstall
```

```bash
lyo service install --dry-run     # print the definition without writing it
lyo service install --name kairos # run more than one game at once
```

The definition carries no secrets, because the token is configuration. Note
that a service does not inherit your shell, so variables set there will not
reach it — install warns if any are set. A `.env` does reach it, since lyo
reads the file itself, but only one beside `lyo.db` or a directory above it:
there is no shell, and Task Scheduler sets no working directory. Install says
which of the files it found fall on which side of that line.

## Changing things without a restart

A running instance listens on a local control channel.

```bash
lyo status                  # what it is serving, and for how long
lyo set adapter.discord.prefix=?
lyo commit                  # "an instance is running -- `lyo reload` to apply"
lyo reload                  # applies configuration and the world
```

`systemctl --user reload lyo` does the same thing, since the unit sends SIGHUP
and that means reload.

A reload validates first. If the game no longer resolves, the old world keeps
serving and the diagnostics are printed:

```
kairos.md:77:10: error[unknown-monster] no monster named "Goblin Scowt" -- did you mean "Goblin Scout"?
Error: world/kairos.md does not resolve
```

A restart loses nothing either way: characters, the live simulation, wounded
monsters and their contributor lists, and duels in progress are all persisted.

## The control channel

A Unix socket beside the state file on POSIX — `lyo.db` becomes `lyo.sock`,
mode 600 — or a loopback TCP port on Windows, recorded in the state file so the
CLI can find it. Newline-delimited JSON, three operations: `ping`, `status`,
`reload`.

It binds to localhost only. Binding wider is possible but requires
`control.main.token`, since it is an unauthenticated administrative channel:

```bash
lyo set control.main.host=0.0.0.0 control.main.token=$(openssl rand -hex 16)
lyo commit
```

On Windows, where there is no `openssl` by default:

```powershell
lyo set control.main.host=0.0.0.0 control.main.token=$(python -c "import secrets; print(secrets.token_hex(16))")
lyo commit
```

Run with `--no-control` to disable it entirely.

## On Windows

Everything is the same command. These are the places the host itself behaves
differently, and what lyo does about each.

**The shell.** PowerShell runs the examples as written. `cmd.exe` has no single
quotes, so `uv tool install --editable '.[discord]'` becomes
`uv tool install --editable ".[discord]"` there. A project virtual environment
is activated with `.venv\Scripts\activate` rather than `source
.venv/bin/activate`.

**The service is a scheduled task**, registered with `schtasks` and triggered
at logon, because that needs no administrator rights and no service wrapper.
Three consequences:

- Task Scheduler cannot set a working directory, so every path in the
  registered command is absolute. `lyo service install --dry-run` prints it.
- `schtasks` accepts at most 261 characters of command. Install refuses before
  calling it rather than passing on a usage dump, and says what to shorten. A
  checkout nearer the drive root is the usual fix.
- `lyo service stop` ends the task, which terminates the process rather than
  asking it to stop. Nothing is lost: the simulation is written after every
  turn, not at exit.

`lyo service status` reads the state out of `schtasks` output, which Windows
translates, so on a non-English install the task line may say `unknown` while
the `instance` line below it — which asks the running process directly — is
still right.

**Reload** has no SIGHUP to send, so `lyo reload` is the way. It works the same
as on Linux, over the control channel.

**The control channel is a loopback TCP port** rather than a Unix socket, since
Windows has no `AF_UNIX` for asyncio. The port is recorded in the state file,
so `lyo status` and `lyo reload` find it with no configuration. Still localhost
only.

**Ctrl-C** stops a run and unwinds it cleanly. Windows has no
`add_signal_handler`, so instead of a handler cancelling the task group, the
interrupt comes out of the loop as a `KeyboardInterrupt` and `asyncio.run`
cancels whatever is still running as it leaves — the same cleanup by a
different route, and the control channel's socket row is cleared either way.

**Game files and line endings.** A game saved on Windows has CRLF line endings.
The grammar takes them, but a markdown fence is matched as a whole line, so a
CRLF document would have looked like one with no `game` blocks in it at all.
Reading a path normalises that; so does the browser adapter's upload, which
normalises whatever it is handed. `lyo unpack
-o recovered.md` writes LF, which is what makes the round trip byte-identical —
redirecting standard output instead (`lyo unpack x.png > y.md`) lets the shell
translate the newlines, and the bytes will not match.

**Non-ASCII output.** Games say things like `⚔️ Brynn attacks`. A Windows
console handles that; a redirected stream would otherwise get the locale's code
page and raise, so lyo widens its own output to UTF-8 at startup.

**Offline assets for the browser adapter** take a plain Windows path or a
Windows file URL — `lyo set adapter.webui.assets=C:\quikchat` or
`file:///C:/quikchat`. The adapter serves what is in that directory itself, so
the page never has to load a script off the filesystem, which a browser would
refuse.

## Bundling

```bash
lyo bundle              # regenerate stale documentation, then zip the project
lyo bundle --no-zip     # documentation only
lyo bundle --force      # regenerate everything
```

Documentation is generated from the code it describes, so the command tables,
configuration paths and language declarations in these files cannot drift from
what the software does.

## Terms

| Term              | Definition |
| ----------------- | ---------- |
| systemd user unit | A service definition owned by your login, needing no root |
| Task Scheduler    | The Windows equivalent used here, triggered at logon |
| schtasks          | The command that registers a scheduled task |
| CRLF              | Carriage return plus line feed: the Windows line ending |
| control channel   | The local socket a running instance listens on |
| SIGHUP            | The signal that conventionally means reload, which the unit sends |
| SIGTERM           | The signal a service manager stops a process with |
| loopback          | 127.0.0.1 and ::1 -- this machine only |
| linger            | The systemd setting that keeps a user service running after logout |

<!-- generated by lyo 0.1.0 from b012c8ea22dc435c -->
