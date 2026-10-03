"""Fill a verb's argument slots from what the player typed.

The monster rule is the brief's: match the longest trailing run of words that
names a living monster, allowing partial matches, and read everything before it
as the weapon. The nastiness stays here rather than in the grammar.
"""

from __future__ import annotations

from typing import Any

from lyo.engine.state import Player, Sim
from lyo.lang.model import Item, Slot, Spell

_DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west",
               "u": "up", "d": "down"}


class Unbound(Exception):
    """A required slot could not be filled."""

    def __init__(self, slot: str, said: str) -> None:
        super().__init__(slot)
        self.slot, self.said = slot, said


def bind(slots: list[Slot], words: list[str], sim: Sim, actor: Player,
         *, duel_opponent: Player | None = None) -> dict[str, Any]:
    """Bind right to left, so a trailing target claims as much as it can."""
    bound: dict[str, Any] = {}
    remaining = list(words)

    for slot in reversed(slots):
        value, remaining = _one(slot, remaining, sim, actor, duel_opponent)
        if value is None:
            if not slot.optional:
                raise Unbound(slot.name, " ".join(words))
            continue
        bound[slot.name] = value
    return bound


def _one(slot: Slot, words: list[str], sim: Sim, actor: Player,
         opponent: Player | None):
    kind = slot.name
    if kind == "monster":
        if opponent is not None:
            return opponent, words  # a duel needs no target
        return _trailing(words, lambda t: _monster(t, sim, actor))
    if kind == "player":
        return _trailing(words, lambda t: _player(t, sim, actor))
    if kind == "weapon":
        return _leading(words, lambda t: _item(t, sim, actor, kinds={"weapon"}))
    if kind == "item":
        return _trailing(words, lambda t: _item(t, sim, actor))
    if kind == "spell":
        return _leading(words, lambda t: _spell(t, sim))
    if kind == "exit":
        return _trailing(words, lambda t: _exit(t, sim, actor))
    return _trailing(words, lambda t: t or None)


def _trailing(words: list[str], match):
    """Longest trailing run first; what precedes it is left for earlier slots."""
    for start in range(len(words)):
        found = match(" ".join(words[start:]))
        if found is not None:
            return found, words[:start]
    return None, words


def _leading(words: list[str], match):
    """Longest leading run first, for a weapon or spell named before a target."""
    for end in range(len(words), 0, -1):
        found = match(" ".join(words[:end]))
        if found is not None:
            return found, words[end:]
    return None, words


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _monster(text: str, sim: Sim, actor: Player):
    needle = _norm(text)
    if not needle:
        return None
    for monster in sim.living_in(actor.location):
        if needle in monster.name.casefold():
            return monster
    return None


def _player(text: str, sim: Sim, actor: Player):
    needle = _norm(text).lstrip("@").strip("<>!")
    if not needle:
        return None
    if needle in sim.players:
        return sim.players[needle]
    for player in sim.players.values():
        if player.user_id == needle or needle in player.name.casefold():
            if player.user_id != actor.user_id:
                return player
    return None


def _item(text: str, sim: Sim, actor: Player, kinds: set[str] | None = None):
    needle = _norm(text)
    if not needle:
        return None
    owned = set(actor.inventory) | {v for v in actor.equipped.values() if v}
    candidates = list(sim.world.items.values())

    #  Exact name, then alias, then partial -- owned items win over unowned.
    for test in (lambda i: _norm(i.name) == needle,
                 lambda i: needle in [_norm(a) for a in i.aliases],
                 lambda i: needle in _norm(i.name)):
        for pool in (True, False):
            for item in candidates:
                if kinds and item.kind not in kinds:
                    continue
                if (item.name in owned or item.is_default) is not pool:
                    continue
                if test(item):
                    return item
    return None


def _spell(text: str, sim: Sim):
    needle = _norm(text)
    if not needle:
        return None
    for spell in sim.world.spells.values():
        if needle == _norm(spell.name) or needle in _norm(spell.name):
            return spell
    return None


def _exit(text: str, sim: Sim, actor: Player):
    needle = _norm(text)
    if not needle:
        return None
    direction = _DIRECTIONS.get(needle, needle)
    here = sim.world.locations.get(actor.location)
    if here is None:
        return None
    for way in here.exits:
        if way.direction == direction:
            return way.target.name
    for way in here.exits:
        if needle in way.target.name.casefold():
            return way.target.name
    return None
