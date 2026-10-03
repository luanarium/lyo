"""The bot-API boundary: pluggy hook specifications and adapter discovery.

An adapter is an ordinary Python package that implements `lyo_adapter` and
advertises itself under the `lyo` entry-point group. The engine never
imports one, so the core stays free of any bot library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pluggy

HOOK = "lyo"
hookspec = pluggy.HookspecMarker(HOOK)
hookimpl = pluggy.HookimplMarker(HOOK)


@dataclass(frozen=True)
class Setting:
    """One piece of configuration an adapter needs, in UCI terms."""

    key: str
    help: str
    required: bool = False
    secret: bool = False
    default: str | None = None


@dataclass(frozen=True)
class Adapter:
    """What an adapter tells the host about itself."""

    name: str
    summary: str
    run: Callable[..., Any]
    settings: tuple[Setting, ...] = ()
    setup: str = ""
    """Markdown describing what the platform needs before this will work.

    The engine knows nothing about gateway intents or OAuth scopes, so an
    adapter states its own prerequisites here and the documentation and
    `lyo adapters --setup` render them.
    """


class Specs:
    """The hooks an adapter may implement."""

    @hookspec
    def lyo_adapter(self) -> Adapter | None:
        """Return this plugin's adapter, or None if it provides none."""

    @hookspec(firstresult=True)
    def lyo_present(self, text: str, kind: str | None, private: bool) -> str | None:
        """Restyle one outgoing message. The first plugin to answer wins."""


def manager() -> pluggy.PluginManager:
    """A plugin manager with the built-in adapters and any installed ones."""
    pm = pluggy.PluginManager(HOOK)
    pm.add_hookspecs(Specs)
    pm.load_setuptools_entrypoints(HOOK)

    #  Register the first-party adapter if its dependency is installed.
    try:
        from lyo.adapters import discord as discord_adapter
    except ImportError:  # pragma: no cover - only without the extra
        discord_adapter = None
    if discord_adapter is not None and not pm.is_registered(discord_adapter):
        pm.register(discord_adapter, name="lyo.adapters.discord")
    return pm


def adapters(pm: pluggy.PluginManager | None = None) -> dict[str, Adapter]:
    pm = pm or manager()
    found: dict[str, Adapter] = {}
    for adapter in pm.hook.lyo_adapter():
        if adapter is not None:
            found[adapter.name] = adapter
    return found


def present(pm: pluggy.PluginManager, text: str, kind: str | None,
            private: bool) -> str:
    styled = pm.hook.lyo_present(text=text, kind=kind, private=private)
    return styled if isinstance(styled, str) else text
