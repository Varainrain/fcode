"""Per-turn economy arbiter for non-attacking, non-defending builders.

Conveyor routing lives HERE (pulled out of mapPathfinding.py, which now only
keeps generic tile/grid primitives), as one of the arbiter's states. The
routing algorithm below is a straight port of the current bot's Dijkstra-
bucket router (same lineage as v60/v80) - splitting it out by file is the
structural change this pass makes; redesigning the algorithm itself is left
as a follow-up (an earlier CONV_BLD_CAP density gate was removed; restoring it
blunt - it should gate on the CANDIDATE's own distance instead of a global
building count, per the session that shipped the current bot's version).

closest_claimant is the ONE shared "don't collide" primitive - the current
bot independently re-derived the same check for ore tiles, explore frontier
tiles, and heal targets. attack.py imports it from here too.

States share ONE floor (S_FLOOR-per-state) with real per-target value inside
it, matching the v-clamp1-b1 finding (55.3%+ pooled from sharing one floor
instead of tiered floor/cap bands) - not artificial priority tiers.
"""

import os

import os
import time
from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS, DIRECTIONS


def _fp(key: str, default: float) -> float:
    v = os.environ.get(key)
    return float(v) if v is not None else default


def _fi(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v is not None else default


def _prof(name):
    # NOTE: duplicated in main.py/attack.py rather than shared via import -
    # importing it back from main.py creates a circular import that fails
    # depending on which file the loader happens to import first.
    def deco(fn):
        def wrapper(ct, player, *a, **k):
            t = time.monotonic()
            r = fn(ct, player, *a, **k)
            player.mapPf._acc(name, time.monotonic() - t)
            return r
        return wrapper
    return deco


S_HEAL_CORE = 3   # lowered to sit INSIDE the new bands: routeConv/routeHarv
                   # cap at 5 and harvest at 4, so a flat 6.0 dominated them
                   # all and the band ordering could never take effect.
S_RC_FLOOR = 3   # B: gated 54.7% vs v108 (best of the batch)
S_RC_CAP = 5
S_RH_FLOOR = 3
S_RH_CAP = 5
S_HV_FLOOR = 2
S_HV_CAP = 4
# Sits ON the shared economy floor, and 'explore' is declared LAST in the
# arbiter's scores dict. max() keeps the FIRST key holding the max value, so on
# a tie at 1.0 every economy state beats explore - it fires only when all three
# return 0, i.e. genuinely nothing to do. Set 0.9 to make that ordering explicit
# instead of relying on dict literal order.
SLOT_BOOTSTRAP = 10
BOOT_CORE_HP = _fp("BOOT_CORE_HP", 0.5)   # below this HP fraction the core still gets nursed


# ORE SIDING: label every ore tile ours/contested/theirs by Manhattan distance
# to each core, so an idle builder never races into the enemy half for a tile
# that ties on the raw harvest score.

C_FIGHT_TURRET = (255, 60, 60)
C_HEAL_CORE = (60, 255, 60)
C_HEAL_BUILD = (60, 255, 200)
C_ROUTE_CONV = (60, 200, 255)
C_ROUTE_HARV = (255, 60, 255)
C_HARVEST = (255, 220, 60)
C_EXPLORE = (255, 140, 0)
C_IDLE = (200, 200, 200)


def init_state(player):
    player.oreTaken = {}     # (x,y) -> round we last SAW a building on that ore tile
    # conveyor routing state (moved out of mapPathfinding.py)
    player.convMap = None
    player.convDirs = {}
    player.convLoop = {}
    player.convRound = -1
    player.hvNorm = None
    player.myNorm = None
    player.bldHp = {}
    player._fDist = None
    player._fStat = None
    player.ringSlots = None
    player.ringTarget = None
    player.ringBlocked = {}
    player.ringTries = 0
    player.ringGiveups = {}
    player.ringSeen = {}
    player.ringTriesFor = None
    player.ringBuilt = 0


def closest_claimant(allies, my_id, my_loc, target) -> bool:
    myDist = my_loc.distance_squared(target)
    for aId, aPos in allies:
        if aId == my_id:
            continue
        if aPos.distance_squared(target) < myDist and aId < my_id:
            return False
    return True

def core_footprint_manhattan(pos: Position, core: Position) -> int:
    return min(
        abs(pos.x - (core.x + dx)) + abs(pos.y - (core.y + dy))
        for dx in (0, 1) for dy in (0, 1)
    )

def ore_rank(player, tile: Position, curRound: int) -> int:
    teamDist = player.mapPf.teamCore.distance_squared(tile)
    enemyDist = player.mapPf.enemyCorePos.distance_squared(tile)
    if enemyDist * 1.2 < teamDist:
        return 1
    elif teamDist * 1.2 < enemyDist or curRound < 80:
        return 2
    else:
        return 4

SLOT_RECALL_ECO = 9   # mirrors main.SLOT_RECALL
RECALL_STATE = _fi("RECALL_STATE", 1)   # 1 = scored state, 0 = old unconditional check


def scoreRecall(ct: Controller, player, myLoc, coreHp) -> tuple:
    """Come home and heal while the core is under threat.

    Was an unconditional pre-arbiter check in main.builder_bot, which preempted
    every other state regardless of what the builder was doing. As a scored
    state it has to WIN, so a lightly-hurt core no longer outranks a builder
    mid-conveyor-chain.
    """
    home = player.mapPf.teamCore
    if home is None:
        return 0, None
    # read_store returns 0 for a slot the core has never written, and the raw-HP
    # encoding makes 0 the STRONGEST emergency - so an unguarded `coreHp < 120`
    # recalls everyone before the core's first write. Treat 0 as "no data".
    if coreHp <= 0:
        return 0, None
    recallScore = 0
    if coreHp < 120:
        recallScore = 12
    elif coreHp < 350 and player.mapPf.myNum % 3 == 1:
        # distance term keyed off the ENEMY core, so builders deep in their half
        # (a committed siege) bid low and ones near home bid high. Guarded because
        # enemyCorePos is None until symmetry resolves.
        foe = player.mapPf.enemyCorePos
        far = 1.0 if foe is None else (1 - (myLoc.distance_squared(foe) / 250))
        recallScore = max(6, 8 * far)
    if recallScore <= 0:
        return 0, None
    # position must be HOME - this is a recall. Returning enemyCorePos would send
    # the builder the wrong way, and the arbiter idles on a None position.
    return recallScore, home

def scoreProtectCore(ct: Controller, myLoc, uncoveredTurrets): # 200
    if not uncoveredTurrets or ct.get_global_resources() < ct.get_gunner_cost():
        return 0, None
    uncoveredTurrets.sort(key=lambda g: g.distance_squared(myLoc))
    return 200, uncoveredTurrets[0]

def scoreHealCore(ct: Controller, coreId, core=None): # 6
    if coreId is None:
        return 0, None
    missing = ct.get_max_hp(coreId) - ct.get_hp(coreId)
    if missing < 10:
        return 0, None
    return S_HEAL_CORE, core

def score_heal_build(ct: Controller, player, myLoc, blds=None): # 6.25 - 8
    myTeam = ct.get_team()
    bestScore, bestPos = 0, None
    seenHp = {}
    if blds is None:
        blds = [(b, ct.get_team(b), ct.get_entity_type(b), ct.get_position(b))
                for b in ct.get_nearby_buildings()]
    for (b, bTeam, bType, bPos) in blds:
        if bTeam != myTeam:
            continue
        if bType not in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR, EntityType.HARVESTER):
            continue
        missing = ct.get_max_hp(b) - ct.get_hp(b)
        if missing < 3:
            continue
        if not closest_claimant(player.allyBuilders, player.myId, myLoc, bPos):
            continue
        # lowered with healCore so the new bands actually govern: at 6.25-8.0
        # this outranked routeConv(5)/routeHarv(5)/harvest(4) unconditionally,
        # i.e. healing a damaged CONVEYOR preempted all routing.
        # UNDER ATTACK BEATS MERELY DAMAGED. A building whose HP fell since last
        # turn is actively being shot; one that is just sitting damaged can wait.
        # Detected by remembering HP per building id rather than guessing from
        # turret coverage - a drop is direct evidence, coverage is a proxy.
        hpNow = ct.get_hp(b)
        prevHp = player.bldHp.get(b)
        underAttack = prevHp is not None and hpNow < prevHp
        score = max(2.5, 4 * (missing / ct.get_max_hp(b)) * (1 - (myLoc.distance_squared(bPos) / 120)))
        if underAttack:
            score = score * 3.0
        if score > bestScore:
            bestScore, bestPos = score, bPos
        seenHp[b] = hpNow
    player.bldHp = seenHp
    return bestScore, bestPos


