# Kairos — Behavior Specification

A description of the bot **as players experience it**, written from the running
code but containing none of it. The purpose is preservation: if the
implementation is rewritten, this is the contract the rewrite must still honor.

Everything is a `!` prefixed text command in a Discord channel or DM. There is
no AI narration — all outcomes are fixed rules and dice.



## 1. Getting started

`!register` is the entry point, and it runs in DMs.

1. In the channel: a note telling the player to check their DMs.
2. In DMs: "What is your character's name?" — the reply is taken verbatim,
   with surrounding whitespace trimmed. Any name is accepted; no uniqueness
   check, no length limit, no profanity filter.
3. A numbered class menu, in this fixed order: **1 Warrior, 2 Mage, 3 Rogue,
   4 Paladin**, each with a one-line blurb. The player may reply with either
   the number or the exact class name. Anything else re-prompts, and it will
   keep re-prompting indefinitely until a valid choice arrives.
4. Confirmation naming the character, class and starting location.

Each DM step waits **120 seconds**. A timeout, closed DMs, or any other
failure posts a single "registration timed out or failed" message back in the
original channel, and nothing is saved.

Calling `!register` when already registered refuses and changes nothing.
**There is no way for a player to delete or re-roll a character.**

### Starting state

Every new character begins with **20 HP**, **10 gold**, in **Oakhaven
Village**, with the stats, MP and kit of their class.

Kit weapons are **auto-equipped**. Kit armor and shields are **not** — a
Warrior starts holding a Wooden Shield in their inventory but unequipped, with
0 DEF, which is a common source of confusion.

| Class   | STR | AGI | INT | MP  | Starting kit                                |
| ------- | --- | --- | --- | --- | ------------------------------------------- |
| Warrior | 8   | 5   | 3   | 5   | Iron Sword, Health Potion ×2, Wooden Shield |
| Mage    | 3   | 4   | 9   | 20  | Apprentice Staff, Mana Potion ×2, Spellbook |
| Rogue   | 4   | 9   | 3   | 8   | Dual Daggers, Lockpick ×3, Smoke Bomb       |
| Paladin | 7   | 4   | 5   | 12  | Warhammer, Health Potion, Holy Symbol       |

Mana Potions **cannot be used** — they are inert inventory items, despite the
name and despite the Mage starting with two. Spellbook, Lockpick, Smoke Bomb
and Holy Symbol are likewise inert: they can be owned, and nothing else.

---

## 2. The world

Six locations, fixed. Movement is compass-based and every path is two-way.

| Location         | Inn | Shop | Monsters                | Exits                                     |
| ---------------- | --- | ---- | ----------------------- | ----------------------------------------- |
| Oakhaven Village | yes | yes  | —                       | N → Whispering Woods, S → Kingsroad       |
| Whispering Woods | —   | —    | Goblin Scout, Dire Wolf | S → Oakhaven Village, E → The Ruined Keep |
| Kingsroad        | —   | —    | Bandit                  | N → Oakhaven Village, E → Ironforge City  |
| Ironforge City   | yes | —    | —                       | W → Kingsroad, N → Dragon's Peak          |
| The Ruined Keep  | —   | —    | Skeleton Guard          | W → Whispering Woods, S → Dragon's Peak   |
| Dragon's Peak    | —   | —    | Young Red Dragon        | S → Ironforge City, N → The Ruined Keep   |

NPCs stand in Oakhaven Village (Elder Thomas, Garth, Mira) and Ironforge City
(Master Vane, Borin). They are **scenery**: `!look` lists their names and
roles, and there is no way to talk to them. Each has written dialogue that
players never see.

### Moving

`!travel <direction>` or `!travel <location>`, aliases `!go` and `!move`.
Directions accept full words or single letters (`north`/`n`). Only the four
compass directions exist; there is no diagonal or vertical movement.

Only directly connected locations are reachable — there is no multi-step
pathfinding, so getting from Oakhaven Village to Dragon's Peak takes two or
three separate commands.

Travel is refused while in a duel. Travel is **not** refused while a duel
challenge is pending, in either direction.

Arriving somewhere may trigger a monster respawn (§5).

### Looking around

`!look` posts **in the channel** and shows: the location name and description,
every living monster with current and max HP, NPC names and roles, the names of
other registered players standing in the same location, and the caller's own
HP and MP. A line about the inn or shop appears when one is present.

