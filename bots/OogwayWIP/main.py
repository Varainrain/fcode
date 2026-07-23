"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

from mapPathfinding import *
from initialSpawning import *
anglePerDir = [
    135, 108, 162, 90,
    45, 72, 18, 0,
    315, 288, 342, 270,
    225, 252, 198, 180
]
spawnPoints = [
    Position(-1, -1), Position(0, -1), Position(-1, 0), Position(0, -1), # tL
    Position(1, -1), Position(0, -1), Position(1, 0), Position(1, 0), # tR
    Position(1, 1), Position(0, 1), Position(1, 0), Position(0, 1), # bR
    Position(-1, 1), Position(0, 1), Position(-1, 0), Position(-1, 0) # bL
]
directionMoves = [
    Position(-6, -6), Position(-2, -6), Position(-6, -2), Position(0, -6), # tL
    Position(6, -6), Position(2, -6), Position(6, -2), Position(6, 0), # tR
    Position(6, 6), Position(2, 6), Position(6, 2), Position(0, 6), # bR
    Position(-6, 6), Position(-2, 6), Position(-6, 2), Position(-6, 0) # bL
]

# slot 0 numSpawned, slot 1-6 map sharing, slot 7 initial target

class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.initSpawn = initialSpawn()
        self.numSpawned = 0
        self.fiveDirections = None
        self.initTarget = None
        self.turnsAlive = 0
        self.mapW = None
        self.mapH = None

    def runCore(self, ct: Controller) -> None:
        if self.numSpawned == 0:
           self.fiveDirections =  self.initSpawn.setBestFive(ct)
           ct.draw_indicator_dot(Position(0, 0), 204, 23, 123)
        if self.fiveDirections and len(self.fiveDirections) > 0: # only the first 5 bots spawned should be there
            spawnAngle = self.fiveDirections[0]
            index = anglePerDir.index(spawnAngle)
            myLoc = ct.get_position()
            tL = myLoc
            tR = myLoc.add(Direction.EAST)
            bL = myLoc.add(Direction.SOUTH)
            bR = myLoc.add(Direction.SOUTH).add(Direction.EAST)
            coreCorners = [tL, tR, bR, bL]

            spawnPos = Position(
                coreCorners[index // 4].x + spawnPoints[index].x,
                coreCorners[index // 4].y + spawnPoints[index].y
            )
            target = Position(spawnPos.x + directionMoves[index].x, spawnPos.y + directionMoves[index].y)
            target = Position(
                max(0, min(target.x, self.mapW - 1)),
                max(0, min(target.y, self.mapH - 1))
            )
            if ct.can_spawn(spawnPos):
                ct.spawn_builder(spawnPos)
                self.numSpawned += 1
                ct.write_store(0, self.numSpawned )
                ct.write_store(7, target.x * 32 + target.y) #
                self.fiveDirections.remove(spawnAngle) # so it doesnt spawn in the same spot twice.
    def run(self, ct: Controller) -> None:
        if self.mapW is None:
            self.mapH = ct.get_map_height()
            self.mapW = ct.get_map_width()
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.numSpawned = ct.read_store(0)
        self.mapPf.setupMap(ct)
        if self.initTarget is None: # set initial target for the first explore
            compact = ct.read_store(7)
            self.initTarget = Position(compact // 32, compact % 32)
        self.turnsAlive += 1
        print(self.runBestState(ct, myLoc))

    def runBestState(self, ct: Controller, myLoc: Position):
        nearbyUnits = ct.get_nearby_entities() # both builder bots and buildings
        myTeam = ct.get_team()

        # attack, max score of 10
        attackScore = 0
        attackPos = None
        if ct.get_global_resources() > 100: # dont attack if u r broke
            for b in nearbyUnits: # looks at nearby enemies, and scored on entity type and distance
                bTeam = ct.get_team(b)
                buildingScore = 0
                if bTeam != myTeam:
                    bPos = ct.get_position(b)
                    bType = ct.get_entity_type(b)
                    if bType in [EntityType.GUNNER, EntityType.SENTINEL, EntityType.CORE]:
                        buildingScore = 10
                    elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                        buildingScore = 8
                    elif bType == EntityType.BUILDER_BOT:
                        buildingScore = 2
                    else:
                        buildingScore = 1
                else:
                    continue
                dist = myLoc.distance_squared(bPos)
                buildingScore = buildingScore * (1 - dist/40)
                if buildingScore > attackScore:
                    attackScore = buildingScore
                    attackPos = bPos # no need to worry about this not being initialized, as it needs buildingScore > attackScore, so there must be a position
        
        # heal, max score of 8
        healScore = 0
        healPos = None
        for b in nearbyUnits: # scored on how low the unit is, distance, and entity type
            bTeam = ct.get_team(b)
            buildingScore = 0
            if bTeam == myTeam:
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                if bType in [EntityType.CORE]: # dont waste an entire state on just healing yourself
                    buildingScore = 8
                elif bType in [EntityType.GUNNER, EntityType.SENTINEL]:
                    buildingScore = 6
                elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                    buildingScore = 4 
                else:
                    buildingScore = 2
            else:
                continue
            dist = myLoc.distance_squared(bPos)
            cHP = ct.get_hp(b)
            maxHP = ct.get_max_hp(b)
            mHP = maxHP - cHP
            buildingScore = buildingScore * (1 - dist/120) * (mHP/maxHP)
            if buildingScore > healScore:
                healScore = buildingScore
                healPos = bPos

        # route, max score of 6
        routeScore = 0 # orphan harvesters + unfinished conveyor chains
        routePos = None
        routeDir = None
        mapW = self.mapW
        mapH = self.mapH
        teamCore = self.mapPf.teamCore
        if teamCore is not None:
            for b in nearbyUnits:
                bScore = 0
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                bDir = None
                endTile = None
                if bType == EntityType.HARVESTER: # max score of 5 to prioritize cotninueing paths
                    noTeamConv = True
                    workingSpots = []
                    for possibleDir in CARDINALS: # would have named it dir, but thats not allowed
                        endTile = bPos.add(possibleDir)
                        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile):
                            eId = ct.get_tile_building_id(endTile)
                            if eId is None:
                                workingSpots.append(endTile)
                            elif ct.get_team(eId) == myTeam and ct.get_entity_type(eId) == EntityType.CONVEYOR:
                                noTeamConv = False
                    if noTeamConv and len(workingSpots) > 0:
                        workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                        bScore = max(1.6, 5 * (1 - (workingSpots[0].distance_squared(teamCore) / 100)) * (1 - myLoc.distance_squared(bPos)/120))
                        bDir = Direction.CENTRE
                        endTile = workingSpots[0]
                elif bType == EntityType.CONVEYOR:  
                    if ct.get_team(b) == myTeam:
                        bDir = ct.get_direction(b)
                        endTile = bPos.add(bDir)
                        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile):
                            eId = ct.get_tile_building_id(endTile)
                            if eId is None:
                                bScore = max(2, 6 * (1 - (endTile.distance_squared(teamCore) / 120)) * (1 - myLoc.distance_squared(bPos)/80))
                if bScore > routeScore:
                    routeScore = bScore
                    routePos = endTile
                    routeDir = bDir

        # harvest, max score of 3
        harvestScore = 0
        harvestPos = None
        if teamCore is not None:
            for tile in ct.get_nearby_tiles():
                if self.mapPf.getTileEnv(tile) == 1: # since it checks all nearby tiles before choosing state, this is fine
                    if ct.get_tile_building_id(tile) is None: 
                        dist = teamCore.distance_squared(tile)
                        tileScore = max(1.2, 3 * (1 - dist/160) * (1 - myLoc.distance_squared(bPos)/120))
                        if tileScore > harvestScore:
                            harvestPos = tile
                            harvestScore = tileScore
            

        # explore, max score of 1
        exploreScore = 0
        if ct.get_current_round() < 12:
            explorePos = self.initTarget
            exploreScore = 1
        else:
            explorePos = self.mapPf.returnUnvisited(ct, myLoc)
            if explorePos is not None:
                exploreScore = 1
            else:
                exploreScore = 0.4 # exploring isnt as important then
        stateScores = [attackScore, healScore, harvestScore, routeScore, exploreScore]
        stateScores.sort(key=lambda score: score, reverse=True)
        bestScore = stateScores[0]
        if bestScore == attackScore:
            self.attack(ct, attackPos)
        elif bestScore == healScore:
            self.heal(ct, healPos)
        elif bestScore == routeScore:
            self.route(ct, routePos, routeDir)
        elif bestScore == harvestScore:
            self.harvest(ct, harvestPos)
        else:
            self.explore(ct, explorePos)
    # def attack(self, ct: Controller, attackPos: Position):
    # def heal(self, ct: Controller, healPos: Position):
    def route(self, ct: Controller, routePos: Position, routeDir: Direction):
        self.mapPf.routeConveyor(ct, routePos)
    def harvest(self, ct: Controller, harvestPos: Position):
        myLoc = ct.get_position()
        dist = harvestPos.distance_squared(myLoc)
        if dist > 2:
            self.mapPf.moveTo(ct, harvestPos)
            return
        elif dist == 2:
            for d in CARDINALS:
                nextPos = myLoc.add(d)
                if nextPos.distance_squared(harvestPos) == 1 and ct.can_move(d):
                    ct.move(d)
                    break
            return
        elif dist == 0:
            for d in CARDINALS:
                if ct.can_move(d):
                    ct.move(d)
                    break
            return
        if ct.can_build_harvester(harvestPos):
            ct.build_harvester(harvestPos)
    def explore(self, ct: Controller, explorePos: Position):
        myLoc = ct.get_position()
        if explorePos is None:
            corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
            explorePos = corners[ct.get_current_round() // 20 % 4]
        self.mapPf.moveTo(ct, explorePos)