# Platforms

What each installed adapter needs before it will work. The engine knows none of this — an adapter declares its own prerequisites, so this page grows when you install another one.

## discord

Play in Discord channels and DMs via discord.py.

Before this adapter will work, Discord needs three things done in
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

### Settings

| Option | | Means |
|---|---|---|
| `adapter.discord.token` | required | Discord bot token. |
| `adapter.discord.prefix` | default `!` | Command prefix. |
| `adapter.discord.owner` | optional | Discord user id allowed to run owner commands. |
| `adapter.discord.notice_seconds` | default `3` | How long the 'check your DMs' note lives. |

```bash
lyo set adapter.main.name=discord
lyo set adapter.discord.token=...
lyo commit
lyo run
```

## webui

Play in a local browser page, with no platform account.

Nothing to set up. This adapter is for trying a game out locally,
so it has no account, no token and no external service.

```
lyo run -a webui
```

It prints a URL; open it. The page needs internet once, to fetch
[quikchat](https://github.com/deftio/quikchat) from a CDN. To work offline,
download `quikchat.umd.min.js` and `quikchat.css` next to each other and name
the directory holding them:

```
lyo set adapter.webui.assets=/path/to/quikchat
lyo commit
```

A `file://` URL means the same thing, and on Windows that is
`file:///C:/path/to/quikchat`. Either way the adapter serves those two files
itself, from `/assets/`, because a page served over HTTP is not allowed to load
a script off the local filesystem. Anything beginning `http://` or `https://` is
handed to the page as it stands, so a CDN or a mirror still works.

The page opens on the ephemeral session as `neo`, both of which are settings,
so poking around saves nothing until you switch deliberately.

**Loading a gameworld.** The box in the left margin is the loaded gameworld's
cover. Click it to load another -- a PNG cartridge, whose own pixels become the
cover, or a bare markdown file. A gameworld is checked before it is accepted,
and a file that does not resolve is refused with the same diagnostics `lyo
lint` would give, so a typo is reported rather than half-loaded.

A loaded gameworld runs in the ephemeral session only. The persistent one keeps
serving the configured game, because its saved characters refer to that game's
items and locations by id and would be orphaned by another.

**Two simulations.** The page has a *persistent* and an *ephemeral* session.
Persistent is the real one, saved to the project's sqlite3 file alongside
whatever your Discord players have done. Ephemeral keeps nothing and can be
reset from the page, which is what you want while changing a game's rules.
They do not share characters.

**Acting as several players.** The page lets you switch identity, so one
browser can register two characters and duel them against each other. That is
the only practical way to test PvP without a second person.

It binds to `127.0.0.1` by default. Widening it serves an unauthenticated
interface that can act as any character, so a non-loopback host also requires
`adapter.webui.token`, which the printed URL then carries.

### Settings

| Option | | Means |
|---|---|---|
| `adapter.webui.host` | default `127.0.0.1` | Interface to bind. Loopback unless widened deliberately. |
| `adapter.webui.port` | default `8720` | Port to listen on. |
| `adapter.webui.token` | optional | Shared secret, required when host is not loopback. |
| `adapter.webui.assets` | default `https://unpkg.com/quikchat` | Where to load quikchat from. Point this at a local copy to work offline. |
| `adapter.webui.prefix` | default `!` | What a command starts with, as in a chat room. Empty means no prefix is needed. |
| `adapter.webui.theme` | default `quikchat-theme-dark` | A quikchat theme class. |
| `adapter.webui.pace` | default `600` | Milliseconds to think before each line of output, shown as quikchat's three-dot pulse. 0 is instant. |
| `adapter.webui.player` | default `neo` | Who the page starts out playing as. |
| `adapter.webui.session` | default `ephemeral` | Which simulation the page opens on: ephemeral keeps nothing, persistent saves. |
| `adapter.webui.sweep_seconds` | default `1` | How often timed-out prompts and lapsed challenges are checked. |
| `adapter.webui.max_upload` | default `4194304` | Largest gameworld the page will accept, in bytes. |

```bash
lyo set adapter.main.name=webui
lyo commit
lyo run
```

## Terms

| Term        | Definition |
| ----------- | ---------- |
| adapter     | A plugin connecting the engine to one chat platform |
| intent      | A Discord permission to receive a category of event |
| gateway     | Discord's websocket connection, which a bot holds open |
| OAuth scope | What an invite link grants the bot |
| token       | The bot's credential. It comes from configuration, the environment or a .env -- never from the game you ship |

<!-- generated by lyo 0.1.0 from c23e544c8e73cf9d -->