def _far_core_corner(player):
    core = player.mapPf.teamCore
    center = Position(player.mapW // 2, player.mapH // 2)
    corners = [core, core.add(Direction.EAST), core.add(Direction.SOUTH),
               core.add(Direction.SOUTH).add(Direction.EAST)]
    return max(corners, key=lambda corner: corner.distance_squared(center))


def score_route_conv(ct: Controller, player, myLoc, myTeam, blds=None):
    mapW, mapH = player.mapW, player.mapH
    teamCore = player.mapPf.teamCore
    farCorner = _far_core_corner(player)
    bestScore, bestEnd = 0, None
    if blds is None:
        blds = [(b, ct.get_team(b), ct.get_entity_type(b), ct.get_position(b))
                for b in ct.get_nearby_buildings()]
    for (b, bTeam, bType, bPos) in blds:
        if bTeam != myTeam or bType != EntityType.CONVEYOR:
            continue
        endTile = bPos.add(ct.get_direction(b))
        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and player.mapPf.inMoveZone(endTile):
            endId = ct.get_tile_building_id(endTile)
            enemyBarrier = (endId is not None and ct.get_team(endId) != myTeam
                            and ct.get_entity_type(endId) == EntityType.BARRIER)
            if enemyBarrier or player.mapPf.checkPassable(ct, endTile):
                if endId is not None and not enemyBarrier:
                    endType = ct.get_entity_type(endId)
                    endTeam = ct.get_team(endId)
                    if endType not in (EntityType.GUNNER, EntityType.BUILDER_BOT, EntityType.BARRIER) and endTeam == myTeam:
                        continue
                    if endType != EntityType.BARRIER and endTeam != myTeam:
                        continue
                bScore = max(S_RC_FLOOR, S_RC_CAP * (1 - endTile.distance_squared(teamCore) / 120) * (1 - myLoc.distance_squared(bPos) / 40))
                if bScore > bestScore:
                    bestScore, bestEnd = bScore, endTile
    return bestScore, bestEnd


def _harvester_working_spots(ct: Controller, player, myTeam, bPos, farCorner):
    mapW, mapH = player.mapW, player.mapH
    noTeamConv = True
    workingSpots = []
    for possibleDir in CARDINALS:
        endTile = bPos.add(possibleDir)
        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and player.mapPf.inMoveZone(endTile):
            eId = ct.get_tile_building_id(endTile)
            if eId is None:
                if ct.is_tile_passable(endTile) and ct.get_tile_env(endTile) == Environment.EMPTY:
                    workingSpots.append(endTile)
            elif ct.get_team(eId) == myTeam:
                eType = ct.get_entity_type(eId)
                if eType == EntityType.CONVEYOR:
                    noTeamConv = False
                elif eType in (EntityType.BARRIER, EntityType.GUNNER):
                    workingSpots.append(endTile)
    return noTeamConv, workingSpots


def score_route_harv(ct: Controller, player, myLoc, myTeam, blds=None):
    teamCore = player.mapPf.teamCore
    farCorner = _far_core_corner(player)
    bestScore, bestEnd = 0, None
    if blds is None:
        blds = [(b, ct.get_team(b), ct.get_entity_type(b), ct.get_position(b))
                for b in ct.get_nearby_buildings()]
    for (b, bTeam, bType, bPos) in blds:
        if bType != EntityType.HARVESTER:
            continue
        if myLoc.distance_squared(bPos) > 10:
            continue
        noTeamConv, workingSpots = _harvester_working_spots(ct, player, myTeam, bPos, farCorner)
        if noTeamConv and workingSpots:
            workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
            bScore = max(S_RH_FLOOR, S_RH_CAP * (1 - workingSpots[0].distance_squared(teamCore) / 220) * (1 - myLoc.distance_squared(bPos) / 60))
            try:
                # ECO SIPHON: connecting an ENEMY harvester routes a quarter
                # of its output into our chain. Time-bounded (round > 50) -
                # on small maps this made eco builders wire the enemy's
                # economy instead of ours before the midgame.
                if ct.get_team(b) != myTeam and ct.get_current_round() > 50:
                    bScore *= 1.25
            except Exception:
                pass
            bScore = min(S_RH_CAP, bScore)
            if bScore > bestScore:
                bestScore, bestEnd = bScore, workingSpots[0]
    return bestScore, bestEnd


def score_harvest(ct: Controller, player, myLoc, myTeam):
    teamCore = player.mapPf.teamCore
    if teamCore is None:
        return 0, None
    if player.myNorm is None:
        player.myNorm = max(220.0, (player.mapW * player.mapW
                                    + player.mapH * player.mapH) / 4.0)
    if player.hvNorm is None:
        # d^2 of the 6th-nearest ore x1.5, floored at the old 160 so ore-rich
        # maps behave exactly as before. Computed once from the cached map.
        _d = []
        _fm = player.mapPf.fullMap
        for _x in range(player.mapW):
            _col = _fm[_x]
            for _y in range(player.mapH):
                if _col[_y] == 1:
                    _d.append(teamCore.distance_squared(Position(_x, _y)))
        _d.sort()
        player.hvNorm = max(160.0, _d[min(5, len(_d) - 1)] * 1.5) if _d else 160.0
    curRound = ct.get_current_round()
    enemyThreatened = player.mapPf.enemyTurretThreatenedTiles(ct)
    bestScore, bestTile, bestKey = 0, None, None
    for x in range(player.mapW):
        for y in range(player.mapH):
            if player.mapPf.fullMap[x][y] == 1:
                tile = Position(x, y)
                # OCCUPIED-ORE MEMORY: no fog memory from the engine, so a
                # tile we watched a harvester go up on looks free the moment
                # it leaves vision without this.

                if ct.is_in_vision(tile):
                    tileId = ct.get_tile_building_id(tile)
                    if tileId is not None:
                        tTeam = ct.get_team(tileId)
                        tType = ct.get_entity_type(tileId)
                        # clearable: ours -> gunner/barrier (destroy);
                        # theirs -> conveyor/barrier (shoot). Anything else,
                        # ESPECIALLY OUR OWN HARVESTER, must be skipped - without
                        # the continue a builder demolishes its own harvester.
                        # our own barrier on enemy-side ore is a DENIAL CAP,
                        # not an obstacle - clearing it made an eco builder and
                        # an attacker fight over the same tile all game.
                        ownCap = (tTeam == myTeam and tType == EntityType.BARRIER
                                  and ore_rank(player, tile, curRound) != 0)
                        clearable = ((not ownCap) and
                                     (tTeam == myTeam and tType in (EntityType.GUNNER, EntityType.BARRIER))
                                     or (tTeam != myTeam and tType in (EntityType.CONVEYOR, EntityType.BARRIER)))
                        if not clearable:
                            player.oreTaken[(x, y)] = curRound
                            continue
                    else:
                        player.oreTaken.pop((x, y), None)
                else:
                    seen = player.oreTaken.get((x, y))
                    if seen is not None and curRound - seen <= 100:
                        continue
                if player.mapPf.inMoveZone(tile) and (x, y) not in enemyThreatened:
                    dist = teamCore.distance_squared(tile)
                    myDist = myLoc.distance_squared(tile)
                    # ADAPTIVE CLIFF. A fixed 160 zeroes at 12.65 tiles, so on any
                    # map whose ore sits further out EVERY tile collapses to
                    # S_HV_FLOOR and this stops ranking ore at all. Three maps are
                    # past that line (ragnarok 18.9, drakkarfjord 14.4,
                    # valkyrie 12.9), and 560 server games agree: coreToOre
                    # rho=-0.54, meanOwnOreDist -0.40, oreNear5 +0.38.
                    tileScore = max(S_HV_FLOOR, S_HV_CAP * (max(0, player.hvNorm - dist) / player.hvNorm) * (max(0, player.myNorm - myDist) / player.myNorm))
                    if ct.get_global_resources() > dist / 7:

                        rank = ore_rank(player, tile, curRound)
                        key = (tileScore, rank, -(dist + myDist))
                        if bestKey is None or key > bestKey:
                            bestKey = key
                            bestScore, bestTile = tileScore, tile
    return bestScore, bestTile


def scoreExplore(ct: Controller, player, myLoc):
    exploreSpot = player.exploreSpot
    teamCore = player.mapPf.teamCore
    if exploreSpot is None or player.exploreDone:
        exploreSpot = teamCore
    if myLoc.distance_squared(exploreSpot) < 9:
        player.exploreDone = True
        exploreSpot = teamCore
    if not player.mapPf.inMoveZone(exploreSpot):
        exploreSpot = teamCore
    return 1, exploreSpot


def _int_set_env(key: str, default: str) -> frozenset:
    v = os.environ.get(key, default)
    return frozenset(int(x) for x in v.split(",") if x.strip())


# PICKET (Lorem pattern, 3dda7812 vs Jython): one midfield lane sentinel by
# ~t15, paid from the opening bank, BEFORE any threat exists. It covers the
# core-to-core approach lane: wave planters and relay riders crossing it eat
# 18 dmg per 2 turns on the walk in, and armored core-shellers that slip
# through die to its indirect fire regardless of barrier shells. Lorem's
# picket went up t11-t14 in every game of their 4-1 over Jython.
PICKET_ENABLE = _fi("PICKET_ENABLE", 1)
PICKET_NUM = _fi("PICKET_NUM", 2)        # which spawn plants it (builder #2)
PICKET_ROUND_MAX = _fi("PICKET_ROUND_MAX", 35)   # give up after this round
PICKET_DIST = _fi("PICKET_DIST", 5)      # manhattan from our core, along the lane
PICKET_SCORE = 9.0    # above all economy (<=8), below recall(12)/protect(200)

# The picket gated BIMODAL vs no-picket (150 games): antler 10/10, ragnarok
# 9/10, frostgate 8/10, archipelago 7/10 - but royale 0/10 and drakkarfjord/
# midgard 1/10 (tempo-fragile or oversized maps where 30 Ti + builder #2's
# detour loses the eco race). Same medicine as the rush table: exact-core
# fingerprint gate. NOTE frostgate and yulerune share identical fingerprints
# ((2,9)/(16,9) 20x20) so enabling frostgate enables yulerune too - measured
# free there (5/10).
PICKET_CORES = {
    (14, 18): frozenset({(6, 4), (6, 12)}),      # antler      10/10
    (30, 30): frozenset({(2, 2), (26, 26)}),     # ragnarok    9/10 (midgard
    # shares this fingerprint... see guard below: midgard measured 1/10, but
    # ragnarok and midgard have IDENTICAL W,H and core positions - they are
    # indistinguishable at runtime. 9/10 + 1/10 nets to 50% -> leave BOTH out.
    (20, 20): frozenset({(2, 9), (16, 9)}),      # frostgate   8/10 (+yulerune 5/10)
    (26, 26): frozenset({(5, 5), (19, 19)}),     # archipelago 7/10
}
# ragnarok/midgard fingerprint collision resolved by exclusion:
# (30,30) RE-ENABLED 08-18 (was popped over the ragnarok/midgard fingerprint
# collision: mirror gated 9/10-vs-1/10 and we averaged it away - the MIRROR
# TRAP again). Field: lingling beats our plain eco on ragnarok t142 with an
# armored wave, while the picket maps beat lingling twice (antler). Class
# referee decides, not mirrors.


def picket_map_ok(player):
    tc = player.mapPf.teamCore
    if tc is None or player.mapW is None:
        return False
    cs = PICKET_CORES.get((player.mapW, player.mapH))
    return bool(cs and (tc.x, tc.y) in cs)

C_PICKET = (255, 200, 40)


def _enemy_core_guess(player):
    foe = player.mapPf.enemyCorePos
    if foe is not None:
        return foe
    tc = player.mapPf.teamCore
    if tc is None or player.mapW is None:
        return None
    # 180-rotation prediction - verified to hold on all 15 pool maps
    return Position(player.mapW - tc.x - 2, player.mapH - tc.y - 2)


# TAXI-TO-FRONT (taxi v3 - v1/v2 parked because solo deliveries landed in
# enemy gunner mass; the FRONT is friendly turret cover by definition, so
# the failure mode is gone). Builder #1 drops one launcher by r14; walkers
# board it only when a front EXISTS and home is quiet; the launcher throws
# them toward the front. Compresses the reinforcement loop the front
# system needs to bootstrap through grinds.
TAXI_ENABLE = _fi("TAXI_ENABLE", 1)
TAXI_ROUND_MAX = _fi("TAXI_ROUND_MAX", 14)
TAXI_SCORE = 8.5


def scoreTaxi(ct, player, myLoc):
    if not TAXI_ENABLE or player.mapPf.myNum != 1:
        return 0, None
    if getattr(player, "_taxiDone", False):
        return 0, None
    if ct.get_current_round() > TAXI_ROUND_MAX:
        player._taxiDone = True
        return 0, None
    if ct.get_global_resources() < ct.get_launcher_cost() + 40:
        return 0, None
    tc = player.mapPf.teamCore
    if tc is None:
        return 0, None
    return TAXI_SCORE, tc


def taxi_task(ct, player, myLoc):
    for b in ct.get_nearby_buildings():
        if (ct.get_team(b) == ct.get_team()
                and ct.get_entity_type(b) == EntityType.LAUNCHER):
            player._taxiDone = True
            return
    for d in DIRECTIONS:
        n = myLoc.add(d)
        if ct.get_tile_building_id(n) is not None:
            continue
        if ct.get_tile_env(n) != Environment.EMPTY:
            continue
        if ct.can_build_launcher(n):
            ct.build_launcher(n)
            player._taxiDone = True
            return
    tc = player.mapPf.teamCore
    if tc is not None:
        player.mapPf.moveTo(ct, tc)


def scorePicket(ct, player, myLoc):
    if not PICKET_ENABLE or player.mapPf.myNum != PICKET_NUM:
        return 0, None
    if not picket_map_ok(player):
        return 0, None
    if getattr(player, "_picketDone", False):
        return 0, None
    if ct.get_current_round() > PICKET_ROUND_MAX:
        player._picketDone = True
        return 0, None
    if ct.get_global_resources() < ct.get_sentinel_cost() + 30:
        return 0, None
    tc = player.mapPf.teamCore
    foe = _enemy_core_guess(player)
    if tc is None or foe is None:
        return 0, None
    dx, dy = foe.x - tc.x, foe.y - tc.y
    dist = max(1, abs(dx) + abs(dy))
    px = tc.x + round(dx * PICKET_DIST / dist)
    py = tc.y + round(dy * PICKET_DIST / dist)
    px = min(max(px, 0), player.mapW - 1)
    py = min(max(py, 0), player.mapH - 1)
    return PICKET_SCORE, Position(px, py)


def picket_task(ct, player, myLoc, target):
    player.draw_state(ct, C_PICKET, target)
    foe = _enemy_core_guess(player)
    if myLoc.distance_squared(target) <= 8:
        # in the neighborhood: plant on the first buildable tile near the lane
        # point, facing down the lane so the ray covers the approach
        cands = [target] + [target.add(d) for d in DIRECTIONS]
        for pos in cands:
            if myLoc.distance_squared(pos) > 2:
                continue
            if ct.get_tile_building_id(pos) is not None:
                continue
            if ct.get_tile_env(pos) != Environment.EMPTY:
                continue
            fd = pos.direction_to(foe) if foe is not None else None
            if fd is not None and ct.can_build_sentinel(pos, fd):
                ct.build_sentinel(pos, fd)
                player._picketDone = True
                return
    player.mapPf.moveTo(ct, target)

RING_ENABLE = _fi("RING_ENABLE", 1)
RING_NUMS = _int_set_env("RING_NUMS", "4")   # mirrors main.DEFEND_NUMS
RING_SCORE = 2.5      # above healBuild's 8.0 cap, below recall's 12
RING_SCORE_IDLE = 0.0  # non-defenders already standing at home
RING_ROUND = 120        # earliest round the ring may start
RING_ORE = _fi("RING_ORE", 0)            # 1 = also pave ORE ring tiles (loses a harvester seat)
RING_MEMORY = _fi("RING_MEMORY", 60)     # rounds a remembered-filled ring tile stays trusted
RING_ATTEMPTS = _fi("RING_ATTEMPTS", 15)  # turns budgeted per ring slot before giving up
RING_RETRY = _fi("RING_RETRY", 40)       # rounds a slot stays blacklisted after a failed build
RING_RESERVE = _fi("RING_RESERVE", 28)   # Ti left untouched after paying for a ring conveyor
                                         # (28 = the same reserve run_core keeps back)

C_RING = (120, 90, 255)


def ring_slots(player):
    """The 8 orthogonally-adjacent tiles of the 2x2 core, each with the
    Direction that points INTO the core from it. Core position never changes,
    so this is computed once per unit."""
    if player.ringSlots is not None:
        return player.ringSlots
    core = player.mapPf.teamCore
    if core is None:
        return ()
    cx, cy = core.x, core.y
    slots = (
        (Position(cx - 1, cy),     Direction.EAST),
        (Position(cx - 1, cy + 1), Direction.EAST),
        (Position(cx,     cy - 1), Direction.SOUTH),
        (Position(cx + 1, cy - 1), Direction.SOUTH),
        (Position(cx,     cy + 2), Direction.NORTH),
        (Position(cx + 1, cy + 2), Direction.NORTH),
        (Position(cx + 2, cy),     Direction.WEST),
        (Position(cx + 2, cy + 1), Direction.WEST),
    )
    kept = []
    for pos, d in slots:
        if 0 <= pos.x < player.mapW and 0 <= pos.y < player.mapH:
            kept.append((pos, d))
    player.ringSlots = tuple(kept)
    return player.ringSlots


def _ring_stands(player, tile: Position, d: Direction):
    """Legal tiles to build `tile` FROM, best first.

    can_build_conveyor needs the builder ORTHOGONALLY adjacent to the target and
    NOT on it. Of tile's 4 orthogonal neighbours one is the core itself (tile+d),
    one is a sibling ring tile, and two are "free": the core's diagonal corner
    and the tile directly outward.

    Preference order is corner, then outward, then SIBLING RING TILE. The corner
    is best because it is adjacent to TWO ring tiles, which turns the whole ring
    into a 4-stop tour. The sibling is last because standing on it makes it
    unbuildable while we are there - the project's recurring "walked onto the
    build target" bug - but it must stay available: measured on valkyrie, ring
    tile (4,15) had WALLS on both of its free stands, so excluding siblings
    outright left it permanently unfillable and cost 220 builder-turns of
    give-up/retry."""
    ringKeys = set((p.x, p.y) for p, _ in ring_slots(player))
    core = player.mapPf.teamCore
    coreKeys = set(((core.x + dx, core.y + dy) for dx in (0, 1) for dy in (0, 1)))
    dx, dy = d.delta()
    out = []
    for nd in CARDINALS:
        n = tile.add(nd)
        if not (0 <= n.x < player.mapW and 0 <= n.y < player.mapH):
            continue
        key = (n.x, n.y)
        if key in coreKeys:
            continue
        if key in ringKeys:
            rank = 2
        elif n.x == tile.x - dx and n.y == tile.y - dy:
            rank = 1          # outward
        else:
            rank = 0          # core diagonal corner
        out.append((rank, n))
    out.sort(key=lambda t: t[0])
    return [n for _, n in out]


def _stand_usable(ct: Controller, player, s: Position) -> bool:
    """BUG THIS EXISTS FOR: mapPathfinding.checkPassable() only inspects
    BUILDINGS and enemy bots - it never reads get_tile_env, so it happily
    returns True for a solid WALL. Using it alone as the stand filter sent the
    defender walking into rock for a full 16-turn attempt budget, over and over
    (valkyrie (4,13) and (5,14) are both WALL, and both reported pass=True).
    Terrain is checked here from the SHARED fullMap (2 == WALL), which also
    works out of vision, where get_tile_env would raise."""
    if not player.mapPf.inMoveZone(s):
        return False
    if player.mapPf.fullMap is not None and player.mapPf.fullMap[s.x][s.y] == 2:
        return False
    if not ct.is_in_vision(s):
        return True   # unreadable (checkPassable would raise) - let moveTo try
    if ct.get_tile_env(s) == Environment.WALL:
        return False
    return player.mapPf.checkPassable(ct, s)


def _ring_state(ct: Controller, player, tile: Position, myTeam):
    """'filled' | 'hole' | 'hostile' | 'unknown' | 'skip'.

    ct.get_tile_env() and ct.get_tile_building_id() RAISE GameError("Position out
    of vision range") rather than returning a sentinel, so every read here has to
    be vision-gated first. (This cost the first sanity run: _ideabase carries no
    exception handlers, so it destroyed a builder per turn instead of degrading.)
    We fall back to the shared fullMap for terrain, which remembers walls/ore
    from any teammate's vision, and report 'unknown' when only occupancy is in
    doubt so the caller can decide whether to walk over and look."""
    key = (tile.x, tile.y)
    if not ct.is_in_vision(tile):
        cached = player.mapPf.fullMap[tile.x][tile.y]
        if cached == 2:                       # remembered WALL - never fillable
            return 'skip'
        if cached == 1 and not RING_ORE:      # remembered ORE
            return 'skip'
        # FOG MEMORY, same idea as oreTaken above: the engine gives no memory, so
        # a tile we watched a conveyor go up on reads as 'unknown' the instant it
        # leaves vision. Without this the defender treadmills - every time it
        # drifts to the edge of its move zone the far side of the ring goes
        # unknown, it bids 9.0 and walks home to look at a tile it just built.
        # Measured on yulerune: 72 arbiter wins for 6 conveyors, ~60 of them
        # spent re-verifying an intact ring.
        seen = player.ringSeen.get(key)
        if seen is not None and seen[1] in ('filled', 'skip'):
            if ct.get_current_round() - seen[0] <= RING_MEMORY:
                return 'skip'
        return 'unknown'
    env = ct.get_tile_env(tile)
    if env == Environment.WALL:
        st = 'skip'
    elif env == Environment.ORE_TITANIUM and not RING_ORE:
        st = 'skip'
    else:
        bid = ct.get_tile_building_id(tile)
        if bid is None:
            st = 'hole'
        elif ct.get_team(bid) != myTeam:
            st = 'hostile'
        else:
            st = 'filled'
    player.ringSeen[key] = (ct.get_current_round(), st)
    return st


def score_ring(ct: Controller, player, myLoc, myTeam):
    if not RING_ENABLE:
        return 0, None
    core = player.mapPf.teamCore
    if core is None or player.mapW is None:
        return 0, None
    curRound = ct.get_current_round()
    if curRound < RING_ROUND:
        return 0, None

    isDefender = player.mapPf.myNum in RING_NUMS
    if not isDefender and core_footprint_manhattan(myLoc, core) > 3:
        # anyone else only patches holes they are already standing next to
        return 0, None

    slots = ring_slots(player)
    if not slots:
        return 0, None

    # AFFORDABILITY, the protectCore way - but split BY ACTION, because the two
    # things this state does have wildly different prices.
    #
    # BUG FOUND BY INSTRUMENTATION: the first version gated the whole state on
    # `resources >= conveyorCost + harvesterCost`. Harvester cost SCALES with
    # team building count (measured 24 -> 86 by r175 on midgard) so from about
    # r75 the gate demanded 70-90 Ti in a bank that routinely holds under 30.
    # The ring therefore built cleanly in the opening and could never be
    # REPAIRED afterwards - which is the entire point of a defensive ring.
    # Worse, the same gate suppressed the anti-squatter response, which costs
    # BUILDER_BOT_ATTACK_COST = 2 Ti, not 70. Measured before the fix:
    # frostgate and royale both ended with an enemy building parked on a ring
    # tile and shots=0 for the whole game.
    ti = ct.get_global_resources()
    canBuild = ti >= ct.get_conveyor_cost() + RING_RESERVE
    canShoot = ti >= 4          # attack costs 2; keep one spare

    live = []
    if canBuild:
        live.append('hole')
        if isDefender:
            # a non-defender never goes LOOKING - it only plugs what it can see
            live.append('unknown')
    if canShoot:
        live.append('hostile')
    if not live:
        return 0, None
    live = tuple(live)

    # honour a committed target so the goalpost cannot move under us while we
    # walk (the failure mode that broke sentinel siege and defence seats).
    if player.ringTarget is not None:
        tPos, tDir = player.ringTarget
        st = _ring_state(ct, player, tPos, myTeam)
        if st in live:
            return (RING_SCORE if isDefender else RING_SCORE_IDLE), tPos
        player.ringTarget = None

    best, bestKey = None, None
    for pos, d in slots:
        pk = (pos.x, pos.y)
        if curRound - player.ringBlocked.get(pk, -99999) < RING_RETRY * (1 + player.ringGiveups.get(pk, 0)):
            continue
        st = _ring_state(ct, player, pos, myTeam)
        if st not in live:
            continue
        if pos == myLoc:
            # We are STANDING on it. can_build_conveyor excludes our own tile, so
            # this is only a target if we can actually step off first - and while
            # we are parked here the tile is denied to the enemy anyway, which is
            # most of the point. Measured before this check: one boxed-in builder
            # re-targeted its own tile 60 times on valkyrie.
            if not any(ct.can_move(_d) for _d in CARDINALS):
                continue
        # hostile last: shooting a 30-HP barrier out at 2 dmg/shot is 15 turns,
        # so plug the free holes first.
        rank = 0 if st == 'hole' else (1 if st == 'unknown' else 2)
        key = (rank, myLoc.distance_squared(pos))
        if bestKey is None or key < bestKey:
            bestKey, best = key, (pos, d)
    if best is None:
        return 0, None
    player.ringTarget = best
    return (RING_SCORE if isDefender else RING_SCORE_IDLE), best[0]


def ring_task(ct: Controller, player, myLoc, myTeam) -> bool:
    """Returns False if it could not do ANYTHING useful this turn, so run() can
    fall through to the next-best state instead of burning the turn. (The
    project's single most expensive recurring bug is an executor that returns
    True having done nothing.)"""
    if player.ringTarget is None:
        return False
    tile, d = player.ringTarget
    player.draw_state(ct, C_RING, tile)

    # ATTEMPT BUDGET. Measured on valkyrie before this existed: one builder spent
    # 213 turns walking at a ring tile it could never reach and 157 turns parked
    # on one it could never build, for 3 conveyors between them. moveTo() reports
    # nothing about whether it made progress, so bound the effort explicitly.
    key = (tile.x, tile.y)
    if player.ringTriesFor != key:
        player.ringTriesFor = key
        player.ringTries = 0
    player.ringTries += 1
    if player.ringTries > RING_ATTEMPTS:
        # ESCALATING BACKOFF: a slot that is simply unreachable (its two stands
        # are walled off) would otherwise cost RING_ATTEMPTS turns every
        # RING_RETRY rounds forever - measured 6 give-ups x 15 turns on valkyrie.
        player.ringGiveups[key] = player.ringGiveups.get(key, 0) + 1
        player.ringBlocked[key] = ct.get_current_round()
        player.ringTarget = None
        player.ringTries = 0
        return False

    # STANDING ON OUR OWN TARGET. can_build_conveyor explicitly excludes the
    # builder's own tile, and CORE_SPAWNING_RADIUS_SQ is 2 - which is exactly the
    # 8 ring tiles plus the 4 diagonals - so every freshly spawned builder starts
    # life standing on a ring tile. Left alone this is the project's recurring
    # "walked onto the build target, now it is permanently unbuildable" bug.
    # Step off, and if we are boxed in do NOT claim the turn.
    if myLoc == tile:
        for s in _ring_stands(player, tile, d):
            if _stand_usable(ct, player, s) and myLoc.distance_squared(s) == 1:
                dd = myLoc.direction_to(s)
                if ct.can_move(dd):
                    ct.move(dd)
                    return True
        for dd in CARDINALS:
            n = myLoc.add(dd)
            if (0 <= n.x < player.mapW and 0 <= n.y < player.mapH
                    and player.mapPf.inMoveZone(n) and ct.can_move(dd)):
                ct.move(dd)
                return True
        return False

    if not ct.is_in_vision(tile):
        # can't read the tile at all yet - walk to a stand and look. moveTo is
        # bounded by the defender's move zone, which is centred on the core, so
        # this converges in a couple of steps.
        for s in _ring_stands(player, tile, d):
            if player.mapPf.inMoveZone(s):
                player.mapPf.moveTo(ct, s)
                return True
        return False

    bid = ct.get_tile_building_id(tile)
    if bid is not None and ct.get_team(bid) != myTeam:
        # ENTOMBED: an enemy building is sitting on our ring tile. can_destroy is
        # allies-only, so the only removal is shooting it out - 30 HP of barrier
        # at BUILDER_BOT_ATTACK_DAMAGE 2 is 15 shots.
        if myLoc.distance_squared(tile) == 1:
            if ct.can_fire(tile):
                ct.fire(tile)
                player.ringTries = 0      # real progress, keep going
                return True
            return False
        for s in _ring_stands(player, tile, d):
            if _stand_usable(ct, player, s):
                player.mapPf.moveTo(ct, s)
                return True
        return False

    if ct.can_build_conveyor(tile, d):
        ct.build_conveyor(tile, d)
        player.ringTarget = None
        player.ringTries = 0
        player.ringBuilt += 1
        return True

    stands = _ring_stands(player, tile, d)
    if any(s == myLoc for s in stands):
        # We are where we need to be and the engine still says no. If the action
        # cooldown simply is not clear that is a timing miss and NOT a reason to
        # give up on the slot - hand the turn to another state (which can still
        # move) and come back. Otherwise the slot is genuinely un-buildable, so
        # blacklist it briefly rather than stalling this builder here forever.
        if ct.can_act():
            player.ringBlocked[key] = ct.get_current_round()
            player.ringTarget = None
        return False

    if player.ringTries > RING_ATTEMPTS // 2:
        # moveTo() gives no reachability signal, so a preferred stand that has no
        # path just burns the budget while the anti-stuck random walk shuffles us
        # around (measured: 86 successful moves, 0 arrivals). Spend the back half
        # of the budget on the other stand instead.
        stands = stands[::-1]
    for s in stands:
        if not _stand_usable(ct, player, s):
            continue
        player.mapPf.moveTo(ct, s)
        return True

    # no reachable stand at all (walled in on both sides)
    player.ringBlocked[key] = ct.get_current_round()
    player.ringTarget = None
    return False


def _signed4(v: int) -> int:
    return v - 16 if v >= 8 else v


def broadcast_gunners(ct: Controller, player) -> list:
    """Decode slot 7: our core's position (bits 0-9) plus up to 2 enemy
    turret offsets from it (4-bit signed dx/dy each, dx=dy=0 = empty)."""
    compact = ct.read_store(7)
    corePos = Position((compact >> 5) & 0x1F, compact & 0x1F)
    gunners = []
    for i in range(2):
        gun = (compact >> (10 + 8 * i)) & 0xFF
        if gun == 0:
            continue
        dx = _signed4((gun >> 4) & 0xF)
        dy = _signed4(gun & 0xF)
        gPos = Position(corePos.x + dx, corePos.y + dy)
        gunners.append(gPos)
        ct.draw_indicator_line(corePos, gPos, 255, 255, 0)
    return gunners

def heal_damaged_non_core(ct: Controller, player) -> bool:
    """Used by main.answer_recall, not by the arbiter directly."""
    myLoc = ct.get_position()
    myTeam = ct.get_team()
    bestPos, bestId, bestDist = None, None, None
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        bType = ct.get_entity_type(b)
        if bType not in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR, EntityType.HARVESTER):
            continue
        if ct.get_hp(b) >= ct.get_max_hp(b):
            continue
        bPos = ct.get_position(b)
        if not closest_claimant(player.allyBuilders, player.myId, myLoc, bPos):
            continue
        dist = myLoc.distance_squared(bPos)
        if bestDist is None or dist < bestDist:
            bestDist, bestPos, bestId = dist, bPos, b
    if bestPos is None:
        return False
    player.draw_state(ct, C_HEAL_BUILD, bestPos)
    if myLoc.distance_squared(bestPos) > 1:
        player.mapPf.moveTo(ct, bestPos)
    elif myLoc.distance_squared(bestPos) < 1:
        player.mapPf.moveTo(ct, player.mapPf.teamCore)
    if ct.can_heal(bestPos) and ct.get_hp(bestId) < ct.get_max_hp(bestId) - 2:
        ct.heal(bestPos)
    return True


