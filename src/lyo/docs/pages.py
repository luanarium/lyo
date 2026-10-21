"""The documents themselves. Prose is authored here; tables are introspected."""

from __future__ import annotations

from lyo import __version__
from lyo.docs import (Document, adapters, codes, commands, declarations,
                      handlers, qualifiers, slots, statements, tables, terms,
                      views)


def _command_table() -> str:
    rows = [f"| `lyo {name}{' ' + usage if usage else ''}` | {help_} |"
            for name, usage, help_ in commands()]
    return "\n".join(["| Command | Does |", "|---|---|", *rows])


def _statement_list() -> str:
    """The statements, as a game writes them rather than as the tree names them."""
    spelled = {"create_player": "create player"}
    blocks = {"each_stmt", "loop_stmt", "handler"}
    return ", ".join(f"`{spelled.get(name, name)}`"
                     for name in statements() if name not in blocks)


def _settings_table() -> str:
    rows = []
    for name, adapter in sorted(adapters().items()):
        for setting in adapter.settings:
            note = "required" if setting.required else (
                f"default `{setting.default}`" if setting.default else "optional")
            rows.append(f"| `adapter.{name}.{setting.key}` | {note} | {setting.help} |")
    return "\n".join(["| Option | | Means |", "|---|---|---|", *rows])


# ------------------------------------------------------------------ README


def readme() -> str:
    return f"""# lyo Engine

An interactive fiction game engine for chatbots. You write a game as one
markdown file — prose and code together — and lyo serves it to a chat room,
where several people play the same world at once.

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
`source .venv/bin/activate` — `.venv\\Scripts\\activate` on Windows — gives one
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

{_command_table()}

### Configuration

Options follow OpenWrt's UCI convention: `package.section.option`, where a `set`
stages a change and nothing is live until `commit`.

{_settings_table()}

Plus `game.main.source` (which game to serve), `adapter.main.name` (which
adapter to use), and `control.main.host` / `control.main.port` /
`control.main.token` for the control channel. See
[docs/configuration.md](docs/configuration.md).

### The language

{len(declarations())} top-level declarations: {', '.join('`' + d + '`' for d in declarations())},
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
"""


# --------------------------------------------------------------- platforms


def platforms() -> str:
    """One section per installed adapter, from what it declares about itself."""
    installed = sorted(adapters().items())
    if not installed:
        return ("# Platforms\n\nNo adapters are installed. "
                "`uv tool install --editable '.[discord]'` installs the "
                "first-party one.\n")

    parts = ["# Platforms", "", "What each installed adapter needs before it "
             "will work. The engine knows none of this — an adapter declares "
             "its own prerequisites, so this page grows when you install "
             "another one.", ""]
    for name, adapter in installed:
        parts += [f"## {name}", "", adapter.summary, ""]
        parts += [adapter.setup.rstrip() if adapter.setup
                  else "_This adapter declares no setup steps._", ""]
        rows = [f"| `adapter.{name}.{s.key}` | "
                f"{'required' if s.required else (f'default `{s.default}`' if s.default else 'optional')} "
                f"| {s.help} |" for s in adapter.settings]
        if rows:
            parts += ["### Settings", "",
                      "| Option | | Means |", "|---|---|---|", *rows, ""]
        parts += [f"```bash", f"lyo set adapter.main.name={name}",
                  *[f"lyo set adapter.{name}.{s.key}=..." for s in adapter.settings
                    if s.required],
                  "lyo commit", "lyo run", "```", ""]

    parts += ["## Terms", "", terms([
        ("adapter", "A plugin connecting the engine to one chat platform"),
        ("intent", "A Discord permission to receive a category of event"),
        ("gateway", "Discord's websocket connection, which a bot holds open"),
        ("OAuth scope", "What an invite link grants the bot"),
        ("token", "The bot's credential. It comes from configuration, the environment or a .env -- never from the game you ship"),
    ])]
    return "\n".join(parts)


# ---------------------------------------------------------------- language


