"""Project and deployment CLI, in the shape of OpenWrt's UCI."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from gamebot import __version__
from gamebot import plugins
from gamebot.cartridge import png as cartridge
from gamebot.cartridge.markdown import tangle as tangle_markdown
from gamebot.lang.check import Report, check, sources_in
from gamebot.lang.resolve import ERROR, WARNING, Diagnostic

_SEVERITY = {ERROR: {"fg": "red", "bold": True}, WARNING: {"fg": "yellow"}}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="gamebot")
def main() -> None:
    """A game engine for chatbot games."""


# --------------------------------------------------------------- lint

def _show(report: Report, diagnostic: Diagnostic) -> None:
    source = report.source
    where = source.where(diagnostic.line, diagnostic.column) if source else str(report.path)
    click.echo(f"{where}: ", nl=False)
    click.secho(f"{diagnostic.severity}", nl=False, **_SEVERITY[diagnostic.severity])
    click.echo(f"[{diagnostic.code}] {diagnostic.message}")

    if source is None:
        return
    origin = source.origin_line(diagnostic.line)
    text = source.line_of(origin)
    if not text.strip():
        return
    gutter = f"{origin:>7}"
    click.secho(f"{gutter} | ", nl=False, fg="bright_black")
    click.echo(text)
    click.secho(f"{' ' * len(gutter)} | ", nl=False, fg="bright_black")
    click.secho(" " * max(diagnostic.column - 1, 0) + "^", fg="bright_black")


@main.command()
@click.argument("source", default="world",
                type=click.Path(exists=True, path_type=Path))
@click.option("--warnings/--no-warnings", default=True, help="Report warnings too.")
@click.option("--stats", is_flag=True, help="Summarise the world that resolved.")
def lint(source: Path, warnings: bool, stats: bool) -> None:
    """Check a game source: .md, .game or a .png cartridge.

    Reads, parses and resolves it, then reports everything wrong at once.
    """
    paths = sources_in(source)
    if not paths:
        raise click.ClickException(f"no game sources in {source}")

    errors = total = 0
    for path in paths:
        report = check(path)
        shown = [d for d in report.diagnostics if warnings or d.severity == ERROR]
        for diagnostic in shown:
            _show(report, diagnostic)
        errors += len(report.errors)
        total += len(shown)

        if stats and report.world:
            w = report.world
            click.secho(f"{path}: ", nl=False, fg="cyan")
            click.echo(
                f"{w.title or 'untitled'} -- {len(w.locations)} locations, "
                f"{len(w.monsters)} monsters, {len(w.items)} items, "
                f"{len(w.classes)} classes, {len(w.spells)} spells, "
                f"{len(w.tracks)} tracks, {len(w.verbs)} verbs, "
                f"{len(w.flows)} flows, {len(w.offers)} offers"
            )

    noun = "source" if len(paths) == 1 else "sources"
    summary = f"{len(paths)} {noun}, {errors} error{'s' * (errors != 1)}"
    if warnings:
        others = total - errors
        summary += f", {others} warning{'s' * (others != 1)}"
    click.secho(summary, fg="red" if errors else "green")
    if errors:
        sys.exit(1)


# --------------------------------------------------------------- tangle

@main.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Write here instead of standard output.")
def tangle(source: Path, output: Path | None) -> None:
    """Extract the `game` blocks from a markdown game, in document order."""
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".png":
        text = cartridge.unpack(source.read_bytes())
    result = tangle_markdown(text)
    if not result.text.strip():
        raise click.ClickException(f"no `game` code blocks in {source}")
    if output is None:
        click.echo(result.text, nl=False)
    else:
        output.write_text(result.text, encoding="utf-8")
        click.echo(f"{output}: {len(result.line_map)} lines of source")


# --------------------------------------------------------------- pack

@main.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Cartridge to write. Defaults to the source named .png.")
@click.option("--image", type=click.Path(exists=True, path_type=Path),
              help="PNG to use as the cartridge label. A plain one is made otherwise.")
def pack(source: Path, output: Path | None, image: Path | None) -> None:
    """Pack a markdown game into a PNG cartridge."""
    markdown = source.read_text(encoding="utf-8")
    report = check(source)
    if not report.ok:
        for diagnostic in report.errors:
            _show(report, diagnostic)
        raise click.ClickException("refusing to pack a source that does not resolve")

    label = image.read_bytes() if image else cartridge.blank()
    output = output or source.with_suffix(".png")
    data = cartridge.pack(label, markdown)
    output.write_bytes(data)
    click.echo(f"{output}: {len(data):,} bytes, carrying {len(markdown):,} of source")


# --------------------------------------------------------------- unpack

@main.command()
@click.argument("cart", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Write here instead of standard output.")
def unpack(cart: Path, output: Path | None) -> None:
    """Recover the markdown game from a PNG cartridge."""
    try:
        markdown = cartridge.unpack(cart.read_bytes())
    except cartridge.CartridgeError as exc:
        raise click.ClickException(str(exc)) from exc
    if output is None:
        click.echo(markdown, nl=False)
    else:
        output.write_text(markdown, encoding="utf-8")
        click.echo(f"{output}: {len(markdown):,} bytes")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------- adapters

@main.command()
def adapters() -> None:
    """List the bot adapters this installation can run."""
    found = plugins.adapters()
    if not found:
        click.echo("No adapters installed.")
        return
    for name, adapter in sorted(found.items()):
        click.secho(name, bold=True, nl=False)
        click.echo(f" -- {adapter.summary}")
        for setting in adapter.settings:
            note = " (required)" if setting.required else (
                f" [{setting.default}]" if setting.default else "")
            click.echo(f"    {name}.{setting.key}{note} -- {setting.help}")


# -------------------------------------------------------------------- run

@main.command()
@click.argument("source", default="world/kairos.md",
                type=click.Path(exists=True, path_type=Path))
@click.option("--adapter", "-a", default="discord", show_default=True,
              help="Which bot adapter to run.")
@click.option("--set", "-s", "overrides", multiple=True, metavar="KEY=VALUE",
              help="A setting, in UCI shape: -s discord.token=...")
@click.option("--db", type=click.Path(path_type=Path), default=None,
              help="The project's sqlite3 file. Defaults to gamebot.db.")
@click.option("--check", is_flag=True,
              help="Validate the source and the settings, then stop.")
def run(source: Path, adapter: str, overrides: tuple[str, ...],
        db: Path | None, check: bool) -> None:
    """Serve a game to a chat platform.

    Settings may also come from the environment, as GAMEBOT_<ADAPTER>_<KEY>.
    """
    from gamebot.engine import Engine
    from gamebot.lang.check import check as check_source

    report = check_source(source)
    if not report.ok:
        for diagnostic in report.errors:
            _show(report, diagnostic)
        raise click.ClickException(f"{source} does not resolve")

    found = plugins.adapters()
    chosen = found.get(adapter)
    if chosen is None:
        known = ", ".join(sorted(found)) or "none"
        raise click.ClickException(f"no adapter called {adapter!r} (have: {known})")

    values = _settings(chosen, overrides)
    missing = [s.key for s in chosen.settings if s.required and not values.get(s.key)]
    if missing:
        hints = ", ".join(f"-s {adapter}.{key}=..." for key in missing)
        raise click.ClickException(f"{adapter} needs: {hints}")

    world = report.world
    click.secho(f"{world.title or source.name}", bold=True, nl=False)
    click.echo(f" -- {len(world.locations)} locations, {len(world.verbs)} verbs, "
               f"serving over {adapter}")
    if check:
        click.secho("checks passed; not connecting", fg="green")
        return

    from gamebot.store import Store

    store = Store(_db_path(db))
    engine = Engine(world, store=store)
    if engine.restored:
        click.secho("saved game refers to things this world no longer has:",
                    fg="yellow")
        for missing in engine.restored:
            click.echo(f"  {missing}")
    click.echo(f"{store.path}: {store.characters()} character(s) restored")
    try:
        chosen.run(engine, values, str(source))
    finally:
        store.save(engine.sim)
        store.close()


def _settings(adapter, overrides: tuple[str, ...]) -> dict[str, str]:
    import os

    values: dict[str, str] = {}
    for setting in adapter.settings:
        if setting.default is not None:
            values[setting.key] = setting.default
        env = os.environ.get(
            f"GAMEBOT_{adapter.name}_{setting.key}".upper())
        if env:
            values[setting.key] = env

    for pair in overrides:
        key, _, value = pair.partition("=")
        key = key.strip()
        if key.startswith(f"{adapter.name}."):
            key = key[len(adapter.name) + 1:]
        values[key] = value.strip()
    return {k: v for k, v in values.items() if v}


# --------------------------------------------------------------- the file

def _db_path(given: "Path | None") -> "Path":
    import os

    from gamebot.store import DEFAULT_PATH

    return given or Path(os.environ.get("GAMEBOT_DB") or DEFAULT_PATH)


_db_option = click.option(
    "--db", type=click.Path(path_type=Path), default=None,
    help="The project's sqlite3 file. Defaults to gamebot.db, or $GAMEBOT_DB.")


# ------------------------------------------------------------------- log

@main.command()
@click.argument("channel", required=False)
@click.option("-n", "--limit", default=20, show_default=True,
              help="How many entries to show.")
@click.option("--subject", help="Only entries about this subject.")
@click.option("--since", help="Only entries at or after this timestamp.")
@_db_option
def log(channel: str | None, limit: int, subject: str | None,
        since: str | None, db: Path | None) -> None:
    """Query the project's logs: event, session or discard.

    With no channel, shows every stream. With no entries at all, lists which
    channels hold what.
    """
    from gamebot.store import Store

    path = _db_path(db)
    if not path.exists():
        raise click.ClickException(f"no such file: {path}")

    with Store(path) as store:
        entries = store.entries(channel, limit=limit, subject=subject,
                                since=since)
        if not entries:
            held = store.channels()
            if not held:
                click.echo("nothing logged yet")
                return
            click.echo("no matching entries. Channels held:")
            for name, count in held:
                click.echo(f"  {name} ({count})")
            return

        for entry in reversed(entries):
            click.secho(entry.at, fg="bright_black", nl=False)
            click.secho(f"  {entry.channel:<8}", fg="cyan", nl=False)
            if entry.subject:
                click.secho(f"{entry.subject} ", bold=True, nl=False)
            click.echo(entry.message)
            for key, value in entry.data.items():
                if key != "kind":
                    click.secho(f"    {key}: {value}", fg="bright_black")


# --------------------------------------------------------------- discard

@main.command()
@click.argument("what")
@click.option("--why", required=True, help="Why it was dropped.")
@_db_option
def discard(what: str, why: str, db: Path | None) -> None:
    """Record something considered and dropped, as the briefs evolve."""
    from gamebot.store import DISCARD, Store

    with Store(_db_path(db)) as store:
        store.log(DISCARD, why, subject=what)
    click.secho(f"discarded: {what}", fg="green")


# ----------------------------------------------------------------- state

@main.command()
@click.argument("note", required=False)
@_db_option
def state(note: str | None, db: Path | None) -> None:
    """Show the latest session state, or save a new one."""
    from gamebot.store import SESSION, Store

    path = _db_path(db)
    if note is None and not path.exists():
        raise click.ClickException(f"no such file: {path}")

    with Store(path) as store:
        if note is not None:
            store.log(SESSION, note)
            click.secho("saved", fg="green")
            return
        latest = store.latest(SESSION)
        if latest is None:
            click.echo("no session state saved yet")
            return
        click.secho(latest.at, fg="bright_black")
        click.echo(latest.message)
