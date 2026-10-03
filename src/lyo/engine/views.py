"""Plain-text renderings of the structured views a verb can `show`.

An adapter is free to render these itself -- this is the fallback so the engine
is playable without one.
"""

from __future__ import annotations

from lyo.engine.evaluate import Scope, evaluate
from lyo.engine.state import Player, Sim


def render(name: str, sim: Sim, actor: Player) -> str:
    return _VIEWS.get(name, _unknown)(sim, actor)


def _unknown(sim: Sim, actor: Player) -> str:
    return "Nothing to show."


def _location(sim: Sim, actor: Player) -> str:
    here = sim.world.locations[actor.location]
    lines = [here.name, here.description]

    living = sim.living_in(actor.location)
    if living:
        lines.append("Here: " + ", ".join(
            f"{m.name} ({m.hp}/{m.max_hp})" for m in living))
    for who, role in here.npcs:
        lines.append(f"{who}, {role}")
    others = sim.players_in(actor.location, exclude=actor.user_id)
    if others:
        lines.append("Also here: " + ", ".join(p.name for p in others))
    if "inn" in here.features:
        lines.append("There is an inn.")
    if "shop" in here.features:
        lines.append("There is a shop.")
    lines.append(f"You: {actor.hp}/{actor.max_hp} hp, {actor.mp}/{actor.max_mp} mp")
    return "\n".join(line for line in lines if line)


def _map(sim: Sim, actor: Player) -> str:
    here = sim.world.locations[actor.location]
    ways = [f"  {e.direction} to {e.target.name}" for e in here.exits]
    return "\n".join([here.name, here.description, *ways])


def _inventory(sim: Sim, actor: Player) -> str:
    scope = Scope(sim, actor)
    rules = sim.world.rules
    atk = int(evaluate(rules.defines["atk"], scope)) if rules and "atk" in rules.defines else 0
    defence = int(evaluate(rules.defines["def"], scope)) if rules and "def" in rules.defines else 0

    gear = ", ".join(f"{slot}: {item}" for slot, item in sorted(actor.equipped.items())
                     if item) or "nothing equipped"
    lines = [
        f"{actor.name} the {actor.char_class}, in {actor.location}",
        f"{actor.hp}/{actor.max_hp} hp, {actor.mp}/{actor.max_mp} mp, {actor.gold} gold",
        f"atk {atk}, def {defence} ({gear})",
    ]

    for track in sim.world.tracks.values():
        cost = int(evaluate(track.cost, scope) or 0) if track.cost else 0
        done = actor.progress.get(track.name, 0)
        current = (getattr(actor, track.raises, None)
                   if track.raises.startswith("max_")
                   else actor.stats.get(track.raises, 0))
        lines.append(f"  {track.raises} {current} -- {done}/{cost} to the next point")

    if actor.inventory:
        lines.append("Carrying: " + ", ".join(
            name if count == 1 else f"{name} x{count}"
            for name, count in sorted(actor.inventory.items())))
    else:
        lines.append("Carrying nothing.")
    return "\n".join(lines)


def _roster(sim: Sim, actor: Player) -> str:
    if not sim.players:
        return "Nobody is registered."
    return "\n".join(f"{p.name} -- {p.location}"
                     for p in sorted(sim.players.values(), key=lambda p: p.name))


def _help(sim: Sim, actor: Player) -> str:
    lines = ["Commands:"]
    for holder in (*sim.world.verbs.values(), *sim.world.flows.values(),
                   *sim.world.offers.values()):
        words = ", ".join([holder.name, *holder.aliases])
        slots = " ".join(f"<{s.name}{'?' if s.optional else ''}>" for s in holder.slots)
        lines.append(f"  {words}{' ' + slots if slots else ''}")
    return "\n".join(lines)


def _stock(sim: Sim, actor: Player) -> str:
    for shop in sim.world.shops:
        if shop.at and shop.at.name == actor.location:
            rows = []
            for ref in shop.stock:
                item = sim.world.items[ref.name]
                rows.append(f"  {item.name} -- {item.cost} gold ({item.kind})")
            return "\n".join(["For sale:", *rows])
    return "There is no shop here."


_VIEWS = {
    "location": _location, "map": _map, "inventory": _inventory,
    "roster": _roster, "help": _help, "stock": _stock,
}
