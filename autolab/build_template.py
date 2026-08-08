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
    # v58 split the rotation affordability floor into three tiers: defending the
    # core, hitting some other turret, and everything else.
    "ROT_FLOOR_DEF": (35,   0, 200, "int",  "attack"),
    "ROT_FLOOR_GUN": (50,   0, 250, "int",  "attack"),
    "ROT_FLOOR":     (85,   0, 300, "int",  "attack"),
    "RAY_FIRST":     (0,    0,   1, "bool", "attack"),
    # SEAT_FALLBACK: when every candidate seat exceeds SEAT_COV_MAX, take the
    # least-covered one anyway instead of returning None. Ladder evidence
    # 2026-08-07 (match_autopsy over 30 games): in every game we lost we landed
    # 0-1 seats on their core while they landed 4-10; in every game we won it
    # was the reverse. A defended core covers all of its ring tiles, the filter
    # empties, findGunnerSpot returns None, and the attacker marches into the
    # coverage it just refused to build in.
    "SEAT_FALLBACK": (0,    0,   1, "bool", "attack"),
    # COUNTER_BATTERY: when no core seat exists at all, shoot the thing that is
    # denying it instead of walking into its fire. Same ladder evidence as
    # SEAT_FALLBACK, opposite remedy - that one takes a bad seat, this one
    # removes the reason the seat is bad. Reuses the chassis' own
    # buildGunnerFor(), which the eco/defence path already uses to answer a
    # turret, so it is the chassis' placement logic and not a new one.
    "COUNTER_BATTERY": (0,  0,   1, "bool", "attack"),
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
    # attack: titanium gates. v58 dropped the "too poor -> just march" early
    # return, so SEAT_TI now has a single call site.
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
    # attack: no seat -> kill the turret denying it (COUNTER_BATTERY)
    (b"                gunnerStuff = self.findGunnerSpot(ct)\r\n"
     b"                if gunnerStuff:\r\n",
     b"                gunnerStuff = self.findGunnerSpot(ct)\r\n"
     b'                if KNOBS["COUNTER_BATTERY"] and not gunnerStuff:\r\n'
     b"                    denier = None\r\n"
     b"                    denierDist = None\r\n"
     b"                    for b in ct.get_nearby_buildings():\r\n"
     b"                        if ct.get_team(b) == ct.get_team():\r\n"
     b"                            continue\r\n"
     b"                        if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):\r\n"
     b"                            continue\r\n"
     b"                        bPos = ct.get_position(b)\r\n"
     b"                        d = myLoc.distance_squared(bPos)\r\n"
     b"                        if denierDist is None or d < denierDist:\r\n"
     b"                            denierDist = d\r\n"
     b"                            denier = bPos\r\n"
     b"                    if denier is not None and self.buildGunnerFor(ct, denier):\r\n"
     b"                        return\r\n"
     b"                if gunnerStuff:\r\n"),
    # attack: least-bad seat instead of NO seat (SEAT_FALLBACK)
    # Every added line sits behind a knob test so that at the default it folds
    # to `if 0:` and verify_template can still prove byte-identity with the
    # chassis. The names only exist when the knob is on, and every use of them
    # is behind the same test.
    (b"        bestAttacker = None\r\n"
     b"        bestScore = None\r\n"
     b"        myLoc = ct.get_position()\r\n",
     b"        bestAttacker = None\r\n"
     b"        bestScore = None\r\n"
     b'        if KNOBS["SEAT_FALLBACK"]:\r\n'
     b"            fbAttacker = None\r\n"
     b"            fbScore = None\r\n"
     b"        myLoc = ct.get_position()\r\n"),
    (b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b'            if seatCov > KNOBS["SEAT_COV_MAX"]:\r\n'
     b"                continue\r\n"
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))",
     b"            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)\r\n"
     b'            if seatCov > KNOBS["SEAT_COV_MAX"]:\r\n'
     b'                if KNOBS["SEAT_FALLBACK"]:\r\n'
     b"                    fb = (seatCov, myLoc.distance_squared(spotPos),\r\n"
     b"                          spotPos.distance_squared(enemyCore))\r\n"
     b"                    if fbScore is None or fb < fbScore:\r\n"
     b"                        fbScore = fb\r\n"
     b"                        fbAttacker = (spotPos, spotDir)\r\n"
     b"                continue\r\n"
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))"),
    (b"                bestAttacker = (spotPos, spotDir)\r\n"
     b"        return bestAttacker\r\n",
     b"                bestAttacker = (spotPos, spotDir)\r\n"
     b'        if KNOBS["SEAT_FALLBACK"] and bestAttacker is None:\r\n'
     b"            return fbAttacker\r\n"
     b"        return bestAttacker\r\n"),
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
    (b"                floor = 35\r\n"
     b"            elif gunnerHits > 0:\r\n"
     b"                floor = 50\r\n"
     b"            else:\r\n"
     b"                floor = 85\r\n",
     b'                floor = KNOBS["ROT_FLOOR_DEF"]\r\n'
     b"            elif gunnerHits > 0:\r\n"
     b'                floor = KNOBS["ROT_FLOOR_GUN"]\r\n'
     b"            else:\r\n"
     b'                floor = KNOBS["ROT_FLOOR"]\r\n'),
]


def build(chassis="OogwayAttack"):
    src = ROOT / "bots" / chassis
    if not (src / "main.py").is_file():
        raise SystemExit(f"no chassis at bots/{chassis}/main.py")
    if TEMPLATE.exists():
        shutil.rmtree(TEMPLATE)
    shutil.copytree(src, TEMPLATE, ignore=shutil.ignore_patterns("__pycache__"))

    p = TEMPLATE / "main.py"
    # Normalise to CRLF first. Chassis files reach us by two routes with two
    # conventions - git checkouts are CRLF here, bots unzipped from a platform
    # submission are LF - and the anchors below are written with \r\n, so an LF
    # chassis would fail every multi-line anchor for a reason that has nothing
    # to do with the code having changed.
    b = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
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
