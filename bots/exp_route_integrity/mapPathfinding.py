"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

openCost = 1       
barrierCost = 8 # to be implemented later


def core_footprint_positions(core: Position):
    return {
        Position(core.x + dx, core.y + dy)
        for dx in (0, 1) for dy in (0, 1)
    }


def proven_connected_conveyors(conveyor_directions, core_tiles):
    """Return only conveyors whose output-facing chain reaches the core."""
    connected = set()
    changed = True
    while changed:
        changed = False
        for position, facing in conveyor_directions.items():
            if position in connected:
                continue
            if position.add(facing) in core_tiles | connected:
                connected.add(position)
                changed = True
    return connected


def harvester_chain_roots(harvester, conveyor_directions):
    return [
        position
        for position in (harvester.add(direction) for direction in CARDINALS)
        if position in conveyor_directions
        and position.add(conveyor_directions[position]) != harvester
    ]


def trace_conveyor_chain(root, conveyor_directions, core_tiles, connected):
    position = root
    visited = set()
    for _ in range(len(conveyor_directions) + 1):
        if position in visited:
            return "cycle", position
        visited.add(position)
        facing = conveyor_directions.get(position)
        if facing is None:
            return "dead_end", position
        output = position.add(facing)
        if output in core_tiles or output in connected:
            return "connected", None
        if output not in conveyor_directions:
            return "dead_end", output
        position = output
    return "cycle", None


def visible_conveyor_merge_safe(
        start, conveyor_directions, core_tiles, visible_tiles):
    """Reject visible dead ends/cycles before treating a conveyor as a trunk.

    A fully visible chain is accepted only when it actually reaches the core.
    If an otherwise valid-looking chain leaves vision, every observed edge must
    make strict Manhattan progress toward the core. This preserves the parent's
    cheap local merge optimization without pretending arbitrary conveyors are
    connected.
    """
    position = start
    visited = set()
    made_only_progress = True
    for _ in range(len(conveyor_directions) + 1):
        if position in visited:
            return False
        visited.add(position)
        facing = conveyor_directions.get(position)
        if facing is None:
            return False
        output = position.add(facing)
        current_distance = min(
            abs(position.x - tile.x) + abs(position.y - tile.y)
            for tile in core_tiles
        )
        output_distance = min(
            abs(output.x - tile.x) + abs(output.y - tile.y)
            for tile in core_tiles
        )
        made_only_progress &= output_distance < current_distance
        if output in core_tiles:
            return True
        if output in conveyor_directions:
            position = output
            continue
        if output in visible_tiles:
            return False
        return made_only_progress
    return False


tileTypes = { # limited to 4 types to maximize caching ability
    Environment.EMPTY: 0, # Only counts if they are passable, or have a team barrier on them
    Environment.ORE_TITANIUM: 1, # Only counts if they dont have a harvester on them
    Environment.WALL: 2,
    'Unpassable': 3 # have an unpassable non team barrier building or are threat from turrets, 
}  
tileTypes2 = {
    "Wall": 0, 
    "Empty": 1, # no building
    "EETurret": 2, # enemy turret
    "EEConveyor": 3, # enemy conveyor
    "EEBlocker": 4, # enemy launcher/barrier
    "ETTurret": 5,  # team turret
    "ETConveyor": 6, # team conveyor
    "ETBlocker": 7, # team launcher/barrier
    "ORE": 8, # no building
    "OETurret": 9, # enemy turret (on ore)
    "OEConveyor": 10, # enemy conveyor (on ore)
    "OEBlocker": 11, # enemy launcher/barrier (on ore)
    "OEHarvester": 12, # enemy harvester
    "OTTurret": 13,  # team turret (on ore)
    "OTBlocker": 14, # team launcher/barrier (on ore)
    "OTHarvester": 15 # team harvester
} # tileTypes2 would be really cool to implement, but imo not worth the time right now
# shared array. 0: num bots spawned 1-6: new tiles from that bot 7: the map symmetry 