# --- conveyor routing (moved out of mapPathfinding.py) ---

def _conveyor_tile_cost(ct: Controller, player, tile: Position, curEnd: Position):
    mapPf = player.mapPf
    cachedVal = mapPf.fullMap[tile.x][tile.y]
    if cachedVal == 2 or cachedVal == 3:
        return None, 'stuck'
    myLoc = mapPf._myLoc
    dx = tile.x - myLoc.x
    dy = tile.y - myLoc.y
    if dx * dx + dy * dy > 20:
        return 1, 'working'
    teamCore = mapPf.teamCore
    endDist = curEnd.distance_squared(teamCore)
    otherDist = tile.distance_squared(teamCore)
    tileId = ct.get_tile_building_id(tile)
    if tileId is not None:
        tTeam = ct.get_team(tileId)
        tType = ct.get_entity_type(tileId)
        if tTeam != ct.get_team():
            return None, 'stuck'
        if tType == EntityType.CORE:
            return 0, 'done'
        if tType == EntityType.CONVEYOR:
            if player.convLoop.get((tile.x, tile.y)):
                return 8, 'working'
            if ct.get_stored_resource(tileId) is not None:
                return 24, 'done'
            if endDist > otherDist:
                return 30, 'done'
            return 2, 'working'
        if tType == EntityType.BARRIER:
            return 8, 'working'
        if tType == EntityType.GUNNER:
            return 24, 'working'
        return None, 'stuck'
    return 1, 'working'


