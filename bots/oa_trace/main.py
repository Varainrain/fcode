"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

# If the core goes below 400 health, and sees a gunner attacking it, it will immediately send a 'recall' order in the next unused slot, where the other bots will walk back to team core, scored based on their distance to it. Synergizes well with OogwayTestExplore
# and spend up titanium to get to 50 ammo, stopping when it has 20 titanium left

from fcode import Controller, Direction, EntityType, Environment, Position

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
ROUTE_STALL_ROUNDS = 24
ROUTE_COMMIT_MAX_LINKS = 4

from mapPathfinding import *

# slot 0 numSpawned, slot 1-6 map sharing, slot 7 teamCore loc (for gunners), slot 8 symmetry (mapPathfinding)

# debug state colors (r, g, b) - one per bot state so the visualiser shows intent
C_SEARCH_CORE  = (80, 120, 255) # Blue | attack: enemy core unknown, hunting for it
C_MARCH_ATTACK = (255, 160, 60) # Orange | attack: marching to known enemy core
C_TURRET_SPOT  = (255, 60, 255) # Pink | attack: moving to/build at turret placement spot
C_HEAL_GUNNER  = (60, 255, 120) # Mint | attack: repairing team gunners
C_FIGHT_TURRET = (255, 60, 60)  # Red | eco: responding to uncovered enemy turret
C_HEAL_CORE    = (60, 255, 60)  # Green | eco: healing the core
C_HEAL_BUILD   = (60, 255, 200) # Cyan | eco: healing a damaged building
C_ROUTE_CONV   = (60, 200, 255) # Sky Blue | eco: routing a conveyor
C_ROUTE_HARV   = (255, 60, 255) # Pink | eco: routing a harvester
C_HARVEST      = (255, 220, 60) # Yellow | eco: building a harvester on ore
C_IDLE         = (200, 200, 200) # Gray | eco: nothing to do, heading home


def _prof(name):
    def deco(fn):
        def wrapper(self, ct, *a, **k):
            import time
            t = time.monotonic()
            r = fn(self, ct, *a, **k)
            self.mapPf._acc(name, time.monotonic() - t)
            return r
        return wrapper
    return deco

def coreFootprintManhattan(pos: Position, core: Position) -> int:
    return min(
        abs(pos.x - (core.x + dx)) + abs(pos.y - (core.y + dy))
        for dx in (0, 1) for dy in (0, 1)
    )

