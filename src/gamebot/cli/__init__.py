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
@click.option("--check", is_flag=True,
              help="Validate the source and the settings, then stop.")
def run(source: Path, adapter: str, overrides: tuple[str, ...],
        check: bool) -> None:
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

    engine = Engine(world)
    chosen.run(engine, values, str(source))


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
