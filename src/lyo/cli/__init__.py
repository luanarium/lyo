"""Project and deployment CLI, in the shape of OpenWrt's UCI."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from lyo import __version__
from lyo import plugins
from lyo.cartridge import png as cartridge
from lyo.cartridge.markdown import tangle as tangle_markdown
from lyo.lang.check import Report, check, sources_in
from lyo.lang.resolve import ERROR, WARNING, Diagnostic

_SEVERITY = {ERROR: {"fg": "red", "bold": True}, WARNING: {"fg": "yellow"}}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="lyo")
def main() -> None:
    """lyo Engine -- a game engine for chatbot games."""


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
    click.echo("Set these with: lyo set adapter.<name>.<key>=<value>, "
               "then lyo commit")


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
              help="The project's sqlite3 file. Defaults to lyo.db.")
@click.option("--control/--no-control", default=True,
              help="Listen on a local control channel for reload and status.")
@click.option("--check", is_flag=True,
              help="Validate the source and the settings, then stop.")
def run(source: Path | None, adapter: str | None, overrides: tuple[str, ...],
        db: Path | None, control: bool, check: bool) -> None:
    """Serve a game to a chat platform.

    Source and adapter default to `game.main.source` and `adapter.main.name`.
    Settings come from configuration, then LYO_<ADAPTER>_<KEY>, then -s.
    """
    from lyo.engine import Engine
    from lyo.lang.check import check as check_source
    from lyo.store import Store

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
            f"`lyo set adapter.{adapter}.{missing[0]}=...` then "
            f"`lyo commit`, or pass -s.")

    world = report.world
    click.secho(f"{world.title or source.name}", bold=True, nl=False)
    click.echo(f" -- {len(world.locations)} locations, {len(world.verbs)} verbs, "
               f"serving over {adapter}")
    if check:
        click.secho("checks passed; not connecting", fg="green")
        store.close()
        return

    engine = Engine(world, store=store)
    services = _control_services(engine, store, source, adapter, values,
                                 _db_path(db)) if control else ()
    if engine.restored:
        click.secho("saved game refers to things this world no longer has:",
                    fg="yellow")
        for missing in engine.restored:
            click.echo(f"  {missing}")
    click.echo(f"{store.path}: {store.characters()} character(s) restored")
    try:
        _invoke(chosen.run, engine, values, str(source), services)
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
        env = os.environ.get(f"LYO_{adapter.name}_{setting.key}".upper())
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

    from lyo.store import DEFAULT_PATH

    return given or Path(os.environ.get("LYO_DB") or DEFAULT_PATH)


_db_option = click.option(
    "--db", type=click.Path(path_type=Path), default=None,
    help="The project's sqlite3 file. Defaults to lyo.db, or $LYO_DB.")


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
    from lyo.store import Store

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
    from lyo.store import Store

    return Store(_db_path(db))


def _bad_path(exc: Exception) -> "click.ClickException":
    return click.ClickException(f"{exc}. Use package.section.option")


@main.command("get")
@click.argument("path")
@_db_option
def get_option(path: str, db: Path | None) -> None:
    """Read one option's live value."""
    from lyo.store.config import BadPath

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

    Nothing takes effect until `lyo commit`.
    """
    from lyo.store.config import BadPath, split_assignment

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
    click.secho(f"{staged} staged -- run `lyo commit` to apply", fg="yellow")


@main.command("show")
@click.argument("prefix", required=False)
@_db_option
def show_options(prefix: str | None, db: Path | None) -> None:
    """Print configuration. A leading ~ is a staged value, - a staged removal."""
    from lyo.store.config import BadPath

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
    from lyo.store.config import BadPath

    with _config(db) as store:
        try:
            existed = store.config.delete(path)
        except BadPath as exc:
            raise _bad_path(exc) from exc
    if not existed:
        raise click.ClickException(f"{path} is not set")
    click.secho(f"{path} staged for removal -- run `lyo commit`", fg="yellow")


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

    #  UCI commits to the store; telling the service is a separate step.
    from lyo.control import listening

    if listening(_db_path(db)):
        click.secho("an instance is running -- `lyo reload` to apply",
                    fg="yellow")


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


def _control_services(engine, store, source: Path, adapter: str,
                      values: dict, db: Path):
    """The control channel, as a coroutine factory the adapter will run."""
    from lyo import control

    config = store.config
    service = control.Service(engine=engine, store=store, source=source,
                              adapter=adapter, settings=values)
    host = config.committed("control.main.host")
    port = int(config.committed("control.main.port") or 0)
    token = config.committed("control.main.token")
    return (lambda: control.serve(service, db=db, host=host, port=port,
                                  token=token),)


def _invoke(run, engine, values, source, services):
    """Call an adapter's run, passing services only if it accepts them."""
    import inspect

    try:
        parameters = inspect.signature(run).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "services" in parameters:
        run(engine, values, source, services=services)
        return
    if services:
        click.secho(f"note: this adapter does not host background services, "
                    f"so the control channel is not running", fg="yellow")
    run(engine, values, source)


