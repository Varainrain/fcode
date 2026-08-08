"""SQLite store for the autolab pipeline. Every game ever played lives here.

One file, `autolab/lab.db`. The runner writes; the dashboard only reads (plus
the `control` table, which is how the dashboard asks the runner to do things).
"""
import json
import sqlite3
import time
from math import sqrt
from pathlib import Path

DB = Path(__file__).resolve().parent / "lab.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS variants (
    name      TEXT PRIMARY KEY,
    knobs     TEXT NOT NULL,
    role      TEXT NOT NULL,          -- champion | null | candidate
    status    TEXT NOT NULL,          -- active | rejected | promoted | retired
    parent    TEXT,
    note      TEXT,
    external  INTEGER NOT NULL DEFAULT 0,   -- 1 = an existing bots/ folder, not a knob vector
    created   REAL NOT NULL,
    closed    REAL
);
CREATE TABLE IF NOT EXISTS games (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    variant   TEXT NOT NULL,
    opponent  TEXT NOT NULL,
    map       TEXT NOT NULL,
    seed      INTEGER NOT NULL,
    seat      TEXT NOT NULL,          -- A if the variant was listed first
    won       INTEGER NOT NULL,       -- 1/0; draws and crashes count as 0
    cond      TEXT,
    turns     INTEGER,
    margin    REAL NOT NULL DEFAULT 0,
    ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS games_variant ON games(variant);
CREATE TABLE IF NOT EXISTS events (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    REAL NOT NULL,
    kind  TEXT NOT NULL,
    text  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS control (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_CONTROL = {
    "paused": "0",
    "chassis": "OogwayAttack",      # the agreed chassis the template is lifted from
    "autopull": "0",                # 1 = `git pull --ff-only` before each chassis check
    "chassis_hash": "",             # last seen hash of the chassis sources
    "workers": "6",
    "lanes": "attack",              # comma list: attack,core,econ
    "min_prune": "60",              # games before a candidate can be killed
    "min_promote": "400",           # games before a candidate can be promoted
    "max_games": "800",             # games after which an undecided one retires
    "candidates": "3",              # candidates live at once
    "request": "",                  # one-shot command from the dashboard
    "heartbeat": "0",               # runner stamps this every cycle
}


def connect():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init():
    con = connect()
    con.executescript(SCHEMA)
    # CREATE TABLE IF NOT EXISTS does nothing to a table that already exists, so
    # columns added after a database was first created need an explicit migration.
    have = {r["name"] for r in con.execute("PRAGMA table_info(variants)")}
    if "external" not in have:
        con.execute("ALTER TABLE variants ADD COLUMN external INTEGER NOT NULL DEFAULT 0")
    gcols = {r["name"] for r in con.execute("PRAGMA table_info(games)")}
    if "margin" not in gcols:
        con.execute("ALTER TABLE games ADD COLUMN margin REAL NOT NULL DEFAULT 0")
    for k, v in DEFAULT_CONTROL.items():
        con.execute("INSERT OR IGNORE INTO control(key,value) VALUES(?,?)", (k, v))
    con.commit()
    return con


def get_control(con, key, default=None):
    row = con.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_control(con, key, value):
    con.execute("INSERT INTO control(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))
    con.commit()


def log(con, kind, text):
    con.execute("INSERT INTO events(ts,kind,text) VALUES(?,?,?)",
                (time.time(), kind, text))
    con.commit()


def add_variant(con, name, knobs, role, parent=None, note="", external=0):
    con.execute(
        "INSERT OR REPLACE INTO variants"
        "(name,knobs,role,status,parent,note,created,external)"
        " VALUES(?,?,?,'active',?,?,?,?)",
        (name, json.dumps(knobs, sort_keys=True), role, parent, note, time.time(),
         int(external)))
    con.commit()


def close_variant(con, name, status):
    con.execute("UPDATE variants SET status=?, closed=? WHERE name=?",
                (status, time.time(), name))
    con.commit()


def margin_of(won, cond, turns):
    """A continuous score in [-1, 1] for one game: sign is the result, size is
    decisiveness. Win/loss is one bit per game; a decisive core kill at t80 and
    a tiebreak scrape at t1000 carry very different information about strength,
    and throwing that away is why the binary signal needs ~400 games to say
    anything. Used ONLY to decide where to spend games - never to promote.
    """
    decisive = "destroy" in (cond or "").lower()
    if decisive:
        speed = max(0.0, (1000.0 - min(turns or 1000, 1000)) / 1000.0)
        mag = 0.2 + 0.8 * speed
    else:
        mag = 0.1                      # tiebreak: barely informative either way
    return mag if won else -mag


def record_game(con, variant, opponent, map_, seed, seat, won, cond, turns):
    con.execute(
        "INSERT INTO games(variant,opponent,map,seed,seat,won,cond,turns,margin,ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (variant, opponent, map_, seed, seat, int(won), cond, turns,
         margin_of(won, cond, turns), time.time()))
    con.commit()


def margin_stats(con, variant, opponent):
    """(mean, standard error, n) of this variant's per-game margin."""
    # margin != 0 excludes rows written before the column existed. margin_of()
    # never returns exactly 0 (a tiebreak is +-0.1), so this is an exact test for
    # "legacy row". Without it, legacy zeros drag every mean to 0 AND collapse
    # the standard error, which would put a near-zero denominator in the screen
    # and manufacture prunes out of nothing.
    rows = [r["margin"] for r in con.execute(
        "SELECT margin FROM games WHERE variant=? AND opponent=? AND margin != 0",
        (variant, opponent)).fetchall()]
    n = len(rows)
    if n < 2:
        return 0.0, 1.0, n
    mean = sum(rows) / n
    var = sum((x - mean) ** 2 for x in rows) / (n - 1)
    return mean, (var / n) ** 0.5, n


def tally(con, variant, opponent=None):
    """Wins/games for a variant, optionally only against one opponent.

    ALWAYS pass the current champion. A variant's row survives a chassis change
    but its old games are against a different bot, so an unqualified tally mixes
    eras: re-benching sub_v49 after the rebase counted its 402 games against the
    OLD champion and retired it at max_games before it played a single game
    against the new one.
    """
    if opponent:
        row = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(won),0) w FROM games"
            " WHERE variant=? AND opponent=?", (variant, opponent)).fetchone()
    else:
        row = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(won),0) w FROM games WHERE variant=?",
            (variant,)).fetchone()
    return row["w"], row["n"]


def wilson(w, n, z=1.96):
    """(point, low, high) as percentages. n=0 -> a band covering everything."""
    if not n:
        return 0.0, 0.0, 100.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * p, 100 * max(0.0, c - half), 100 * min(1.0, c + half)


def knobs_of(con, name):
    row = con.execute("SELECT knobs FROM variants WHERE name=?", (name,)).fetchone()
    return json.loads(row["knobs"]) if row else None


def champion(con):
    row = con.execute(
        "SELECT * FROM variants WHERE role='champion' AND status='active'"
        " ORDER BY created DESC LIMIT 1").fetchone()
    return row


def active(con, role):
    return con.execute(
        "SELECT * FROM variants WHERE role=? AND status='active' ORDER BY created",
        (role,)).fetchall()
