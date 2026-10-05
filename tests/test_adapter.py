"""The discord adapter's routing, driven against a stand-in for discord.py."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lyo.adapters.discord import (Bot, Settings, diagnose, lyo_adapter,
                                  lyo_present)
from lyo.engine import Engine
from lyo.lang.check import check
from lyo.plugins import adapters, manager

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


# ------------------------------------------------------- a stand-in discord

class Forbidden(Exception):
    """What discord raises when a user's DMs are closed."""


class LoginFailure(Exception):
    """What discord raises for a token it will not accept."""


class PrivilegedIntentsRequired(Exception):
    """What discord raises when the portal has not granted an intent."""


class Embed:
    """Enough of discord.Embed to see what the adapter laid out."""

    def __init__(self, title=None, description=None, colour=None):
        self.title, self.description, self.colour = title, description, colour
        self.fields: list[tuple[str, str, bool]] = []

    def add_field(self, name, value, inline=True):
        self.fields.append((name, value, inline))


@dataclass
class FakeDiscord:
    Forbidden = Forbidden
    LoginFailure = LoginFailure
    PrivilegedIntentsRequired = PrivilegedIntentsRequired


@dataclass
class RichDiscord(FakeDiscord):
    """A discord that has embeds, which the plain stand-in deliberately has not."""

    Embed = Embed


@dataclass
class Channel:
    name: str = "channel"
    sent: list[tuple[str, float | None]] = field(default_factory=list)
    embeds: list = field(default_factory=list)

    async def send(self, text=None, delete_after=None, embed=None):
        self.sent.append((text, delete_after))
        if embed is not None:
            self.embeds.append(embed)
        return object()

    @property
    def texts(self):
        return [t for t, _ in self.sent if t is not None]


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


def make(world, replies=(), owner=None, dms_open=True, clock=None,
         discord=None):
    engine = Engine(world, seed=7, clock=clock)
    client = Client(replies)
    settings = Settings.from_mapping(
        {"token": "x", "prefix": "!", "owner": owner or "",
         "notice_seconds": "3"})
    bot = Bot(engine, client, settings, discord or FakeDiscord(), str(WORLD))
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


def test_a_refused_token_is_explained_not_traced():
    #  discord.py raises from inside the TaskGroup, so it arrives in a group.
    group = ExceptionGroup("start", [LoginFailure("401 Unauthorized")])
    advice = diagnose(group, FakeDiscord())
    assert advice is not None
    assert "DISCORD_TOKEN" in advice and "Reset Token" in advice


def test_a_missing_intent_points_at_the_portal():
    advice = diagnose(PrivilegedIntentsRequired("shard 0"), FakeDiscord())
    assert advice is not None
    assert "Message Content Intent" in advice


def test_any_other_failure_is_left_alone():
    assert diagnose(RuntimeError("something else"), FakeDiscord()) is None


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
    assert any("Oakhaven Village Shop" in t for t in dm)
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


# ---------------------------------------------------------------- the layout

def shop(world, **kwargs):
    """Open the shop and hand back whatever reached the DM channel."""
    engine, bot, user, channel = make(world, replies=["done"], **kwargs)
    engine.register("1", "Brynn", "Warrior")
    engine.sim.players["1"].gold = 60
    say(bot, user, channel, "!shop")
    return engine, user.dm_channel


def test_a_shop_becomes_an_embed_titled_after_itself(world):
    _, dm = shop(world, discord=RichDiscord())
    assert len(dm.embeds) == 1, "the shelf is one embed, not twelve messages"
    embed = dm.embeds[0]
    assert embed.title == "🏪 Oakhaven Village Shop", "the badge is the adapter's"
    assert "Your Gold: **60**" in embed.description
    assert "🪙" in embed.description, "a glyph for a line the engine wrote"
    assert embed.colour == 0xE67E22


def test_every_stocked_item_is_one_field_in_shelf_order(world):
    _, dm = shop(world, discord=RichDiscord())
    fields = dm.embeds[0].fields
    assert len(fields) == 12
    #  A price glued to its `g` is left alone by the number-bolding rule,
    #  which is how the Kairos bot wrote this line too.
    assert [name for name, _, _ in fields][:3] == [
        "⚔️ Notched Iron Shortsword — 25g",
        "🏹 Splintered Oak Bow — 30g",
        "🪄 Apprentice's Ash Staff — 35g",
    ]
    assert all(inline is False for _, _, inline in fields)


def test_a_field_carries_the_type_stats_price_and_flavour(world):
    _, dm = shop(world, discord=RichDiscord())
    detail = dict((n, v) for n, v, _ in dm.embeds[0].fields)
    sword = detail["⚔️ Notched Iron Shortsword — 25g"]
    assert sword.splitlines() == [
        "⚔️ NOTCHED IRON SHORTSWORD",
        "Type: Main Hand",
        "Stats: +**3** DAMAGE | +**5**% CRIT CHANCE",
        "Price: **25** Gold",
        '"Dull near the hilt, but the edge is sharp enough to take down '
        'cellar rats."',
    ]


def test_a_negative_stat_keeps_its_own_sign(world):
    _, dm = shop(world, discord=RichDiscord())
    detail = " ".join(v for _, v, _ in dm.embeds[0].fields)
    assert "-**1** DEF" in detail, "the bow trades defence for reach"
    assert "+-" not in detail


def test_without_embeds_the_shelf_still_arrives_as_text(world):
    #  The plain stand-in has no Embed, standing in for any adapter that
    #  cannot lay one out. Nothing may be lost.
    _, dm = shop(world)
    assert dm.embeds == []
    shelf = "\n".join(dm.texts)
    assert "Oakhaven Village Shop" in shelf
    assert "NOTCHED IRON SHORTSWORD" in shelf
    assert "Type: Main Hand" in shelf
    assert "cellar rats" in shelf


def test_an_ordinary_message_is_never_dressed_up_as_an_embed(world):
    engine, bot, user, channel = make(world, discord=RichDiscord())
    engine.register("1", "Brynn", "Warrior")
    say(bot, user, channel, "!look")
    assert channel.embeds == []
    assert channel.texts, "it went as text"
