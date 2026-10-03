"""Multi-turn conversations: `flow` with its `ask` steps.

A flow suspends at every `ask` and resumes when the player answers, so the
driver keeps an explicit stack of blocks rather than recursing. That is what
makes `loop:` in the shop work, and what lets each step carry its own timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lark import Token, Tree

from gamebot.engine.evaluate import LanguageError, Scope
from gamebot.engine.execute import Refused, Stopped, _unwrap, execute
from gamebot.engine.turn import Message, Turn
from gamebot.lang.model import Flow, Item


@dataclass
class Prompt:
    """A question waiting on an answer."""

    flow: str
    key: str
    text: str
    options: list[str] = field(default_factory=list)
    timeout: float = 120.0
    private: bool = True
    reprompts: bool = False

    def rendered(self) -> str:
        if not self.options:
            return self.text
        lines = [self.text] + [f"{i}. {name}"
                              for i, name in enumerate(self.options, start=1)]
        return "\n".join(lines)


@dataclass
class Step:
    """What a flow produced: something to say, something to ask, or an end."""

    messages: list[Message] = field(default_factory=list)
    prompt: Prompt | None = None
    done: bool = False
    refused: bool = False
    registered: tuple[str, str] | None = None


class Conversation:
    """One player's run through one flow."""

    def __init__(self, engine: Any, flow: Flow, actor, private: bool) -> None:
        self.engine = engine
        self.flow = flow
        self.turn = Turn(actor=actor, private=private)
        self.turn.values["start"] = engine.world.start_at.name
        self.scope = Scope(engine.sim, actor, {}, turn=self.turn)
        body = list(flow.tree.children[1:]) if flow.tree is not None else []
        self._frames: list[tuple[list, int, str]] = [(body, 0, "body")]
        self.pending: Prompt | None = None
        self._ask_node: Tree | None = None
        self.answers: dict[str, str] = {}

    # ------------------------------------------------------------ stepping

    def start(self) -> Step:
        return self._advance()

    def _emit(self, **kwargs) -> Step:
        taken, self.turn.messages = self.turn.messages, []
        return Step(messages=taken, **kwargs)

    def _advance(self) -> Step:
        while self._frames:
            statements, index, kind = self._frames[-1]
            if index >= len(statements):
                if kind == "loop":
                    self._frames[-1] = (statements, 0, kind)
                    continue
                self._frames.pop()
                continue

            node = _unwrap(statements[index])
            self._frames[-1] = (statements, index + 1, kind)
            if node is None:
                continue

            if node.data == "ask_stmt":
                self._ask_node = node
                self.pending = self._prompt(node)
                return self._emit(prompt=self.pending)

            if node.data == "loop_stmt":
                self._frames.append((list(node.children), 0, "loop"))
                continue

            if node.data == "handler":
                continue  # `on timeout:` only runs if the flow is abandoned

            try:
                execute(node, self.scope, self.turn)
                self._render_view()
            except Refused:
                self._frames.clear()
                return self._emit(done=True, refused=True)
            except Stopped:
                self._break_loop()
                continue
            except LanguageError as exc:
                self._frames.clear()
                self.turn.say(f"This game cannot do that: {exc}")
                return self._emit(done=True, refused=True)

        created = self.turn.values.get("created")
        registered = None
        if created:
            registered = (self.answers.get(created[0], created[0]),
                          self.answers.get(created[1], created[1]))
        return self._emit(done=True, registered=registered)

    def _render_view(self) -> None:
        name = self.turn.values.pop("view", None)
        if name:
            from gamebot.engine import views
            self.turn.say(views.render(name, self.engine.sim, self.turn.actor),
                          self.turn.private, kind=name)

    def _break_loop(self) -> None:
        while self._frames:
            _, _, kind = self._frames.pop()
            if kind == "loop":
                return

    # --------------------------------------------------------------- asking

    def _prompt(self, node: Tree) -> Prompt:
        key = str(node.children[0])
        text = node.children[1]
        options: list[str] = []
        timeout, reprompts = 120.0, False

        for option in node.children[2:]:
            option = _unwrap(option)
            if option is None:
                continue
            if option.data == "offers":
                options = self._offered(str(option.children[0]))
            elif option.data == "timeout":
                quantity = option.children[0]
                timeout = float(str(quantity.children[0]))
            elif option.data == "reprompts":
                reprompts = True

        return Prompt(flow=self.flow.name, key=key,
                      text=str(text)[1:-1] if text is not None else "",
                      options=options, timeout=timeout,
                      private=self.turn.private, reprompts=reprompts)

    def _offered(self, collection: str) -> list[str]:
        world = self.engine.world
        table = {"class": world.classes, "classes": world.classes,
                 "spell": world.spells, "item": world.items,
                 "location": world.locations}.get(collection, {})
        return list(table)

    # --------------------------------------------------------------- answering

    def reply(self, text: str) -> Step:
        if self.pending is None or self._ask_node is None:
            return self._emit(done=True)

        prompt, node = self.pending, self._ask_node
        matched, action = self._match(node, text, prompt)

        if matched is None:
            if prompt.reprompts:
                return self._emit(prompt=prompt)
            self._frames.clear()
            return self._emit(done=True, refused=True)

        self.answers[prompt.key] = matched
        self.scope.bindings[prompt.key] = matched
        self.turn.values[prompt.key] = matched
        self.pending = self._ask_node = None

        if action == "stop":
            self._break_loop()
        elif action == "buy":
            self._buy(matched)
        return self._advance()

    def _match(self, node: Tree, said: str,
               prompt: Prompt) -> tuple[str | None, str | None]:
        said = said.strip()

        #  A numbered or named menu, from `offers every <thing> by number, name`.
        if prompt.options:
            if said.isdigit() and 1 <= int(said) <= len(prompt.options):
                return prompt.options[int(said) - 1], None
            for option in prompt.options:
                if said.casefold() == option.casefold():
                    return option, None
            return None, None

        for option in node.children[2:]:
            option = _unwrap(option)
            if option is None or option.data != "accepts":
                continue
            spec = option.children[0]
            found, action = self._spec(spec, said)
            if found is not None:
                return found, action
        return None, None

    def _spec(self, spec: Tree, said: str) -> tuple[str | None, str | None]:
        action = _action_of(spec)

        if spec.data == "any_of":
            trimmed = any(isinstance(c, Token) and c.type == "TRIMMED"
                          for c in spec.children if c is not None)
            value = said.strip() if trimmed else said
            return (value or None), action

        if spec.data == "one_of_literals":
            words = [str(t)[1:-1] for t in spec.children[0].children]
            for word in words:
                if said.casefold() == word.casefold():
                    return word, action
            return None, action

        if spec.data == "one_of_names":
            names = [str(t) for t in spec.children[0].children]
            for name in names:
                if said.casefold() == name.casefold():
                    return name, action
            return None, action

        if spec.data == "any_item_in":
            item = self._in_stock(said)
            return (item.name if item else None), action

        return None, action

    def _in_stock(self, said: str) -> Item | None:
        needle = " ".join(said.split()).casefold()
        if not needle:
            return None
        world, here = self.engine.world, self.turn.actor.location
        for shop in world.shops:
            if not shop.at or shop.at.name != here:
                continue
            stocked = [world.items[ref.name] for ref in shop.stock]
            for test in (lambda i: i.name.casefold() == needle,
                         lambda i: needle in [a.casefold() for a in i.aliases],
                         lambda i: needle in i.name.casefold()):
                for item in stocked:
                    if test(item):
                        return item
        return None

    def _buy(self, item_name: str) -> None:
        world, actor = self.engine.world, self.turn.actor
        item = world.items.get(item_name)
        if item is None or item.cost is None:
            self.turn.say("That is not for sale.")
            return
        if actor.gold < item.cost:
            self.turn.say(f"You cannot afford {item.name}.")
            return
        actor.gold -= item.cost
        actor.give(item.name, 1)
        self.turn.say(f"Bought {item.name} for {item.cost} gold. "
                      f"{actor.gold} gold left.")

    # -------------------------------------------------------------- failure

    def abandon(self) -> Step:
        """Give up on the flow, running its `on timeout:` handler if it has one."""
        self._frames.clear()
        self.pending = self._ask_node = None
        body = list(self.flow.tree.children[1:]) if self.flow.tree else []
        for statement in body:
            node = _unwrap(statement)
            if node is not None and node.data == "handler" \
                    and str(node.children[0]) == "timeout":
                for inner in node.children[1:]:
                    inner = _unwrap(inner)
                    if inner is None:
                        continue
                    try:
                        execute(inner, self.scope, self.turn)
                    except (Refused, Stopped, LanguageError):
                        break
        return self._emit(done=True, refused=True)


def _action_of(spec: Tree) -> str | None:
    for child in spec.children:
        if isinstance(child, Tree) and child.data in ("aw_stop", "aw_buy"):
            return "stop" if child.data == "aw_stop" else "buy"
    return None
