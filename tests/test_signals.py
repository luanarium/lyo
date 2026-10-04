"""Stopping cleanly: Ctrl-C, SIGTERM, and who owns them."""

import asyncio
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from lyo.control import socket_path
from lyo.signals import stop_on_signals
from lyo.store import Store

ROOT = Path(__file__).parent.parent
WORLD = ROOT / "world" / "kairos.md"


def test_a_stop_signal_cancels_the_task_that_owns_the_loop():
    """The point of the helper: one signal, the whole group unwinds."""
    finished: list[str] = []

    async def child(name: str) -> None:
        try:
            await asyncio.sleep(30)
        finally:
            finished.append(name)

    async def main() -> None:
        stop_on_signals()
        asyncio.get_running_loop().call_later(
            0.05, signal.raise_signal, signal.SIGINT)
        async with asyncio.TaskGroup() as group:
            group.create_task(child("server"))
            group.create_task(child("sweeper"))

    with pytest.raises((asyncio.CancelledError, KeyboardInterrupt)):
        asyncio.run(main())
    assert sorted(finished) == ["server", "sweeper"], (
        "every sibling unwound, not just the one that handled the signal")


def test_the_control_channel_no_longer_claims_the_stop_signals():
    """It used to cancel only itself, which left its siblings running."""
    source = (ROOT / "src" / "lyo" / "control.py").read_text()
    assert "add_signal_handler(number, task.cancel)" not in source
    assert "SIGHUP" in source, "reload-on-hangup is still its business"


def test_stop_on_signals_outside_a_loop_is_harmless():
    async def main() -> None:
        stop_on_signals()

    asyncio.run(main())  # no task group, nothing to cancel, no error


# --------------------------------------------------------- the real process

def _serve(tmp_path, port):
    db = tmp_path / "lyo.db"
    log = open(tmp_path / "out.log", "w+")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "lyo"), "run", "-a", "webui",
         "-s", f"webui.port={port}", "--db", str(db)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(100):
        time.sleep(0.05)
        if "serving" in (tmp_path / "out.log").read_text():
            return proc, db
    proc.kill()
    pytest.skip(f"server did not start: {(tmp_path / 'out.log').read_text()}")


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_the_server_stops_on_a_signal(tmp_path, sig):
    proc, _ = _serve(tmp_path, _free_port())
    proc.send_signal(sig)
    try:
        assert proc.wait(timeout=15) == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(f"{sig.name} did not stop the server")
    assert "stopped" in (tmp_path / "out.log").read_text()


def test_stopping_removes_the_control_socket(tmp_path):
    """Why the control channel wanted the signal in the first place."""
    proc, db = _serve(tmp_path, _free_port())
    sock = socket_path(db)
    assert sock.exists(), "the control channel is listening"

    proc.send_signal(signal.SIGINT)
    assert proc.wait(timeout=15) == 0
    assert not sock.exists(), "its finally ran as the group unwound"

    with Store(db) as store:
        assert store.db.execute(
            "SELECT 1 FROM meta WHERE key = 'control_port'").fetchone() is None


def test_an_open_event_stream_does_not_block_shutdown(tmp_path):
    port = _free_port()
    proc, _ = _serve(tmp_path, port)
    stream = socket.create_connection(("127.0.0.1", port), timeout=5)
    stream.sendall(b"GET /api/events?session=persistent HTTP/1.1\r\n"
                   b"Host: localhost\r\n\r\n")
    time.sleep(0.5)
    try:
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=15) == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("a connected browser held shutdown open")
    finally:
        stream.close()
