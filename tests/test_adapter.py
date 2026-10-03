"""The discord adapter's routing, driven against a stand-in for discord.py."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lyo.adapters.discord import Bot, Settings, lyo_adapter, lyo_present
from lyo.engine import Engine
from lyo.lang.check import check
from lyo.plugins import adapters, manager

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


# ------------------------------------------------------- a stand-in discord

class Forbidden(Exception):
    """What discord raises when a user's DMs are closed."""


@dataclass
class FakeDiscord:
    Forbidden = Forbidden


@dataclass
class Channel:
    name: str = "channel"
    sent: list[tuple[str, float | None]] = field(default_factory=list)

    async def send(self, text, delete_after=None):
        self.sent.append((text, delete_after))
        return object()

    @property
    def texts(self):
        return [t for t, _ in self.sent]


@dataclass
class User:
    id: int = 1
    dms_open: bool = True
    dm_channel: Channel | None = None
    bot: bool = False

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def create_dm(self):
        if not self.dms_open:
            raise Forbidden("closed")
        self.dm_channel = self.dm_channel or Channel("dm")
        return self.dm_channel


@dataclass
class Msg:
    author: User
    channel: Channel
    content: str
    guild: object | None = "guild"
    mentions: list = field(default_factory=list)


class Client:
    """Serves scripted DM replies to wait_for."""

    def __init__(self, replies=()):
        self.replies = list(replies)

    async def wait_for(self, event, check=None, timeout=None):
        if not self.replies:
            raise asyncio.TimeoutError
        text = self.replies.pop(0)
        if text is TIMEOUT:
            raise asyncio.TimeoutError
        return Msg(author=User(1), channel=Channel("dm"), content=text, guild=None)


TIMEOUT = object()


@pytest.fixture(scope="module")
def world():
    report = check(WORLD)
    assert report.ok
    return report.world


def make(world, replies=(), owner=None, dms_open=True, clock=None):
    engine = Engine(world, seed=7, clock=clock)
    client = Client(replies)
    settings = Settings(token="x", prefix="!", owner=owner, notice_seconds=3)
    bot = Bot(engine, client, settings, FakeDiscord(), str(WORLD))
    user = User(1, dms_open=dms_open)
    channel = Channel()
    return engine, bot, user, channel


def say(bot, user, channel, text, guild="guild", mentions=()):
    message = Msg(author=user, channel=channel, content=text,
                  guild=guild, mentions=list(mentions))
    asyncio.run(bot.handle(message))
    return message


# ------------------------------------------------------------- the plugin

def test_the_adapter_is_discoverable_as_a_plugin():
    assert "discord" in adapters(manager())


def test_the_adapter_declares_its_settings_in_uci_shape():
    keys = [s.key for s in lyo_adapter().settings]
    assert keys == ["token", "prefix", "owner", "notice_seconds"]
    assert lyo_adapter().settings[0].required


def test_presentation_bolds_numbers_and_badges_a_view():
    assert lyo_present("hits for 8", None, False) == "hits for **8**"
    styled = lyo_present("Carrying nothing.", "inventory", True)
    assert styled.startswith("\U0001f392")


# ------------------------------------------------------------- routing

