# lyo Engine

A game engine for chatbot games. You write a game as one markdown file — prose
and code together — and lyo serves it to a chat room, where several people play
the same world at once.

## Install

```bash
uv tool install --editable '.[discord]'
```

That is the way to install lyo. It puts `lyo` on your `PATH` in an environment
of its own, so every command below is just `lyo ...` with nothing in front of
it. `--editable` keeps it following this checkout, so source changes take
effect immediately; drop it for a frozen copy, and drop `[discord]` if you only
want the browser adapter, which needs no dependencies at all.

```bash
uv tool upgrade lyo        # after changing dependencies, not after editing code
uv tool uninstall lyo      # undo
uv tool list               # what is installed
```

Without installing, `uv run lyo ...` works inside the project, and
`source .venv/bin/activate` — `.venv\Scripts\activate` on Windows — gives one
shell a bare `lyo`.

On Windows use PowerShell, where that install line works as written; `cmd.exe`
takes the single quotes literally, so there it is
`uv tool install --editable ".[discord]"`. Everything else is the same command
on both hosts. [docs/deployment.md](docs/deployment.md) collects the handful of
places where Windows behaves differently.

## Get playing

```bash
lyo set adapter.discord.token=YOUR_TOKEN      # stage the token
lyo commit                                    # apply it
lyo run world/kairos.md                       # serve the example game
```

Or try it with no account at all, in a browser:

```bash
lyo run -a webui                              # prints a URL; open it
```

The page is a chat room with one of you in it: type the same commands, read the
same output. Three things it has that a chat platform does not — switch which
character you are, so one browser can duel itself; reset the simulation between
rule changes; and load another gameworld by clicking the cover in the left
margin, a `.md` file or a `.png` cartridge, checked before it is accepted and
refused with the diagnostics `lyo lint` would give. It opens on a throwaway
simulation that saves nothing, so poking at a game leaves no characters behind.
[docs/platforms.md](docs/platforms.md) has the rest.

Then in Discord: `!register` to make a character, `!look` to see where you are,
`!attack wolf` to start a fight.

Discord needs a little setup first — an application, a token, and the **Message
Content Intent**, without which the bot connects but never sees a command.
`lyo adapters --setup` prints the steps, and so does
[docs/platforms.md](docs/platforms.md).

## Check a game before serving it

```bash
lyo lint world/kairos.md
```

```
kairos.md:77:10: error[unknown-monster] no monster named "Goblin Scowt" -- did you mean "Goblin Scout"?
     77 |   spawns "Goblin Scowt", "Dire Wolf"
          |          ^
```

`lint` reads all three forms a game can take — `.md`, a bare `.game`, or a
`.png` cartridge — and reports every problem at once, pointing at the line in
the file you actually edit.

## Run it as a service

```bash
lyo service install world/kairos.md --start
lyo service status
```

The unit carries no secrets: the token lives in configuration, not the service
definition. Changing configuration does not need a restart:

```bash
lyo set adapter.discord.prefix=?
lyo commit                 # "an instance is running -- `lyo reload` to apply"
lyo reload                 # applied, without dropping the connection
```

## Ship a game as one file

A game is a markdown document whose fenced `game` blocks are its source, so the
file is both the program and its documentation. It can also be packed into a
PNG — a cartridge — whose picture is the label:

```bash
lyo pack world/kairos.md -o kairos.png    # 5.6 kB, carrying 14 kB of source
lyo lint kairos.png                        # reads the game out of the image
lyo unpack kairos.png -o recovered.md      # byte-identical
```

See [docs/cartridge.md](docs/cartridge.md).

## Everything else

