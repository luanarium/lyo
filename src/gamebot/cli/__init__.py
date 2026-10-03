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
            click.echo(f"    adapter.{name}.{setting.key}{note} -- {setting.help}")
    click.echo()
    click.echo("Set these with: gamebot set adapter.<name>.<key>=<value>, "
               "then gamebot commit")


# -------------------------------------------------------------------- run

@main.command()
@click.argument("source", required=False,
                type=click.Path(exists=True, path_type=Path))
@click.option("--adapter", "-a", default=None,
              help="Which bot adapter to run. Default: adapter.main.name, "
                   "else discord.")
@click.option("--set", "-s", "overrides", multiple=True, metavar="KEY=VALUE",
              help="A setting, in UCI shape: -s discord.token=...")
@click.option("--db", type=click.Path(path_type=Path), default=None,
              help="The project's sqlite3 file. Defaults to gamebot.db.")
@click.option("--check", is_flag=True,
              help="Validate the source and the settings, then stop.")
def run(source: Path | None, adapter: str | None, overrides: tuple[str, ...],
        db: Path | None, check: bool) -> None:
    """Serve a game to a chat platform.

    Source and adapter default to `game.main.source` and `adapter.main.name`.
    Settings come from configuration, then GAMEBOT_<ADAPTER>_<KEY>, then -s.
    """
    from gamebot.engine import Engine
    from gamebot.lang.check import check as check_source
    from gamebot.store import Store

    store = Store(_db_path(db))
    config = store.config
    source = source or Path(config.committed("game.main.source")
                            or "world/kairos.md")
    adapter = adapter or config.committed("adapter.main.name") or "discord"
    if not source.exists():
        store.close()
        raise click.ClickException(f"no such game source: {source}")

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

    values = _settings(chosen, overrides, config)
    missing = [s.key for s in chosen.settings if s.required and not values.get(s.key)]
    if missing:
        hints = ", ".join(f"adapter.{adapter}.{key}" for key in missing)
        raise click.ClickException(
            f"{adapter} needs {hints}. Set it with "
            f"`gamebot set adapter.{adapter}.{missing[0]}=...` then "
            f"`gamebot commit`, or pass -s.")

    world = report.world
    click.secho(f"{world.title or source.name}", bold=True, nl=False)
    click.echo(f" -- {len(world.locations)} locations, {len(world.verbs)} verbs, "
               f"serving over {adapter}")
    if check:
        click.secho("checks passed; not connecting", fg="green")
        store.close()
        return

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


def _settings(adapter, overrides: tuple[str, ...], config) -> dict[str, str]:
    """Declared default, then configuration, then environment, then -s."""
    import os

    values: dict[str, str] = {
        s.key: s.default for s in adapter.settings if s.default is not None
    }
    values.update(config.live("adapter", adapter.name))

    for setting in adapter.settings:
        env = os.environ.get(f"GAMEBOT_{adapter.name}_{setting.key}".upper())
        if env:
            values[setting.key] = env

    for pair in overrides:
        key, _, value = pair.partition("=")
        key = key.strip()
        for prefix in (f"adapter.{adapter.name}.", f"{adapter.name}."):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
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


# ----------------------------------------------------------------- state

@main.command()
@click.argument("summary", required=False)
@click.option("--history", "-n", type=int, default=None,
              help="Show the last N entries instead of only the latest.")
@_db_option
def state(summary: str | None, history: int | None, db: Path | None) -> None:
    """Show the latest session state, or save a new one.

    One brief paragraph per session. Git is the record of what changed and why;
    this is the digest on top of it.
    """
    from gamebot.store import Store

    path = _db_path(db)
    if summary is None and not path.exists():
        raise click.ClickException(f"no such file: {path}")

    with Store(path) as store:
        if summary is not None:
            store.save_state(summary)
            click.secho("saved", fg="green")
            return

        entries = store.state(history or 1)
        if not entries:
            click.echo("no session state saved yet")
            return
        for entry in reversed(entries):
            click.secho(entry.at, fg="bright_black")
            click.echo(entry.summary)
            if len(entries) > 1:
                click.echo()