def _conveyor_tile_cost_safe(ct: Controller, player, tile: Position, enemyThreatened, curEnd: Position):
    cost, status = _conveyor_tile_cost(ct, player, tile, curEnd)
    if cost is not None and (tile.x, tile.y) in enemyThreatened:
        cost += 24
    return cost, status

def _classify_conveyors(ct: Controller, player, myTeam):
    curRound = ct.get_current_round()
    if player.convRound == curRound:
        return player.convDirs, player.convLoop
    w, h = player.mapW, player.mapH
    convDirs = {}
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.CONVEYOR:
            bPos = ct.get_position(b)
            convDirs[(bPos.x, bPos.y)] = (bPos, ct.get_direction(b), ct.get_stored_resource(b) is not None)
    convLoop = {}
    for startKey in convDirs:
        if startKey in convLoop:
            continue
        thisPath = []
        onPath = {}
        cur = startKey
        isLoop = False
        while True:
            if cur in onPath:
                isLoop = True
                break
            if cur in convLoop:
                isLoop = convLoop[cur]
                break
            onPath[cur] = True
            thisPath.append(cur)
            curPos, curDir, _ = convDirs[cur]
            nextPos = curPos.add(curDir)
            if not (0 <= nextPos.x < w and 0 <= nextPos.y < h):
                break
            nextKey = (nextPos.x, nextPos.y)
            if nextKey not in convDirs:
                break
            cur = nextKey
        for key in thisPath:
            convLoop[key] = isLoop
    player.convDirs = convDirs
    player.convLoop = convLoop
    player.convRound = curRound
    return convDirs, convLoop

