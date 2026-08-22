"""Map pathfinding for OogwayRush.

Generic tile/grid primitives only: map sharing, symmetry-based enemy-core
discovery, gunner/sentinel spot generation, and unit movement. Conveyor
routing lives in eco.py now (it's an economy-arbiter state, not a grid
primitive) - this file no longer tracks conveyorMap/convDirs/convLoop.

Base: fcode/bots/v60's mapPathfinding.py (same lineage as the current bot
and fcode/bots/v80 - identical Dijkstra-bucket conveyor algorithm, same
x*32+y position packing, same core cost formula, before this file dropped
the conveyor-specific pieces). Two fixes ported forward from the current
lineage on top of that base, because they're small, isolated, and already
proven correct: the checkTileSymmetry stale-guard fix, and mirrorKnownTile
(free terrain-mirroring onto symmetry counterparts). Also added: sentinelLines
+ gunnerSpots(lines=) (needed for sentinel placement, which v60 never had),
and moveTo's anti-clump tiebreak (proven, isolated, unrelated to conveyors).
"""

import heapq
import os
import random
import time

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
cardDeltas = [(d.delta()[0], d.delta()[1]) for d in CARDINALS]

# squared-distance radius of the home-corner move zone (see inMoveZone).
DEFEND_RADIUS2 = int(os.environ.get("DEFEND_RADIUS2", "34"))


def _prof(name):
    def deco(fn):
        def wrapper(self, ct, *a, **k):
            t = time.monotonic()
            r = fn(self, ct, *a, **k)
            self._acc(name, time.monotonic() - t)
            return r
        return wrapper
    return deco

symSlot = 8  # slots 0-7 are taken (0 numSpawned, 1-6 map sharing, 7 team core loc)
symBits = {'flipX': 1, 'flipY': 2, '180': 4}  # store *killed* symmetries so 0 = nothing ruled out

openCost = 1
barrierCost = 8
gunnerCost = 24  # gunners cost more, so higher

tileTypes = {  # limited to 4 types to maximize caching ability
    Environment.EMPTY: 0,
    Environment.ORE_TITANIUM: 1,
    Environment.WALL: 2,
    'Unpassable': 3,
}

# facing -> (dx, dy, reach). gunnerLines for a gunner's real range (range-sq
# 13): floor(sqrt(13))=3 cardinal, floor(sqrt(13/2))=2 diagonal.
gunnerLines = []
for _d in CARDINALS:
    _dx, _dy = _d.delta()
    gunnerLines.append([_dx, _dy, 3, _d])
for _d in [Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST]:
    _dx, _dy = _d.delta()
    gunnerLines.append([_dx, _dy, 2, _d])

# Same construction but for a sentinel's real range (range-sq 32 vs gunner's
# 13): floor(sqrt(32))=5 cardinal, floor(sqrt(32/2))=4 diagonal. v60 never
# had this table - reusing gunnerLines for sentinel placement would silently
# confine a sentinel to gunner-safe standoff distances.
sentinelLines = []
for _d in CARDINALS:
    _dx, _dy = _d.delta()
    sentinelLines.append([_dx, _dy, 5, _d])
for _d in [Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST]:
    _dx, _dy = _d.delta()
    sentinelLines.append([_dx, _dy, 4, _d])


