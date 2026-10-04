"""A local web UI for testing a game without a chat platform.

Runs only when asked for -- `lyo run -a webui` -- and needs no account, no
token and no network: the engine is the same one the Discord adapter drives, so
what works here works there.

Two simulations run side by side over the one world. The persistent session is
the engine the host handed us, saving to the project's sqlite3 file; the
ephemeral one is a second engine with no store attached, which forgets
everything when the process ends and can be reset mid-session. The browser
picks which it is talking to.

No `lyo_present` hook here on purpose: that hook is firstresult, so
implementing it would quietly restyle Discord's output too. Presentation for
this surface belongs in its own stylesheet.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from typing import Any

from lyo.adapters.webui.http import (Request, Response, Server,
                                     Unavailable, event)
from lyo.adapters.webui.session import Line, Session
from lyo.engine import Engine
from lyo.plugins import Adapter, Setting, hookimpl
from lyo.signals import stop_on_signals

SETTINGS = (
    Setting("host", "Interface to bind. Loopback unless widened deliberately.",
            default="127.0.0.1"),
    Setting("port", "Port to listen on.", default="8720"),
    Setting("token", "Shared secret, required when host is not loopback.",
            secret=True),
    Setting("assets", "Where to load quikchat from. Point this at a local copy "
                      "to work offline.", default="https://unpkg.com/quikchat"),
    Setting("theme", "A quikchat theme class.", default="quikchat-theme-dark"),
    Setting("sweep_seconds", "How often timed-out prompts and lapsed "
                             "challenges are checked.", default="1"),
)

SETUP = """Nothing to set up. This adapter is for trying a game out locally,
so it has no account, no token and no external service.

```
lyo run -a webui
```