`!map` is sent **by DM** and shows the current location's description, its exit
list with direction arrows, and a fixed hand-drawn ASCII map of all six
locations.

---

## 3. Fighting monsters

**Monsters are shared.** Each location has one of each of its monsters, and
their HP is global to that location — if one player wounds the Dire Wolf, every
other player finds it wounded. Damage dealt is never per-player.

`!attack <target>`, or `!attack <weapon> <target>` to use something other than
the equipped weapon. `hands`, `hand`, `fist`, `fists` or `punch` all mean bare
fists. A named weapon must be in the player's inventory.

Targets match on the **longest trailing run of words** that names a living
monster, with partial matches allowed — so `!attack wolf` finds the Dire Wolf,
and everything before the matched name is read as the weapon. There is no
disambiguation prompt; the first match wins.

### Damage

- The player deals **max(1, ATK)**, where **ATK = weapon damage + (scaling stat ÷ 2, rounded down)**.
- **Monster DEF does not exist.** Armor values on monsters are not modeled at all.
- Then **every living monster in the location hits back**, each for
  **max(1, its STR − player DEF)**. The total is reported as one number with
  the retaliators named.
- **DEF = body armor + shield.** Nothing else reduces damage.

The practical consequence: fighting in a location with two monsters means
taking two monsters' worth of damage every single turn, including from the one
not being attacked, and clearing a location means tanking everything in it.
Retaliation is not a counter-attack — it happens on the player's turn, whether
or not their own attack landed a kill, and only stops when nothing is left
alive.

A turn's output reports, in order: the attack, damage dealt with ATK shown, the
target's remaining HP, any defeat, any loot, the retaliation with DEF shown,
any level-ups, and the player's own remaining HP.

### Monsters

Only **STR** matters in combat — it is the monster's entire damage output. AGI
and INT are recorded and never used.

| Monster          | HP  | STR | AGI | INT | Gold   | Drops                                               |
| ---------------- | --- | --- | --- | --- | ------ | --------------------------------------------------- |
| Goblin Scout     | 12  | 3   | 7   | 2   | 2–5    | Goblin Ear (always), Rusty Cleaver (10%)            |
| Dire Wolf        | 18  | 6   | 6   | 1   | 3–6    | Wolf Pelt (always), Health Potion (15%)             |
| Bandit           | 15  | 5   | 5   | 4   | 5–10   | Stolen Coin Purse (always), Dual Daggers (8%)       |
| Skeleton Guard   | 22  | 7   | 3   | 1   | 8–15   | Bone Fragment ×1–2 (always), Chainmail (5%)         |
| Young Red Dragon | 55  | 12  | 8   | 8   | 50–100 | Dragon Scale ×1–3 (always), Dragon's Heart (always) |

### Casting

`!cast <target>`, or `!cast <spell> <target>`. **Fireball is the only spell in
the game** — 5 MP, damage **3 + (INT ÷ 2)**. It is available to every class
from the start; no spell is ever learned, bought or dropped.

MP is checked before the cast and deducted after it resolves. Casting draws
retaliation exactly like attacking does.

### Falling

At **0 HP** a player has "fallen" and cannot attack or cast. They can still
travel, drink a potion, rest, shop and be looted-for. There is **no death
penalty** — no lost gold, no lost items, no respawn timer, no corpse run.
Recovery is a Health Potion or walking to an inn.

---

## 4. Loot and party sharing

A kill rolls gold within the monster's range, then rolls each drop
independently against its chance.

Every player who has damaged a monster since it last respawned shares its loot:

- **Gold** is divided evenly, and the remainder from the division goes to
  whoever landed the killing blow.
- **Items are not divided** — every contributor receives their own full copy of
  every drop. Two players splitting a dragon get two Dragon's Hearts.
- Solo kills behave as a party of one: everything goes to the killer.

Contributors are tracked by damage since the last respawn, which means **a
player who leaves the location, or who has fallen, still receives their share.**
Walking away mid-fight costs nothing.

Messages distinguish solo loot from party loot, naming the per-player gold
share and the killer's leftover bonus.

> *Baseline:* none of this existed. Loot went entirely to whoever landed the
> killing blow, with no contributor tracking and no sharing of any kind.
> Shared loot arrived with the PvP port.