def language() -> str:
    return f"""# The lyo language

A game is a set of declarations. They may appear in any order — the document is
the compilation unit, so a location may name a monster declared further down.
Blocks are delimited by indentation, and `#` begins a comment.

## Declarations

{len(declarations())} of them — {', '.join('`' + d + '`' for d in declarations())} —
plus `npc`, which appears only inside a `location`.

```game
game "Kairos":
  players start at "Oakhaven Village" with 20 hp, 10 gold

location "Whispering Woods":
  "Ancient oaks crowd the path, their branches knitted overhead."
  east to "The Ruined Keep"
  spawns "Goblin Scout", "Dire Wolf"

monster "Dire Wolf":
  18 hp, 6 str, 6 agi, 1 int
  drops 3 to 6 gold
  drops "Wolf Pelt"
  drops "Health Potion" 15% of the time
```

Exits are two-way unless marked `one way`, so each connection is declared once.

### Items

```game
item "Iron Sword" is a weapon:
  4 damage scaling str

item "Fists" is the default weapon:
  also known as "hands", "fist", "punch"
  1 damage scaling str

item "Health Potion" is consumable:
  also known as "potion"
  on use:
    refuse "You are already at full health." when hp is max_hp
    take 1 item from player
    restore 8 hp

item "Splintered Oak Bow" is a weapon:
  4 damage scaling agi, -1 def, 5% crit_chance
  costs 30 gold
  worn on "Main Hand"
  shown as "🏹"
  "Strung with coiled hemp."
```

A refusal aborts the rest of the body, which is why a potion drunk at full
health is not consumed.

A stat may be negative or written as a percentage; `5% crit_chance` is a way
of spelling 5, not a new kind of number. `worn on` and `shown as` are for a
player's eyes only — a label for the slot and a glyph — so a game can say
`Hands` without the engine growing a hands slot. The quoted line is the item's
flavour text. All three show up wherever an item is listed at length, which
today means a shop.

```game
shop at "Oakhaven Village":
  named "Oakhaven Village Shop"
  stocks "Splintered Oak Bow", "Chipped Buckler"
```

`named` is optional; a shop with no name of its own is called after its town.

### Verbs

A verb is a player-facing command. Its slots say what it takes; the engine
resolves them, including the longest-trailing-match rule that lets
`attack iron sword dire wolf` find the wolf and read the rest as the weapon.

```game
verb attack <weapon?> <monster>:
  public
  refuse "You have fallen." unless alive
  deal atk at least 1 to monster
  say "{{player}} hits {{monster}} for {{dealt}}."
  then for every living monster here:
    deal its str - def at least 1 to player
  say "Retaliation from {{retaliators}}: {{taken}}." when taken > 0
```

`public` goes to the room, `private` by direct message. The adapter decides what
that means for its platform.

### Conversations and offers

`flow` is a multi-turn conversation; `offer` is a timed challenge between two
players. These are the chatbot-shaped primitives, and the reason an existing
interactive-fiction library would not do.

```game
flow register:
  private
  refuse "You already have a character." when registered
  ask name: "What is your character's name?"
    accepts any text, trimmed
    times out after 120 seconds
  ask chosen: "Choose a class:"
    offers every class by number, name
    reprompts forever
  create player named name as chosen

offer duel from <player> to <player>:
  requires both alive, both here
  expires after 60 seconds, saying "The challenge expired."
  accepted by verb accept
  while active:
    turn based, alternating
    armor applies
    no retaliation
```

### Rules

Named formulas and event handlers, referenced everywhere else.

```game
rules:
  define def as armor.def + shield.def + accessory.def
  define atk as weapon.damage + weapon.scales / 2

  on kill monster:
    roll gold in monster.gold
    split gold evenly among contributors, remainder to killer

  on enter location:
    respawn all monsters here unless any other player here
```

## Statements

{', '.join('`' + s + '`' for s in statements())}, plus `for every <selector>:`
and `loop:`.

## Expressions

Integer arithmetic throughout, with floor division — every formula in a game
rounds down. `+ - * /`, comparisons (`is`, `is not`, `>`, `>=`, `<`, `<=`),
`and` / `or` / `not`, and the postfix clamps `at least`, `at most` and
`capped at`, which bind loosest so `its str - def at least 1` clamps the whole
subtraction.

Paths read live state: `hp`, `max_hp`, `gold`, a stat by name, `here.inn`,
`weapon.damage`, `monster.gold`, `its str` inside a loop. `both alive` and
`either dueling` quantify over the two sides of a duel.

## Identity

Every declaration has a stable `id`, defaulting to a slug of its name:

```game
item "Rusted Longsword" is a weapon:
  id iron_sword
```

Saved characters refer to the id, never the display name, so renaming an item
does not orphan the copies players hold. Lint rejects a collision.

## Terms

{terms([
    ("declaration", "A top-level definition: a location, item, verb and so on"),
    ("slot", "A verb argument, written `<monster>` or `<weapon?>` if optional"),
    ("clamp", "A postfix bound: `at least`, `at most`, `capped at`"),
    ("flow", "A multi-turn conversation, suspending at each `ask`"),
    ("offer", "A timed challenge from one player to another"),
    ("selector", "What `for every` iterates: `living monster here`"),
    ("slug", "A stable id derived from a display name: `dragons_heart`"),
    ("LALR(1)", "The parsing algorithm: one token of lookahead, no ambiguity"),
    ("lark", "The parsing library the grammar is written for"),
])}
"""


