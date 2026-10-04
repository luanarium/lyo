"""The local testing UI: sessions, routing, and the HTTP surface."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from lyo.adapters.webui import WebUI, lyo_adapter
from lyo.adapters.webui.http import Request, Response, Server, Static, render
from lyo.adapters.webui.session import Line, Session
from lyo.engine import Engine
from lyo.lang.check import check
from lyo.store import Store

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


@pytest.fixture(scope="module")
def world():
    report = check(WORLD)
    assert report.ok
    return report.world


class Clock:
    """A clock a test can move without sleeping."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def session(world):
    clock = Clock()
    engine = Engine(world, seed=7, clock=clock)
    talk = Session("test", engine, persistent=False, clock=clock)
    talk.clock_handle = clock
    return talk


def heard(session) -> list[Line]:
    seen: list[Line] = []
    session.listeners.append(seen.append)
    return seen


def register(session, player_id, name, choice="1"):
    session.say(player_id, "register")
    session.say(player_id, name)
    return session.say(player_id, choice)


# -------------------------------------------------------------- the adapter

def test_the_adapter_is_declared_and_needs_no_dependency():
    adapter = lyo_adapter()
    assert adapter.name == "webui"
    assert [s.key for s in adapter.settings][:3] == ["host", "port", "token"]
    assert adapter.setup, "it documents itself for the platforms page"


def test_the_adapter_is_discoverable_without_any_extra():
    from lyo.plugins import adapters

    assert "webui" in adapters()


def test_it_does_not_implement_the_present_hook():
    """That hook is firstresult; implementing it would restyle Discord too."""
    import lyo.adapters.webui as module

    assert not hasattr(module, "lyo_present")


# -------------------------------------------------------------- conversation

def test_a_command_runs_and_reports(session):
    register(session, "w1", "Brynn")
    reply = session.say("w1", "look")
    assert any("Oakhaven Village" in line.text for line in reply.lines)
    assert not reply.refused


def test_registration_runs_as_a_conversation(session):
    first = session.say("w1", "register")
    assert "What is your character's name?" in first.prompt

    second = session.say("w1", "Brynn")
    assert "1. Warrior" in second.prompt and "4. Paladin" in second.prompt

    done = session.say("w1", "2")
    assert done.prompt is None
    assert session.engine.sim.players["w1"].char_class == "Mage"


def test_an_unknown_command_says_so_without_raising(session):
    register(session, "w1", "Brynn")
    reply = session.say("w1", "flibbertigibbet")
    assert reply.unknown
    assert "No such command" in reply.lines[0].text


def test_empty_input_does_nothing(session):
    assert session.say("w1", "   ").lines == []


def test_public_lines_reach_other_browsers_and_private_ones_do_not(session):
    register(session, "w1", "Brynn")
    seen = heard(session)

    session.say("w1", "travel north")
    assert any("travels to Whispering Woods" in line.text for line in seen)

    seen.clear()
    session.say("w1", "inventory")
    assert seen == [], "a DM is nobody else's business"


def test_two_identities_can_duel_in_one_browser(session):
    register(session, "w1", "Brynn")
    register(session, "w2", "Selene", "2")

    assert not session.say("w1", "duel @w2").refused
    assert not session.say("w2", "accept").refused
    duel = session.engine.sim.duel_of("w1")
    assert duel is not None and duel.other("w1") == "w2"
    assert session.say("w2", "attack").refused, "not their turn"
    assert not session.say("w1", "attack").refused


# ------------------------------------------------------------------- timing

def test_an_abandoned_prompt_times_out_and_saves_nothing(session):
    clock = session.clock_handle
    session.say("w1", "register")
    session.say("w1", "Brynn")
    assert session.waiting_on("w1")

    clock.advance(121)
    fired = session.sweep()
    assert any("timed out" in line.text for line in fired)
    assert not session.waiting_on("w1")
    assert "w1" not in session.engine.sim.players


