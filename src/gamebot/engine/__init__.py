"""The shared simulation: world state, turns, duels, respawns."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from lark import Token, Tree

from gamebot.engine import views
from gamebot.engine.bind import Unbound, bind
from gamebot.engine.flows import Conversation, Prompt, Step
from gamebot.engine.evaluate import LanguageError, Scope, evaluate
from gamebot.engine.execute import Refused, Stopped, run_body
from gamebot.engine.state import Duel, Monster, Offer, Player, Sim
from gamebot.engine.turn import Message, Turn, render
from gamebot.lang.model import Item, Spell, Verb, World

__all__ = ["Engine", "Outcome", "Message", "Prompt", "Step"]


@dataclass
class Outcome:
    messages: list[Message] = field(default_factory=list)
    refused: bool = False
    unknown: bool = False
    expires_in: float | None = None
    """Seconds until a challenge this command made lapses, if it made one.

    The adapter owns the waiting, exactly as it does for a flow's prompts.
    """

    @property
    def text(self) -> str:
        return "\n".join(m.text for m in self.messages)

    def __bool__(self) -> bool:
        return not (self.refused or self.unknown)


class Engine:
    """Drives one world for many players."""

    def __init__(self, world: World, *, seed: int | None = None,
                 clock: Any = None, store: Any = None) -> None:
        self.world = world
        self.sim = Sim(world=world, rng=random.Random(seed),
                       **({"clock": clock} if clock else {}))
        self.store = store
        self._vocabulary = self._index()
        self._talking: dict[str, Conversation] = {}
        self.restored: list[str] = []
        if store is not None:
            self.restored = store.load(self.sim)

    def reload(self, world: World) -> None:
        """Swap in a revalidated world, keeping the players who are logged in.

        Duels come across too, since the players in them do. Pending
        challenges do not: they are measured in seconds, and the world they
        were made in has just changed underneath them.
        """
        previous = self.sim
        self.world = world
        self.sim = Sim(world=world, rng=previous.rng, clock=previous.clock,
                       offset=previous.offset)
        self.sim.players = previous.players
        self.sim.duels = previous.duels
        self._vocabulary = self._index()
        self._talking.clear()
        self._persist()

    # ------------------------------------------------------- persistence

    def _persist(self) -> None:
        """Save after anything that changed the simulation."""
        if self.store is not None:
            self.store.save(self.sim)

    # ------------------------------------------------------------ clock

    def advance(self, seconds: float) -> list[Message]:
        """Move time forward without sleeping. For tests; play uses the clock."""
        self.sim.offset += seconds
        return self.expire_offers()

    def expire_offers(self) -> list[Message]:
        """Drop any challenge past its deadline, and say so."""
        notices = []
        for offer in self.sim.expire_offers():
            declared = self.world.offers.get(offer.kind)
            text = (self._expiry_text(declared)
                    or f"The {offer.kind} challenge expired.")
            notices.append(Message(text))
        if notices:
            self._persist()
        return notices

    @staticmethod
    def _expiry_text(declared) -> str | None:
        if declared is None or declared.tree is None:
            return None
        for node in declared.tree.iter_subtrees():
            if node.data == "expires" and node.children[-1] is not None:
                return str(node.children[-1])[1:-1]
        return None

    # --------------------------------------------------------- vocabulary

    def _index(self) -> dict[str, Any]:
        words: dict[str, Any] = {}
        for holder in (*self.world.verbs.values(), *self.world.flows.values(),
                       *self.world.offers.values()):
            for word in (holder.name, *holder.aliases):
                words[word.casefold()] = holder
        return words

    # ---------------------------------------------------------- registration

    def register(self, user_id: str, name: str, char_class: str,
                 *, announce: bool = True) -> Outcome:
        """Create a character. The `register` flow drives this once it runs."""
        if user_id in self.sim.players:
            return Outcome([Message("You already have a character.", True)],
                           refused=True)
        declared = self.world.classes.get(char_class)
        if declared is None:
            return Outcome([Message(f"No class called {char_class}.", True)],
                           refused=True)

        hp = self.world.start_with.get("hp", 1)
        player = Player(
            user_id=user_id, name=name, char_class=char_class,
            location=self.world.start_at.name,
            hp=hp, max_hp=hp,
            mp=declared.stats.get("mp", 0), max_mp=declared.stats.get("mp", 0),
            gold=self.world.start_with.get("gold", 0),
            stats={k: v for k, v in declared.stats.items() if k != "mp"},
        )
        for count, ref in declared.carried:
            player.give(ref.name, count)
        for count, ref in declared.equipped:
            player.give(ref.name, count)
            item = self.world.items.get(ref.name)
            if item and item.slot:
                player.equipped[item.slot] = ref.name
                player.take(ref.name, 1)
        self.sim.players[user_id] = player
        self._persist()
        if not announce:
            return Outcome()
        return Outcome([Message(
            f"{name} the {char_class} begins in {player.location}.", True)])

    # -------------------------------------------------------------- command

    def command(self, user_id: str, text: str) -> Outcome:
        words = text.split()
        if not words:
            return Outcome(unknown=True)

        holder = self._vocabulary.get(words[0].casefold())
        if holder is None:
            return Outcome(unknown=True)

        if holder.name in self.world.flows:
            return Outcome(unknown=False, refused=True,
                           messages=[Message(
                               f"`{holder.name}` is a conversation -- "
                               f"start it with begin_flow.", True)])

        player = self.sim.players.get(user_id)
        if player is None:
            return Outcome([Message("Use register first.")], refused=True)

        self.sim.expire_offers()
        if holder.name in self.world.offers:
            return self._offer(holder, player, words[1:])
        return self._verb(holder, player, words[1:])

    # ----------------------------------------------------------------- verbs

    def _verb(self, verb: Verb, player: Player, words: list[str]) -> Outcome:
        duel = self.sim.duel_of(player.user_id)
        opponent = self.sim.players[duel.other(player.user_id)] if duel else None
        rules = self._duel_rules()

        if duel and verb.name in ("attack", "cast") and rules.get("turn_based"):
            if duel.turn != player.user_id:
                return Outcome([Message("It is not your turn.")], refused=True)

        try:
            bound = bind(verb.slots, words, self.sim, player,
                         duel_opponent=opponent)
        except Unbound as exc:
            return Outcome([Message(self._unbound_text(exc, player))], refused=True)

        #  An optional `<spell?>` left unsaid means the game's only spell.
        if any(s.name == "spell" for s in verb.slots) and "spell" not in bound:
            default = next(iter(self.world.spells.values()), None)
            if default is not None:
                bound["spell"] = default

        turn = Turn(actor=player, private=verb.visibility == "private")
        scope = Scope(self.sim, player, dict(bound),
                      duel=duel is not None,
                      duel_armor=bool(duel and rules.get("armor_applies")),
                      turn=turn)

        before_hp = player.hp
        try:
            run_body(verb.tree.children[len(verb.slots) + 1:], scope, turn)
        except Refused:
            return Outcome(turn.messages, refused=True)
        except Stopped:
            pass
        except LanguageError as exc:
            return Outcome([Message(f"This game cannot do that: {exc}")],
                           refused=True)

        #  What the verb used is what the tracks grow from.
        if turn.dealt:
            if any(s.name == "spell" for s in verb.slots):
                turn.cast = bound.get("spell")
            elif any(s.name == "weapon" for s in verb.slots):
                turn.attacked_with = bound.get("weapon") or evaluate(
                    Tree("path", [Token("NAME", "weapon")]), scope)

        self._grow(player, turn, took_damage=player.hp < before_hp)
        self._after(verb, player, turn, duel)
        self._render_view(turn)
        if not turn.refused:
            self._persist()
        return Outcome(turn.messages)

    def _unbound_text(self, exc: Unbound, player: Player) -> str:
        if exc.slot == "monster":
            living = self.sim.living_in(player.location)
            if not living:
                return "There is nothing here to fight."
            names = ", ".join(m.name for m in living)
            return f"Attack what? Here: {names}."
        if exc.slot == "exit":
            here = self.world.locations[player.location]
            ways = ", ".join(f"{e.direction} to {e.target.name}" for e in here.exits)
            return f"Go where? From here: {ways}."
        if exc.slot == "player":
            return "Name a player with an @mention."
        return f"Which {exc.slot}?"

    # ---------------------------------------------------------------- offers

    def _offer(self, declared, player: Player, words: list[str]) -> Outcome:
        try:
            bound = bind(declared.slots[-1:], words, self.sim, player)
        except Unbound as exc:
            return Outcome([Message(self._unbound_text(exc, player))], refused=True)
        target = bound.get("player")

        turn = Turn(actor=player, private=declared.visibility == "private")
        scope = Scope(self.sim, player, {"target": target, "opponent": target},
                      turn=turn)
        try:
            run_body(self._requirements(declared) + self._guards(declared),
                     scope, turn)
        except Refused:
            return Outcome(turn.messages, refused=True)
        except LanguageError as exc:
            return Outcome([Message(f"This game cannot do that: {exc}")],
                           refused=True)

        if target is None or target.user_id == player.user_id:
            return Outcome([Message("Challenge someone else.")], refused=True)

        seconds = declared.expires_after or 60
        self.sim.offers.append(Offer(declared.name, player.user_id,
                                     target.user_id, self.sim.now + seconds))
        self._persist()
        return Outcome([Message(
            f"{player.name} challenges {target.name} to a {declared.name}. "
            f"{target.name} has {seconds} seconds to accept or decline.")],
            expires_in=float(seconds))

    @staticmethod
    def _requirements(declared) -> list[Tree]:
        if declared.tree is None:
            return []
        return [n for n in declared.tree.iter_subtrees() if n.data == "requires"]

    @staticmethod
    def _guards(declared) -> list[Tree]:
        if declared.tree is None:
            return []
        return [n for n in declared.tree.iter_subtrees() if n.data == "refuse"]

    def _duel_rules(self) -> dict[str, bool]:
        found: dict[str, bool] = {}
        for offer in self.world.offers.values():
            if offer.tree is None:
                continue
            for node in offer.tree.iter_subtrees():
                if node.data in ("turn_based", "armor_applies", "no_retaliation"):
                    found[node.data] = True
        return found

    def _after(self, verb: Verb, player: Player, turn: Turn,
               duel: Duel | None) -> None:
        """Honour what the offer declared about its resolving verbs."""
        for declared in self.world.offers.values():
            for ref, word in self._resolutions(declared):
                if word != verb.name:
                    continue
                if ref == "accepted":
                    self._start_duel(player, turn)
                elif ref == "declined":
                    self._drop_offer(player, turn)
                elif ref == "forfeited" and duel:
                    self._end_duel(duel, winner=duel.other(player.user_id), turn=turn)

        if duel and duel in self.sim.duels:
            for side in (duel.a, duel.b):
                if self.sim.players[side].hp <= 0:
                    self._end_duel(duel, winner=duel.other(side), turn=turn)
                    return
            if turn.dealt and not turn.refused:
                duel.turn = duel.other(player.user_id)

    @staticmethod
    def _resolutions(declared) -> list[tuple[str, str]]:
        if declared.tree is None:
            return []
        out = []
        for node in declared.tree.iter_subtrees():
            if node.data == "resolved_by":
                out.append((str(node.children[0]), str(node.children[-1])))
        return out

    def _start_duel(self, player: Player, turn: Turn) -> None:
        offer = self.sim.offer_to(player.user_id)
        if offer is None:
            return
        self.sim.offers.remove(offer)
        challenger = self.sim.players[offer.challenger]
        if challenger.location != player.location:
            turn.say(f"{challenger.name} is no longer here.")
            return
        self.sim.duels.append(Duel(offer.challenger, player.user_id,
                                   turn=offer.challenger))
        turn.say(f"The duel begins. {challenger.name} strikes first.")

    def _drop_offer(self, player: Player, turn: Turn) -> None:
        offer = self.sim.offer_to(player.user_id)
        if offer is not None:
            self.sim.offers.remove(offer)

    def _end_duel(self, duel: Duel, winner: str, turn: Turn) -> None:
        if duel in self.sim.duels:
            self.sim.duels.remove(duel)
        loser = duel.other(winner)
        turn.say(f"{self.sim.players[loser].name} has fallen. "
                 f"{self.sim.players[winner].name} wins. There is no prize.")

    # ---------------------------------------------------------------- growth

    def _grow(self, player: Player, turn: Turn, took_damage: bool) -> None:
        for track in self.world.tracks.values():
            if not self._advances(track, turn, took_damage):
                continue
            player.progress[track.name] = player.progress.get(track.name, 0) + 1
            self._maybe_raise(player, track, turn)

    @staticmethod
    def _advances(track, turn: Turn, took_damage: bool) -> bool:
        for trigger in track.triggers:
            if trigger == "on_damage" and took_damage:
                return True
            if trigger == "on_attack" and turn.attacked_with is not None:
                if track.scaling is None or track.scaling == turn.attacked_with.scales:
                    return True
            if trigger == "on_cast" and turn.cast is not None:
                if track.scaling is None or track.scaling == turn.cast.scales:
                    return True
        return False

    def _maybe_raise(self, player: Player, track, turn: Turn) -> None:
        scope = Scope(self.sim, player)
        for _ in range(100):
            cost = int(evaluate(track.cost, scope) or 0) if track.cost else 0
            if cost <= 0 or player.progress.get(track.name, 0) < cost:
                return
            player.progress[track.name] -= cost
            self._apply_raise(player, track)
            turn.levelled.append(track.raises)
            turn.say(f"{player.name}'s {track.raises} rises to "
                     f"{self._current(player, track.raises)}.")

    @staticmethod
    def _apply_raise(player: Player, track) -> None:
        name, amount = track.raises, track.amount
        if name == "max_hp":
            player.max_hp += amount
        elif name == "max_mp":
            player.max_mp += amount
        else:
            player.stats[name] = player.stats.get(name, 0) + amount
        if track.effect:
            effect, by = track.effect
            if effect.startswith("heal"):
                player.hp = min(player.hp + by, player.max_hp)
            elif effect.startswith("restore"):
                player.mp = min(player.mp + by, player.max_mp)

    @staticmethod
    def _current(player: Player, name: str) -> int:
        if name in ("max_hp", "max_mp"):
            return getattr(player, name)
        return player.stats.get(name, 0)

    # ----------------------------------------------------------------- flows

    def flow_named(self, word: str) -> str | None:
        """The flow a typed word starts, if it starts one."""
        holder = self._vocabulary.get(word.casefold())
        if holder is not None and holder.name in self.world.flows:
            return holder.name
        return None

    def talking(self, user_id: str) -> bool:
        return user_id in self._talking

    def begin_flow(self, user_id: str, name: str) -> Step:
        flow = self.world.flows.get(name)
        if flow is None:
            return Step(messages=[Message(f"No conversation called {name}.", True)],
                        done=True, refused=True)

        actor = self.sim.players.get(user_id) or self._stranger(user_id)
        talk = Conversation(self, flow, actor, private=flow.visibility != "public")
        step = talk.start()
        self._settle(user_id, talk, step)
        return step

    def reply_flow(self, user_id: str, text: str) -> Step:
        talk = self._talking.get(user_id)
        if talk is None:
            return Step(done=True)
        step = talk.reply(text)
        self._settle(user_id, talk, step)
        return step

    def abandon_flow(self, user_id: str) -> Step:
        talk = self._talking.pop(user_id, None)
        if talk is None:
            return Step(done=True)
        return talk.abandon()

    def _settle(self, user_id: str, talk: Conversation, step: Step) -> None:
        """Keep the conversation if it is still asking; finish it otherwise."""
        if step.prompt is not None:
            self._talking[user_id] = talk
            return
        self._talking.pop(user_id, None)
        self._persist()
        if step.registered:
            name, char_class = step.registered
            #  The flow says its own line; do not announce it twice.
            created = self.register(user_id, name, char_class, announce=False)
            step.messages = [m for m in step.messages] + created.messages
            step.refused = step.refused or created.refused

    def _stranger(self, user_id: str) -> Player:
        """A stand-in for someone with no character yet, so `register` can run."""
        return Player(user_id=user_id, name="", char_class="",
                      location=self.world.start_at.name, hp=1, max_hp=1,
                      mp=0, max_mp=0)

    # ----------------------------------------------------------------- views

    def _render_view(self, turn: Turn) -> None:
        name = turn.values.get("view")
        if name:
            turn.say(views.render(name, self.sim, turn.actor), turn.private,
                     kind=name)