---

## 5. Respawning

Monsters return to full HP when a player **travels into** a location that has
monsters and that **no other player is currently standing in**. All monsters
there are restored at once and the contributor list is wiped. The arrival
message names whichever monsters were actually revived.

There is no timer. A location occupied continuously by at least one player
never respawns, and a location nobody visits stays cleared indefinitely. Two
players can keep a location permanently farmed-out, or reset it for each other
by taking turns leaving and returning.

---

## 6. Leveling

There are no character levels and no experience bar. Five things grow
independently, each from **doing the thing**:

| Track           | Grows from                                             | Cost of next point           | Gain |
| --------------- | ------------------------------------------------------ | ---------------------------- | ---- |
| STR / AGI / INT | attacking or casting with something that scales off it | 5 + (2 × current value) uses | +1   |
| Max HP          | being hit                                              | 5 hits                       | +2   |
| Max MP          | casting                                                | 5 casts                      | +2   |

Per turn: an attack trains the equipped weapon's scaling stat by 1. A cast
trains the spell's stat by 1 **and** Max MP by 1. Either also trains Max HP by
1 **if the player took damage that turn**. Leftover progress always carries
over, and a raise in Max HP or Max MP adds the same amount to current HP or MP.

Because stat costs scale with the current value, a Mage's INT 9 needs 23 casts
for the next point while their STR 3 needs 11 — classes drift toward
all-rounders over a long enough game. `!inventory` shows exact progress on all
five tracks.

---

## 7. Resting

`!rest` (aliases `!sleep`, `!inn`) fully restores **both HP and MP** at
**Oakhaven Village** and **Ironforge City**. It is free, instant, unlimited and
has no cooldown. Anywhere else it is refused with the inn list. Already-full
players get a "nothing to do" message.

Resting is the only MP recovery in the game, since Mana Potions do not work.

---

## 8. Shopping

The shop exists only in **Oakhaven Village**, and the player must be standing
there.

`!shop` sends the stock list by DM and then **stays open as a conversation**:
any message naming an item buys it immediately, and `done`, `exit`, `leave`,
`cancel` or `quit` closes it. It times out after **120 seconds** of silence.
There is no confirmation step and no basket — each message is a purchase.

`!buy <item name>` buys a single item from the channel instead.

Items are **buy-only; nothing can be sold**, so gold is purely accumulative.
Prices are fixed and stock is unlimited.

| Item                       | Price | Kind                           |
| -------------------------- | ----- | ------------------------------ |
| Padded Sling               | 15    | weapon, AGI                    |
| Thick Leather Gloves       | 15    | armor (body slot)              |
| Rusty Cleaver              | 20    | weapon, STR                    |
| Reinforced Tunic           | 20    | armor (body)                   |
| Chipped Buckler            | 22    | shield                         |
| Notched Iron Shortsword    | 25    | weapon, STR                    |
| Lucky Copper Coin          | 25    | accessory — cannot be equipped |
| Boiled Leather Vest        | 28    | armor (body)                   |
| Novice Weaver's Robe       | 28    | armor (body)                   |
| Splintered Oak Bow         | 30    | weapon, AGI                    |
| Encumbered Miner's Lantern | 30    | accessory — cannot be equipped |
| Apprentice's Ash Staff     | 35    | weapon, INT                    |

Buying an unequippable item warns that it is flavor only. Two of the twelve
items on sale can never be used for anything.

> *Baseline:* **all twelve were unequippable.** Shop stock was defined in its
> own separate table and never registered as weapons or armor, so `!equip`
> refused every purchase with "cannot be equipped as gear" and the
> flavor-item warning printed on every single sale. The shop was entirely
> cosmetic and **gold had no mechanical use in the game.** The YAML migration
> gave ten of the twelve real types and scaling stats, which is the single
> largest gameplay change between the frozen original and today.

---

## 9. Items and equipment

Three slots: **weapon**, **body armor**, **shield**. `!equip <item>` puts an
owned item in the slot its type dictates, replacing whatever was there. Nothing
is ever consumed by equipping and there are no requirements, so any class can
wield anything.

Only **weapon damage** and **armor/shield DEF** affect play. Every other listed
stat — crit chance, evasion, max MP bonuses, luck — and every `effect` line
such as bleed, blocking or lantern illumination is **displayed in the shop and
does nothing.** A player comparing two items on their descriptions is being
misled.

