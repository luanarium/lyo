-- The project's sqlite3 file: saved characters, live simulation, session
-- state, and configuration.
--
-- Everything a save refers to is an id declared in the game source, never a
-- display name, so renaming an item or a location does not orphan the
-- characters holding or standing in it.

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ----------------------------------------------------------- characters

CREATE TABLE IF NOT EXISTS player (
    user_id     TEXT PRIMARY KEY,
    name        TEXT    NOT NULL,
    class_id    TEXT    NOT NULL,
    location_id TEXT    NOT NULL,
    hp          INTEGER NOT NULL,
    max_hp      INTEGER NOT NULL,
    mp          INTEGER NOT NULL,
    max_mp      INTEGER NOT NULL,
    gold        INTEGER NOT NULL,
    created_at  TEXT    NOT NULL,
    seen_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS player_stat (
    user_id TEXT    NOT NULL REFERENCES player(user_id) ON DELETE CASCADE,
    stat    TEXT    NOT NULL,
    value   INTEGER NOT NULL,
    PRIMARY KEY (user_id, stat)
);

-- A track's value and its leftover progress are both kept: dropping the
-- leftover would silently steal partial progress.
CREATE TABLE IF NOT EXISTS player_progress (
    user_id TEXT    NOT NULL REFERENCES player(user_id) ON DELETE CASCADE,
    track   TEXT    NOT NULL,
    value   INTEGER NOT NULL,
    PRIMARY KEY (user_id, track)
);

CREATE TABLE IF NOT EXISTS player_item (
    user_id  TEXT    NOT NULL REFERENCES player(user_id) ON DELETE CASCADE,
    item_id  TEXT    NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS player_equipment (
    user_id TEXT NOT NULL REFERENCES player(user_id) ON DELETE CASCADE,
    slot    TEXT NOT NULL,
    item_id TEXT NOT NULL,
    PRIMARY KEY (user_id, slot)
);

-- ------------------------------------------------- live simulation state
--
-- The original lost all of this on restart. Keeping it means a party three
-- turns into a dragon does not lose the fight to a deploy.

CREATE TABLE IF NOT EXISTS monster_state (
    location_id TEXT    NOT NULL,
    monster_id  TEXT    NOT NULL,
    hp          INTEGER NOT NULL,
    PRIMARY KEY (location_id, monster_id)
);

CREATE TABLE IF NOT EXISTS monster_contributor (
    location_id TEXT    NOT NULL,
    monster_id  TEXT    NOT NULL,
    user_id     TEXT    NOT NULL,
    ordinal     INTEGER NOT NULL,
    PRIMARY KEY (location_id, monster_id, user_id)
);

CREATE TABLE IF NOT EXISTS duel (
    a    TEXT NOT NULL,
    b    TEXT NOT NULL,
    turn TEXT NOT NULL,
    PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS offer (
    kind       TEXT NOT NULL,
    challenger TEXT NOT NULL,
    target     TEXT NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY (kind, challenger, target)
);

-- --------------------------------------------------- session state
--
-- One brief paragraph per session, written only when asked. Git is the record
-- of what changed and why; this is the human-readable digest on top of it, so
-- there are deliberately no other project logs here.

CREATE TABLE IF NOT EXISTS session_state (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    summary TEXT NOT NULL
);

-- --------------------------------------------------------------- config
--
-- UCI shape: package.section.option. A staged value waits for a commit.

CREATE TABLE IF NOT EXISTS config (
    package   TEXT NOT NULL,
    section   TEXT NOT NULL,
    option    TEXT NOT NULL,
    value     TEXT,
    staged    TEXT,
    PRIMARY KEY (package, section, option)
);