def test_public_output_goes_to_the_channel(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!look")
    assert any("Oakhaven Village" in t for t in channel.texts)
    assert user.dm_channel is None


def test_private_output_is_dmed_with_a_self_deleting_notice(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!inventory")

    assert user.dm_channel is not None
    assert any("Brynn the Warrior" in t for t in user.dm_channel.texts)
    notice = [(t, d) for t, d in channel.sent if "check your DMs" in t]
    assert notice and notice[0][1] == 3, "the note deletes itself"


def test_closed_dms_fall_back_to_the_channel(world):
    engine, bot, user, channel = make(world, dms_open=False)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!inventory")
    assert any("Brynn the Warrior" in t for t in channel.texts)
    assert not any("check your DMs" in t for t in channel.texts)


def test_an_unknown_command_is_ignored(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!flibbertigibbet")
    assert channel.sent == []


def test_text_without_the_prefix_is_ignored(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "look")
    assert channel.sent == []


def test_a_mention_resolves_to_the_other_player(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    engine.register("2", "Selene", "Mage")
    other = User(2)
    say(bot, user, channel, "!duel <@2>", mentions=[other])
    assert any("challenges Selene" in t for t in channel.texts)


# ------------------------------------------------------------ conversations

def test_register_runs_as_a_dm_conversation(world):
    engine, bot, user, channel = make(world, replies=["Brynn", "1"])
    say(bot, user, channel, "!register")

    dm = user.dm_channel.texts
    assert any("What is your character's name?" in t for t in dm)
    assert any("Warrior" in t and "Mage" in t for t in dm), "a numbered menu"
    assert "1" in engine.sim.players
    assert engine.sim.players["1"].name == "Brynn"
    assert any("check your DMs" in t for t in channel.texts)


def test_register_accepts_a_class_by_name(world):
    engine, bot, user, channel = make(world, replies=["Nia", "rogue"])
    say(bot, user, channel, "!register")
    assert engine.sim.players["1"].char_class == "Rogue"


def test_a_timed_out_registration_saves_nothing_and_says_so_publicly(world):
    engine, bot, user, channel = make(world, replies=["Brynn", TIMEOUT])
    say(bot, user, channel, "!register")
    assert "1" not in engine.sim.players
    assert any("timed out" in t for t in channel.texts)


def test_closed_dms_point_at_the_single_shot_command(world):
    engine, bot, user, channel = make(world, dms_open=False)
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!shop")
    assert any("!buy <item>" in t for t in channel.texts)


def test_the_shop_conversation_buys_and_closes(world):
    engine, bot, user, channel = make(world, replies=["buckler", "done"])
    engine.register("1", "Brynn", "Warrior")
    engine.sim.players["1"].gold = 60
    say(bot, user, channel, "!shop")

    dm = user.dm_channel.texts
    assert any("For sale" in t for t in dm)
    assert any("Bought Chipped Buckler" in t for t in dm)
    assert engine.sim.players["1"].inventory.get("Chipped Buckler") == 1
    assert not engine.talking("1")


def test_a_dm_mid_conversation_is_not_read_as_a_command(world):
    engine, bot, user, channel = make(world)
    engine.register("1", "Brynn", "Warrior")
    bot._busy.add(user.id)
    dm = Channel("dm")
    asyncio.run(bot.handle(Msg(author=user, channel=dm, content="!look", guild=None)))
    assert dm.sent == []


# ------------------------------------------------------------------ owner

def test_reload_is_owner_only(world):
    engine, bot, user, channel = make(world, owner="999")
    say(bot, user, channel, "!reload")
    assert channel.sent == []


def test_reload_refuses_a_broken_source_and_shows_the_errors(world, tmp_path):
    broken = tmp_path / "broken.md"
    broken.write_text(
        WORLD.read_text().replace('spawns "Goblin Scout"', 'spawns "Goblin Scowt"'))
    engine, bot, user, channel = make(world, owner="1")
    bot.source = str(broken)
    say(bot, user, channel, "!reload")
    assert any("Refusing to reload" in t for t in channel.texts)
    assert any("Goblin Scout" in t for t in channel.texts), "suggests the fix"


def test_reload_keeps_players_and_reports_back_online(world):
    engine, bot, user, channel = make(world, owner="1")
    engine.register("1", "Brynn", "Warrior")
    engine.sim.players["1"].gold = 42
    say(bot, user, channel, "!reload")
    assert any("Back online" in t for t in channel.texts)
    assert engine.sim.players["1"].gold == 42


# ------------------------------------------------------- challenge expiry

def test_a_challenge_lapses_with_a_notice_in_the_channel(world):
    """The brief gives a challenge 60 seconds, and a notice when it passes."""
    ticks = [1000.0]
    engine, bot, user, channel = make(world, clock=lambda: ticks[0])
    engine.register("1", "Brynn", "Warrior")
    engine.register("2", "Selene", "Mage")

    async def scenario():
        await bot.handle(Msg(author=user, channel=channel,
                             content="!duel <@2>", mentions=[User(2)]))
        assert bot._waiting, "the adapter scheduled the lapse"
        assert len(engine.sim.offers) == 1
        ticks[0] += 61          # time passes
        await bot._lapse(channel, 0)

    asyncio.run(scenario())
    assert any("expired" in t for t in channel.texts)
    assert engine.sim.offers == []


def test_a_challenge_accepted_in_time_still_works(world):
    ticks = [1000.0]
    engine, bot, user, channel = make(world, clock=lambda: ticks[0])
    engine.register("1", "Brynn", "Warrior")
    engine.register("2", "Selene", "Mage")

    say(bot, user, channel, "!duel <@2>", mentions=[User(2)])
    ticks[0] += 59
    other, their_channel = User(2), Channel()
    say(bot, other, their_channel, "!accept")
    assert engine.sim.duel_of("1") is not None
