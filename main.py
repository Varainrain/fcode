"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; the engine calls run() once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

import math
import random

from fcode import Controller, Direction, EntityType, Environment, Position

from coreHelper import findEnemyCore, findTeamCore, findThreats, spawnBots
from defend import Defender
import homedefense
import mapanalysis
import turretplan

CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
DIRECTIONS = CARDINALS
CardDirections = CARDINALS

# 20 ammo = 10 gunner shots or 2 sentinel shots.
GLOBAL_AMMO_BUFFER = 20
REPLACE_CAP = 8       # max lifetime replacement respawns
REPLACE_COOLDOWN = 25  # min rounds between them
MILITARY_FLOOR = 150   # below this ti, harvesters/conveyors win the money, not extra sentinels
# rotate only with enough titanium left for follow-up work.
GUNNER_ROTATE_MIN_TITANIUM = 25

openCost = 1       
barrierCost = 8 # to be implemented later


tileTypes = { # limited to 4 types to maximize caching ability
    Environment.EMPTY: 0, # Only counts if they are passable, or have a team barrier on them
    Environment.ORE_TITANIUM: 1, # Only counts if they dont have a harvester on them
    Environment.WALL: 2,
    'Unpassable': 3 # have an unpassable non team barrier building or are threat from turrets, 
}  
# shared array. 0: num bots spawned 1-6: new tiles from that bot 7: the map symmetry (nothing writes it yet)


class DialPathfinderAdapter:
    """The small Pathfinder surface expected by Defender."""

    def __init__(self, player):
        self.player = player

    def moveTo(self, ct: Controller, target: Position):
        self.player.moveTo(ct, target)

    def reset(self):
        # defend.py wants a pf object, just hand it the new mover
        pass

