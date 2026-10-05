"""Bind a parse tree into a world, and say plainly what is wrong with it.

Two passes, because convention 8 makes the document the compilation unit and
declarations order-independent: collect every declaration first, then bind the
names they refer to. Diagnostics accumulate rather than raising, so one run
reports every problem instead of only the first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches

from lark import Token, Tree

from lyo.lang.model import (
    CharClass, Drop, Exit, Flow, Item, Location, Monster, Offer, Ref, Rules,
    Shop, Slot, Spell, Track, Verb, World,
)
from lyo.lang.source import Source

ERROR = "error"
WARNING = "warning"

#  Wrapper rules that carry no information of their own.
_WRAPPERS = {"declaration", "stmt", "sequenced", "location_stmt", "rules_stmt",
             "item_stmt", "monster_stmt", "duel_stmt", "class_stmt", "spell_stmt",
             "track_stmt", "shop_stmt", "game_stmt", "ask_opt"}

_OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east",
             "up": "down", "down": "up", "in": "out", "out": "in"}

#  What a message may interpolate. Unknown placeholders are a warning, since a
#  game may legitimately be ahead of the engine.
_PLACEHOLDERS = {
    "player", "opponent", "target", "challenger", "killer", "here", "start",
    "monster", "item", "spell", "weapon", "name", "chosen", "class",
    "dealt", "taken", "restored", "healed", "cost", "gold", "loot", "total",
    "hp", "mp", "max_hp", "max_mp", "retaliators", "contributors", "inns",
    "stock", "share", "remainder", "drops",
}

_BUILTIN_HANDLERS = {"use", "kill", "enter", "attack", "cast", "equip",
                     "buy", "timeout"}


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    line: int
    column: int

    def format(self, source: Source) -> str:
        return f"{source.where(self.line, self.column)}: {self.severity}[{self.code}] {self.message}"


@dataclass
class Resolution:
    world: World
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == ERROR]

    @property
    def ok(self) -> bool:
        return not self.errors


# ----------------------------------------------------------------- helpers

def _unwrap(node):
    while isinstance(node, Tree) and node.data in _WRAPPERS:
        trees = [c for c in node.children if c is not None]
        if len(trees) != 1:
            break
        node = trees[0]
    return node


def _text(token: Token | None) -> str:
    if token is None:
        return ""
    raw = str(token)
    return raw[1:-1] if raw[:1] == '"' else raw


def _pos(node) -> tuple[int, int]:
    """Any positioned thing: a Tree, a Token, a Ref, or a Decl."""
    if isinstance(node, Tree):
        try:
            return node.meta.line, node.meta.column
        except AttributeError:
            return 0, 0
    return getattr(node, "line", 0) or 0, getattr(node, "column", 0) or 0


def _ref(token: Token) -> Ref:
    return Ref(_text(token), token.line or 0, token.column or 0)


def _named(tree: Tree, name: str) -> list[Tree]:
    return [c for c in tree.children if isinstance(c, Tree) and c.data == name]


def _quantities(tree: Tree) -> list[tuple[int, str, str | None]]:
    """Read a quantity_list into (amount, unit, scaling) triples.

    A quantity may be negative (`-1 def`) or written as a percentage
    (`5% crit_chance`); both come back as a plain signed int, since a
    percentage is only a way of spelling a number here. Which units were
    written that way is `_percent_units`, for whoever has to print them.
    """
    out = []
    for group in _named(tree, "quantity_list") or [tree]:
        for q in _named(group, "quantity"):
            kids = [c for c in q.children if c is not None]
            sign, kids = (-1, kids[1:]) if str(kids[0]) == "-" else (1, kids)
            amount = sign * int(str(kids[0]).rstrip("%"))
            unit = str(kids[1])
            scaling = str(kids[2]) if len(kids) > 2 else None
            out.append((amount, unit, scaling))
    return out


def _percent_units(tree: Tree) -> set[str]:
    """The units in a quantity_list written as a percentage, not a count."""
    found = set()
    for group in _named(tree, "quantity_list") or [tree]:
        for q in _named(group, "quantity"):
            kids = [c for c in q.children if c is not None]
            kids = kids[1:] if str(kids[0]) == "-" else kids
            if str(kids[0]).endswith("%"):
                found.add(str(kids[1]))
    return found


# ----------------------------------------------------------------- resolver

class _Resolver:
    def __init__(self, source: Source) -> None:
        self.source = source
        self.world = World()
        self.diagnostics: list[Diagnostic] = []
        self._seen: dict[tuple[str, str], tuple[int, int]] = {}

    def report(self, severity, code, message, node) -> None:
        line, column = _pos(node)
        self.diagnostics.append(Diagnostic(severity, code, message, line, column))

    def error(self, code, message, node):
        self.report(ERROR, code, message, node)

    def warn(self, code, message, node):
        self.report(WARNING, code, message, node)

    # ------------------------------------------------------------ collect

    def collect(self, tree: Tree) -> None:
        for declaration in tree.children:
            node = _unwrap(declaration)
            handler = getattr(self, f"_on_{node.data}", None)
            if handler is None:
                self.warn("unknown-declaration", f"ignored `{node.data}`", node)
                continue
            handler(node)

    def _claim(self, kind: str, name: str, node) -> bool:
        key = (kind, name.casefold())
        if key in self._seen:
            first = self._seen[key]
            self.error("duplicate",
                       f'{kind} "{name}" is already declared at line {first[0]}', node)
            return False
        self._seen[key] = _pos(node)
        return True

    def _on_game_decl(self, node: Tree) -> None:
        self.world.title = _text(node.children[0])
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "players_start":
                self.world.start_at = _ref(stmt.children[0])
                for amount, unit, _ in self._amounts(stmt.children[1]):
                    self.world.start_with[unit] = amount

    def _amounts(self, tree: Tree):
        out = []
        for a in _named(tree, "of") + _named(tree, "all_of"):
            kids = [c for c in a.children if c is not None]
            if a.data == "all_of":
                out.append((None, str(kids[0]), None))
            else:
                value = kids[0]
                number = int(str(value.children[0])) if isinstance(value, Tree) else int(str(value))
                out.append((number, str(kids[1]), None))
        return out

    def _on_location_decl(self, node: Tree) -> None:
        name = _text(node.children[0])
        loc = Location(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "identifier":
                loc.id = str(stmt.children[0])
            elif stmt.data == "description":
                loc.description = _text(stmt.children[0])
            elif stmt.data == "features":
                loc.features = {str(t) for t in stmt.children[0].children}
            elif stmt.data == "spawns":
                loc.spawns += [_ref(t) for t in stmt.children[0].children]
            elif stmt.data == "exit":
                one_way, direction, target = stmt.children
                loc.exits.append(Exit(
                    name=f"{name}:{direction}", line=target.line or 0,
                    column=target.column or 0, direction=str(direction),
                    target=_ref(target), one_way=one_way is not None))
            elif stmt.data == "npc_decl":
                loc.npcs.append((_text(stmt.children[0]), _text(stmt.children[1])))
        if self._claim("location", name, node):
            self.world.locations[name] = loc

    def _on_monster_decl(self, node: Tree) -> None:
        name = _text(node.children[0])
        mon = Monster(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "identifier":
                mon.id = str(stmt.children[0])
            elif stmt.data == "description":
                mon.description = _text(stmt.children[0])
            elif stmt.data == "stats":
                mon.stats = {u: a for a, u, _ in _quantities(stmt)}
            elif stmt.data == "drop":
                #  `range?` and `chance?` create no placeholders, so find each
                #  child by what it is rather than where it sits.
                rng = next((c for c in stmt.children
                            if isinstance(c, Tree) and c.data == "range"), None)
                odds = next((c for c in stmt.children
                             if isinstance(c, Tree) and c.data == "chance"), None)
                what = next((c for c in stmt.children if isinstance(c, Token)), None)
                if what is None:
                    continue
                low, high = (int(str(c)) for c in rng.children) if rng else (1, 1)
                if what.type == "NAME" and str(what) == "gold":
                    mon.gold = (low, high)
                else:
                    chance = int(str(odds.children[0]).rstrip("%")) if odds else 100
                    mon.drops.append(Drop(_ref(what), low, high, chance))
        if self._claim("monster", name, node):
            self.world.monsters[name] = mon

    def _on_item_decl(self, node: Tree) -> None:
        name = _text(node.children[0])
        kind_tree = node.children[1]
        kind_name = " ".join(str(t) for t in kind_tree.children[0].children if t is not None)
        item = Item(name=name, line=node.meta.line, column=node.meta.column, tree=node,
                    kind=kind_name, is_default=kind_tree.data == "default_kind")
        for stmt in node.children[2:]:
            stmt = _unwrap(stmt)
            if stmt.data == "identifier":
                item.id = str(stmt.children[0])
            elif stmt.data == "description":
                item.description = _text(stmt.children[0])
            elif stmt.data == "attrs":
                for amount, unit, scaling in _quantities(stmt):
                    item.attrs[unit] = amount
                    if scaling:
                        item.scales = scaling
                item.percents |= _percent_units(stmt)
            elif stmt.data == "costs":
                for amount, _unit, _ in _quantities(stmt):
                    item.cost = amount
            elif stmt.data == "grants":
                item.grants.update({u: a for a, u, _ in _quantities(stmt)})
                item.percents |= _percent_units(stmt)
            elif stmt.data == "aliases":
                item.aliases += [_text(t) for t in stmt.children[0].children]
            elif stmt.data == "icon":
                item.icon = _text(stmt.children[0])
            elif stmt.data == "worn":
                item.worn = _text(stmt.children[0])
            elif stmt.data == "handler":
                item.handlers.add(str(stmt.children[0]))
        if self._claim("item", name, node):
            self.world.items[name] = item

    def _on_class_decl(self, node: Tree) -> None:
        name = _text(node.children[0])
        cls = CharClass(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "identifier":
                cls.id = str(stmt.children[0])
            elif stmt.data == "description":
                cls.description = _text(stmt.children[0])
            elif stmt.data == "stats":
                cls.stats = {u: a for a, u, _ in _quantities(stmt)}
            elif stmt.data in ("starts_equipped", "starts_carried"):
                bucket = cls.equipped if stmt.data == "starts_equipped" else cls.carried
                for kit in _named(stmt.children[0], "kit_item"):
                    kids = [c for c in kit.children if c is not None]
                    count = int(str(kids[0])) if len(kids) > 1 else 1
                    bucket.append((count, _ref(kids[-1])))
        if self._claim("class", name, node):
            self.world.classes[name] = cls

    def _on_spell_decl(self, node: Tree) -> None:
        name = _text(node.children[0])
        spell = Spell(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "costs":
                spell.cost = {u: a for a, u, _ in _quantities(stmt)}
            elif stmt.data == "deals":
                spell.damage = stmt.children[0]
                tokens = [c for c in stmt.children if isinstance(c, Token)]
                if len(tokens) > 1:
                    spell.scales = str(tokens[-1])
            elif stmt.data == "provokes":
                spell.provokes = True
            elif stmt.data == "known_by":
                spell.known_by = [str(t) for t in stmt.children[0].children]
        if self._claim("spell", name, node):
            self.world.spells[name] = spell

    def _on_track_decl(self, node: Tree) -> None:
        name = str(node.children[0])
        track = Track(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "advances":
                trigger = stmt.children[0]
                track.triggers.append(trigger.data)
                #  on_attack is [with-what, scaling]; on_cast is [scaling].
                scaling = trigger.children[-1] if trigger.children else None
                if scaling is not None:
                    track.scaling = str(scaling)
            elif stmt.data == "cost":
                track.cost = stmt.children[0]
            elif stmt.data == "raises":
                track.raises = str(stmt.children[0])
                track.amount = int(str(stmt.children[1]))
                extra = stmt.children[2] if len(stmt.children) > 2 else None
                if extra is not None:
                    track.effect = (str(extra.children[0]), int(str(extra.children[1])))
        if self._claim("track", name, node):
            self.world.tracks[name] = track

    def _body(self, target: Verb, statements) -> None:
        for stmt in statements:
            stmt = _unwrap(stmt)
            data = getattr(stmt, "data", "")
            if data == "visibility":
                target.visibility = str(stmt.children[0])
            elif data == "aliases":
                target.aliases += [_text(t) for t in stmt.children[0].children]
            elif data == "trigger":
                target.triggers.append(_ref(stmt.children[0]))
            elif data == "ask_stmt" and isinstance(target, Flow):
                target.asks.append(str(stmt.children[0]))
            elif data == "resolved_by" and isinstance(target, Offer):
                target.resolvers.append(_ref(stmt.children[-1]))
            elif data == "expires" and isinstance(target, Offer):
                for amount, _unit, _ in _quantities(stmt):
                    target.expires_after = amount
            elif data in ("each_stmt", "loop_stmt", "while_active", "handler"):
                self._body(target, stmt.children)

    def _on_verb_decl(self, node: Tree) -> None:
        name = str(node.children[0])
        verb = Verb(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        verb.slots = self._slots(node)
        self._body(verb, node.children[1:])
        if self._claim("verb", name, node):
            self.world.verbs[name] = verb

    def _on_flow_decl(self, node: Tree) -> None:
        name = str(node.children[0])
        flow = Flow(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        self._body(flow, node.children[1:])
        if self._claim("flow", name, node):
            self.world.flows[name] = flow

    def _on_offer_decl(self, node: Tree) -> None:
        name = str(node.children[0])
        offer = Offer(name=name, line=node.meta.line, column=node.meta.column, tree=node)
        offer.slots = self._slots(node)
        self._body(offer, node.children[1:])
        if self._claim("offer", name, node):
            self.world.offers[name] = offer

    def _slots(self, node: Tree) -> list[Slot]:
        out = []
        for s in _named(node, "slot"):
            kids = [c for c in s.children if c is not None]
            out.append(Slot(name=str(kids[0]), line=s.meta.line, column=s.meta.column,
                            optional=len(kids) > 1))
        return out

    def _on_rules_decl(self, node: Tree) -> None:
        rules = Rules(name="rules", line=node.meta.line, column=node.meta.column, tree=node)
        for stmt in node.children:
            stmt = _unwrap(stmt)
            if stmt.data == "define":
                rules.defines[str(stmt.children[0])] = stmt.children[1]
            elif stmt.data == "handler":
                rules.handlers.add(str(stmt.children[0]))
        if self.world.rules is not None:
            self.error("duplicate", "rules are already declared", node)
            return
        self.world.rules = rules

    def _on_shop_decl(self, node: Tree) -> None:
        shop = Shop(name=_text(node.children[0]), line=node.meta.line,
                    column=node.meta.column, tree=node, at=_ref(node.children[0]))
        for stmt in node.children[1:]:
            stmt = _unwrap(stmt)
            if stmt.data == "stocks":
                shop.stock += [_ref(t) for t in stmt.children[0].children]
            elif stmt.data == "shop_name":
                shop.title = _text(stmt.children[0])
        self.world.shops.append(shop)

    # ----------------------------------------------------------- validate

    def _check(self, ref: Ref, table: dict, kind: str, code: str) -> bool:
        if ref.name in table:
            return True
        near = get_close_matches(ref.name, list(table), n=1, cutoff=0.7)
        hint = f' -- did you mean "{near[0]}"?' if near else ""
        self.diagnostics.append(Diagnostic(
            ERROR, code, f'no {kind} named "{ref.name}"{hint}', ref.line, ref.column))
        return False

    def validate(self) -> None:
        w = self.world
        self._validate_ids()
        self._validate_start()
        self._validate_exits()
        self._validate_spawns_and_drops()
        self._validate_kits()
        self._validate_shops()
        self._validate_defaults()
        self._validate_scaling()
        self._validate_dispatch()
        self._validate_orphans()
        self._validate_placeholders()
        self._validate_aliases()

    def _validate_ids(self) -> None:
        """A save keys on these, so a collision would merge two things."""
        for kind, table in (("location", self.world.locations),
                            ("monster", self.world.monsters),
                            ("item", self.world.items),
                            ("class", self.world.classes)):
            claimed: dict[str, str] = {}
            for decl in table.values():
                owner = claimed.get(decl.id)
                if owner is not None:
                    self.error("id-clash",
                               f'{kind} id `{decl.id}` is used by both "{owner}" '
                               f'and "{decl.name}" -- give one an explicit `id`',
                               decl.tree)
                claimed[decl.id] = decl.name

    def _validate_start(self) -> None:
        if self.world.start_at is None:
            self.error("no-start", "no `game` declaration says where players start",
                       self.world.rules or Slot(name="", line=1, column=1))
            return
        self._check(self.world.start_at, self.world.locations, "location", "unknown-location")

    def _validate_exits(self) -> None:
        w = self.world
        for loc in w.locations.values():
            for ex in list(loc.exits):
                if not self._check(ex.target, w.locations, "location", "unknown-location"):
                    continue
                if ex.one_way:
                    continue
                opposite = _OPPOSITE.get(ex.direction)
                if opposite is None:
                    self.warn("no-opposite",
                              f"`{ex.direction}` has no known opposite, so the return path "
                              f"cannot be inferred -- declare it, or mark this `one way`",
                              ex.target)
                    continue
                far = w.locations[ex.target.name]
                if not any(e.direction == opposite for e in far.exits):
                    far.exits.append(Exit(
                        name=f"{far.name}:{opposite}", line=ex.line, column=ex.column,
                        direction=opposite, target=Ref(loc.name, ex.line, ex.column),
                        implied_from=loc.name))

        for loc in w.locations.values():
            by_direction: dict[str, Exit] = {}
            for ex in loc.exits:
                clash = by_direction.get(ex.direction)
                if clash and clash.target.name != ex.target.name:
                    self.error("exit-conflict",
                               f'"{loc.name}" sends {ex.direction} to both '
                               f'"{clash.target.name}" and "{ex.target.name}"', ex.target)
                by_direction.setdefault(ex.direction, ex)

    def _validate_spawns_and_drops(self) -> None:
        w = self.world
        for loc in w.locations.values():
            for ref in loc.spawns:
                self._check(ref, w.monsters, "monster", "unknown-monster")
        for mon in w.monsters.values():
            for drop in mon.drops:
                self._check(drop.ref, w.items, "item", "unknown-item")
            if mon.gold[1] < mon.gold[0]:
                self.error("bad-range", f'"{mon.name}" drops a backwards gold range', mon.tree)

    def _validate_kits(self) -> None:
        for cls in self.world.classes.values():
            for _count, ref in cls.kit:
                self._check(ref, self.world.items, "item", "unknown-item")

    def _validate_shops(self) -> None:
        w = self.world
        for shop in w.shops:
            if self._check(shop.at, w.locations, "location", "unknown-location"):
                if "shop" not in w.locations[shop.at.name].features:
                    self.error("shop-without-feature",
                               f'"{shop.at.name}" stocks a shop but does not declare `has shop`',
                               shop.at)
            for ref in shop.stock:
                if not self._check(ref, w.items, "item", "unknown-item"):
                    continue
                if w.items[ref.name].cost is None:
                    self.error("unpriced",
                               f'"{ref.name}" is stocked but has no `costs` line', ref)

    def _validate_defaults(self) -> None:
        defaults: dict[str, list[str]] = {}
        for item in self.world.items.values():
            if item.is_default:
                defaults.setdefault(item.kind, []).append(item.name)
        for kind in ("weapon", "body armor"):
            found = defaults.get(kind, [])
            if not found:
                self.warn("no-default",
                          f"no default {kind}, so a player with that slot empty has nothing "
                          f"to fall back on", self.world.rules or Slot(name="", line=1, column=1))
            elif len(found) > 1:
                self.error("many-defaults",
                           f"more than one default {kind}: {', '.join(found)}",
                           self.world.items[found[-1]].tree)

    def _validate_scaling(self) -> None:
        w = self.world
        #  A track is conventionally named after the stat it grows, but what it
        #  actually grows is what it `raises`, and the two need not match: a
        #  `track faith_track` raising `faith` does grow faith.
        grown = set(w.tracks) | {t.raises for t in w.tracks.values() if t.raises}
        for item in w.items.values():
            if item.scales and item.scales not in grown:
                self.warn("untracked-stat",
                          f'"{item.name}" scales off `{item.scales}`, which no track grows',
                          item.tree)
        for spell in w.spells.values():
            if spell.scales and spell.scales not in grown:
                self.warn("untracked-stat",
                          f'"{spell.name}" scales off `{spell.scales}`, which no track grows',
                          spell.tree)

    def _validate_dispatch(self) -> None:
        w = self.world
        known = set(_BUILTIN_HANDLERS)
        known |= {h for item in w.items.values() for h in item.handlers}
        if w.rules:
            known |= w.rules.handlers

        for holder in (*w.verbs.values(), *w.flows.values(), *w.offers.values()):
            for ref in holder.triggers:
                if ref.name not in known:
                    near = get_close_matches(ref.name, sorted(known), n=1, cutoff=0.6)
                    hint = f' -- did you mean "{near[0]}"?' if near else ""
                    self.diagnostics.append(Diagnostic(
                        ERROR, "unknown-handler",
                        f'`{holder.name}` triggers `{ref.name}`, which nothing handles{hint}',
                        ref.line, ref.column))

        for offer in w.offers.values():
            for ref in offer.resolvers:
                self._check(ref, w.verbs, "verb", "unknown-verb")

    def _validate_orphans(self) -> None:
        w = self.world
        reachable = {i.name for i in w.items.values() if i.is_default}
        reachable |= {r.name for c in w.classes.values() for _n, r in c.kit}
        reachable |= {d.ref.name for m in w.monsters.values() for d in m.drops}
        reachable |= {r.name for s in w.shops for r in s.stock}
        for item in w.items.values():
            if item.name not in reachable:
                self.warn("orphan-item",
                          f'"{item.name}" is declared but nothing grants it -- no kit, '
                          f"no drop, no shop", item.tree)

    def _validate_placeholders(self) -> None:
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9.]*)\}")
        for token in self._strings():
            for name in pattern.findall(str(token)):
                root = name.split(".")[0]
                if root not in _PLACEHOLDERS:
                    near = get_close_matches(root, sorted(_PLACEHOLDERS), n=1, cutoff=0.7)
                    hint = f' -- did you mean "{near[0]}"?' if near else ""
                    self.diagnostics.append(Diagnostic(
                        WARNING, "unknown-placeholder",
                        f"`{{{name}}}` is not a value the engine binds{hint}",
                        token.line or 0, token.column or 0))

    def _strings(self):
        for holder in (self.world.locations, self.world.items, self.world.monsters,
                       self.world.classes, self.world.verbs, self.world.flows,
                       self.world.offers, self.world.spells):
            for decl in holder.values():
                if decl.tree is not None:
                    yield from (t for t in decl.tree.scan_values(
                        lambda v: isinstance(v, Token) and v.type == "STRING"))

    def _validate_aliases(self) -> None:
        w = self.world
        claimed: dict[str, str] = {}
        for holder in (*w.verbs.values(), *w.flows.values(), *w.offers.values()):
            for word in (holder.name, *holder.aliases):
                key = word.casefold()
                if key in claimed and claimed[key] != holder.name:
                    self.error("alias-clash",
                               f'`{word}` is claimed by both `{claimed[key]}` and '
                               f'`{holder.name}`', holder.tree)
                claimed[key] = holder.name


def resolve(tree: Tree, source: Source) -> Resolution:
    """Bind a parse tree into a world, collecting every complaint on the way."""
    resolver = _Resolver(source)
    resolver.collect(tree)
    resolver.validate()
    resolver.diagnostics.sort(key=lambda d: (d.line, d.column))
    return Resolution(world=resolver.world, diagnostics=resolver.diagnostics)
