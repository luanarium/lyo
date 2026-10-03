"""Execute the language's statements.

A verb body is a list of statements run in order. A refusal aborts the rest of
the body, which is how `refuse "..." unless alive` works, and `stop` leaves the
enclosing loop.
"""

from __future__ import annotations

from typing import Any

from lark import Token, Tree

from gamebot.engine.evaluate import LanguageError, Scope, evaluate, truth, _select
from gamebot.engine.state import Monster, Player, Sim
from gamebot.engine.turn import Turn, render
from gamebot.lang.model import Item, Spell


class Refused(Exception):
    """A guard rejected the command. Nothing further in the body runs."""


class Stopped(Exception):
    """`stop` ended the enclosing loop."""


def run_body(statements, scope: Scope, turn: Turn) -> None:
    for statement in statements:
        node = _unwrap(statement)
        if node is None:
            continue
        execute(node, scope, turn)


def execute(node: Tree, scope: Scope, turn: Turn) -> None:
    handler = _STATEMENTS.get(node.data)
    if handler is None:
        #  Declaration-level lines (visibility, aliases, duel rules) are read
        #  when the verb is bound, not when it runs.
        if node.data in _IGNORED:
            return
        raise LanguageError(f"cannot execute `{node.data}`")
    handler(node, scope, turn)


_IGNORED = {"visibility", "aliases", "expires", "resolved_by", "while_active",
            "turn_based", "armor_applies", "no_retaliation", "ends_when",
            "requires", "ask_stmt"}

#  Pass-through rules that carry no information of their own. Missing one here
#  makes a whole handler body silently unreachable.
_WRAPPERS = {"stmt", "sequenced", "declaration", "rules_stmt", "item_stmt",
             "location_stmt", "monster_stmt", "class_stmt", "spell_stmt",
             "track_stmt", "shop_stmt", "game_stmt", "duel_stmt", "ask_opt"}


def _unwrap(node):
    while isinstance(node, Tree) and node.data in _WRAPPERS:
        children = [c for c in node.children if c is not None]
        if len(children) != 1:
            return node
        node = children[0]
    return node if isinstance(node, Tree) else None


# ------------------------------------------------------------------ guards

def _refuse(node: Tree, scope: Scope, turn: Turn) -> None:
    template, polarity, condition = node.children
    holds = truth(condition, scope)
    trips = holds if str(polarity) == "when" else not holds
    if trips:
        turn.refuse(render(str(template)[1:-1], turn, scope.bindings))
        raise Refused


# ----------------------------------------------------------------- effects

def _target_of(ref, scope: Scope) -> Any:
    return evaluate(ref, scope)


def _deal(node: Tree, scope: Scope, turn: Turn) -> None:
    amount = int(evaluate(node.children[0], scope))
    victim = _target_of(node.children[1], scope)
    _apply_damage(victim, amount, scope, turn)


def _apply_damage(victim: Any, amount: int, scope: Scope, turn: Turn) -> None:
    amount = max(amount, 0)
    if isinstance(victim, Monster):
        victim.hp = max(victim.hp - amount, 0)
        victim.damaged_by(scope.actor.user_id)
        turn.dealt += amount
        if not victim.alive:
            _on_kill(victim, scope, turn)
        return

    if isinstance(victim, Player):
        if victim.user_id != scope.actor.user_id and scope.duel_armor:
            amount = max(amount - _defence_of(victim, scope), 1)
        victim.hp = max(victim.hp - amount, 0)
        if victim.user_id == scope.actor.user_id:
            turn.taken += amount
            if scope.loop_item is not None:
                turn.retaliators.append(_name_of(scope.loop_item))
        else:
            turn.dealt += amount
        return

    raise LanguageError("nothing to damage")


def _defence_of(player: Player, scope: Scope) -> int:
    """The defence the game's own `def` formula gives this player."""
    rules = scope.sim.world.rules
    if rules is None or "def" not in rules.defines:
        return 0
    return int(evaluate(rules.defines["def"], scope.for_player(player)) or 0)


def _name_of(thing: Any) -> str:
    return getattr(thing, "name", str(thing))


def _restore(node: Tree, scope: Scope, turn: Turn) -> None:
    for amount in node.children[0].children:
        value = int(evaluate(amount, scope) or 0)
        unit = str([c for c in amount.children if isinstance(c, Token)][-1])
        _top_up(scope.actor, unit, value, turn)


def _top_up(player: Player, unit: str, value: int, turn: Turn) -> None:
    if unit == "hp":
        before = player.hp
        player.hp = min(player.hp + value, player.max_hp)
        turn.restored += player.hp - before
    elif unit == "mp":
        before = player.mp
        player.mp = min(player.mp + value, player.max_mp)
        turn.restored += player.mp - before
    else:
        raise LanguageError(f"cannot restore `{unit}`")


