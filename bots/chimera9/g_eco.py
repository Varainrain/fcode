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
from g_mapPathfinding import CARDINALS, DIRECTIONS


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


S_HEAL_CORE = _fp("S_HEAL_CORE", 6.0)
S_RC_FLOOR = _fp("S_RC_FLOOR", 1.0)   # shared floor across routeConv/routeHarv/harvest
S_RC_CAP = _fp("S_RC_CAP", 4.0)
S_RH_FLOOR = _fp("S_RH_FLOOR", 1.0)
S_RH_CAP = _fp("S_RH_CAP", 3.2)
S_HV_FLOOR = _fp("S_HV_FLOOR", 1.0)
S_HV_CAP = _fp("S_HV_CAP", 2.2)
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

def score_heal_build(ct: Controller, player, myLoc): # 6.25 - 8
    myTeam = ct.get_team()
    bestScore, bestPos = 0, None
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        bType = ct.get_entity_type(b)
        if bType not in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR, EntityType.HARVESTER):
            continue
        missing = ct.get_max_hp(b) - ct.get_hp(b)
        if missing < 3:
            continue
        bPos = ct.get_position(b)
        if not closest_claimant(player.allyBuilders, player.myId, myLoc, bPos):
            continue
        score = max(6.25, 8 * (missing / ct.get_max_hp(b)) * (1 - (myLoc.distance_squared(bPos) / 120)))
        if score > bestScore:
            bestScore, bestPos = score, bPos
    return bestScore, bestPos


