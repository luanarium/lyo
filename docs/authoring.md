# Writing a gameworld

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

12 top-level declarations in all: `game`, `location`, `monster`, `item`, `class`, `spell`, `track`, `verb`, `flow`, `offer`, `rules`, `shop`.
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

**Item kinds.** Any word, but four of them equip: `weapon` (the weapon slot), `body armor` (the armor slot), `shield` (the shield slot), `accessory` (the accessory slot). A kind outside that
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
`buy`, `create player`, `deal`, `equip`, `give`, `heal`, `move`, `refuse`, `respawn`, `restore`, `roll`, `say`, `show`, `split`, `stop`, `take`, `trigger`,
plus `for every <selector>:` and `loop:`. There is no way to define a new one
from inside a game.

**Events.** A handler hangs off one of `on attack`, `on buy`, `on cast`, `on enter`, `on equip`, `on kill`, `on timeout`, `on use`.
An invented event name is reported as `unknown-handler` rather than silently
never firing.

**Views.** `show` renders one of `help`, `inventory`, `location`, `map`, `roster`, `stock`.
These are the only screens the engine draws; everything else a player sees is a
message your game wrote.

**Selectors.** `for every` iterates one kind of thing, narrowed by
`living`, `other`, `fallen` and optionally `here`. There is
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

`alias-clash`, `bad-range`, `exit-conflict`, `id-clash`, `many-defaults`, `no-default`, `no-opposite`, `no-start`, `orphan-item`, `shop-without-feature`, `unknown-declaration`, `unknown-handler`, `unknown-item`, `unknown-location`, `unknown-monster`, `unknown-placeholder`, `unknown-verb`, `untracked-stat`

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

| Term        | Definition |
| ----------- | ---------- |
| declaration | A top-level definition: a location, item, verb and so on |
| gameworld   | One markdown document: a game's source and its documentation at once |
| tangle      | Extract the fenced `game` blocks, in document order |
| cartridge   | That markdown packed into a PNG whose picture is the label |
| slot        | Either a verb argument `<monster>`, or the place an item equips |
| track       | A progression: what earns points, and what a point raises |
| handler     | An `on <event>:` body the engine runs at a fixed moment |
| view        | A screen the engine draws, named by `show` |
| clamp       | A postfix bound: `at least`, `at most`, `capped at` |
| lint        | Resolve a game and report every problem, with line and column |

<!-- generated by lyo 0.1.0 from b767ac4c12e565ae -->
