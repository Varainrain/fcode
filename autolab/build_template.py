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
    # SEAT_MAX_OWN: stop adding seats past N and tend the ones we have instead.
    # 0 = off (current behaviour). Grounded in the 2026-08-08 cost measurement:
    # a GUNNER is +20% scale, exactly as much as an extra builder, so the 5th
    # seat makes every future purchase ~2x. Healing an existing gun is 1 Ti per
    # 4 hp and adds nothing to the scale. This is also the first mechanism that
    # would explain the v85 bake-off's "guns past 3 rarely matter".
    "SEAT_MAX_OWN":  (0,    0,   6, "int",  "attack"),
    # SIEGE_SENTINEL: seat a SENTINEL instead of a gunner. 0 = off.
    # Ladder evidence 2026-08-08: across 10 games vs Clankers and team lazy the
    # correlation is exact - every game where they built a sentinel our core took
    # damage (504-1152), every game where they built none it took ZERO. They kill
    # us with sentinels; we have built zero sentinels in every game on record.
    # The 2.3.6 numbers say we have this backwards. Both turret types cost the
    # same +20% scale, which is the binding constraint, and per turret:
    #     gunner   20 Ti  7 dmg /1 turn = 7 DPS   25 hp  range r2 13
    #     sentinel 30 Ti 18 dmg /2 turns= 9 DPS   40 hp  range r2 32, ignores obstacles
    # Pantheon's postmortem calls gunners the better siege tool, but that was a
    # balance where a gunner did 10 dmg on a 1-turn reload (10 DPS). The 2.3.6
    # nerf (10->7 dmg, 40->25 hp, 10->20 Ti) inverted it and nobody re-tested.
    # The decisive part: two builders healing is 8 hp/turn, which fully negates a
    # 7-DPS gunner and does NOT stop a 9-DPS sentinel - and out-healing is exactly
    # what our 658-core-damage-and-still-lose games look like.
    # ⚠ A sentinel CANNOT ROTATE (rotate() is gunner-only), so the facing chosen
    # at build time is permanent.
    "SIEGE_SENTINEL": (0,   0,   1, "bool", "attack"),
    # SEAT_PREFER_CORE: score seats by closeness to the ENEMY CORE first, not to
    # the attacker. Ours picks the seat nearest ITSELF with distance-to-core as
    # the last tiebreak. Pantheon scored placements globally with "a step
    # discount [which] prioritizes placing gunners directly adjacent to targets".
    "SEAT_PREFER_CORE": (0, 0,   1, "bool", "attack"),
    # ATTACK_BUDDY: do not spend on a seat unless N friendly builders are within
    # vision. Pantheon only engaged when they "locally outnumber the threat"
    # (>=2 allies vs 1 enemy within range 25), and this repo measured the same
    # thing from the other side: krb2 removed the buddy-wait and scored 42% -
    # "the buddy-wait IS the wave; solo arrivals die piecemeal". 0 = off.
    "ATTACK_BUDDY":  (0,    0,   4, "int",  "attack"),
    # SIEGE_DENY_HEAL: barrier the tiles orthogonally adjacent to the ENEMY core.
    # Healing is orthogonal-adjacent only (1 Ti per 4 hp, no cooldown, and a
    # builder cannot move and heal in the same turn), so a 2x2 core can only be
    # healed from the 8 tiles touching it. Put OUR barrier on one and that heal
    # slot is gone - enemy units cannot pass our barriers.
    # This repo already proved the mechanic from the wrong side: krb3 sealed our
    # OWN ring and made our own core unhealable ("THE deep 2.3 fact of the
    # night", 29%). Nobody tried it offensively.
    # The cost law makes it nearly free: a barrier is 3 Ti at +1% scale, against
    # a gunner's +20%. Eight barriers cost less scale than half a gunner, and we
    # deal 658 core damage a game and still lose to healing.
    "SIEGE_DENY_HEAL": (0,  0,   1, "bool", "attack"),
    # SEAT_RAY_CLEAR: reject a seat whose line to the core is blocked by OUR OWN
    # buildings. Gunners "can only shoot the first target in range" and friendly
    # buildings absorb the shot, so a seat behind our own conveyor is a turret
    # that never fires. Measured on v58 with an instrumented copy: 468 of 821
    # gunner-turns (57%) had the gun aimed at our own conveyor or our own gunner.
    # The chassis already has rayBlockedByTeam() and buildGunnerFor() uses it -
    # findGunnerSpot, the siege path, never calls it. Pantheon solved this at
    # placement time too: a penalty for placements that would destroy an ally
    # conveyor, and never letting a new placement cut off an existing turret.
    "SEAT_RAY_CLEAR": (0,   0,   1, "bool", "attack"),
    # ROT_WEIGHTED + ROT_W_*: the gunner rotation scorer is a hardcoded
    # lexicographic tuple (coreHits, coreThreatHits, gunnerHits, otherHits), so
    # ONE core hit outranks any number of enemy guns, permanently. A core is 500
    # hp and a gunner 25, so that ordering is an untested assumption. With
    # ROT_WEIGHTED on, the tuple becomes a weighted sum and the weights become
    # searchable. Ray length caps each count at 3, so the defaults below
    # (1000/100/10/1) reproduce the lexicographic order exactly - the knob
    # changes the search space, not the default behaviour.
    "ROT_WEIGHTED":  (0,    0,    1, "bool", "attack"),
    "ROT_W_CORE":    (1000, 0, 2000, "int", "attack"),
    "ROT_W_THREAT":  (100,  0, 2000, "int", "attack"),
    "ROT_W_GUN":     (10,   0, 2000, "int", "attack"),
    "ROT_W_OTHER":   (1,    0, 2000, "int", "attack"),
    "AMMO_CEIL":     (16,   8, 120, "int",  "core"),
    "AMMO_RESERVE":  (28,   0, 120, "int",  "core"),
    "SPAWN_MIN":     (5,    2,  10, "int",  "econ"),
    "SPAWN_TI":      (360, 80, 600, "int",  "econ"),
    # SPAWN_ALLY_STEP / SPAWN_TI_HI: Pantheon's scale-aware spawn gate, from the
    # battlecode sources - "baseline = 400 if allies >= 12 else 200", i.e. the
    # titanium bar for spawning RISES as the roster grows. v58 spawns on a flat
    # bar while every unit is +20% scale, so late builders quietly double the
    # price of everything. 0 = off (flat bar, current behaviour).
    "SPAWN_ALLY_STEP": (0,  0,  20, "int",  "econ"),
    "SPAWN_TI_HI":   (500, 80, 900, "int",  "econ"),
    # --- pathfinding (chassis file; flagged to Oogway, measured here) ---
    # PF_SETTLE: finish the A* fill so every cardinal neighbour of the bot is
    # settled before stepping. Measured 2.6% of fills exit with an unsettled
    # neighbour, i.e. an upper bound the greedy step may act on.
    "PF_SETTLE":     (0,    0,   1, "bool", "path"),
    # PF_UNSEEN_COST: cost charged for a tile outside vision. 0 = off (assume
    # clear, cost 1). Khaos treated unseen tiles as impassable instead.
    "PF_UNSEEN_COST": (0,   0, 200, "int",  "path"),
}

