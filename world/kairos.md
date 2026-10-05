# Kairos

A six-location fantasy game for a chat room. Every outcome is a fixed rule or a
die roll; nothing here is narrated by a model.

This file is the game. The prose is for you, the fenced blocks are the source,
and both travel together — as this document, or packed into a PNG cartridge.

## Starting out

A new character begins in Oakhaven Village with 20 health and 10 gold, plus the
stats and kit of their class.

```game
game "Kairos":
  players start at "Oakhaven Village" with 20 hp, 10 gold
```

Four classes. A class fixes the three stats and the starting magic pool; the kit
is equipped on arrival, so a Warrior walks out already holding their shield.

<details><summary>The four classes</summary>

```game
class "Warrior":
  "A stalwart fighter who trades speed for raw power."
  8 str, 5 agi, 3 int, 5 mp
  starts with "Iron Sword", "Wooden Shield"
  starts carrying 2 "Health Potion"

class "Mage":
  "A scholar of fire, frail in body and deep in reserve."
  3 str, 4 agi, 9 int, 20 mp
  starts with "Apprentice Staff"
  starts carrying 2 "Mana Potion", "Spellbook"

class "Rogue":
  "Quick hands, quicker feet, and a habit of being elsewhere."
  4 str, 9 agi, 3 int, 8 mp
  starts with "Dual Daggers"
  starts carrying 3 "Lockpick", "Smoke Bomb"

class "Paladin":
  "Armoured conviction, with just enough grace to mend a wound."
  7 str, 4 agi, 5 int, 12 mp
  starts with "Warhammer"
  starts carrying "Health Potion", "Holy Symbol"
```

</details>

## The world

Six locations. Exits are two-way, so each connection is declared once and the
return path comes for free — six declarations give all twelve passages.

Oakhaven Village and Ironforge City have inns. Only Oakhaven has a shop.

<details><summary>The six locations</summary>

```game
location "Oakhaven Village":
  "Timber halls ring a muddy square, and smoke leans off the thatch."
  has inn, shop
  north to "Whispering Woods"
  south to "Kingsroad"
  npc "Elder Thomas" as "village elder":
    says "The woods have grown restless of late."
  npc "Garth" as "blacksmith":
    says "Bring me dragon scale and we will talk."
  npc "Mira" as "herbalist":
    says "Potions keep better than promises."

location "Whispering Woods":
  "Ancient oaks crowd the path, their branches knitted overhead."
  east to "The Ruined Keep"
  spawns "Goblin Scout", "Dire Wolf"

location "Kingsroad":
  "A rutted trade road, straight and badly watched."
  east to "Ironforge City"
  spawns "Bandit"

location "Ironforge City":
  "Forge light stains the undersides of the clouds."
  has inn
  north to "Dragon's Peak"
  npc "Master Vane" as "guild master":
    says "Work is plentiful. Survivors are not."
  npc "Borin" as "armourer":
    says "Chainmail turns a blade. Gloves turn a conversation."

location "The Ruined Keep":
  "Fallen stone, and something patient in the dark below."
  south to "Dragon's Peak"
  spawns "Skeleton Guard"

location "Dragon's Peak":
  "Bare rock, hot wind, and the smell of a kept fire."
  spawns "Young Red Dragon"
```

</details>

## Monsters

Monsters are shared. Each location holds one of each of its monsters and their
health is common to everyone standing there — wound the wolf and the next player
finds it wounded.

Only strength reaches combat. Agility and intellect are recorded for the record.

<details><summary>The five monsters</summary>

```game
monster "Goblin Scout":
  12 hp, 3 str, 7 agi, 2 int
  drops 2 to 5 gold
  drops "Goblin Ear"
  drops "Rusty Cleaver" 10% of the time

monster "Dire Wolf":
  18 hp, 6 str, 6 agi, 1 int
  drops 3 to 6 gold
  drops "Wolf Pelt"
  drops "Health Potion" 15% of the time

monster "Bandit":
  15 hp, 5 str, 5 agi, 4 int
  drops 5 to 10 gold
  drops "Stolen Coin Purse"
  drops "Dual Daggers" 8% of the time

monster "Skeleton Guard":
  22 hp, 7 str, 3 agi, 1 int
  drops 8 to 15 gold
  drops 1 to 2 "Bone Fragment"
  drops "Chainmail" 5% of the time

monster "Young Red Dragon":
  55 hp, 12 str, 8 agi, 8 int
  drops 50 to 100 gold
  drops 1 to 3 "Dragon Scale"
  drops "Dragon's Heart"
```

</details>

## Items

Three slots carry gear: a weapon, body armour, and a shield. An accessory slot
holds the odds and ends. Nothing has a level requirement, so any class can wield
anything it can afford.

A weapon's damage is its own, plus half the stat it scales off. Armour and
shields contribute defence and nothing else.

<details><summary>Weapons</summary>

