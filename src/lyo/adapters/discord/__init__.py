"""The discord.py adapter.

discord.py is imported lazily inside `run`, so this module is importable --
and discoverable as a plugin -- whether or not the `discord` extra is
installed. Nothing in the engine imports this package.
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field

from lyo.engine import Engine, Message
from lyo.plugins import Adapter, Setting, hookimpl
from lyo.signals import stop_on_signals

SETTINGS = (
    Setting("token", "Discord bot token.", required=True, secret=True),
    Setting("prefix", "Command prefix.", default="!"),
    Setting("owner", "Discord user id allowed to run owner commands."),
    Setting("notice_seconds", "How long the 'check your DMs' note lives.",
            default="3"),
)

#  Presentation lives on this side of the boundary, not in the game.
EMOJI = {
    "refusal": "⛔", "location": "\U0001f9ed", "map": "\U0001f5fa",
    "inventory": "\U0001f392", "roster": "\U0001f465", "help": "❓",
    "stock": "\U0001f3ea",
}
_NUMBER = re.compile(r"(?<![\w*])(\d+)(?![\w*])")


SETUP = """Before this adapter will work, Discord needs three things done in
the [developer portal](https://discord.com/developers/applications).

1. **Create an application**, then under **Bot** use *Reset Token* to get a
   token. That is `adapter.discord.token`.

   A machine that already runs a discord.py bot usually keeps that token in a
   `.env` file as `DISCORD_TOKEN`. Leave it there: a `.env` beside the project
   -- or one directory above it -- is read at startup, as is `$DISCORD_TOKEN`
   itself, so nothing has to be copied into configuration. `lyo run --check`
   prints which of them the token came from.

2. **Enable the Message Content Intent**, under **Bot → Privileged Gateway
   Intents**. Without it the bot connects but never sees a command, because
   Discord sends empty message content. This adapter requests the intent, so
   discord.py will refuse to connect until the portal grants it.

3. **Invite the bot**, under **OAuth2 → URL Generator**, with the `bot` scope
   and these permissions:

   | Permission | Why |
   |---|---|
   | Send Messages | everything |
   | Read Message History | reading commands in a channel |
   | Manage Messages | deleting the "check your DMs" notice after a few seconds |

   Only the first two are required. Without *Manage Messages* the notice simply
   stays in the channel.

For `adapter.discord.owner`, which enables `!reload` in chat: turn on
**Developer Mode** in Discord's own settings under *Advanced*, then right-click
your name and *Copy User ID*.

Players need their direct messages open for private output such as `!inventory`
and `!register`. If they are closed, the adapter posts in the channel instead,
except for `!shop`, which points them at `!buy` instead.
"""


@hookimpl
def lyo_adapter() -> Adapter:
    return Adapter(
        name="discord",
        summary="Play in Discord channels and DMs via discord.py.",
        run=run,
        settings=SETTINGS,
        setup=SETUP,
    )


@hookimpl
def lyo_present(text: str, kind: str | None, private: bool) -> str:
    """Bold the numbers and prefix a line with an emoji, per the brief."""
    styled = _NUMBER.sub(r"**\1**", text)
    badge = EMOJI.get(kind or "")
    if badge:
        return f"{badge} {styled}"
    return styled


@dataclass
class Settings:
    """A live view over the host's settings dict.

    Reading through rather than snapshotting means a `lyo reload` that changes
    `adapter.discord.prefix` takes effect without dropping the connection.
    """

    values: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, values: dict[str, str]) -> "Settings":
        return cls(values)

    @property
    def token(self) -> str:
        return self.values.get("token", "")

    @property
    def prefix(self) -> str:
        return self.values.get("prefix") or "!"

    @property
    def owner(self) -> str | None:
        return self.values.get("owner") or None

    @property
    def notice_seconds(self) -> float:
        return float(self.values.get("notice_seconds") or 3)


def run(engine: Engine, values: dict[str, str], source: str | None = None,
        services: tuple = ()) -> None:
    """Connect to Discord and serve the engine until interrupted.

    `services` are coroutine factories the host wants running alongside, such
    as the control channel. A failure in any of them takes the rest down.
    """
    import discord  # noqa: PLC0415 - deliberately lazy

    settings = Settings.from_mapping(values)
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True
    client = discord.Client(intents=intents)
    bot = Bot(engine, client, settings, discord, source)

    @client.event
    async def on_ready() -> None:
        print(f"connected as {client.user} -- serving {engine.world.title!r}")

    @client.event
    async def on_message(message) -> None:
        if message.author.bot:
            return
        await bot.handle(message)

    async def main() -> None:
        stop_on_signals()
        async with client:
            async with asyncio.TaskGroup() as group:
                group.create_task(client.start(settings.token))
                for factory in services:
                    group.create_task(factory())

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("stopped", flush=True)
    except BaseException as error:
        #  The two ways a Discord bot fails to start are a token Discord will
        #  not accept and an intent the portal has not granted. Both arrive as
        #  a library exception from inside a TaskGroup, which would otherwise
        #  reach the operator as a traceback saying neither what is wrong nor
        #  where to fix it.
        advice = diagnose(error, discord)
        if advice is None:
            raise
        print(advice, file=sys.stderr, flush=True)
        raise SystemExit(1) from None


def diagnose(error: BaseException, discord) -> str | None:
    """Advice for a startup failure, or None if it is not one we know.

    `discord` is passed in rather than imported so this stays callable
    without the extra installed.
    """
    for cause in _flatten(error):
        if isinstance(cause, discord.LoginFailure):
            return (
                "Discord refused the token. It is read from, in order of "
                "precedence: -s, $LYO_DISCORD_TOKEN or $DISCORD_TOKEN, "
                "adapter.discord.token, then a .env file -- `lyo run --check` "
                "prints which one was used. If it is the right one, it may "
                "have been revoked: Reset Token in the developer portal "
                "issues a new one.")
        if isinstance(cause, discord.PrivilegedIntentsRequired):
            return (
                "Discord has not granted the Message Content Intent, without "
                "which a bot cannot read a command. Enable it under Bot -> "
                "Privileged Gateway Intents in the developer portal, then "
                "start again. `lyo adapters --setup` has the rest of the "
                "portal setup.")
    return None


def _flatten(error: BaseException) -> list[BaseException]:
    """An exception and, for a group, everything inside it."""
    if isinstance(error, BaseExceptionGroup):
        return [error, *(c for e in error.exceptions for c in _flatten(e))]
    return [error]


class Bot:
    """Maps Discord messages onto engine commands, and back again."""

    def __init__(self, engine: Engine, client, settings: Settings, discord,
                 source: str | None) -> None:
        self.engine = engine
        self.client = client
        self.settings = settings
        self.discord = discord
        self.source = source
        self._busy: set[int] = set()
        self._waiting: set = set()

    # ------------------------------------------------------------- inbound

    async def handle(self, message) -> None:
        uid = str(message.author.id)
        private = message.guild is None

        #  A DM from someone mid-conversation is an answer, not a command.
        if private and message.author.id in self._busy:
            return

        text = message.content.strip()
        if not text.startswith(self.settings.prefix):
            return
        text = text[len(self.settings.prefix):].strip()
        if not text:
            return

        word = text.split()[0].casefold()
        if word in ("reload", "restart"):
            await self._reload(message)
            return

        flow = self.engine.flow_named(word)
        if flow is not None:
            await self._converse(message, flow)
            return

        outcome = self.engine.command(uid, self._resolve_mentions(message, text))
        if outcome.unknown:
            return
        await self._deliver(message, outcome.messages)

        #  A challenge lapses on its own. The adapter does the waiting, as it
        #  does for a flow's prompts.
        if outcome.expires_in:
            self._schedule(self._lapse(message.channel, outcome.expires_in))

    def _resolve_mentions(self, message, text: str) -> str:
        """Turn a real mention, <@123>, into the bare id the engine binds on.

        A typed `@name` needs nothing here: it arrives as plain text and the
        engine matches it against character names. That is why this adapter
        does not ask for the privileged members intent -- a bot the portal has
        not granted it cannot connect at all.
        """
        for user in message.mentions:
            text = re.sub(rf"<@!?{user.id}>", str(user.id), text)
        return text

    # ------------------------------------------------------------ outbound

    async def _deliver(self, message, messages: list[Message]) -> None:
        public = [m for m in messages if not m.private]
        private = [m for m in messages if m.private]

        for item in public:
            await message.channel.send(self._style(item))

        if not private:
            return
        sent = await self._dm(message.author, private)
        if sent:
            if message.guild is not None:
                await message.channel.send(
                    f"{message.author.mention} check your DMs.",
                    delete_after=self.settings.notice_seconds)
            return
        #  DMs are closed: fall back to the channel rather than losing the reply.
        for item in private:
            await message.channel.send(self._style(item))

    async def _dm(self, user, messages: list[Message]) -> bool:
        try:
            channel = user.dm_channel or await user.create_dm()
            for item in messages:
                await channel.send(self._style(item))
        except self.discord.Forbidden:
            return False
        return True

    def _style(self, message: Message) -> str:
        return lyo_present(message.text, message.kind, message.private)

    def _schedule(self, coroutine) -> None:
        task = asyncio.ensure_future(coroutine)
        self._waiting.add(task)
        task.add_done_callback(self._waiting.discard)

    async def drain(self) -> None:
        """Wait for anything scheduled. Used by tests."""
        while self._waiting:
            await asyncio.gather(*list(self._waiting), return_exceptions=True)

    async def _lapse(self, channel, seconds: float) -> None:
        await asyncio.sleep(seconds)
        for notice in self.engine.expire_offers():
            await channel.send(self._style(notice))

    # --------------------------------------------------------- conversations

    async def _converse(self, message, flow: str) -> None:
        user, uid = message.author, str(message.author.id)
        if user.id in self._busy:
            return
        self._busy.add(user.id)
        try:
            await self._run_flow(message, flow, user, uid)
        finally:
            self._busy.discard(user.id)

    async def _run_flow(self, message, flow: str, user, uid: str) -> None:
        try:
            channel = user.dm_channel or await user.create_dm()
        except self.discord.Forbidden:
            await message.channel.send(
                f"{user.mention} I cannot DM you. "
                f"Open your DMs, or use `{self.settings.prefix}buy <item>`.")
            return

        if message.guild is not None:
            await message.channel.send(
                f"{user.mention} check your DMs.",
                delete_after=self.settings.notice_seconds)

        step = self.engine.begin_flow(uid, flow)
        while True:
            for item in step.messages:
                target = channel if item.private else message.channel
                await target.send(self._style(item))
            if step.prompt is None:
                return

            await channel.send(self._style(
                Message(step.prompt.rendered(), True)))

            def is_answer(reply) -> bool:
                return (reply.author.id == user.id
                        and reply.guild is None
                        and not reply.author.bot)

            try:
                reply = await self.client.wait_for(
                    "message", check=is_answer, timeout=step.prompt.timeout)
            except asyncio.TimeoutError:
                step = self.engine.abandon_flow(uid)
                for item in step.messages:
                    target = channel if item.private else message.channel
                    await target.send(self._style(item))
                return
            step = self.engine.reply_flow(uid, reply.content)

    # --------------------------------------------------------------- owner

    async def _reload(self, message) -> None:
        """Validate before restarting, and refuse with the errors shown."""
        owner = self.settings.owner
        if not owner or str(message.author.id) != owner:
            return
        if not self.source:
            await message.channel.send("No source to reload from.")
            return

        from lyo.lang.check import check

        report = check(self.source)
        if not report.ok:
            lines = "\n".join(
                d.format(report.source) if report.source else d.message
                for d in report.errors[:10])
            await message.channel.send(
                f"Refusing to reload -- {len(report.errors)} error(s):\n```\n{lines}\n```")
            return

        self.engine.reload(report.world)
        await message.channel.send("Back online.")