KNOB_LINE = "KNOBS = {" + ", ".join(
    '"%s": %d' % (k, v[0]) for k, v in KNOB_SPEC.items()) + "}"

# --- mapPathfinding.py substitutions -----------------------------------------
# Reviewed against the sources 2026-08-08. Both defects are real; both are
# guarded so the default folds back to the chassis byte-for-byte.
PF_SUBS = [
    (b"CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]",
     b"CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]\r\n"
     + KNOB_LINE.encode() + b"  # autolab"),
    # PF_UNSEEN_COST: tiles outside vision are assumed to be clear terrain at
    # cost 1. Pantheon's Khaos treated unseen tiles as IMPASSABLE and filled the
    # map in via symmetry broadcast instead, so units never route through
    # corridors that may not exist. 0 = off (optimistic, current behaviour).
    (b"        if dx * dx + dy * dy > 20: # outside vision: assume clear terrain\r\n"
     b"            return openCost\r\n",
     b"        if dx * dx + dy * dy > 20: # outside vision: assume clear terrain\r\n"
     b'            if KNOBS["PF_UNSEEN_COST"]:\r\n'
     b'                return KNOBS["PF_UNSEEN_COST"]\r\n'
     b"            return openCost\r\n"),
    # PF_SETTLE: the A* fill early-exits the moment it POPS the bot's own tile,
    # but that only settles that tile - the neighbours it then compares may be
    # relaxed upper bounds, so the greedy step can pick the wrong direction.
    # Measured: 2.6% of fills (24 of 917) exit with an unsettled neighbour.
    # With this on, the fill keeps going until every cardinal neighbour of the
    # bot has been popped, which is what a full reverse Dijkstra guarantees.
    (b"        self.fillCount += 1\r\n",
     b'        if KNOBS["PF_SETTLE"]:\r\n'
     b"            _hit = None\r\n"
     b"            _neigh = set()\r\n"
     b"        self.fillCount += 1\r\n"),
    (b"            if cx == mx and cy == my:\r\n"
     b"                return g\r\n",
     b'            if KNOBS["PF_SETTLE"]:\r\n'
     b"                _neigh.discard((cx, cy))\r\n"
     b"                if cx == mx and cy == my:\r\n"
     b"                    _hit = g\r\n"
     b"                    for _dx, _dy in cardDeltas:\r\n"
     b"                        _nx, _ny = mx + _dx, my + _dy\r\n"
     b"                        if 0 <= _nx < w and 0 <= _ny < h and distStamp[_nx][_ny] == fill:\r\n"
     b"                            _neigh.add((_nx, _ny))\r\n"
     b"                if _hit is not None and not _neigh:\r\n"
     b"                    return _hit\r\n"
     b"            if cx == mx and cy == my:\r\n"
     b"                return g\r\n"),
]

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
    # core: scale-aware spawn bar (Pantheon precedent). Guarded so it folds to
    # `if 0 and ...:` at the default and the template still verifies.
    (b"            if spawnableTiles:\r\n",
     b'            if KNOBS["SPAWN_ALLY_STEP"] and ct.get_unit_count() >= KNOBS["SPAWN_ALLY_STEP"] and globalTitanium <= KNOBS["SPAWN_TI_HI"]:\r\n'
     b"                spawnableTiles = []\r\n"
     b"            if spawnableTiles:\r\n"),
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
    # attack: seat a sentinel rather than a gunner (SIEGE_SENTINEL). Guarded and
    # placed BEFORE the gunner build so the chassis line survives untouched; the
    # sentinel line shot ignores obstacles, so the gunner's seat still reaches.
    (b"                    if ct.can_build_gunner(gunnerSpot, gunnerDir):\r\n"
     b"                        ct.build_gunner(gunnerSpot, gunnerDir)\r\n",
     b'                    if KNOBS["SIEGE_SENTINEL"] and ct.can_build_sentinel(gunnerSpot, gunnerDir):\r\n'
     b"                        ct.build_sentinel(gunnerSpot, gunnerDir)\r\n"
     b"                        return\r\n"
     b"                    if ct.can_build_gunner(gunnerSpot, gunnerDir):\r\n"
     b"                        ct.build_gunner(gunnerSpot, gunnerDir)\r\n"),
    # attack: deny the enemy core's heal slots with barriers (SIEGE_DENY_HEAL)
    (b"            if ct.get_global_resources() >= KNOBS[\"SEAT_TI\"]:\r\n",
     b'            if KNOBS["SIEGE_DENY_HEAL"] and ct.get_global_resources() >= 40:\r\n'
     b"                ec = self.mapPf.enemyCorePos\r\n"
     b"                coreTiles = [ec, ec.add(Direction.EAST), ec.add(Direction.SOUTH),\r\n"
     b"                             ec.add(Direction.SOUTH).add(Direction.EAST)]\r\n"
     b"                for ct2 in coreTiles:\r\n"
     b"                    for d2 in CARDINALS:\r\n"
     b"                        heal = ct2.add(d2)\r\n"
     b"                        if heal in coreTiles:\r\n"
     b"                            continue\r\n"
     b"                        if myLoc.distance_squared(heal) != 1:\r\n"
     b"                            continue\r\n"
     b"                        if ct.can_build_barrier(heal):\r\n"
     b"                            ct.build_barrier(heal)\r\n"
     b"                            return\r\n"
     b"            if ct.get_global_resources() >= KNOBS[\"SEAT_TI\"]:\r\n"),
    # attack: score the seat by adjacency to the TARGET, not to the attacker
    (b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))\r\n",
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))\r\n"
     b'            if KNOBS["SEAT_PREFER_CORE"]:\r\n'
     b"                score = (seatCov, spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))\r\n"),
    # attack: do not siege alone (ATTACK_BUDDY)
    (b"                gunnerStuff = self.findGunnerSpot(ct)\r\n",
     b'                if KNOBS["ATTACK_BUDDY"]:\r\n'
     b"                    mates = 1\r\n"
     b"                    for u in ct.get_nearby_units():\r\n"
     b"                        if ct.get_team(u) == ct.get_team() and ct.get_entity_type(u) == EntityType.BUILDER_BOT and u != ct.get_id():\r\n"
     b"                            mates += 1\r\n"
     b'                    if mates < KNOBS["ATTACK_BUDDY"]:\r\n'
     b"                        self.drawState(ct, C_MARCH_ATTACK, self.mapPf.enemyCorePos)\r\n"
     b"                        self.mapPf.moveTo(ct, self.mapPf.enemyCorePos)\r\n"
     b"                        return\r\n"
     b"                gunnerStuff = self.findGunnerSpot(ct)\r\n"),
    # attack: past N seats, tend what we have instead of buying scale (SEAT_MAX_OWN)
    (b"                gunnerStuff = self.findGunnerSpot(ct)\r\n",
     b'                if KNOBS["SEAT_MAX_OWN"]:\r\n'
     b"                    ownGuns = 0\r\n"
     b"                    for b in ct.get_nearby_buildings():\r\n"
     b"                        if ct.get_team(b) == ct.get_team() and ct.get_entity_type(b) == EntityType.GUNNER:\r\n"
     b"                            ownGuns += 1\r\n"
     b'                    if ownGuns >= KNOBS["SEAT_MAX_OWN"] and self.healTeamGunners(ct):\r\n'
     b"                        return\r\n"
     b"                gunnerStuff = self.findGunnerSpot(ct)\r\n"),
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
    # gunner: make the target priority ORDER searchable (ROT_WEIGHTED)
    # Keep the chassis line intact and add a guarded OVERRIDE after it, so the
    # default folds to a bare `if 0:` block the verifier strips. An if/else pair
    # does not fold - the else survives the strip and the diff fails.
    (b"            score = (coreHits, coreThreatHits, gunnerHits, otherHits)\r\n",
     b"            score = (coreHits, coreThreatHits, gunnerHits, otherHits)\r\n"
     b'            if KNOBS["ROT_WEIGHTED"]:\r\n'
     b'                score = (coreHits * KNOBS["ROT_W_CORE"]\r\n'
     b'                         + coreThreatHits * KNOBS["ROT_W_THREAT"]\r\n'
     b'                         + gunnerHits * KNOBS["ROT_W_GUN"]\r\n'
     b'                         + otherHits * KNOBS["ROT_W_OTHER"],\r\n'
     b"                         coreThreatHits, gunnerHits, otherHits)\r\n"),
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
    # attack: refuse a seat whose line of fire is blocked by our own buildings.
    # Ordered AFTER the SEAT_PREFER_CORE sub so the score line it anchors on is
    # the one that survives that substitution - anchor order is load-bearing.
    (b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))\r\n",
     b'            if KNOBS["SEAT_RAY_CLEAR"] and self.rayBlockedByTeam(ct, spotPos, enemyCore, spotDir, ct.get_team()):\r\n'
     b"                continue\r\n"
     b"            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))\r\n"),
]


