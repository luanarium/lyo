"""Evaluate the language's expressions against live state.

All arithmetic is integer arithmetic with floor division, which is what every
formula in the game assumes: half a stat, a fifth of a track, an even split of
gold with the remainder going somewhere specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lark import Token, Tree

from lyo.engine.state import Monster, Player, Sim


class LanguageError(Exception):
    """The game asked for something the engine cannot provide."""


@dataclass
class Scope:
    """What names mean during one statement."""

    sim: Sim
    actor: Player
    bindings: dict[str, Any] = field(default_factory=dict)
    loop_item: Any = None
    duel: bool = False
    """In a duel, monsters are ignored entirely and nobody hits back."""
    duel_armor: bool = False
    turn: Any = None
    """The turn in progress, so a condition can test what has happened."""

    def rebind(self, **extra: Any) -> "Scope":
        return Scope(self.sim, self.actor, {**self.bindings, **extra},
                     self.loop_item, self.duel, self.duel_armor, self.turn)

    def with_loop(self, item: Any) -> "Scope":
        return Scope(self.sim, self.actor, self.bindings, item,
                     self.duel, self.duel_armor, self.turn)

    def for_player(self, player: Player) -> "Scope":
        return Scope(self.sim, player, {}, None, self.duel, self.duel_armor,
                     self.turn)


_SLOT_OF_KIND = {"weapon": "weapon", "body armor": "armor",
                 "shield": "shield", "accessory": "accessory"}


def evaluate(node, scope: Scope) -> Any:
    """Evaluate one expression node."""
    if node is None:
        return None
    if isinstance(node, Token):
        return _atom_token(node, scope)

    handler = _NODES.get(node.data)
    if handler is None:
        raise LanguageError(f"cannot evaluate `{node.data}`")
    return handler(node, scope)


def truth(node, scope: Scope) -> bool:
    value = evaluate(node, scope)
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


# ------------------------------------------------------------------ atoms

def _atom_token(token: Token, scope: Scope) -> Any:
    if token.type == "NUMBER":
        return int(str(token))
    if token.type == "PERCENT":
        return int(str(token).rstrip("%"))
    if token.type == "STRING":
        return str(token)[1:-1]
    return _lookup(str(token), scope)


def _number(node: Tree, scope: Scope) -> int:
    return int(str(node.children[0]))


def _percent(node: Tree, scope: Scope) -> int:
    return int(str(node.children[0]).rstrip("%"))


def _literal(node: Tree, scope: Scope) -> str:
    return str(node.children[0])[1:-1]


def _all_of(node: Tree, scope: Scope) -> Any:
    """`all hp` is the headroom to the maximum, so `restore all hp` tops up."""
    name = str(node.children[0])
    ceiling = _lookup(f"max_{name}", scope)
    current = _lookup(name, scope)
    if isinstance(ceiling, int) and isinstance(current, int):
        return ceiling - current
    return ceiling


def _of(node: Tree, scope: Scope) -> Any:
    """An `amount` like `8 hp`: the number, with the unit read separately."""
    return evaluate(node.children[0], scope)


def _path(node: Tree, scope: Scope) -> Any:
    parts = [str(c) for c in node.children]
    value = _lookup(parts[0], scope)
    for part in parts[1:]:
        value = _attribute(value, part, scope)
    return value


def _its(node: Tree, scope: Scope) -> Any:
    if scope.loop_item is None:
        raise LanguageError("`its` used outside a `for every` block")
    value: Any = scope.loop_item
    for part in [str(c) for c in node.children[0].children]:
        value = _attribute(value, part, scope)
    return value


def _call(node: Tree, scope: Scope) -> Any:
    name = str(node.children[0])
    args = [evaluate(c, scope) for c in node.children[1:]]
    if name in ("max", "min"):
        return (max if name == "max" else min)(args)
    raise LanguageError(f"no function named `{name}`")


def _quantified(node: Tree, scope: Scope) -> bool:
    """`both alive` / `either dueling`, over the two sides of a duel."""
    which = str(node.children[0])
    attribute = [str(c) for c in node.children[1].children]
    people = _duel_sides(scope)
    results = []
    for person in people:
        value: Any = person
        for part in attribute:
            value = _attribute(value, part, scope)
        results.append(bool(value))
    return all(results) if which == "both" else any(results)


def _any_matching(node: Tree, scope: Scope) -> bool:
    return bool(_select(node.children[0], scope))


def _select(selector: Tree, scope: Scope) -> list[Any]:
    """`living monster here`, `other player here`, `fallen player here`."""
    parts = [c for c in selector.children if c is not None]
    qualifiers = {str(c.children[0]) for c in parts if isinstance(c, Tree)}
    nouns = [str(c) for c in parts if isinstance(c, Token)]
    noun = nouns[0] if nouns else ""
    here = "here" in nouns[1:] or len(nouns) > 1

    if noun.startswith("monster"):
        if scope.duel:
            return []  #  a duel ignores the room's monsters entirely
        room = scope.actor.location
        found = scope.sim.monsters_in(room)
        if "living" in qualifiers:
            found = [m for m in found if m.alive]
        if "fallen" in qualifiers:
            found = [m for m in found if not m.alive]
        return found

    if noun.startswith("player"):
        exclude = scope.actor.user_id if "other" in qualifiers else None
        found = scope.sim.players_in(scope.actor.location, exclude=exclude)
        if "living" in qualifiers:
            found = [p for p in found if p.alive]
        if "fallen" in qualifiers:
            found = [p for p in found if not p.alive]
        return found

    raise LanguageError(f"cannot select `{noun}`")


# ------------------------------------------------------------- operators

def _sum(node: Tree, scope: Scope) -> int:
    total = evaluate(node.children[0], scope)
    for operator, operand in zip(node.children[1::2], node.children[2::2]):
        value = evaluate(operand, scope)
        total = total + value if str(operator.children[0]) == "+" else total - value
    return total


def _product(node: Tree, scope: Scope) -> int:
    total = evaluate(node.children[0], scope)
    for operator, operand in zip(node.children[1::2], node.children[2::2]):
        value = evaluate(operand, scope)
        if str(operator.children[0]) == "*":
            total *= value
        else:
            if value == 0:
                raise LanguageError("division by zero")
            total //= value  # floor: every formula in the game rounds down
    return total


def _clamp(node: Tree, scope: Scope) -> int:
    value = evaluate(node.children[0], scope)
    for op in node.children[1:]:
        bound = evaluate(op.children[0], scope)
        if op.data == "at_least":
            value = max(value, bound)
        else:  # at_most, capped_at
            value = min(value, bound)
    return value


_COMPARE = {
    "is": lambda a, b: a == b,
    "isnot": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def _comparison(node: Tree, scope: Scope) -> bool:
    left = evaluate(node.children[0], scope)
    operator = "".join(str(t) for t in node.children[1].children)
    right = evaluate(node.children[2], scope)
    compare = _COMPARE.get(operator)
    if compare is None:
        raise LanguageError(f"no comparison `{operator}`")
    return compare(left, right)


def _and(node: Tree, scope: Scope) -> bool:
    return all(truth(c, scope) for c in node.children)


def _or(node: Tree, scope: Scope) -> bool:
    return any(truth(c, scope) for c in node.children)


def _not(node: Tree, scope: Scope) -> bool:
    return not truth(node.children[0], scope)


_NODES = {
    "number": _number, "percent": _percent, "literal": _literal,
    "all_of": _all_of, "of": _of, "path": _path, "its": _its, "call": _call,
    "quantified": _quantified, "any_matching": _any_matching,
    "sum": _sum, "product": _product, "clamp": _clamp,
    "comparison": _comparison, "and_expr": _and, "or_expr": _or,
    "logical_not": _not,
}


# --------------------------------------------------------------- lookup

def _duel_sides(scope: Scope) -> list[Player]:
    duel = scope.sim.duel_of(scope.actor.user_id)
    if duel:
        return [scope.sim.players[duel.a], scope.sim.players[duel.b]]
    other = scope.bindings.get("target") or scope.bindings.get("opponent")
    return [scope.actor, other] if isinstance(other, Player) else [scope.actor]


def _lookup(name: str, scope: Scope) -> Any:
    sim, actor = scope.sim, scope.actor

    if name in scope.bindings:
        return scope.bindings[name]

    #  What this turn has done so far, so `when taken > 0` can be asked.
    turn = scope.turn
    if turn is not None:
        if name in ("dealt", "taken", "restored"):
            return getattr(turn, name)
        if name == "retaliators":
            return turn.retaliators
        if name in turn.values:
            return turn.values[name]

    if name == "player":
        return actor
    if name == "here":
        return sim.world.locations.get(actor.location)
    if name == "opponent":
        duel = sim.duel_of(actor.user_id)
        return sim.players[duel.other(actor.user_id)] if duel else None

    #  Player numbers.
    if name in ("hp", "max_hp", "mp", "max_mp", "gold"):
        return getattr(actor, name)
    if name in actor.stats:
        return actor.stats[name]

    #  Predicates.
    if name == "alive":
        return actor.alive
    if name == "fallen":
        return not actor.alive
    if name == "registered":
        return actor.user_id in sim.players
    if name == "dueling":
        return sim.duel_of(actor.user_id) is not None
    if name == "challenged":
        return sim.offer_to(actor.user_id) is not None

    #  Equipment slots, so `weapon.damage` and `shield.def` resolve.
    if name in ("weapon", "armor", "shield", "accessory"):
        return _equipped(actor, name, sim)

    #  A name defined by the rules block, evaluated on demand.
    rules = sim.world.rules
    if rules and name in rules.defines:
        return evaluate(rules.defines[name], scope)

    raise LanguageError(f"nothing named `{name}`")


def _equipped(actor: Player, slot: str, sim: Sim):
    held = actor.equipped.get(slot)
    if held and held in sim.world.items:
        return sim.world.items[held]
    #  Fall back on whatever the game declared as the default for this slot.
    for item in sim.world.items.values():
        if item.is_default and _SLOT_OF_KIND.get(item.kind) == slot:
            return item
    return None


def _attribute(value: Any, part: str, scope: Scope) -> Any:
    if value is None:
        return 0

    from lyo.lang.model import Item, Location, Spell

    if isinstance(value, Item):
        if part == "scales":
            return scope.actor.stats.get(value.scales or "", 0)
        if part in value.attrs:
            return value.attrs[part]
        if part in value.grants:
            return value.grants[part]
        if part == "cost":
            return value.cost if value.cost is not None else 0
        if part == "name":
            return value.name
        return 0

    if isinstance(value, Location):
        if part in ("inn", "shop"):
            return part in value.features
        if part == "name":
            return value.name
        return 0

    if isinstance(value, Spell):
        if part == "cost":
            return sum(value.cost.values())
        if part == "damage":
            return evaluate(value.damage, scope) if value.damage is not None else 0
        if part == "name":
            return value.name
        return 0

    if isinstance(value, Player):
        if part in ("hp", "max_hp", "mp", "max_mp", "gold", "name"):
            return getattr(value, part)
        if part == "alive":
            return value.alive
        if part == "dueling":
            return scope.sim.duel_of(value.user_id) is not None
        if part == "challenged":
            return scope.sim.offer_to(value.user_id) is not None
        return value.stats.get(part, 0)

    if isinstance(value, Monster):
        if part in ("hp", "max_hp", "name"):
            return getattr(value, part)
        if part == "alive":
            return value.alive
        world = scope.sim.world.monsters.get(value.name)
        if part == "gold" and world:
            return world.gold
        return world.stats.get(part, 0) if world else 0

    return getattr(value, part, 0)
