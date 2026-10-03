"""Configuration in UCI shape: staging, committing, reverting."""

import pytest

from lyo.store import Store
from lyo.store.config import BadPath, parse, split_assignment


@pytest.fixture
def config(tmp_path):
    with Store(tmp_path / "lyo.db") as store:
        yield store.config


# ------------------------------------------------------------------ paths

def test_a_path_is_three_parts():
    assert parse("adapter.discord.token") == ("adapter", "discord", "token")


@pytest.mark.parametrize("bad", ["", "adapter", "adapter.discord",
                                 "a.b.c.d", "adapter..token", "."])
def test_a_malformed_path_is_rejected(bad):
    with pytest.raises(BadPath):
        parse(bad)


def test_a_prefix_is_allowed_when_not_exact():
    assert parse("adapter", exact=False) == ("adapter",)
    assert parse("adapter.discord", exact=False) == ("adapter", "discord")


def test_an_assignment_splits_and_unquotes():
    assert split_assignment("a.b.c=x") == ("a.b.c", "x")
    assert split_assignment("a.b.c='x y'") == ("a.b.c", "x y")
    assert split_assignment("a.b.c=") == ("a.b.c", "")
    with pytest.raises(BadPath):
        split_assignment("a.b.c")


# ---------------------------------------------------------------- staging

def test_a_set_stages_and_a_commit_applies(config):
    config.set("adapter.discord.token", "abc")
    assert config.changes()
    assert config.get("adapter.discord.token") == "abc"

    config.commit()
    assert config.changes() == []
    assert config.get("adapter.discord.token") == "abc"


def test_a_running_service_sees_nothing_until_commit(config):
    """The point of the convention: a half-finished edit is not live."""
    config.set("adapter.discord.token", "abc")
    assert config.get("adapter.discord.token") == "abc", "the author sees it"
    assert config.committed("adapter.discord.token") is None, "the service does not"
    assert config.live("adapter", "discord") == {}

    config.commit()
    assert config.committed("adapter.discord.token") == "abc"
    assert config.live("adapter", "discord") == {"token": "abc"}


def test_revert_discards_a_staged_change(config):
    config.set("adapter.discord.prefix", "!")
    config.commit()
    config.set("adapter.discord.prefix", "?")
    assert config.get("adapter.discord.prefix") == "?"

    config.revert()
    assert config.get("adapter.discord.prefix") == "!"
    assert config.changes() == []


def test_revert_removes_an_option_that_was_never_committed(config):
    config.set("adapter.discord.token", "abc")
    config.revert()
    assert config.show() == []


def test_commit_can_be_scoped_to_one_package(config):
    config.set("adapter.discord.token", "abc")
    config.set("game.main.source", "world/kairos.md")
    config.commit("adapter")

    assert config.committed("adapter.discord.token") == "abc"
    assert config.committed("game.main.source") is None
    assert [o.path for o in config.changes()] == ["game.main.source"]


# --------------------------------------------------------------- deleting

def test_deleting_a_committed_option_stages_the_removal(config):
    config.set("adapter.discord.prefix", "!")
    config.commit()

    assert config.delete("adapter.discord.prefix")
    assert config.committed("adapter.discord.prefix") == "!", "still live"
    assert config.get("adapter.discord.prefix") is None, "gone to the author"

    config.commit()
    assert config.show() == []


def test_deleting_an_uncommitted_option_just_drops_it(config):
    config.set("adapter.discord.prefix", "!")
    assert config.delete("adapter.discord.prefix")
    assert config.show() == []


def test_deleting_something_absent_reports_it(config):
    assert config.delete("adapter.discord.nothing") is False


def test_a_staged_removal_can_be_reverted(config):
    config.set("adapter.discord.prefix", "!")
    config.commit()
    config.delete("adapter.discord.prefix")
    config.revert()
    assert config.get("adapter.discord.prefix") == "!"


# ----------------------------------------------------------------- showing

def test_show_filters_by_prefix(config):
    config.set("adapter.discord.token", "abc")
    config.set("game.main.source", "world/kairos.md")
    config.commit()

    assert [o.path for o in config.show("adapter")] == ["adapter.discord.token"]
    assert [o.path for o in config.show("game.main")] == ["game.main.source"]
    assert len(config.show()) == 2


def test_show_marks_staged_values_and_removals(config):
    config.set("adapter.discord.token", "abc")
    config.commit()
    config.set("adapter.discord.prefix", "?")
    config.delete("adapter.discord.token")

    lines = {o.option: o.show() for o in config.show()}
    assert lines["prefix"].startswith("~")
    assert lines["token"].startswith("-")


def test_values_with_quotes_survive_a_round_trip(config):
    config.set("adapter.discord.token", "it's a secret")
    config.commit()
    assert config.get("adapter.discord.token") == "it's a secret"


# ------------------------------------------------------------- migration

def test_a_schema_three_config_table_gains_the_column(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE config (
            package TEXT NOT NULL, section TEXT NOT NULL, option TEXT NOT NULL,
            value TEXT, staged TEXT,
            PRIMARY KEY (package, section, option));
        INSERT INTO config VALUES ('adapter', 'discord', 'token', NULL, 'abc');
        INSERT INTO config VALUES ('adapter', 'discord', 'prefix', '!', NULL);
    """)
    old.commit()
    old.close()

    with Store(path) as store:
        config = store.config
        #  A pre-existing staged value is read as a staged set.
        assert [o.path for o in config.changes()] == ["adapter.discord.token"]
        assert config.get("adapter.discord.token") == "abc"
        assert config.committed("adapter.discord.prefix") == "!"
