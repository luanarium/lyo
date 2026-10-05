"""A small HTTP server for the testing UI.

Hand-rolled on asyncio rather than `http.server`, for the same reason the
control channel is: it has to share one event loop with the adapter's other
work, and threads would buy nothing here. The subset is deliberate --
HTTP/1.1, Content-Length bodies, no keep-alive except for the event stream.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlparse

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MAX_BODY = 8 * 1024 * 1024   # a gameworld upload, not just a command


class Unavailable(Exception):
    """The address could not be bound."""

    def __init__(self, host: str, port: int, cause: OSError) -> None:
        self.host, self.port, self.cause = host, port, cause
        import errno

        #  Winsock numbers its own errors (WSAEADDRINUSE is 10048), and Python
        #  passes those through untranslated, so each reason is a small set.
        def one_of(*names: str) -> set[int]:
            return {n for n in (getattr(errno, name, None) for name in names)
                    if n is not None}

        if cause.errno in one_of("EADDRINUSE", "WSAEADDRINUSE"):
            detail = (f"something is already listening on {host}:{port}. "
                      f"Stop it, or choose another port: "
                      f"`lyo run -a webui -s webui.port={port + 1}`")
        elif cause.errno in one_of("EACCES", "EPERM", "WSAEACCES"):
            detail = (f"not permitted to bind {host}:{port}. Ports below 1024 "
                      f"need privileges; pick a higher one.")
        elif cause.errno in one_of("EADDRNOTAVAIL", "WSAEADDRNOTAVAIL"):
            detail = (f"no interface on this machine has the address {host}. "
                      f"Check `adapter.webui.host`.")
        elif cause.errno is None:
            #  asyncio collapses a multi-address failure into one OSError with
            #  no errno and the candidate list as its message, so the real
            #  reason is gone. Name the two that are plausible.
            detail = (f"could not bind {host}:{port}. Either no interface on "
                      f"this machine has that address, or the port needs "
                      f"privileges. Check `adapter.webui.host`.")
        else:
            detail = f"could not bind {host}:{port}: {cause.strerror or cause}"
        super().__init__(detail)


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes = b""

    def json(self) -> dict:
        if not self.body:
            return {}
        try:
            loaded = json.loads(self.body)
        except (ValueError, UnicodeDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def one(self, key: str, default: str = "") -> str:
        found = self.query.get(key)
        return found[0] if found else default


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of_json(cls, payload: dict, status: int = 200) -> "Response":
        return cls(status, json.dumps(payload).encode(),
                   "application/json; charset=utf-8")

    @classmethod
    def text(cls, message: str, status: int = 200) -> "Response":
        return cls(status, message.encode(), "text/plain; charset=utf-8")


_REASON = {200: "OK", 204: "No Content", 400: "Bad Request",
           401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
           413: "Payload Too Large", 500: "Internal Server Error"}


def render(response: Response) -> bytes:
    reason = _REASON.get(response.status, "OK")
    lines = [f"HTTP/1.1 {response.status} {reason}",
             f"Content-Type: {response.content_type}",
             f"Content-Length: {len(response.body)}",
             "Cache-Control: no-store",
             "Connection: close"]
    lines += [f"{key}: {value}" for key, value in response.headers.items()]
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + response.body


async def read_request(reader: asyncio.StreamReader) -> Request | None:
    head = await reader.readuntil(b"\r\n\r\n")
    text = head.decode("latin-1")
    start, *rest = text.rstrip().split("\r\n")
    try:
        method, target, _ = start.split(" ", 2)
    except ValueError:
        return None

    headers = {}
    for line in rest:
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()

    length = int(headers.get("content-length") or 0)
    if length > MAX_BODY:
        raise ValueError("body too large")
    body = await reader.readexactly(length) if length else b""

    parsed = urlparse(target)
    return Request(method.upper(), parsed.path, parse_qs(parsed.query),
                   headers, body)


#  Spelled out rather than asked of `mimetypes`, which on Windows reads the
#  registry first and there answers `text/plain` for .js on some machines.
#  The page loads app.js as a module, and a browser refuses a module served as
#  anything but JavaScript, so the registry would decide whether the UI runs.
TYPES = {".html": "text/html; charset=utf-8",
         ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8",
         ".mjs": "text/javascript; charset=utf-8",
         ".json": "application/json; charset=utf-8",
         ".svg": "image/svg+xml",
         ".png": "image/png",
         ".ico": "image/x-icon",
         ".woff2": "font/woff2"}


class Static:
    """Files shipped beside this module, served by name."""

    def __init__(self, package: str = "lyo.adapters.webui.static") -> None:
        self.root = files(package)

    def read(self, name: str) -> Response | None:
        name = name.lstrip("/") or "index.html"
        if "/" in name or "\\" in name or ".." in name:
            return None
        try:
            data = (self.root / name).read_bytes()
        except (FileNotFoundError, OSError, NotADirectoryError):
            return None
        return Response(200, data, type_of(name))


def type_of(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in TYPES:
        return TYPES[suffix]
    kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if kind.startswith("text/") or kind.endswith("javascript"):
        kind += "; charset=utf-8"
    return kind


Handler = Callable[[Request], Awaitable[Response | None]]


class Server:
    """Routes requests, and holds open event streams."""

    def __init__(self, host: str, port: int, *, token: str | None = None,
                 static: Static | None = None) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.static = static or Static()
        self.routes: dict[tuple[str, str], Handler] = {}
        self.streams: dict[str, Callable[[Request], Awaitable[None]]] = {}
        self._server: asyncio.AbstractServer | None = None

    @property
    def loopback(self) -> bool:
        return self.host in LOOPBACK

    def route(self, method: str, path: str):
        def take(handler: Handler) -> Handler:
            self.routes[(method.upper(), path)] = handler
            return handler
        return take

    def stream(self, path: str):
        """A route that holds the connection open and writes events."""
        def take(handler):
            self.streams[path] = handler
            return handler
        return take

    def url(self) -> str:
        shown = "localhost" if self.host in ("127.0.0.1", "::1") else self.host
        base = f"http://{shown}:{self.port}/"
        return f"{base}?token={self.token}" if self.token else base

    def permitted(self, request: Request) -> bool:
        if not self.token:
            return True
        offered = (request.one("token")
                   or request.headers.get("x-lyo-token", ""))
        return secrets.compare_digest(offered, self.token)

    async def listen(self) -> int:
        """Bind, and report the port actually taken. 0 means let the OS pick.

        A busy port is an ordinary thing to hit, so it is reported as a
        sentence rather than a stack trace.
        """
        try:
            self._server = await asyncio.start_server(
                self._client, self.host, self.port)
        except OSError as exc:
            raise Unavailable(self.host, self.port, exc) from None
        chosen = self._server.sockets[0].getsockname()
        self.port = chosen[1] if isinstance(chosen, tuple) else self.port
        return self.port

    async def serve(self) -> None:
        if self._server is None:
            await self.listen()
        async with self._server:
            await self._server.serve_forever()

    async def _client(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        try:
            request = await read_request(reader)
            if request is None:
                await self._send(writer, Response.text("bad request", 400))
                return
            if not self.permitted(request):
                await self._send(writer, Response.text("unauthorized", 401))
                return

            if request.method == "GET" and request.path in self.streams:
                await self._open_stream(request, writer)
                return

            response = await self._dispatch(request)
            await self._send(writer, response)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionResetError, BrokenPipeError):
            pass
        except ValueError as exc:
            await self._send(writer, Response.text(str(exc), 413))
        finally:
            writer.close()
            with _quiet():
                await writer.wait_closed()

    async def _dispatch(self, request: Request) -> Response:
        handler = self.routes.get((request.method, request.path))
        if handler is not None:
            found = await handler(request)
            return found if found is not None else Response(204)

        if request.method != "GET":
            return Response.text("method not allowed", 405)
        served = self.static.read(request.path)
        return served if served is not None else Response.text("not found", 404)

    async def _open_stream(self, request: Request,
                           writer: asyncio.StreamWriter) -> None:
        writer.write(b"HTTP/1.1 200 OK\r\n"
                     b"Content-Type: text/event-stream; charset=utf-8\r\n"
                     b"Cache-Control: no-store\r\n"
                     b"Connection: keep-alive\r\n"
                     b"X-Accel-Buffering: no\r\n\r\n")
        await writer.drain()
        await self.streams[request.path](request, writer)

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, response: Response) -> None:
        writer.write(render(response))
        with _quiet():
            await writer.drain()


class _quiet:
    """Swallow the disconnects that are normal when a browser navigates away."""

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        return kind is not None and issubclass(
            kind, (ConnectionResetError, BrokenPipeError, OSError))


def event(name: str, payload: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()