```game
item "Fists" is the default weapon:
  also known as "hands", "hand", "fist", "punch"
  1 damage scaling str

item "Rusty Cleaver" is a weapon:
  2 damage scaling str
  costs 20 gold

item "Padded Sling" is a weapon:
  2 damage scaling agi
  costs 15 gold

item "Apprentice's Ash Staff" is a weapon:
  2 damage scaling int
  costs 35 gold

item "Apprentice Staff" is a weapon:
  3 damage scaling int

item "Dual Daggers" is a weapon:
  3 damage scaling agi

item "Notched Iron Shortsword" is a weapon:
  3 damage scaling str
  costs 25 gold

item "Iron Sword" is a weapon:
  4 damage scaling str

item "Splintered Oak Bow" is a weapon:
  4 damage scaling agi
  costs 30 gold

item "Warhammer" is a weapon:
  5 damage scaling str
```

</details>

<details><summary>Armour and shields</summary>

Thick Leather Gloves take the body slot, as specified — wearing them means
wearing no chest armour.

```game
item "Clothes" is the default body armor:
  0 def

item "Robes" is body armor:
  1 def

item "Thick Leather Gloves" is body armor:
  1 def
  costs 15 gold

item "Leather Armor" is body armor:
  2 def

item "Reinforced Tunic" is body armor:
  2 def
  costs 20 gold

item "Novice Weaver's Robe" is body armor:
  2 def
  costs 28 gold

item "Boiled Leather Vest" is body armor:
  3 def
  costs 28 gold

item "Chainmail" is body armor:
  4 def

item "Chipped Buckler" is a shield:
  1 def
  costs 22 gold

item "Wooden Shield" is a shield:
  2 def
```

</details>

<details><summary>Potions, accessories and trophies</summary>

Both potions work. A potion drunk at full health is refused rather than wasted.

```game
item "Health Potion" is consumable:
  also known as "potion"
  on use:
    refuse "⚠️ You are already at full health." when hp is max_hp
    take 1 item from player
    restore 8 hp
    say "🧪 {player} drinks a Health Potion — ❤️ {hp}/{max_hp} HP"

item "Mana Potion" is consumable:
  on use:
    refuse "⚠️ Your reserve is already full." when mp is max_mp
    take 1 item from player
    restore 8 mp
    say "🧪 {player} drinks a Mana Potion — 💧 {mp}/{max_mp} MP"

item "Lucky Copper Coin" is an accessory:
  grants 1 luck
  costs 25 gold

item "Encumbered Miner's Lantern" is an accessory:
  grants 1 def
  costs 30 gold

item "Spellbook" is a trinket:
  "Dense, annotated, and of no use in a fight."

item "Lockpick" is a trinket:
  "There is nothing in Kairos that locks."

item "Smoke Bomb" is a trinket:
  "No one here is looking the other way."

item "Holy Symbol" is a trinket:
  "Comforting. Inert."

item "Goblin Ear" is a trophy:
  "Proof, of a sort."

item "Wolf Pelt" is a trophy:
  "Still faintly warm."

item "Stolen Coin Purse" is a trophy:
  "Empty. Someone got there first."

item "Bone Fragment" is a trophy:
  "Older than the keep."

item "Dragon Scale" is a trophy:
  "Heavier than it looks."

item "Dragon's Heart" is a trophy:
  "It has not entirely stopped."
```

</details>

## Magic

Fireball is the whole of magic. Every class knows it from the start, and no
spell is ever learned, bought or dropped.

```game
spell "Fireball":
  costs 5 mp
  deals 3 + int / 2 damage scaling int
  provokes retaliation
  known by all
```

## Growing stronger

There are no levels. Five things grow, each from doing the thing, and each
costing more as it rises — which is why a Mage slowly stops being only a Mage.

```game
track str:
  advances when attacking with a weapon scaling str
  next point costs 5 + 2 * str uses
  raises str by 1

track agi:
  advances when attacking with a weapon scaling agi
  next point costs 5 + 2 * agi uses
  raises agi by 1

track int:
  advances when casting a spell scaling int
  next point costs 5 + 2 * int uses
  raises int by 1

track max_hp:
  advances when taking damage
  next point costs 5 uses
  raises max_hp by 2 and heals 2

track max_mp:
  advances when casting
  next point costs 5 uses
  raises max_mp by 2 and restores 2
```

## The rules of a fight

Attacking draws every living monster in the location, not only the one struck.
Clearing a room means tanking everything in it.

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

Loot is shared by everyone who damaged the monster since it last respawned.
Gold divides evenly with the remainder going to whoever landed the last blow;
items are not divided at all, so every contributor receives a full copy of every
drop. Walking away mid-fight costs nothing.

Monsters return to full health when someone travels into a location that nobody
else is standing in. There is no timer, so a room held continuously is a room
permanently cleared.

## Commands

Fighting, travelling and looking are public — the whole room follows a fight.
Anything long or private arrives by direct message.

<details><summary>Fighting</summary>