# --------------------------------------------------------------- cartridge


def cartridge() -> str:
    return f"""# One file, two forms

A game is distributed as a single file. The canonical form is markdown; a bare
`.game` file is just the extracted source.

## Literate markdown

Fenced ` ```game ` blocks are the source. Everything else is prose for the
reader, so one file is both the program and its documentation. Blocks may sit
inside collapsible `<details>` sections to keep a long world readable.

```bash
lyo tangle world/kairos.md -o kairos.game   # extract just the source
```

Extraction keeps a line map, so a parse error reports the line in the markdown
you edit, not in the concatenated source.

## PNG cartridges

The same markdown can be carried inside a PNG whose visible picture is the
label:

```bash
lyo pack world/kairos.md --image cover.png -o kairos.png
lyo lint kairos.png
lyo unpack kairos.png -o recovered.md
```

The payload lives in a private ancillary chunk named `gaMe`, which the PNG
specification reserves for exactly this and which every decoder ignores — the
file stays an ordinary image. Inside it: a four-byte magic, a SHA-256 of the
payload, then the markdown, zlib-compressed.

| Field | Bytes | |
|---|---|---|
| magic | 4 | `GBC1` |
| digest | 32 | SHA-256 of the uncompressed markdown |
| payload | rest | zlib-compressed UTF-8 markdown |

Standard `tEXt`, `zTXt` and `iTXt` chunks are read as a fallback, since other
tools write there.

Reading and writing needs no imaging library — the chunk format is a length, a
type, the data and a CRC, all of which the standard library can do.

### The cover

Covers are **630×500**, which is itch.io's cover size rather than anything
invented here, and so the shape game covers are usually drawn in. `lyo pack`
without `--image` draws a plain one at that size, marked as a placeholder so
anything showing covers can draw something better than a blank rectangle.

Nothing is enforced. `--image` keeps the art it is given byte for byte,
whatever its dimensions: resizing it would mean decoding and re-encoding
somebody's picture, which costs an imaging library and loses the original.
Art of another shape is **letterboxed where it is displayed** instead, so none
of it is ever cropped. `lyo pack` reports the shape it found:

```
kairos.png: 6,789 bytes, carrying 14,125 of source
  label 630x500  (the 5:4 cover shape)
```

## What a cartridge is not

**Not re-encoding-proof.** Ancillary chunks are stripped by anything that
recompresses an image. Distribute cartridges as files — attachments, releases —
not as images posted through a service that re-encodes them. The reader says so
when a payload is missing rather than failing obscurely.

**Not tamper-proof.** The digest catches corruption, not alteration: anyone can
unpack, edit and repack. It is a convenient envelope, not a signature.

## Terms

{terms([
    ("literate source", "A markdown file that is at once a game's code and its documentation"),
    ("tangle", "Extract a markdown game's fenced `game` blocks, in document order"),
    ("cartridge", "A game's markdown embedded in a PNG chunk"),
    ("ancillary chunk", "PNG data a decoder may ignore; where the payload lives"),
    ("gaMe", "The private chunk type this format uses"),
    ("CRC", "Cyclic redundancy check — the per-chunk checksum PNG requires"),
])}
"""


# ---------------------------------------------------------------- adapters


