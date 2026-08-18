"""Map pathfinding for OogwayRush.

Map sharing, convoy routing, loop detection, symmetry-based enemy-core
discovery, threat-aware conveyor routing, and gunner spot generation.
"""

import heapq
import random

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
cardDeltas = [(d.delta()[0], d.delta()[1]) for d in CARDINALS]


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

sentinelLines = []
for _d in CARDINALS:
    _dx, _dy = _d.delta()
    sentinelLines.append([_dx, _dy, 5, _d])
for _d in [Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST]:
    _dx, _dy = _d.delta()
    sentinelLines.append([_dx, _dy, 4, _d])

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
        self.mapChanged = True
        self.prevTarget = None
        self.allSymmetries = ['flipX', 'flipY', '180']
        self.allEnemyCore = {}
        self.enemyCorePos = None
        self.mapSymmetry = None

        self.mirrorProvenance = {}
        self.enemyThreatCache = set()
        self.enemyThreatRound = -1
        self._prof = {'turns': 0}
    

    def setupMap(self, ct: Controller):
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
    
    def checkPassable (self, ct: Controller, tile: Position): # Only team barriers, or empty tiles are passbale
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None and not ct.is_tile_passable(tile):
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam != ct.get_team() or (tType != EntityType.BARRIER):
                return False
        return True
    
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
                self.mirrorKnownTile(tile, tileType)
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
                self.mirrorKnownTile(Position(x, y), t_type)
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
    
    def moveTo (self, ct: Controller, target: Position):
        myLoc = ct.get_position()
        if myLoc == target:
            return
        if self.mapChanged or self.prevTarget is None or self.prevTarget != target:
            self.fillInDistTable(ct, target)
        self.prevTarget = target

        nearbyLaunchers = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != ct.get_team() and ct.get_entity_type(b) == EntityType.LAUNCHER:
                nearbyLaunchers.append(ct.get_position(b))

        bestDist = 4096
        bestDir = None

        for d in CARDINALS:
            nextPos = myLoc.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.distMap[nextPos.x][nextPos.y] if self.distStamp[nextPos.x][nextPos.y] == self.fillCount else 4096
                tileId = ct.get_tile_building_id(nextPos)
                if posDist == bestDist and bestDir is not None and ct.can_move(d):
                    bestDir = d
                if posDist < bestDist:
                    if ct.can_move(d):
                        bestDir = d
                        bestDist = posDist
                    elif tileId is not None:
                        tTeam = ct.get_team(tileId)
                        tType = ct.get_entity_type(tileId)
                        if tTeam == ct.get_team() and (tType == EntityType.BARRIER):
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

        if bestDir is not None and ct.can_move(bestDir):
            ct.move(bestDir)
            self.stuckTurns = 0
        else:
            self.stuckTurns += 1
            if self.stuckTurns > 2:
                movableDirs = []
                for i in CARDINALS:
                    nextPos = myLoc.add(i)
                    if ct.can_move(i):
                        nearbyLaunchers.sort(key=lambda launcherPos: launcherPos.distance_squared(nextPos))
                        isLauncherThreat = len(nearbyLaunchers) > 0 and nearbyLaunchers[0].distance_squared(nextPos) < 4
                        if not isLauncherThreat:
                            movableDirs.append(i)
                if len(movableDirs) > 0:
                    ct.move(random.choice(movableDirs))
    
    def getTileEnv (self, tile: Position):
        return self.fullMap[tile.x][tile.y]

    def gunnerSpots(self, target: Position, mapW, mapH, blocked=True, lines=None):
        """Every [position, facing] a turret could stand and hit target.
        Walks each line outward from target, so the facing returned is the
        reverse of the walk. With blocked=True a wall or building on the line
        ends that direction early - it cannot be stood on and it shields
        everything behind it. Unseen tiles are assumed clear. mapW/mapH are
        taken explicitly so this also works without setupMap() (e.g. from
        the core, or a spot planner that has not built the full map).
        `lines` defaults to gunnerLines (reach calibrated to gunner range-sq
        13); pass sentinelLines for a sentinel's real range-sq 32 reach -
        every existing call site is unaffected by this default."""
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
        # Every tile we only "know" because we inferred it under this now-
        # disproven symmetry was never actually observed -- revert to
        # unknown so it gets re-learned normally instead of continuing to
        # feed a wrong guess into pathfinding (fillInDistTable) or the
        # harvest/ore scans.
        stale = [xy for xy, s in self.mirrorProvenance.items() if s == sym]
        for xy in stale:
            x, y = xy
            self.seenTiles[x][y] = False
            self.fullMap[x][y] = -1
            del self.mirrorProvenance[xy]
        if stale:
            self.mapChanged = True

    def checkTileSymmetry(self, tile: Position, tileType): # called per newly known tile - cheap
        # Was `len(self.allSymmetries) <= 1: return`, which stops checking
        # for good the moment only one candidate is left. flipX/flipY die
        # almost immediately on generic terrain, leaving '180' alone at
        # length 1 -- so the ONE symmetry mirrorKnownTile actually depends
        # on for the whole game (180 is the guaranteed one, GAME-RULES.md)
        # was never being contradiction-checked again after that point.
        # self.mapSymmetry is never assigned anywhere else in this file, so
        # that half of the old condition was always vacuous.
        if not self.allSymmetries:
            return
        isWall = (tileType == 2)
        for sym in list(self.allSymmetries): # list() since killSymmetry mutates it
            m = self.mirrorTile(tile, sym)
            if not self.seenTiles[m.x][m.y]:
                continue # mirror unknown, this tile tells us nothing yet
            if (self.fullMap[m.x][m.y] == 2) != isWall: # wall vs not-wall disagrees
                self.killSymmetry(sym)

    def mirrorKnownTile(self, tile: Position, tileType):
        """Copy a directly/shared-observed STATIC tile (empty/ore/wall) onto
        its symmetry counterpart(s) for free. GAME-RULES.md guarantees
        180-degree map symmetry unconditionally -- the same fact rotCorePos()
        already relies on -- so every tile we see also tells us its 180
        counterpart's terrain before any unit ever travels there; any
        surviving flipX/flipY candidate gets the same treatment speculatively
        until checkTileSymmetry disproves it (killSymmetry then reverts).
        Never mirrors the dynamic 'Unpassable' reading (tileType 3): that is
        a player-action footprint (a building or threat sitting on an
        empty/ore tile), not terrain, and is not remotely guaranteed
        symmetric.
        On odd width/height maps, flipX(T) or flipY(T) can land on the exact
        same tile as 180(T) (the middle row/column). '180' as never killed --
        check it first so a coinciding tile's provenance is attributed to
        the symmetry that will never need to revert it, instead of whichever
        of flipX/flipY happened to be checked first."""
        if tileType not in (0, 1, 2):
            return
        for sym in ('180', 'flipX', 'flipY'):
            if sym not in self.allSymmetries:
                continue
            m = self.mirrorTile(tile, sym)
            if (m.x, m.y) == (tile.x, tile.y):
                continue  # self-mirror (odd-dimension center row/column/tile): already direct ground truth
            if self.seenTiles[m.x][m.y]:
                continue  # ground truth (direct or shared) always wins over an inference
            self.seenTiles[m.x][m.y] = True
            self.fullMap[m.x][m.y] = tileType
            self.mirrorProvenance[(m.x, m.y)] = sym
            self.mapChanged = True

    def updateSymmetry(self, ct: Controller): # called once per turn
        # the enemy core is always the 180-rotational mirror of our own, so once we
        # know our core (turn 0) the position is set for good - no symmetry guessing
        if self.teamCore is None or self.enemyCorePos is not None:
            return
        self.enemyCorePos = self.rotCorePos()
