"""Stopping cleanly, from whichever task owns the event loop.

This belongs to the host -- the adapter whose `run` created the loop -- and
not to anything it hosts. A service that installs its own SIGINT handler both
replaces asyncio's, which would otherwise cancel the main task, and cancels
only itself, leaving its siblings running with nothing left to interrupt them.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

#  SIGINT is Ctrl-C; SIGTERM is what a service manager sends.
STOPPING = ("SIGINT", "SIGTERM")


def stop_on_signals(task: asyncio.Task | None = None) -> None:
    """Make a stop signal cancel `task`, defaulting to the current one.

    Cancelling the task that owns a TaskGroup unwinds every child through its
    own `finally`, so sockets are removed and state is saved on the way out.

    Windows has no `add_signal_handler`; there the default handling asyncio
    installs is left in place, which already cancels the main task.
    """
    task = task or asyncio.current_task()
    if task is None:  # pragma: no cover - only outside a running loop
        return
    loop = asyncio.get_running_loop()
    for name in STOPPING:
        number = getattr(signal, name, None)
        if number is None:
            continue
        with contextlib.suppress(NotImplementedError, AttributeError,
                                 ValueError, RuntimeError):
            loop.add_signal_handler(number, task.cancel)