# ------------------------------------------------------- the control channel

def _control_args(db: Path | None):
    from lyo.control import ControlError
    from lyo.store import Store

    path = _db_path(db)
    if not path.exists():
        #  No state file means nothing has ever run, let alone is running.
        raise ControlError(
            f"no state file at {path}, so nothing is running. "
            f"Start one with `lyo run`.")
    with Store(path) as store:
        config = store.config
        recorded = store.db.execute(
            "SELECT value FROM meta WHERE key = 'control_port'").fetchone()
        return {
            "db": path,
            "host": config.committed("control.main.host"),
            "port": int(recorded["value"]) if recorded else
                    int(config.committed("control.main.port") or 0) or None,
            "token": config.committed("control.main.token"),
        }


@main.command()
@_db_option
def status(db: Path | None) -> None:
    """Ask a running instance what it is doing."""
    from lyo.control import ControlError, request

    try:
        reply = request("status", **_control_args(db))
    except ControlError as exc:
        raise click.ClickException(str(exc)) from exc
    if not reply.get("ok"):
        raise click.ClickException(reply.get("error", "refused"))

    click.secho(reply["world"], bold=True, nl=False)
    click.echo(f"  pid {reply['pid']}, up {reply['uptime']}s")
    click.echo(f"  source     {reply['source']}")
    click.echo(f"  world      {reply['locations']} locations, "
               f"{reply['verbs']} verbs")
    click.echo(f"  players    {reply['characters']} registered, "
               f"{reply['duels']} duelling, {reply['offers']} challenged")


@main.command()
@_db_option
def reload(db: Path | None) -> None:
    """Apply committed configuration and world changes to a running instance."""
    from lyo.control import ControlError, request

    try:
        reply = request("reload", **_control_args(db))
    except ControlError as exc:
        raise click.ClickException(str(exc)) from exc

    if not reply.get("ok"):
        for line in reply.get("diagnostics", []):
            click.echo(line)
        raise click.ClickException(reply.get("error", "reload refused"))
    warnings = reply.get("warnings") or 0
    plural = "s" if warnings != 1 else ""
    note = f", {warnings} warning{plural}" if warnings else ""
    click.secho(f"reloaded {reply['reloaded']}{note}", fg="green")


# --------------------------------------------------------------- the service

@main.group()
def service() -> None:
    """Run and manage lyo as a service."""


def _plan(name: str, db: Path | None, source: Path | None):
    from lyo import service as svc

    return svc.plan(name=name, db=_db_path(db), source=source)


def _supervisor():
    from lyo.service import ServiceError, supervisor

    try:
        return supervisor()
    except ServiceError as exc:
        raise click.ClickException(str(exc)) from exc


def _report(result) -> None:
    click.secho(result.message, fg="green" if result.ok else "red")
    if result.detail:
        click.echo(f"  {result.detail}")
    if not result.ok:
        sys.exit(1)


_name_option = click.option("--name", default="lyo", show_default=True,
                            help="Instance name, for running more than one.")


@service.command("install")
@_name_option
@click.argument("source", required=False,
                type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True,
              help="Print the definition instead of writing it.")
@click.option("--start", "and_start", is_flag=True, help="Start it afterwards.")
@_db_option
def service_install(name: str, source: Path | None, dry_run: bool,
                    and_start: bool, db: Path | None) -> None:
    """Install the service definition for this host.

    The definition carries no secrets: the bot token lives in the project's
    sqlite3 file, so set it with `lyo set adapter.<name>.token=...` first.
    """
    from lyo.service import ServiceError, supervisor

    plan = _plan(name, db, source)
    try:
        boss = supervisor()
    except ServiceError as exc:
        if not dry_run:
            raise click.ClickException(str(exc)) from exc
        click.secho(str(exc), fg="yellow")
        click.echo()
        from lyo.service import Systemd

        click.echo(Systemd().definition(plan))
        return

    if dry_run:
        click.secho(f"{boss.kind} at {boss.unit_path(plan)}:", bold=True)
        click.echo()
        click.echo(boss.definition(plan))
        return

    _warn_about_env(plan)
    _report(boss.install(plan))
    click.echo(f"  {boss.hint(plan)}")
    if and_start:
        _report(boss.start(plan))


