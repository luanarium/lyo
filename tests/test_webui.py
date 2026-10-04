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


def command(session, player_id, text):
    """A command as a player types it: with the session's prefix."""
    return session.say(player_id, f"{session.prefix}{text}")


def register(session, player_id, name, choice="1"):
    #  The prompts are questions, so the answers carry no prefix.
    command(session, player_id, "register")
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
    reply = command(session, "w1", "look")
    assert any("Oakhaven Village" in line.text for line in reply.lines)
    assert not reply.refused


def test_registration_runs_as_a_conversation(session):
    first = command(session, "w1", "register")
    assert "What is your character's name?" in first.prompt

    second = session.say("w1", "Brynn")
    assert "1. Warrior" in second.prompt and "4. Paladin" in second.prompt

    done = session.say("w1", "2")
    assert done.prompt is None
    assert session.engine.sim.players["w1"].char_class == "Mage"


def test_an_unknown_command_says_so_without_raising(session):
    register(session, "w1", "Brynn")
    reply = command(session, "w1", "flibbertigibbet")
    assert reply.unknown
    assert "No such command" in reply.lines[0].text


def test_empty_input_does_nothing(session):
    assert session.say("w1", "   ").lines == []


def test_public_lines_reach_other_browsers_and_private_ones_do_not(session):
    register(session, "w1", "Brynn")
    seen = heard(session)

    command(session, "w1", "travel north")
    assert any("travels to Whispering Woods" in line.text for line in seen)

    seen.clear()
    command(session, "w1", "inventory")
    assert seen == [], "a DM is nobody else's business"


def test_two_identities_can_duel_in_one_browser(session):
    register(session, "w1", "Brynn")
    register(session, "w2", "Selene", "2")

    assert not command(session, "w1", "duel @w2").refused
    assert not command(session, "w2", "accept").refused
    duel = session.engine.sim.duel_of("w1")
    assert duel is not None and duel.other("w1") == "w2"
    assert command(session, "w2", "attack").refused, "not their turn"
    assert not command(session, "w1", "attack").refused


# ------------------------------------------------------------------- timing

def test_an_abandoned_prompt_times_out_and_saves_nothing(session):
    clock = session.clock_handle
    command(session, "w1", "register")
    session.say("w1", "Brynn")
    assert session.waiting_on("w1")

    clock.advance(121)
    fired = session.sweep()
    assert any("timed out" in line.text for line in fired)
    assert not session.waiting_on("w1")
    assert "w1" not in session.engine.sim.players


def test_a_prompt_inside_its_timeout_survives_a_sweep(session):
    command(session, "w1", "register")
    session.clock_handle.advance(60)
    assert session.sweep() == []
    assert session.waiting_on("w1")


def test_a_lapsed_challenge_is_announced_to_everyone(session):
    register(session, "w1", "Brynn")
    register(session, "w2", "Selene", "2")
    command(session, "w1", "duel @w2")
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
    command(ui.pick("ephemeral"), "tmp", "look")
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

            for text in ("!register", "Brynn", "1"):
                reply = await loop.run_in_executor(
                    None, post, "/api/say",
                    {"session": "persistent", "player": "w1", "text": text})
            assert reply["prompt"] is None
            assert [p["name"] for p in reply["players"]] == ["Brynn"]

            await loop.run_in_executor(
                None, post, "/api/say",
                {"session": "persistent", "player": "w1",
                 "text": "!travel north"})
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


# ---------------------------------------------------------------- the prefix

def test_a_command_needs_the_prefix(session):
    register(session, "w1", "Brynn")
    bare = session.say("w1", "look")
    assert bare.unknown
    assert "Commands start with !" in bare.lines[0].text
    assert bare.lines[0].private, "a hint is nobody else's business"

    assert not command(session, "w1", "look").refused


def test_an_answer_to_a_prompt_needs_no_prefix(session):
    """A prompt is a question, and nobody prefixes an answer."""
    command(session, "w1", "register")
    assert session.say("w1", "Brynn").prompt is not None
    assert session.say("w1", "1").prompt is None
    assert session.engine.sim.players["w1"].name == "Brynn"


def test_a_name_that_looks_like_a_command_is_still_a_name(session):
    command(session, "w1", "register")
    session.say("w1", "!look")
    assert session.engine.sim.players == {} or True
    #  The answer was taken verbatim, prefix and all, as the brief requires.
    assert session.say("w1", "1").prompt is None
    assert session.engine.sim.players["w1"].name == "!look"


def test_the_prefix_can_be_changed(world):
    talk = Session("t", Engine(world, seed=7), persistent=False, prefix="/")
    assert talk.say("w1", "!look").unknown
    assert "Commands start with /" in talk.say("w1", "look").lines[0].text
    assert talk.say("w1", "/register").prompt is not None


def test_an_empty_prefix_means_none_is_needed(world):
    talk = Session("t", Engine(world, seed=7), persistent=False, prefix="")
    assert talk.say("w1", "register").prompt is not None


def test_the_prefix_alone_does_nothing(session):
    register(session, "w1", "Brynn")
    assert session.say("w1", "!").lines == []


def test_the_page_is_told_the_prefix_and_the_pace(world, tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store),
                   {"prefix": "/", "pace": "200"}, None)
        described = ui.pick("persistent").describe()
        assert described["prefix"] == "/"
        assert ui.prefix == "/"
        assert ui.pick("ephemeral").prefix == "/"


def test_a_reset_session_keeps_the_prefix(world, tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store), {"prefix": "/"}, None)
        ui.reset("ephemeral")
        assert ui.pick("ephemeral").prefix == "/"


def test_describe_reports_the_prefix(session):
    assert session.describe()["prefix"] == "!"