def _far_core_corner(player):
    core = player.mapPf.teamCore
    center = Position(player.mapW // 2, player.mapH // 2)
    corners = [core, core.add(Direction.EAST), core.add(Direction.SOUTH),
               core.add(Direction.SOUTH).add(Direction.EAST)]
    return max(corners, key=lambda corner: corner.distance_squared(center))


def score_route_conv(ct: Controller, player, myLoc, myTeam):
    mapW, mapH = player.mapW, player.mapH
    teamCore = player.mapPf.teamCore
    farCorner = _far_core_corner(player)
    bestScore, bestEnd = 0, None
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


def score_route_harv(ct: Controller, player, myLoc, myTeam):
    teamCore = player.mapPf.teamCore
    farCorner = _far_core_corner(player)
    bestScore, bestEnd = 0, None
    for b in ct.get_nearby_buildings():
        if ct.get_entity_type(b) != EntityType.HARVESTER:
            continue
        bPos = ct.get_position(b)
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
                    if ct.get_tile_building_id(tile) is not None:
                        player.oreTaken[(x, y)] = curRound
                    else:
                        player.oreTaken.pop((x, y), None)
                else:
                    seen = player.oreTaken.get((x, y))
                    if seen is not None and curRound - seen <= 100:
                        continue
                if player.mapPf.inMoveZone(tile) and (x, y) not in enemyThreatened:
                    dist = teamCore.distance_squared(tile)
                    myDist = myLoc.distance_squared(tile)
                    tileScore = max(S_HV_FLOOR, S_HV_CAP * (max(0, 160 - dist) / 160) * (max(0, 220 - myDist) / 220))
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
    import heapq
    myTeam = ct.get_team()
    myLoc = ct.get_position()
    player.mapPf._myLoc = myLoc
    enemyThreatened = player.mapPf.enemyTurretThreatenedTiles(ct)
    w, h = player.mapW, player.mapH
    maxCost = (w + h) * (24 + 24) + 48
    if player.convMap is None or len(player.convMap) != w:
        player.convMap = [[[maxCost, 'stuck'] for _ in range(h)] for _ in range(w)]
    convMap = player.convMap
    for x in range(w):
        for y in range(h):
            convMap[x][y] = [maxCost, 'stuck']
    buckets = [[] for _ in range(maxCost)]
    teamCore = player.mapPf.teamCore
    tL = teamCore
    bL = teamCore.add(Direction.SOUTH)
    tR = teamCore.add(Direction.EAST)
    bR = teamCore.add(Direction.SOUTH).add(Direction.EAST)
    corners = [tL, bL, tR, bR]
    for c in corners:
        convMap[c.x][c.y] = [0, 'done']
        buckets[0].append(c)
    corners.sort(key=lambda corner: corner.distance_squared(myLoc))
    closestCorner = corners[0]
    convDirs, convLoop = _classify_conveyors(ct, player, myTeam)
    for key, (bPos, bDir, bLoaded) in convDirs.items():
        if convLoop[key]:
            continue
        cost = 28 if bLoaded else 4
        if bPos.distance_squared(closestCorner) > myLoc.distance_squared(closestCorner):
            cost += 24
        if cost < convMap[bPos.x][bPos.y][0]:
            convMap[bPos.x][bPos.y] = [cost, 'done']
            buckets[cost].append(bPos)
    for dist in range(maxCost):
        bucket = buckets[dist]
        hitBucket = False
        while bucket:
            cur = bucket.pop()
            if convMap[cur.x][cur.y][0] < dist:
                continue
            if cur == curEnd:
                hitBucket = True
            for d in CARDINALS:
                nextTile = cur.add(d)
                nx, ny = nextTile.x, nextTile.y
                if 0 <= nx < w and 0 <= ny < h:
                    cost, status = _conveyor_tile_cost_safe(ct, player, nextTile, enemyThreatened, curEnd)
                    if status != 'stuck':
                        newDist = dist + cost
                        if newDist < maxCost and newDist < convMap[nx][ny][0]:
                            convMap[nx][ny] = [newDist, status]
                            buckets[newDist].append(nextTile)
        if hitBucket:
            return dist
    return 4096

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
        import g_attack as attack
        myTeam = ct.get_team()
        covered = attack.covered_tiles_by_turrets(ct, myTeam)
        if (target.x, target.y) not in covered:
            enemyCoverage = attack.enemy_turret_coverage(ct, player)
            teamCore = player.mapPf.teamCore
            best, bestScore = None, None
            for spotPos, spotDir in player.mapPf.gunnerSpots(
                    target, player.mapW, player.mapH, True):
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
                score = (seatCov,
                         spotPos.distance_squared(teamCore) if teamCore is not None else 0,
                         myLoc.distance_squared(spotPos))
                if bestScore is None or score < bestScore:
                    bestScore, best = score, (spotPos, spotDir)
            if best is not None:
                gunnerSpot, gunnerDir = best
                player.draw_state(ct, C_FIGHT_TURRET, gunnerSpot)
                if ct.can_build_gunner(gunnerSpot, gunnerDir):
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
    for b in ct.get_nearby_buildings():
        bTeam = ct.get_team(b)
        bType = ct.get_entity_type(b)
        if bTeam == myTeam and bType == EntityType.CORE:
            coreId = b
        elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
            enemyTurrets.append(ct.get_position(b))
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
        'healBuild': [0, None] if booting else score_heal_build(ct, player, myLoc),
        'routeConv': score_route_conv(ct, player, myLoc, myTeam),
        'routeHarv': score_route_harv(ct, player, myLoc, myTeam),
        'harvest': score_harvest(ct, player, myLoc, myTeam),
        # every tie at the 1.0 economy floor; moved above routeConv it would
        # silently preempt every marginal conveyor, harvester and ore tile.
        'explore': scoreExplore(ct, player, myLoc),
    }
    bestState = max(scores, key=lambda k: scores[k][0])
    bestScore, bestPos = scores[bestState]

    if bestScore <= 0 or bestPos is None:
        if player.mapPf.teamCore is not None:
            player.draw_state(ct, C_IDLE, player.mapPf.teamCore)
            if not ct.is_in_vision(player.mapPf.teamCore):
                player.mapPf.moveTo(ct, player.mapPf.teamCore)
        return

    if bestState == 'protect':
        protectCore(ct, player, bestPos)
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