class Player:
    def __init__(self):
        self.defender = Defender()
        self.pf = DialPathfinderAdapter(self)

        self.fullMap = None # bot's local version of the full map
        self.newTiles = [] # shared publicly so all bots have info
        self.seenTiles = None # used to get self.newTiles
        self.numSpawned = 0
        self.myNum = -1 # every builder bot gets its own unique number used to write to the shared array, and organize roles (1, 2, 3, ...)
        self.teamCore = None
        self.distMap = None
        self._cacheTarget = None  # dijkstra reuse: skip recompute on same target+map
        self._cacheVer = -1
        self.mapW = None
        self.mapH = None
        self.stuckTurns = 0
        self.turretPlanner = None
        self.turtled = False  # opponent kills cores, we stop attacking
        self.replacements = 0      # capped respawns so deaths cant chain-drain
        self.lastReplaceRound = -999
        self.homeDefense = homedefense.HomeDefense()

        self.randDir = Direction.NORTH

        # Role
        self.attackMode = False
        self.alwaysDefense = False
        self.defenseMode = False
        self.justSpawned = True

        # Attacking
        self.attackPos = None
        self.spawnSentinelHere = None

        # Cores
        self.teamCoreTiles = None
        self.enemyCore = None

        # Launcher proofing
        self.oldPos = None

        # Harvester finding
        self.currentHarvester = None
        self.foundHarvester = None
        self.usedHarvesters = []
        self.reachHarvesterTime = 0

        # Building back and sentinel placement
        self.conveyorEnd = None
        self.surroundHarvester = False
        self.protectTurns = 0
        self.sentinelSpot = None
        self.isEnemyInfastructure = None
        self.nextTurretCountDown = 0

        # Placing a sentinel while extending economy
        self.turretTimeOut = 0
        self.enemyPos = None
        self.enemyType = -1

        # Exploring and symmetry attack hypotheses
        self.explorePos = None
        self.exploreTime = 0
        self.attackMoveTimeout = 0
        self.attackHypothesisIndex = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            if self.mapW is None:
                self.mapW = ct.get_map_width()
                self.mapH = ct.get_map_height()
                mapanalysis.reset_map(self.mapW, self.mapH)
            self.core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builderBot(ct)
        elif etype == EntityType.SENTINEL:
            self.sentinel(ct)
        elif etype == EntityType.LAUNCHER:
            self.launcher(ct)
        elif etype == EntityType.GUNNER:
            self.gunner(ct)

    def core(self, ct: Controller) -> None:
        homeEmergency = self.homeDefense.observe_from_core(ct)

        # replacement respawn: capped + cooldowned so a sentinel wall cant
        # farm our titanium one dead builder at a time (string tiebreak: 41
        # dead builders = ~1200 ti gone)
        rnd = ct.get_current_round()
        wantReplace = (rnd >= 30 and self.replacements < REPLACE_CAP
                       and rnd - self.lastReplaceRound >= REPLACE_COOLDOWN
                       and ct.get_unit_count() <= 6
                       and ct.get_global_resources() >= ct.get_builder_bot_cost() + 60)
        # spawn first so the ammo topup doesnt eat the builder money
        if spawnBots(self.numSpawned, ct) or wantReplace:
            _isReplace = not spawnBots(self.numSpawned, ct)
            corePos = ct.get_position()
            threats = findThreats(ct)
            spawned = False

            for dx in (-1, 0, 1, 2):
                for dy in (-1, 0, 1, 2):
                    # skip the core's own 4 tiles
                    if 0 <= dx <= 1 and 0 <= dy <= 1:
                        continue

                    spawnPos = Position(corePos.x + dx, corePos.y + dy)
                    if not ct.can_spawn(spawnPos):
                        continue
                    if any(spawnPos.distance_squared(threat) <= 2
                           for threat in threats):
                        continue

                    ct.spawn_builder(spawnPos)
                    self.numSpawned += 1
                    if _isReplace:
                        self.replacements += 1
                        self.lastReplaceRound = rnd
                    # slot 0 also drives builder numbering + the share rotation
                    ct.write_store(0, self.numSpawned)
                    spawned = True
                    break

                if spawned:
                    break

        ammoBuffer = (homedefense.HOME_AMMO_BUFFER if homeEmergency
                      else GLOBAL_AMMO_BUFFER)
        currentAmmo = ct.get_global_ammo()
        if currentAmmo < ammoBuffer:
            # keep enough for the next builder
            spareTitanium = (
                ct.get_global_resources() - ct.get_builder_bot_cost()
            )
            amount = min(ammoBuffer - currentAmmo, spareTitanium)
            if amount > 0 and ct.can_convert_ammo(amount):
                ct.convert_ammo(amount)

    def gunner(self, ct: Controller) -> None:
        target = ct.get_gunner_target()
        if target is not None:
            builder_id = ct.get_tile_builder_bot_id(target)
            building_id = ct.get_tile_building_id(target)
            target_id = builder_id if builder_id is not None else building_id
            if (target_id is not None
                    and ct.get_team(target_id) != ct.get_team()):
                if ct.can_fire(target):
                    ct.fire(target)
                return

        if (ct.get_global_resources() < GUNNER_ROTATE_MIN_TITANIUM
                or ct.get_action_cooldown() != 0):
            return

        my_pos = ct.get_position()
        current_facing = ct.get_direction()
        candidates = []
        for entity_id in ct.get_nearby_entities(13):
            entity_type = ct.get_entity_type(entity_id)
            if entity_type not in (
                    EntityType.GUNNER, EntityType.SENTINEL,
                    EntityType.BUILDER_BOT):
                continue
            if ct.get_team(entity_id) == ct.get_team():
                continue
            enemy_pos = ct.get_position(entity_id)
            dx = enemy_pos.x - my_pos.x
            dy = enemy_pos.y - my_pos.y
            if dx != 0 and dy != 0:
                continue
            if dx > 0:
                facing = Direction.EAST
            elif dx < 0:
                facing = Direction.WEST
            elif dy > 0:
                facing = Direction.SOUTH
            elif dy < 0:
                facing = Direction.NORTH
            else:
                continue
            if facing == current_facing:
                continue
            priority = 0 if entity_type in (
                EntityType.GUNNER, EntityType.SENTINEL
            ) else 1
            candidates.append((priority, my_pos.distance_squared(enemy_pos),
                               CARDINALS.index(facing), facing))

        if candidates:
            facing = min(candidates)[3]
            if ct.can_rotate(facing):
                ct.rotate(facing)

    def sentinel(self, ct: Controller) -> None:
        if self.enemyCore is None:
            self.enemyCore = findEnemyCore(ct)

        team = ct.get_team()
        priority = {
            EntityType.CORE: 5,
            EntityType.SENTINEL: 3,
            EntityType.GUNNER: 3,
            EntityType.BARRIER: 2,
            EntityType.LAUNCHER: 2,
            EntityType.CONVEYOR: 1,
        }
        # no HARVESTER here on purpose, stealing them is better
        targets = {
            EntityType.CORE,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BARRIER,
            EntityType.LAUNCHER,
            EntityType.CONVEYOR,
        }

        bestTile = None
        bestPriority = 0
        for tile in ct.get_attackable_tiles():
            if not self.isInBounds(ct, tile) or not ct.is_in_vision(tile):
                continue
            buildingID = ct.get_tile_building_id(tile)
            builderID = ct.get_tile_builder_bot_id(tile)

            if builderID is not None and ct.get_team(builderID) == team:
                continue
            if buildingID is not None and ct.get_team(buildingID) == team:
                continue

            tilePriority = 0
            if buildingID is not None:
                buildingType = ct.get_entity_type(buildingID)
                if buildingType not in targets:
                    continue
                tilePriority = priority.get(buildingType, 1)
                if builderID is not None:
                    tilePriority += 2
            elif builderID is not None:
                # not worth 10 ammo on a lone builder
                continue

            if tilePriority > bestPriority:
                bestPriority = tilePriority
                bestTile = tile

        if bestTile is not None and ct.can_fire(bestTile):
            ct.fire(bestTile)

    def launcher(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        for d in CARDINALS:
            adjacent = myLoc.add(d)
            if not self.isInBounds(ct, adjacent) or not ct.is_in_vision(adjacent):
                continue
            bot_id = ct.get_tile_builder_bot_id(adjacent)
            if bot_id is None or ct.get_team(bot_id) == ct.get_team():
                continue

            best = None
            bestDist = -1
            for tile in ct.get_nearby_tiles(26):
                if ct.can_launch(adjacent, tile):
                    dist = self.manhattan(myLoc, tile)
                    if dist > bestDist:
                        bestDist = dist
                        best = tile
            if best is not None:
                ct.launch(adjacent, best)
                return

    def builderBot(self, ct: Controller) -> None:
        currentRound = ct.get_current_round()
        myLoc = ct.get_position()
        self.setUp(ct, myLoc)

        if self.myNum == -1:
            # first read is k-1 on our spawn round (writes land next round),
            # +1 = unique 1..n since the core only spawns 1 per turn
            self.myNum = ct.read_store(0) + 1
        if self.mapW is None or self.mapH is None:
            self.mapW = ct.get_map_width()
            self.mapH = ct.get_map_height()
        if self.distMap is None:
            self.distMap = [[4096 for _ in range(self.mapH)]
                            for _ in range(self.mapW)]
        if self.fullMap is None:
            self.fullMap = [[-1 for _ in range(self.mapH)]
                            for _ in range(self.mapW)]
            mapanalysis.configure_map(self.mapW, self.mapH)
        if self.seenTiles is None:
            self.seenTiles = [[False for _ in range(self.mapH)]
                              for _ in range(self.mapW)]

        # order matters: comms first, real work, leftover-cpu stuff last
        self.getNewTiles(ct)
        self.shareTiles(ct, currentRound)
        self.updateBoard(ct)
        if self.teamCore is not None and self.turretPlanner is None:
            self.turretPlanner = turretplan.TurretPlanner(
                self.mapW, self.mapH, self.teamCore
            )
        if self.turretPlanner is not None:
            self.turretPlanner.sync_and_observe(ct)

        if (not self.turtled and self.turretPlanner is not None
                and self.homeDefense.should_turtle(
                    ct, self.turretPlanner,
                    self.teamCoreTiles or ([self.teamCore] if self.teamCore else []))):
            self.turtled = True

        responding, reactiveBuilt = self.homeDefense.respond(
            ct, self.turretPlanner, self.myNum,
            self.teamCoreTiles or ([self.teamCore] if self.teamCore else []),
            self.fullMap, self.moveTo,
        )
        if reactiveBuilt is not None:
            self.noteBuiltTile(reactiveBuilt)

        if not responding:
            self.runRoleBehavior(ct, currentRound)

            # urgent turret proposal only if we didnt already move this turn
            if (self.turretPlanner is not None
                    and self.turretPlanner.should_pursue_urgent(
                        ct, self.myNum
                    )):
                proposal = self.turretPlanner.current_proposal
                self.moveTo(ct, Position(proposal.x, proposal.y))

            if self.turretPlanner is not None:
                built = self.turretPlanner.try_passive_build(ct)
                if built is not None:
                    self.noteBuiltTile(Position(built.x, built.y))
        self.advanceMapAnalysis(ct)
        if self.turretPlanner is not None:
            self.turretPlanner.advance(ct, self.fullMap, self.myNum)
            self.turretPlanner.draw_debug(ct)

    def noteBuiltTile(self, builtPos: Position):
        oldType = self.fullMap[builtPos.x][builtPos.y]
        self.fullMap[builtPos.x][builtPos.y] = 3
        self.seenTiles[builtPos.x][builtPos.y] = True
        self.newTiles.append([builtPos, 3])
        if oldType not in (2, 3):
            mapanalysis.note_structural_tile(
                builtPos.x, builtPos.y, True, self.mapW, self.mapH
            )

    def setUp(self, ct: Controller, myLoc: Position):
        if self.teamCore is None:
            self.teamCore = findTeamCore(ct)
            if self.teamCore is not None:
                self.teamCoreTiles = self._computeCoreTiles(ct, self.teamCore)
        if self.enemyCore is None:
            self.enemyCore = findEnemyCore(ct)
        if self.oldPos is not None and self.manhattan(myLoc, self.oldPos) > 1:
            self.pf.reset()
        self.oldPos = myLoc

    def _computeCoreTiles(self, ct: Controller, corner: Position) -> list:
        if not self.isInBounds(ct, corner) or not ct.is_in_vision(corner):
            return [corner]
        cid = ct.get_tile_building_id(corner)
        tiles = []
        if cid is not None:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = Position(corner.x + dx, corner.y + dy)
                    if (self.isInBounds(ct, q) and ct.is_in_vision(q)
                            and ct.get_tile_building_id(q) == cid):
                        tiles.append(q)
        return tiles if tiles else [corner]

    @staticmethod
    def manhattan(a: Position, b: Position) -> int:
        return abs(a.x - b.x) + abs(a.y - b.y)

    def nearCore2(self, pos: Position) -> int:
        tiles = self.teamCoreTiles if self.teamCoreTiles else [self.teamCore]
        tiles = [tile for tile in tiles if tile is not None]
        if not tiles:
            return (self.mapW + self.mapH) if self.mapW is not None else 4096
        return min(self.manhattan(pos, tile) for tile in tiles)

    @staticmethod
    def cardinalDirectionTo(origin: Position, target: Position) -> Direction:
        dx = target.x - origin.x
        dy = target.y - origin.y
        if abs(dx) >= abs(dy) and dx != 0:
            return Direction.EAST if dx > 0 else Direction.WEST
        if dy != 0:
            return Direction.SOUTH if dy > 0 else Direction.NORTH
        return Direction.CENTRE

    def runRoleBehavior(self, ct: Controller, currentRound: int):
        myLoc = ct.get_position()
        if ct.get_hp() < ct.get_max_hp() and ct.can_heal(myLoc):
            ct.heal(myLoc)

        if (ct.get_id() < 5
                and self.currentHarvester is None
                and (currentRound > 20 or self.nearCore2(myLoc) < 3)):
            self.alwaysDefense = True
            self.defenseMode = True
        if currentRound % 120 == 1 or self.justSpawned:
            self.assignRole(ct, currentRound)
        self.justSpawned = False

        # old repair pass
        self.defender.defendInfrastructure(ct, self.teamCore, self.pf)

        if self.attackMode:
            if self.turtled:
                # attacking this opponent just feeds it our workforce.
                # go MINE, not park: econ margin is the whole win condition,
                # and defense capacity comes from the guard + interrupts
                self.attackMode = False
                self.defenseMode = False
            else:
                self.attack(ct)
                return
        if self.defenseMode:
            self.defender.defendInfrastructure(ct, self.teamCore, self.pf)
            # big-map standing guard comes before idle heal-parking
            guardEngaged, guardBuilt = self.homeDefense.maintain_standing_guard(
                ct, self.turretPlanner,
                self.teamCoreTiles or ([self.teamCore] if self.teamCore else []),
                self.enemyCore, self.fullMap, self.moveTo,
            )
            if guardBuilt is not None:
                self.noteBuiltTile(guardBuilt)
            if guardEngaged:
                return
            healPos = self.defender.picHealingLoc(
                ct, self.teamCore, self.alwaysDefense
            )
            if (self.nearCore2(ct.get_position()) < 3
                    and ct.get_global_resources() >= ct.get_conveyor_cost()):
                direction = self.cardinalDirectionTo(
                    ct.get_position(), self.teamCore
                )
                if (direction != Direction.CENTRE
                        and ct.can_build_conveyor(ct.get_position(), direction)):
                    ct.build_conveyor(ct.get_position(), direction)
            if healPos is not None:
                self.moveTo(ct, healPos)
            return

        if self.currentHarvester is not None:
            if self.surroundHarvester:
                self.buildConveyor(ct)
            else:
                self.protectHarvester(ct)
        else:
            self.getHarvester(ct, ct.get_position())
            if self.foundHarvester is None and self.currentHarvester is None:
                myLoc = ct.get_position()
                if (self.explorePos is None or self.exploreTime > 35
                        or self.manhattan(self.explorePos, myLoc) <= 2):
                    self.pickExplore(ct, currentRound)
                    self.exploreTime = 0
                self.exploreTime += 1
                ct.draw_indicator_line(myLoc, self.explorePos, 255, 255, 255)
                self.moveTo(ct, self.explorePos)

    def assignRole(self, ct: Controller, currentRound):
        if currentRound <= 120:
            # 36% Offense, 64% Eco + 1 Defense Bot
            if (currentRound % 11 in [3, 5, 7, 10]
                    and self.currentHarvester is None
                    and not self.turtled):
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
                if role > 0.75 or self.alwaysDefense:
                    self.defenseMode = True
                elif role > 0.4 and not self.turtled:
                    self.attackMode = True

    def attack(self, ct: Controller) -> None:
        if self.teamCore is None:
            return
        myLoc = ct.get_position()
        coreHypothesis = [
            Position(ct.get_map_width() - 2 - self.teamCore.x,
                     ct.get_map_height() - 2 - self.teamCore.y),
            Position(ct.get_map_width() - 2 - self.teamCore.x,
                     self.teamCore.y),
            Position(self.teamCore.x,
                     ct.get_map_height() - 2 - self.teamCore.y),
        ]
        if self.enemyCore is not None:
            self.attackPos = self.enemyCore
        elif self.attackPos is None:
            self.attackPos = coreHypothesis[self.attackHypothesisIndex]
            self.attackMoveTimeout = 0

        def nextAttackHypothesis():
            self.attackHypothesisIndex = (
                self.attackHypothesisIndex + 1
            ) % len(coreHypothesis)
            self.attackPos = coreHypothesis[self.attackHypothesisIndex]
            self.attackMoveTimeout = 0

        def changeAttackPos():
            dx = 5 * random.randint(-1, 1)
            dy = 5 * random.randint(-1, 1)
            new_x = max(0, min(self.attackPos.x + dx,
                               ct.get_map_width() - 1))
            new_y = max(0, min(self.attackPos.y + dy,
                               ct.get_map_height() - 1))
            self.attackPos = Position(new_x, new_y)
            self.attackMoveTimeout = 0

        if self.manhattan(myLoc, self.attackPos) < 4:
            changeAttackPos()

        if self.spawnSentinelHere is None:
            nearbyEnemyStuff = []
            for building_id in ct.get_nearby_buildings():
                if (ct.get_entity_type(building_id) == EntityType.CONVEYOR
                        and ct.get_team(building_id) != ct.get_team()
                        and ct.get_stored_resource(building_id) is not None):
                    nearbyEnemyStuff.append(ct.get_position(building_id))
            nearbyEnemyStuff.sort(
                key=lambda p: self.manhattan(p, self.attackPos)
            )

            if not nearbyEnemyStuff:
                self.attackMoveTimeout += 1
                self.moveTo(ct, self.attackPos)
                if self.attackMoveTimeout > 20:
                    if self.enemyCore is None:
                        nextAttackHypothesis()
                    else:
                        changeAttackPos()
                return
            self.spawnSentinelHere = nearbyEnemyStuff[0]
            self.attackMoveTimeout = 0

        for building_id in ct.get_nearby_buildings():
            if (ct.get_entity_type(building_id) == EntityType.SENTINEL
                    and ct.get_team(building_id) == ct.get_team()
                    and self.manhattan(ct.get_position(building_id),
                                       self.spawnSentinelHere) <= 4):
                self.spawnSentinelHere = None
                self.attackMoveTimeout = 0
                self.moveTo(ct, self.attackPos)
                return

        if self.attackMoveTimeout > 25:
            self.spawnSentinelHere = None
            self.attackMoveTimeout = 0
            return

        if myLoc != self.spawnSentinelHere:
            self.moveTo(ct, self.spawnSentinelHere)
            self.attackMoveTimeout += 1
            return
        self.attackMoveTimeout = 0

        if (not self.isInBounds(ct, self.spawnSentinelHere)
                or not ct.is_in_vision(self.spawnSentinelHere)):
            return
        building_id = ct.get_tile_building_id(self.spawnSentinelHere)
        if building_id is not None:
            if ct.get_team(building_id) == ct.get_team():
                if ct.can_destroy(self.spawnSentinelHere):
                    ct.destroy(self.spawnSentinelHere)
            else:
                self.defender.placeLauncher(ct, self.spawnSentinelHere)
                self.moveTo(ct, self.spawnSentinelHere)
                if ct.can_fire(self.spawnSentinelHere):
                    ct.fire(self.spawnSentinelHere)

        building_id = ct.get_tile_building_id(self.spawnSentinelHere)
        if building_id is None:
            if ct.get_position() == self.spawnSentinelHere:
                self.moveTo(ct, self.attackPos)
            directionChoices = {d: 0 for d in CARDINALS}
            for enemy_id in ct.get_nearby_buildings():
                if ct.get_team(enemy_id) == ct.get_team():
                    continue
                direction = self.cardinalDirectionTo(
                    self.spawnSentinelHere, ct.get_position(enemy_id)
                )
                if direction == Direction.CENTRE:
                    continue
                if ct.get_entity_type(enemy_id) == EntityType.CORE:
                    directionChoices[direction] += 25
                else:
                    directionChoices[direction] += 1

            directionChoice = max(
                directionChoices, key=lambda d: directionChoices[d]
            )
            if ct.can_build_sentinel(self.spawnSentinelHere, directionChoice):
                ct.build_sentinel(self.spawnSentinelHere, directionChoice)
                self.spawnSentinelHere = None
                self.attackPos = None

    def pickExplore(self, ct: Controller, currentRound):
        w = ct.get_map_width()
        h = ct.get_map_height()
        myLoc = ct.get_position()
        radius = (w + h) // 5
        if currentRound > 5:
            theta = random.random() * 2 * math.pi
        else:
            theta = (((3 * currentRound) % 5) / 5) * 2 * math.pi
        tx = int(max(0, min(w - 1, myLoc.x + math.cos(theta) * radius)))
        ty = int(max(0, min(h - 1, myLoc.y + math.sin(theta) * radius)))
        self.explorePos = Position(tx, ty)

    def getHarvester(self, ct: Controller, myLoc: Position):
        if self.foundHarvester is None:
            # shared map first: chase ore teammates found, no out of vision queries
            used = set(self.usedHarvesters)
            knownOres = {
                Position(x, y)
                for x in range(self.mapW)
                for y in range(self.mapH)
                if self.fullMap[x][y] == 1
                and Position(x, y) not in used
            }
            # still scan vision too: enemy harvesters sit on ore thats blocked in fullMap
            for tile in ct.get_nearby_tiles():
                if (tile not in used
                        and ct.get_tile_env(tile) == Environment.ORE_TITANIUM):
                    knownOres.add(tile)
            knownOres = list(knownOres)
            knownOres.sort(
                key=lambda p: (self.manhattan(p, myLoc) + self.nearCore2(p),
                               p.x, p.y)
            )
            for orePos in knownOres:
                willWork = True
                if ct.is_in_vision(orePos):
                    oreID = ct.get_tile_building_id(orePos)
                    if oreID is not None:
                        willWork = (
                            ct.get_team(oreID) == ct.get_team()
                            or ct.get_entity_type(oreID) == EntityType.HARVESTER
                        )
                if willWork:
                    self.foundHarvester = orePos
                    self.reachHarvesterTime = 0
                    break
            if self.foundHarvester is None:
                return

        if self.reachHarvesterTime >= 20:
            self.removeHarvester(ct)
            return

        if ct.is_in_vision(self.foundHarvester):
            oreID = ct.get_tile_building_id(self.foundHarvester)
            if oreID is not None:
                if ct.get_team(oreID) == ct.get_team():
                    if ct.get_entity_type(oreID) == EntityType.HARVESTER:
                        self.removeHarvester(ct)
                        return
                    if (ct.can_destroy(self.foundHarvester)
                            and myLoc.distance_squared(self.foundHarvester) <= 2):
                        # destroying our own stuff is free, doesnt use the build action
                        ct.destroy(self.foundHarvester)
                elif ct.get_entity_type(oreID) != EntityType.HARVESTER:
                    self.removeHarvester(ct)
                    return

        if myLoc == self.foundHarvester:
            possibleSpots = []
            for direction in CARDINALS:
                pos = myLoc.add(direction)
                if self.isInBounds(ct, pos) and ct.can_move(direction):
                    possibleSpots.append(pos)
            possibleSpots.sort(key=lambda pos: self.nearCore2(pos))
            if possibleSpots:
                self.moveTo(ct, possibleSpots[0])
            else:
                self.usedHarvesters.append(self.foundHarvester)
                self.foundHarvester = None
            return

        if self.manhattan(myLoc, self.foundHarvester) > 1:
            self.moveTo(ct, self.foundHarvester)
            self.reachHarvesterTime += 1
            return

        if (ct.is_in_vision(self.foundHarvester)
                and ct.get_position().distance_squared(self.foundHarvester) <= 2):
            if ct.can_build_harvester(self.foundHarvester):
                ct.build_harvester(self.foundHarvester)
                self.addHarvester(ct, ct.get_position())
                return
            oreID = ct.get_tile_building_id(self.foundHarvester)
            if (oreID is not None
                    and ct.get_entity_type(oreID) == EntityType.HARVESTER
                    and ct.get_team(oreID) != ct.get_team()):
                self.addHarvester(ct, ct.get_position())

    def removeHarvester(self, ct: Controller):
        if self.foundHarvester is not None:
            self.usedHarvesters.append(self.foundHarvester)
        self.foundHarvester = None
        self.reachHarvesterTime = 0

    def addHarvester(self, ct: Controller, myLoc: Position):
        self.currentHarvester = self.foundHarvester
        self.usedHarvesters.append(self.foundHarvester)
        self.foundHarvester = None
        self.conveyorEnd = myLoc
        self.surroundHarvester = False
        self.isEnemyInfastructure = None
        self.sentinelSpot = None
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
            for building_id in ct.get_nearby_buildings():
                if ct.get_team(building_id) != ct.get_team():
                    self.isEnemyInfastructure = ct.get_position(building_id)

        protectSpots = []
        for direction in CARDINALS:
            pos = self.currentHarvester.add(direction)
            if (self.isInBounds(ct, pos) and ct.is_in_vision(pos)
                    and pos != self.conveyorEnd
                    and ct.get_tile_env(pos) != Environment.WALL
                    and ct.get_tile_building_id(pos) is None):
                protectSpots.append(pos)
        if not protectSpots:
            self.protectTurns = 0
            self.surroundHarvester = True
            self.isEnemyInfastructure = None
            self.sentinelSpot = None
            return

        if self.isEnemyInfastructure is not None and self.sentinelSpot is None:
            protectSpots.sort(
                key=lambda pos: self.manhattan(pos, self.isEnemyInfastructure)
            )
            self.sentinelSpot = protectSpots[0]

        myLoc = ct.get_position()
        protectSpots.sort(key=lambda pos: self.manhattan(pos, myLoc))
        if myLoc in protectSpots:
            self.moveTo(ct, self.currentHarvester)
            return
        if myLoc.distance_squared(protectSpots[0]) > 2:
            self.moveTo(ct, protectSpots[0])
            return

        for pos in protectSpots:
            if pos == self.sentinelSpot:
                direction = self.cardinalDirectionTo(
                    pos, self.isEnemyInfastructure
                )
                if (direction != Direction.CENTRE
                        and ct.get_global_resources() >= MILITARY_FLOOR
                        and ct.can_build_sentinel(pos, direction)):
                    ct.build_sentinel(pos, direction)
                    return
            elif ct.can_build_barrier(pos):
                ct.build_barrier(pos)
                return

    def buildConveyor(self, ct: Controller):
        if self.conveyorEnd is None:
            self.currentHarvester = None
            return
        ct.draw_indicator_dot(self.conveyorEnd, 255, 255, 255)
        myLoc = ct.get_position()
        if self.nearCore2(self.conveyorEnd) == 0:
            self.currentHarvester = None
            self.conveyorEnd = None
            return
        if myLoc.distance_squared(self.conveyorEnd) > 2:
            self.moveTo(ct, self.conveyorEnd)
            return
        if (not self.isInBounds(ct, self.conveyorEnd)
                or not ct.is_in_vision(self.conveyorEnd)):
            return

        conveyorID = ct.get_tile_building_id(self.conveyorEnd)
        if (conveyorID is None and self.nextTurretCountDown <= 0
                and self.nearCore2(self.conveyorEnd) > 1
                and myLoc != self.conveyorEnd
                and self.enemyPos is None and self.turretTimeOut == 0):
            for building_id in ct.get_nearby_buildings():
                if ct.get_team(building_id) == ct.get_team():
                    continue
                ct.draw_indicator_dot(ct.get_position(building_id), 200, 20, 100)
                enemyType = ct.get_entity_type(building_id)
                pos = ct.get_position(building_id)
                if enemyType == EntityType.CORE:
                    self.enemyPos, self.enemyType = pos, 3
                elif (enemyType in (EntityType.SENTINEL, EntityType.GUNNER)
                      and self.enemyType < 2):
                    self.enemyPos, self.enemyType = pos, 2
                elif enemyType == EntityType.CONVEYOR and self.enemyType < 1:
                    self.enemyPos, self.enemyType = pos, 1
                elif (enemyType in (EntityType.LAUNCHER, EntityType.BARRIER)
                      and self.enemyType < 0):
                    self.enemyPos, self.enemyType = pos, 0

        if self.enemyPos is not None and self.turretTimeOut == 0:
            direction = self.cardinalDirectionTo(self.conveyorEnd, self.enemyPos)
            if (direction != Direction.CENTRE
                    and ct.get_global_resources() >= MILITARY_FLOOR
                    and ct.can_build_sentinel(self.conveyorEnd, direction)):
                ct.build_sentinel(self.conveyorEnd, direction)
                self.turretTimeOut = 1
                self.nextTurretCountDown = 5
            else:
                return
        if self.turretTimeOut > 0:
            self.turretTimeOut += 1
        if self.enemyType == 3 and self.turretTimeOut > 0:
            self.currentHarvester = None
            self.conveyorEnd = None
            self.enemyPos = None
            self.enemyType = -1
            return
        if self.turretTimeOut > 24:
            self.enemyPos = None
            self.enemyType = -1
        elif self.turretTimeOut > 0:
            return
        self.buildCloser(ct)

    def buildCloser(self, ct: Controller):
        if self.conveyorEnd is None:
            return
        myLoc = ct.get_position()
        if (not self.isInBounds(ct, self.conveyorEnd)
                or not ct.is_in_vision(self.conveyorEnd)):
            self.moveTo(ct, self.conveyorEnd)
            return

        endID = ct.get_tile_building_id(self.conveyorEnd)
        if endID is not None:
            endEntity = ct.get_entity_type(endID)
            if (endEntity == EntityType.CONVEYOR
                    and ct.get_team(endID) == ct.get_team()):
                self.conveyorEnd = None
                self.currentHarvester = None
                return
            if ct.can_destroy(self.conveyorEnd):
                ct.destroy(self.conveyorEnd)
            if myLoc != self.conveyorEnd:
                self.moveTo(ct, self.conveyorEnd)
            if self.defender.destroyTurns > 5:
                self.defender.placeLauncher(ct, self.conveyorEnd)
            if ct.can_fire(self.conveyorEnd):
                ct.fire(self.conveyorEnd)
                self.defender.destroyTurns += 1

        possibleConveyors = []
        for direction in CARDINALS:
            end = self.conveyorEnd.add(direction)
            if (self.isInBounds(ct, end) and ct.is_in_vision(end)
                    and ct.can_build_conveyor(self.conveyorEnd, direction)
                    and ct.get_tile_env(end) in
                    (Environment.EMPTY, Environment.ORE_TITANIUM)):
                possibleConveyors.append(direction)
        possibleConveyors.sort(
            key=lambda direction: self.nearCore2(
                self.conveyorEnd.add(direction)
            )
        )

        for direction in possibleConveyors:
            end = self.conveyorEnd.add(direction)
            if (self.nearCore2(end) == 0
                    and ct.can_build_conveyor(self.conveyorEnd, direction)):
                ct.build_conveyor(self.conveyorEnd, direction)
                self.nextTurretCountDown = 0
                self.currentHarvester = None
                self.conveyorEnd = None
                return

        for direction in possibleConveyors:
            end = self.conveyorEnd.add(direction)
            if self.nearCore2(end) >= self.nearCore2(self.conveyorEnd):
                continue
            endID = ct.get_tile_building_id(end)
            if (endID is not None
                    and ct.get_entity_type(endID) == EntityType.CONVEYOR
                    and ct.get_team(endID) == ct.get_team()
                    and ct.can_build_conveyor(self.conveyorEnd, direction)
                    and ct.get_stored_resource(endID) is None):
                ct.build_conveyor(self.conveyorEnd, direction)
                self.nextTurretCountDown = 0
                self.currentHarvester = None
                self.conveyorEnd = None
                self.turretTimeOut = 0
                self.enemyPos = None
                self.enemyType = -1
                return

        for direction in possibleConveyors:
            end = self.conveyorEnd.add(direction)
            endID = ct.get_tile_building_id(end)
            canReplace = (
                endID is None
                or (ct.get_entity_type(endID) in
                    (EntityType.BARRIER, EntityType.LAUNCHER)
                    and ct.get_team(endID) == ct.get_team())
            )
            if (canReplace
                    and ct.can_build_conveyor(self.conveyorEnd, direction)):
                ct.build_conveyor(self.conveyorEnd, direction)
                self.nextTurretCountDown -= 1
                self.conveyorEnd = end
                self.turretTimeOut = 0
                self.enemyPos = None
                self.enemyType = -1
                return

    def isInBounds(self, ct: Controller, pos: Position) -> bool:
        return (0 <= pos.x < ct.get_map_width()
                and 0 <= pos.y < ct.get_map_height())


    def checkPassable (self, ct: Controller, tile: Position): # Only team barriers, or empty tiles are passbale
        if not self.isInBounds(ct, tile) or not ct.is_in_vision(tile):
            return False
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
            oldType = self.fullMap[x][y]
            if self.seenTiles[x][y] == False or self.fullMap[x][y] != tileType:
                self.seenTiles[x][y] = True
                self.newTiles.append([Position(x, y), tileType]) 
            if (oldType in (-1, 2, 3)) != (tileType in (-1, 2, 3)):
                mapanalysis.note_structural_tile(
                    x, y, tileType in (-1, 2, 3), self.mapW, self.mapH
                )
            self.fullMap[x][y] = tileType
    
    def shareTiles(self, ct: Controller, curRound):
        spawnCount = ct.read_store(0)
        # store reads 0 on round one, skip so we dont % 0
        if spawnCount <= 0 or self.myNum < 1 or self.teamCore is None:
            return
        boundedRound = curRound % spawnCount + 1 # to bound it from 1 to n
        if boundedRound == self.myNum: # means your turn to share in the shared array if the mod is correct
            
            # start by sorting newTiles by the 16 tiles farthest away from your core
            self.newTiles.sort(
                key=lambda tile: self.manhattan(tile[0], self.teamCore),
                reverse=True,
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

            oldType = self.fullMap[x][y]
            if (oldType in (-1, 2, 3)) != (t_type in (-1, 2, 3)):
                mapanalysis.note_structural_tile(
                    x, y, t_type in (-1, 2, 3), self.mapW, self.mapH
                )
            self.fullMap[x][y] = t_type
            if not self.seenTiles[x][y]: 
                self.seenTiles[x][y] = True
                
            self.newTiles = [t for t in self.newTiles if not (t[0].x == x and t[0].y == y)] # you dont want to broadcast the same position twice

    def advanceMapAnalysis(self, ct: Controller):
        """Spend only post-action spare cycles on the shared analysis job."""
        analysisJob = mapanalysis.job
        if (analysisJob is None
                and ct.get_cpu_time_elapsed() < mapanalysis.CPU_BUDGET_US):
            analysisJob = mapanalysis.get_job()
        while (analysisJob is not None
               and ct.get_cpu_time_elapsed() < mapanalysis.CPU_BUDGET_US
               and analysisJob.phase != mapanalysis.DONE):
            analysisJob.step()

        if analysisJob is not None and analysisJob.phase == mapanalysis.DONE:
            mapanalysis.draw_debug(ct, Position)
            
    def tileCost(self, ct: Controller, tile: Position) -> int | None:
        if not (0 <= tile.x < self.mapW and 0 <= tile.y < self.mapH):
            return None
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
        maxCost = (w + h) * barrierCost + 5
        
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

    def moveTo (self, ct: Controller, target: Position):
        if ct.get_move_cooldown() != 0:
            return
        overBudget = ct.get_cpu_time_elapsed() > 7000
        myLoc = ct.get_position()
        if myLoc == target:
            return
        # target can be off-map on small maps
        if not (0 <= target.x < self.mapW and 0 <= target.y < self.mapH):
            return
        if overBudget:
            # low on budget: greedy step instead of the full dijkstra
            bestDir = None
            bestDist = 4096
            for d in CARDINALS:
                nextPos = myLoc.add(d)
                if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH and ct.can_move(d):
                    posDist = abs(nextPos.x - target.x) + abs(nextPos.y - target.y)
                    if posDist < bestDist:
                        bestDir = d
                        bestDist = posDist
            if bestDir is not None:
                ct.move(bestDir)
                self.stuckTurns = 0
            else:
                self.stuckTurns += 1
            return
        # cache: only rerun dijkstra when target or the shared map changed, or
        # we walked into cells this table never filled (early-exit is bot-anchored)
        ver = mapanalysis.struct_version
        fresh = self._cacheTarget == target and self._cacheVer == ver and any(
            0 <= myLoc.add(d).x < self.mapW and 0 <= myLoc.add(d).y < self.mapH
            and self.distMap[myLoc.add(d).x][myLoc.add(d).y] < 4096
            for d in CARDINALS)
        if not fresh:
            self.fillInDistTable(ct, target)
            self._cacheTarget = target
            self._cacheVer = ver
        bestDist = 4096
        bestDir = None
        for d in CARDINALS:
            nextPos = myLoc.add(d)
            if 0 <= nextPos.x < self.mapW and 0 <= nextPos.y < self.mapH:
                posDist = self.distMap[nextPos.x][nextPos.y]
                # tile queries raise outside vision
                tileId = ct.get_tile_building_id(nextPos) if ct.is_in_vision(nextPos) else None
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
        # boxed in, nothing movable
        if bestDir is None:
            self.stuckTurns += 1
            if self.stuckTurns > 2 + (ct.get_id() % 8):
                movableDirs = []
                for i in CARDINALS:
                    if ct.can_move(i):
                        movableDirs.append(i)
                if len(movableDirs) > 0:
                    ct.move(random.choice(movableDirs))
            return

        nextPos = myLoc.add(bestDir)
        tileId = ct.get_tile_building_id(nextPos) if ct.is_in_vision(nextPos) else None
        if tileId is not None:
            tTeam = ct.get_team(tileId)
            tType = ct.get_entity_type(tileId)
            if tTeam == ct.get_team() and tType == EntityType.BARRIER:
                if ct.can_destroy(nextPos):
                    ct.destroy(nextPos)
                else:
                    return # dont want to increase stuckTurns for no reason
        if ct.can_move(bestDir):
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