| Command | Does |
|---|---|
| `lyo adapters` | List the bot adapters this installation can run. |
| `lyo bundle` | Generate any documentation not yet written or updated, then zip it up. |
| `lyo changes [PACKAGE]` | List staged changes awaiting a commit. |
| `lyo commit [PACKAGE]` | Apply staged changes. |
| `lyo delete <PATH>` | Stage the removal of one option. |
| `lyo get <PATH>` | Read one option's live value. |
| `lyo lint [SOURCE]` | Check a game source: .md, .game or a .png cartridge. |
| `lyo pack <SOURCE>` | Pack a markdown game into a PNG cartridge. |
| `lyo reload` | Apply committed configuration and world changes to a running instance. |
| `lyo revert [PACKAGE]` | Throw staged changes away. |
| `lyo run [SOURCE]` | Serve a game to a chat platform. |
| `lyo service install [SOURCE]` | Install the service definition for this host. |
| `lyo service restart` | Restart the service. For configuration changes, prefer `lyo reload`. |
| `lyo service start` | Start the service. |
| `lyo service status` | Report what the host's service manager thinks, and what the instance says. |
| `lyo service stop` | Stop the service. |
| `lyo service uninstall` | Stop the service and remove its definition. |
| `lyo set <ASSIGNMENTS>` | Stage one or more options. Takes `-` to read assignments from stdin. |
| `lyo show [PREFIX]` | Print configuration. A leading ~ is a staged value, - a staged removal. |
| `lyo state [SUMMARY]` | Show the latest session state, or save a new one. |
| `lyo status` | Ask a running instance what it is doing. |
| `lyo tangle <SOURCE>` | Extract the `game` blocks from a markdown game, in document order. |
| `lyo unpack <CART>` | Recover the markdown game from a PNG cartridge. |

### Configuration

Options follow OpenWrt's UCI convention: `package.section.option`, where a `set`
stages a change and nothing is live until `commit`.

| Option | | Means |
|---|---|---|
| `adapter.discord.token` | required | Discord bot token. |
| `adapter.discord.prefix` | default `!` | Command prefix. |
| `adapter.discord.owner` | optional | Discord user id allowed to run owner commands. |
| `adapter.discord.notice_seconds` | default `3` | How long the 'check your DMs' note lives. |
| `adapter.webui.host` | default `127.0.0.1` | Interface to bind. Loopback unless widened deliberately. |
| `adapter.webui.port` | default `8720` | Port to listen on. |
| `adapter.webui.token` | optional | Shared secret, required when host is not loopback. |
| `adapter.webui.assets` | default `https://unpkg.com/quikchat` | Where to load quikchat from. Point this at a local copy to work offline. |
| `adapter.webui.prefix` | default `!` | What a command starts with, as in a chat room. Empty means no prefix is needed. |
| `adapter.webui.theme` | default `quikchat-theme-dark` | A quikchat theme class. |
| `adapter.webui.pace` | default `600` | Milliseconds to think before each line of output, shown as quikchat's three-dot pulse. 0 is instant. |
| `adapter.webui.player` | default `neo` | Who the page starts out playing as. |
| `adapter.webui.session` | default `ephemeral` | Which simulation the page opens on: ephemeral keeps nothing, persistent saves. |
| `adapter.webui.sweep_seconds` | default `1` | How often timed-out prompts and lapsed challenges are checked. |
| `adapter.webui.max_upload` | default `4194304` | Largest gameworld the page will accept, in bytes. |

Plus `game.main.source` (which game to serve), `adapter.main.name` (which
adapter to use), and `control.main.host` / `control.main.port` /
`control.main.token` for the control channel. See
[docs/configuration.md](docs/configuration.md).

### The language

12 top-level declarations: `game`, `location`, `monster`, `item`, `class`, `spell`, `track`, `verb`, `flow`, `offer`, `rules`, `shop`,
plus `npc` inside a location. See [docs/language.md](docs/language.md).

### Writing another adapter

Discord is a plugin, not the engine. See [docs/adapters.md](docs/adapters.md).

## Requirements

Python 3.11 or newer. The core depends on three packages, each of which has no
dependencies of its own: `lark`, `pluggy`, `click`. `discord.py` arrives only
with the `discord` extra, and nothing in the core imports it.

Linux and Windows are both supported, including running as a service —
systemd user units on one, Task Scheduler on the other, neither needing
administrator rights.

<!-- generated by lyo 0.1.0 from c8c626d12cb8387f -->
