"""The world a game declares, once its names have been bound."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lark import Tree


@dataclass(frozen=True)
class Ref:
    """A name used somewhere, with the position that used it."""

    name: str
    line: int
    column: int


def slug(text: str) -> str:
    """A stable identifier derived from a display name."""
    #  Drop apostrophes rather than treating them as separators, so
    #  "Dragon's Heart" is dragons_heart and not dragon_s_heart.
    bare = re.sub(r"['’]", "", text.casefold())
    return re.sub(r"[^a-z0-9]+", "_", bare).strip("_") or "unnamed"


@dataclass
class Decl:
    """Common head of every declaration."""

    name: str
    line: int
    column: int
    tree: Tree | None = None
    id: str = ""
    """Stable identity for saved games. Defaults to a slug of the name.

    A save refers to this, never to the display name, so renaming an item or a
    location does not orphan the characters holding or standing in it.
    """

    def __post_init__(self) -> None:
        if not self.id:
            self.id = slug(self.name)


@dataclass
class Exit(Decl):
    direction: str = ""
    target: Ref | None = None
    one_way: bool = False
    implied_from: str | None = None


@dataclass
class Location(Decl):
    description: str = ""
    features: set[str] = field(default_factory=set)
    exits: list[Exit] = field(default_factory=list)
    spawns: list[Ref] = field(default_factory=list)
    npcs: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Drop:
    """One rolled reward: an item, how many, and how often."""

    ref: Ref
    low: int = 1
    high: int = 1
    chance: int = 100


@dataclass
class Monster(Decl):
    description: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    gold: tuple[int, int] = (0, 0)
    drops: list[Drop] = field(default_factory=list)


@dataclass
class Item(Decl):
    kind: str = ""
    is_default: bool = False
    description: str = ""
    attrs: dict[str, int] = field(default_factory=dict)
    percents: set[str] = field(default_factory=set)
    """Which attrs were written `5% crit_chance` rather than `5 crit_chance`.

    Display only. A percentage is a way of spelling a number, so the value is
    an ordinary int everywhere else.
    """
    scales: str | None = None
    cost: int | None = None
    grants: dict[str, int] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    icon: str = ""
    worn: str = ""
    """What to call this item's slot to a player: `Main Hand`, `Trinket`.

    The engine equips by `slot` below, which is derived from the kind and is
    the same four places it has always been. This is the label only, so a game
    can say `Hands` without the engine having to grow a hands slot.
    """
    handlers: set[str] = field(default_factory=set)

    SLOTS = {"weapon": "weapon", "body armor": "armor", "shield": "shield",
             "accessory": "accessory"}

    @property
    def slot(self) -> str | None:
        return self.SLOTS.get(self.kind)

    @property
    def label(self) -> str:
        """The player-facing name for where this is worn."""
        return self.worn or self.kind.title()


@dataclass
class CharClass(Decl):
    description: str = ""
    stats: dict[str, int] = field(default_factory=dict)
    equipped: list[tuple[int, Ref]] = field(default_factory=list)
    carried: list[tuple[int, Ref]] = field(default_factory=list)

    @property
    def kit(self) -> list[tuple[int, Ref]]:
        return self.equipped + self.carried


@dataclass
class Spell(Decl):
    cost: dict[str, int] = field(default_factory=dict)
    damage: Tree | None = None
    scales: str | None = None
    provokes: bool = False
    known_by: list[str] = field(default_factory=list)


@dataclass
class Track(Decl):
    raises: str = ""
    amount: int = 0
    triggers: list[str] = field(default_factory=list)
    scaling: str | None = None
    cost: Tree | None = None
    """Expression for the cost of the next point, in uses."""
    effect: tuple[str, int] | None = None
    """A second thing the raise does, as in `raises max_hp by 2 and heals 2`."""


@dataclass
class Slot(Decl):
    optional: bool = False


@dataclass
class Verb(Decl):
    slots: list[Slot] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    visibility: str | None = None
    triggers: list[Ref] = field(default_factory=list)


@dataclass
class Flow(Verb):
    asks: list[str] = field(default_factory=list)


@dataclass
class Offer(Verb):
    resolvers: list[Ref] = field(default_factory=list)
    expires_after: int | None = None


@dataclass
class Shop(Decl):
    at: Ref | None = None
    stock: list[Ref] = field(default_factory=list)
    title: str = ""

    @property
    def label(self) -> str:
        """What the shop calls itself. Named after its town if it has not said."""
        return self.title or f"{self.name} Shop"


@dataclass
class Rules(Decl):
    defines: dict[str, Tree] = field(default_factory=dict)
    handlers: set[str] = field(default_factory=set)


@dataclass
class World:
    title: str = ""
    start_at: Ref | None = None
    start_with: dict[str, int] = field(default_factory=dict)
    locations: dict[str, Location] = field(default_factory=dict)
    monsters: dict[str, Monster] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    classes: dict[str, CharClass] = field(default_factory=dict)
    spells: dict[str, Spell] = field(default_factory=dict)
    tracks: dict[str, Track] = field(default_factory=dict)
    verbs: dict[str, Verb] = field(default_factory=dict)
    flows: dict[str, Flow] = field(default_factory=dict)
    offers: dict[str, Offer] = field(default_factory=dict)
    shops: list[Shop] = field(default_factory=list)
    rules: Rules | None = None

    def item_aliases(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in self.items.values():
            for alias in item.aliases:
                out[alias.casefold()] = item.name
        return out
