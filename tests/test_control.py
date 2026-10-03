"""The control channel: a running instance, reachable from the CLI."""

import asyncio
import json
from pathlib import Path

import pytest

from lyo import control
from lyo.control import ControlError, Service, socket_path
from lyo.engine import Engine
from lyo.lang.check import check
from lyo.store import Store

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


@pytest.fixture(scope="module")
def world():
    report = check(WORLD)
    assert report.ok
    return report.world


@pytest.fixture
def service(world, tmp_path):
    store = Store(tmp_path / "lyo.db")
    engine = Engine(world, seed=7, store=store)
    yield Service(engine=engine, store=store, source=WORLD, adapter="discord",
                  settings={"prefix": "!"})
    store.close()


# ------------------------------------------------------------------ paths

def test_the_socket_sits_beside_the_state_file():
    assert socket_path(Path("/var/lib/lyo.db")) == Path("/var/lib/lyo.sock")


# ---------------------------------------------------------------- service

def test_status_reports_the_live_world(service):
    service.engine.register("u1", "Brynn", "Warrior")
    reported = service.status()
    assert reported["ok"] and reported["world"] == "Kairos"
    assert reported["characters"] == 1
    assert reported["locations"] == 6
    assert reported["source"].endswith("kairos.md")


def test_reload_applies_a_good_world_and_keeps_players(service):
    service.engine.register("u1", "Brynn", "Warrior")
    reply = service.reload()
    assert reply["ok"] and reply["reloaded"] == "Kairos"
    assert "u1" in service.engine.sim.players


def test_reload_refuses_a_broken_world_and_keeps_serving(service, tmp_path):
    broken = tmp_path / "broken.md"
    broken.write_text(
        WORLD.read_text().replace('spawns "Goblin Scout"', 'spawns "Goblin Scowt"'))
    service.source = broken
    before = service.engine.world

    reply = service.reload()
    assert reply["ok"] is False
    assert "does not resolve" in reply["error"]
    assert any("did you mean" in line for line in reply["diagnostics"])
    assert service.engine.world is before, "the old world is still serving"


def test_reload_picks_up_committed_adapter_settings(service):
    service.store.config.set("adapter.discord.prefix", "?")
    service.store.config.commit()
    assert service.settings["prefix"] == "!", "not yet"

    service.reload()
    assert service.settings["prefix"] == "?", "a live view, so no restart needed"


# --------------------------------------------------------------- dispatch

def test_ping_status_and_reload_are_answered(service):
    for operation in ("ping", "status", "reload"):
        reply = control._dispatch(service, None, json.dumps({"op": operation}).encode())
        assert reply["ok"], operation


def test_an_unknown_operation_is_refused(service):
    reply = control._dispatch(service, None, b'{"op": "destroy"}')
    assert reply["ok"] is False and "no such operation" in reply["error"]


def test_an_empty_request_is_refused(service):
    assert control._dispatch(service, None, b"  \n")["ok"] is False


def test_a_token_is_required_when_one_is_set(service):
    assert control._dispatch(service, "secret", b'{"op": "ping"}')["ok"] is False
    good = control._dispatch(service, "secret",
                             b'{"op": "ping", "token": "secret"}')
    assert good["ok"]


# ----------------------------------------------------------- round trip

@pytest.mark.skipif(not control.UNIX_AVAILABLE, reason="needs AF_UNIX")
def test_a_request_reaches_a_live_server(service, tmp_path):
    db = tmp_path / "lyo.db"

    async def scenario():
        server = asyncio.create_task(control.serve(service, db=db))
        await asyncio.sleep(0.2)
        try:
            #  The client is blocking, so it runs off the event loop.
            return await asyncio.to_thread(control.request, "status", db=db)
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)

    reply = asyncio.run(scenario())
    assert reply["ok"] and reply["world"] == "Kairos"
    assert not socket_path(db).exists(), "the socket is cleaned up on shutdown"


@pytest.mark.skipif(not control.UNIX_AVAILABLE, reason="needs AF_UNIX")
def test_listening_is_false_with_nothing_there(tmp_path):
    assert control.listening(tmp_path / "lyo.db") is False


def test_requesting_with_nothing_listening_explains_itself(tmp_path):
    with pytest.raises(ControlError, match="no running instance"):
        control.request("status", db=tmp_path / "lyo.db")


@pytest.mark.skipif(not control.UNIX_AVAILABLE, reason="needs AF_UNIX")
def test_a_stale_socket_is_reported_as_not_running(tmp_path):
    import socket as socket_module

    db = tmp_path / "lyo.db"
    stale = socket_module.socket(socket_module.AF_UNIX)
    stale.bind(str(socket_path(db)))
    stale.close()

    with pytest.raises(ControlError, match="stale socket"):
        control.request("status", db=db)


# --------------------------------------------------------------- binding

def test_binding_beyond_loopback_needs_a_token(service, tmp_path):
    """The convention allows widening; an admin channel still needs auth."""
    with pytest.raises(ControlError, match="without control.main.token"):
        asyncio.run(control.serve(service, db=tmp_path / "lyo.db",
                                  host="0.0.0.0"))


def test_a_loopback_tcp_port_is_recorded_for_the_client(service, tmp_path):
    db = tmp_path / "lyo.db"

    async def scenario():
        server = asyncio.create_task(
            control.serve(service, db=db, host="127.0.0.1"))
        await asyncio.sleep(0.2)
        row = service.store.db.execute(
            "SELECT value FROM meta WHERE key = 'control_port'").fetchone()
        port = int(row["value"])
        try:
            return port, await asyncio.to_thread(
                control.request, "ping", db=db, host="127.0.0.1", port=port)
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)

    port, reply = asyncio.run(scenario())
    assert port > 0 and reply["ok"]