def adapter_guide() -> str:
    hooks = "`lyo_adapter`, `lyo_present`"
    return f"""# Writing an adapter

Discord is a plugin. Nothing in the engine imports it, and the same game runs
over any chat platform someone writes an adapter for.

An adapter is an ordinary Python package that implements {hooks} and advertises
itself under the `lyo` entry-point group.

```python
from lyo.plugins import Adapter, Setting, hookimpl

@hookimpl
def lyo_adapter():
    return Adapter(
        name="irc",
        summary="Play in IRC channels and private messages.",
        run=run,
        settings=(Setting("server", "Host to connect to.", required=True),
                  Setting("nick", "Nickname.", default="lyo")),
    )

def run(engine, values, source=None, services=()):
    ...
```

```toml
[project.entry-points.lyo]
irc = "my_package.irc"
```

`lyo adapters` then lists it, and its settings become configuration paths of the
form `adapter.irc.server`.

Two first-party adapters are worth reading as examples. `lyo.adapters.discord`
is one with a platform SDK behind it; `lyo.adapters.webui` is one with no SDK at
all — a local page over a hand-rolled HTTP server, which is the smaller of the
two and shows the whole contract on its own.

## Installing one

Discovery is by entry point, so an adapter has to live in the same environment
as the command. With lyo installed as a tool, `--with` puts it there:

```bash
uv tool install --editable '.[discord]' --with lyo-irc
lyo adapters                 # it appears, with its own settings
lyo run -a irc
```

Nothing else is required — no registration, no configuration file. Working on
an adapter alongside lyo, `--with-editable` points at its checkout instead, so
both follow their source.

## What run receives

| Argument | |
|---|---|
| `engine` | The simulation. Call `engine.command(user_id, text)` for a typed command, and `engine.begin_flow` / `reply_flow` / `abandon_flow` for a conversation |
| `values` | The resolved settings, as a live dict — read through it rather than copying, so a `lyo reload` that changes a setting takes effect |
| `source` | The game's path, for an owner-triggered reload |
| `services` | Coroutine factories the host wants running alongside, such as the control channel. Accepting this is optional |

## What an adapter owns

Transport and presentation, and nothing else. A command's outcome carries
messages marked `private` or not; mapping that onto direct messages, and
styling the text, is the adapter's business. The game never mentions a platform.

```python
outcome = engine.command(user_id, text)
for message in outcome.messages:
    await (dm if message.private else channel).send(style(message.text))
```

A `lyo_present` implementation restyles outgoing text, receiving the message's
`kind` — a view's name, or `refusal` — so a platform can badge or format by
category.

### Laying out more than a line

A message is always complete as `text`. A view that has structure also reports
it, so an adapter with a richer surface can lay it out instead:

| field | what it is |
|---|---|
| `title` | the view's own heading, if it has one |
| `body` | the lines between the title and the blocks |
| `blocks` | a list of `heading` / `body` sections |

`text` is the flattening of exactly those three, so an adapter that ignores
them loses nothing. The Discord adapter turns a shop's blocks into embed
fields; the browser adapter prints the text. Which view reports structure is
the engine's business, not a game's — a game says `show stock` either way.

## Conversations

A `flow` suspends at each question. The adapter does the waiting, which is what
lets a timeout be the game's own number:

```python
step = engine.begin_flow(user_id, "register")
while step.prompt:
    await channel.send(step.prompt.rendered())
    reply = await wait_for_a_message(timeout=step.prompt.timeout)
    step = engine.reply_flow(user_id, reply)
```

On a timeout, `engine.abandon_flow(user_id)` runs the game's `on timeout:`
handler and saves nothing.

## Terms

{terms([
    ("adapter", "A plugin connecting the engine to one chat platform"),
    ("pluggy", "The plugin library, as used by pytest and tox"),
    ("hookimpl", "The decorator marking a function as a hook implementation"),
    ("entry point", "Packaging metadata that lets a plugin be discovered once installed"),
    ("flow", "A multi-turn conversation the adapter drives one answer at a time"),
    ("outcome", "What a command produced: messages, and whether it was refused"),
])}
"""


# ----------------------------------------------------------- configuration


