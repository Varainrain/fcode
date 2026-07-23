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

    def runCore(self, ct: Controller) -> None:
        if self.numSpawned == 0:
           self.fiveDirections =  self.initSpawn.setBestFive(ct)
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
            if ct.can_spawn(spawnPos):
                ct.spawn_builder(spawnPos)
                self.numSpawned += 1
                ct.write_store(0, self.numSpawned )
                ct.write_store(7, target.x * 32 + target.y) #
                self.fiveDirections.remove(spawnAngle) # so it doesnt spawn in the same spot twice.
    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
    def builderBot(self, ct: Controller):
        myLoc = get.get_position()
        self.mapPf.setupMap(ct)
        if self.initTarget is None:
                compact = ct.read_store(7)
                self.initTarget = Position(compact // 32, compact % 32)
            self.mapPf.moveTo(ct, self.initTarget)
            ct.draw_indicator_line(myLoc, self.initTarget, 255, 255, 255)
        self.turnsAlive += 1
        self.pickBestState(ct, myLoc)
    def pickBestState(self, ct: Controller, myLoc: Position):
        myTeam = ct.get_team()
        attackScore = 0
        attackPos = None
        for b in ct.get_nearby_units():
            bTeam = ct.get_team(b)
            buildingScore = 0
            if bTeam != myTeam:
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                if bType in [EntityType.GUNNER, EntityType.SENTINEL, EntityType.CORE]:
                    buildingScore = 8
                elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                    buildingScore = 6
                elif bType == EntityType.BUILDER_BOT:
                    buildingScore = 4
                else:
                    buildingScore = 2
            dist = myLoc.distance_squared(bPos)
            buildingScore = buildingScore * (1 - dist/40)
            if buildingScore > attackScore:
                attackScore = buildingScore
                attackPos = bPos # no need to worry about this not being initialized, as it needs buildingScore > attackScore, so there must be a position
        healScore = 0
        healPos = None
        for b in ct.get_nearby_units():
            bTeam = ct.get_team(b)
            buildingScore = 0
            if bTeam == myTeam:
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                if bType in [EntityType.BUILDER_BOT, EntityType.CORE:]:
                    buildingScore = 8
                elif bType in [EntityType.GUNNER, EntityType.SENTINEL]:
                    buildingScore = 6
                elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                    buildingScore = 4 
                else:
                    buildingScore = 2
            dist = myLoc.distance_squared(bPos)
            cHP = ct.get_hp(b)
            mHP = ct.gret_max_hp(b)
            buildingScore = buildingScore * (1 - dist/120) * (1 - cHP/mHP)
            if buildingScore > healScore:
                healScore = buildingScore
                healPos = bPos
        routeScore = 0
        exploreScore = 0