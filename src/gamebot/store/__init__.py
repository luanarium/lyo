"""sqlite3 persistence for characters, live simulation, and logs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

from gamebot.engine.state import Duel, Player, Sim

SCHEMA_VERSION = "4"
DEFAULT_PATH = Path("gamebot.db")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SessionState:
    """One session's digest."""

    id: int
    at: str
    summary: str


class Store:
    """The project's sqlite3 file."""

    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _migrate(self) -> None:
        sql = (files("gamebot.store") / "schema.sql").read_text(encoding="utf-8")
        self.db.executescript(sql)
        self._migrate_legacy()
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,))

    def _migrate_legacy(self) -> None:
        present = {row["name"] for row in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}

        #  Schema 1 kept event and discard streams. Git is that record.
        if "log" in present:
            self.db.execute(
                "INSERT INTO session_state (at, summary) "
                "SELECT at, message FROM log WHERE channel = 'session' "
                "ORDER BY id")
            self.db.execute("DROP TABLE log")

        #  Schema 2 stored challenge deadlines and a counted clock. Both are
        #  meaningless once the clock reads real elapsed time, and a
        #  sixty-second challenge has no business surviving a restart.
        if "offer" in present:
            self.db.execute("DROP TABLE offer")
        self.db.execute("DELETE FROM meta WHERE key = 'clock'")

        #  Schema 4 distinguishes a staged value from a staged removal.
        columns = {row["name"] for row in
                   self.db.execute("PRAGMA table_info(config)")}
        if columns and "staged_op" not in columns:
            self.db.execute("ALTER TABLE config ADD COLUMN staged_op TEXT")
            self.db.execute(
                "UPDATE config SET staged_op = 'set' WHERE staged IS NOT NULL")

    @property
    def config(self) -> "Config":
        from gamebot.store.config import Config

        return Config(self.db)

    # ------------------------------------------------------- session state

    def save_state(self, summary: str) -> int:
        cursor = self.db.execute(
            "INSERT INTO session_state (at, summary) VALUES (?, ?)",
            (now(), summary.strip()))
        return int(cursor.lastrowid)

    def state(self, limit: int = 1) -> list[SessionState]:
        rows = self.db.execute(
            "SELECT * FROM session_state ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [SessionState(r["id"], r["at"], r["summary"]) for r in rows]

    def latest_state(self) -> SessionState | None:
        found = self.state(1)
        return found[0] if found else None

    # ---------------------------------------------------------- snapshot

    def save(self, sim: Sim) -> None:
        """Write the whole simulation. It is small, so there are no deltas.

        Rows are upserted rather than deleted and rebuilt: a wholesale rebuild
        silently resets any column it does not restate, which `created_at`
        already had to work around by hand.
        """
        world = sim.world
        items = {decl.name: decl.id for decl in world.items.values()}
        locations = {decl.name: decl.id for decl in world.locations.values()}
        classes = {decl.name: decl.id for decl in world.classes.values()}
        monsters = {decl.name: decl.id for decl in world.monsters.values()}

        with self.db:
            self.db.execute("BEGIN")
            for player in sim.players.values():
                self._save_player(player, items, locations, classes)
            self._prune("player", "user_id", sim.players)

            for location, room in sim.rooms.items():
                location_id = locations.get(location, location)
                for name, monster in room.items():
                    self._save_monster(location_id, monsters.get(name, name),
                                       monster)

            self.db.execute("DELETE FROM duel")
            for duel in sim.duels:
                self.db.execute(
                    "INSERT INTO duel (a, b, turn) VALUES (?, ?, ?)",
                    (duel.a, duel.b, duel.turn))

    def _prune(self, table: str, key: str, keep) -> None:
        """Drop rows for anything no longer in the simulation."""
        kept = list(keep)
        if not kept:
            self.db.execute(f"DELETE FROM {table}")
            return
        marks = ", ".join("?" * len(kept))
        self.db.execute(f"DELETE FROM {table} WHERE {key} NOT IN ({marks})", kept)

    def _save_monster(self, location_id: str, monster_id: str,
                      monster) -> None:
        self.db.execute(
            "INSERT INTO monster_state (location_id, monster_id, hp) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (location_id, monster_id) DO UPDATE SET hp = excluded.hp",
            (location_id, monster_id, monster.hp))
        self.db.execute(
            "DELETE FROM monster_contributor "
            "WHERE location_id = ? AND monster_id = ?",
            (location_id, monster_id))
        for ordinal, user_id in enumerate(monster.contributors):
            self.db.execute(
                "INSERT INTO monster_contributor "
                "(location_id, monster_id, user_id, ordinal) VALUES (?, ?, ?, ?)",
                (location_id, monster_id, user_id, ordinal))

    def _save_player(self, player: Player, items: dict[str, str],
                     locations: dict[str, str], classes: dict[str, str]) -> None:
        #  created_at is written once and never restated, so it cannot be lost.
        self.db.execute(
            "INSERT INTO player (user_id, name, class_id, location_id, hp, "
            "max_hp, mp, max_mp, gold, created_at, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "  name = excluded.name, class_id = excluded.class_id, "
            "  location_id = excluded.location_id, hp = excluded.hp, "
            "  max_hp = excluded.max_hp, mp = excluded.mp, "
            "  max_mp = excluded.max_mp, gold = excluded.gold, "
            "  seen_at = excluded.seen_at",
            (player.user_id, player.name,
             classes.get(player.char_class, player.char_class),
             locations.get(player.location, player.location),
             player.hp, player.max_hp, player.mp, player.max_mp, player.gold,
             now(), now()))

        #  These are plain key/value sets with no columns of their own, so
        #  rebuilding them per player is safe and keeps removals correct.
        for table, column, rows in (
            ("player_stat", "stat", player.stats.items()),
            ("player_progress", "track", player.progress.items()),
        ):
            self.db.execute(f"DELETE FROM {table} WHERE user_id = ?",
                            (player.user_id,))
            for name, value in rows:
                self.db.execute(
                    f"INSERT INTO {table} (user_id, {column}, value) "
                    f"VALUES (?, ?, ?)", (player.user_id, name, value))

        self.db.execute("DELETE FROM player_item WHERE user_id = ?",
                        (player.user_id,))
        for name, quantity in player.inventory.items():
            if quantity > 0:
                self.db.execute(
                    "INSERT INTO player_item (user_id, item_id, quantity) "
                    "VALUES (?, ?, ?)",
                    (player.user_id, items.get(name, name), quantity))

        self.db.execute("DELETE FROM player_equipment WHERE user_id = ?",
                        (player.user_id,))
        for slot, name in player.equipped.items():
            if name:
                self.db.execute(
                    "INSERT INTO player_equipment (user_id, slot, item_id) "
                    "VALUES (?, ?, ?)",
                    (player.user_id, slot, items.get(name, name)))

    # ------------------------------------------------------------- restore

    def load(self, sim: Sim) -> list[str]:
        """Restore into a fresh simulation. Returns anything that no longer exists."""
        world = sim.world
        items = {decl.id: decl.name for decl in world.items.values()}
        locations = {decl.id: decl.name for decl in world.locations.values()}
        classes = {decl.id: decl.name for decl in world.classes.values()}
        monsters = {decl.id: decl.name for decl in world.monsters.values()}
        lost: list[str] = []

        def name_of(table: dict[str, str], key: str, kind: str) -> str | None:
            if key in table:
                return table[key]
            lost.append(f"{kind} `{key}`")
            return None

        for row in self.db.execute("SELECT * FROM player"):
            location = name_of(locations, row["location_id"], "location")
            char_class = name_of(classes, row["class_id"], "class")
            if location is None or char_class is None:
                continue
            player = Player(
                user_id=row["user_id"], name=row["name"], char_class=char_class,
                location=location, hp=row["hp"], max_hp=row["max_hp"],
                mp=row["mp"], max_mp=row["max_mp"], gold=row["gold"])
            sim.players[player.user_id] = player

        for row in self.db.execute("SELECT * FROM player_stat"):
            if row["user_id"] in sim.players:
                sim.players[row["user_id"]].stats[row["stat"]] = row["value"]
        for row in self.db.execute("SELECT * FROM player_progress"):
            if row["user_id"] in sim.players:
                sim.players[row["user_id"]].progress[row["track"]] = row["value"]
        for row in self.db.execute("SELECT * FROM player_item"):
            player = sim.players.get(row["user_id"])
            name = name_of(items, row["item_id"], "item")
            if player is not None and name is not None:
                player.inventory[name] = row["quantity"]
        for row in self.db.execute("SELECT * FROM player_equipment"):
            player = sim.players.get(row["user_id"])
            name = name_of(items, row["item_id"], "item")
            if player is not None and name is not None:
                player.equipped[row["slot"]] = name

        for row in self.db.execute("SELECT * FROM monster_state"):
            location = locations.get(row["location_id"])
            monster = monsters.get(row["monster_id"])
            if location is None or monster is None:
                lost.append(f"monster `{row['monster_id']}`")
                continue
            live = sim.rooms.get(location, {}).get(monster)
            if live is not None:
                live.hp = min(row["hp"], live.max_hp)

        for row in self.db.execute(
                "SELECT * FROM monster_contributor ORDER BY ordinal"):
            location = locations.get(row["location_id"])
            monster = monsters.get(row["monster_id"])
            live = sim.rooms.get(location or "", {}).get(monster or "")
            if live is not None:
                live.damaged_by(row["user_id"])

        for row in self.db.execute("SELECT * FROM duel"):
            if row["a"] in sim.players and row["b"] in sim.players:
                sim.duels.append(Duel(row["a"], row["b"], row["turn"]))
        #  Pending challenges are deliberately not restored: they last sixty
        #  seconds, so one that outlived a restart is already stale.

        return sorted(set(lost))

    def characters(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS n FROM player").fetchone()
        return int(row["n"])