def configuration() -> str:
    return f"""# Configuration

In the shape of OpenWrt's UCI: `package.section.option`, where a `set` stages a
change and nothing is live until `commit`.

```bash
lyo set adapter.discord.token=abc adapter.discord.prefix=?
lyo changes            # ~ adapter.discord.prefix='?'
lyo commit
lyo show adapter       #   adapter.discord.prefix='?'
```

A staged value is visible to you and invisible to a running service — that
separation is the reason the convention stages at all. `lyo get` shows your
pending edit; the service reads only what has been committed.

| Command | |
|---|---|
| `lyo get <path>` | One option, as you see it |
| `lyo set <path>=<value>...` | Stage a change. `-` reads assignments from standard input |
| `lyo show [prefix]` | Print configuration; `~` marks a staged value, `-` a staged removal |
| `lyo delete <path>` | Stage a removal |
| `lyo changes [package]` | What is waiting for a commit |
| `lyo commit [package]` | Apply |
| `lyo revert [package]` | Discard |

`lyo show` output is valid input to `lyo set -`, so configuration can be copied
between machines with a pipe.

## Paths

| Path | |
|---|---|
| `game.main.source` | Which game to serve |
| `adapter.main.name` | Which adapter to run |
| `adapter.<name>.<key>` | Whatever that adapter declares; see `lyo adapters` |
| `control.main.host` | Bind the control channel to TCP instead of a Unix socket |
| `control.main.port` | Port for that, `0` to choose one |
| `control.main.token` | Required if the host is not loopback |

Settings resolve in order: the adapter's declared default, then a `.env` file,
then configuration, then the environment, then `-s` on the command line.

The two environment names for a setting are `LYO_<ADAPTER>_<KEY>` and the bare
`<ADAPTER>_<KEY>`, so the `DISCORD_TOKEN` a machine already uses for a
discord.py bot is picked up as it stands. A `.env` is looked for beside the
project and one directory above it, in both the current directory and wherever
`lyo.db` is, and ranks below configuration: the file is whatever the host
happens to have, `lyo set` is what you chose. `lyo run --check` prints which of
them each setting came from, naming secrets without printing them.

## Where it lives

One sqlite3 file, `lyo.db` by default or `$LYO_DB`, holding
{len(tables())} tables: saved characters and their inventories, the live
simulation, session state, and this configuration.

Session state is one paragraph per session, written only when asked:

```bash
lyo state "What changed today."
lyo state --history 5
```

Git is the record of what changed and why; session state is the digest on top
of it.

## Terms

{terms([
    ("UCI", "OpenWrt's Unified Configuration Interface, the convention this follows"),
    ("package", "The first path segment: a subsystem, such as `adapter`"),
    ("section", "The second: an instance, such as `discord`"),
    ("staged", "Set but not committed; visible to you, not to a running service"),
    ("committed", "Applied; what a running service reads"),
])}
"""


# ------------------------------------------------------------- deployment


def deployment() -> str:
    return f"""# Running it

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
is activated with `.venv\\Scripts\\activate` rather than `source
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
Windows file URL — `lyo set adapter.webui.assets=C:\\quikchat` or
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

The archive is what git tracks, plus the documents just generated. A file that
is neither tracked nor ignored is refused rather than quietly left out — a new
module missing from an archive is an import error for whoever unpacks it. Commit
it, add it to `.gitignore`, or pass `--with-untracked`. So the order is: write
code, `lyo bundle --no-zip`, commit, `lyo bundle`.

## Terms

{terms([
    ("systemd user unit", "A service definition owned by your login, needing no root"),
    ("Task Scheduler", "The Windows equivalent used here, triggered at logon"),
    ("schtasks", "The command that registers a scheduled task"),
    ("CRLF", "Carriage return plus line feed: the Windows line ending"),
    ("control channel", "The local socket a running instance listens on"),
    ("SIGHUP", "The signal that conventionally means reload, which the unit sends"),
    ("SIGTERM", "The signal a service manager stops a process with"),
    ("loopback", "127.0.0.1 and ::1 -- this machine only"),
    ("linger", "The systemd setting that keeps a user service running after logout"),
])}
"""


# ------------------------------------------------------------- authoring


