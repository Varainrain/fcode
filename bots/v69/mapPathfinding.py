"""Map pathfinding for OogwayRush.

Map sharing, convoy routing, loop detection, symmetry-based enemy-core
discovery, threat-aware conveyor routing, and gunner spot generation.
"""

import heapq
import random
import time

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
cardDeltas = [(d.delta()[0], d.delta()[1]) for d in CARDINALS]


def _prof(name):
    def deco(fn):
        def wrapper(self, ct, *a, **k):
            t = time.monotonic()
            r = fn(self, ct, *a, **k)
            self._acc(name, time.monotonic() - t)
            return r
        return wrapper
    return deco

symSlot = 8 # slots 0-7 are taken (0 numSpawned, 1-6 map sharing, 7 team core loc)
symBits = {'flipX': 1, 'flipY': 2, '180': 4} # store *killed* symmetries so 0 = nothing ruled out

openCost = 1
barrierCost = 8
gunnerCost = 24 # gunners cost more, so higher

tileTypes = { # limited to 4 types to maximize caching ability
    Environment.EMPTY: 0, # Only counts if they are passable, or have a team barrier on them
    Environment.ORE_TITANIUM: 1, # Only counts if they dont have a harvester on them
    Environment.WALL: 2,
    'Unpassable': 3 # have an unpassable non team barrier building or are threat from turrets, 
}  
# shared array. 0: num bots spawned 1-6: new tiles from that bot 8: the map symmetry 
gunnerLines = []
for _d in CARDINALS:
    _dx, _dy = _d.delta()
    gunnerLines.append([_dx, _dy, 3, _d])
for _d in [Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST]:
    _dx, _dy = _d.delta()
    gunnerLines.append([_dx, _dy, 2, _d])