def _creates_loop(player, buildPos: Position, d: Direction):
    w, h = player.mapW, player.mapH
    buildKey = (buildPos.x, buildPos.y)
    cur = buildPos.add(d)
    onPath = {}
    while True:
        if not (0 <= cur.x < w and 0 <= cur.y < h):
            return False
        curKey = (cur.x, cur.y)
        if curKey == buildKey:
            return True
        if curKey in onPath:
            return True
        if player.convLoop.get(curKey):
            return True
        if curKey not in player.convDirs:
            return False
        onPath[curKey] = True
        curPos, curDir, _ = player.convDirs[curKey]
        cur = curPos.add(curDir)

@_prof('convFill')
def _fill_conveyor_dist_table(ct: Controller, player, curEnd: Position):
    """Dial's-algorithm distance fill over conveyor-routing cost.

    FLAT-ARRAY REWRITE. The previous form was the TLE hot spot: measured 402
    calls/game on valkyrie driving 1.27M tile-cost evaluations, with a worst
    builder turn of 97ms against a 10ms budget. Three costs removed:

      1. convMap was a list-of-lists-of-2-element-lists - triple indirection on
         every read AND w*h fresh list allocations per call. Now flat int lists
         indexed y*w+x, reused across calls.
      2. a Position was allocated for every neighbour of every popped node.
         Now neighbours are integer index arithmetic; a Position is built only
         when a tile's cost is evaluated for the first time.
      3. the bucket loop ran over range(maxCost) = 2928 slots although the
         largest single edge cost is 54. Now it stops at the highest bucket
         actually populated.

    Behaviour is identical - verified in-game against the original by a
    differential probe (bots/_flatdiff) comparing the full distance table on
    every call.
    """
    myTeam = ct.get_team()
    myLoc = ct.get_position()
    player.mapPf._myLoc = myLoc
    enemyThreatened = player.mapPf.enemyTurretThreatenedTiles(ct)
    w, h = player.mapW, player.mapH
    maxCost = (w + h) * (24 + 24) + 48
    size = w * h

    dist = player._fDist
    stat = player._fStat
    if dist is None or len(dist) != size:
        dist = player._fDist = [maxCost] * size
        stat = player._fStat = [0] * size
    else:
        for i in range(size):
            dist[i] = maxCost
            stat[i] = 0

    ccost = {}          # idx -> (cost, statusCode) memo, one dijkstra run only
    STUCK, WORKING, DONE = 0, 1, 2
    _S = {'stuck': STUCK, 'working': WORKING, 'done': DONE}

    def cost_at(idx, x, y):
        c = ccost.get(idx)
        if c is not None:
            return c
        cost, status = _conveyor_tile_cost(ct, player, Position(x, y), curEnd)
        if cost is not None and (x, y) in enemyThreatened:
            cost += 24
        c = (cost, _S[status])
        ccost[idx] = c
        return c

    buckets = {}
    maxBucket = 0
    teamCore = player.mapPf.teamCore
    corners = [teamCore, teamCore.add(Direction.SOUTH), teamCore.add(Direction.EAST),
               teamCore.add(Direction.SOUTH).add(Direction.EAST)]
    for c in corners:
        ci = c.y * w + c.x
        dist[ci] = 0
        stat[ci] = DONE
        b = buckets.get(0)
        if b is None:
            buckets[0] = [ci]
        else:
            b.append(ci)

    corners.sort(key=lambda corner: corner.distance_squared(myLoc))
    closestCorner = corners[0]
    convDirs, convLoop = _classify_conveyors(ct, player, myTeam)
    for key, (bPos, bDir, bLoaded) in convDirs.items():
        if convLoop[key]:
            continue
        cost = 28 if bLoaded else 4
        if bPos.distance_squared(closestCorner) > myLoc.distance_squared(closestCorner):
            cost += 24
        bi = bPos.y * w + bPos.x
        if cost < dist[bi]:
            dist[bi] = cost
            stat[bi] = DONE
            b = buckets.get(cost)
            if b is None:
                buckets[cost] = [bi]
            else:
                b.append(bi)
            if cost > maxBucket:
                maxBucket = cost

    endIdx = curEnd.y * w + curEnd.x
    d = 0
    while d <= maxBucket:
        bucket = buckets.get(d)
        if not bucket:
            d += 1
            continue
        hit = False
        while bucket:
            ci = bucket.pop()
            if dist[ci] < d:
                continue
            if ci == endIdx:
                hit = True
            cy, cx = divmod(ci, w)
            # WEST / EAST / NORTH / SOUTH by index arithmetic
            if cx > 0:
                ni = ci - 1
                cost, st = cost_at(ni, cx - 1, cy)
                if st != STUCK:
                    nd = d + cost
                    if nd < maxCost and nd < dist[ni]:
                        dist[ni] = nd
                        stat[ni] = st
                        b = buckets.get(nd)
                        if b is None:
                            buckets[nd] = [ni]
                        else:
                            b.append(ni)
                        if nd > maxBucket:
                            maxBucket = nd
            if cx + 1 < w:
                ni = ci + 1
                cost, st = cost_at(ni, cx + 1, cy)
                if st != STUCK:
                    nd = d + cost
                    if nd < maxCost and nd < dist[ni]:
                        dist[ni] = nd
                        stat[ni] = st
                        b = buckets.get(nd)
                        if b is None:
                            buckets[nd] = [ni]
                        else:
                            b.append(ni)
                        if nd > maxBucket:
                            maxBucket = nd
            if cy > 0:
                ni = ci - w
                cost, st = cost_at(ni, cx, cy - 1)
                if st != STUCK:
                    nd = d + cost
                    if nd < maxCost and nd < dist[ni]:
                        dist[ni] = nd
                        stat[ni] = st
                        b = buckets.get(nd)
                        if b is None:
                            buckets[nd] = [ni]
                        else:
                            b.append(ni)
                        if nd > maxBucket:
                            maxBucket = nd
            if cy + 1 < h:
                ni = ci + w
                cost, st = cost_at(ni, cx, cy + 1)
                if st != STUCK:
                    nd = d + cost
                    if nd < maxCost and nd < dist[ni]:
                        dist[ni] = nd
                        stat[ni] = st
                        b = buckets.get(nd)
                        if b is None:
                            buckets[nd] = [ni]
                        else:
                            b.append(ni)
                        if nd > maxBucket:
                            maxBucket = nd
        if hit:
            _publish(player, w, h, dist, stat, maxCost)
            return d
        d += 1
    _publish(player, w, h, dist, stat, maxCost)
    return 4096


