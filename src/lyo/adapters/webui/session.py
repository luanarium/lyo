"""One world, one simulation, many browser clients.

Deliberately free of any transport: the HTTP layer registers a callback and
this module never imports asyncio, so the whole thing is testable by calling
`say` and reading what comes back.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from lyo.engine import Engine, Message


@dataclass
class Line:
    """One rendered message, on its way to a browser."""

    text: str
    private: bool = False
    kind: str | None = None
    player: str | None = None
    """Who caused it. The sender sees their own; others see only public lines."""

    def as_dict(self) -> dict:
        return {"text": self.text, "private": self.private,
                "kind": self.kind, "player": self.player}


@dataclass
class Reply:
    """What one turn produced for the caller."""

    lines: list[Line] = field(default_factory=list)
    prompt: str | None = None
    """A flow is waiting on an answer; the next thing typed answers it."""
    refused: bool = False
    unknown: bool = False

    def as_dict(self) -> dict:
        return {"lines": [line.as_dict() for line in self.lines],
                "prompt": self.prompt, "refused": self.refused,
                "unknown": self.unknown}


class Session:
    """An engine plus the browsers watching it."""

    def __init__(self, name: str, engine: Engine, *, persistent: bool,
                 prefix: str = "!",
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.name = name
        self.engine = engine
        self.persistent = persistent
        self.prefix = prefix
        self.clock = clock
        self.listeners: list[Callable[[Line], None]] = []
        #  When each open prompt stops waiting, so a timeout fires on time.
        self._deadlines: dict[str, float] = {}

    # ------------------------------------------------------------- players

    def players(self) -> list[dict]:
        return [
            {"id": p.user_id, "name": p.name, "class": p.char_class,
             "location": p.location, "hp": p.hp, "max_hp": p.max_hp,
             "mp": p.mp, "max_mp": p.max_mp, "gold": p.gold,
             "dueling": self.engine.sim.duel_of(p.user_id) is not None}
            for p in self.engine.sim.players.values()
        ]

    def describe(self) -> dict:
        world = self.engine.world
        return {
            "session": self.name,
            "persistent": self.persistent,
            "title": world.title or "untitled",
            "players": self.players(),
            "prefix": self.prefix,
            "verbs": sorted(
                [*world.verbs, *world.flows, *world.offers]
            ),
        }

    # ---------------------------------------------------------------- turns

    def say(self, player_id: str, text: str) -> Reply:
        """Answer an open prompt, start a conversation, or run a command.

        An open prompt takes the text as it was typed: a prompt is a question,
        and nobody prefixes an answer. Everything else is a command and needs
        the prefix, exactly as it would in a chat room.
        """
        text = text.strip()
        if not text:
            return Reply()

        engine = self.engine
        if engine.talking(player_id):
            return self._flow(player_id, engine.reply_flow(player_id, text))

        if self.prefix:
            if not text.startswith(self.prefix):
                return Reply(
                    lines=[Line(f"Commands start with {self.prefix} -- "
                                f"try {self.prefix}help.", True, "hint",
                                player_id)],
                    unknown=True)
            text = text[len(self.prefix):].strip()
            if not text:
                return Reply()

        flow = engine.flow_named(text.split()[0])
        if flow is not None:
            return self._flow(player_id, engine.begin_flow(player_id, flow))

        outcome = engine.command(player_id, text)
        if outcome.unknown:
            return Reply(
                lines=[Line(f"No such command: {text.split()[0]}", True,
                            "refusal", player_id)],
                unknown=True)

        reply = Reply(lines=self._lines(outcome.messages, player_id),
                      refused=outcome.refused)
        self._publish(reply.lines, player_id)
        if outcome.expires_in:
            #  The adapter owns the waiting, so remember when to announce it.
            self._deadlines[f"offer:{player_id}"] = (
                self.clock() + outcome.expires_in)
        return reply

    def _flow(self, player_id: str, step) -> Reply:
        reply = Reply(lines=self._lines(step.messages, player_id),
                      refused=step.refused)
        if step.prompt is not None:
            reply.prompt = step.prompt.rendered()
            self._deadlines[f"flow:{player_id}"] = (
                self.clock() + step.prompt.timeout)
        else:
            self._deadlines.pop(f"flow:{player_id}", None)
        self._publish(reply.lines, player_id)
        return reply

    @staticmethod
    def _lines(messages: list[Message], player_id: str) -> list[Line]:
        return [Line(m.text, m.private, m.kind, player_id) for m in messages]

    def _publish(self, lines: list[Line], player_id: str) -> None:
        """Send the public half to everyone else watching."""
        for line in lines:
            if line.private:
                continue
            for listen in list(self.listeners):
                listen(line)

    # --------------------------------------------------------------- timing

    def sweep(self) -> list[Line]:
        """Fire anything whose deadline has passed. Called on a timer."""
        now = self.clock()
        fired: list[Line] = []

        for key, deadline in list(self._deadlines.items()):
            if deadline > now:
                continue
            kind, _, player_id = key.partition(":")
            del self._deadlines[key]
            if kind != "flow":
                continue
            step = self.engine.abandon_flow(player_id)
            fired += self._lines(step.messages, player_id)

        for notice in self.engine.expire_offers():
            fired.append(Line(notice.text, False, notice.kind))

        #  An expiry notice is news to everyone, including whoever caused it.
        for line in fired:
            for listen in list(self.listeners):
                listen(line)
        return fired

    def waiting_on(self, player_id: str) -> bool:
        return f"flow:{player_id}" in self._deadlines
