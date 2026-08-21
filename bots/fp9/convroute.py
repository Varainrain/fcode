"""route_conveyor and its distance fill, carried VERBATIM from bots/ecoExample.

Kept unchanged on purpose: this fill was the historical TLE hot spot (402 calls
per game driving 1.27M tile-cost evaluations, worst builder turn 97ms against a
10ms budget) and has already been rewritten flat and proven behaviour-identical by
an in-game differential probe. Do not edit it.

It takes `player` as its second argument, which is the Player instance (self at the
call site), and reads player.convMap / convDirs / convLoop / _fDist / _fStat.
"""

import time
from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS, DIRECTIONS


def _prof(name):
    """No-op stand-in for ecoExample's profiling decorator, so the block below
    stays byte-identical to its measured original."""
    def deco(fn):
        return fn
    return deco

# =====================================================================
# CARRIED OVER VERBATIM from bots/ecoExample/eco.py lines 790-1138.
# Do not edit: the flat-array rewrite took a 97ms builder turn down to
# something viable and was verified behaviour-identical in-game.
# =====================================================================
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
            return CONV_GUNNER_COST, 'working'
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
        cost = CONV_JOIN_LOADED if bLoaded else CONV_JOIN_FREE
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
                # Another bot may have already built this exact segment. Replace it
                # ONLY if its facing is wrong - destroying a correctly-facing
                # conveyor makes two builders on one chain delete each other's work
                # in a loop, which is what the replay showed.
                if ct.get_direction(curId) != bestNextDir:
                    if ct.can_destroy(curEnd):
                        ct.destroy(curEnd)
            elif curId is not None and ct.get_team(curId) != ct.get_team():
                if ct.can_fire(curEnd):
                    ct.fire(curEnd)
            return
        else:
            mapPf.moveTo(ct, curEnd)

# --- task executors (move/build for the state the arbiter picked) ---

# =====================================================================
# NEW CODE (fp1). Everything below is written for this bot.
# =====================================================================