def _apply(path, subs, label):
    """Apply anchored substitutions to one file, asserting every anchor."""
    # Normalise to CRLF first. Chassis files reach us by two routes with two
    # conventions - git checkouts are CRLF here, bots unzipped from a platform
    # submission are LF - and the anchors below are written with \r\n, so an LF
    # chassis would fail every multi-line anchor for a reason that has nothing
    # to do with the code having changed.
    b = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    for i, (anchor, repl) in enumerate(subs):
        n = b.count(anchor)
        if n != 1:
            raise SystemExit(
                f"{label} anchor {i} matched {n} times, expected 1 - the chassis "
                f"moved under us. Fix autolab/build_template.py before searching."
                f"\n  anchor: {anchor[:80]!r}")
        b = b.replace(anchor, repl, 1)
    path.write_bytes(b)


def build(chassis="OogwayAttack"):
    src = ROOT / "bots" / chassis
    if not (src / "main.py").is_file():
        raise SystemExit(f"no chassis at bots/{chassis}/main.py")
    if TEMPLATE.exists():
        shutil.rmtree(TEMPLATE)
    shutil.copytree(src, TEMPLATE, ignore=shutil.ignore_patterns("__pycache__"))

    _apply(TEMPLATE / "main.py", MAIN_SUBS, "main.py")
    # mapPathfinding.py carries its own copy of the KNOBS line: it is a separate
    # module with no import of main, so pathfinding knobs need the dict locally.
    # materialise() rewrites the line in BOTH files.
    _apply(TEMPLATE / "mapPathfinding.py", PF_SUBS, "mapPathfinding.py")
    (TEMPLATE / "AUTOLAB_TEMPLATE").write_text(
        f"generated from bots/{chassis} by autolab.build_template\n")
    print(f"built bots/_template from bots/{chassis} "
          f"({len(MAIN_SUBS)} main + {len(PF_SUBS)} pathfinding anchors, "
          f"{len(KNOB_SPEC)} knobs)")
    return TEMPLATE


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "OogwayAttack")