Equipment effective values:

| Weapon                  | Damage | Scales |
| ----------------------- | ------ | ------ |
| Fists (fallback)        | 1      | STR    |
| Rusty Cleaver           | 2      | STR    |
| Padded Sling            | 2      | AGI    |
| Apprentice's Ash Staff  | 2      | INT    |
| Apprentice Staff        | 3      | INT    |
| Dual Daggers            | 3      | AGI    |
| Notched Iron Shortsword | 3      | STR    |
| Iron Sword              | 4      | STR    |
| Splintered Oak Bow      | 4      | AGI    |
| Warhammer               | 5      | STR    |

| Armor                | DEF | Slot   |
| -------------------- | --- | ------ |
| Clothes (fallback)   | 0   | body   |
| Chipped Buckler      | 1   | shield |
| Robes                | 1   | body   |
| Thick Leather Gloves | 1   | body   |
| Wooden Shield        | 2   | shield |
| Leather Armor        | 2   | body   |
| Reinforced Tunic     | 2   | body   |
| Boiled Leather Vest  | 3   | body   |
| Chainmail            | 4   | body   |

Note that the Splintered Oak Bow's listed `-1 DEF` and the Boiled Leather
Vest's `-1 evasion` are cosmetic. Thick Leather Gloves occupy the **body**
slot despite being gloves, so wearing them means wearing no chest armor.

> *Baseline:* only **Fists, Iron Sword, Apprentice Staff, Dual Daggers and
> Warhammer** were equippable weapons, and only **Clothes, Robes, Leather
> Armor, Chainmail and Wooden Shield** equippable armor — the five of each that
> come from class kits and monster drops. Every shop weapon and armour piece in
> the tables above was inert. A player's gear therefore never improved except
> by a 5% Chainmail drop from a Skeleton Guard or an 8% Dual Daggers drop from
> a Bandit.

Unequipped items are never lost and a player can carry any number of them;
inventory stacks by quantity and has no weight or size limit.

### Using items

`!use <item>` works on consumables only. **Health Potion is the only working
consumable in the game**: it restores **8 HP**, capped at max HP. Used at full
health it is **refused and not consumed**. `potion` is accepted as a shorthand.

Trying to use gear redirects the player to `!equip`. Trying to use anything
else reports that it stays in the inventory.

---

## 10. Player versus player

> *Baseline:* **PvP did not exist.** There were no duel, challenge, accept,
> decline or forfeit commands, and nothing in this section applies to the
> frozen original. It arrived wholesale from the second copy.

`!duel @user` (alias `!challenge`) issues a challenge. Both players must be
registered, alive, in the same location, not already dueling, and the target
must not already have a pending challenge. The target has **60 seconds** to
`!accept` or `!decline` before it expires with a notice.

Once a duel starts, `!attack` and `!cast` **need no target** — they
automatically hit the opponent, and monsters in the location are ignored
entirely. `!forfeit` concedes and hands the win to the opponent.

Duel combat differs from monster combat in three ways:

- Damage is **max(1, power − opponent DEF)** — **armor actually works** here.
- **Nobody hits back.** Each command is one one-way hit.
- **There is no turn order.** Either player may act as often and as fast as
  they like, so a duel is substantially a typing-speed contest.

Experience: the attacker trains their weapon's stat (or spell stat plus Max MP);
the defender trains Max HP by 1 for being hit.

The duel ends when one side reaches 0 HP. **There is no prize** — no gold, no
items, no ranking, no record. The loser is simply at 0 HP like any other
death, and the only lasting effect of a duel is the stat growth both sides
earned from it.

`!use` is **not** blocked during a duel, so potions can be drunk mid-fight and
whoever brought more of them has a durable advantage.

---

## 11. Information commands

`!inventory` (alias `!inv`), by DM: name, class, location, HP, MP, gold, ATK
and DEF with the gear producing them, all five leveling tracks with exact
progress, and the item list with quantities.

`!viewdb` (alias `!viewDB`), by DM: every registered player's name and current
location. This is the only way to see other players globally, and it exposes
every character's position to everyone.

`!help`, by DM: a categorized command list, with an extra owner-only section
shown only to the bot owner.