class MapPathfinder:
    def __init__(self):
        self.fullMap = None
        self.newTiles = []
        self.seenTiles = None
        self.myNum = -1
        self.teamCore = None
        self._tcCache = {}
        self.distMap = None
        self.distStamp = None
        self.fillCount = 0
        self._myLoc = None
        self.mapW = None
        self.mapH = None
        self.stuckTurns = 0
        self.constrainedHome = None
        self.constrainedFarCorner = None
        self.mapChanged = True
        self.prevTarget = None
        self.allSymmetries = ['flipX', 'flipY', '180']
        self.allEnemyCore = {}
        self.enemyCorePos = None
        self.mapSymmetry = None
        # (x,y) -> sym for every tile whose value came from mirroring a
        # DIRECTLY/shared-observed tile, not from our own vision. Ground
        # truth always wins over an inference and is never recorded here;
        # killSymmetry() reverts these if the symmetry it used gets disproven.
        self.mirrorProvenance = {}
        self.enemyThreatCache = set()
        self.enemyThreatRound = -1
        self.enemyConvSeen = set()
        self.freshEnemyCuts = {}
        self._prof = {'turns': 0}

    def _acc(self, key, dt):
        self._prof[key] = self._prof.get(key, 0) + dt

    def _noteEnemyConvDeaths(self, ct: Controller):
        """CUT-AND-CAP support: track visible ENEMY conveyor tiles; when one
        disappears, remember the tile for a few rounds so a nearby builder
        can cap it with a barrier before it gets rebuilt in place."""
        rnd = ct.get_current_round()
        gone = []
        for txy in list(self.enemyConvSeen)[:60]:
            t = Position(txy[0], txy[1])
            try:
                if not ct.is_in_vision(t):
                    continue
                bid = ct.get_tile_building_id(t)
                if bid is None:
                    gone.append(txy)
            except Exception:
                continue
        for txy in gone:
            self.enemyConvSeen.discard(txy)
            self.freshEnemyCuts[txy] = rnd
        for txy in [k for k, v in self.freshEnemyCuts.items() if rnd - v > 4]:
            del self.freshEnemyCuts[txy]

    def setupMap(self, ct: Controller):
        self._noteEnemyConvDeaths(ct)
        self.mapChanged = False
        curRound = ct.get_current_round()
        if self.teamCore is None:
            for i in ct.get_nearby_buildings():
                if ct.get_entity_type(i) == EntityType.CORE and ct.get_team(i) == ct.get_team():
                    self.teamCore = ct.get_position(i)

        if self.myNum == -1:
            self.myNum = ct.read_store(0)
        if self.mapW is None or self.mapH is None:
            self.mapW = ct.get_map_width()
            self.mapH = ct.get_map_height()
        if self.distMap is None:
            self.distMap = [[4096 for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.distStamp is None:
            self.distStamp = [[0 for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.fullMap is None:
            self.fullMap = [[-1 for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.seenTiles is None:
            self.seenTiles = [[False for _ in range(self.mapH)] for _ in range(self.mapW)]
        self.getNewTiles(ct)
        self.shareTiles(ct, curRound)
        self.updateBoard(ct)
        self.updateSymmetry(ct)
        # (profiling print removed: stdout is captured into the replay)

    def checkPassable(self, ct: Controller, tile: Position):
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None and not ct.is_tile_passable(tile):
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam != ct.get_team() or (tType != EntityType.BARRIER and tType != EntityType.GUNNER):
                return False
        if ct.is_in_vision(tile):
            bbId = ct.get_tile_builder_bot_id(tile)
            if bbId is not None and ct.get_team(bbId) != ct.get_team():
                return False
        return True

    @_prof('getTiles')
    def getNewTiles(self, ct: Controller):
        for tile in ct.get_nearby_tiles():
            x = tile.x
            y = tile.y
            tileEnv = ct.get_tile_env(tile)
            # PHANTOM WALLS. checkPassable is False whenever an enemy
            # BUILDER is standing on a tile, and that verdict was cached in
            # fullMap and then MIRRORED to the far side of the map, where we
            # may never look again - a unit that walked past for one turn
            # became a permanent wall in our head, and the spear's builder
            # got stuck against walls that were not there. Only real
            # buildings block, and conveyors/splitters never do (the engine
            # lets a builder stand on them).
            blocked = False
            if ct.is_in_vision(tile):
                bId = ct.get_tile_building_id(tile)
                if bId is not None:
                    bt = ct.get_entity_type(bId)
                    blocked = bt not in (EntityType.CONVEYOR,
                                         EntityType.SPLITTER)
            if blocked and tileEnv != Environment.WALL:
                tileEnv = 'Unpassable'
            tileType = tileTypes.get(tileEnv)
            if self.seenTiles[x][y] == False or self.fullMap[x][y] != tileType:
                if tileEnv != 'Unpassable':
                    # buildings are not symmetric - never mirror them
                    self.checkTileSymmetry(tile, tileType)
                    self.mirrorKnownTile(tile, tileType)
                self.seenTiles[x][y] = True
                self.newTiles.append([Position(x, y), tileType])
                self.mapChanged = True
            self.fullMap[x][y] = tileType

    def shareTiles(self, ct: Controller, curRound):
        boundedRound = curRound % ct.read_store(0) + 1
        if boundedRound == self.myNum:
            self.newTiles.sort(key=lambda t: t[0].distance_squared(self.teamCore), reverse=True)
            combined = 0
            needToRemove = []
            for i in range(16):
                if i < len(self.newTiles):
                    cachedPos, cachedType = self.newTiles[i]
                    needToRemove.append(self.newTiles[i])
                    val = ((cachedPos.x & 0x1F) << 7) | ((cachedPos.y & 0x1F) << 2) | (cachedType & 0x3)
                else:
                    val = 0xFFF
                combined = (combined << 12) | val
            for i in range(6):
                part = (combined >> (32 * i)) & 0xFFFFFFFF
                ct.write_store(6 - i, part)
            for i in needToRemove:
                self.newTiles.remove(i)

    @_prof('board')
    def updateBoard(self, ct: Controller):
        combined = 0
        for i in range(1, 7):
            part = ct.read_store(i)
            combined = (combined << 32) | part
        for i in range(16):
            val = (combined >> (12 * (15 - i))) & 0xFFF
            if val == 0xFFF:
                continue
            x = (val >> 7) & 0x1F
            y = (val >> 2) & 0x1F
            t_type = val & 0x3
            if self.mapW is not None and (x >= self.mapW or y >= self.mapH):
                continue
            if not self.seenTiles[x][y] or self.fullMap[x][y] != t_type:
                self.checkTileSymmetry(Position(x, y), t_type)
                self.mirrorKnownTile(Position(x, y), t_type)
                self.seenTiles[x][y] = True
                self.fullMap[x][y] = t_type
                self.mapChanged = True
            self.newTiles = [t for t in self.newTiles if not (t[0].x == x and t[0].y == y)]

    def tileCost(self, ct: Controller, tile: Position):
        # MEMOISED per fillInDistTable run - pure function of the tile given
        # fixed engine state, but evaluated once per INCOMING EDGE (1.27M calls
        # per game measured on a 30x30).
        k = (tile.x, tile.y)
        c = self._tcCache.get(k)
        if c is not None:
            return c[0]
        r = self._tileCostUncached(ct, tile)
        self._tcCache[k] = (r,)
        return r

    def _tileCostUncached(self, ct: Controller, tile: Position):
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal > 1:
            return None
        myLoc = self._myLoc
        dx = tile.x - myLoc.x
        dy = tile.y - myLoc.y
        if dx * dx + dy * dy > 20:
            return openCost
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None:
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                return barrierCost
            elif tTeam == ct.get_team() and tType == EntityType.GUNNER:
                return gunnerCost
            elif ct.is_tile_passable(tile) == False:
                return 4096
        return openCost

    @_prof('dist')
    def fillInDistTable(self, ct: Controller, targetLoc: Position):
        self._tcCache = {}
        w, h = self.mapW, self.mapH
        maxCost = (w + h) * (barrierCost + 1) + 8
        self.fillCount += 1
        fill = self.fillCount

        myLoc = ct.get_position()
        self._myLoc = myLoc
        mx, my = myLoc.x, myLoc.y

        distMap = self.distMap
        distStamp = self.distStamp
        distMap[targetLoc.x][targetLoc.y] = 0
        distStamp[targetLoc.x][targetLoc.y] = fill

        tx, ty = targetLoc.x, targetLoc.y
        heap = [(abs(tx - mx) + abs(ty - my), 0, tx, ty)]
        heappush = heapq.heappush
        heappop = heapq.heappop

        # NEIGHBOUR-COMPLETE EXIT.
        # The original returned the moment myLoc was popped. That leaves the
        # OTHER cardinal neighbours of myLoc unstamped, and moveTo reads an
        # unstamped tile as 4096 while its own bestDist starts at 4096 - so
        # `4096 < 4096` is False and those tiles are never even considered.
        # Net effect: one ally builder standing on the optimal next step froze
        # the bot completely, with three other legal moves available. Invisible
        # in a one-builder rush (nothing is ever in the way); MEASURED here as
        # every single failed harvest attempt - 12 to 18 per bot per 100 rounds
        # on a 10x10 with 5 builders, which stopped the economy dead.
        # The fix expands until all four neighbours are POPPED, i.e. exactly
        # what moveTo reads and nothing more. Popping is the right test: the
        # manhattan heuristic is consistent given step costs >= 1, so a node's
        # distance is final when it is popped.
        need = set()
        for dx, dy in cardDeltas:
            nx, ny = mx + dx, my + dy
            if 0 <= nx < w and 0 <= ny < h:
                need.add((nx, ny))
        found = None

        while heap:
            _, g, cx, cy = heappop(heap)
            if distStamp[cx][cy] == fill and distMap[cx][cy] < g:
                continue
            need.discard((cx, cy))
            if cx == mx and cy == my and found is None:
                found = g
            if found is not None and not need:
                return found
            for dx, dy in cardDeltas:
                nx = cx + dx
                ny = cy + dy
                if 0 <= nx < w and 0 <= ny < h:
                    stepCost = self.tileCost(ct, Position(nx, ny))
                    if stepCost is not None:
                        newG = g + stepCost
                        if newG < maxCost and (distStamp[nx][ny] != fill or newG < distMap[nx][ny]):
                            distMap[nx][ny] = newG
                            distStamp[nx][ny] = fill
                            heappush(heap, (newG + abs(nx - mx) + abs(ny - my), newG, nx, ny))
        return found if found is not None else 4096

    def enemyTurretThreatenedTiles(self, ct: Controller):
        curRound = ct.get_current_round()
        if self.enemyThreatRound == curRound:
            return self.enemyThreatCache
        myTeam = ct.get_team()
        threatened = set()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType == EntityType.GUNNER:
                bPos = ct.get_position(b)
                for d in DIRECTIONS:
                    for t in ct.get_attackable_tiles_from(bPos, d, EntityType.GUNNER):
                        threatened.add((t.x, t.y))
            elif bType == EntityType.SENTINEL:
                bPos = ct.get_position(b)
                bDir = ct.get_direction(b)
                for t in ct.get_attackable_tiles_from(bPos, bDir, EntityType.SENTINEL):
                    threatened.add((t.x, t.y))
        self.enemyThreatCache = threatened
        self.enemyThreatRound = curRound
        return threatened

    def setMoveZone(self, home: Position, farCorner: Position):
        self.constrainedHome = home
        self.constrainedFarCorner = farCorner

    def clearMoveZone(self):
        self.constrainedHome = None
        self.constrainedFarCorner = None

    def inMoveZone(self, pos: Position) -> bool:
        if self.constrainedHome is None or self.constrainedFarCorner is None:
            return True
        return pos.distance_squared(self.constrainedFarCorner) <= DEFEND_RADIUS2

    def moveTo(self, ct: Controller, target: Position):
        myLoc = ct.get_position()
        if myLoc == target:
            return
        if not self.inMoveZone(target):
            return
        if self.mapChanged or self.prevTarget is None or self.prevTarget != target:
            self.fillInDistTable(ct, target)
        self.prevTarget = target

        nearbyLaunchers = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != ct.get_team() and ct.get_entity_type(b) == EntityType.LAUNCHER:
                nearbyLaunchers.append(ct.get_position(b))

        # ANTI-CLUMP TIEBREAK: among steps of EQUAL distance, prefer the one
        # furthest from allies, so builders sharing a target don't walk the
        # identical path and duplicate each other's work. Distance still
        # wins outright; this only breaks ties.
        # NOTE: get_nearby_units() yields entity IDs, and Controller.get_id()
        # takes NO arguments (it returns THIS unit's id). The original
        # `ct.get_id(u) != ct.get_id()` therefore raised TypeError on every
        # call, was swallowed by the except below, and left allyNear empty -
        # so clumpCost() always returned 0 and this tiebreak never once ran.
        # MEASURED before the fix: 3863 swallowed TypeErrors in one midgard game.
        allyNear = []
        try:
            myTeam = ct.get_team()
            myId = ct.get_id()
            for u in ct.get_nearby_units():
                if u != myId and ct.get_team(u) == myTeam:
                    allyNear.append(ct.get_position(u))
        except Exception:
            pass

        def clumpCost(pos):
            c = 0
            for a in allyNear:
                dd = max(abs(a.x - pos.x), abs(a.y - pos.y))
                if dd <= 1:
                    c += 4
                elif dd <= 2:
                    c += 1
            return c

        bestDist = 4096
        bestClump = 99
        bestDir = None

        for d in CARDINALS:
            nextPos = myLoc.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.distMap[nextPos.x][nextPos.y] if self.distStamp[nextPos.x][nextPos.y] == self.fillCount else 4096
                tileId = ct.get_tile_building_id(nextPos)
                if posDist == bestDist and bestDir is not None and ct.can_move(d):
                    cc = clumpCost(nextPos)
                    if cc < bestClump:
                        bestClump = cc
                        bestDir = d
                if posDist < bestDist:
                    bestClump = clumpCost(nextPos) if ct.can_move(d) else 99
                    if ct.can_move(d):
                        bestDir = d
                        bestDist = posDist
                    elif tileId is not None:
                        tTeam = ct.get_team(tileId)
                        tType = ct.get_entity_type(tileId)
                        if tTeam == ct.get_team() and (tType == EntityType.BARRIER or tType == EntityType.GUNNER):
                            bestDir = d
                            bestDist = posDist
        if bestDir is not None:
            nextPos = myLoc.add(bestDir)
            tileId = ct.get_tile_building_id(nextPos)
            if tileId is not None:
                tTeam = ct.get_team(tileId)
                tType = ct.get_entity_type(tileId)
                if tTeam == ct.get_team() and (tType == EntityType.BARRIER):
                    if ct.can_destroy(nextPos):
                        ct.destroy(nextPos)
                    else:
                        return

            nearbyLaunchers.sort(key=lambda launcherPos: launcherPos.distance_squared(nextPos))
            isLauncherThreat = len(nearbyLaunchers) > 0 and nearbyLaunchers[0].distance_squared(nextPos) < 4
            if isLauncherThreat:
                attackingSpots = self.gunnerSpots(nearbyLaunchers[0], self.mapW, self.mapH, True)
                for spot in attackingSpots:
                    if not ct.is_in_vision(spot[0]):
                        continue
                    spotId = ct.get_tile_building_id(spot[0])
                    if spotId is not None:
                        spotType = ct.get_entity_type(spotId)
                        spotTeam = ct.get_team(spotId)
                        if spotType == EntityType.GUNNER and spotTeam == ct.get_team():
                            spotDir = ct.get_direction(spotId)
                            if spotDir == spot[1]:
                                return
                if ct.get_global_resources() > 110:
                    if ct.can_build_gunner(nextPos, nextPos.direction_to(nearbyLaunchers[0])):
                        ct.build_gunner(nextPos, nextPos.direction_to(nearbyLaunchers[0]))
                else:
                    self.stuckTurns += 1
                return

        if bestDir is not None and ct.can_move(bestDir) and self.inMoveZone(myLoc.add(bestDir)):
            ct.move(bestDir)
            self.stuckTurns = 0
        else:
            self.stuckTurns += 1
            if self.stuckTurns > 2 + (ct.get_id() % 8):
                movableDirs = []
                for i in CARDINALS:
                    nextPos = myLoc.add(i)
                    if ct.can_move(i) and self.inMoveZone(nextPos):
                        nearbyLaunchers.sort(key=lambda launcherPos: launcherPos.distance_squared(nextPos))
                        isLauncherThreat = len(nearbyLaunchers) > 0 and nearbyLaunchers[0].distance_squared(nextPos) < 4
                        if not isLauncherThreat:
                            movableDirs.append(i)
                if len(movableDirs) > 0:
                    ct.move(random.choice(movableDirs))

    def getTileEnv(self, tile: Position):
        return self.fullMap[tile.x][tile.y]

    def gunnerSpots(self, target: Position, mapW, mapH, blocked=True, lines=None):
        """Every [position, facing] a turret could stand and hit target.
        `lines` defaults to gunnerLines (reach calibrated to gunner range-sq
        13); pass sentinelLines for a sentinel's real range-sq 32 reach."""
        if lines is None:
            lines = gunnerLines
        spots = []
        for dx, dy, maxK, d in lines:
            x, y = target.x, target.y
            for k in range(1, maxK + 1):
                x -= dx
                y -= dy
                if not (0 <= x < mapW and 0 <= y < mapH):
                    break
                if blocked and self.fullMap is not None and self.fullMap[x][y] > 1:
                    break
                spots.append([Position(x, y), d])
        return spots

    def mirrorTile(self, tile: Position, sym):
        if sym == 'flipX':
            return Position(self.mapW - 1 - tile.x, tile.y)
        if sym == 'flipY':
            return Position(tile.x, self.mapH - 1 - tile.y)
        return Position(self.mapW - 1 - tile.x, self.mapH - 1 - tile.y)  # 180

    def rotCorePos(self):
        x, y, w, h = self.teamCore.x, self.teamCore.y, self.mapW, self.mapH
        return Position(w - x - 2, h - y - 2)

    def killSymmetry(self, sym):
        if sym in self.allSymmetries:
            self.allSymmetries.remove(sym)
        if sym in self.allEnemyCore:
            del self.allEnemyCore[sym]
        # Every tile we only "know" because we inferred it under this now-
        # disproven symmetry was never actually observed - revert to unknown.
        stale = [xy for xy, s in self.mirrorProvenance.items() if s == sym]
        for xy in stale:
            x, y = xy
            self.seenTiles[x][y] = False
            self.fullMap[x][y] = -1
            del self.mirrorProvenance[xy]
        if stale:
            self.mapChanged = True

    def checkTileSymmetry(self, tile: Position, tileType):
        # FIX (was `if self.mapSymmetry is not None or len(self.allSymmetries)
        # <= 1: return` in v60): that stopped re-validating symmetry the
        # moment only one candidate survived - so once flipX/flipY die early
        # (which happens within the first few turns on most maps), '180'
        # (the one guaranteed-correct symmetry) never got contradiction-
        # checked again. self.mapSymmetry is never assigned anywhere in this
        # file, so that half of the old condition was always vacuous.
        if not self.allSymmetries:
            return
        isWall = (tileType == 2)
        for sym in list(self.allSymmetries):
            m = self.mirrorTile(tile, sym)
            if not self.seenTiles[m.x][m.y]:
                continue
            if (self.fullMap[m.x][m.y] == 2) != isWall:
                self.killSymmetry(sym)

    def mirrorKnownTile(self, tile: Position, tileType):
        """Copy a directly/shared-observed STATIC tile (empty/ore/wall) onto
        its symmetry counterpart(s) for free - 180-degree map symmetry is
        guaranteed unconditionally (the same fact rotCorePos() relies on),
        and any surviving flipX/flipY candidate gets the same treatment
        speculatively until checkTileSymmetry disproves it. Never mirrors
        the dynamic 'Unpassable' reading (tileType 3): that's a player-action
        footprint, not terrain, and isn't guaranteed symmetric. v60 never
        had this - added because it's free information."""
        if tileType not in (0, 1, 2):
            return
        for sym in ('180', 'flipX', 'flipY'):
            if sym not in self.allSymmetries:
                continue
            m = self.mirrorTile(tile, sym)
            if (m.x, m.y) == (tile.x, tile.y):
                continue
            if self.seenTiles[m.x][m.y]:
                continue
            self.seenTiles[m.x][m.y] = True
            self.fullMap[m.x][m.y] = tileType
            self.mirrorProvenance[(m.x, m.y)] = sym
            self.mapChanged = True

    def updateSymmetry(self, ct: Controller):
        if self.teamCore is None or self.enemyCorePos is not None:
            return
        self.enemyCorePos = self.rotCorePos()
