"""One command's worth of outcome: what happened and what to say about it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lyo.engine.state import Monster, Player
from lyo.lang.model import Item, Location, Spell


@dataclass
class Message:
    text: str
    private: bool = False
    kind: str | None = None
    """A hint for presentation: a view's name, or "refusal"."""


@dataclass
class Turn:
    """Accumulates a turn, so a message can report the whole of it at once."""

    actor: Player
    private: bool = False
    messages: list[Message] = field(default_factory=list)
    refusal: str | None = None
    stopped: bool = False

    dealt: int = 0
    taken: int = 0
    restored: int = 0
    retaliators: list[str] = field(default_factory=list)
    levelled: list[str] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)

    #  What the turn did, for the growth tracks to read afterwards.
    attacked_with: Item | None = None
    cast: Spell | None = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None

    def say(self, text: str, private: bool | None = None,
            kind: str | None = None) -> None:
        self.messages.append(
            Message(text, self.private if private is None else private, kind))

    def refuse(self, text: str) -> None:
        self.refusal = text
        self.messages.append(Message(text, self.private, "refusal"))


_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9.]*)\}")


def render(template: str, turn: Turn, bindings: dict[str, Any]) -> str:
    """Fill a message's placeholders from the turn and its bindings."""

    def one(match: re.Match[str]) -> str:
        name = match.group(1)
        root, _, attribute = name.partition(".")
        value = _value(root, turn, bindings)
        if attribute and value is not None:
            value = getattr(value, attribute, value)
        return match.group(0) if value is None else _show(value)

    return _PLACEHOLDER.sub(one, template)


def _value(root: str, turn: Turn, bindings: dict[str, Any]) -> Any:
    if root in turn.values:
        return turn.values[root]
    if root in bindings:
        return bindings[root]
    actor = turn.actor
    return {
        "player": actor, "name": actor.name, "class": actor.char_class,
        "here": actor.location, "hp": actor.hp, "max_hp": actor.max_hp,
        "mp": actor.mp, "max_mp": actor.max_mp, "gold": actor.gold,
        "dealt": turn.dealt, "taken": turn.taken, "restored": turn.restored,
        "healed": turn.restored,
        "retaliators": turn.retaliators or None,
    }.get(root)


def _show(value: Any) -> str:
    if isinstance(value, (Player, Monster)):
        return value.name
    if isinstance(value, (Item, Spell, Location)):
        return value.name
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        parts = [_show(v) for v in value]
        if not parts:
            return "nothing"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return str(value)
