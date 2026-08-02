"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

# If the core goes below 400 health, and sees a gunner attacking it, it will immediately send a 'recall' order in the next unused slot, where the other bots will walk back to team core, scored based on their distance to it. Synergizes well with OogwayTestExplore
# and spend up titanium to get to 50 ammo, stopping when it has 20 titanium left

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
gunnerAttacks = [
    Position(0, 1), Position(0, 2), Position(0, 3),
    Position(0, -1), Position(0, -2), Position(0, -3),
    Position(-1, 0), Position(-2, 0), Position(-3, 0),
    Position(1, 0), Position(2, 0), Position(3, 0),
    Position(-1, 1), Position(-2, 2),
    Position(-1, -1), Position(-2, -2),
    Position(1, 1), Position(2, 2),
    Position(1, -1), Position(2, -2)
]
# slot 0 numSpawned, slot 1-6 map sharing, slot 7 initial target, slot 8 symmetry (mapPathfinding)
RECALL_SLOT = 9 # core-written: 1 while under attack and low HP, else 0
TEAM_CORE_SLOT = 10 # core-written every turn: its own position. Gunners never call
                     # setupMap(), so self.mapPf.teamCore is always None for them -
                     # this is the only way a gunner can find out where home is.
CORE_HP_FLOOR = 400 # below this + an actual threat gunner in vision, sound the recall
GUNNER_ROTATE_FLOOR_NORMAL = 60
GUNNER_ROTATE_FLOOR_COREDEFENSE = 25 # relaxed when the best target is a gunner hitting our core

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
        globalAmmo = ct.get_global_ammo()
        globalTitanium = ct.get_global_resources()

        myLoc = ct.get_position()
        ct.write_store(TEAM_CORE_SLOT, myLoc.x * 32 + myLoc.y)

        underAttack = ct.get_hp() < CORE_HP_FLOOR and self.nearestEnemyGunner(ct, ct.get_team()) is not None
        ct.write_store(RECALL_SLOT, 1 if underAttack else 0)

        if globalTitanium > 200 + 40 * self.numSpawned:
            for i in ct.get_nearby_tiles():
                if ct.can_spawn(i):
                    ct.spawn_builder(i)
                    corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
                    corners.sort(key=lambda corner: corner.distance_squared(ct.get_position()))
                    ct.write_store(7, corners[0].x * 32 + corners[0].y)
                    break

        if underAttack:
            # push ammo up toward 16 instead of the normal floor of 28, but never
            # convert the last 28 Ti - still need to be able to afford repairs/builds
            convertAmount = min(20 - globalAmmo, globalTitanium - 28)
            if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
                ct.convert_ammo(convertAmount)
        elif globalAmmo < 16 and globalTitanium > 20:
            if ct.can_convert_ammo(16 - globalAmmo):
                ct.convert_ammo(16 - globalAmmo)
        
    def run(self, ct: Controller) -> None:
        if self.mapW is None:
            self.mapH = ct.get_map_height()
            self.mapW = ct.get_map_width()
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
        elif etype == EntityType.GUNNER:
            self.runGunner(ct)
    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.numSpawned = ct.read_store(0)
        self.mapPf.setupMap(ct)
        if self.initTarget is None: # set initial target for the first explore
            compact = ct.read_store(7)
            self.initTarget = Position(compact // 32, compact % 32)
        self.turnsAlive += 1
        self.runBestState(ct, myLoc)
    def coreThreatSpots(self, ct: Controller):
        """Every [pos, facing] spot that could hit one of our core's 4 tiles,
        read from TEAM_CORE_SLOT since a gunner's own mapPf.teamCore is
        always None (gunners never call setupMap())."""
        compact = ct.read_store(TEAM_CORE_SLOT)
        teamCore = Position(compact // 32, compact % 32)
        corners = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
                   teamCore.add(Direction.SOUTH).add(Direction.EAST)]
        spots = set()
        for corner in corners:
            for spotPos, spotDir in self.mapPf.gunnerSpots(corner, self.mapW, self.mapH, blocked=False):
                spots.add((spotPos.x, spotPos.y, spotDir))
        return spots

    def runGunner (self, ct: Controller):
        curTarget = ct.get_gunner_target()
        myDir = ct.get_direction()
        myPos = ct.get_position()
        myTeam = ct.get_team()
        if curTarget is not None:
            targetId = ct.get_tile_building_id(curTarget)
            bbId = ct.get_tile_builder_bot_id(curTarget)
            if bbId is not None and ct.get_team(bbId) == myTeam:
                return # dont kill your own bot
            if targetId is not None and ct.get_team(targetId) != ct.get_team():
                if ct.can_fire(curTarget):
                    ct.fire(curTarget)
                    return
        threatSpots = self.coreThreatSpots(ct) # scan always runs now, resource check moves to the end
        bestScore = 0
        bestDir = myDir # so you only rotate when you need to
        bestIsCoreDefense = False
        for d in DIRECTIONS:
            curScore = 0
            curIsCoreDefense = False
            for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
                tileId = ct.get_tile_building_id(tile)
                bbId = ct.get_tile_builder_bot_id(tile)
                if tileId is not None and ct.get_team(tileId) != myTeam:
                    tType = ct.get_entity_type(tileId)
                    if tType in [EntityType.GUNNER, EntityType.SENTINEL]:
                        curScore += 10
                        if tType == EntityType.GUNNER and (tile.x, tile.y, ct.get_direction(tileId)) in threatSpots:
                            curIsCoreDefense = True # this gunner is itself aimed at our core
                    elif tType == EntityType.CORE:
                        curScore += 8
                    elif tType in [EntityType.LAUNCHER, EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER]:
                        curScore += 4
                    else:
                        curScore += 1
                    if bbId is not None and ct.get_team(bbId) != myTeam:
                        curScore += 4
            if curScore > bestScore:
                bestScore = curScore
                bestDir = d
                bestIsCoreDefense = curIsCoreDefense
        if bestDir != myDir:
            floor = GUNNER_ROTATE_FLOOR_COREDEFENSE if bestIsCoreDefense else GUNNER_ROTATE_FLOOR_NORMAL
            if ct.get_global_resources() > floor and ct.can_rotate(bestDir):
                ct.rotate(bestDir)


    def nearbyAllyBuilders(self, ct: Controller, nearbyUnits, myTeam):
        """[(id, pos), ...] for every ally builder bot in this bot's vision,
        including itself. Computed once per turn and reused across every
        target-exclusivity check below, instead of re-filtering nearbyUnits
        per candidate."""
        allies = []
        for b in nearbyUnits:
            if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.BUILDER_BOT:
                allies.append((b, ct.get_position(b)))
        return allies

    def isClosestAllyTo(self, allies, myId: int, myLoc: Position, target: Position) -> bool:
        """True if no other visible ally builder is closer to target than we
        are (ties broken by lower id). Needs no messaging: every bot computes
        the same answer from its own vision, so as long as the two builders
        contending for a target can see each other, they agree on who backs
        off - one keeps the candidate, the other falls through to its next
        best option instead of walking to a target someone else already has.
        A builder outside our vision that is secretly closer isn't accounted
        for; that's a double-claim, not a wasted trip, and gets no worse than
        today's behaviour (which does no exclusivity check at all)."""
        for aId, aPos in allies:
            if aId == myId:
                continue
            aDist = aPos.distance_squared(target)
            myDist = myLoc.distance_squared(target)
            if aDist < myDist or (aDist == myDist and aId < myId):
                return False
        return True

    def coveredTiles(self, ct: Controller, myTeam):
        """Every tile some existing team gunner or sentinel already threatens.

        Gunners are checked at every facing, not just their current one - the
        decision here is whether to BUILD another turret, so what matters is
        whether an existing one could be rotated onto this target, not where
        it happens to be pointed this turn. Sentinels cannot rotate, so only
        their built facing is checked. This is the raw attack pattern (walls
        do not block it), so a wall-shielded target can be under-covered -
        that just means we occasionally build a redundant turret, not that
        we skip a needed one.
        """
        covered = set()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType == EntityType.GUNNER:
                bPos = ct.get_position(b)
                for d in DIRECTIONS:
                    for t in ct.get_attackable_tiles_from(bPos, d, EntityType.GUNNER):
                        covered.add((t.x, t.y))
            elif bType == EntityType.SENTINEL:
                bPos = ct.get_position(b)
                bDir = ct.get_direction(b)
                for t in ct.get_attackable_tiles_from(bPos, bDir, EntityType.SENTINEL):
                    covered.add((t.x, t.y))
        return covered

    def nearestEnemyGunner(self, ct: Controller, myTeam):
        """Nearest enemy GUNNER that can actually hit one of our core's 4
        tiles right now, or None. A gunner merely being nearby isn't enough -
        its exact (position, facing) has to be one of the spots gunnerSpots
        finds for at least one core tile, i.e. it has to actually be aimed at
        us, not just standing around close by."""
        if ct.get_entity_type(ct.get_id()) == EntityType.CORE:
            myLoc = ct.get_position() # core's own tile is the corner tiles' top-left
        else:
            myLoc = self.mapPf.teamCore
        coreCorners = [myLoc, myLoc.add(Direction.EAST), myLoc.add(Direction.SOUTH),
                       myLoc.add(Direction.SOUTH).add(Direction.EAST)]
        threatSpots = set()
        for corner in coreCorners:
            for spotPos, spotDir in self.mapPf.gunnerSpots(corner, self.mapW, self.mapH, blocked=False):
                threatSpots.add((spotPos.x, spotPos.y, spotDir))
        best, bestDist = None, 4096
        for b in ct.get_nearby_entities():
            if ct.get_team(b) != myTeam and ct.get_entity_type(b) == EntityType.GUNNER:
                bPos = ct.get_position(b)
                bDir = ct.get_direction(b)
                if (bPos.x, bPos.y, bDir) not in threatSpots:
                    continue # nearby, but not actually aimed to hit the core
                dist = myLoc.distance_squared(bPos)
                if dist < bestDist:
                    bestDist = dist
                    best = bPos
        return best

    def runBestState(self, ct: Controller, myLoc: Position):
        nearbyUnits = ct.get_nearby_entities() # both builder bots and buildings
        myTeam = ct.get_team()
        myId = ct.get_id()
        allyBuilders = self.nearbyAllyBuilders(ct, nearbyUnits, myTeam)

        attackScore, attackPos = self.scoreAttack(ct, myLoc, myTeam, myId, allyBuilders, nearbyUnits)
        retreatScore, retreatPos = self.scoreRetreat(ct, myLoc)
        healScore, healPos = self.scoreHeal(ct, myLoc, myTeam, nearbyUnits)
        routeScore, routePos, routeDir = self.scoreRoute(ct, myLoc, myTeam, myId, allyBuilders, nearbyUnits)
        harvestScore, harvestPos = self.scoreHarvest(ct, myLoc, myTeam, myId, allyBuilders)
        exploreScore, explorePos = self.scoreExplore(ct, myLoc)

        stateScores = [attackScore, retreatScore, healScore, harvestScore, routeScore, exploreScore]
        stateScores.sort(key=lambda score: score, reverse=True)
        bestScore = stateScores[0]
        if bestScore == attackScore:
            self.attack(ct, attackPos)
        elif bestScore == retreatScore:
            self.retreat(ct, retreatPos)
        elif bestScore == healScore:
            self.heal(ct, healPos)
        elif bestScore == routeScore:
            self.route(ct, routePos, routeDir)
        elif bestScore == harvestScore:
            self.harvest(ct, harvestPos)
        else:
            self.explore(ct, explorePos)

    def scoreRetreat(self, ct: Controller, myLoc: Position):
        """Core-sounded recall: below attack's core-defense ceiling (12) so a
        bot that can actually build a killing gunner still does that instead,
        but above everything else - urgent, though scaled a bit by distance
        per the spec (closer bots weigh it slightly more, though it stays
        high even from across the map so distant bots still come home)."""
        retreatScore = 0
        retreatPos = None
        teamCore = self.mapPf.teamCore
        if teamCore is not None and ct.read_store(RECALL_SLOT) == 1:
            dist = myLoc.distance_squared(teamCore)
            retreatScore = max(7, 9 * (1 - dist / 300))
            retreatPos = teamCore
        return retreatScore, retreatPos

    def retreat(self, ct: Controller, retreatPos: Position):
        self.mapPf.moveTo(ct, retreatPos)

    def scoreAttack(self, ct: Controller, myLoc: Position, myTeam, myId, allyBuilders, nearbyUnits):
        # attack, max score of 10
        attackScore = 0
        attackPos = None
        if ct.get_global_resources() > 10:
            coreThreat = self.nearestEnemyGunner(ct, ct.get_team())
            if coreThreat is not None and (coreThreat.x, coreThreat.y) not in self.coveredTiles(ct, myTeam):
                if self.isClosestAllyTo(allyBuilders, myId, myLoc, coreThreat): # only the closest bot commits - others fall through instead of piling on
                    attackScore = 15
                    attackPos = coreThreat
        if ct.get_id() > 4: # dont attack if u r broke and leave one bot for defense
            covered = self.coveredTiles(ct, myTeam)
            for b in nearbyUnits: # looks at nearby enemies, and scored on entity type and distance
                bTeam = ct.get_team(b)
                buildingScore = 0
                if bTeam != myTeam:
                    bPos = ct.get_position(b)
                    bType = ct.get_entity_type(b)
                    if bType in [EntityType.CORE] and ct.get_global_resources() > 25:
                        buildingScore = 10
                    elif bType in [EntityType.GUNNER, EntityType.SENTINEL] and ct.get_global_resources() > 110:
                        buildingScore = 10
                    elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER] and ct.get_global_resources() > 115:
                        buildingScore = 8
                    elif bType == EntityType.BUILDER_BOT and ct.get_global_resources() > 125:
                        buildingScore = 4
                    elif ct.get_global_resources() > 160:
                        buildingScore = 1
                else:
                    continue
                if (bPos.x, bPos.y) in covered and buildingScore != 10:
                    continue # an existing team gunner/sentinel can already reach this target
                dist = myLoc.distance_squared(bPos)
                buildingScore = buildingScore * (1 - dist/48)
                if buildingScore > attackScore:
                    attackScore = buildingScore
                    attackPos = bPos # no need to worry about this not being initialized, as it needs buildingScore > attackScore, so there must be a position
        return attackScore, attackPos

    def scoreHeal(self, ct: Controller, myLoc: Position, myTeam, nearbyUnits):
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
                elif bType in [EntityType.BUILDER_BOT] and ct.get_global_resources() > 28:
                    buildingScore = 8
                elif bType in [EntityType.GUNNER, EntityType.SENTINEL]:
                    buildingScore = 6
                elif bType in [EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SPLITTER] and ct.get_global_resources() > 24:
                    buildingScore = 4
                else:
                    buildingScore = 2
            else:
                continue
            dist = myLoc.distance_squared(bPos)
            cHP = ct.get_hp(b)
            maxHP = ct.get_max_hp(b)
            mHP = maxHP - cHP
            if dist > 0:
                buildingScore = buildingScore * (1 - dist/120) * (mHP/maxHP)
                if buildingScore > healScore:
                    healScore = buildingScore
                    healPos = bPos
        return healScore, healPos

    def scoreRoute(self, ct: Controller, myLoc: Position, myTeam, myId, allyBuilders, nearbyUnits):
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
                if bType in (EntityType.HARVESTER, EntityType.CONVEYOR) and not self.isClosestAllyTo(allyBuilders, myId, myLoc, bPos):
                    continue # a closer ally already has this harvester/conveyor - dont chase it too
                if bType == EntityType.HARVESTER and myLoc.distance_squared(bPos) < 16: # max score of 5 to prioritize cotninueing paths
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
                        bScore = max(1.6, 5 * max(0, (1 - (workingSpots[0].distance_squared(teamCore) / 100))) * max(0, (1 - myLoc.distance_squared(bPos)/60)))
                        bDir = Direction.CENTRE
                        endTile = workingSpots[0]
                elif bType == EntityType.CONVEYOR:
                    if ct.get_team(b) == myTeam:
                        bDir = ct.get_direction(b)
                        endTile = bPos.add(bDir)
                        if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile):
                            eId = ct.get_tile_building_id(endTile)
                            if eId is None:
                                bScore = max(2, 6 * max(0, (1 - (endTile.distance_squared(teamCore) / 120))) * max(0, (1 - myLoc.distance_squared(bPos)/40)))
                if bScore > routeScore:
                    routeScore = bScore
                    routePos = endTile
                    routeDir = bDir
        return routeScore, routePos, routeDir

    def scoreHarvest(self, ct: Controller, myLoc: Position, myTeam, myId, allyBuilders):
        # harvest, max score of 3
        harvestScore = 0
        harvestPos = None
        teamCore = self.mapPf.teamCore
        if teamCore is not None:
            enemyThreatened = self.mapPf.enemyTurretThreatenedTiles(ct)
            for tile in ct.get_nearby_tiles():
                if self.mapPf.getTileEnv(tile) == 1: # since it checks all nearby tiles before choosing state, this is fine
                    if ct.get_tile_building_id(tile) is None:
                        if not self.isClosestAllyTo(allyBuilders, myId, myLoc, tile):
                            continue # a closer ally already has this ore tile
                        if (tile.x, tile.y) in enemyThreatened:
                            continue # dont place a harvester somewhere an enemy turret can hit it
                        dist = teamCore.distance_squared(tile)
                        tileScore = max(1.2, 3 * (1 - dist/160) * (1 - myLoc.distance_squared(tile)/120))
                        if tileScore > harvestScore and ct.get_global_resources() > dist / 7:
                            harvestPos = tile
                            harvestScore = tileScore
        return harvestScore, harvestPos

    def scoreExplore(self, ct: Controller, myLoc: Position):
        # explore, max score of 1
        exploreScore = 0
        if ct.get_current_round() < 12:
            explorePos = self.initTarget
            exploreScore = 1
        else:
            if self.mapPf.enemyCorePos is not None and self.mapPf.myNum < 3:
                explorePos = self.mapPf.enemyCorePos
                exploreScore = 5
            elif self.mapPf.myNum < 3:
                explorePos = Position(self.mapW // 2, self.mapH // 2)
                exploreScore = 7
            explorePos = self.mapPf.returnUnvisited(ct, myLoc)
            if explorePos is not None:
                exploreScore = 1
            else:
                exploreScore = 0.4 # exploring isnt as important then
        return exploreScore, explorePos

    def rayBlockedByTeam(self, ct: Controller, gunnerSpot: Position, attackPos: Position, d: Direction, myTeam) -> bool:
        """True if a TEAM-owned building sits strictly between gunnerSpot and
        attackPos along facing d. Builder bots (either team) and enemy
        buildings are deliberately ignored: builder bots are transient, and an
        enemy building in the way just becomes the gunner's real target
        instead of attackPos, which is fine - only a permanent team building
        forever wastes the shot. dist < 10 and != 5 (checked by the caller)
        guarantees this is a true straight cardinal/diagonal line, so walking
        step by step in d reaches attackPos exactly."""
        dx, dy = d.delta()
        x, y = gunnerSpot.x + dx, gunnerSpot.y + dy
        for _ in range(max(self.mapW, self.mapH)): # bound the walk, just in case
            if (x, y) == (attackPos.x, attackPos.y):
                return False
            if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                return False # left the map before reaching the target - shouldn't happen
            if self.mapPf.getTileEnv(Position(x, y)) == 2: # wall
                return True
            bId = ct.get_tile_building_id(Position(x, y))
            if bId is not None and ct.get_team(bId) == myTeam:
                return True
            x += dx
            y += dy
        return False

    def attack(self, ct: Controller, attackPos: Position):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        mapW = self.mapW
        mapH = self.mapH
        for d in CARDINALS:
            gunnerSpot = myLoc.add(d)
            dist = attackPos.distance_squared(gunnerSpot)
            if dist < 10 and dist != 5 and 0 <= gunnerSpot.x < mapW and 0 <= gunnerSpot.y < mapH:
                spotId = ct.get_tile_building_id(gunnerSpot)
                if spotId is None:
                    gunnerDir = gunnerSpot.direction_to(attackPos)
                    if self.rayBlockedByTeam(ct, gunnerSpot, attackPos, gunnerDir, myTeam):
                        continue # a team building sits between here and the target - try another spot
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)
                        return # only stop once we've actually built a gunner with a clear line
        for d in CARDINALS: # try destorying after you exhaust all possible build opportunities
            gunnerSpot = myLoc.add(d)
            dist = attackPos.distance_squared(gunnerSpot)
            if dist < 10 and dist != 5 and 0 <= gunnerSpot.x < mapW and 0 <= gunnerSpot.y < mapH:
                spotId = ct.get_tile_building_id(gunnerSpot)
                if spotId is not None:            
                    spotTeam = ct.get_team(spotId)
                    spotType = ct.get_entity_type(spotId)
                    if spotTeam == myTeam and spotType == EntityType.BARRIER:
                        if ct.can_destroy(gunnerSpot):
                            ct.destroy(gunnerSpot)
                            return
        self.mapPf.moveTo(ct, attackPos)

    def heal(self, ct: Controller, healPos: Position):

        myLoc = ct.get_position()
        if ct.can_heal(healPos):
            ct.heal(healPos)
        else:

            if myLoc.distance_squared(healPos) > 1:
                self.mapPf.moveTo(ct, healPos)
            elif myLoc.distance_squared(healPos) < 1:
                self.mapPf.moveTo(ct, self.mapPf.teamCore)

    def route(self, ct: Controller, routePos: Position, routeDir: Direction):
        self.mapPf.routeConveyor(ct, routePos)

    def harvest(self, ct: Controller, harvestPos: Position):
        myLoc = ct.get_position()
        if ct.can_build_harvester(harvestPos):
            ct.build_harvester(harvestPos)
        if harvestPos.distance_squared(myLoc) > 1:
            self.mapPf.moveTo(ct, harvestPos)
        elif harvestPos.distance_squared(myLoc) < 1:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
        if ct.can_build_harvester(harvestPos):
            ct.build_harvester(harvestPos)

    def explore(self, ct: Controller, explorePos: Position):
        myLoc = ct.get_position()
        if explorePos is None:
            corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
            explorePos = corners[ct.get_current_round() // 20 % 4]
        self.mapPf.moveTo(ct, explorePos)