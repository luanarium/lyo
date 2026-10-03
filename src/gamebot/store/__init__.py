"""sqlite3 persistence for characters, live simulation, and logs."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from gamebot.engine.state import Duel, Monster, Offer, Player, Sim
from gamebot.lang.model import World

SCHEMA_VERSION = "1"
DEFAULT_PATH = Path("gamebot.db")

EVENT = "event"
SESSION = "session"
DISCARD = "discard"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Entry:
    """One row of the log."""

    id: int
    at: str
    channel: str
    subject: str | None
    message: str
    data: dict[str, Any]


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
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,))

    # --------------------------------------------------------------- logs

    def log(self, channel: str, message: str, *, subject: str | None = None,
            **data: Any) -> int:
        cursor = self.db.execute(
            "INSERT INTO log (at, channel, subject, message, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (now(), channel, subject, message,
             json.dumps(data, default=str) if data else None))
        return int(cursor.lastrowid)

    def entries(self, channel: str | None = None, *, limit: int = 50,
                subject: str | None = None, since: str | None = None
                ) -> list[Entry]:
        clauses, values = [], []
        if channel:
            clauses.append("channel = ?")
            values.append(channel)
        if subject:
            clauses.append("subject = ?")
            values.append(subject)
        if since:
            clauses.append("at >= ?")
            values.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.execute(
            f"SELECT * FROM log {where} ORDER BY id DESC LIMIT ?",
            (*values, limit)).fetchall()
        return [self._entry(row) for row in rows]

    def latest(self, channel: str) -> Entry | None:
        found = self.entries(channel, limit=1)
        return found[0] if found else None

    @staticmethod
    def _entry(row: sqlite3.Row) -> Entry:
        return Entry(id=row["id"], at=row["at"], channel=row["channel"],
                     subject=row["subject"], message=row["message"],
                     data=json.loads(row["data"]) if row["data"] else {})

    def channels(self) -> list[tuple[str, int]]:
        rows = self.db.execute(
            "SELECT channel, COUNT(*) AS n FROM log GROUP BY channel "
            "ORDER BY channel").fetchall()
        return [(row["channel"], row["n"]) for row in rows]

    # ---------------------------------------------------------- snapshot

    def save(self, sim: Sim) -> None:
        """Write the whole simulation. It is small, so there are no deltas."""
        world = sim.world
        items = {decl.name: decl.id for decl in world.items.values()}
        locations = {decl.name: decl.id for decl in world.locations.values()}
        classes = {decl.name: decl.id for decl in world.classes.values()}
        monsters = {decl.name: decl.id for decl in world.monsters.values()}

        with self.db:
            self.db.execute("BEGIN")
            known = {row["user_id"]: row["created_at"] for row in
                     self.db.execute("SELECT user_id, created_at FROM player")}
            self.db.execute("DELETE FROM player")
            for player in sim.players.values():
                self._save_player(player, known, items, locations, classes)

            self.db.execute("DELETE FROM monster_state")
            self.db.execute("DELETE FROM monster_contributor")
            for location, room in sim.rooms.items():
                location_id = locations.get(location, location)
                for name, monster in room.items():
                    monster_id = monsters.get(name, name)
                    self.db.execute(
                        "INSERT INTO monster_state (location_id, monster_id, hp) "
                        "VALUES (?, ?, ?)", (location_id, monster_id, monster.hp))
                    for ordinal, user_id in enumerate(monster.contributors):
                        self.db.execute(
                            "INSERT INTO monster_contributor "
                            "(location_id, monster_id, user_id, ordinal) "
                            "VALUES (?, ?, ?, ?)",
                            (location_id, monster_id, user_id, ordinal))

            self.db.execute("DELETE FROM duel")
            for duel in sim.duels:
                self.db.execute(
                    "INSERT INTO duel (a, b, turn) VALUES (?, ?, ?)",
                    (duel.a, duel.b, duel.turn))

            self.db.execute("DELETE FROM offer")
            for offer in sim.offers:
                self.db.execute(
                    "INSERT INTO offer (kind, challenger, target, expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (offer.kind, offer.challenger, offer.target, offer.expires_at))

            self.db.execute(
                "INSERT INTO meta (key, value) VALUES ('clock', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(sim.now),))

    def _save_player(self, player: Player, known: dict[str, str],
                     items: dict[str, str], locations: dict[str, str],
                     classes: dict[str, str]) -> None:
        stamp = now()
        self.db.execute(
            "INSERT INTO player (user_id, name, class_id, location_id, hp, "
            "max_hp, mp, max_mp, gold, created_at, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (player.user_id, player.name,
             classes.get(player.char_class, player.char_class),
             locations.get(player.location, player.location),
             player.hp, player.max_hp, player.mp, player.max_mp, player.gold,
             known.get(player.user_id, stamp), stamp))

        for stat, value in player.stats.items():
            self.db.execute(
                "INSERT INTO player_stat (user_id, stat, value) VALUES (?, ?, ?)",
                (player.user_id, stat, value))
        for track, value in player.progress.items():
            self.db.execute(
                "INSERT INTO player_progress (user_id, track, value) "
                "VALUES (?, ?, ?)", (player.user_id, track, value))
        for name, quantity in player.inventory.items():
            if quantity > 0:
                self.db.execute(
                    "INSERT INTO player_item (user_id, item_id, quantity) "
                    "VALUES (?, ?, ?)",
                    (player.user_id, items.get(name, name), quantity))
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
        for row in self.db.execute("SELECT * FROM offer"):
            sim.offers.append(Offer(row["kind"], row["challenger"],
                                    row["target"], row["expires_at"]))

        clock = self.db.execute(
            "SELECT value FROM meta WHERE key = 'clock'").fetchone()
        if clock is not None:
            sim.now = float(clock["value"])

        return sorted(set(lost))

    def characters(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS n FROM player").fetchone()
        return int(row["n"])