# ------------------------------------------------------------ config (UCI)
#
# `package.section.option`, get/set/show/commit. A set stages; nothing is live
# until commit. First-party paths: game.main.source, adapter.main.name, and
# adapter.<name>.<key> for whatever an adapter declares.

def _config(db: "Path | None"):
    from gamebot.store import Store

    return Store(_db_path(db))


def _bad_path(exc: Exception) -> "click.ClickException":
    return click.ClickException(f"{exc}. Use package.section.option")


@main.command("get")
@click.argument("path")
@_db_option
def get_option(path: str, db: Path | None) -> None:
    """Read one option's live value."""
    from gamebot.store.config import BadPath

    with _config(db) as store:
        try:
            value = store.config.get(path)
        except BadPath as exc:
            raise _bad_path(exc) from exc
    if value is None:
        raise click.ClickException(f"{path} is not set")
    click.echo(value)


@main.command("set")
@click.argument("assignments", nargs=-1, required=True, metavar="PATH=VALUE...")
@_db_option
def set_option(assignments: tuple[str, ...], db: Path | None) -> None:
    """Stage one or more options. Takes `-` to read assignments from stdin.

    Nothing takes effect until `gamebot commit`.
    """
    from gamebot.store.config import BadPath, split_assignment

    lines: list[str] = []
    for given in assignments:
        if given == "-":
            lines += sys.stdin.read().splitlines()
        else:
            lines.append(given)

    staged = 0
    with _config(db) as store:
        for line in lines:
            #  Tolerate the markers `show` emits, so show | set - round-trips.
            line = line.lstrip("~- ").strip()
            if not line or line.startswith("#"):
                continue
            try:
                path, value = split_assignment(line)
                option = store.config.set(path, value)
            except BadPath as exc:
                raise _bad_path(exc) from exc
            click.echo(option.show())
            staged += 1
    click.secho(f"{staged} staged -- run `gamebot commit` to apply", fg="yellow")


@main.command("show")
@click.argument("prefix", required=False)
@_db_option
def show_options(prefix: str | None, db: Path | None) -> None:
    """Print configuration. A leading ~ is a staged value, - a staged removal."""
    from gamebot.store.config import BadPath

    with _config(db) as store:
        try:
            options = store.config.show(prefix)
        except BadPath as exc:
            raise _bad_path(exc) from exc
        if not options:
            click.echo("nothing configured" if not prefix
                       else f"nothing matching {prefix}")
            return
        for option in options:
            click.echo(option.show())


@main.command("delete")
@click.argument("path")
@_db_option
def delete_option(path: str, db: Path | None) -> None:
    """Stage the removal of one option."""
    from gamebot.store.config import BadPath

    with _config(db) as store:
        try:
            existed = store.config.delete(path)
        except BadPath as exc:
            raise _bad_path(exc) from exc
    if not existed:
        raise click.ClickException(f"{path} is not set")
    click.secho(f"{path} staged for removal -- run `gamebot commit`", fg="yellow")


@main.command("changes")
@click.argument("package", required=False)
@_db_option
def show_changes(package: str | None, db: Path | None) -> None:
    """List staged changes awaiting a commit."""
    with _config(db) as store:
        pending = store.config.changes(package)
    if not pending:
        click.echo("no staged changes")
        return
    for option in pending:
        click.echo(option.show())


@main.command("commit")
@click.argument("package", required=False)
@_db_option
def commit_options(package: str | None, db: Path | None) -> None:
    """Apply staged changes."""
    with _config(db) as store:
        applied = store.config.commit(package)
    if not applied:
        click.echo("no staged changes")
        return
    for option in applied:
        click.echo(f"{option.path}={option.effective or ''}")
    click.secho(f"{len(applied)} committed", fg="green")


@main.command("revert")
@click.argument("package", required=False)
@_db_option
def revert_options(package: str | None, db: Path | None) -> None:
    """Throw staged changes away."""
    with _config(db) as store:
        dropped = store.config.revert(package)
    if not dropped:
        click.echo("no staged changes")
        return
    click.secho(f"{len(dropped)} reverted", fg="green")