_STATNAME = ('stuck', 'working', 'done')


def _publish(player, w, h, dist, stat, maxCost):
    """Write the flat result back into player.convMap, which route_conveyor reads."""
    cm = player.convMap
    if cm is None or len(cm) != w:
        cm = player.convMap = [[[maxCost, 'stuck'] for _ in range(h)] for _ in range(w)]
    for x in range(w):
        col = cm[x]
        base = x
        for y in range(h):
            cell = col[y]
            i = y * w + base
            cell[0] = dist[i]
            cell[1] = _STATNAME[stat[i]]


@_prof('convRoute')
def route_conveyor(ct: Controller, player, curEnd: Position):
    mapPf = player.mapPf
    if not mapPf.inMoveZone(curEnd):
        return
    myLoc = ct.get_position()
    _fill_conveyor_dist_table(ct, player, curEnd)
    convMap = player.convMap
    bestDist, bestNextDir = 4096, None
    for d in CARDINALS:
        nextPos = curEnd.add(d)
        if 0 <= nextPos.x < player.mapW and 0 <= nextPos.y < player.mapH:
            posDist = convMap[nextPos.x][nextPos.y][0]
            if posDist < bestDist and not _creates_loop(player, curEnd, d):
                bestNextDir, bestDist = d, posDist
            elif posDist == bestDist and bestNextDir is not None and not _creates_loop(player, curEnd, d):
                if myLoc.distance_squared(nextPos) < myLoc.distance_squared(curEnd.add(bestNextDir)):
                    bestNextDir, bestDist = d, posDist
    if bestNextDir is None:
        return
    tileId = ct.get_tile_building_id(curEnd)
    if tileId is not None:
        tTeam = ct.get_team(tileId)
        tType = ct.get_entity_type(tileId)
        if tTeam == ct.get_team() and tType in (EntityType.BARRIER, EntityType.GUNNER):
            if ct.can_destroy(curEnd):
                ct.destroy(curEnd)
                return
    if ct.can_build_conveyor(curEnd, bestNextDir):
        ct.build_conveyor(curEnd, bestNextDir)
    else:
        if myLoc == curEnd:
            for d in CARDINALS:
                if ct.can_move(d) and mapPf.inMoveZone(myLoc.add(d)):
                    ct.move(d)
                    return
        elif myLoc.distance_squared(curEnd) == 1:
            curId = ct.get_tile_building_id(curEnd)
            if curId is not None and ct.get_team(curId) == ct.get_team() and ct.get_entity_type(curId) == EntityType.CONVEYOR:
                if ct.can_destroy(curEnd):
                    ct.destroy(curEnd)
            elif curId is not None and ct.get_team(curId) != ct.get_team():
                if ct.can_fire(curEnd):
                    ct.fire(curEnd)
            return
        else:
            mapPf.moveTo(ct, curEnd)

