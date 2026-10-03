"""Documentation as a compilation step, and the bundle that runs it."""

import re
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from lyo import __version__
from lyo.cli import main
from lyo.docs import STAMP, commands, declarations, statements, tables, terms
from lyo.docs.pages import DOCUMENTS

ROOT = Path(__file__).parent.parent


def run(*args, cwd=None):
    runner = CliRunner()
    if cwd is None:
        return runner.invoke(main, [str(a) for a in args])
    import os

    here = os.getcwd()
    try:
        os.chdir(cwd)
        return runner.invoke(main, [str(a) for a in args])
    finally:
        os.chdir(here)


# ------------------------------------------------------------ introspection

def test_declarations_come_from_the_grammar():
    found = declarations()
    #  Twelve top-level; `npc` is a declaration only inside a location.
    assert len(found) == 12
    assert found[0] == "game" and "offer" in found and "flow" in found
    assert "npc" not in found


def test_commands_come_from_click_including_the_service_group():
    names = [name for name, _usage, _help in commands()]
    assert "lint" in names and "bundle" in names
    assert "service install" in names, "group members are listed too"
    assert all(help_ for _n, _u, help_ in commands()), "every command is described"


def test_statements_come_from_the_executor():
    assert "deal" in statements() and "refuse" in statements()


def test_tables_come_from_the_schema():
    assert "player" in tables() and "config" in tables()


def test_a_terms_table_is_aligned_markdown():
    text = terms([("a", "first"), ("bb", "second")])
    lines = text.splitlines()
    assert lines[0].startswith("| Term")
    assert len({len(line.split("|")) for line in lines}) == 1, "same column count"


# ------------------------------------------------------------- the stamp

def test_every_document_renders_and_carries_the_required_pieces():
    for document in DOCUMENTS:
        text = document.render()
        assert text.strip(), document.path
        assert text.startswith("# "), f"{document.path} needs a heading"
        if document.path != "README.md":
            assert "| Term" in text, f"{document.path} needs its terms table"


def test_a_written_document_is_then_current(tmp_path):
    document = DOCUMENTS[0]
    #  Inputs are read relative to the root, so copy what it needs.
    for name in document.inputs:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())

    assert document.current(tmp_path) is False
    document.write(tmp_path)
    assert document.current(tmp_path) is True

    found = STAMP.search((tmp_path / document.path).read_text())
    assert found and found["version"] == __version__


def test_changing_an_input_makes_it_stale(tmp_path):
    document = DOCUMENTS[2]  # cartridge.md
    for name in document.inputs:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    document.write(tmp_path)
    assert document.current(tmp_path)

    #  Content, not mtime: a touch must not count as a change.
    first = tmp_path / document.inputs[0]
    first.touch()
    assert document.current(tmp_path), "a touch is not a change"

    first.write_bytes(first.read_bytes() + b"\n# changed\n")
    assert document.current(tmp_path) is False


def test_the_shipped_documentation_is_current():
    """`lyo bundle` was run; the committed docs match the code."""
    stale = [d.path for d in DOCUMENTS if not d.current(ROOT)]
    assert not stale, f"run `lyo bundle`: {stale}"


# --------------------------------------------------------------- the bundle

def test_bundle_writes_documents_and_an_archive(tmp_path):
    import shutil
    import subprocess

    work = tmp_path / "project"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
        ".git", ".venv", "dist", "__pycache__", "*.db", "*.sock"))
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    subprocess.run(["git", "add", "-A"], cwd=work, check=True)

    for document in DOCUMENTS:
        (work / document.path).unlink(missing_ok=True)

    result = run("bundle", cwd=work)
    assert result.exit_code == 0, result.output
    assert result.output.count("wrote") == len(DOCUMENTS)

    for document in DOCUMENTS:
        assert (work / document.path).exists(), document.path

    archive = work / "dist" / f"lyo-{__version__}.zip"
    assert archive.exists()
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
    assert f"lyo-{__version__}/README.md" in names
    assert f"lyo-{__version__}/docs/language.md" in names
    assert f"lyo-{__version__}/src/lyo/cli/__init__.py" in names
    assert not any("/.venv/" in n for n in names), "git decides what is in"


def test_bundle_says_nothing_to_do_when_current():
    result = run("bundle", "--no-zip")
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_bundle_no_zip_writes_no_archive(tmp_path):
    result = run("bundle", "--no-zip")
    assert result.exit_code == 0
    assert "bytes" not in result.output


def test_bundle_outside_a_repository_explains_itself(tmp_path):
    result = run("bundle", cwd=tmp_path)
    assert result.exit_code != 0
    assert "not a git repository" in result.output