def _heal(node: Tree, scope: Scope, turn: Turn) -> None:
    _top_up(scope.actor, "hp", int(evaluate(node.children[0], scope)), turn)


def _amount_parts(amount: Tree, scope: Scope) -> tuple[int, str]:
    value = int(evaluate(amount, scope) or 0)
    unit = str([c for c in amount.children if isinstance(c, Token)][-1])
    return value, unit


def _give(node: Tree, scope: Scope, turn: Turn) -> None:
    count, unit = _amount_parts(node.children[0], scope)
    who = _target_of(node.children[1], scope)
    _transfer(who, unit, count, scope, sign=+1)


def _take(node: Tree, scope: Scope, turn: Turn) -> None:
    count, unit = _amount_parts(node.children[0], scope)
    who = _target_of(node.children[1], scope)
    _transfer(who, unit, count, scope, sign=-1, turn=turn)


def _transfer(who: Any, unit: str, count: int, scope: Scope, sign: int,
              turn: Turn | None = None) -> None:
    if not isinstance(who, Player):
        raise LanguageError("can only give to or take from a player")
    if unit == "gold":
        who.gold = max(who.gold + sign * count, 0)
        return
    if unit in ("hp", "mp"):
        current = getattr(who, unit)
        ceiling = getattr(who, f"max_{unit}")
        setattr(who, unit, max(min(current + sign * count, ceiling), 0))
        return
    #  Otherwise the unit names a bound item.
    item = scope.bindings.get(unit)
    name = item.name if isinstance(item, Item) else unit
    if sign > 0:
        who.give(name, count)
        return
    if not who.take(name, count) and turn is not None:
        turn.refuse(f"You are not carrying {name}.")
        raise Refused


def _move(node: Tree, scope: Scope, turn: Turn) -> None:
    who = _target_of(node.children[0], scope)
    where = _target_of(node.children[1], scope)
    if not isinstance(who, Player):
        raise LanguageError("can only move a player")
    destination = where if isinstance(where, str) else _name_of(where)
    if destination not in scope.sim.world.locations:
        raise LanguageError(f"nowhere called `{destination}`")
    who.location = destination
    _on_enter(scope, turn)


def _equip(node: Tree, scope: Scope, turn: Turn) -> None:
    item = _target_of(node.children[0], scope)
    if not isinstance(item, Item):
        raise LanguageError("nothing to equip")
    slot = item.slot
    if slot is None:
        turn.refuse(f"{item.name} cannot be worn or wielded.")
        raise Refused
    actor = scope.actor
    if not actor.holds(item.name):
        turn.refuse(f"You are not carrying {item.name}.")
        raise Refused
    previous = actor.equipped.get(slot)
    actor.take(item.name, 1)
    if previous:
        actor.give(previous, 1)
    actor.equipped[slot] = item.name


def _roll(node: Tree, scope: Scope, turn: Turn) -> None:
    name = str(node.children[0])
    span = _target_of(node.children[1], scope)
    low, high = span if isinstance(span, tuple) else (0, int(span or 0))
    turn.values[name] = scope.sim.rng.randint(low, high)


def _split(node: Tree, scope: Scope, turn: Turn) -> None:
    pot = str(node.children[0])
    among = str(node.children[1])
    leftover_to = str(node.children[2]) if node.children[2] is not None else None

    total = int(turn.values.get(pot, 0))
    people: list[Player] = list(turn.values.get(among) or [])
    if not people:
        people = [scope.actor]

    share, remainder = divmod(total, len(people))
    for person in people:
        person.gold += share
    if remainder and leftover_to:
        winner = turn.values.get(leftover_to) or scope.actor
        if isinstance(winner, Player):
            winner.gold += remainder
    turn.values["share"] = share
    turn.values["remainder"] = remainder


def _respawn(node: Tree, scope: Scope, turn: Turn) -> None:
    guard = node.children[0] if node.children else None
    if guard is not None and truth(guard, scope):
        return
    revived = scope.sim.respawn(scope.actor.location)
    turn.values["revived"] = revived


def _say(node: Tree, scope: Scope, turn: Turn) -> None:
    template, scope_token, polarity, condition = node.children
    if polarity is not None:
        holds = truth(condition, scope)
        if holds is not (str(polarity) == "when"):
            return
    private = turn.private
    if scope_token is not None:
        private = str(scope_token) == "privately"
    turn.say(render(str(template)[1:-1], turn, scope.bindings), private)