class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.mapW = None
        self.mapH = None
        self.defendHome = None
        self.visitedCenter = False
        self.trace = {}

    def _t(self, key):
        self.trace[key] = self.trace.get(key, 0) + 1

    def _flush(self, ct: Controller):
        if ct.get_current_round() % 100 or not self.trace:
            return
        try:
            with open("/tmp/oa_trace.csv", "a") as fh:
                fh.write("%d,%d,%s\n" % (
                    ct.get_current_round(), ct.get_id(),
                    ";".join("%s=%d" % kv for kv in sorted(self.trace.items()))))
        except Exception:
            pass

    def distToCore(self, ct: Controller, pos: Position):
        myLoc = ct.get_position()
        tL = myLoc
        tR = myLoc.add(Direction.EAST)
        bL = myLoc.add(Direction.SOUTH)
        bR = myLoc.add(Direction.SOUTH).add(Direction.EAST)
        coreCorners = [tL, tR, bR, bL]
        coreCorners.sort(key=lambda coreCorner: coreCorner.distance_squared(pos))
        return coreCorners[0].distance_squared(pos)

    def drawState(self, ct: Controller, color, target: Position = None, dot: bool = True):
        myLoc = ct.get_position()
        if target is not None:
            ct.draw_indicator_line(myLoc, target, *color)
        if dot:
            ct.draw_indicator_dot(myLoc, *color)

    def runCore(self, ct: Controller) -> None:
        myLoc = ct.get_position()

        nearbyOres = []
        for tile in ct.get_nearby_tiles():
            if ct.get_tile_env(tile) == Environment.ORE_TITANIUM:
                nearbyOres.append(tile)
        nearbyOres.sort(key=lambda ore: self.distToCore(ct, ore))

        globalAmmo = ct.get_global_ammo()
        globalTitanium = ct.get_global_resources()

        if self.numSpawned < 5 or globalTitanium > 360:
            spawnableTiles = []
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    spawnableTiles.append(tile)
            if spawnableTiles:
                mapCenter = Position(self.mapW // 2, self.mapH // 2)
                nextNum = self.numSpawned + 1
                if nextNum % 3 == 1 and nextNum not in (5, 7): # attacking bots
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(mapCenter))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
                else: # eco/defense bot
                    sortTarget = nearbyOres[0] if nearbyOres else mapCenter
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(sortTarget))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
            ct.write_store(0, self.numSpawned) # used so bots know their roles
        ct.write_store(7, myLoc.x * 32 + myLoc.y)
        convertAmount = min(16 - globalAmmo, globalTitanium - 28)
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)
        
    def run(self, ct: Controller) -> None:
        if self.mapW is None:
            self.mapH = ct.get_map_height()
            self.mapW = ct.get_map_width()

        etype = ct.get_entity_type()
        if etype == EntityType.BUILDER_BOT:
            self._flush(ct)
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
        elif etype == EntityType.GUNNER:
            self.runGunner(ct)

    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.mapPf.setupMap(ct)
        self.setupDefendClamp(ct)
        if self.mapPf.myNum % 3 == 1 and self.mapPf.myNum not in (5, 7): # attacking
            # pathfind to enemy core. if it isnt known pathfind to center of map.
            # once the enemy core is known, calculate all possible tiles that are empty and you can place a gunner on such that it would attack the enemy core
            # score them by their distance, and the number of enemy gunners attacking those tiles (if it has more than 1, dont count it)
            # pathfind to the one with the highest score, and place a gunner there
            # if there are no such spots, the create a gunner to target enemy gunners, scoring based on distance to enemy core, and the best valid spots. 
            # valid spots are scored based on their proximity to the builder bot, as number of enemy gunners attacking them (also limited to one.)
            # continue, until your titanium drops below 80
            self.runAttack(ct)
        else: # economy / defending - both build the same way
            # go around the map, routing conveyors back to the core.
            # routing/harvesting is priority number 2, first priority, is if you ever see and enemy gunner, either attack it or heal it based on if that gunner is being attacked or not.
            self.runEco(ct)

    def setupDefendClamp(self, ct: Controller):
        if self.mapPf.myNum != 5 and self.mapPf.myNum != 7:
            self.mapPf.clearMoveZone()
            return
        home = self.getDefendHome(ct)
        if home is None:
            self.mapPf.clearMoveZone()
            return
        self.mapPf.setMoveZone(home, self.farCoreCorner())

    def farCoreCorner(self) -> Position:
        core = self.mapPf.teamCore
        center = Position(self.mapW // 2, self.mapH // 2)
        corners = [core, core.add(Direction.EAST), core.add(Direction.SOUTH),
                   core.add(Direction.SOUTH).add(Direction.EAST)]
        return max(corners, key=lambda corner: corner.distance_squared(center))

    def visibleDefendBots(self, ct: Controller) -> list:
        if self.mapPf.myNum in [5, 7]:
            return []
        farCorner = self.farCoreCorner()
        myLoc = ct.get_position()
        myDist = myLoc.distance_squared(farCorner)
        defendBots = []
        for u in ct.get_nearby_units():
            if ct.get_entity_type(u) != EntityType.BUILDER_BOT or ct.get_team(u) != ct.get_team():
                continue
            uPos = ct.get_position(u)
            if uPos.distance_squared(farCorner) <= 20 and uPos.distance_squared(farCorner) < myDist:
                defendBots.append(uPos)
        return defendBots

    @_prof('attack')
    def runAttack(self, ct: Controller):
        myLoc = ct.get_position()
        if self.mapPf.enemyCorePos is None:
            mapCenter = Position(self.mapW // 2, self.mapH // 2)
            if not self.visitedCenter:
                if ct.get_current_round() > 20 or myLoc.distance_squared(mapCenter) < 12:
                    self.visitedCenter = True
                else:
                    self.drawState(ct, C_SEARCH_CORE, mapCenter)
                    self.mapPf.moveTo(ct, mapCenter)
                    return
            candidates = list(self.mapPf.allEnemyCore.values())
            if candidates:
                target = candidates[(self.mapPf.myNum // 2) % len(candidates)]
            else:
                corners = [Position(1, 1), Position(self.mapW - 2, 1),
                           Position(1, self.mapH - 2), Position(self.mapW - 2, self.mapH - 2)]
                target = corners[(self.mapPf.myNum // 2) % len(corners)]
            self.drawState(ct, C_SEARCH_CORE, target)
            self.mapPf.moveTo(ct, target)
            return
        else:
            ti = ct.get_global_resources()
            gunCost = ct.get_gunner_cost()
            self._t('attack_turns')
            if gunCost + 28 <= ti < 96:
                self._t('A2_affordable_but_gated')   # seat we could pay for, gate said no
            if ti >= 96 and ti < gunCost:
                self._t('A2_gated_open_but_broke')   # gate said yes, cost says no
            if ct.get_global_ammo() < 4:
                self._t('ammo_dry')                  # no gunner anywhere can fire

            if ct.get_global_resources() < 96:
                if ct.get_global_resources() >= 30 and self.attackHarvesterWithGunner(ct):
                    return
                self.drawState(ct, C_MARCH_ATTACK, self.mapPf.enemyCorePos)
                self.mapPf.moveTo(ct, self.mapPf.enemyCorePos)
                return

            if ct.get_global_resources() >= 96:
                gunnerStuff = self.findGunnerSpot(ct)
                if gunnerStuff:
                    gunnerSpot, gunnerDir = gunnerStuff
                    self.drawState(ct, C_TURRET_SPOT, gunnerSpot)
                    bbId = ct.get_tile_builder_bot_id(gunnerSpot)
                    if bbId is not None and bbId != ct.get_id():
                        self._t('A3_seat_occupied_by_ally')
                    dNow = myLoc.distance_squared(gunnerSpot)
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)
                        self._t('seated')
                        self._t('A1_move_after_build')  # falls through to a moveTo below
                    elif dNow == 1:
                        self._t('adj_cant_build')       # standing next to the seat, no-op turn
                        if ti < gunCost:
                            self._t('adj_cant_build_broke')
                    elif dNow < 1:
                        self._t('standing_on_seat')

                    myDist = myLoc.distance_squared(gunnerSpot)
                    if myDist < 1:
                        self._t('A1_second_path_from_seat')
                        self.mapPf.moveTo(ct, self.mapPf.teamCore)
                    elif myDist > 1:
                        self._t('A1_double_moveTo')     # walk to seat THEN march again
                        self.mapPf.moveTo(ct, gunnerSpot)
                    else:
                        return

            if self.healTeamGunners(ct):
                return
            self.drawState(ct, C_MARCH_ATTACK, self.mapPf.enemyCorePos)
            self.mapPf.moveTo(ct, self.mapPf.enemyCorePos)

    @_prof('harvGun')
    def attackHarvesterWithGunner(self, ct: Controller) -> bool:
        myLoc = ct.get_position()
        harvester = None
        harvesterDist = None
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) != EntityType.HARVESTER or ct.get_team(b) == ct.get_team():
                continue
            bPos = ct.get_position(b)
            d = myLoc.distance_squared(bPos)
            if harvesterDist is None or d < harvesterDist:
                harvesterDist = d
                harvester = bPos
        if harvester is None:
            return False
        enemyCoverage = self.enemyTurretCoverage(ct)
        enemyCore = self.mapPf.enemyCorePos
        best = None
        bestScore = None
        for spotPos, spotDir in self.mapPf.gunnerSpots(harvester, self.mapW, self.mapH, True):
            if not ct.is_in_vision(spotPos):
                continue
            if ct.get_tile_building_id(spotPos) is not None:
                continue
            if ct.get_tile_env(spotPos) != Environment.EMPTY:
                continue
            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
            if seatCov > 1:
                continue
            score = (seatCov, -spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))
            if bestScore is None or score < bestScore:
                bestScore = score
                best = (spotPos, spotDir)
        if best is None:
            return False
        spotPos, spotDir = best
        self.drawState(ct, C_TURRET_SPOT, spotPos)
        if ct.can_build_gunner(spotPos, spotDir):
            ct.build_gunner(spotPos, spotDir)
        myDist = myLoc.distance_squared(spotPos)
        if myDist < 1:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
        elif myDist > 1:
            self.mapPf.moveTo(ct, spotPos)
        return True

    def findGunnerSpot(self, ct):
        enemyCoverage = self.enemyTurretCoverage(ct)
        coreAttackers = self.getAttackableTiles(ct)
        bestAttacker = None
        bestScore = None
        myLoc = ct.get_position()
        enemyCore = self.mapPf.enemyCorePos
        for spotPos, spotDir in coreAttackers:
            if not ct.is_in_vision(spotPos):
                continue
            if ct.get_tile_building_id(spotPos) is not None:
                continue
            if ct.get_tile_env(spotPos) != Environment.EMPTY:
                continue
            seatCov = enemyCoverage.get((spotPos.x, spotPos.y), 0)
            if seatCov > 1:
                continue
            score = (seatCov, myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))
            if bestScore is None or score < bestScore:
                bestScore = score
                bestAttacker = (spotPos, spotDir)
        return bestAttacker

    def getAttackableTiles(self, ct):
        enemyCore = self.mapPf.enemyCorePos
        coreCorners = [
            enemyCore, enemyCore.add(Direction.EAST), enemyCore.add(Direction.SOUTH),
            enemyCore.add(Direction.SOUTH).add(Direction.EAST)]
        coreAttackers = set()
        for corner in coreCorners:
            for spot in self.mapPf.gunnerSpots(corner, self.mapW, self.mapH, True):
                coreAttackers.add((spot[0], spot[1]))
        return coreAttackers

    @_prof('tCov')
    def enemyTurretCoverage(self, ct: Controller) -> dict:
        enemyCoverage = {}
        myTeam = ct.get_team()
        for b in ct.get_nearby_buildings():
            bType = ct.get_entity_type(b)
            if ct.get_team(b) == myTeam or bType not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            bPos = ct.get_position(b)
            curDir = ct.get_direction(b)
            facings = DIRECTIONS if bType == EntityType.GUNNER else [curDir]
            for d in facings:
                weight = 1.0 if d == curDir else 0.5
                dx, dy = d.delta()
                maxK = 3 if d in CARDINALS else 2
                x, y = bPos.x, bPos.y
                for _ in range(maxK):
                    x += dx
                    y += dy
                    if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                        break
                    enemyCoverage[(x, y)] = enemyCoverage.get((x, y), 0) + weight
                    tilePos = Position(x, y)
                    if not ct.is_in_vision(tilePos):
                        break
                    if ct.get_tile_env(tilePos) == Environment.WALL:
                        break
                    if ct.get_tile_building_id(tilePos) is not None:
                        break
                    if ct.get_tile_builder_bot_id(tilePos) is not None:
                        break
        return enemyCoverage

    def coreThreatSpots(self, ct: Controller):
        compact = ct.read_store(7)
        teamCore = Position(compact // 32, compact % 32)
        corners = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
                   teamCore.add(Direction.SOUTH).add(Direction.EAST)]
        spots = set()
        for corner in corners:
            for spotPos, spotDir in self.mapPf.gunnerSpots(corner, self.mapW, self.mapH, blocked=False):
                spots.add((spotPos.x, spotPos.y, spotDir))
        return spots

    @_prof('gunner')
    def runGunner(self, ct: Controller):
        curTarget = ct.get_gunner_target()
        myDir = ct.get_direction()
        myPos = ct.get_position()
        myTeam = ct.get_team()
        if curTarget is not None:
            targetId = ct.get_tile_building_id(curTarget)
            bbId = ct.get_tile_builder_bot_id(curTarget)
            if bbId is not None and ct.get_team(bbId) == myTeam:
                return # dont kill your own bot
            enemyBuilding = targetId is not None and ct.get_team(targetId) != myTeam
            enemyBuilder = bbId is not None and ct.get_team(bbId) != myTeam
            if enemyBuilding or enemyBuilder:
                if ct.can_fire(curTarget):
                    ct.fire(curTarget)
                    return
        if curTarget is not None:
            targetId = ct.get_tile_building_id(curTarget)
            if targetId is not None and ct.get_team(targetId) == myTeam and ct.get_entity_type(targetId) == EntityType.CONVEYOR:
                sawTeamConv = False
                for tile in ct.get_attackable_tiles_from(myPos, myDir, EntityType.GUNNER):
                    tileId = ct.get_tile_building_id(tile)
                    if tileId is None:
                        continue
                    if ct.get_team(tileId) == myTeam and ct.get_entity_type(tileId) == EntityType.CONVEYOR:
                        sawTeamConv = True
                        continue
                    if sawTeamConv and ct.get_team(tileId) != myTeam and ct.get_entity_type(tileId) == EntityType.GUNNER:
                        if self.gunnerAttacksCore(ct, tile, tileId):
                            if ct.can_fire(curTarget):
                                ct.fire(curTarget)
                            return
                    break
        threatSpots = self.coreThreatSpots(ct)
        directionScores = []
        bestDir = myDir
        bestIsCoreDefense = False
        for directionIndex, d in enumerate(DIRECTIONS):
            coreHits = 0
            coreThreatHits = 0
            gunnerHits = 0
            otherHits = 0
            for tile in ct.get_attackable_tiles_from(myPos, d, EntityType.GUNNER):
                tileId = ct.get_tile_building_id(tile)
                if tileId is not None and ct.get_team(tileId) != myTeam:
                    tType = ct.get_entity_type(tileId)
                    if tType == EntityType.CORE:
                        coreHits += 1
                    elif tType in [EntityType.GUNNER, EntityType.SENTINEL]:
                        gunnerHits += 1
                        if tType == EntityType.GUNNER and (tile.x, tile.y, ct.get_direction(tileId)) in threatSpots:
                            coreThreatHits += 1
                    else:
                        otherHits += 1
            # Keep core pressure first, then preserve guns that are actively
            # stopping a core shot. Prefer the current facing on exact ties so
            # equivalent targets do not burn 10 Ti rotating back and forth.
            score = (coreHits, coreThreatHits, gunnerHits, otherHits)
            directionScores.append((
                score,
                1 if d == myDir else 0,
                -directionIndex,
                d,
                coreThreatHits > 0,
            ))
        if directionScores:
            _, _, _, bestDir, bestIsCoreDefense = max(directionScores)
        if bestDir != myDir:
            floor = 20 if bestIsCoreDefense else 80
            if ct.get_global_resources() > floor and ct.can_rotate(bestDir):
                ct.rotate(bestDir)

    def gunnerAttacksCore(self, ct: Controller, gunnerTile: Position, gunnerId: int) -> bool:
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return False
        coreTiles = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH),
                     teamCore.add(Direction.SOUTH).add(Direction.EAST)]
        for attackTile in ct.get_attackable_tiles_from(gunnerTile, ct.get_direction(gunnerId), EntityType.GUNNER):
            if attackTile in coreTiles:
                return True
        return False

    def getDefendHome(self, ct: Controller):
        if self.defendHome is not None:
            return self.defendHome
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return None
        center = Position(self.mapW // 2, self.mapH // 2)
        covered = self.coveredTiles(ct)
        candidates = []
        fallback = []
        for dx in range(-1, 3):
            for dy in range(-1, 3):
                if 0 <= dx <= 1 and 0 <= dy <= 1: # skip the 2x2 core itself
                    continue
                tile = Position(teamCore.x + dx, teamCore.y + dy)
                if not (0 <= tile.x < self.mapW and 0 <= tile.y < self.mapH):
                    continue
                if self.mapPf.getTileEnv(tile) > 1: # wall or unpassable
                    continue
                if not ct.is_in_vision(tile):
                    continue
                if ct.get_tile_building_id(tile) is not None:
                    continue
                fallback.append(tile)
                if (tile.x, tile.y) not in covered: # never block a team gunner line
                    candidates.append(tile)
        if self.mapPf.myNum == 5:
            candidates.sort(key=lambda tile: tile.distance_squared(center)) # 5th bot: closest to center
            fallback.sort(key=lambda tile: tile.distance_squared(center))
        else:
            candidates.sort(key=lambda tile: tile.distance_squared(center), reverse=True) # 7th bot: farthest
            fallback.sort(key=lambda tile: tile.distance_squared(center), reverse=True)
        if candidates:
            self.defendHome = candidates[0]
        elif fallback:
            self.defendHome = fallback[0]
        return self.defendHome

    @_prof('healCore')
    def healCore(self, ct: Controller, home):
        myLoc = ct.get_position()
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return
        coreTiles = [teamCore, teamCore.add(Direction.EAST),
                     teamCore.add(Direction.SOUTH),
                     teamCore.add(Direction.SOUTH).add(Direction.EAST)]
        for tile in coreTiles:
            if myLoc.distance_squared(tile) == 1 and ct.can_heal(tile):
                ct.heal(tile)
                return
        if home is not None and myLoc != home:
            self.mapPf.moveTo(ct, home)

    @_prof('buildGun')
    def buildGunnerFor(self, ct: Controller, target: Position) -> bool:
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        for d in CARDINALS:
            spot = myLoc.add(d)
            dist = target.distance_squared(spot)
            if dist < 10 and dist != 5 and 0 <= spot.x < self.mapW and 0 <= spot.y < self.mapH:
                if ct.get_tile_building_id(spot) is None:
                    gunnerDir = spot.direction_to(target)
                    if not self.rayBlockedByTeam(ct, spot, target, gunnerDir, myTeam):
                        if ct.can_build_gunner(spot, gunnerDir):
                            ct.build_gunner(spot, gunnerDir)
                            return True
        return False
        # we dont even build barriers so no need lmao

    @_prof('healBuild')
    def healDamagedNonCore(self, ct: Controller) -> bool:
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        bestPos = None
        bestId = None
        bestDist = None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR, EntityType.HARVESTER):
                if ct.get_hp(b) < (ct.get_max_hp(b)):
                    bPos = ct.get_position(b)
                    dist = myLoc.distance_squared(bPos)
                    if bestDist is None or dist < bestDist:
                        bestDist = dist
                        bestPos = bPos
                        bestId = b
        if bestPos is None:
            return False
        self.drawState(ct, C_HEAL_BUILD, bestPos)
        if myLoc.distance_squared(bestPos) > 1:
            self.mapPf.moveTo(ct, bestPos)
        elif myLoc.distance_squared(bestPos) < 1:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
        if ct.can_heal(bestPos) and ct.get_hp(bestId) < (ct.get_max_hp(bestId) - 2):
            ct.heal(bestPos)   
        return True

    @_prof('healGun')
    def healTeamGunners(self, ct: Controller) -> bool:
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        best = None
        bestKey = None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            if ct.get_hp(b) >= ct.get_max_hp(b):
                continue
            bPos = ct.get_position(b)
            missing = ct.get_max_hp(b) - ct.get_hp(b)
            key = (-missing, myLoc.distance_squared(bPos))
            if bestKey is None or key < bestKey:
                bestKey = key
                best = bPos
        if best is None:
            return False
        self.drawState(ct, C_HEAL_GUNNER, best)
        if myLoc.distance_squared(best) == 1 and ct.can_heal(best):
            ct.heal(best)
            return True
        self.mapPf.moveTo(ct, best)
        return True

    @_prof('cov')
    def coveredTiles(self, ct: Controller) -> set:
        covered = set()
        myTeam = ct.get_team()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType in (EntityType.GUNNER, EntityType.SENTINEL):
                bPos = ct.get_position(b)
                bDir = ct.get_direction(b)
                for t in ct.get_attackable_tiles_from(bPos, bDir, bType):
                    covered.add((t.x, t.y))
        return covered

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

    @_prof('eco')
    def runEco(self, ct: Controller):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        covered = self.coveredTiles(ct)
        enemyTurrets = []
        visibleDamagedCore = False

        for b in ct.get_nearby_buildings():
            bTeam = ct.get_team(b)
            bType = ct.get_entity_type(b)
            if bTeam == myTeam and bType == EntityType.CORE:
                visibleDamagedCore = ct.get_hp(b) < ct.get_max_hp(b)
            elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
                enemyTurrets.append(ct.get_position(b))
        uncoveredTurrets = [g for g in enemyTurrets if (g.x, g.y) not in covered]

        if uncoveredTurrets and ct.get_global_resources() >= ct.get_gunner_cost(): # only respond if we can afford a gunner
            uncoveredTurrets.sort(key=lambda g: g.distance_squared(myLoc))
            target = uncoveredTurrets[0]
            self.drawState(ct, C_FIGHT_TURRET, target)

            if self.buildGunnerFor(ct, target): # try to place gunner there
                return
            
            if ct.can_fire(target):
                ct.fire(target)
                return
            
            self.mapPf.moveTo(ct, target) # if you can move towards the gunner
            

        if visibleDamagedCore:
            # if the core isnt at max health, try to heal it
            self.drawState(ct, C_HEAL_CORE, self.mapPf.teamCore)
            self.healCore(ct, self.mapPf.teamCore)
            return

        if self.healDamagedNonCore(ct): # if some other building isnt at max health, try to save it
            return

        if self.routeConveyorTask(ct, myLoc, myTeam): # try routing a conveyor back to the core
            return

        if self.routeHarvesterTask(ct, myLoc, myTeam): # try routing a harvester back to the core
            return

        if self.harvestTask(ct, myLoc, myTeam): # place something on a team harvester
            return
            
        if self.mapPf.teamCore is not None:
            self.drawState(ct, C_IDLE, self.mapPf.teamCore)
            if not ct.is_in_vision(self.mapPf.teamCore):
                self.mapPf.moveTo(ct, self.mapPf.teamCore)

    @_prof('rcTask')
    def routeConveyorTask(self, ct: Controller, myLoc, myTeam) -> bool:
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)

        bestScore, bestEnd = -1, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.CONVEYOR:
                continue
            bPos = ct.get_position(b)
            endTile = bPos.add(ct.get_direction(b))
            if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and self.mapPf.inMoveZone(endTile):
                if endTile.distance_squared(farCorner) <= 20 and any(endTile.distance_squared(dPos) <= 10 for dPos in defendBots):
                    continue
                if self.mapPf.checkPassable(ct, endTile):
                    endId = ct.get_tile_building_id(endTile) 
                    if endId is not None:
                        endType = ct.get_entity_type(endId)
                        endTeam = ct.get_team(endId)
                        if endType not in [EntityType.GUNNER, EntityType.BUILDER_BOT, EntityType.BARRIER] or endTeam != myTeam:
                            continue

                    bScore = max(0, (1 - endTile.distance_squared(teamCore) / 120))  *  (1 - myLoc.distance_squared(bPos) / 40)
                    if bScore > bestScore:
                        bestScore = bScore
                        bestEnd = endTile
                        
        if bestEnd is not None:
            self.drawState(ct, C_ROUTE_CONV, bestEnd)
            self.mapPf.routeConveyor(ct, bestEnd)
            return True
        return False

    @_prof('rhTask')
    def routeHarvesterTask(self, ct: Controller, myLoc, myTeam) -> bool:
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)
        bestScore, bestEnd = -1, None
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) != EntityType.HARVESTER or ct.get_team(b) != myTeam:
                continue
            bPos = ct.get_position(b)
            if myLoc.distance_squared(bPos) > 10:
                continue
            noTeamConv = True
            workingSpots = []
            for possibleDir in CARDINALS:
                endTile = bPos.add(possibleDir)
                if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile)and self.mapPf.inMoveZone(endTile):
                    if endTile.distance_squared(farCorner) <= 20 and any(endTile.distance_squared(dPos) <= 10 for dPos in defendBots):
                        continue
                    eId = ct.get_tile_building_id(endTile)
                    if ct.is_tile_passable(endTile) and eId is None and ct.get_tile_env(endTile) == Environment.EMPTY:
                        workingSpots.append(endTile)
                    elif ct.get_team(eId) == myTeam and ct.get_entity_type(eId) == EntityType.CONVEYOR:
                        noTeamConv = False
            if noTeamConv and len(workingSpots) > 0:
                workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                bScore = max(0, 1 - (workingSpots[0].distance_squared(teamCore) / 220)) * max(0, 1 - (myLoc.distance_squared(bPos) / 60))
                if bScore > bestScore:
                    bestScore = bScore
                    bestEnd = workingSpots[0]
        if bestEnd is not None:
            self.drawState(ct, C_ROUTE_HARV, bestEnd)
            self.mapPf.routeConveyor(ct, bestEnd)
            return True
        return False

    @_prof('harvest')
    def harvestTask(self, ct: Controller, myLoc, myTeam) -> bool:
        teamCore = self.mapPf.teamCore
        enemyThreatened = self.mapPf.enemyTurretThreatenedTiles(ct)
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)

        bestScore, bestTile = -1, None

        for x in range(self.mapW):
            for y in range(self.mapH):
                if self.mapPf.fullMap[x][y] == 1:
                    tile = Position(x, y)
                    if ct.is_in_vision(tile) and ct.get_tile_building_id(tile) is not None:
                        continue
                    if tile.distance_squared(farCorner) <= 20 and any(tile.distance_squared(dPos) <= 10 for dPos in defendBots):
                        continue
                    if self.mapPf.inMoveZone(tile) and (x, y) not in enemyThreatened:
                        dist = teamCore.distance_squared(tile)
                        tileScore = max(0, (160 - dist)) * max(0, (220 - myLoc.distance_squared(tile)))
                        if tileScore > bestScore and ct.get_global_resources() > dist / 7:
                            bestScore = tileScore
                            bestTile = tile

        if bestTile is not None:
            self.drawState(ct, C_HARVEST, bestTile)
            if bestTile.distance_squared(myLoc) > 1:
                self.mapPf.moveTo(ct, bestTile)
            if bestTile.distance_squared(myLoc) < 1:
                self.mapPf.moveTo(ct, teamCore)
            if ct.can_build_harvester(bestTile):
                ct.build_harvester(bestTile)
            return True
        return False
