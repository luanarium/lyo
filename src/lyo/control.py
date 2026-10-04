"""The control channel: a running instance, reachable from the CLI.

A Unix socket on POSIX and a loopback TCP port on Windows, so `lyo commit`
followed by `lyo reload` can apply configuration and world changes to a live
service without dropping its chat connection.

It binds to localhost only. Widening it is possible, per the project's
convention, but it is an unauthenticated admin channel, so a non-loopback host
must also set `control.main.token`.
"""

from __future__ import annotations

import asyncio
import json
import contextlib
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
UNIX_AVAILABLE = hasattr(socket, "AF_UNIX") and sys.platform != "win32"


class ControlError(Exception):
    """The control channel could not be reached, or refused the request."""


def socket_path(db: Path) -> Path:
    """Beside the state file, so --db moves both together."""
    return db.with_suffix(".sock")


# --------------------------------------------------------------- the service


@dataclass
class Service:
    """What a running instance exposes to the control channel."""

    engine: Any
    store: Any
    source: Path
    adapter: str = ""
    settings: dict[str, str] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    on_change: Callable[[], None] | None = None

    def status(self) -> dict:
        world = self.engine.world
        sim = self.engine.sim
        return {
            "ok": True,
            "pid": os.getpid(),
            "source": str(self.source),
            "world": world.title or self.source.name,
            "uptime": round(time.monotonic() - self.started, 1),
            "characters": len(sim.players),
            "duels": len(sim.duels),
            "offers": len(sim.offers),
            "locations": len(world.locations),
            "verbs": len(world.verbs),
        }

    def reload(self) -> dict:
        """Re-read committed configuration and the world, validating first."""
        from lyo.lang.check import check

        report = check(self.source)
        if not report.ok:
            return {
                "ok": False,
                "error": f"{self.source} does not resolve",
                "diagnostics": [
                    d.format(report.source) if report.source else d.message
                    for d in report.errors[:20]
                ],
            }

        #  Live settings the adapter reads per message, such as the prefix.
        if self.adapter:
            self.settings.update(self.store.config.live("adapter", self.adapter))
        self.engine.reload(report.world)
        if self.on_change:
            self.on_change()
        return {"ok": True, "reloaded": report.world.title or self.source.name,
                "warnings": len(report.diagnostics) - len(report.errors)}


# ---------------------------------------------------------------- the server


async def serve(service: Service, *, db: Path, host: str | None = None,
                port: int = 0, token: str | None = None) -> None:
    """Listen until cancelled. Unix socket unless a host is given."""
    if host and host not in LOOPBACK and not token:
        raise ControlError(
            f"refusing to bind the control channel to {host} without "
            f"control.main.token -- it is an unauthenticated admin channel")

    handler = _handler(service, token)
    if host or not UNIX_AVAILABLE:
        bound = host or "127.0.0.1"
        server = await asyncio.start_server(handler, bound, port)
        chosen = server.sockets[0].getsockname()[1]
        service.store.db.execute(
            "INSERT INTO meta (key, value) VALUES ('control_port', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (str(chosen),))
        where = f"{bound}:{chosen}"
    else:
        path = socket_path(db)
        path.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(handler, str(path))
        path.chmod(0o600)
        where = str(path)

    print(f"control channel on {where}")

    #  Stop signals are the host's business, not this task's: handling them
    #  here replaced asyncio's own handler and cancelled only this task,
    #  leaving its siblings running with nothing left to interrupt them. See
    #  lyo.signals. The cleanup below still runs, because the host cancelling
    #  its task group cancels this one too.
    loop = asyncio.get_running_loop()

    #  SIGHUP means reload, as it does for every other daemon, so
    #  `systemctl --user reload` and `lyo reload` do the same thing.
    hangup = getattr(signal, "SIGHUP", None)
    if hangup is not None:
        with contextlib.suppress(NotImplementedError, AttributeError):
            loop.add_signal_handler(hangup, _on_hangup, service)

    try:
        async with server:
            await server.serve_forever()
    finally:
        if not host and UNIX_AVAILABLE:
            socket_path(db).unlink(missing_ok=True)
        service.store.db.execute("DELETE FROM meta WHERE key = 'control_port'")


def _on_hangup(service: Service) -> None:
    reply = service.reload()
    if reply.get("ok"):
        print(f"reloaded {reply['reloaded']}")
    else:
        print(f"reload refused: {reply.get('error')}")
        for line in reply.get("diagnostics", []):
            print(f"  {line}")


def _handler(service: Service, token: str | None):
    async def handle(reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            reply = _dispatch(service, token, line)
        except asyncio.TimeoutError:
            reply = {"ok": False, "error": "timed out waiting for a request"}
        except Exception as exc:  # a bad request must not take the service down
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        writer.write(json.dumps(reply).encode() + b"\n")
        await writer.drain()
        writer.close()

    return handle


def _dispatch(service: Service, token: str | None, line: bytes) -> dict:
    if not line.strip():
        return {"ok": False, "error": "empty request"}
    request = json.loads(line)
    if token and request.get("token") != token:
        return {"ok": False, "error": "bad token"}

    operation = request.get("op")
    if operation == "ping":
        return {"ok": True, "pid": os.getpid()}
    if operation == "status":
        return service.status()
    if operation == "reload":
        return service.reload()
    return {"ok": False, "error": f"no such operation: {operation!r}"}


# ---------------------------------------------------------------- the client


def request(operation: str, *, db: Path, host: str | None = None,
            port: int | None = None, token: str | None = None,
            timeout: float = 10.0) -> dict:
    """Ask a running instance one question. Raises if none is listening."""
    payload = json.dumps(
        {"op": operation, **({"token": token} if token else {})}).encode() + b"\n"

    try:
        if host or not UNIX_AVAILABLE:
            if not port:
                raise ControlError("no control port recorded -- is it running?")
            connection = socket.create_connection((host or "127.0.0.1", port),
                                                  timeout=timeout)
        else:
            path = socket_path(db)
            if not path.exists():
                #  Absolute, because a service runs from elsewhere and a
                #  relative path in the message would point at nothing.
                raise ControlError(f"nothing listening on {path.absolute()}")
            connection = socket.socket(socket.AF_UNIX)
            connection.settimeout(timeout)
            try:
                connection.connect(str(path))
            except ConnectionRefusedError as exc:
                connection.close()
                raise ControlError(
                    f"a stale socket at {path.absolute()} -- "
                    f"the instance is not running") from exc
    except (OSError, ControlError) as exc:
        raise ControlError(
            f"no running instance to talk to ({exc}). Start one with `lyo run`."
        ) from exc

    with connection:
        connection.sendall(payload)
        chunks = []
        while not chunks or not chunks[-1].endswith(b"\n"):
            piece = connection.recv(65536)
            if not piece:
                break
            chunks.append(piece)
    body = b"".join(chunks).strip()
    if not body:
        raise ControlError("the instance closed without replying")
    return json.loads(body)


def listening(db: Path, port: int | None = None) -> bool:
    """Whether an instance is reachable, for a hint rather than an error."""
    try:
        return bool(request("ping", db=db, port=port).get("ok"))
    except (ControlError, OSError, json.JSONDecodeError):
        return False
