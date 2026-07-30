"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

# REACTIVE LANE BARRIER — the Ijti absorb pattern (15-game autopsy: they
# take the FIRST core hit at t35-55 vs lastpopperian_ and win at t218-285
# anyway; barriers in the firing lanes are the visible mechanism, 2-12 per
# game, and nobody else on the ladder builds barriers at all).
# Math: barrier = 3 Ti / 30 hp, a gunner shot = 10 -> one barrier eats 3
# shots. Strictly REACTIVE: nothing is built until an enemy turret actually
# aims at our core, so the mirror cost is zero by construction.
AEGIS_SLOT = 9      # free store slot: one claimant at a time (stampede
                    # gate — every-builder-responds collapsed 26%/18%)
AEGIS_RANGE = 12    # only builders this close to home take the job

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
# slot 0 numSpawned, slot 1-6 map sharing, slot 7 initial target

class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.initSpawn = initialSpawn()
        self.numSpawned = 0
        self.fiveDirections = None
        self.initTarget = None
        self.turnsAlive = 0
        self._aegisStuck = 0      # turns the aegis walk made no progress
        self.attackBan = 0
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

        if globalTitanium > 80 + 60 * self.numSpawned:
            for i in ct.get_nearby_tiles():
                if ct.can_spawn(i):
                    ct.spawn_builder(i)
                    corners = [Position(0, 0), Position(self.mapW - 1, 0), Position(0, self.mapH - 1), Position(self.mapW - 1, self.mapH - 1)]
                    corners.sort(key=lambda corner: corner.distance_squared(ct.get_position()))
                    ct.write_store(7, corners[0].x * 32 + corners[0].y)
                    break
        if globalAmmo < 20 and globalTitanium > 100:
            if ct.can_convert_ammo(20 - globalAmmo):
                ct.convert_ammo(20 - globalAmmo)
        
    def run(self, ct: Controller) -> None:
        # dev26+: an uncaught exception PERMANENTLY destroys this unit (a
        # CPU timeout only skips the turn) — one bad tile query must never
        # cost a unit. OogwayNEW shipped without this armor.
        try:
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
        except Exception:
            pass
    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.numSpawned = ct.read_store(0)
        self.mapPf.setupMap(ct)
        if self.initTarget is None: # set initial target for the first explore
            compact = ct.read_store(7)
            self.initTarget = Position(compact // 32, compact % 32)
        self.turnsAlive += 1
        if self.aegis(ct, myLoc):
            return
        self.runBestState(ct, myLoc)
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
        if ct.get_global_resources() > 60:
            bestScore = 0
            bestDir = myDir # so you only rotate when you need to
            for d in DIRECTIONS:
                curScore = 0
                for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
                    tileId = ct.get_tile_building_id(tile)
                    bbId = ct.get_tile_builder_bot_id(tile) 
                    if tileId is not None and ct.get_team(tileId) != myTeam:
                        tType = ct.get_entity_type(tileId)
                        if tType in [EntityType.GUNNER, EntityType.SENTINEL]:
                            curScore += 10
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
            if bestDir != myDir:
                if ct.can_rotate(bestDir):
                    ct.rotate(bestDir)


    def coveredTiles(self, ct: Controller, myTeam):
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

    def _laneTile(self, ct: Controller, tp, foot):
        """First free tile on the straight 8-dir ray from enemy turret tp
        to a core foot tile — the spot where a barrier eats the shots."""
        for c in foot:
            dx, dy = c[0] - tp[0], c[1] - tp[1]
            if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
                continue                     # not a firing ray
            sx = (dx > 0) - (dx < 0)
            sy = (dy > 0) - (dy < 0)
            x, y = tp[0] + sx, tp[1] + sy
            while (x, y) != c:
                p = Position(x, y)
                try:
                    if (ct.is_in_vision(p)
                            and ct.get_tile_building_id(p) is None
                            and self.mapPf.getTileEnv(p) not in (1, 2, 3)):
                        return p
                except Exception:
                    pass
                x += sx
                y += sy
        return None

    def aegis(self, ct: Controller, myLoc: Position) -> bool:
        """When an enemy turret aims at our core, nearby builders block the
        lane with barriers. Returns True if the turn was used.
        NO claim system and NO dedicated walker — v1 elected one claimant
        and it pathed into our own ring wall and stood two tiles short for
        seven turns while the core died (aegis.log, skerry t58-76). Now:
        every builder within range responds OPPORTUNISTICALLY; a barrier is
        3 Ti so a double-build costs less than a single turn of dithering,
        and once a lane tile is filled _laneTile returns the NEXT free tile
        toward the core — layered armor by construction."""
        tc = self.mapPf.teamCore
        if tc is None:
            return False
        if abs(myLoc.x - tc.x) + abs(myLoc.y - tc.y) > AEGIS_RANGE:
            return False
        if ct.get_global_resources() < 10:
            return False
        foot = [(tc.x + a, tc.y + b) for a in (0, 1) for b in (0, 1)]
        myTeam = ct.get_team()
        lane = None
        for b in ct.get_nearby_entities():
            try:
                if ct.get_team(b) == myTeam:
                    continue
                if ct.get_entity_type(b) not in (EntityType.GUNNER,
                                                 EntityType.SENTINEL):
                    continue
                bp = ct.get_position(b)
                if min(abs(bp.x - c[0]) + abs(bp.y - c[1]) for c in foot) > 6:
                    continue
                lane = self._laneTile(ct, (bp.x, bp.y), foot)
                if lane is not None:
                    break
            except Exception:
                continue
        if lane is None:
            self._aegisStuck = 0
            return False
        d = abs(myLoc.x - lane.x) + abs(myLoc.y - lane.y)
        if d == 1:
            if ct.can_act() and ct.can_build_barrier(lane):
                ct.build_barrier(lane)
                return True
            return True                     # adjacent but on cooldown: hold
        if d == 0:                          # 2.3: cannot build on own tile
            for mv in CARDINALS:
                if ct.can_move(mv):
                    ct.move(mv)
                    return True
            return True
        # walk in — with a greedy fallback, because mapPf.moveTo dead-ends
        # against our own ring conveyors (the exact v1 failure)
        before = (myLoc.x, myLoc.y)
        if self._aegisStuck >= 2:
            best = None
            for mv in CARDINALS:
                n = myLoc.add(mv)
                nd = abs(n.x - lane.x) + abs(n.y - lane.y)
                if ct.can_move(mv) and (best is None or nd < best[0]):
                    best = (nd, mv)
            if best is not None:
                ct.move(best[1])
                self._aegisStuck = 0
                return True
        self.mapPf.moveTo(ct, lane)
        if (myLoc.x, myLoc.y) == before and ct.get_move_cooldown() == 0:
            self._aegisStuck += 1
        return True

    def runBestState(self, ct: Controller, myLoc: Position):
        nearbyUnits = ct.get_nearby_entities() # both builder bots and buildings
        myTeam = ct.get_team()

        # attack, max score of 10
        attackScore = 0
        attackPos = None
        if self.attackBan == 0:
            if ct.get_global_resources() > 120: # dont attack if u r broke
                covered = self.coveredTiles(ct, myTeam)
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
                            buildingScore = 4
                        else:
                            buildingScore = 1
                    else:
                        continue
                    if (bPos.x, bPos.y) in covered:
                        continue
                    dist = myLoc.distance_squared(bPos)
                    buildingScore = buildingScore * (1 - dist/48)
                    if buildingScore > attackScore:
                        attackScore = buildingScore
                        attackPos = bPos # no need to worry about this not being initialized, as it needs buildingScore > attackScore, so there must be a position
                for b in ct.get_nearby_buildings(5):
                    if ct.get_entity_type(b) == EntityType.GUNNER and ct.get_team(b) == myTeam:
                        attackScore = 0
                        self.attackBan = 4 + (ct.get_id() % 8)
                        break
        else:
            self.attackBan -= 1

        # heal, max score of 8
        healScore = 0
        healPos = None
        for b in nearbyUnits: # scored on how low the unit is, distance, and entity type
            bTeam = ct.get_team(b)
            buildingScore = 0
            if bTeam == myTeam:
                bPos = ct.get_position(b)
                bType = ct.get_entity_type(b)
                if bType in [EntityType.CORE, EntityType.BUILDER_BOT]: # dont waste an entire state on just healing yourself
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
            if dist > 0:
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

        # harvest, max score of 3
        harvestScore = 0
        harvestPos = None
        if teamCore is not None:
            for tile in ct.get_nearby_tiles():
                if self.mapPf.getTileEnv(tile) == 1: # since it checks all nearby tiles before choosing state, this is fine
                    if ct.get_tile_building_id(tile) is None: 
                        dist = teamCore.distance_squared(tile)
                        tileScore = max(1.2, 3 * (1 - dist/160) * (1 - myLoc.distance_squared(tile)/120))
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

    def rayBlockedByTeam(self, ct: Controller, gunnerSpot: Position, attackPos: Position, d: Direction, myTeam) -> bool:
        dx, dy = d.delta()
        x, y = gunnerSpot.x + dx, gunnerSpot.y + dy
        for _ in range(max(self.mapW, self.mapH)):
            if (x, y) == (attackPos.x, attackPos.y):
                return False
            if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                return False
            if self.mapPf.getTileEnv(Position(x, y)) == 2:
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
                        continue
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)
                        return
        for d in CARDINALS: # try destorying after you exhaust all possible build opportunities
            gunnerSpot = myLoc.add(d)
            dist = attackPos.distance_squared(gunnerSpot)
            if dist < 10 and dist != 5 and 0 <= gunnerSpot.x < mapW and 0 <= gunnerSpot.y < mapH:
                spotId = ct.get_tile_building_id(gunnerSpot)
                if spotId is not None:            
                    spotTeam = ct.get_team(spotId)
                    spotType = ct.get_entity_type(spotId)
                    if spotTeam == myTeam and spotType in [EntityType.BARRIER]:
                        if ct.can_destroy(gunnerSpot):
                            ct.destroy(gunnerSpot)
                            return
        self.mapPf.moveTo(ct, attackPos)

    def heal(self, ct: Controller, healPos: Position):
        myLoc = ct.get_position()
        if ct.can_heal(healPos):
            ct.heal(healPos)
        else:
            if myLoc.distance_squared(healPos) > 2:
                self.mapPf.moveTo(ct, healPos)
            elif myLoc.distance_squared(healPos) > 1:
                for d in CARDINALS:
                    newLoc = myLoc.add(d)
                    if newLoc.distance_squared(healPos) == 1 and ct.can_move(d):
                        ct.move(d)
            else:
                self.mapPf.moveTo(ct, self.mapPf.teamCore)
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