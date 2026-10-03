"""Persistence: characters, live simulation, and the logs."""

from pathlib import Path

import pytest

from gamebot.engine import Engine
from gamebot.lang.check import check
from gamebot.lang.model import slug
from gamebot.store import Store

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


@pytest.fixture(scope="module")
def world():
    report = check(WORLD)
    assert report.ok
    return report.world


@pytest.fixture
def db(tmp_path):
    with Store(tmp_path / "gamebot.db") as store:
        yield store


# ------------------------------------------------------------------- ids

def test_slugs_are_stable_and_readable():
    assert slug("Iron Sword") == "iron_sword"
    assert slug("Dragon's Heart") == "dragons_heart"
    assert slug("The Ruined Keep") == "the_ruined_keep"
    assert slug("!!!") == "unnamed"


def test_the_world_gives_every_declaration_an_id(world):
    assert world.items["Iron Sword"].id == "iron_sword"
    assert world.locations["The Ruined Keep"].id == "the_ruined_keep"
    assert world.classes["Warrior"].id == "warrior"


def test_an_explicit_id_overrides_the_slug(world, tmp_path):
    source = tmp_path / "t.game"
    source.write_text(
        'game "T":\n  players start at "Home" with 1 hp\n\n'
        'location "Home":\n  id hearth\n  "Here."\n\n'
        'item "Fists" is the default weapon:\n  1 damage scaling str\n\n'
        'item "Clothes" is the default body armor:\n  0 def\n')
    report = check(source)
    assert report.ok
    assert report.world.locations["Home"].id == "hearth"


def test_colliding_ids_are_an_error(tmp_path):
    source = tmp_path / "t.game"
    source.write_text(
        'game "T":\n  players start at "Home" with 1 hp\n\n'
        'location "Home":\n  "Here."\n\n'
        'item "Fists" is the default weapon:\n  1 damage scaling str\n\n'
        'item "Clothes" is the default body armor:\n  0 def\n\n'
        'item "Rock" is a weapon:\n  id stone\n  1 damage scaling str\n\n'
        'item "Pebble" is a weapon:\n  id stone\n  1 damage scaling str\n')
    report = check(source)
    assert any(d.code == "id-clash" for d in report.errors)


# -------------------------------------------------------------- round trip

def test_a_character_survives_a_restart(world, tmp_path):
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        first = Engine(world, seed=7, store=store)
        first.register("u1", "Brynn", "Warrior")
        first.command("u1", "travel north")
        first.command("u1", "attack wolf")
        before = first.sim.players["u1"]
        snapshot = (before.name, before.char_class, before.location, before.hp,
                    before.max_hp, before.mp, before.gold, dict(before.stats),
                    dict(before.progress), dict(before.inventory),
                    dict(before.equipped))

    with Store(path) as store:
        second = Engine(world, store=store)
        after = second.sim.players["u1"]
        assert (after.name, after.char_class, after.location, after.hp,
                after.max_hp, after.mp, after.gold, dict(after.stats),
                dict(after.progress), dict(after.inventory),
                dict(after.equipped)) == snapshot
        assert second.restored == []


def test_partial_track_progress_is_not_lost(world, tmp_path):
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        engine = Engine(world, seed=7, store=store)
        engine.register("u1", "Brynn", "Warrior")
        engine.command("u1", "travel north")
        engine.command("u1", "attack wolf")
        assert engine.sim.players["u1"].progress["str"] == 1

    with Store(path) as store:
        engine = Engine(world, store=store)
        assert engine.sim.players["u1"].progress == {"str": 1, "max_hp": 1}


def test_wounded_monsters_and_contributors_survive_a_restart(world, tmp_path):
    """The original lost this on every restart; keeping it is deliberate."""
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        engine = Engine(world, seed=7, store=store)
        engine.register("u1", "Brynn", "Warrior")
        engine.command("u1", "travel north")
        engine.command("u1", "attack wolf")

    with Store(path) as store:
        engine = Engine(world, store=store)
        wolf = engine.sim.rooms["Whispering Woods"]["Dire Wolf"]
        assert wolf.hp == 10
        assert wolf.contributors == ["u1"]


def test_a_duel_survives_a_restart_but_a_challenge_does_not(world, tmp_path):
    """A duel is ongoing; a sixty-second challenge is stale by definition."""
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        engine = Engine(world, seed=7, store=store)
        engine.register("u1", "Brynn", "Warrior")
        engine.register("u2", "Selene", "Mage")
        engine.register("u3", "Nia", "Rogue")
        #  The challenge has to predate the duel: the game refuses a challenge
        #  against someone already dueling.
        engine.command("u3", "duel @u1")
        engine.command("u1", "duel @u2")
        engine.command("u2", "accept")
        assert len(engine.sim.offers) == 1

    with Store(path) as store:
        engine = Engine(world, store=store)
        duel = engine.sim.duel_of("u1")
        assert duel is not None and duel.other("u1") == "u2"
        assert duel.turn == "u1"
        assert engine.sim.offers == []