def test_a_prompt_inside_its_timeout_survives_a_sweep(session):
    session.say("w1", "register")
    session.clock_handle.advance(60)
    assert session.sweep() == []
    assert session.waiting_on("w1")


def test_a_lapsed_challenge_is_announced_to_everyone(session):
    register(session, "w1", "Brynn")
    register(session, "w2", "Selene", "2")
    session.say("w1", "duel @w2")
    seen = heard(session)

    session.clock_handle.advance(61)
    fired = session.sweep()
    assert any("expired" in line.text for line in fired)
    assert any("expired" in line.text for line in seen)
    assert session.engine.sim.offers == []


# ------------------------------------------------------- the two simulations

@pytest.fixture
def ui(world, tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        yield WebUI(Engine(world, seed=7, store=store), {}, str(WORLD))


def test_the_two_sessions_are_separate_worlds(ui):
    register(ui.pick("ephemeral"), "tmp", "Throwaway", "3")
    assert ui.pick("ephemeral").engine.sim.players
    assert ui.pick("persistent").engine.sim.players == {}


def test_only_the_persistent_session_has_a_store(ui):
    assert ui.pick("persistent").engine.store is not None
    assert ui.pick("ephemeral").engine.store is None


def test_the_ephemeral_session_writes_nothing(ui, tmp_path):
    register(ui.pick("ephemeral"), "tmp", "Throwaway")
    store = ui.pick("persistent").engine.store
    assert store.characters() == 0


def test_the_persistent_session_saves(ui):
    register(ui.pick("persistent"), "w1", "Brynn")
    assert ui.pick("persistent").engine.store.characters() == 1


def test_resetting_replaces_only_the_ephemeral_simulation(ui):
    register(ui.pick("persistent"), "w1", "Brynn")
    register(ui.pick("ephemeral"), "tmp", "Throwaway")

    assert ui.reset("ephemeral")
    assert ui.pick("ephemeral").engine.sim.players == {}
    assert "w1" in ui.pick("persistent").engine.sim.players

    assert ui.reset("persistent") is False, "the real one is not resettable"
    assert ui.reset("nonsense") is False


def test_a_reset_session_keeps_broadcasting(ui):
    ui.reset("ephemeral")
    seen = heard(ui.pick("ephemeral"))
    register(ui.pick("ephemeral"), "tmp", "Throwaway")
    ui.pick("ephemeral").say("tmp", "look")
    assert seen, "the new session's listener was reattached"


# ---------------------------------------------------------------- the server

def test_a_request_is_parsed(tmp_path):
    from lyo.adapters.webui.http import read_request

    async def go():
        reader = asyncio.StreamReader()
        body = b'{"text":"look"}'
        reader.feed_data(
            b"POST /api/say?session=x HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        reader.feed_eof()
        return await read_request(reader)

    request = asyncio.run(go())
    assert request.method == "POST" and request.path == "/api/say"
    assert request.one("session") == "x"
    assert request.json() == {"text": "look"}


def test_a_response_renders_with_its_length():
    response = Response.of_json({"ok": True})
    raw = render(response)
    assert raw.startswith(b"HTTP/1.1 200 OK\r\n")
    assert f"Content-Length: {len(response.body)}\r\n".encode() in raw
    head, _, body = raw.partition(b"\r\n\r\n")
    assert json.loads(body) == {"ok": True}
    assert b"Connection: close" in head


def test_static_files_are_served_and_traversal_refused():
    static = Static()
    assert static.read("/")is not None, "index by default"
    assert static.read("app.js") is not None
    assert static.read("../../../etc/passwd") is None
    assert static.read("nope.js") is None


def test_a_token_is_only_required_when_one_is_set():
    plain = Server("127.0.0.1", 0)
    assert plain.permitted(Request("GET", "/", {}, {}))

    guarded = Server("0.0.0.0", 0, token="sesame")
    assert not guarded.permitted(Request("GET", "/", {}, {}))
    assert guarded.permitted(Request("GET", "/", {"token": ["sesame"]}, {}))
    assert guarded.permitted(
        Request("GET", "/", {}, {"x-lyo-token": "sesame"}))
    assert not guarded.loopback


def test_the_printed_url_carries_the_token():
    assert Server("127.0.0.1", 8720).url() == "http://localhost:8720/"
    assert "token=sesame" in Server("10.0.0.5", 8720, token="sesame").url()


# -------------------------------------------------------------- end to end

def test_the_whole_surface_over_a_real_socket(world, tmp_path):
    """Bind a port, play a turn over HTTP, and watch it arrive on the stream."""
    import urllib.request

    with Store(tmp_path / "lyo.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store), {}, str(WORLD))
        server = Server("127.0.0.1", 0)
        ui.attach(server)

        async def scenario():
            port = await server.listen()
            serving = asyncio.create_task(server.serve())
            base = f"http://127.0.0.1:{port}"

            def get(path):
                with urllib.request.urlopen(base + path, timeout=5) as r:
                    return r.status, r.read()

            def post(path, payload):
                request = urllib.request.Request(
                    base + path, method="POST",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=5) as r:
                    return json.loads(r.read())

            loop = asyncio.get_running_loop()

            status, page = await loop.run_in_executor(None, get, "/")
            assert status == 200 and b"<title>lyo</title>" in page

            status, script = await loop.run_in_executor(None, get, "/app.js")
            assert status == 200 and b"quikchat" in script

            _, raw = await loop.run_in_executor(None, get, "/api/state")
            assert json.loads(raw)["title"] == "Kairos"

            #  Open the event stream, then act, and see the line arrive.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET /api/events?session=persistent HTTP/1.1\r\n"
                         b"Host: localhost\r\n\r\n")
            await writer.drain()
            await reader.readuntil(b"\r\n\r\n")
            assert b"hello" in await asyncio.wait_for(reader.read(200), 5)

            for text in ("register", "Brynn", "1"):
                reply = await loop.run_in_executor(
                    None, post, "/api/say",
                    {"session": "persistent", "player": "w1", "text": text})
            assert reply["prompt"] is None
            assert [p["name"] for p in reply["players"]] == ["Brynn"]

            await loop.run_in_executor(
                None, post, "/api/say",
                {"session": "persistent", "player": "w1", "text": "travel north"})
            pushed = await asyncio.wait_for(reader.read(400), 5)
            assert b"travels to Whispering Woods" in pushed

            #  A turn with no player named is a bad request, not a crash.
            try:
                await loop.run_in_executor(
                    None, post, "/api/say", {"text": "look"})
                raise AssertionError("should have refused")
            except urllib.error.HTTPError as error:
                assert error.code == 400

            writer.close()
            serving.cancel()

        asyncio.run(scenario())
        assert store.characters() == 1, "the persistent session saved"


def test_a_busy_port_is_a_sentence_not_a_stack_trace(world):
    """Hitting a taken port is ordinary; it should read like a message."""
    import errno
    import socket

    from lyo.adapters.webui.http import Unavailable

    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    port = held.getsockname()[1]
    try:
        async def go():
            await Server("127.0.0.1", port).listen()

        with pytest.raises(Unavailable) as caught:
            asyncio.run(go())
    finally:
        held.close()

    message = str(caught.value)
    assert "already listening" in message
    assert f"webui.port={port + 1}" in message, "it suggests a way out"
    assert caught.value.cause.errno == errno.EADDRINUSE


def test_an_address_not_on_this_machine_is_explained():
    """asyncio loses the errno here, so the message must still be useful."""
    from lyo.adapters.webui.http import Unavailable

    with pytest.raises(Unavailable) as caught:
        asyncio.run(Server("203.0.113.1", 9999).listen())

    message = str(caught.value)
    assert "adapter.webui.host" in message
    assert "no interface" in message
    assert "out of [(" not in message, "asyncio's candidate list is noise"


def test_a_privileged_port_is_explained():
    from lyo.adapters.webui.http import Unavailable

    with pytest.raises(Unavailable, match="privileges"):
        asyncio.run(Server("127.0.0.1", 80).listen())