def _warn_about_env(plan) -> None:
    """A token given by environment variable will not reach the service."""
    import os

    leaked = [k for k in os.environ if k.startswith("LYO_") and k != "LYO_DB"]
    if leaked:
        click.secho(
            f"note: {', '.join(sorted(leaked))} is set in your shell but will "
            f"not reach the service. Put it in configuration instead: "
            f"`lyo set adapter.discord.token=...` then `lyo commit`.",
            fg="yellow")


@service.command("uninstall")
@_name_option
@_db_option
def service_uninstall(name: str, db: Path | None) -> None:
    """Stop the service and remove its definition."""
    boss = _supervisor()
    _report(boss.uninstall(_plan(name, db, None)))


@service.command("start")
@_name_option
@_db_option
def service_start(name: str, db: Path | None) -> None:
    """Start the service."""
    _report(_supervisor().start(_plan(name, db, None)))


@service.command("stop")
@_name_option
@_db_option
def service_stop(name: str, db: Path | None) -> None:
    """Stop the service."""
    _report(_supervisor().stop(_plan(name, db, None)))


@service.command("restart")
@_name_option
@_db_option
def service_restart(name: str, db: Path | None) -> None:
    """Restart the service. For configuration changes, prefer `lyo reload`."""
    _report(_supervisor().restart(_plan(name, db, None)))


@service.command("status")
@_name_option
@_db_option
def service_status(name: str, db: Path | None) -> None:
    """Report what the host's service manager thinks, and what the instance says."""
    from lyo.control import ControlError, request

    boss = _supervisor()
    plan = _plan(name, db, None)
    state = boss.status(plan)

    click.secho(f"{plan.unit_name}: ", bold=True, nl=False)
    click.secho(state.message, fg="green" if state.ok else "yellow")
    click.echo(f"  {boss.kind}")
    running = boss.current_command(plan)
    click.echo(f"  installed  {'yes, ' + str(boss.unit_path(plan)) if running else 'no'}")
    #  Show what is installed, which may differ from what this plan would write.
    click.echo(f"  command    {running or plan.command() + '   (would run)'}")

    try:
        reply = request("status", **_control_args(db))
    except (ControlError, click.ClickException) as exc:
        click.echo(f"  instance   not reachable ({exc})")
        return
    click.echo(f"  instance   {reply['world']}, pid {reply['pid']}, "
               f"up {reply['uptime']}s, {reply['characters']} character(s)")


# --------------------------------------------------------------- the bundle

@main.command()
@click.option("--no-zip", "skip_zip", is_flag=True,
              help="Generate documentation only.")
@click.option("--force", is_flag=True,
              help="Regenerate every document, stale or not.")
@click.option("-o", "--output", type=click.Path(path_type=Path),
              help="Where to write the archive. Defaults to dist/.")
def bundle(skip_zip: bool, force: bool, output: Path | None) -> None:
    """Generate any documentation not yet written or updated, then zip it up.

    Documents are generated from the code they describe, so a brief cannot
    quietly drift from what the software does. Each carries a stamp naming the
    version and a hash of its inputs, which is how staleness is known.
    """
    from lyo.docs.pages import DOCUMENTS

    root = Path.cwd()
    written, kept = [], []
    for document in DOCUMENTS:
        if force or not document.current(root):
            written.append(document.write(root).relative_to(root))
        else:
            kept.append(document.path)

    for path in written:
        click.secho(f"  wrote   {path}", fg="green")
    for path in kept:
        click.secho(f"  current {path}", fg="bright_black")
    if not written:
        click.echo("documentation is up to date")

    if skip_zip:
        return
    archive = _zip(root, output)
    click.secho(f"{archive}: {archive.stat().st_size:,} bytes", bold=True)


def _zip(root: Path, output: Path | None) -> Path:
    """Everything git tracks, plus whatever was just generated."""
    import subprocess
    import zipfile

    from lyo import __version__

    listed = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                            cwd=root, check=False)
    if listed.returncode != 0:
        raise click.ClickException("not a git repository, so there is nothing "
                                   "to bundle -- `--no-zip` still writes docs")

    files = {line for line in listed.stdout.splitlines() if line}
    from lyo.docs.pages import DOCUMENTS

    files |= {d.path for d in DOCUMENTS if (root / d.path).exists()}

    archive = output or root / "dist" / f"lyo-{__version__}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    stem = f"lyo-{__version__}"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in sorted(files):
            source = root / name
            if source.is_file():
                zipped.write(source, f"{stem}/{name}")
    return archive