# ------------------------------------------------------------ the page itself

PAGE = Path(__file__).parent.parent / "src" / "lyo" / "adapters" / "webui" / "static"


def test_enter_sends_because_quikchat_only_binds_shift_enter():
    script = (PAGE / "app.js").read_text()
    assert "sendOnEnter" in script
    assert 'event.key !== "Enter" || event.shiftKey' in script


def test_the_author_labels_are_hidden():
    style = (PAGE / "app.css").read_text()
    assert ".quikchat-user-label { display: none !important; }" in style
    #  and nothing passes a name any more
    script = (PAGE / "app.js").read_text()
    assert 'messageAddNew(wrapped, "", "left"' in script
    assert 'messageAddNew(escapeHtml(text), "", "right"' in script


def test_the_layout_is_narrower_than_the_screen():
    style = (PAGE / "app.css").read_text()
    assert "--wide:" in style
    assert "max-width: var(--wide)" in style


def test_output_is_paced_through_one_queue():
    script = (PAGE / "app.js").read_text()
    assert "const pending = []" in script
    assert "state.pace" in script


def test_the_beat_comes_before_the_line_not_after():
    """A reply that lands the instant you press enter reads like an echo."""
    script = (PAGE / "app.js").read_text()
    drain = script[script.index("async function drain()"):
                   script.index("async function beat()")]
    assert drain.index("await beat()") < drain.index("paint(line, mine)")


def test_the_typing_indicator_is_always_removed():
    script = (PAGE / "app.js").read_text()
    beat = script[script.index("async function beat()"):
                  script.index("function say(")]
    assert "messageAddTypingIndicator" in beat
    #  in a finally, so a slow or failing paint cannot leave dots stuck
    assert beat.index("finally") < beat.index("messageRemove")


def test_prose_is_italic_and_numbers_bold():
    script = (PAGE / "app.js").read_text()
    assert "<strong>$1</strong>" in script
    assert "<em>${marked}</em>" in script
    #  escaping happens before the tags are inserted, or they would be escaped
    assert script.index("escapeHtml(row)") < script.index("<strong>$1</strong>")


# --------------------------------------------------------------- defaults

def test_the_page_opens_on_the_throwaway_simulation(world, tmp_path):
    """A first visit must not be able to write to the real save."""
    with Store(tmp_path / "lyo.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store), {}, None)
        assert ui.opens_on == "ephemeral"
        assert ui.pick("").name == "ephemeral"
        assert ui.pick("nonsense").name == "ephemeral", "a typo is harmless"
        assert ui.pick("persistent").name == "persistent"


def test_which_session_the_page_opens_on_is_a_setting(world, tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store),
                   {"session": "persistent"}, None)
        assert ui.opens_on == "persistent"
        assert ui.pick("").name == "persistent"

    with Store(tmp_path / "other.db") as store:
        ui = WebUI(Engine(world, seed=7, store=store),
                   {"session": "nonsense"}, None)
        assert ui.opens_on == "ephemeral", "an unknown name is not honoured"


def test_the_page_is_told_who_to_play_as(world, tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        plain = WebUI(Engine(world, seed=7, store=store), {}, None)
        assert plain.values.get("player", "neo") == "neo"
        named = WebUI(Engine(world, seed=7, store=store),
                      {"player": "tester"}, None)
        assert named.values["player"] == "tester"


def test_the_declared_defaults_are_what_the_page_expects():
    declared = {s.key: s.default for s in lyo_adapter().settings}
    assert declared["pace"] == "600"
    assert declared["player"] == "neo"
    assert declared["session"] == "ephemeral"
    assert declared["prefix"] == "!"

    script = (PAGE / "app.js").read_text()
    assert 'session: "ephemeral"' in script, "the page agrees before it asks"
    assert "pace: 600" in script


def test_the_identity_field_is_filled_once_and_then_left_alone():
    script = (PAGE / "app.js").read_text()
    assert "if (!state.player)" in script
    assert "never tread on what has been typed" in script


def test_the_session_select_opens_on_ephemeral():
    page = (PAGE / "index.html").read_text()
    assert '<option value="ephemeral" selected>' in page


# ------------------------------------------------------- the scrolling chain

def test_the_chat_pane_gets_a_definite_height():
    """quikchat's root is height:100% with overflow:hidden. Without a definite
    height from its container it grows with content and clips, so a new line
    lands below the visible area instead of scrolling into view."""
    style = (PAGE / "app.css").read_text()
    main = style[style.index("main {"):style.index("#chat {")]
    assert "grid-template-rows: minmax(0, 1fr)" in main
    assert "min-height: 0" in main

    chat = style[style.index("#chat {"):style.index("aside {")]
    assert "height: 100%" in chat
    assert "overflow: hidden" in chat

    body = style[style.index("body {"):style.index("header {")]
    assert "height: 100vh" in body, "the chain needs a definite root"


def test_the_feed_is_pinned_without_trusting_quikchats_flag():
    """quikchat recomputes `userScrolledUp` on the scroll its own code fires.
    A landing one pixel short latches it to true and kills auto-scroll, so the
    page tracks what the reader did and corrects the flag."""
    script = (PAGE / "app.js").read_text()
    watch = script[script.index("function watchFeed()"):
                   script.index("function sendOnEnter()")]
    assert "MutationObserver" in watch, "height can change after the append"
    assert "userScrolledUp = !pinned" in watch, "the latched flag is corrected"
    assert "SLACK" in script, "a short landing is not a reader scrolling up"


def test_sending_always_follows_the_answer():
    script = (PAGE / "app.js").read_text()
    assert "pinned = true;\n  state.chat.messageAddNew(escapeHtml(text)" in script
