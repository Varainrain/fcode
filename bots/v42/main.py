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
        self.routeTarget = None
        self.routeBestDistance = None
        self.routeLastProgressRound = 0
        self.knownConnectedConveyors = {}
        self.visitedCenter = False

    def distToCore(self, ct: Controller, pos: Position):
        myLoc = ct.get_position()
        tL = myLoc
        tR = myLoc.add(Direction.EAST)
        bL = myLoc.add(Direction.SOUTH)
        bR = myLoc.add(Direction.SOUTH).add(Direction.EAST)
        coreCorners = [tL, tR, bR, bL]
        coreCorners.sort(key=lambda coreCorner: coreCorner.distance_squared(pos))
        return coreCorners[0].distance_squared(pos)

    def runCore(self, ct: Controller) -> None:
        myLoc = ct.get_position()

        nearbyOres = []
        for tile in ct.get_nearby_tiles():
            if ct.get_tile_env(tile) == Environment.ORE_TITANIUM:
                nearbyOres.append(tile)
        nearbyOres.sort(key=lambda ore: self.distToCore(ct, ore))

        globalAmmo = ct.get_global_ammo()
        globalTitanium = ct.get_global_resources()

        if self.numSpawned < 4 or globalTitanium > 360:
            spawnableTiles = []
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    spawnableTiles.append(tile)
            if spawnableTiles:
                mapCenter = Position(self.mapW // 2, self.mapH // 2)
                if self.numSpawned % 2 == 0: # attacking bots
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(mapCenter))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
                elif self.numSpawned % 2 == 1: # eco/defense bot
                    sortTarget = nearbyOres[0] if nearbyOres else mapCenter
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(sortTarget))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
            ct.write_store(0, self.numSpawned) # used so bots know their roles
        ct.write_store(7, myLoc.x * 32 + myLoc.y)
        # sentinel siege drinks 10 ammo/shot every 2 rounds; the old 16
        # ceiling starves a single firing sentinel, let alone two
        convertAmount = min(60 - globalAmmo, globalTitanium - 28)
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)
        
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
        self.mapPf.setupMap(ct)
        self.setupDefendClamp(ct)
        if self.mapPf.myNum % 2 == 1: # attacking
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
        if self.mapPf.myNum != 4 and self.mapPf.myNum != 6:
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

    def runAttack(self, ct: Controller):
        myLoc = ct.get_position()
        if self.mapPf.enemyCorePos is None:
            mapCenter = Position(self.mapW // 2, self.mapH // 2)
            if not self.visitedCenter:
                if ct.get_current_round() > 20 or myLoc.distance_squared(mapCenter) < 12:
                    self.visitedCenter = True
                else:
                    self.mapPf.moveTo(ct, mapCenter)
                    return
            candidates = list(self.mapPf.allEnemyCore.values())
            if candidates:
                target = candidates[(self.mapPf.myNum // 2) % len(candidates)]
                self.mapPf.moveTo(ct, target)
            else:
                corners = [Position(1, 1), Position(self.mapW - 2, 1),
                           Position(1, self.mapH - 2), Position(self.mapW - 2, self.mapH - 2)]
                target = corners[(self.mapPf.myNum // 2) % len(corners)]
                self.mapPf.moveTo(ct, target)
            return
        else:
            # THE SENTINEL SWITCH (2.3.4 meta: every team above us runs
            # sentinel siege, zero-to-few gunners). Two measured failures
            # shaped this: v31s searched seats vision-wide and STALLED
            # (10%); v32p planted naked sentinels that enemy gunners
            # walked around and killed (36%) — Pantheon's survive because
            # BARRIERS shield them. So: deterministic diagonal seats
            # (k=4/3 from a core corner = range^2 32/18, outside gunner
            # reach), then the SAME builder flanks its sentinel with two
            # barriers before rejoining normal play. Gunners stay as the
            # fallback/support weapon, not the siege weapon.
            if ct.get_global_resources() >= 40:
                if self.shieldedSentinel(ct, myLoc):
                    return
            if ct.get_global_resources() >= 84:
                gunnerStuff = self.findGunnerSpot(ct)
                if gunnerStuff:
                    gunnerSpot, gunnerDir = gunnerStuff
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)
                        return
                    myDist = myLoc.distance_squared(gunnerSpot)
                    if myDist < 1:
                        self.mapPf.moveTo(ct, self.mapPf.teamCore)
                    elif myDist > 1:
                        self.mapPf.moveTo(ct, gunnerSpot)
                    return
            # Can't place any more (no open seat or below titanium threshold):
            # divert to heal a damaged team gunner before marching on.
            if self.healTeamGunners(ct):
                return
            self.mapPf.moveTo(ct, self.mapPf.enemyCorePos)

    def shieldedSentinel(self, ct, myLoc) -> bool:
        """Plant one sentinel on the nearest free diagonal standoff seat,
        then two flank barriers beside it. Deterministic seats, hard caps,
        instant fall-through — the two known failure modes (seat-hunt
        stall, naked sentinel) are both structural non-options here.
        Returns True if the turn was used."""
        # phase 2: flank the sentinel I already planted
        if getattr(self, "_mySent", None) is not None:
            if getattr(self, "_flanked", 0) >= 2:
                return False
            sp = self._mySent
            enemyCore = self.mapPf.enemyCorePos
            flanks = []
            if enemyCore is not None:
                dx = 1 if enemyCore.x >= sp.x else -1
                dy = 1 if enemyCore.y >= sp.y else -1
                # the two tiles between the sentinel and the enemy approach
                flanks = [Position(sp.x + dx, sp.y), Position(sp.x, sp.y + dy)]
            for fl in flanks:
                if not (0 <= fl.x < self.mapW and 0 <= fl.y < self.mapH):
                    continue
                try:
                    if not ct.is_in_vision(fl):
                        continue
                    if ct.get_tile_building_id(fl) is not None:
                        continue
                    if ct.get_tile_env(fl) != Environment.EMPTY:
                        continue
                except Exception:
                    continue
                d = abs(myLoc.x - fl.x) + abs(myLoc.y - fl.y)
                if d == 1:
                    if ct.can_act() and ct.can_build_barrier(fl):
                        ct.build_barrier(fl)
                        self._flanked = getattr(self, "_flanked", 0) + 1
                        return True
                    return False
                if d <= 4 and ct.get_move_cooldown() == 0:
                    self.mapPf.moveTo(ct, fl)
                    return True
            self._flanked = 2              # nothing flankable: move on
            return False
        # phase 1: plant the sentinel on a deterministic diagonal seat
        if getattr(self, "_sentGaveUp", False):
            return False
        enemyCore = self.mapPf.enemyCorePos
        if enemyCore is None:
            return False
        corners = [enemyCore, enemyCore.add(Direction.EAST),
                   enemyCore.add(Direction.SOUTH),
                   enemyCore.add(Direction.SOUTH).add(Direction.EAST)]
        cands = []
        for c in corners:
            for sx in (-1, 1):
                for sy in (-1, 1):
                    for k in (4, 3):
                        p2 = Position(c.x + sx * k, c.y + sy * k)
                        if 0 <= p2.x < self.mapW and 0 <= p2.y < self.mapH:
                            cands.append((k, p2, c))
        cands.sort(key=lambda t: (-t[0], myLoc.distance_squared(t[1])))
        tries = 0
        for k, seat, corner in cands:
            if ct.is_in_vision(seat):
                try:
                    if ct.get_tile_building_id(seat) is not None:
                        continue
                    if ct.get_tile_env(seat) != Environment.EMPTY:
                        continue
                except Exception:
                    continue
            tries += 1
            if tries > 3:
                break
            d2 = myLoc.distance_squared(seat)
            if d2 <= 2:
                face = None
                for f in DIRECTIONS:
                    try:
                        if ct.can_fire_from(seat, f, EntityType.SENTINEL, corner):
                            face = f
                            break
                    except Exception:
                        continue
                if face is None:
                    continue
                if ct.can_build_sentinel(seat, face):
                    ct.build_sentinel(seat, face)
                    self._mySent = seat
                    return True
                self._sentGaveUp = True    # seat contested: gunner play
                return False
            if d2 <= 200:
                self.mapPf.moveTo(ct, seat)
                return True
            break
        self._sentGaveUp = True
        return False

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
                        if tType == EntityType.SENTINEL:
                            v7 = ct.read_store(7)
                            if v7:
                                _cx, _cy = v7 // 32, v7 % 32
                                if abs(tile.x - _cx) + abs(tile.y - _cy) <= 7:
                                    coreThreatHits += 1
                        elif (tile.x, tile.y, ct.get_direction(tileId)) in threatSpots:
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

    def cornerShields(self, ct: Controller) -> bool:
        """SENTINEL-LINE SEAL (from v33/v34, ic3d's observation; v36 shipped
        without it and the 2-3-vs-Pantheon result came FROM it). Every
        sentinel line into the core passes either the diagonal corner tile
        (diagonal lines) or a cardinal lane tile at distance 2 (straight
        lines). 12 barriers, 36 Ti, mirror-free (51%/49% measured). The d1
        ring stays open for spawns and heals; own barriers are passable.
        fjord fix: approach shield tiles even when OUT of vision — the old
        is_in_vision gate meant a tile nobody stood near never got built."""
        core = None
        v = ct.read_store(7)
        if v:
            core = Position(v // 32, v % 32)
        if core is None:
            return False
        myLoc = ct.get_position()
        if abs(myLoc.x - core.x) + abs(myLoc.y - core.y) > 8:
            return False
        if ct.get_global_resources() < 25:
            return False
        # TRIAGE (sporks autopsy: our core healing was ZERO in 4 of 10
        # games because this shield loop preempts the heal logic in
        # runDefend, and under sustained fire the shields always need
        # work — armor on a corpse. When the core is actually hurt, the
        # defender's turn belongs to healing: sporks out-heal us 592-0
        # in games we lost with MORE damage dealt.)
        try:
            cid = ct.get_tile_building_id(core)
            if cid is not None and ct.get_hp(cid) < 350:
                return False
        except Exception:
            pass
        shields = [Position(core.x - 1, core.y - 1),
                   Position(core.x + 2, core.y - 1),
                   Position(core.x - 1, core.y + 2),
                   Position(core.x + 2, core.y + 2),
                   Position(core.x,     core.y - 2),
                   Position(core.x + 1, core.y - 2),
                   Position(core.x,     core.y + 3),
                   Position(core.x + 1, core.y + 3),
                   Position(core.x - 2, core.y),
                   Position(core.x - 2, core.y + 1),
                   Position(core.x + 3, core.y),
                   Position(core.x + 3, core.y + 1)]
        for sp in shields:
            if not (0 <= sp.x < self.mapW and 0 <= sp.y < self.mapH):
                continue
            seen = False
            try:
                seen = ct.is_in_vision(sp)
                if seen:
                    if ct.get_tile_building_id(sp) is not None:
                        continue
                    if ct.get_tile_env(sp) != Environment.EMPTY:
                        continue
            except Exception:
                continue
            d = abs(myLoc.x - sp.x) + abs(myLoc.y - sp.y)
            if d == 1:
                if ct.can_act() and ct.can_build_barrier(sp):
                    ct.build_barrier(sp)
                    return True
                if seen:
                    continue
                return False
            if d <= 5 and ct.get_move_cooldown() == 0:
                self.mapPf.moveTo(ct, sp)
                return True
        return False

    def runDefend(self, ct: Controller):
        if self.cornerShields(ct):
            return
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        # HEAL-FIRST DEFENSE (the second heal-zero bug, 9d28da39 g2: we
        # dealt 693, they dealt 504 — and healed 686 to our 0, off passive
        # income, and won). The old flow only reached healCore when NO
        # uncovered enemy turret was visible — i.e. never during a siege.
        # A heal is 4hp for 1 Ti; a counter-gunner is 20+ Ti and dies in
        # two sentinel hits. When the core is bleeding, heal IS defense.
        # v41's all-heal lock regressed (42%): both defenders nursed a
        # scratched core forever while the siege turret kept firing.
        # sporks heals AND fights. Split: ONE defender claims the healer
        # role per turn (slot 14 = claim round, self-expiring), the rest
        # keep counter-turret play.
        tc = self.mapPf.teamCore
        if tc is not None:
            try:
                cid = ct.get_tile_building_id(tc)
                rnd = ct.get_current_round()
                claim = ct.read_store(14)
                if cid is not None and ct.get_hp(cid) < 480:
                    if claim < rnd:            # unclaimed this round: mine
                        ct.write_store(14, rnd + 1)
                        self.healCore(ct)
                        return
                    # someone else heals; I fight on below
            except Exception:
                pass
        covered = self.coveredTiles(ct)
        enemyGunners = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam and ct.get_entity_type(b) in (EntityType.GUNNER, EntityType.SENTINEL):
                enemyGunners.append(ct.get_position(b))
        uncovered = [g for g in enemyGunners if (g.x, g.y) not in covered]
        if uncovered:
            uncovered.sort(key=lambda g: g.distance_squared(myLoc))
            target = uncovered[0]
            if self.buildGunnerFor(ct, target):
                return
            self.mapPf.moveTo(ct, target)
            return
        self.healCore(ct)

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
                if ct.get_tile_building_id(tile) is not None:
                    continue
                fallback.append(tile)
                if (tile.x, tile.y) not in covered: # never block a team gunner line
                    candidates.append(tile)
        if self.mapPf.myNum == 4:
            candidates.sort(key=lambda tile: tile.distance_squared(center)) # 4th bot: closest to center
            fallback.sort(key=lambda tile: tile.distance_squared(center))
        else:
            candidates.sort(key=lambda tile: tile.distance_squared(center), reverse=True) # 6th bot: farthest
            fallback.sort(key=lambda tile: tile.distance_squared(center), reverse=True)
        if candidates:
            self.defendHome = candidates[0]
        elif fallback:
            self.defendHome = fallback[0]
        return self.defendHome

    def healCore(self, ct: Controller, home=None):
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
        if home is None:
            home = self.getDefendHome(ct)
        if home is not None and myLoc != home:
            self.mapPf.moveTo(ct, home)

    def buildGunnerFor(self, ct: Controller, target: Position) -> bool:
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        for d in CARDINALS:
            spot = myLoc.add(d)
            dist = target.distance_squared(spot)
            if dist < 10 and dist != 5 and 0 <= spot.x < self.mapW and 0 <= spot.y < self.mapH:
                if ct.get_tile_building_id(spot) is None:
                    gunnerDir = spot.direction_to(target)
                    if self.rayBlockedByTeam(ct, spot, target, gunnerDir, myTeam):
                        continue
                    if ct.can_build_gunner(spot, gunnerDir):
                        ct.build_gunner(spot, gunnerDir)
                        return True
        for d in CARDINALS: # try destroying a team barrier in the way
            spot = myLoc.add(d)
            dist = target.distance_squared(spot)
            if dist < 10 and dist != 5 and 0 <= spot.x < self.mapW and 0 <= spot.y < self.mapH:
                spotId = ct.get_tile_building_id(spot)
                if spotId is not None:
                    if ct.get_team(spotId) == myTeam and ct.get_entity_type(spotId) == EntityType.BARRIER:
                        if ct.can_destroy(spot):
                            ct.destroy(spot)
                            return True
        return False

    def healDamagedNonCore(self, ct: Controller) -> bool:
        """Walk to and repair the nearest damaged friendly non-core building.
        Unlike healAttackedNonCore, no enemy line-of-fire requirement - any
        damaged conveyor/harvester/barrier/turret qualifies. Returns False
        when no such tile is visible, so the caller can continue with
        routing/harvesting."""
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        best = None
        bestKey = None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType == EntityType.CORE:
                continue
            if bType not in (EntityType.GUNNER, EntityType.SENTINEL,
                              EntityType.BARRIER, EntityType.CONVEYOR,
                              EntityType.HARVESTER):
                continue
            if ct.get_hp(b) >= ct.get_max_hp(b):
                continue
            bPos = ct.get_position(b)
            key = myLoc.distance_squared(bPos)
            if bestKey is None or key < bestKey:
                bestKey = key
                best = bPos
        if best is None:
            return False
        if myLoc.distance_squared(best) == 1 and ct.can_heal(best):
            ct.heal(best)
            return True
        self.mapPf.moveTo(ct, best)
        return True

    def healTeamGunners(self, ct: Controller) -> bool:
        """Walk to and repair the most damaged friendly gunner/sentinel in
        vision. Used by attack bots when they cannot place any more turrets
        (no open seat, or titanium below threshold). Returns False when no
        visible damaged friendly turret exists, so the caller can fall back
        to its default action."""
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
        if myLoc.distance_squared(best) == 1 and ct.can_heal(best):
            ct.heal(best)
            return True
        self.mapPf.moveTo(ct, best)
        return True

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

    def runEco(self, ct: Controller):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        covered = self.coveredTiles(ct)
        enemyGunners = []
        visibleDamagedCore = False
        for b in ct.get_nearby_buildings():
            bTeam = ct.get_team(b)
            bType = ct.get_entity_type(b)
            if bTeam == myTeam and bType == EntityType.CORE:
                visibleDamagedCore = ct.get_hp(b) < ct.get_max_hp(b)
            elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
                enemyGunners.append(ct.get_position(b))
        uncovered = [g for g in enemyGunners if (g.x, g.y) not in covered]
        if uncovered:
            uncovered.sort(key=lambda g: g.distance_squared(myLoc))
            target = uncovered[0]
            if self.buildGunnerFor(ct, target):
                return
            self.mapPf.moveTo(ct, target)
            return
        if visibleDamagedCore: # heal the core whenever it is damaged, even with no enemy gunners in sight
            self.healCore(ct, home=self.mapPf.teamCore)
            return
        if self.healDamagedNonCore(ct):
            return
        if self.repairFormerlyConnectedTrunk(ct, myLoc, myTeam):
            return
        if self.resumeCommittedRoute(ct):
            return
        if self.routeConveyorTask(ct, myLoc, myTeam):
            return
        if self.routeHarvesterTask(ct, myLoc, myTeam):
            return
        if self.harvestTask(ct, myLoc, myTeam):
            return
        if self.mapPf.teamCore is not None:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)

    def observeConnectedConveyors(self, ct: Controller, myTeam):
        convDirs, convLoop = self.mapPf.classifyConveyors(ct, myTeam)
        for key, data in convDirs.items():
            if not convLoop.get(key, False):
                self.knownConnectedConveyors[key] = (data[0], data[1])
        return convDirs, convLoop

    def repairCandidate(self, ct: Controller, myLoc, myTeam, convDirs, convLoop):
        """Return one exact destroyed edge from a formerly draining trunk.

        A missing edge is useful only when it still has a live producer on its
        upstream side and its output joins a currently proven suffix. This
        excludes abandoned branches and the broad long-route behavior that
        already lost its economy gate.
        """
        core = self.mapPf.teamCore
        coreTiles = {
            core, core.add(Direction.EAST), core.add(Direction.SOUTH),
            core.add(Direction.SOUTH).add(Direction.EAST),
        }
        candidates = []
        for key, (pos, direction) in self.knownConnectedConveyors.items():
            if key in convDirs or not ct.is_in_vision(pos):
                continue
            if ct.get_tile_building_id(pos) is not None:
                continue
            output = pos.add(direction)
            outputKey = output.x * 32 + output.y
            downstreamLive = output in coreTiles or (
                outputKey in convDirs and not convLoop.get(outputKey, False))
            if not downstreamLive:
                continue

            upstreamCount = 0
            loadedUpstream = 0
            for data in convDirs.values():
                if data[0].add(data[1]) == pos:
                    upstreamCount += 1
                    loadedUpstream += 1 if data[2] else 0
            for d in CARDINALS:
                source = pos.add(d)
                if not (0 <= source.x < self.mapW and 0 <= source.y < self.mapH):
                    continue
                if not ct.is_in_vision(source):
                    continue
                sourceId = ct.get_tile_building_id(source)
                if (sourceId is not None and ct.get_team(sourceId) == myTeam and
                        ct.get_entity_type(sourceId) == EntityType.HARVESTER):
                    upstreamCount += 1
            if upstreamCount == 0:
                continue
            score = (-loadedUpstream, -upstreamCount,
                     myLoc.distance_squared(pos), coreFootprintManhattan(pos, core), key)
            candidates.append((score, pos, direction))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1], candidates[0][2]

    def repairFormerlyConnectedTrunk(self, ct: Controller, myLoc, myTeam) -> bool:
        if self.mapPf.teamCore is None:
            return False
        convDirs, convLoop = self.observeConnectedConveyors(ct, myTeam)
        candidate = self.repairCandidate(ct, myLoc, myTeam, convDirs, convLoop)
        if candidate is None:
            return False
        target, direction = candidate
        # Never walk, reserve a role, or publish a claim for repair. Rebuild the
        # exact productive edge only when this builder can do it immediately;
        # otherwise normal routing/economy continues unchanged this turn.
        if ct.can_build_conveyor(target, direction):
            ct.build_conveyor(target, direction)
            self.knownConnectedConveyors[target.x * 32 + target.y] = (
                target, direction)
            return True
        return False

    def clearCommittedRoute(self):
        self.routeTarget = None
        self.routeBestDistance = None
        self.routeLastProgressRound = 0

    def commitRoute(self, ct: Controller, target: Position) -> bool:
        if coreFootprintManhattan(target, self.mapPf.teamCore) > ROUTE_COMMIT_MAX_LINKS:
            self.mapPf.routeConveyor(ct, target)
            return True
        self.routeTarget = target
        self.routeBestDistance = None
        self.routeLastProgressRound = ct.get_current_round()
        return self.resumeCommittedRoute(ct)

    def resumeCommittedRoute(self, ct: Controller) -> bool:
        """Resume an interrupted conveyor head until it drains or truly stalls."""
        if self.routeTarget is None or self.mapPf.teamCore is None:
            return False
        core = self.mapPf.teamCore
        coreTiles = {
            core, core.add(Direction.EAST), core.add(Direction.SOUTH),
            core.add(Direction.SOUTH).add(Direction.EAST),
        }
        myTeam = ct.get_team()
        currentRound = ct.get_current_round()

        # Walk through an already-built visible suffix immediately. This keeps
        # the commitment at the first missing link instead of camping on an
        # earlier conveyor after combat or healing interrupted the route.
        for _ in range(self.mapW + self.mapH):
            target = self.routeTarget
            if not (0 <= target.x < self.mapW and 0 <= target.y < self.mapH):
                self.clearCommittedRoute()
                return False
            if target in coreTiles:
                self.clearCommittedRoute()
                return False
            if not ct.is_in_vision(target):
                break
            targetId = ct.get_tile_building_id(target)
            if targetId is None:
                break
            if ct.get_team(targetId) == myTeam:
                if ct.get_entity_type(targetId) == EntityType.CONVEYOR:
                    self.routeTarget = target.add(ct.get_direction(targetId))
                    self.routeBestDistance = None
                    self.routeLastProgressRound = currentRound
                    continue
                if ct.get_entity_type(targetId) in (EntityType.BARRIER, EntityType.GUNNER):
                    # our own blocker at the frontier - hand off to routeConveyor
                    # below, which already knows how to destroy it and rebuild
                    break
            self.clearCommittedRoute()
            return False

        target = self.routeTarget
        myLoc = ct.get_position()
        distance = myLoc.distance_squared(target)
        if self.routeBestDistance is None or distance < self.routeBestDistance:
            self.routeBestDistance = distance
            self.routeLastProgressRound = currentRound
        elif currentRound - self.routeLastProgressRound >= ROUTE_STALL_ROUNDS:
            self.clearCommittedRoute()
            return False

        if not ct.is_in_vision(target):
            self.mapPf.moveTo(ct, target)
            return True

        self.mapPf.routeConveyor(ct, target)
        # routeConveyor may move us while trying to obtain a legal build stand.
        # Re-check vision before querying the old head after that move.
        if not ct.is_in_vision(target):
            return True
        targetId = ct.get_tile_building_id(target)
        if (targetId is not None and ct.get_team(targetId) == myTeam and
                ct.get_entity_type(targetId) == EntityType.CONVEYOR):
            self.routeTarget = target.add(ct.get_direction(targetId))
            self.routeBestDistance = None
            self.routeLastProgressRound = currentRound
        return True

    def routeConveyorTask(self, ct: Controller, myLoc, myTeam) -> bool:
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return False
        bestScore, bestEnd = 0, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.CONVEYOR:
                continue
            bPos = ct.get_position(b)
            endTile = bPos.add(ct.get_direction(b))
            if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile) and self.mapPf.inMoveZone(endTile):
                if ct.get_tile_building_id(endTile) is None:
                    bScore = max(2, 6 * max(0, (1 - endTile.distance_squared(teamCore) / 120)) * max(0, (1 - myLoc.distance_squared(bPos) / 40)))
                    if bScore > bestScore:
                        bestScore = bScore
                        bestEnd = endTile
        if bestEnd is not None:
            return self.commitRoute(ct, bestEnd)
        return False

    def routeHarvesterTask(self, ct: Controller, myLoc, myTeam) -> bool:
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return False
        bestScore, bestEnd = 0, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.HARVESTER:
                continue
            bPos = ct.get_position(b)
            if myLoc.distance_squared(bPos) >= 16:
                continue
            noTeamConv = True
            workingSpots = []
            for possibleDir in CARDINALS:
                endTile = bPos.add(possibleDir)
                if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and ct.is_tile_passable(endTile) and self.mapPf.inMoveZone(endTile):
                    eId = ct.get_tile_building_id(endTile)
                    if eId is None:
                        workingSpots.append(endTile)
                    elif ct.get_team(eId) == myTeam and ct.get_entity_type(eId) == EntityType.CONVEYOR:
                        noTeamConv = False
            if noTeamConv and len(workingSpots) > 0:
                workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                bScore = max(1.6, 5 * max(0, (1 - workingSpots[0].distance_squared(teamCore) / 100)) * max(0, (1 - myLoc.distance_squared(bPos) / 60)))
                if bScore > bestScore:
                    bestScore = bScore
                    bestEnd = workingSpots[0]
        if bestEnd is not None:
            return self.commitRoute(ct, bestEnd)
        return False

    def harvestTask(self, ct: Controller, myLoc, myTeam) -> bool:
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return False
        enemyThreatened = self.mapPf.enemyTurretThreatenedTiles(ct)
        bestScore, bestTile = 0, None
        # scan the whole shared map, not just what's currently in this bot's own vision -
        # otherwise ore another bot broadcast over the store slots is never actually visited
        for x in range(self.mapW):
            for y in range(self.mapH):
                if self.mapPf.fullMap[x][y] != 1:
                    continue
                tile = Position(x, y)
                if not self.mapPf.inMoveZone(tile):
                    continue
                if ct.is_in_vision(tile) and ct.get_tile_building_id(tile) is not None:
                    continue
                if (x, y) in enemyThreatened:
                    continue
                dist = teamCore.distance_squared(tile)
                tileScore = max(1.2, 3 * (1 - dist / 160) * (1 - myLoc.distance_squared(tile) / 220))
                if tileScore > bestScore and ct.get_global_resources() > dist / 7:
                    bestScore = tileScore
                    bestTile = tile
        if bestTile is None:
            return False
        if ct.can_build_harvester(bestTile):
            ct.build_harvester(bestTile)
            return True
        if bestTile.distance_squared(myLoc) > 1:
            self.mapPf.moveTo(ct, bestTile)
        elif bestTile.distance_squared(myLoc) < 1:
            self.mapPf.moveTo(ct, teamCore)
        return True
    
