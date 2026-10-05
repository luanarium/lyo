"""Plain-text renderings of the structured views a verb can `show`.

An adapter is free to render these itself -- this is the fallback so the engine
is playable without one.

A view may also come back as `Rendered`: the same text, plus the shape it was
built from, so an adapter with something richer than a line of text -- a
Discord embed, say -- can lay it out itself. Nothing here knows what an embed
is; it reports a title and a list of headed blocks, and the plain text is the
flattening of exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lyo.engine.evaluate import Scope, evaluate
from lyo.engine.state import Player, Sim
from lyo.lang.model import Item


@dataclass
class Block:
    """One headed section of a view: a shop's shelf, say."""

    heading: str
    body: str


@dataclass
class Rendered:
    text: str
    title: str = ""
    body: str = ""
    blocks: list[Block] = field(default_factory=list)


def view(name: str, sim: Sim, actor: Player) -> Rendered:
    """One view, structured if it has structure to report."""
    out = _VIEWS.get(name, _unknown)(sim, actor)
    return out if isinstance(out, Rendered) else Rendered(out)


def render(name: str, sim: Sim, actor: Player) -> str:
    return view(name, sim, actor).text


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


def _stock(sim: Sim, actor: Player) -> Rendered:
    for shop in sim.world.shops:
        if shop.at is None or shop.at.name != actor.location:
            continue
        blocks = [_shelf(sim.world.items[ref.name]) for ref in shop.stock]
        gold = f"Your Gold: {actor.gold}"
        text = "\n".join([shop.label, gold,
                          *(f"{b.heading}\n{b.body}" for b in blocks)])
        return Rendered(text=text, title=shop.label, body=gold,
                        blocks=blocks)
    return Rendered("There is no shop here.")


def _shelf(item: Item) -> Block:
    """One item as a shop shows it: a line to pick from, then the detail."""
    icon = f"{item.icon} " if item.icon else ""
    detail = [f"{icon}{item.name.upper()}", f"Type: {item.label}"]
    #  What it is and what it confers read the same on a shelf.
    stats = {**item.attrs, **item.grants}
    if stats:
        detail.append("Stats: " + " | ".join(
            _stat(name, value, item) for name, value in stats.items()))
    detail.append(f"Price: {item.cost} Gold")
    if item.description:
        detail.append(f'"{item.description}"')
    return Block(f"{icon}{item.name} \u2014 {item.cost}g", "\n".join(detail))


def _stat(name: str, value: int, item: Item) -> str:
    """`+3 DAMAGE`, `-1 DEF`, `+5% CRIT CHANCE`.

    The minus of a negative value is its own sign, so only a positive one
    needs saying.
    """
    unit = "%" if name in item.percents else ""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}{unit} {name.replace('_', ' ').upper()}"


_VIEWS = {
    "location": _location, "map": _map, "inventory": _inventory,
    "roster": _roster, "help": _help, "stock": _stock,
}
