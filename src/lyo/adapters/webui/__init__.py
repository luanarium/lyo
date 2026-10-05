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

from pathlib import Path

from lyo.adapters.webui.http import (Request, Response, Server, Unavailable,
                                     event, type_of)
from lyo.adapters.webui.session import Line, Session
from lyo.cartridge.png import SIGNATURE, is_placeholder
from lyo.engine import Engine
from lyo.lang.check import check_bytes
from lyo.plugins import Adapter, Setting, hookimpl
from lyo.signals import stop_on_signals

CDN = "https://unpkg.com/quikchat"

#  The two files quikchat ships, and the names a local copy keeps.
VENDORED = ("quikchat.umd.min.js", "quikchat.css")


def vendored(value: str) -> Path | None:
    """The directory a local `assets` setting names, or None for a URL.

    A browser will not load a `file://` script from an `http://` page, so a
    local copy cannot simply be handed to the page as a URL -- the adapter
    serves it instead, from the directory named here.
    """
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    if not value or value.startswith(("http://", "https://", "//")):
        return None
    if value.startswith("file:"):
        #  url2pathname is what turns /C:/x into C:\x on Windows.
        path = Path(url2pathname(urlparse(value).path))
    else:
        path = Path(value).expanduser()
    if path.suffix == ".js":
        path = path.parent
    return path


SETTINGS = (
    Setting("host", "Interface to bind. Loopback unless widened deliberately.",
            default="127.0.0.1"),
    Setting("port", "Port to listen on.", default="8720"),
    Setting("token", "Shared secret, required when host is not loopback.",
            secret=True),
    Setting("assets", "Where to load quikchat from. Point this at a local copy "
                      "to work offline.", default="https://unpkg.com/quikchat"),
    Setting("prefix", "What a command starts with, as in a chat room. Empty "
                      "means no prefix is needed.", default="!"),
    Setting("theme", "A quikchat theme class.", default="quikchat-theme-dark"),
    Setting("pace", "Milliseconds to think before each line of output, shown "
                    "as quikchat's three-dot pulse. 0 is instant.",
            default="600"),
    Setting("player", "Who the page starts out playing as.", default="neo"),
    Setting("session", "Which simulation the page opens on: ephemeral keeps "
                       "nothing, persistent saves.", default="ephemeral"),
    Setting("sweep_seconds", "How often timed-out prompts and lapsed "
                             "challenges are checked.", default="1"),
    Setting("max_upload", "Largest gameworld the page will accept, in bytes.",
            default="4194304"),
)