def authoring() -> str:
    """What a gameworld file can and cannot do, for whoever edits one."""
    equips = ", ".join(f"`{kind}` (the {slot} slot)"
                       for kind, slot in slots().items())
    return f"""# Writing a gameworld

One file is the whole game. A markdown document's fenced `game` blocks are its
source, in document order, and that document is the compilation unit: there are
no includes, and declarations may appear in any order, so a location may name a
monster declared two hundred lines below it.

Everything below is reachable from inside that one file. Nothing below needs
the engine changed, recompiled or restarted — `lyo reload` picks up a new world
without dropping the chat connection.

```bash
lyo lint world/kairos.md     # the only check you need while writing
```

## What you add, and where

| To add | Declare |
|---|---|
| A room, its exits, what it has, who stands in it | `location`, with `npc` inside it |
| A thing to fight, its stats, its gold, its drop table | `monster` |
| Gear, loot, a potion, anything carried | `item` |
| A character class and the kit it starts with | `class` |
| A spell, its cost and what it scales off | `spell` |
| Levelling: what earns points, what a point raises | `track` |
| A player command | `verb` |
| A multi-turn conversation in direct messages | `flow` |
| A timed challenge between two players, and how a duel resolves | `offer` |
| The combat formulas, and what happens on an event | `rules` |
| What a shop sells | `shop` |

{len(declarations())} top-level declarations in all: {', '.join('`' + d + '`' for d in declarations())}.
[language.md](language.md) is the syntax; `kairos.md` is a worked example of
every one of them.

## What you can invent freely

**Stat names.** `str`, `agi`, `int` are conventions of the example game, not the
engine's. A game may declare `luck`, `faith` or `heat` on a class, grant it from
an accessory, raise it from a `track` and read it in a formula. Nothing needs
teaching about it first.

**Directions.** An exit is `<name> to "<location>"`, and the name is any word:
`down to "The Crypt"` works. Exits are two-way unless marked `one way`, so a
connection is declared once. The engine knows the opposites of
north/south, east/west, up/down and in/out; any other name needs `one way` in
both directions, which lint says plainly.

**Item kinds.** Any word, but four of them equip: {equips}. A kind outside that
list is simply carried, which is what `consumable` is — an item with an
`on use:` body. A refusal inside that body aborts the rest of it, which is why
a potion drunk at full health is not spent.

**Numbers and formulas.** `define` names any formula, and every other
declaration can read it. Integer arithmetic throughout, floor division, with
`at least` / `at most` / `capped at` as postfix clamps.

**The words a player types.** `also known as` gives a verb or an item aliases,
and a verb's slots resolve by longest trailing match, so
`attack iron sword dire wolf` finds the wolf and reads the rest as the weapon.

**Your own wording for everything said.** Messages live in the game, not the
adapter: `refuse`, `say`, an `npc`'s line, a flow's prompts and its timeout
notice. Emoji included.

The exception is a `show`n view. Its scaffolding is the engine's — `Type:`,
`Price:`, `Your Gold:` — because the engine is what assembles it. What a game
puts inside one is still the game's: an item's name, its flavour line, its
`shown as` glyph and its `worn on` label, and a shop's `named`. A platform
badge like the shop's 🏪 is the adapter's, not either.

## What the game decides, and what the platform decides

A `verb`, `flow` or `offer` marked `public` goes to the room and `private` by
direct message. That is as far as a game's say in presentation goes: whether
"private" means a DM, a thread or a whisper is the adapter's business, and so is
styling. A game that hard-coded Discord would not run anywhere else.

## What you cannot add from inside a gameworld

These are engine vocabulary. A game that needs one of them needs the engine
changed — which is a Python change, not a markdown one.

**Statements.** The verbs of the language are fixed:
{_statement_list()},
plus `for every <selector>:` and `loop:`. There is no way to define a new one
from inside a game.

**Events.** A handler hangs off one of {', '.join('`on ' + h + '`' for h in handlers())}.
An invented event name is reported as `unknown-handler` rather than silently
never firing.

**Views.** `show` renders one of {', '.join('`' + v + '`' for v in views())}.
These are the only screens the engine draws; everything else a player sees is a
message your game wrote.

**Selectors.** `for every` iterates one kind of thing, narrowed by
{', '.join('`' + q + '`' for q in qualifiers())} and optionally `here`. There is
no filtering by arbitrary condition.

**Free-form state.** There are no variables, flags or counters. What persists is
fixed: a player's stats, hp/mp, gold, inventory, equipment, location and `track`
points, plus wounded monsters with the list of who hurt them, and duels in
progress. Quest chains, "has spoken to the smith", a day counter — none of these
have anywhere to live yet.

**Time.** The only clocks are an `offer`'s expiry and an `ask`'s timeout.
Nothing fires on a schedule, and nothing happens while no one is typing.

**Randomness beyond what is declared.** Drop chances and gold ranges are
rolled by the engine. A game cannot roll its own dice in a formula.

**Fractions.** Integers only, and division floors. `weapon.scales / 2` on an
odd number rounds down, everywhere, always.

**Another file.** No includes, no imports, no shared library of items between
games. One document, which is also how a game is shipped: as that markdown, or
packed into a PNG cartridge whose picture is the label.

## The loop while writing

`lyo lint` resolves the whole document and reports everything at once, pointing
at the line and column in the markdown you edit — not in the extracted source,
and not in the PNG if that is what you handed it.

```
kairos.md:77:10: error[unknown-monster] no monster named "Goblin Scowt" -- did you mean "Goblin Scout"?
     77 |   spawns "Goblin Scowt", "Dire Wolf"
          |          ^
```

It catches a misspelled name with a suggestion, a duplicate or clashing `id`, an
exit with no way back, an item nothing grants or sells, a shop in a location
without the feature, a placeholder no message can fill, and a stat nothing
raises. Every diagnostic it can report:

{', '.join('`' + c + '`' for c in codes())}

Warnings are shown by default and are not errors — a game with warnings runs.
`--no-warnings` hides them, `--stats` summarises the world that resolved, and
`lyo run --check` validates the settings as well, then stops without
connecting.

## Identity, and why renaming is safe

Every declaration has an `id`, a slug of its name unless you give one. Saved
characters refer to the id, so renaming `"Iron Sword"` to `"Rusted Longsword"`
keeps the swords players are carrying — as long as the id does not move:

```game
item "Rusted Longsword" is a weapon:
  id iron_sword
```

Lint rejects two declarations claiming one id.

## Terms

{terms([
    ("declaration", "A top-level definition: a location, item, verb and so on"),
    ("gameworld", "One markdown document: a game's source and its documentation at once"),
    ("tangle", "Extract the fenced `game` blocks, in document order"),
    ("cartridge", "That markdown packed into a PNG whose picture is the label"),
    ("slot", "Either a verb argument `<monster>`, or the place an item equips"),
    ("track", "A progression: what earns points, and what a point raises"),
    ("handler", "An `on <event>:` body the engine runs at a fixed moment"),
    ("view", "A screen the engine draws, named by `show`"),
    ("clamp", "A postfix bound: `at least`, `at most`, `capped at`"),
    ("lint", "Resolve a game and report every problem, with line and column"),
])}
"""