def _show(node: Tree, scope: Scope, turn: Turn) -> None:
    turn.values["view"] = str(node.children[0])


def _trigger(node: Tree, scope: Scope, turn: Turn) -> None:
    name = str(node.children[0])
    on = node.children[1] if len(node.children) > 1 else None
    subject = _target_of(on, scope) if on is not None else None

    if isinstance(subject, Item):
        body = _handler_of(subject, name)
        if body is None:
            turn.refuse(f"{subject.name} stays in your inventory.")
            raise Refused
        run_body(body, scope.rebind(item=subject), turn)
        return

    rules = scope.sim.world.rules
    if rules and name in rules.handlers:
        _run_rule(name, scope, turn)
        return
    raise LanguageError(f"nothing handles `{name}`")


def _handler_of(item: Item, name: str):
    if item.tree is None:
        return None
    for child in item.tree.children:
        node = _unwrap(child)
        if node is not None and node.data == "handler" and str(node.children[0]) == name:
            return node.children[1:]
    return None


def _buy(node: Tree, scope: Scope, turn: Turn) -> None:
    item = _target_of(node.children[0], scope)
    if not isinstance(item, Item) or item.cost is None:
        turn.refuse("That is not for sale.")
        raise Refused
    if not _stocked(item, scope):
        turn.refuse(f"{item.name} is not sold here.")
        raise Refused
    if scope.actor.gold < item.cost:
        turn.refuse("You cannot afford that.")
        raise Refused
    scope.actor.gold -= item.cost
    scope.actor.give(item.name, 1)


def _stocked(item: Item, scope: Scope) -> bool:
    here = scope.actor.location
    for shop in scope.sim.world.shops:
        if shop.at and shop.at.name == here:
            return any(ref.name == item.name for ref in shop.stock)
    return False


def _stop(node: Tree, scope: Scope, turn: Turn) -> None:
    turn.stopped = True
    raise Stopped


def _each(node: Tree, scope: Scope, turn: Turn) -> None:
    selector, *body = node.children
    for item in _select(selector, scope):
        run_body(body, scope.with_loop(item), turn)


def _loop(node: Tree, scope: Scope, turn: Turn) -> None:
    try:
        for _ in range(1000):
            run_body(node.children, scope, turn)
    except Stopped:
        return


def _create_player(node: Tree, scope: Scope, turn: Turn) -> None:
    turn.values["created"] = (str(node.children[0]), str(node.children[1]))


def _handler_stmt(node: Tree, scope: Scope, turn: Turn) -> None:
    run_body(node.children[1:], scope, turn)


_STATEMENTS = {
    "refuse": _refuse, "deal": _deal, "restore": _restore, "heal": _heal,
    "give": _give, "take": _take, "move": _move, "equip": _equip,
    "roll": _roll, "split": _split, "respawn": _respawn, "say": _say,
    "show": _show, "trigger": _trigger, "buy": _buy, "stop": _stop,
    "each_stmt": _each, "loop_stmt": _loop, "create_player": _create_player,
    "handler": _handler_stmt,
}


# ------------------------------------------------------------- rule hooks

def _run_rule(name: str, scope: Scope, turn: Turn) -> None:
    rules = scope.sim.world.rules
    if rules is None or rules.tree is None:
        return
    for child in rules.tree.children:
        node = _unwrap(child)
        if node is not None and node.data == "handler" and str(node.children[0]) == name:
            run_body(node.children[1:], scope, turn)
            return


def _on_kill(victim: Monster, scope: Scope, turn: Turn) -> None:
    sim = scope.sim
    contributors = [sim.players[uid] for uid in victim.contributors if uid in sim.players]
    if not contributors:
        contributors = [scope.actor]

    inner = scope.rebind(monster=victim)
    turn.values.update({
        "monster": victim, "contributors": contributors, "killer": scope.actor,
    })

    #  Items are not divided: every contributor gets a full copy of each drop.
    granted: list[str] = []
    world_monster = sim.world.monsters[victim.name]
    for drop in world_monster.drops:
        if drop.chance < 100 and sim.rng.randint(1, 100) > drop.chance:
            continue
        count = sim.rng.randint(drop.low, drop.high)
        for person in contributors:
            person.give(drop.ref.name, count)
        granted.append(drop.ref.name if count == 1 else f"{count} x {drop.ref.name}")
    turn.values["loot"] = granted or None
    turn.values["drops"] = granted or None

    _run_rule("kill", inner, turn)


def _on_enter(scope: Scope, turn: Turn) -> None:
    rules = scope.sim.world.rules
    if rules and "enter" in rules.handlers:
        _run_rule("enter", scope, turn)