It prints a URL; open it. The page needs internet once, to fetch
[quikchat](https://github.com/deftio/quikchat) from a CDN. To work offline,
download `quikchat.umd.min.js` and `quikchat.css` next to each other and point
the adapter at them:

```
lyo set adapter.webui.assets=file:///path/to/quikchat
lyo commit
```

**Two simulations.** The page has a *persistent* and an *ephemeral* session.
Persistent is the real one, saved to the project's sqlite3 file alongside
whatever your Discord players have done. Ephemeral keeps nothing and can be
reset from the page, which is what you want while changing a game's rules.
They do not share characters.

**Acting as several players.** The page lets you switch identity, so one
browser can register two characters and duel them against each other. That is
the only practical way to test PvP without a second person.

It binds to `127.0.0.1` by default. Widening it serves an unauthenticated
interface that can act as any character, so a non-loopback host also requires
`adapter.webui.token`, which the printed URL then carries.
"""


@hookimpl
def lyo_adapter() -> Adapter:
    return Adapter(
        name="webui",
        summary="Play in a local browser page, with no platform account.",
        run=run,
        settings=SETTINGS,
        setup=SETUP,
    )


class Clients:
    """The browsers currently listening, and the queues feeding them."""

    def __init__(self) -> None:
        self._queues: dict[int, asyncio.Queue] = {}
        self._next = 0

    def open(self) -> tuple[int, asyncio.Queue]:
        self._next += 1
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._queues[self._next] = queue
        return self._next, queue

    def close(self, handle: int) -> None:
        self._queues.pop(handle, None)

    def push(self, payload: bytes) -> None:
        for queue in list(self._queues.values()):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(payload)

    def __len__(self) -> int:
        return len(self._queues)


class WebUI:
    """Routes a browser onto one of two sessions."""

    def __init__(self, engine: Engine, values: dict[str, str],
                 source: str | None = None) -> None:
        self.values = values
        self.source = source
        self.world = engine.world
        self.clients: dict[str, Clients] = {}
        self.sessions: dict[str, Session] = {}
        self._install("persistent", Session("persistent", engine,
                                            persistent=True))
        self._install("ephemeral", self._fresh())

    #  ------------------------------------------------------------ sessions

    def _fresh(self) -> Session:
        """A second engine over the same world, with nothing behind it."""
        return Session("ephemeral", Engine(self.world), persistent=False)

    def _install(self, name: str, session: Session) -> None:
        clients = self.clients.setdefault(name, Clients())
        session.listeners.clear()
        session.listeners.append(
            lambda line: clients.push(event("line", line.as_dict())))
        self.sessions[name] = session

    def pick(self, name: str) -> Session:
        return self.sessions.get(name) or self.sessions["persistent"]

    def reset(self, name: str) -> bool:
        """Throw an ephemeral simulation away. The persistent one is kept."""
        if name != "ephemeral":
            return False
        self._install("ephemeral", self._fresh())
        return True

    #  --------------------------------------------------------------- timing

    async def sweeping(self, every: float) -> None:
        while True:
            await asyncio.sleep(every)
            for name, session in self.sessions.items():
                for line in session.sweep():
                    self.clients[name].push(event("line", line.as_dict()))

    #  --------------------------------------------------------------- routes

    def attach(self, server: Server) -> None:
        @server.route("GET", "/api/state")
        async def state(request: Request) -> Response:
            session = self.pick(request.one("session", "persistent"))
            described = session.describe()
            described["sessions"] = list(self.sessions)
            described["assets"] = self.values.get(
                "assets", "https://unpkg.com/quikchat")
            described["theme"] = self.values.get(
                "theme", "quikchat-theme-dark")
            described["source"] = self.source
            described["waiting"] = [
                p["id"] for p in described["players"]
                if session.waiting_on(p["id"])]
            return Response.of_json(described)

        @server.route("POST", "/api/say")
        async def say(request: Request) -> Response:
            payload = request.json()
            player = str(payload.get("player") or "").strip()
            text = str(payload.get("text") or "")
            if not player:
                return Response.of_json({"error": "name a player first"}, 400)
            session = self.pick(str(payload.get("session") or "persistent"))
            reply = session.say(player, text)
            answer = reply.as_dict()
            answer["players"] = session.players()
            return Response.of_json(answer)

        @server.route("POST", "/api/reset")
        async def reset(request: Request) -> Response:
            name = str(request.json().get("session") or "")
            if not self.reset(name):
                return Response.of_json(
                    {"error": "only the ephemeral session can be reset"}, 400)
            self.clients[name].push(event("reset", {"session": name}))
            return Response.of_json({"session": name, "reset": True})

        @server.stream("/api/events")
        async def events(request: Request, writer) -> None:
            name = request.one("session", "persistent")
            clients = self.clients.setdefault(name, Clients())
            handle, queue = clients.open()
            try:
                writer.write(event("hello", {"session": name}))
                await writer.drain()
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), 20)
                    except asyncio.TimeoutError:
                        payload = b": keep-alive\n\n"
                    writer.write(payload)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass  #  a browser navigating away is not an error
            finally:
                clients.close(handle)


def run(engine: Engine, values: dict[str, str], source: str | None = None,
        services: tuple = ()) -> None:
    """Serve the testing UI until interrupted."""
    host = values.get("host") or "127.0.0.1"
    port = int(values.get("port") or 8720)
    token = values.get("token") or None
    every = float(values.get("sweep_seconds") or 1)

    if host not in {"127.0.0.1", "::1", "localhost"} and not token:
        #  Same rule the control channel follows: widening an unauthenticated
        #  admin surface is not something to do by accident.
        token = secrets.token_urlsafe(16)
        print(f"note: {host} is not loopback, so a token was generated. "
              f"Set adapter.webui.token to choose your own.", flush=True)

    ui = WebUI(engine, values, source)
    server = Server(host, port, token=token)
    ui.attach(server)

    async def main() -> None:
        await server.listen()
        #  flush: the URL is the whole point of this adapter's output, and
        #  stdout is a pipe under a service manager.
        print(f"serving {engine.world.title!r} at {server.url()}", flush=True)
        if not server.loopback:
            print(f"warning: bound to {host}, reachable beyond this machine",
                  flush=True)
        stop_on_signals()
        async with asyncio.TaskGroup() as group:
            group.create_task(server.serve())
            group.create_task(ui.sweeping(every))
            for factory in services:
                group.create_task(factory())

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("stopped", flush=True)
    except Unavailable as exc:
        raise SystemExit(f"lyo: {exc}") from None