DOCUMENTS = (
    Document("README.md", "lyo Engine", readme,
             ("src/lyo/cli/__init__.py", "src/lyo/adapters/discord/__init__.py",
              "src/lyo/adapters/webui/__init__.py",
              "pyproject.toml", "src/lyo/lang/grammar/game.lark")),
    Document("docs/authoring.md", "Writing a gameworld", authoring,
             ("src/lyo/lang/grammar/game.lark", "src/lyo/lang/resolve.py",
              "src/lyo/engine/execute.py", "src/lyo/engine/views.py",
              "src/lyo/lang/model.py")),
    Document("docs/language.md", "The lyo language", language,
             ("src/lyo/lang/grammar/game.lark", "src/lyo/lang/model.py",
              "src/lyo/lang/resolve.py", "src/lyo/engine/execute.py")),
    Document("docs/cartridge.md", "One file, two forms", cartridge,
             ("src/lyo/cartridge/png.py", "src/lyo/cartridge/markdown.py")),
    #  Both adapters' own words are the page, so either one changing makes it
    #  stale -- that is the whole point of a page generated from what they
    #  declare about themselves.
    Document("docs/platforms.md", "Platforms", platforms,
             ("src/lyo/adapters/discord/__init__.py",
              "src/lyo/adapters/webui/__init__.py",
              "src/lyo/plugins/__init__.py")),
    Document("docs/adapters.md", "Writing an adapter", adapter_guide,
             ("src/lyo/plugins/__init__.py",
              "src/lyo/adapters/discord/__init__.py",
              "src/lyo/adapters/webui/__init__.py")),
    Document("docs/configuration.md", "Configuration", configuration,
             ("src/lyo/store/config.py", "src/lyo/store/schema.sql",
              "src/lyo/cli/__init__.py")),
    Document("docs/deployment.md", "Running it", deployment,
             ("src/lyo/service/__init__.py", "src/lyo/control.py",
              "src/lyo/cli/__init__.py")),
)
