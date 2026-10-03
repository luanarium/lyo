"""Live simulation state: who is where, and how hurt everything is.

Monster health is held per location and shared by everyone standing there,
which is the defining rule of the game: wound the wolf and the next player
finds it wounded.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from gamebot.lang.model import World


@dataclass
class Player:
    user_id: str
    name: str
    char_class: str
    location: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    gold: int = 0
    stats: dict[str, int] = field(default_factory=dict)
    progress: dict[str, int] = field(default_factory=dict)
    inventory: dict[str, int] = field(default_factory=dict)
    equipped: dict[str, str | None] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def give(self, item: str, count: int = 1) -> None:
        self.inventory[item] = self.inventory.get(item, 0) + count

    def take(self, item: str, count: int = 1) -> bool:
        held = self.inventory.get(item, 0)
        if held < count:
            return False
        if held == count:
            del self.inventory[item]
        else:
            self.inventory[item] = held - count
        return True

    def holds(self, item: str) -> bool:
        return self.inventory.get(item, 0) > 0 or item in self.equipped.values()


@dataclass
class Monster:
    """One monster in one location. Its health is common to that room."""

    name: str
    hp: int
    max_hp: int
    contributors: list[str] = field(default_factory=list)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def damaged_by(self, user_id: str) -> None:
        if user_id not in self.contributors:
            self.contributors.append(user_id)


@dataclass
class Duel:
    a: str
    b: str
    turn: str

    def other(self, user_id: str) -> str:
        return self.b if user_id == self.a else self.a

    def holds(self, user_id: str) -> bool:
        return user_id in (self.a, self.b)


@dataclass
class Offer:
    kind: str
    challenger: str
    target: str
    expires_at: float


@dataclass
class Sim:
    """Everything mutable, over an immutable world."""

    world: World
    players: dict[str, Player] = field(default_factory=dict)
    rooms: dict[str, dict[str, Monster]] = field(default_factory=dict)
    duels: list[Duel] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    clock: Callable[[], float] = time.monotonic
    """Reads real elapsed time. Monotonic, so an NTP step cannot rewind a
    challenge's deadline."""
    offset: float = 0.0
    """Added to the clock, so a test can move time without sleeping."""

    @property
    def now(self) -> float:
        return self.clock() + self.offset

    def __post_init__(self) -> None:
        for name, location in self.world.locations.items():
            self.rooms[name] = {
                ref.name: self._fresh(ref.name) for ref in location.spawns
            }

    def _fresh(self, monster: str) -> Monster:
        hp = self.world.monsters[monster].stats.get("hp", 1)
        return Monster(name=monster, hp=hp, max_hp=hp)

    # --------------------------------------------------------- rooms

    def monsters_in(self, location: str) -> list[Monster]:
        return list(self.rooms.get(location, {}).values())

    def living_in(self, location: str) -> list[Monster]:
        return [m for m in self.monsters_in(location) if m.alive]

    def players_in(self, location: str, *, exclude: str | None = None) -> list[Player]:
        return [p for p in self.players.values()
                if p.location == location and p.user_id != exclude]

    def respawn(self, location: str) -> list[str]:
        """Restore every monster in a room and forget who hurt them."""
        revived = []
        for name, monster in self.rooms.get(location, {}).items():
            if monster.hp < monster.max_hp:
                revived.append(name)
            fresh = self._fresh(name)
            monster.hp, monster.max_hp, monster.contributors = fresh.hp, fresh.max_hp, []
        return revived

    # --------------------------------------------------------- duels

    def duel_of(self, user_id: str) -> Duel | None:
        return next((d for d in self.duels if d.holds(user_id)), None)

    def offer_to(self, user_id: str) -> Offer | None:
        self.expire_offers()
        return next((o for o in self.offers if o.target == user_id), None)

    def expire_offers(self) -> list[Offer]:
        stale = [o for o in self.offers if o.expires_at <= self.now]
        for offer in stale:
            self.offers.remove(offer)
        return stale
