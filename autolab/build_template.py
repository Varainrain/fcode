"""Generate the knobbed template bot from whatever chassis is current.

The pipeline never edits a bot by hand. It takes the chassis (default
`bots/OogwayAttack`), applies a fixed list of ANCHORED replacements that lift
hardcoded literals into a single `KNOBS` dict, and writes `bots/_template/`.
Every anchor is asserted, so if Oogway pushes a chassis where a line moved, this
fails loudly instead of silently producing a bot that ignores half the knobs.

Re-run it after every chassis update:

    python -m autolab.build_template            # from bots/OogwayAttack
    python -m autolab.build_template OogwayNEW  # from some other chassis

Then prove the template is behaviour-identical to its parent before trusting any
search result built on it:

    python -m autolab.verify_template
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "bots" / "_template"

# name -> (default, low, high, kind, lane)
#   kind: "int" | "bool"
#   lane: "attack" owned by oni; "core"/"econ" belong to other owners and are
#         excluded from the default search space (MODULES.md ownership).
KNOB_SPEC = {
    "SEAT_TI":       (96,  20, 260, "int",  "attack"),
    "HARASS_TI":     (30,  10, 200, "int",  "attack"),
    "SEAT_COV_MAX":  (1,    0,   3, "int",  "attack"),
    "ATTACK_MOD":    (3,    2,   5, "int",  "attack"),
    "ROT_FLOOR_DEF": (20,   0, 200, "int",  "attack"),
    "ROT_FLOOR":     (80,   0, 300, "int",  "attack"),
    "RAY_FIRST":     (0,    0,   1, "bool", "attack"),
    "AMMO_CEIL":     (16,   8, 120, "int",  "core"),
    "AMMO_RESERVE":  (28,   0, 120, "int",  "core"),
    "SPAWN_MIN":     (5,    2,  10, "int",  "econ"),
    "SPAWN_TI":      (360, 80, 600, "int",  "econ"),
}

KNOB_LINE = "KNOBS = {" + ", ".join(
    '"%s": %d' % (k, v[0]) for k, v in KNOB_SPEC.items()) + "}"

# (anchor, replacement) applied to main.py, in order. Anchors are byte-exact and
# each must appear exactly once.
MAIN_SUBS = [
    # the KNOBS dict itself, injected right after the CARDINALS definition
    (b"CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]",
     b"CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]\r\n"
     + KNOB_LINE.encode() + b"  # autolab"),
    # core: spawn policy
    (b"if self.numSpawned < 5 or globalTitanium > 360:",
     b'if self.numSpawned < KNOBS["SPAWN_MIN"] or globalTitanium > KNOBS["SPAWN_TI"]:'),
    # core: ammo conversion ceiling and reserve
    (b"convertAmount = min(16 - globalAmmo, globalTitanium - 28)",
     b'convertAmount = min(KNOBS["AMMO_CEIL"] - globalAmmo, globalTitanium - KNOBS["AMMO_RESERVE"])'),
    # role split - both sites must agree
    (b"if nextNum % 3 == 1 and nextNum not in (5, 7):",
     b'if nextNum % KNOBS["ATTACK_MOD"] == 1 and nextNum not in (5, 7):'),
    (b"if self.mapPf.myNum % 3 == 1 and self.mapPf.myNum not in (5, 7):",
     b'if self.mapPf.myNum % KNOBS["ATTACK_MOD"] == 1 and self.mapPf.myNum not in (5, 7):'),
    # attack: titanium gates
    (b"if ct.get_global_resources() < 96:",
     b'if ct.get_global_resources() < KNOBS["SEAT_TI"]:'),
    (b"if ct.get_global_resources() >= 30 and self.attackHarvesterWithGunner(ct):",
     b'if ct.get_global_resources() >= KNOBS["HARASS_TI"] and self.attackHarvesterWithGunner(ct):'),
    (b"if ct.get_global_resources() >= 96:",
     b'if ct.get_global_resources() >= KNOBS["SEAT_TI"]:'),
    # attack: seat coverage tolerance (two call sites, harass + core siege)
    (b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b"            if seatCov > 1:\r\n"
     b"                continue\r\n"
     b"            score = (seatCov, -spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))",
     b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b'            if seatCov > KNOBS["SEAT_COV_MAX"]:\r\n'
     b"                continue\r\n"
     b"            score = (seatCov, -spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))"),
    (b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b"            if seatCov > 1:\r\n"
     b"                continue\r\n"
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))",
     b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b'            if seatCov > KNOBS["SEAT_COV_MAX"]:\r\n'
     b"                continue\r\n"
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))"),
    # gunner: rotation ray scoring - RAY_FIRST reproduces gated candidate oa_a9
    (b"            for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):\r\n"
     b"                tileId = ct.get_tile_building_id(tile)\r\n"
     b"                if tileId is not None and ct.get_team(tileId) != myTeam:",
     b"            for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):\r\n"
     b'                if KNOBS["RAY_FIRST"] and ct.get_tile_builder_bot_id(tile) is not None:\r\n'
     b"                    break\r\n"
     b"                tileId = ct.get_tile_building_id(tile)\r\n"
     b'                if KNOBS["RAY_FIRST"] and tileId is not None and ct.get_team(tileId) == myTeam:\r\n'
     b"                    break\r\n"
     b"                if tileId is not None and ct.get_team(tileId) != myTeam:"),
    (b"                    else:\r\n"
     b"                        otherHits += 1\r\n",
     b"                    else:\r\n"
     b"                        otherHits += 1\r\n"
     b'                    if KNOBS["RAY_FIRST"]:\r\n'
     b"                        break\r\n"),
    # gunner: rotation affordability floors
    (b"floor = 20 if bestIsCoreDefense else 80",
     b'floor = KNOBS["ROT_FLOOR_DEF"] if bestIsCoreDefense else KNOBS["ROT_FLOOR"]'),
]


def build(chassis="OogwayAttack"):
    src = ROOT / "bots" / chassis
    if not (src / "main.py").is_file():
        raise SystemExit(f"no chassis at bots/{chassis}/main.py")
    if TEMPLATE.exists():
        shutil.rmtree(TEMPLATE)
    shutil.copytree(src, TEMPLATE, ignore=shutil.ignore_patterns("__pycache__"))

    p = TEMPLATE / "main.py"
    b = p.read_bytes()
    for i, (anchor, repl) in enumerate(MAIN_SUBS):
        n = b.count(anchor)
        if n != 1:
            raise SystemExit(
                f"anchor {i} matched {n} times, expected 1 - the chassis moved "
                f"under us. Fix autolab/build_template.py before searching.\n"
                f"  anchor: {anchor[:80]!r}")
        b = b.replace(anchor, repl, 1)
    p.write_bytes(b)
    (TEMPLATE / "AUTOLAB_TEMPLATE").write_text(
        f"generated from bots/{chassis} by autolab.build_template\n")
    print(f"built bots/_template from bots/{chassis} "
          f"({len(MAIN_SUBS)} anchors, {len(KNOB_SPEC)} knobs)")
    return TEMPLATE


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "OogwayAttack")
