from fcode import *
from coreHelper import *
from pathfinding import *
from defend import *
import math
import random
# This file contains the eco bot code, ported from Cambridge Battlecode to
# the Florent Code League (fcode) API.

Directions = [d for d in Direction if d != Direction.CENTRE]
DIRECTIONS = Directions  # alias used in attack()
CardDirections = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]


class Player:
    def __init__(self):
        # Other Files
        self.pf = Pathfinder()
        self.defender = Defender()

        self.numSpawned = 0

        # Role
        self.attackMode = False
        self.alwaysDefense = False
        self.defenseMode = False
        self.justSpawned = True

        # Attacking
        self.attackPos = None
        self.spawnSentinelHere = None

        # Cores
        self.teamCore = None        # reference corner tile of the (2x2) core
        self.teamCoreTiles = None   # all tiles of the core footprint
        self.enemyCore = None

        # Launcher Proofing
        self.oldPos = None

        # Harvester Finding
        self.currentHarvester = None
        self.foundHarvester = None
        self.usedHarvesters = []
        self.reachHarvesterTime = 0

        # Building Back + Sentinel Placment
        self.conveyorEnd = None
        self.surroundHarvester = False
        self.protectTurns = 0
        self.sentinelSpot = None
        self.isEnemyInfastructure = None
        self.nextTurretCountDown = 0

        # Placing Gunner On Attack
        self.turretTimeOut = 0  # Starts when turret is placed
        self.enemyPos = None
        self.enemyType = -1
        # Exploring
        self.explorePos = None
        self.exploreTime = 0
        self.attackMoveTimeout = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
        elif etype == EntityType.SENTINEL:
            self.sentinel(ct)
        elif etype == EntityType.LAUNCHER:
            self.launcher(ct)

    def core(self, ct: Controller) -> None:
        if spawnBots(self.numSpawned, ct) == False:
            return

        threats = findThreats(ct)

        for i in Directions:
            isThreat = False
            spawnPos = ct.get_position().add(i)
            for j in threats:
                if spawnPos.distance_squared(j) <= 2:
                    isThreat = True
            if ct.can_spawn(ct.get_position().add(i)) and isThreat == False:
                ct.spawn_builder(ct.get_position().add(i))
                self.numSpawned += 1

    def sentinel(self, ct: Controller) -> None:
        for j in ct.get_attackable_tiles():
            if ct.get_tile_building_id(j) is not None:
                ct.draw_indicator_line(ct.get_position(), j, 255, 255, 255)
        if self.enemyCore is None:
            self.enemyCore = findEnemyCore(ct)
        if self.enemyCore is not None:
            if ct.can_fire(self.enemyCore):
                ct.fire(self.enemyCore)
        else:
            for j in ct.get_attackable_tiles():
                if ct.get_tile_building_id(j) is not None:
                    i = ct.get_tile_building_id(j)
                    if ct.get_team(i) != ct.get_team():
                        if ct.get_entity_type(i) == EntityType.SENTINEL or ct.get_entity_type(i) == EntityType.GUNNER:
                            if ct.can_fire(ct.get_position(i)):
                                ct.fire(ct.get_position(i))
                                return
            for j in ct.get_attackable_tiles():
                if ct.get_tile_building_id(j) is not None:
                    i = ct.get_tile_building_id(j)
                    if ct.get_team(i) != ct.get_team():
                        if ct.get_entity_type(i) == EntityType.CONVEYOR:
                            if ct.can_fire(ct.get_position(i)):
                                ct.fire(ct.get_position(i))
                                return
            for j in ct.get_attackable_tiles():
                if ct.get_tile_building_id(j) is not None:
                    i = ct.get_tile_building_id(j)
                    if ct.get_team(i) != ct.get_team():
                        if ct.can_fire(ct.get_position(i)):
                            ct.fire(ct.get_position(i))
                            return

    def launcher(self, ct: Controller):
        myLoc = ct.get_position()

        for d in Directions:
            adjacent = myLoc.add(d)
            if adjacent.x < 0 or adjacent.y < 0 or adjacent.x >= ct.get_map_width() or adjacent.y >= ct.get_map_height():
                continue
            bot_id = ct.get_tile_builder_bot_id(adjacent)
            if bot_id is not None and ct.get_team(bot_id) != ct.get_team():
                best = None
                bestDist = 0
                for tile in ct.get_nearby_tiles(26):
                    if ct.can_launch(adjacent, tile):
                        dist = tile.distance_squared(myLoc)
                        if dist > bestDist:
                            bestDist = dist
                            best = tile
                if best is not None:
                    ct.launch(adjacent, best)
                    return

    def builderBot(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        if ct.get_hp() < ct.get_max_hp():
            if ct.can_heal(myLoc):
                ct.heal(myLoc)
        currentRound = ct.get_current_round()
        self.setUp(ct, myLoc)
        if ct.get_id() < 5 and ((self.currentHarvester is None and currentRound > 24)):
            self.alwaysDefense = True
        if currentRound % 120 == 1 or self.justSpawned:
            self.assignRole(ct, currentRound)
        self.justSpawned = False
        self.defender.defendInfrastructure(ct, self.teamCore, self.pf)

        if self.attackMode == True:
            self.attack(ct)
            return
        if self.defenseMode:
            self.defender.defendInfrastructure(ct, self.teamCore, self.pf)
            healPos = self.defender.picHealingLoc(ct, self.teamCore, self.alwaysDefense)
            if healPos is not None:
                self.pf.moveTo(ct, healPos)
            return
        else:
            if self.currentHarvester is not None:
                if self.surroundHarvester:
                    self.buildConveyor(ct)
                else:
                    self.protectHarvester(ct)
            else:
                self.getHarvester(ct, myLoc)
                if self.foundHarvester is None and self.currentHarvester is None:
                    if self.explorePos is None or self.exploreTime > 35 or self.explorePos.distance_squared(myLoc) <= 4:
                        self.pickExplore(ct, currentRound)
                        self.exploreTime = 0
                    self.exploreTime += 1
                    ct.draw_indicator_line(myLoc, self.explorePos, 255, 255, 255)
                    self.pf.moveTo(ct, self.explorePos)

    def setUp(self, ct: Controller, myLoc: Position):
        if self.teamCore is None:
            self.teamCore = findTeamCore(ct)
            if self.teamCore is not None:
                self.teamCoreTiles = self._computeCoreTiles(ct, self.teamCore)
        if self.enemyCore is None:
            self.enemyCore = findEnemyCore(ct)
        if self.oldPos is not None and myLoc.distance_squared(self.oldPos) > 2:
            self.pf.reset()
        self.oldPos = myLoc

    def _computeCoreTiles(self, ct: Controller, corner: Position) -> list:
        cid = ct.get_tile_building_id(corner)
        tiles = []
        if cid is not None:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = Position(corner.x + dx, corner.y + dy)
                    if self.isInBounds(ct, q) and ct.get_tile_building_id(q) == cid:
                        tiles.append(q)
        return tiles if tiles else [corner]

    def nearCore2(self, pos: Position) -> int:
        tiles = self.teamCoreTiles if self.teamCoreTiles else [self.teamCore]
        return min(pos.distance_squared(t) for t in tiles)

    def assignRole(self, ct: Controller, currentRound):

        if currentRound <= 120:
            # 36% Offense, 64% Eco + 1 Defense Bot
            if currentRound % 11 in [2, 5, 7, 0] and self.currentHarvester is None:
                self.attackMode = True
            else:
                self.defenseMode = False
                self.attackMode = False
        if currentRound % 120 == 1 and currentRound > 120:
            # 25% Defense, 35% Offense, 40% Eco
            self.defenseMode = False
            self.attackMode = False
            if self.currentHarvester is None:
                role = random.random()
                if role > 0.75 or self.alwaysDefense == True:
                    self.defenseMode = True
                elif role > 0.4 and currentRound > 120:
                    self.attackMode = True

    def attack(self, ct: Controller) -> None:
        myLoc = ct.get_position()

        # Determine attack destination
        if self.attackPos is None:
            self.attackPos = Position(
                ct.get_map_width() - self.teamCore.x,
                ct.get_map_height() - self.teamCore.y
            )
            self.attackMoveTimeout = 0
        if self.enemyCore is not None:
            self.attackPos = self.enemyCore
            
        def changeAttackPos (ct: Controller):
            dx = 5 * random.randint(-1, 1) # more consistently farther away
            dy = 5 * random.randint(-1, 1)
            new_x = max(0, min(self.attackPos.x + dx, ct.get_map_width() - 1))
            new_y = max(0, min(self.attackPos.y + dy, ct.get_map_height() - 1))
            self.attackPos = Position(new_x, new_y)
            self.attackMoveTimeout = 0
        
        # Jitter so we don't stand still on the target
        if myLoc.distance_squared(self.attackPos) < 8:
            changeAttackPos(ct)

        
        if self.spawnSentinelHere is None: # Pick a sentinel placement spot near the attack target
            nearbyEnemyStuff = []
            isStuff = False
            for i in ct.get_nearby_buildings():
                if ct.get_entity_type(i) == EntityType.CONVEYOR:
                    if ct.get_team(i) != ct.get_team() and ct.get_stored_resource(i) is not None:
                        nearbyEnemyStuff.append(ct.get_position(i))
                        isStuff = True
            nearbyEnemyStuff.sort(key=lambda p: p.distance_squared(self.attackPos))
            
            if not isStuff: # no enemy infastructure was found
                self.attackMoveTimeout += 1
                self.pf.moveTo(ct, self.attackPos)
                if self.attackMoveTimeout > 20: # While moving to attack pos, no enemy infastructure was found for 20 turns, change it
                    changeAttackPos(ct)
                return
            else: # stuff was found, now reuse attackMoveTimeout for sentinelSpot
                self.spawnSentinelHere = nearbyEnemyStuff[0]
                self.attackMoveTimeout = 0

        # From now on there must be a sentinel Spot
        
        # first check if there is already another sentinel close by
        for b_id in ct.get_nearby_buildings():
            if ct.get_entity_type(b_id) == EntityType.SENTINEL and ct.get_team(b_id) == ct.get_team():
                if ct.get_position(b_id).distance_squared(self.spawnSentinelHere) <= 8:
                    self.spawnSentinelHere = None
                    self.attackMoveTimeout = 0
                    self.pf.moveTo(ct, self.attackPos)
                    return

        if self.attackMoveTimeout > 25: # This spot is hard to get, switch to another one
            self.spawnSentinelHere = None
            self.attackMoveTimeout = 0
            return
       
        if myLoc.distance_squared(self.spawnSentinelHere) < 1: # this means you are close enough to the sentinelSpot
            self.attackMoveTimeout = 0
        else:
            self.pf.moveTo(ct, self.spawnSentinelHere)
            self.attackMoveTimeout += 1
            return


        if ct.get_tile_building_id(self.spawnSentinelHere) is not None: # if there is something else there clear it
            thingTeam = ct.get_team(ct.get_tile_building_id(self.spawnSentinelHere))
            if thingTeam == ct.get_team():
                if ct.can_destroy(self.spawnSentinelHere):
                    ct.destroy(self.spawnSentinelHere)
            else:
                self.defender.placeLauncher(ct, self.spawnSentinelHere)
                self.pf.moveTo(ct, self.spawnSentinelHere)
                if ct.can_fire(self.spawnSentinelHere) and ct.get_global_resources() > 25:
                    ct.fire(self.spawnSentinelHere)

        
        if ct.get_tile_building_id(self.spawnSentinelHere) is None: # Tile is clear — build sentinel facing the most valuable targets
            if myLoc == self.spawnSentinelHere:
                self.pf.moveTo(ct, self.attackPos)
            directionChoices = {d: 0 for d in DIRECTIONS}
            for i in ct.get_nearby_buildings():
                if ct.get_team(i) != ct.get_team():
                    d = self.spawnSentinelHere.direction_to(ct.get_position(i))
                    if ct.get_entity_type(i) == EntityType.CORE:
                        directionChoices[d] += 25
                    else:
                        directionChoices[d] += 1

            directionChoice = max(directionChoices, key=lambda d: directionChoices[d])

            if ct.can_build_sentinel(self.spawnSentinelHere, directionChoice):
                ct.build_sentinel(self.spawnSentinelHere, directionChoice)
                self.spawnSentinelHere = None
                self.attackPos = None



    def pickExplore(self, ct: Controller, currentRound):
        w = ct.get_map_width()
        h = ct.get_map_height()
        myLoc = ct.get_position()
        radius = (w + h) // 5

        theta = random.random() * 2 * math.pi
        tx = int(max(0, min(w - 1, myLoc.x + math.cos(theta) * radius)))
        ty = int(max(0, min(h - 1, myLoc.y + math.sin(theta) * radius)))
        self.explorePos = Position(tx, ty)

    def getHarvester(self, ct: Controller, myLoc: Position):
        if self.foundHarvester is None:
            nearbyOres = []
            for i in ct.get_nearby_tiles():
                if ct.is_in_vision(i):
                    if ct.get_tile_env(i) == Environment.ORE_TITANIUM:
                        nearbyOres.append(i)
            nearbyOres.sort(key=lambda p: p.distance_squared(myLoc))
            found = False
            for t in nearbyOres:
                tID = ct.get_tile_building_id(t)
                willWork = False
                if t not in self.usedHarvesters:
                    if tID is None:
                        willWork = True
                    elif ct.get_team(tID) == ct.get_team():
                        willWork = True
                    elif ct.get_entity_type(tID) == EntityType.HARVESTER:
                        willWork = True
                if willWork and self.foundHarvester is None:
                    self.foundHarvester = t
                    self.reachHarvesterTime = 0
                    found = True
            if found == False:
                return
        if self.reachHarvesterTime >= 40:  # Limit time spend trying to reach the harvester
            self.removeHarvester(ct)
            return
        if ct.is_in_vision(self.foundHarvester) and ct.get_tile_building_id(self.foundHarvester) is not None:  # Checks on current ore tile
            oreID = ct.get_tile_building_id(self.foundHarvester)
            if ct.get_team(oreID) == ct.get_team():
                if ct.get_entity_type(oreID) == EntityType.HARVESTER:  # Already is a team harvester
                    self.removeHarvester(ct)
                    return
                else:
                    if ct.can_destroy(self.foundHarvester) and myLoc.distance_squared(self.foundHarvester) == 1:  # Remove to have room for harvester
                        ct.destroy(self.foundHarvester)
            elif ct.get_entity_type(oreID) != EntityType.HARVESTER:  # Nothing you can do
                self.removeHarvester(ct)
                return
        if myLoc == self.foundHarvester:
            possibleSpots = []
            for i in CardDirections:
                pos = myLoc.add(i)
                if self.isInBounds(ct, pos) and self.pf.canMove(ct, i):
                    possibleSpots.append((i, pos))
            possibleSpots.sort(key=lambda x: self.nearCore2(x[1]))
            if len(possibleSpots) > 0:
                self.pf._move(ct, possibleSpots[0][0])
            else:
                self.usedHarvesters.append(self.foundHarvester)
                self.foundHarvester = None
            return
        myLoc = ct.get_position()
        if myLoc.distance_squared(self.foundHarvester) > 1:
            self.pf.moveTo(ct, self.foundHarvester)
            self.reachHarvesterTime += 1
        myLoc = ct.get_position()
        if myLoc.distance_squared(self.foundHarvester) == 1:
            if ct.can_build_harvester(self.foundHarvester):  # Built the harvester
                ct.build_harvester(self.foundHarvester)
                self.addHarvester(ct, myLoc)
                return
            oreID = ct.get_tile_building_id(self.foundHarvester)
            if oreID is not None and ct.get_entity_type(oreID) == EntityType.HARVESTER and ct.get_team(oreID) != ct.get_team():  # Right next to an enemy harvester
                self.addHarvester(ct, myLoc)
                return
            return

    def removeHarvester(self, ct: Controller):
        self.usedHarvesters.append(self.foundHarvester)
        self.foundHarvester = None
        self.reachHarvesterTime = 0

    def addHarvester(self, ct: Controller, myLoc):
        # Book keeping
        self.currentHarvester = self.foundHarvester
        self.usedHarvesters.append(self.foundHarvester)
        self.foundHarvester = None
        self.conveyorEnd = myLoc
        # Protect Harvester
        self.surroundHarvester = False
        self.isEnemyInfastructure = None
        self.sentinelSpot = None
        # Placing Sentinel on Offense
        self.turretTimeOut = 0
        self.enemyPos = None
        self.enemyType = -1

    def protectHarvester(self, ct: Controller):
        if self.protectTurns > 12:
            self.protectTurns = 0
            self.surroundHarvester = True
            self.isEnemyInfastructure = None
            self.sentinelSpot = None
            return

        self.protectTurns += 1
        if self.isEnemyInfastructure is None:
            for i in ct.get_nearby_buildings():
                if ct.get_team(i) != ct.get_team():
                    self.isEnemyInfastructure = ct.get_position(i)

        protectSpots = []
        for i in CardDirections:
            pos = self.currentHarvester.add(i)
            if self.isInBounds(ct, pos) and ct.is_in_vision(pos) and pos != self.conveyorEnd:
                if ct.get_tile_env(pos) != Environment.WALL:
                    if ct.get_tile_building_id(pos) is None:
                        protectSpots.append(pos)
        if len(protectSpots) == 0:
            self.protectTurns = 0
            self.surroundHarvester = True
            self.isEnemyInfastructure = None
            self.sentinelSpot = None
            return

        if self.isEnemyInfastructure and self.sentinelSpot is None:
            protectSpots.sort(key=lambda c: c.distance_squared(self.isEnemyInfastructure))
            self.sentinelSpot = protectSpots[0]

        protectSpots.sort(key=lambda c: c.distance_squared(ct.get_position()))

        for i in protectSpots:
            bID = ct.get_tile_building_id(i)
            etype = None
            if bID is not None:
                etype = ct.get_entity_type(bID)
            if ct.get_position() == i and bID is None:
                self.pf.moveTo(ct, self.currentHarvester)
            if ct.get_position().distance_squared(i) > 2:
                self.pf.moveTo(ct, i)
            if i == self.sentinelSpot:
                if ct.can_build_sentinel(i, i.direction_to(self.isEnemyInfastructure)):
                    ct.build_sentinel(i, i.direction_to(self.isEnemyInfastructure))
                    return
            else:
                if ct.can_build_barrier(i):
                    ct.build_barrier(i)
                    return
            return

    def buildConveyor(self, ct: Controller):
        ct.draw_indicator_dot(self.conveyorEnd, 255, 255, 255)
        myLoc = ct.get_position()
        if self.nearCore2(self.conveyorEnd) == 0:  # frontier is on the core (delivery handled in buildCloser)
            self.currentHarvester = None
            self.conveyorEnd = None
            return
        if myLoc.distance_squared(self.conveyorEnd) > 2:
            self.pf.moveTo(ct, self.conveyorEnd)

        if myLoc.distance_squared(self.conveyorEnd) < 4:
            conveyorID = ct.get_tile_building_id(self.conveyorEnd)
            if conveyorID is None and self.nextTurretCountDown <= 0:
                if myLoc.distance_squared(self.conveyorEnd) > 0 and self.enemyPos is None and self.turretTimeOut == 0:
                    for i in ct.get_nearby_buildings():  # If a target exists it will find it
                        if ct.get_team(i) != ct.get_team():
                            ct.draw_indicator_dot(ct.get_position(i), 200, 20, 100)
                            eType = ct.get_entity_type(i)
                            pos = ct.get_position(i)
                            if eType in [EntityType.SENTINEL, EntityType.GUNNER]:
                                self.enemyPos = pos
                                self.enemyType = 3
                            elif eType == EntityType.CORE and self.enemyType < 2:
                                self.enemyPos = pos
                                self.enemyType = 2
                            elif eType == EntityType.CONVEYOR and self.enemyType < 1:
                                self.enemyPos = pos
                                self.enemyType = 1
                            elif eType == EntityType.LAUNCHER and self.enemyType < 0:
                                self.enemyPos = pos
                                self.enemyType = 0
            if self.enemyPos is not None and self.turretTimeOut == 0:  # If it hasn't built a turret yet it waits until it can
                if ct.can_build_sentinel(self.conveyorEnd, self.conveyorEnd.direction_to(self.enemyPos)):
                    ct.build_sentinel(self.conveyorEnd, self.conveyorEnd.direction_to(self.enemyPos))
                    self.turretTimeOut += 1
                    self.nextTurretCountDown = 3
                else:
                    return
            if self.turretTimeOut > 0:
                self.turretTimeOut += 1
            if self.enemyType == 2 and self.turretTimeOut > 0:  # It's a core you're attacking, so leave the turret there
                self.currentHarvester = None
                self.conveyorEnd = None
                self.enemyPos = None
                self.enemyType = -1
                return
            if self.turretTimeOut > 16:
                self.enemyPos = None
                self.enemyType = -1
            elif self.turretTimeOut > 0:
                return
            self.buildCloser(ct)

    def buildCloser(self, ct: Controller):
        myLoc = ct.get_position()
        endID = ct.get_tile_building_id(self.conveyorEnd)
        if endID is not None:
            endEntity = ct.get_entity_type(endID)
            if endEntity in [EntityType.CONVEYOR] and ct.get_team(endID) == ct.get_team():
                self.conveyorEnd = None
                self.currentHarvester = None
                return
            elif ct.can_destroy(self.conveyorEnd):
                ct.destroy(self.conveyorEnd)
            if myLoc != self.conveyorEnd:
                self.pf.moveTo(ct, self.conveyorEnd)
            if self.defender.destroyTurns > 5:
                self.defender.placeLauncher(ct, self.conveyorEnd)
            if ct.can_fire(self.conveyorEnd):
                ct.fire(self.conveyorEnd)
                self.defender.destroyTurns += 1

        # Candidate cardinal conveyor extensions toward the core.
        possibleConveyors = []
        for i in CardDirections:
            end = self.conveyorEnd.add(i)
            if self.isInBounds(ct, end):
                if ct.can_build_conveyor(self.conveyorEnd, i) and (ct.get_tile_env(end) == Environment.EMPTY or ct.get_tile_env(end) == Environment.ORE_TITANIUM):
                    possibleConveyors.append(i)
        possibleConveyors.sort(key=lambda c: self.nearCore2(self.conveyorEnd.add(c)))

        # Try to build a conveyor directly adjacent to the core
        for i in possibleConveyors:
            end = self.conveyorEnd.add(i)
            if self.nearCore2(end) == 0:
                if ct.can_build_conveyor(self.conveyorEnd, i):
                    ct.build_conveyor(self.conveyorEnd, i)
                    self.nextTurretCountDown = 0
                    self.currentHarvester = None
                    self.conveyorEnd = None
                    return

        # Try to link into an existing friendly conveyor that's closer to the core
        for i in possibleConveyors:
            end = self.conveyorEnd.add(i)
            if self.nearCore2(end) < self.nearCore2(self.conveyorEnd):
                endID = ct.get_tile_building_id(end)
                if endID is not None:
                    endEntity = ct.get_entity_type(endID)
                    if endEntity == EntityType.CONVEYOR and ct.get_team(endID) == ct.get_team():
                        if ct.can_build_conveyor(self.conveyorEnd, i) and ct.get_stored_resource(endID) is None:
                            ct.build_conveyor(self.conveyorEnd, i)
                            self.nextTurretCountDown = 0
                            self.currentHarvester = None
                            self.conveyorEnd = None
                            self.turretTimeOut = 0
                            self.enemyPos = None
                            self.enemyType = -1
                            return

        # Extend one step closer with the best available conveyor
        for i in possibleConveyors:
            end = self.conveyorEnd.add(i)
            endID2 = ct.get_tile_building_id(end)
            if endID2 is None or (ct.get_entity_type(endID2) == EntityType.BARRIER and ct.get_team(endID2) == ct.get_team()):
                if ct.can_build_conveyor(self.conveyorEnd, i):
                    ct.build_conveyor(self.conveyorEnd, i)
                    self.nextTurretCountDown -= 1
                    self.conveyorEnd = end
                    self.turretTimeOut = 0
                    self.enemyPos = None
                    self.enemyType = -1
                    return

    def isInBounds(self, ct: Controller, pos: Position) -> bool:
        W = ct.get_map_width() - 1
        H = ct.get_map_height() - 1
        if pos.x == max(0, min(W, pos.x)) and pos.y == max(0, min(H, pos.y)):
            return True
        return False