# --- task executors (move/build for the state the arbiter picked) ---

def _heal_pos(ct: Controller, player, pos: Position):
    myLoc = ct.get_position()
    player.draw_state(ct, C_HEAL_BUILD, pos)
    d = myLoc.distance_squared(pos)
    if d == 1:
        if ct.can_heal(pos):
            ct.heal(pos)
        return
    if d < 1:
        player.mapPf.moveTo(ct, player.mapPf.teamCore)
        return
    player.mapPf.moveTo(ct, pos)

def _harvest_pos(ct: Controller, player, tile: Position):
    myLoc = ct.get_position()
    player.draw_state(ct, C_HARVEST, tile)
    if tile.distance_squared(myLoc) > 1:
        player.mapPf.moveTo(ct, tile)
    if tile.distance_squared(myLoc) < 1:
        player.mapPf.moveTo(ct, player.mapPf.teamCore)
    if ct.can_build_harvester(tile):
        ct.build_harvester(tile)
    # get_tile_building_id RAISES out of vision - it is not a sentinel query.
    if ct.is_in_vision(tile):
        bId = ct.get_tile_building_id(tile)
        if bId is not None:
            bType = ct.get_entity_type(bId)
            # NEVER attack a HARVESTER sitting on the ore. A builder does 2
            # dmg/shot, so grinding one down costs many turns for a tile the
            # owner can simply rebuild - and if it is OURS, destroying it throws
            # away working income. Only clear things that are cheap to remove.
            if bType != EntityType.HARVESTER:
                if ct.get_team(bId) != ct.get_team():
                    if ct.can_fire(tile):
                        ct.fire(tile)
                elif bType in (EntityType.GUNNER, EntityType.BARRIER):
                    if ct.can_destroy(tile):
                        ct.destroy(tile)


def route_conv_task(ct: Controller, player, myLoc, myTeam) -> bool:
    mapW, mapH = player.mapW, player.mapH
    teamCore = player.mapPf.teamCore
    bestScore, bestEnd = -1, None
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.CONVEYOR:
            continue
        bPos = ct.get_position(b)
        endTile = bPos.add(ct.get_direction(b))
        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and player.mapPf.inMoveZone(endTile):
            endId = ct.get_tile_building_id(endTile)
            enemyBarrier = (endId is not None and ct.get_team(endId) != myTeam
                            and ct.get_entity_type(endId) == EntityType.BARRIER)
            if enemyBarrier or player.mapPf.checkPassable(ct, endTile):
                if endId is not None and not enemyBarrier:
                    endType = ct.get_entity_type(endId)
                    endTeam = ct.get_team(endId)
                    if endType not in (EntityType.GUNNER, EntityType.BUILDER_BOT, EntityType.BARRIER) and endTeam == myTeam:
                        continue
                    if endType != EntityType.BARRIER and endTeam != myTeam:
                        continue
                bScore = max(0, (1 - endTile.distance_squared(teamCore) / 120)) * (1 - myLoc.distance_squared(bPos) / 40)
                if bScore > bestScore:
                    bestScore, bestEnd = bScore, endTile
    if bestEnd is not None:
        player.draw_state(ct, C_ROUTE_CONV, bestEnd)
        route_conveyor(ct, player, bestEnd)
        return True
    return False


def route_harv_task(ct: Controller, player, myLoc, myTeam) -> bool:
    teamCore = player.mapPf.teamCore
    farCorner = _far_core_corner(player)
    bestScore, bestEnd = -1, None
    for b in ct.get_nearby_buildings():
        if ct.get_entity_type(b) != EntityType.HARVESTER:
            continue
        bPos = ct.get_position(b)
        if myLoc.distance_squared(bPos) > 10:
            continue
        noTeamConv, workingSpots = _harvester_working_spots(ct, player, myTeam, bPos, farCorner)
        if noTeamConv and workingSpots:
            workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
            bScore = (max(0, 1 - (workingSpots[0].distance_squared(teamCore) / 220))
                      * max(0, 1 - (myLoc.distance_squared(bPos) / 60)))
            try:
                if ct.get_team(b) != myTeam and ct.get_current_round() > 50:
                    bScore *= 1.2
            except Exception:
                pass
            if bScore > bestScore:
                bestScore, bestEnd = bScore, workingSpots[0]
    if bestEnd is not None:
        player.draw_state(ct, C_ROUTE_HARV, bestEnd)
        route_conveyor(ct, player, bestEnd)
        return True
    return False


def protectCore(ct: Controller, player, target: Position):
    player.draw_state(ct, C_FIGHT_TURRET, target)
    myLoc = ct.get_position()
    if ct.get_global_ammo() > 0:
        # Mirrors attack_harvester_with_gunner: seat a gunner against THIS target.
        # (find_gunner_spot is NOT usable here - it builds its candidate seats from
        # get_attackable_tiles(), i.e. the corners of the ENEMY core, so it would
        # send a defender across the map instead of covering the turret that is
        # shelling us.)
        # attack.py does `from eco import closest_claimant`, so a module-level
        # `import attack` here is circular - import inside the function instead.
        import attack
        myTeam = ct.get_team()
        covered = attack.covered_tiles_by_turrets(ct, myTeam)
        # Coverage alone no longer closes the case for a core-sheller: the
        # arbiter re-bids these until 2 gunners are in range (wave overkill),
        # so seat a second gunner instead of walking in to melee for 2.
        _thin = False
        _tc = player.mapPf.teamCore
        if (target.x, target.y) in covered and _tc is not None:
            _coreTiles = [_tc, _tc.add(Direction.EAST), _tc.add(Direction.SOUTH),
                          _tc.add(Direction.SOUTH).add(Direction.EAST)]
            if any(t.distance_squared(target) <= 32 for t in _coreTiles):
                _nCover = sum(1 for b in ct.get_nearby_buildings()
                              if ct.get_team(b) == myTeam
                              and ct.get_entity_type(b) == EntityType.GUNNER
                              and ct.get_position(b).distance_squared(target) <= 13)
                _thin = _nCover < 2
        if (target.x, target.y) not in covered or _thin:
            enemyCoverage = attack.enemy_turret_coverage(ct, player)
            teamCore = player.mapPf.teamCore
            # ANTI-ARMOR (OpenSverige fb981e12, frostgate t84): a core-sheller
            # with an adjacent enemy barrier is ARMORED - gunners physically
            # cannot hit it through the shell (direct fire), so seat a SENTINEL
            # instead: indirect fire kills it through the barriers in 3 hits,
            # and off the target's facing line it takes zero return fire.
            # WIDENED (roster matrix: jav1 32%, v108base 34%): entomb-style
            # sieges park the mortar 1-2 tiles BEHIND their own barrier wall,
            # so adjacency (<=2) never fired and gunners ground at blocked
            # rays. Any enemy barrier within dist-sq 8 of the sheller marks it
            # armored -> sentinel seat (indirect fire ignores the wall).
            armored = False
            for _b in ct.get_nearby_buildings():
                if (ct.get_team(_b) != myTeam
                        and ct.get_entity_type(_b) == EntityType.BARRIER
                        and ct.get_position(_b).distance_squared(target) <= 8):
                    armored = True
                    break
            if armored:
                from mapPathfinding import sentinelLines
                seats = player.mapPf.gunnerSpots(target, player.mapW, player.mapH,
                                                 blocked=False, lines=sentinelLines)
                affordable = ct.get_global_resources() >= ct.get_sentinel_cost()
            else:
                seats = player.mapPf.gunnerSpots(target, player.mapW, player.mapH, True)
                affordable = True
            best, bestScore = None, None
            for spotPos, spotDir in seats:
                if not ct.is_in_vision(spotPos):
                    continue
                if ct.get_tile_building_id(spotPos) is not None:
                    continue
                if ct.get_tile_env(spotPos) == Environment.WALL:
                    continue
                seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
                if seatCov > 0.5:
                    continue
                # DEFENSIVE flip: the harvester version prefers seats FAR from our
                # core (it is raiding). A seat covering a turret that threatens us
                # wants to be NEAR our core instead.
                # MUTUAL SUPPORT (frostgate-vs-jav1 autopsy: every solo seat we
                # took died in 2-9 turns to their gunner mass): prefer seats our
                # EXISTING turrets already cover, so whatever attacks the new
                # gunner gets shot back. Solo seats only when nothing covered
                # exists.
                unsupported = 0 if (spotPos.x, spotPos.y) in covered else 1
                score = (seatCov,
                         unsupported,
                         spotPos.distance_squared(teamCore) if teamCore is not None else 0,
                         myLoc.distance_squared(spotPos))
                if bestScore is None or score < bestScore:
                    bestScore, best = score, (spotPos, spotDir)
            if best is not None and affordable:
                gunnerSpot, gunnerDir = best
                player.draw_state(ct, C_FIGHT_TURRET, gunnerSpot)
                if armored:
                    if ct.can_build_sentinel(gunnerSpot, gunnerDir):
                        ct.build_sentinel(gunnerSpot, gunnerDir)
                elif ct.can_build_gunner(gunnerSpot, gunnerDir):
                    ct.build_gunner(gunnerSpot, gunnerDir)
                myDist = myLoc.distance_squared(gunnerSpot)
                if myDist < 1:
                    player.mapPf.moveTo(ct, player.mapPf.teamCore)
                elif myDist > 1:
                    player.mapPf.moveTo(ct, gunnerSpot)
                else:
                    return

    if ct.can_fire(target):
        ct.fire(target)
        return
    player.mapPf.moveTo(ct, target)