```game
verb attack <weapon?> <monster>:
  public
  refuse "💀 You have fallen. Use a potion, or walk to an inn." unless alive
  deal atk at least 1 to monster
  say "⚔️ {player} attacks {monster} — 💥 {dealt} damage, 🩸 {monster.hp} HP left"
  say "☠️ {monster} is defeated! 🎁 {loot}" when monster.hp is 0 and not dueling
  then for every living monster here:
    deal its str - def at least 1 to player
  say "↩️ {retaliators} hit back for {taken} — ❤️ {player} on {hp} HP" when taken > 0

verb cast <spell?> <monster>:
  public
  refuse "💀 You have fallen. Use a potion, or walk to an inn." unless alive
  refuse "💧 Not enough magic for that." when mp < spell.cost
  take spell.cost mp from player
  deal spell.damage at least 1 to monster
  say "🔮 {player} casts {spell} at {monster} — 💥 {dealt} damage, 🩸 {monster.hp} HP left"
  say "☠️ {monster} is defeated! 🎁 {loot}" when monster.hp is 0 and not dueling
  then for every living monster here:
    deal its str - def at least 1 to player
  say "↩️ {retaliators} hit back for {taken} — ❤️ {player} on {hp} HP" when taken > 0
```

</details>

<details><summary>Moving and looking</summary>

```game
verb travel <exit>:
  also known as "go", "move"
  public
  refuse "❌ You cannot travel mid-duel. Finish the fight, or forfeit." when dueling
  move player to exit
  say "🥾 {player} travels to 📍 {here}."

verb look:
  public
  show location

verb map:
  private
  show map

verb rest:
  also known as "sleep", "inn"
  public
  refuse "❌ There is no inn here. Inns: Oakhaven Village, Ironforge City." unless here.inn
  refuse "🛏️ You are already fully rested." when hp is max_hp and mp is max_mp
  restore all hp, all mp
  say "🛌 {player} rests at the inn — ❤️ {hp}/{max_hp} HP | 💧 {mp}/{max_mp} MP"
```

</details>

<details><summary>Gear, goods and records</summary>

```game
verb use <item>:
  public
  trigger use on item

verb equip <item>:
  public
  equip item
  say "🛡️ {player} equips {item}."

verb buy <item>:
  public
  refuse "❌ There is no shop here." unless here.shop
  buy item
  say "🛒 {player} buys {item} — 🪙 {gold} gold left"

verb inventory:
  also known as "inv"
  private
  show inventory

verb viewdb:
  private
  show roster

verb help:
  private
  show help
```

</details>

## Conversations

Registration and the shop are conversations rather than single commands. Both
run in direct messages and both give up after two minutes of silence.

```game
flow register:
  private
  refuse "⚠️ You already have a registered character." when registered
  ask name: "What is your character's name?"
    accepts any text, trimmed
    times out after 120 seconds
  ask chosen: "Choose a class:"
    offers every class by number, name
    reprompts forever
    times out after 120 seconds
  create player named name as chosen
  say "🛡️ {name} the {chosen} begins in 📍 {start}."
  on timeout:
    say "⚠️ Registration timed out or failed." publicly

flow shop:
  private
  refuse "❌ There is no shop here." unless here.shop
  show stock
  loop:
    ask choice: "Name an item to buy, or say done."
      accepts "done", "exit", "leave", "cancel", "quit" to stop
      accepts any item in stock to buy it
      reprompts forever
      times out after 120 seconds
```

The shop stands in Oakhaven Village. Everything is buy-only and stock never
runs out.

```game
shop at "Oakhaven Village":
  stocks "Padded Sling", "Thick Leather Gloves", "Rusty Cleaver"
  stocks "Reinforced Tunic", "Chipped Buckler", "Notched Iron Shortsword"
  stocks "Lucky Copper Coin", "Boiled Leather Vest", "Novice Weaver's Robe"
  stocks "Splintered Oak Bow", "Encumbered Miner's Lantern"
  stocks "Apprentice's Ash Staff"
```

## Duels

A challenge waits sixty seconds. Both players must be alive and in the same
place. Duels alternate turns, armour works, and nobody is hitting back out of
turn — but potions are not blocked, so bring some.

There is no prize. What you keep is whatever the fight taught you.

```game
offer duel from <player> to <player>:
  also known as "challenge"
  public
  requires both alive, both here
  refuse "❌ One of you is already in a duel." when either dueling
  refuse "❌ They already have a pending challenge." when target.challenged
  expires after 60 seconds, saying "⌛ The challenge expired."
  accepted by verb accept
  declined by verb decline
  forfeited by verb forfeit
  while active:
    turn based, alternating
    armor applies
    no retaliation
    ends when either hp is 0, with no prize

verb accept:
  public
  refuse "❌ You have no pending duel challenge." unless challenged
  say "⚔️ {player} accepts — the duel begins!"

verb decline:
  public
  refuse "❌ You have no pending duel challenge." unless challenged
  say "🚫 {player} declines the duel challenge."

verb forfeit:
  public
  refuse "❌ You are not in a duel." unless dueling
  say "🏳️ {player} forfeits the duel! 🏆 {opponent} wins."
```