class MapPathfinder:
    def __init__(self):
        self.fullMap = None # bot's local version of the full map
        self.newTiles = [] # shared publicly so all bots have info
        self.seenTiles = None # used to get self.newTiles
        self.myNum = -1 # every builder bot gets its own unique number used to write to the shared array, and organize roles (1, 2, 3, ...)
        self.teamCore = None
        self.distMap = None
        self.distStamp = None
        self.fillCount = 0
        self._myLoc = None
        self.conveyorMap = None
        self.mapW = None
        self.mapH = None
        self.stuckTurns = 0
        self.constrainedHome = None
        self.constrainedFarCorner = None
        self.mapChanged = True
        self.prevTarget = None
        self.convDirs = {}
        self.convLoop = {}
        self.convRound = -1
        self.allSymmetries = ['flipX', 'flipY', '180']
        self.allEnemyCore = {}
        self.enemyCorePos = None
        self.mapSymmetry = None
        self.enemyThreatCache = set()
        self.enemyThreatRound = -1
        self._prof = {'turns': 0}

    def _acc(self, key, dt):
        self._prof[key] = self._prof.get(key, 0) + dt
    
    def _noteConvDeaths(self, ct: Controller):
        """CHURN FIX (lighthouse tiebreak: 45 of our 50 conveyors died vs
        Pantheon's 5 of 36 — we rebuild into the same blade). Remember
        tiles where OUR conveyor disappeared; the router prices them up
        so replacements path AROUND contested corridors. Per-unit memory:
        the rebuilder is usually the same builder that routed the chain."""
        if not hasattr(self, 'myConvSeen'):
            self.myConvSeen = set()
            self.deadConv = {}
        gone = []
        for txy in list(self.myConvSeen)[:80]:
            t = Position(txy[0], txy[1])
            try:
                if not ct.is_in_vision(t):
                    continue
                bid = ct.get_tile_building_id(t)
                if bid is None:
                    gone.append(txy)
                elif ct.get_team(bid) != ct.get_team():
                    gone.append(txy)          # enemy built on our corpse
            except Exception:
                continue
        for txy in gone:
            self.myConvSeen.discard(txy)
            self.deadConv[txy] = self.deadConv.get(txy, 0) + 1

    def setupMap(self, ct: Controller):
        self._noteConvDeaths(ct)
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
        if self.conveyorMap is None:
            self.conveyorMap = [[[4096, 'stuck'] for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.fullMap is None:
            self.fullMap = [[-1 for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.seenTiles is None:
            self.seenTiles = [[False for _ in range(self.mapH)] for _ in range(self.mapW)]
        self.getNewTiles(ct)
        self.shareTiles(ct, curRound)
        self.updateBoard(ct)
        self.updateSymmetry(ct)
        if self.myNum >= 0 and curRound % 250 == 0:
            self._prof['turns'] += 1
            print(f"[prof] bot{self.myNum} r{curRound} "
                  + " ".join(f"{k}={v:.4f}" for k, v in sorted(self._prof.items())), flush=True)
    
    def checkPassable (self, ct: Controller, tile: Position): # Only team barriers, or empty tiles are passbale
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
    def getNewTiles (self, ct: Controller):
        for tile in ct.get_nearby_tiles():
            x = tile.x
            y = tile.y
            tileEnv = ct.get_tile_env(tile)
            if not self.checkPassable(ct, tile) and tileEnv != Environment.WALL: # Walls clearly dont have buildings so need that
                tileEnv = 'Unpassable'
            tileType = tileTypes.get(tileEnv)
            if self.seenTiles[x][y] == False or self.fullMap[x][y] != tileType:
                self.checkTileSymmetry(tile, tileType) # before we mark it seen, so it cant test itself
                self.seenTiles[x][y] = True
                self.newTiles.append([Position(x, y), tileType]) 
                self.mapChanged = True
            self.fullMap[x][y] = tileType
    
    def shareTiles(self, ct: Controller, curRound):
        boundedRound = curRound % ct.read_store(0) + 1 # to bound it from 1 to n
        if boundedRound == self.myNum: # means your turn to share in the shared array if the mod is correct
            
            # start by sorting newTiles by the 16 tiles farthest away from your core
            self.newTiles.sort(key=lambda t: t[0].distance_squared(self.teamCore), 
                reverse=True
            )
            # convert each tile into a 12 bit integer (if theres less tiles, just send all 1s to fill in the remaining space (so it points to an out of bounds tile)
            combined = 0
            needToRemove = []
            for i in range(16):
                if i < len(self.newTiles):
                    cachedPos, cachedType = self.newTiles[i]
                    needToRemove.append(self.newTiles[i])
                    val = ((cachedPos.x & 0x1F) << 7) | ((cachedPos.y & 0x1F) << 2) | (cachedType & 0x3)
                else:
                    val = 0xFFF 
                combined = (combined << 12) | val # combine all of them to form a 196 bit integer

            # split that numebr into 6 32 bit integers, and write them to the shared array
            for i in range(6):
                part = (combined >> (32 * i)) & 0xFFFFFFFF
                ct.write_store(6 - i, part)
            for i in needToRemove:
                self.newTiles.remove(i)      
    
    @_prof('board')
    def updateBoard (self, ct: Controller):
        # read the 6 32 bit integers, and combine them into 1 196 bit one.
        combined = 0
        for i in range(1, 7):
            part = ct.read_store(i)
            combined = (combined << 32) | part
        # split that into 16 12 bit integers.
        # retrive the X, and Y and the cached value for each integer.
        # if X > mapW or Y > mapH, then pass that one
        # update your table, adn check if the tile is in you newTiles. If it is remove it
        for i in range(16):
            val = (combined >> (12 * (15 - i))) & 0xFFF
            
            if val == 0xFFF:
                continue
                
            x = (val >> 7) & 0x1F
            y = (val >> 2) & 0x1F
            t_type = val & 0x3

            if self.mapW is not None and (x >= self.mapW or y >= self.mapH): # all 1s means that no actual one to share
                continue

            if not self.seenTiles[x][y] or self.fullMap[x][y] != t_type:
                self.checkTileSymmetry(Position(x, y), t_type) # tiles other bots found count too
                self.seenTiles[x][y] = True
                self.fullMap[x][y] = t_type
                self.mapChanged = True
                
            self.newTiles = [t for t in self.newTiles if not (t[0].x == x and t[0].y == y)] # you dont want to broadcast the same position twice
            
    def tileCost(self, ct: Controller, tile: Position) -> int | None:
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal > 1: # either wall or unpassable
            return None
        myLoc = self._myLoc
        dx = tile.x - myLoc.x
        dy = tile.y - myLoc.y
        if dx * dx + dy * dy > 20: # outside vision: assume clear terrain
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
    def fillInDistTable (self, ct: Controller, targetLoc: Position):
        # A* from the target toward the bot's position (Manhattan heuristic is
        # admissible + consistent for cardinal-only movement). Explores roughly the
        # path corridor instead of flooding the whole map, so far-apart targets are
        # cheap. distStamp marks tiles written this fill so there is no full-map reset.
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
        heap = [(abs(tx - mx) + abs(ty - my), 0, tx, ty)] # (f, g, x, y)
        heappush = heapq.heappush
        heappop = heapq.heappop

        while heap:
            _, g, cx, cy = heappop(heap)
            if distStamp[cx][cy] == fill and distMap[cx][cy] < g:
                continue
            if cx == mx and cy == my:
                return g
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
        return 4096

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

    def conveyorTileCostSafe(self, ct: Controller, tile: Position, enemyThreatened, curEnd: Position):
        cost, status = self.conveyorTileCost(ct, tile, curEnd)
        if cost is not None and (tile.x, tile.y) in enemyThreatened:
            cost += 24
        # death-site pricing: a tile that has eaten our conveyors twice is
        # a corridor, not a route (45x churn in the lost econ race)
        if cost is not None and hasattr(self, 'deadConv'):
            d = self.deadConv.get((tile.x, tile.y), 0)
            if d:
                cost += 45 * min(2, d)
        return [cost, status]

    def conveyorTileCost(self, ct: Controller, tile: Position, curEnd: Position):
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal == 2 or cachedVal == 3:
            return [None, 'stuck']

        myLoc = self._myLoc
        dx = tile.x - myLoc.x
        dy = tile.y - myLoc.y
        if dx * dx + dy * dy > 20: # outside vision: assume clear terrain
            return [1, 'working']

        endDist = curEnd.distance_squared(self.teamCore)
        otherDist = tile.distance_squared(self.teamCore)
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None:
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam != ct.get_team():
                return [None, 'stuck']  # enemy building
            if tType == EntityType.CORE:
                return [0, 'done']
            if tType == EntityType.CONVEYOR:
                if hasattr(self, 'myConvSeen'):
                    self.myConvSeen.add((tile.x, tile.y))
                if self.convLoop.get(tile.x * 32 + tile.y):
                    return [8, 'working']  # in a cycle: build through it, never a sink
                if ct.get_stored_resource(tileId) is not None:
                    return [24, 'done']  # loaded
                if endDist > otherDist:
                    return [30, 'done']
                return [2, 'working']  # empty
            if tType == EntityType.BARRIER:
                return [barrierCost, 'working']  
            if tType == EntityType.GUNNER:
                return [gunnerCost, 'working']  
            return [None, 'stuck']  # dont break other stuff
        return [1, 'working'] 

    @_prof('classify')
    def classifyConveyors(self, ct: Controller, myTeam):
        curRound = ct.get_current_round()
        if self.convRound == curRound:
            return self.convDirs, self.convLoop
        w, h = self.mapW, self.mapH
        convDirs = {}
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.CONVEYOR:
                bPos = ct.get_position(b)
                convDirs[bPos.x * 32 + bPos.y] = [bPos, ct.get_direction(b),
                                                  ct.get_stored_resource(b) is not None]
        convLoop = {}
        for startKey in convDirs:
            if startKey in convLoop: # already resolved as part of an earlier chain
                continue
            thisPath = []
            onPath = {}
            cur = startKey
            isLoop = False
            while True:
                if cur in onPath: # walked back onto this same chain
                    isLoop = True
                    break
                if cur in convLoop: # joins a chain we already have a verdict for
                    isLoop = convLoop[cur]
                    break
                onPath[cur] = True
                thisPath.append(cur)
                curPos, curDir, curLoaded = convDirs[cur]
                nextPos = curPos.add(curDir)
                if not (0 <= nextPos.x < w and 0 <= nextPos.y < h):
                    break # points off the map, cant be a cycle
                nextKey = nextPos.x * 32 + nextPos.y
                if nextKey not in convDirs:
                    break # core, out of vision, or dead end - assume it drains
                cur = nextKey
            for key in thisPath: # anything upstream of a cycle never drains either
                convLoop[key] = isLoop
        self.convDirs = convDirs
        self.convLoop = convLoop
        self.convRound = curRound
        return convDirs, convLoop

    @_prof('conv')
    def fillConveyorDistTable(self, ct: Controller, curEnd: Position):
        myTeam = ct.get_team()
        myLoc = ct.get_position()
        self._myLoc = myLoc
        enemyThreatened = self.enemyTurretThreatenedTiles(ct)
        w, h = self.mapW, self.mapH
        maxCost = (w + h) * (gunnerCost + 24) + 48 # because path ends when you go to a full conveyor
        for x in range(w):
            for y in range(h):
                self.conveyorMap[x][y] = [maxCost, 'stuck']
        buckets = [[] for _ in range(maxCost)]
        tL = self.teamCore
        bL = self.teamCore.add(Direction.SOUTH)
        tR = self.teamCore.add(Direction.EAST)
        bR = self.teamCore.add(Direction.SOUTH).add(Direction.EAST)
        corners = [tL, bL, tR, bR]
        buckets[0].append(tL)
        buckets[0].append(tR)
        buckets[0].append(bL)
        buckets[0].append(bR)
        self.conveyorMap[tL.x][tL.y] = [0, 'done']
        self.conveyorMap[tR.x][tR.y] = [0, 'done']
        self.conveyorMap[bR.x][bR.y] = [0, 'done']
        self.conveyorMap[bL.x][bL.y] = [0, 'done']
        corners.sort(key=lambda corner: corner.distance_squared(myLoc))
        closestCorner = corners[0]
        convDirs, convLoop = self.classifyConveyors(ct, myTeam)
        for key in convDirs:
            bPos, bDir, bLoaded = convDirs[key]
            if convLoop[key]:
                continue # cycle: not a sink, so no seed. still reached by normal expansion below
            cost = 28 if bLoaded else 4
            if bPos.distance_squared(closestCorner) > myLoc.distance_squared(closestCorner):
                cost += 24
            if cost < self.conveyorMap[bPos.x][bPos.y][0]:
                self.conveyorMap[bPos.x][bPos.y] = [cost, 'done']
                buckets[cost].append(bPos)
        for dist in range(maxCost):
            bucket = buckets[dist]
            hitBucket = False
            while bucket:
                cur = bucket.pop()
                if self.conveyorMap[cur.x][cur.y][0] < dist:
                    continue
                if cur == curEnd:
                    hitBucket = True # still expand below - routeConveyor needs curEnd's own
                    # neighbors labeled, especially the outward one away from core, which
                    # can only ever be reached by expanding from curEnd itself
                for d in CARDINALS:
                    nextTile = cur.add(d)
                    nx, ny = nextTile.x, nextTile.y
                    if 0 <= nx < w and 0 <= ny < h:
                        cost, status = self.conveyorTileCostSafe(ct, nextTile, enemyThreatened, curEnd)
                        if status != 'stuck':
                            newDist = dist + cost
                            if newDist < maxCost and newDist < self.conveyorMap[nx][ny][0]:
                                self.conveyorMap[nx][ny] = [newDist, status]
                                buckets[newDist].append(nextTile)
            if hitBucket:
                return dist
        return 4096

    def createsLoop(self, buildPos: Position, d: Direction):
        w, h = self.mapW, self.mapH
        buildKey = buildPos.x * 32 + buildPos.y
        cur = buildPos.add(d)
        onPath = {}
        while True:
            if not (0 <= cur.x < w and 0 <= cur.y < h):
                return False # ran off the map, cant be a cycle
            curKey = cur.x * 32 + cur.y
            if curKey == buildKey:
                return True # chain leads back into the tile we are about to build
            if curKey in onPath:
                return True # downstream loops on itself, so we would feed it
            if self.convLoop.get(curKey):
                return True # already flagged as looping
            if curKey not in self.convDirs:
                return False # core, empty ground, or out of vision - assume it drains
            onPath[curKey] = True
            curPos, curDir, curLoaded = self.convDirs[curKey]
            cur = curPos.add(curDir)

    @_prof('route')
    def routeConveyor(self, ct: Controller, curEnd: Position):
        if not self.inMoveZone(curEnd):
            return
        myLoc = ct.get_position()
        self.fillConveyorDistTable(ct, curEnd)
        bestDist = 4096
        bestNextDir = None
        for d in CARDINALS:
            nextPos = curEnd.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.conveyorMap[nextPos.x][nextPos.y][0]
                if posDist < bestDist and not self.createsLoop(curEnd, d):
                    bestNextDir = d
                    bestDist = posDist
                elif posDist == bestDist and bestNextDir is not None and not self.createsLoop(curEnd, d):
                    if myLoc.distance_squared(nextPos) < myLoc.distance_squared(curEnd.add(bestNextDir)):
                        bestNextDir = d
                        bestDist = posDist
        if bestNextDir is None:
            return # ur cooked just give up
        tileId = ct.get_tile_building_id(curEnd)
        if tileId is not None:
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam == ct.get_team() and (tType == EntityType.BARRIER or tType == EntityType.GUNNER):
                if ct.can_destroy(curEnd):
                    ct.destroy(curEnd)
                    return
        if ct.can_build_conveyor(curEnd, bestNextDir):
            ct.build_conveyor(curEnd, bestNextDir)
            if hasattr(self, 'myConvSeen'):
                self.myConvSeen.add((curEnd.x, curEnd.y))
        else:
            if myLoc == curEnd:
                # standing on the chain head can't build (needs adjacency) - step off to any
                # movable cardinal neighbor so we're adjacent to curEnd again next turn
                for d in CARDINALS:
                    if ct.can_move(d) and self.inMoveZone(myLoc.add(d)):
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
                self.moveTo(ct, curEnd)

    def setMoveZone(self, home: Position, farCorner: Position):
        self.constrainedHome = home
        self.constrainedFarCorner = farCorner

    def clearMoveZone(self):
        self.constrainedHome = None
        self.constrainedFarCorner = None

    def inMoveZone(self, pos: Position) -> bool:
        if self.constrainedHome is None or self.constrainedFarCorner is None:
            return True
        return (pos.distance_squared(self.constrainedFarCorner) <= 41)
    
    def moveTo (self, ct: Controller, target: Position):
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

        # ANTI-CLUMP TIEBREAK.
        # On a 4-connected grid most steps toward a target are tied on distance,
        # and this loop took the first one in CARDINALS order - so two builders
        # with the same target walk the identical path and duplicate each other's
        # work. The replays show exactly that, and two postmortems name it: one
        # calls it "early economy bots following waypoints in the exact same
        # order, rendering multiple builders redundant", and Pantheon's own step
        # tiebreak skips tiles next to friendly bots because "avoiding builder
        # bots helps prevent clumping or situations where we accidentally step
        # onto another builder bot's target tile".
        # So among steps of EQUAL distance, prefer the one furthest from allies.
        # Distance still wins outright; this only breaks ties.
        allyNear = []
        try:
            myTeam = ct.get_team()
            for u in ct.get_nearby_units():
                if ct.get_team(u) == myTeam and ct.get_id(u) != ct.get_id():
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
                        return # this is intentional

            nearbyLaunchers.sort(key=lambda launcherPos: launcherPos.distance_squared(nextPos))
            isLauncherThreat = len(nearbyLaunchers) > 0 and nearbyLaunchers[0].distance_squared(nextPos) < 4
            if isLauncherThreat:
                attackingSpots = self.gunnerSpots(nearbyLaunchers[0], self.mapW, self.mapH, True)
                for spot in attackingSpots: # check if a gunner has already been placed
                    if not ct.is_in_vision(spot[0]):
                        continue
                    spotId = ct.get_tile_building_id(spot[0])
                    if spotId is not None:
                        spotType = ct.get_entity_type(spotId)
                        spotTeam = ct.get_team(spotId)
                        if spotType == EntityType.GUNNER and spotTeam == ct.get_team():
                            spotDir = ct.get_direction(spotId)
                            if spotDir == spot[1]:
                                # a gunner has already been placed
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
    
    def getTileEnv (self, tile: Position):
        return self.fullMap[tile.x][tile.y]

    def gunnerSpots(self, target: Position, mapW, mapH, blocked=True):
        """Every [position, facing] a gunner could stand and hit target.
        Walks each line outward from target, so the facing returned is the
        reverse of the walk. With blocked=True a wall or building on the line
        ends that direction early - it cannot be stood on and it shields
        everything behind it. Unseen tiles are assumed clear. mapW/mapH are
        taken explicitly so this also works without setupMap() (e.g. from
        the core, or a spot planner that has not built the full map)."""
        spots = []
        for dx, dy, maxK, d in gunnerLines:
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

    def mirrorTile(self, tile: Position, sym): # where tile lands under a symmetry
        if sym == 'flipX':
            return Position(self.mapW - 1 - tile.x, tile.y)
        if sym == 'flipY':
            return Position(tile.x, self.mapH - 1 - tile.y)
        return Position(self.mapW - 1 - tile.x, self.mapH - 1 - tile.y) # 180

    def mirrorCore(self, sym): # -2 not -1: the core is 2x2 and we track its top left corner
        x, y, w, h = self.teamCore.x, self.teamCore.y, self.mapW, self.mapH
        if sym == 'flipX':
            return Position(w - x - 2, y)
        if sym == 'flipY':
            return Position(x, h - y - 2)
        return Position(w - x - 2, h - y - 2) # 180

    def rotCorePos(self): # the enemy core always sits at the 180-rotational mirror of ours,
        x, y, w, h = self.teamCore.x, self.teamCore.y, self.mapW, self.mapH # even if the map's own symmetry is flipX/flipY
        return Position(w - x - 2, h - y - 2)

    def killSymmetry(self, sym):
        if sym in self.allSymmetries:
            self.allSymmetries.remove(sym)
        if sym in self.allEnemyCore:
            del self.allEnemyCore[sym]

    def checkTileSymmetry(self, tile: Position, tileType): # called per newly known tile - cheap
        if self.mapSymmetry is not None or len(self.allSymmetries) <= 1:
            return
        isWall = (tileType == 2)
        for sym in list(self.allSymmetries): # list() since killSymmetry mutates it
            m = self.mirrorTile(tile, sym)
            if not self.seenTiles[m.x][m.y]:
                continue # mirror unknown, this tile tells us nothing yet
            if (self.fullMap[m.x][m.y] == 2) != isWall: # wall vs not-wall disagrees
                self.killSymmetry(sym)

    def updateSymmetry(self, ct: Controller): # called once per turn
        # the enemy core is always the 180-rotational mirror of our own, so once we
        # know our core (turn 0) the position is set for good - no symmetry guessing
        if self.teamCore is None or self.enemyCorePos is not None:
            return
        self.enemyCorePos = self.rotCorePos()