def _heal_core_task(ct: Controller, player):
    myLoc = ct.get_position()
    teamCore = player.mapPf.teamCore
    if teamCore is None:
        return
    coreTiles = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
                 teamCore.add(Direction.SOUTH).add(Direction.EAST)]
    for tile in coreTiles:
        if myLoc.distance_squared(tile) == 1 and ct.can_heal(tile):
            ct.heal(tile)
            return
    if teamCore is not None and myLoc != teamCore:
        player.mapPf.moveTo(ct, teamCore)


@_prof('eco')
def run(ct: Controller, player):
    myLoc = ct.get_position()
    myTeam = ct.get_team()
    covered = player.covered_tiles(ct)
    enemyTurrets = []
    coreId = None
    # TLE BUDGET: the ONE building sweep for this turn - (id, team, type, pos)
    # tuples feed every scorer below so none of them re-sweeps (each re-sweep
    # was ~3 engine calls per visible building, x4 scorers, x5 builders).
    blds = []
    for b in ct.get_nearby_buildings():
        bTeam = ct.get_team(b)
        bType = ct.get_entity_type(b)
        bPos = ct.get_position(b)
        blds.append((b, bTeam, bType, bPos))
        if bTeam == myTeam and bType == EntityType.CORE:
            coreId = b
        elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
            enemyTurrets.append(bPos)
    # The core broadcasts up to 2 enemy turret offsets in slot 7 each turn -
    # turrets nobody nearby has answered yet. Without folding these into
    # enemyTurrets, a builder only ever responds to what it can personally
    # see, and the whole point of the broadcast is reacting to what it can't.
    enemyTurretKeys = set((g.x, g.y) for g in enemyTurrets)
    for g in broadcast_gunners(ct, player):
        if (g.x, g.y) not in enemyTurretKeys and (g.x, g.y) not in covered:
            if myLoc.distance_squared(g) <= 32:   # only answer broadcasts we're close to
                enemyTurretKeys.add((g.x, g.y))
                enemyTurrets.append(g)

    uncoveredTurrets = [g for g in enemyTurrets if (g.x, g.y) not in covered]

    # WAVE OVERKILL: a turret that can shell our CORE (sentinel range-sq 32
    # of the 2x2 footprint) stays a live threat until TWO of our gunners have
    # it in range. One covering gunner grinds 6 shots through ammo gaps while
    # the sentinel does 9 hp/turn - the Bisons autopsy had one "covered" wave
    # sentinel survive 42 turns for 378 core damage. Range check ignores
    # facing: a seated gunner can rotate.
    _tc = player.mapPf.teamCore
    if _tc is not None:
        _coreTiles = [_tc, _tc.add(Direction.EAST), _tc.add(Direction.SOUTH),
                      _tc.add(Direction.SOUTH).add(Direction.EAST)]
        _myGuns = [bPos for (_b, bTeam, bType, bPos) in blds
                   if bTeam == myTeam and bType == EntityType.GUNNER]
        for _g in enemyTurrets:
            if (_g.x, _g.y) in covered and any(t.distance_squared(_g) <= 32 for t in _coreTiles):
                if sum(1 for p in _myGuns if p.distance_squared(_g) <= 13) < 2:
                    uncoveredTurrets.append(_g)

    # ECONOMY BOOTSTRAP (suppress-passives form).
    # Measured on royale: the opening burns all 500 Ti by r60 and harvester
    # cost SCALES with unit count (24 -> 56), so builders reach the ore at
    # r120 unable to pay. By the time Ti recovers at r180 the core has chip
    # damage and healCore (flat 6.0) outbids every economy state forever ->
    # ZERO harvesters, 0 mined over 1000 turns, tiebreak loss 0-2390. Clamp
    # hits it in 3 of 6 royale games; this bot in 1 of 6.
    #
    # An earlier attempt BOOSTED harvest above everything (S_BOOTSTRAP=12).
    # That measured 31.1% - catastrophic - for two compounding reasons:
    # it outranked protect, so builders ignored turrets shelling our core;
    # and it outranked routeConv/routeHarv, so harvesters got built but never
    # CONNECTED. An unconnected harvester earns nothing, so income never
    # arrived, the flag never cleared, and the bot deadlocked in permanent
    # bootstrap mode (nordkap 0/24, drumlin 0/24).
    #
    # So do not re-rank economy at all. The economy ladder is already correct
    # - routing SHOULD follow harvesting. Only the PASSIVE states are the
    # problem, so while the team has no income at all, healCore/healBuild
    # simply stop bidding, and the existing ordering does the rest. Active
    # defense (protect) is untouched, and a core actually dying still gets
    # nursed via BOOT_CORE_HP.
    booting = False
    try:
        if ct.read_store(SLOT_BOOTSTRAP) == 1 and coreId is not None:
            booting = ct.get_hp(coreId) > BOOT_CORE_HP * ct.get_max_hp(coreId)
    except Exception:
        booting = False

    scores = {
        'protect': scoreProtectCore(ct, myLoc, uncoveredTurrets),
        'recall': (scoreRecall(ct, player, myLoc, ct.read_store(SLOT_RECALL_ECO))
                   if RECALL_STATE else (0, None)),
        'healCore': [0, None] if booting else scoreHealCore(ct, coreId, player.mapPf.teamCore),
        'healBuild': [0, None] if booting else score_heal_build(ct, player, myLoc, blds),
        'ring': score_ring(ct, player, myLoc, myTeam),
        'routeConv': score_route_conv(ct, player, myLoc, myTeam, blds),
        'routeHarv': score_route_harv(ct, player, myLoc, myTeam, blds),
        'harvest': score_harvest(ct, player, myLoc, myTeam),
        # every tie at the 1.0 economy floor; moved above routeConv it would
        # silently preempt every marginal conveyor, harvester and ore tile.
        'explore': scoreExplore(ct, player, myLoc),
        'picket': scorePicket(ct, player, myLoc),
        'taxi': scoreTaxi(ct, player, myLoc),
    }
    while True:
        bestState = max(scores, key=lambda k: scores[k][0])
        bestScore, bestPos = scores[bestState]
        if bestState != 'ring' or bestScore <= 0 or bestPos is None:
            break
        if ring_task(ct, player, myLoc, myTeam):
            return
        scores['ring'] = (0, None)

    if bestScore <= 0 or bestPos is None:
        if player.mapPf.teamCore is not None:
            player.draw_state(ct, C_IDLE, player.mapPf.teamCore)
            if not ct.is_in_vision(player.mapPf.teamCore):
                player.mapPf.moveTo(ct, player.mapPf.teamCore)
        return

    if bestState == 'protect':
        protectCore(ct, player, bestPos)
    elif bestState == 'picket':
        picket_task(ct, player, myLoc, bestPos)
    elif bestState == 'taxi':
        taxi_task(ct, player, myLoc)
    elif bestState == 'recall':
        player.answer_recall(ct, myLoc)
    elif bestState == 'healCore':
        player.draw_state(ct, C_HEAL_CORE, player.mapPf.teamCore)
        _heal_core_task(ct, player)
    elif bestState == 'healBuild':
        _heal_pos(ct, player, bestPos)
    elif bestState == 'routeConv':
        # NOT route_conveyor(bestPos) - see route_conv_task's docstring
        route_conv_task(ct, player, myLoc, myTeam)
    elif bestState == 'routeHarv':
        route_harv_task(ct, player, myLoc, myTeam)
    elif bestState == 'harvest':
        _harvest_pos(ct, player, bestPos)
    elif bestState == 'explore':
        player.draw_state(ct, C_EXPLORE, bestPos)
        player.mapPf.moveTo(ct, bestPos)