class MapPathfinder:
    def __init__(self):
        self.fullMap = None # bot's local version of the full map
        self.newTiles = [] # shared publicly so all bots have info
        self.seenTiles = None # used to get self.newTiles
        self.myNum = -1 # every builder bot gets its own unique number used to write to the shared array, and organize roles (1, 2, 3, ...)
        self.teamCore = None
        self.distMap = None
        self.conveyorMap = None
        self.mapW = None
        self.mapH = None
        self.stuckTurns = 0
        self.mapChanged = True
        self.prevTarget = None
        self.randDir = Direction.NORTH
        self.knownTeamConveyors = {}
        self.knownTeamHarvesters = set()
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
        if self.conveyorMap is None:
            self.conveyorMap = [[[4096, 'stuck'] for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.fullMap is None:
            self.fullMap = [[-1 for _ in range(self.mapH)] for _ in range(self.mapW)]
        if self.seenTiles is None:
            self.seenTiles = [[False for _ in range(self.mapH)] for _ in range(self.mapW)]
        self.getNewTiles(ct)
        self.shareTiles(ct, curRound)
        self.updateBoard(ct)
    def checkPassable (self, ct: Controller, tile: Position): # Only team barriers, or empty tiles are passbale
        tileId = ct.get_tile_building_id(tile)
        if tileId is not None and not ct.is_tile_passable(tile):
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam != ct.get_team() or tType != EntityType.BARRIER:
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
                self.seenTiles[x][y] = True
                self.newTiles.append([Position(x, y), tileType]) 
                self.mapChanged = True
            self.fullMap[x][y] = tileType

    def observeEconomyTile(self, ct: Controller, tile: Position):
        """Refresh facing memory only for the currently visible tile."""
        tileId = ct.get_tile_building_id(tile)
        ownType = None
        if tileId is not None and ct.get_team(tileId) == ct.get_team():
            ownType = ct.get_entity_type(tileId)
        if ownType == EntityType.CONVEYOR:
            self.knownTeamConveyors[tile] = ct.get_direction(tileId)
        else:
            self.knownTeamConveyors.pop(tile, None)
        if ownType == EntityType.HARVESTER:
            self.knownTeamHarvesters.add(tile)
        else:
            self.knownTeamHarvesters.discard(tile)

    def refreshEconomyGraph(self, ct: Controller):
        """Refresh graph state only when the designated repairer needs it."""
        for tile in ct.get_nearby_tiles():
            self.observeEconomyTile(ct, tile)

    def connectedConveyors(self):
        if self.teamCore is None:
            return set()
        return proven_connected_conveyors(
            self.knownTeamConveyors,
            core_footprint_positions(self.teamCore),
        )

    def routeLinkEstimate(self, position: Position, connected=None):
        if self.teamCore is None:
            return 4096
        if connected is None:
            connected = self.connectedConveyors()
        targets = core_footprint_positions(self.teamCore) | set(connected)
        return max(1, min(
            abs(position.x - target.x) + abs(position.y - target.y)
            for target in targets
        ))

    def lateEconomyRouteCandidates(self, ct: Controller):
        """Missing links traced from built friendly harvesters, never walls."""
        connected = self.connectedConveyors()
        coreTiles = core_footprint_positions(self.teamCore)
        candidates = []
        for harvester in sorted(
                self.knownTeamHarvesters, key=lambda p: (p.x, p.y)):
            roots = harvester_chain_roots(
                harvester, self.knownTeamConveyors)
            traces = [
                trace_conveyor_chain(
                    root, self.knownTeamConveyors, coreTiles, connected)
                for root in roots
            ]
            if any(status == "connected" for status, _ in traces):
                continue
            ends = {
                end for status, end in traces
                if status in ("dead_end", "cycle") and end is not None
            }
            if not roots:
                ends = {harvester.add(direction) for direction in CARDINALS}
            for end in sorted(ends, key=lambda p: (p.x, p.y)):
                if not (0 <= end.x < self.mapW and 0 <= end.y < self.mapH):
                    continue
                if not ct.is_in_vision(end):
                    continue
                endId = ct.get_tile_building_id(end)
                if endId is not None:
                    if ct.get_team(endId) != ct.get_team():
                        continue
                    endType = ct.get_entity_type(endId)
                    if endType == EntityType.CONVEYOR:
                        if end in connected:
                            continue
                    elif endType != EntityType.BARRIER:
                        continue
                occupyingBuilder = ct.get_tile_builder_bot_id(end)
                if (occupyingBuilder is not None
                        and ct.get_team(occupyingBuilder) != ct.get_team()):
                    continue
                if (occupyingBuilder is None
                        and not ct.is_tile_passable(end)):
                    continue
                candidates.append((
                    harvester,
                    end,
                    bool(roots),
                    self.routeLinkEstimate(end, connected),
                ))
        return candidates
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

            ct.draw_indicator_line(Position(x, y), ct.get_position(), 20, 140, 200)

            if not self.seenTiles[x][y] or self.fullMap[x][y] != t_type: 
                self.seenTiles[x][y] = True
                self.fullMap[x][y] = t_type
                self.mapChanged = True
                
            self.newTiles = [t for t in self.newTiles if not (t[0].x == x and t[0].y == y)] # you dont want to broadcast the same position twice
            
    def tileCost(self, ct: Controller, tile: Position) -> int | None:
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal > 1: # either wall or unpassable
            return None
        if ct.is_in_vision(tile):
            tileId = ct.get_tile_building_id(tile)
            if tileId is not None:
                tTeam = ct.get_team(tileId)
                tType = ct.get_entity_type(tileId)
                if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                    return barrierCost
                elif ct.is_tile_passable(tile) == False:
                    return 4096
        return openCost

    def fillInDistTable (self, ct: Controller, targetLoc: Position):
        w, h = self.mapW, self.mapH
        maxCost = (w + h) * barrierCost + 8
        
        for x in range(w):
            for y in range(h):
                self.distMap[x][y] = 4096
        
        buckets = [[] for _ in range(maxCost)]
        buckets[0].append(targetLoc)
        self.distMap[targetLoc.x][targetLoc.y] = 0
       
        myLoc = ct.get_position()

        myNeighbors = []
        for d in CARDINALS:
            myNeighbors.append(myLoc.add(d))

        for dist in range(maxCost):
            bucket = buckets[dist]
            hitBucket = False
            while bucket:
                cur = bucket.pop()

                if self.distMap[cur.x][cur.y] < dist:
                    continue

                if (cur.x, cur.y) in myNeighbors:
                    hitBucket = True
                    continue

                for d in CARDINALS:
                    nextTile = cur.add(d)
                    nextX = nextTile.x
                    nextY = nextTile.y
                    if 0 <= nextX < w and 0 <= nextY < h:
                        stepCost = self.tileCost(ct, nextTile)
                        if stepCost is not None:
                            newDist = dist + stepCost
                            if newDist < maxCost and newDist < self.distMap[nextX][nextY]:
                                self.distMap[nextX][nextY] = newDist
                                buckets[newDist].append(nextTile)
            if hitBucket:
                return dist
        return 4096

    def conveyorTileCost(self, ct: Controller, tile: Position):
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal == 2 or cachedVal == 3:
            return [None, 'stuck']

        if ct.is_in_vision(tile):
            tileId = ct.get_tile_building_id(tile)
            if tileId is not None:
                tTeam = ct.get_team(tileId)
                tType = ct.get_entity_type(tileId)
                if tTeam != ct.get_team():
                    return [None, 'stuck']  # enemy building
                if tType == EntityType.CORE:
                    return [0, 'done']
                if tType == EntityType.CONVEYOR:
                    if ct.get_stored_resource(tileId) is not None:
                        return [40, 'done']  # loaded
                    return [8, 'working']  # empty
                if tType == EntityType.BARRIER:
                    return [barrierCost, 'working']  
                return [None, 'stuck']  # dont break other stuff
        return [1, 'working'] 

    def fillConveyorDistTable(self, ct: Controller, curEnd: Position):
        myTeam = ct.get_team()
        myLoc = ct.get_position()
        w, h = self.mapW, self.mapH
        maxCost = (w + h) * barrierCost + 48 # because path ends when you go to a full conveyor
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
        nearbyBuildings = ct.get_nearby_buildings()
        visibleTiles = set(ct.get_nearby_tiles())
        conveyorDirections = {}
        conveyorIds = {}
        for b in nearbyBuildings:
            if (ct.get_team(b) == myTeam
                    and ct.get_entity_type(b) == EntityType.CONVEYOR):
                position = ct.get_position(b)
                conveyorDirections[position] = ct.get_direction(b)
                conveyorIds[position] = b
        coreTiles = core_footprint_positions(self.teamCore)
        safeMerges = {
            position for position in conveyorDirections
            if visible_conveyor_merge_safe(
                position, conveyorDirections, coreTiles, visibleTiles)
        }
        for bPos in safeMerges:
            b = conveyorIds[bPos]
            bPos = ct.get_position(b)
            cost = 8 if ct.get_stored_resource(b) is None else 40
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
                    hitBucket = True
                    continue
                for d in CARDINALS:
                    nextTile = cur.add(d)
                    nx, ny = nextTile.x, nextTile.y
                    if 0 <= nx < w and 0 <= ny < h:
                        cost, status = self.conveyorTileCost(ct, nextTile)
                        if status != 'stuck':
                            newDist = dist + cost
                            if newDist < maxCost and newDist < self.conveyorMap[nx][ny][0]:
                                self.conveyorMap[nx][ny] = [newDist, status]
                                buckets[newDist].append(nextTile)
            if hitBucket:
                return dist
        return 4096

    def routeConveyor(self, ct: Controller, curEnd: Position):
        myLoc = ct.get_position()
        self.fillConveyorDistTable(ct, curEnd)
        bestDist = 4096
        bestNextDir = None
        for d in CARDINALS:
            nextPos = curEnd.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.conveyorMap[nextPos.x][nextPos.y][0]
                if posDist < bestDist: 
                    bestNextDir = d
                    bestDist = posDist
        if bestNextDir is None:
            return # ur cooked just give up
        tileId = ct.get_tile_building_id(curEnd)
        if tileId is not None:
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                if ct.can_destroy(curEnd):
                    ct.destroy(curEnd)
                    return
        if ct.can_build_conveyor(curEnd, bestNextDir):
            ct.build_conveyor(curEnd, bestNextDir)
        else:
            self.moveTo(ct, curEnd)

    def lateConveyorTileCost(self, ct: Controller, tile: Position, connected):
        """Late repair may merge only into a proven, currently empty trunk."""
        cachedVal = self.fullMap[tile.x][tile.y]
        if cachedVal in (2, 3):
            return None
        if tile in self.knownTeamConveyors:
            if tile not in connected:
                return None
            if ct.is_in_vision(tile):
                tileId = ct.get_tile_building_id(tile)
                if (tileId is None
                        or ct.get_team(tileId) != ct.get_team()
                        or ct.get_entity_type(tileId) != EntityType.CONVEYOR
                        or ct.get_stored_resource(tileId) is not None):
                    return None
            return 0
        if ct.is_in_vision(tile):
            tileId = ct.get_tile_building_id(tile)
            if tileId is not None:
                if ct.get_team(tileId) != ct.get_team():
                    return None
                tileType = ct.get_entity_type(tileId)
                if tileType == EntityType.CORE:
                    return 0
                if tileType == EntityType.BARRIER:
                    return barrierCost
                return None
        return 1

    def fillLateConveyorDistTable(self, ct: Controller, curEnd: Position):
        connected = self.connectedConveyors()
        w, h = self.mapW, self.mapH
        maxCost = (w + h) * barrierCost + 48
        for x in range(w):
            for y in range(h):
                self.conveyorMap[x][y] = [maxCost, 'stuck']
        buckets = [[] for _ in range(maxCost)]
        coreTiles = core_footprint_positions(self.teamCore)
        for position in coreTiles:
            self.conveyorMap[position.x][position.y] = [0, 'done']
            buckets[0].append(position)
        for position in connected:
            if ct.is_in_vision(position):
                tileId = ct.get_tile_building_id(position)
                if (tileId is None
                        or ct.get_team(tileId) != ct.get_team()
                        or ct.get_entity_type(tileId) != EntityType.CONVEYOR
                        or ct.get_stored_resource(tileId) is not None):
                    continue
            self.conveyorMap[position.x][position.y] = [8, 'done']
            buckets[8].append(position)
        for distance in range(maxCost):
            bucket = buckets[distance]
            reached = False
            while bucket:
                current = bucket.pop()
                if self.conveyorMap[current.x][current.y][0] < distance:
                    continue
                if current == curEnd:
                    reached = True
                    continue
                for direction in CARDINALS:
                    neighbor = current.add(direction)
                    if not (0 <= neighbor.x < w and 0 <= neighbor.y < h):
                        continue
                    step = (
                        0 if neighbor == curEnd
                        else self.lateConveyorTileCost(
                            ct, neighbor, connected)
                    )
                    if step is None:
                        continue
                    newDistance = distance + step
                    if (newDistance < maxCost
                            and newDistance
                            < self.conveyorMap[neighbor.x][neighbor.y][0]):
                        self.conveyorMap[neighbor.x][neighbor.y] = [
                            newDistance, 'working']
                        buckets[newDistance].append(neighbor)
            if reached:
                return distance
        return 4096

    def routeLateConveyor(self, ct: Controller, curEnd: Position):
        """Build one verified late-repair link; parent routing is untouched."""
        self.fillLateConveyorDistTable(ct, curEnd)
        best = None
        for direction in CARDINALS:
            neighbor = curEnd.add(direction)
            if not (0 <= neighbor.x < self.mapW
                    and 0 <= neighbor.y < self.mapH):
                continue
            distance = self.conveyorMap[neighbor.x][neighbor.y][0]
            key = (distance, direction.value)
            if best is None or key < best[0]:
                best = (key, direction)
        if best is None or best[0][0] >= 4096:
            return
        tileId = ct.get_tile_building_id(curEnd)
        if tileId is not None and ct.get_team(tileId) == ct.get_team():
            tileType = ct.get_entity_type(tileId)
            if (tileType in (EntityType.BARRIER, EntityType.CONVEYOR)
                    and curEnd not in self.connectedConveyors()
                    and ct.can_destroy(curEnd)):
                ct.destroy(curEnd)
                return
        direction = best[1]
        if ct.can_build_conveyor(curEnd, direction):
            ct.build_conveyor(curEnd, direction)
        else:
            self.moveTo(ct, curEnd)

    def moveTo (self, ct: Controller, target: Position):
        myLoc = ct.get_position()
        if myLoc == target:
            return
        
        if self.mapChanged or self.prevTarget is None or self.prevTarget != target:
            self.fillInDistTable(ct, target)
        self.prevTarget = target
        bestDist = 4096
        bestDir = None
        for d in CARDINALS:
            nextPos = myLoc.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.distMap[nextPos.x][nextPos.y]
                tileId = ct.get_tile_building_id(nextPos)
                if posDist < bestDist: 
                    if ct.can_move(d):
                        bestDir = d
                        bestDist = posDist
                    elif tileId is not None:
                        tTeam = ct.get_team(tileId)
                        tType = ct.get_entity_type(tileId)
                        if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                            bestDir = d
                            bestDist = posDist
        if bestDir is not None:
            nextPos = myLoc.add(bestDir)
            tileId = ct.get_tile_building_id(nextPos)
            if tileId is not None:
                tTeam = ct.get_team(tileId)
                tType = ct.get_entity_type(tileId)
                if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                    if ct.can_destroy(nextPos):
                        ct.destroy(nextPos)
                    else:
                        return # dont want to increase stuckTurns for no reason
        if bestDir is not None and ct.can_move(bestDir):
            ct.move(bestDir)
            self.stuckTurns = 0
        else:
            self.stuckTurns += 1
            if self.stuckTurns > 2 + (ct.get_id() % 8):
                movableDirs = []
                for i in CARDINALS:
                    if ct.can_move(i):
                        movableDirs.append(i)
                if len(movableDirs) > 0:
                    ct.move(random.choice(movableDirs))
    
    def returnUnvisited(self, ct: Controller, myLoc: Position):
        unvisitedPositions = []
        for x in range(self.mapW):
            for y in range(self.mapH):
                if not self.seenTiles[x][y]:
                    unvisitedPositions.append(Position(x, y))
        unvisitedPositions.sort(key=lambda pos: pos.distance_squared(myLoc))
        if len(unvisitedPositions) > 0:
            return unvisitedPositions[0]
        return None
    def getTileEnv (self, tile: Position):
        return self.fullMap[tile.x][tile.y]