---

## 12. Presentation conventions

Output is Discord markdown, heavily emoji-prefixed, with key numbers bolded.

Long or private output — help, map, inventory, roster, shop — is **sent by DM**,
with a short "check your DMs" note left in the channel that deletes itself
after 3 seconds. If the player's DMs are closed, the content is posted in the
channel instead, except for `!shop`, which instead tells them to use `!buy`.

Combat, travel, looking, resting and all duel messages are posted **in the
channel**, so the whole server follows a fight as it happens.

Unregistered players attempting any command get the same "use `!register`
first" warning.

---

## 13. What a restart destroys

The owner-only `!reload` (alias `!restart`) validates everything before
restarting and refuses, with the errors shown in the channel, if anything is
broken. A successful restart posts "back online" when it returns.

Restarting **resets all monster HP to full everywhere** and **wipes every
active duel and pending challenge**. Player characters, inventories, gold and
progress are stored and always survive.

Monster state and duels existing only in memory is the single most
behavior-visible consequence of a restart: a party three turns into a dragon
fight loses all of it.

---

## 14. Known rough edges, as players meet them

Behaviors that are surprising but currently real, worth preserving knowingly or
fixing deliberately. Items 1–6 came in with the PvP port and do **not** exist
in the baseline; 7–9 are original, and 7 was *worse* there (see §8):

1. **A challenger can walk away and still duel.** Travel is only blocked for
   players already in a duel, and accepting re-checks nothing, so a challenge
   accepted after the challenger has left starts a duel between two different
   locations.
2. **The killing blow can leave the loser standing at 2 HP.** The defender's
   Max HP growth is applied after the damage, so a level-up on the fatal hit
   tops their current HP back up. They are announced as fallen, the duel ends,
   and they are alive.
3. **`!duel` with a plain name replies nothing at all.** Only an @mention
   works; a typed name fails silently and the player sees no response.
4. **Duels are won on typing speed**, having no turn order.
5. **Potions work mid-duel**, making duels partly a contest of potion stock.
6. **Loot reaches players who left or fell**, since contribution is never
   re-checked against who is still present.
7. **Two of twelve shop items can never be equipped or used**, and most listed
   item stats do nothing.
8. **Mana Potions don't work**, including the two every Mage starts with.
9. **A shield in the starting kit is not equipped**, so new Warriors are at
   0 DEF while appearing to own a shield.

---

## 15. Player state that must survive a migration

Saved permanently in SQLite (`players.db`); everything else is in memory and
expendable. Two tables, currently holding **4 characters and 13 inventory
rows**.

**Characters**, one row per Discord user:

| Field                                            | Meaning                                                    |
| ------------------------------------------------ | ---------------------------------------------------------- |
| user_id                                          | Discord user ID — the primary key and the only identity    |
| name, class                                      | chosen at registration, never editable afterward           |
| hp, max_hp                                       | current and maximum health                                 |
| mp, max_mp                                       | current and maximum magic                                  |
| gold                                             | spendable currency                                         |
| str, agi, int                                    | the three stats                                            |
| str_exp, agi_exp, int_exp                        | progress toward the next point of each                     |
| hp_exp, mp_exp                                   | progress toward the next Max HP / Max MP raise             |
| location                                         | which of the six locations they are standing in            |
| equipped_weapon, equipped_armor, equipped_shield | item names, or the fallbacks `Fists`, `Clothes` and `None` |

**Inventory**, one row per player per item, keyed on that pair, with a quantity
column for stacking.

### What matters for a future import

- **Items are identified by their display-name string**, in both the equipment
  fields and the inventory table. There are no item IDs. Renaming an item in a
  rewrite orphans every existing copy, and renaming a location orphans every
  player standing in it. Any migration must map old names to new ones
  explicitly.
- **The three fallback names are load-bearing**: `Fists`, `Clothes` and the
  literal string `None` mean "nothing equipped" and must keep meaning that.
- **Progress is split across two columns per track** — a value and its
  leftover exp. Dropping the exp columns silently steals partial progress.
- Nothing records when a character was created, last played, or anything
  historical, so no play history can be reconstructed. There is also no
  per-guild separation: one character per Discord user, globally.

A full dump of the current contents can be taken from the database file at any
time; only the shape above needs preserving in advance.