SETUP = """Nothing to set up. This adapter is for trying a game out locally,
so it has no account, no token and no external service.

```
lyo run -a webui
```

It prints a URL; open it. The page needs internet once, to fetch
[quikchat](https://github.com/deftio/quikchat) from a CDN. To work offline,
download `quikchat.umd.min.js` and `quikchat.css` next to each other and name
the directory holding them:

```
lyo set adapter.webui.assets=/path/to/quikchat
lyo commit
```

A `file://` URL means the same thing, and on Windows that is
`file:///C:/path/to/quikchat`. Either way the adapter serves those two files
itself, from `/assets/`, because a page served over HTTP is not allowed to load
a script off the local filesystem. Anything beginning `http://` or `https://` is
handed to the page as it stands, so a CDN or a mirror still works.

The page opens on the ephemeral session as `neo`, both of which are settings,
so poking around saves nothing until you switch deliberately.

**Loading a gameworld.** The box in the left margin is the loaded gameworld's
cover. Click it to load another -- a PNG cartridge, whose own pixels become the
cover, or a bare markdown file. A gameworld is checked before it is accepted,
and a file that does not resolve is refused with the same diagnostics `lyo
lint` would give, so a typo is reported rather than half-loaded.

A loaded gameworld runs in the ephemeral session only. The persistent one keeps
serving the configured game, because its saved characters refer to that game's
items and locations by id and would be orphaned by another.

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
        #  A loaded gameworld replaces the ephemeral world only; see SETUP.
        self.loaded: Any = None
        self.loaded_name: str | None = None
        self.covers: dict[str, bytes | None] = {
            "persistent": self._packaged_cover(source), "ephemeral": None}
        self._install("persistent", Session(
            "persistent", engine, persistent=True,
            prefix=values.get("prefix", "!")))
        self._install("ephemeral", self._fresh())

    #  ------------------------------------------------------------ sessions

    @property
    def prefix(self) -> str:
        """Read through, so a reload that changes the prefix takes effect."""
        return self.values.get("prefix", "!")

    def assets_url(self) -> str:
        """Where the page should load quikchat from.

        A local copy is served from here rather than handed over as a
        `file://` URL, which the page's own origin would not be allowed to
        load. Read through, so `lyo reload` can move it.
        """
        value = self.values.get("assets") or CDN
        return f"/assets/{VENDORED[0]}" if vendored(value) else value

    @staticmethod
    def _cover_of(data: bytes | None) -> bytes | None:
        """A cartridge's pixels are its cover -- unless `pack` drew them.

        A label `lyo pack` generated for want of art is a featureless square,
        and the page has something better to draw, so it is not a cover.
        """
        if not data or not data.startswith(SIGNATURE):
            return None
        return None if is_placeholder(data) else data

    @classmethod
    def _packaged_cover(cls, source: str | None) -> bytes | None:
        if not source:
            return None
        path = Path(source)
        if path.suffix.lower() != ".png" or not path.exists():
            return None
        try:
            return cls._cover_of(path.read_bytes())
        except OSError:  # pragma: no cover - unreadable file
            return None

    def _fresh(self) -> Session:
        """A second engine over the same world, with nothing behind it."""
        world = self.loaded or self.world
        return Session("ephemeral", Engine(world), persistent=False,
                       prefix=self.prefix)

    # ------------------------------------------------------- gameworlds

    def gameworld(self, session: str) -> dict:
        """What the page shows under the cover: which gameworld is loaded."""
        if session == "ephemeral" and self.loaded_name:
            return {"name": self.loaded_name,
                    "title": self.loaded.title or self.loaded_name,
                    "cover": self.covers.get("ephemeral") is not None,
                    "loaded": True}
        name = Path(self.source).name if self.source else "default"
        return {"name": name, "title": self.world.title or name,
                "cover": self.covers.get("persistent") is not None,
                "loaded": False}

    def load_gameworld(self, name: str, data: bytes) -> tuple[bool, list, dict]:
        """Accept a gameworld file, or refuse it with the reasons.

        It is checked in full before anything is replaced, so a file with a
        typo in it leaves the running session exactly as it was.
        """
        report = check_bytes(name or "gameworld", data)
        if not report.ok:
            lines = [
                {"where": (report.source.where(d.line, d.column)
                           if report.source else name),
                 "severity": d.severity, "code": d.code, "message": d.message}
                for d in report.errors[:12]
            ]
            return False, lines, {}

        self.loaded = report.world
        self.loaded_name = name or "gameworld"
        self.covers["ephemeral"] = self._cover_of(data)
        self._install("ephemeral", self._fresh())
        self.clients["ephemeral"].push(
            event("reset", {"session": "ephemeral"}))
        return True, [], self.gameworld("ephemeral")

    def unload_gameworld(self) -> dict:
        """Back to the gameworld the host was started with."""
        self.loaded = None
        self.loaded_name = None
        self.covers["ephemeral"] = None
        self._install("ephemeral", self._fresh())
        self.clients["ephemeral"].push(
            event("reset", {"session": "ephemeral"}))
        return self.gameworld("ephemeral")

    def _install(self, name: str, session: Session) -> None:
        clients = self.clients.setdefault(name, Clients())
        session.listeners.clear()
        session.listeners.append(
            lambda line: clients.push(event("line", line.as_dict())))
        self.sessions[name] = session

    @property
    def opens_on(self) -> str:
        """Which simulation an unnamed request means, and the page opens on.

        Ephemeral by default, so neither a stray request nor a first visit
        writes to the real save.
        """
        asked = self.values.get("session") or "ephemeral"
        return asked if asked in self.sessions else "ephemeral"

    def pick(self, name: str) -> Session:
        return self.sessions.get(name) or self.sessions[self.opens_on]

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
            session = self.pick(request.one("session", self.opens_on))
            described = session.describe()
            described["sessions"] = list(self.sessions)
            described["assets"] = self.assets_url()
            described["theme"] = self.values.get(
                "theme", "quikchat-theme-dark")
            described["pace"] = int(self.values.get("pace") or 0)
            described["player"] = self.values.get("player", "neo")
            described["gameworld"] = self.gameworld(session.name)
            described["max_upload"] = int(
                self.values.get("max_upload") or 4 * 1024 * 1024)
            #  Read through rather than from the session, so `lyo reload`
            #  changing the prefix reaches a page that is already open.
            described["prefix"] = self.prefix
            for session in self.sessions.values():
                session.prefix = self.prefix
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
            session = self.pick(str(payload.get("session") or self.opens_on))
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

        #  One route per file quikchat ships: the names are fixed, so there is
        #  no path to traverse out of the directory the setting names.
        @server.route("GET", f"/assets/{VENDORED[0]}")
        @server.route("GET", f"/assets/{VENDORED[1]}")
        async def asset(request: Request) -> Response:
            directory = vendored(self.values.get("assets") or CDN)
            if directory is None:
                return Response.text("quikchat is loaded from a CDN here, so "
                                     "there is no local copy to serve", 404)
            name = request.path.rsplit("/", 1)[-1]
            try:
                data = (directory / name).read_bytes()
            except OSError:
                return Response.text(
                    f"adapter.webui.assets names {directory}, which has no "
                    f"{name} in it", 404)
            return Response(200, data, type_of(name))

        @server.route("GET", "/api/cover")
        async def cover(request: Request) -> Response:
            name = request.one("session", self.opens_on)
            data = self.covers.get(name)
            if not data:
                return Response(204)
            return Response(200, data, "image/png")

        @server.route("POST", "/api/gameworld")
        async def gameworld(request: Request) -> Response:
            filename = request.one("name", "gameworld")
            if not request.body:
                return Response.of_json({"error": "nothing was uploaded"}, 400)
            ok, problems, info = self.load_gameworld(filename, request.body)
            if not ok:
                return Response.of_json(
                    {"error": f"{filename} does not resolve",
                     "problems": problems}, 400)
            return Response.of_json({"gameworld": info, "session": "ephemeral"})

        @server.route("POST", "/api/gameworld/unload")
        async def unload(request: Request) -> Response:
            return Response.of_json({"gameworld": self.unload_gameworld(),
                                     "session": "ephemeral"})

        @server.stream("/api/events")
        async def events(request: Request, writer) -> None:
            name = request.one("session", self.opens_on)
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