def test_renaming_an_item_keeps_the_save_when_the_id_is_pinned(world, tmp_path):
    """The hazard the brief warns about, made harmless by a stable id."""
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        engine = Engine(world, seed=7, store=store)
        engine.register("u1", "Brynn", "Warrior")
        assert engine.sim.players["u1"].equipped["weapon"] == "Iron Sword"

    #  In-source references move with the rename -- that is what lint is for.
    #  The save does not, because it keys on the pinned id.
    renamed = tmp_path / "renamed.md"
    renamed.write_text(WORLD.read_text()
                       .replace('item "Iron Sword" is a weapon:',
                                'item "Rusted Longsword" is a weapon:\n  id iron_sword')
                       .replace('starts with "Iron Sword"',
                                'starts with "Rusted Longsword"'))
    report = check(renamed)
    assert report.ok, [d.message for d in report.errors]

    with Store(path) as store:
        engine = Engine(report.world, store=store)
        assert engine.sim.players["u1"].equipped["weapon"] == "Rusted Longsword"
        assert engine.restored == []


def test_a_save_naming_something_gone_is_reported_not_crashed(world, tmp_path):
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        engine = Engine(world, seed=7, store=store)
        engine.register("u1", "Brynn", "Warrior")
        engine.sim.players["u1"].give("Wolf Pelt", 1)
        store.save(engine.sim)

    trimmed = tmp_path / "trimmed.md"
    trimmed.write_text(WORLD.read_text().replace(
        'item "Wolf Pelt" is a trophy:\n  "Still faintly warm."\n', ""))
    report = check(trimmed)

    with Store(path) as store:
        engine = Engine(report.world, store=store)
        assert engine.restored == ["item `wolf_pelt`"]
        assert "u1" in engine.sim.players, "the character still loads"


# --------------------------------------------------------- session state

def test_session_state_saves_and_reads_back(db):
    db.save_state("  Built the store; next is the UCI config CLI.  ")
    latest = db.latest_state()
    assert latest.summary == "Built the store; next is the UCI config CLI."
    assert latest.at


def test_session_state_keeps_a_history_newest_first(db):
    for note in ("first", "second", "third"):
        db.save_state(note)
    assert [e.summary for e in db.state(2)] == ["third", "second"]
    assert db.latest_state().summary == "third"


def test_no_session_state_yet(db):
    assert db.latest_state() is None
    assert db.state(5) == []


def test_play_is_not_logged(world, db):
    """Git is the record of change; play writes no project log."""
    engine = Engine(world, seed=7, store=db)
    engine.register("u1", "Brynn", "Warrior")
    engine.command("u1", "look")
    assert db.latest_state() is None
    tables = {row["name"] for row in db.db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "log" not in tables


def test_an_older_file_is_migrated(tmp_path):
    """Schema 1 kept event and discard streams; only session state survives."""
    path = tmp_path / "old.db"
    import sqlite3

    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
            channel TEXT NOT NULL, subject TEXT, message TEXT NOT NULL,
            data TEXT);
        INSERT INTO log (at, channel, subject, message) VALUES
            ('2026-10-01T00:00:00+00:00', 'session', NULL, 'the first session'),
            ('2026-10-02T00:00:00+00:00', 'discard', 'Evennia', 'too heavy'),
            ('2026-10-02T00:00:01+00:00', 'event', 'u1', 'Brynn: attack'),
            ('2026-10-03T00:00:00+00:00', 'session', NULL, 'the second session');
    """)
    old.commit()
    old.close()

    with Store(path) as store:
        assert [e.summary for e in store.state(5)] == [
            "the second session", "the first session"]
        tables = {row["name"] for row in store.db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "log" not in tables
        version = store.db.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        assert version["value"] == "3"


def test_opening_an_existing_file_is_safe(tmp_path):
    path = tmp_path / "gamebot.db"
    with Store(path) as store:
        store.save_state("first")
    with Store(path) as store:
        store.save_state("second")
        assert len(store.state(5)) == 2


def test_a_schema_two_file_drops_offers_and_the_counted_clock(tmp_path):
    path = tmp_path / "old.db"
    import sqlite3

    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('clock', '1234.5');
        CREATE TABLE offer (
            kind TEXT NOT NULL, challenger TEXT NOT NULL, target TEXT NOT NULL,
            expires_at REAL NOT NULL, PRIMARY KEY (kind, challenger, target));
        INSERT INTO offer VALUES ('duel', 'u1', 'u2', 60.0);
    """)
    old.commit()
    old.close()

    with Store(path) as store:
        tables = {row["name"] for row in store.db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "offer" not in tables
        assert store.db.execute(
            "SELECT 1 FROM meta WHERE key = 'clock'").fetchone() is None
