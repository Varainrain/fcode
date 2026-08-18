"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

# If the core goes below 400 health, and sees a gunner attacking it, it will immediately send a 'recall' order in the next unused slot, where the other bots will walk back to team core, scored based on their distance to it. Synergizes well with OogwayTestExplore
# and spend up titanium to get to 50 ammo, stopping when it has 20 titanium left

from fcode import Controller, Direction, EntityType, Environment, Position

from mapPathfinding import *


GUN_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in gunnerLines}

SENT_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in sentinelLines}

class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.mapW = None
        self.mapH = None
        self.mySpots = []
        self.mySpot = None

    def runCore(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        globalAmmo = ct.get_global_ammo()
        if self.numSpawned < 1:
            spawnableTiles = []
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    spawnableTiles.append(tile)
            if spawnableTiles:
                enemyCore = Position(self.mapW - myLoc.x - 2, self.mapH - myLoc.y - 2)
                spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(enemyCore))
                closestTile = spawnableTiles[0]
                ct.spawn_builder(closestTile)
                self.numSpawned += 1
            ct.write_store(0, self.numSpawned) # used so bots know their role

        # ALARM DEFENDER (aa4c2bca game 4: the Bisons' 4-sentinel wave killed
        # our core t48 while our rush needed ~3 more turns - a pure race with
        # ZERO interference from us). If an enemy unit enters core vision,
        # spawn ONE home defender. 30 Ti of the war bank buys a gunner + core
        # heals against a 36/turn wave; the race margin flips.
        if self.numSpawned == 1:
            myTeam = ct.get_team()
            for u in ct.get_nearby_units():
                if ct.get_team(u) != myTeam:
                    if ct.get_global_resources() >= 60:
                        for tile in ct.get_nearby_tiles():
                            if ct.can_spawn(tile):
                                ct.spawn_builder(tile)
                                self.numSpawned += 1
                                ct.write_store(0, self.numSpawned)
                                break
                    break


        convertAmount = 28 - globalAmmo
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)

    def gunnerSpots(self, ct: Controller, enemyCoreTiles):
        gunnerSpots = []
        for corner in enemyCoreTiles:
            for cornerDir in DIRECTIONS:
                gunnerSpot = corner.add(cornerDir)
                if gunnerSpot not in enemyCoreTiles and gunnerSpot not in gunnerSpots:
                    gunnerSpots.append(gunnerSpot)
        return gunnerSpots

    def nearbyAllies(self, ct: Controller, myTeam, myLoc):
        nearbyAllies = []
        for bBot in ct.get_nearby_units():
            if ct.get_team(bBot) == myTeam and ct.get_entity_type(bBot) == EntityType.BUILDER_BOT:
                bPos = ct.get_position(bBot)
                if bPos != myLoc:
                    nearbyAllies.append(bPos)

    def run_defender(self, ct: Controller, myLoc) -> None:
        """Home insurance vs waves: one gunner facing the nearest threat,
        then heal the core. Costs ~50 Ti of the war bank; flips razor races
        (aa4c2bca game 4 was lost by ~3 turns with zero interference)."""
        myTeam = ct.get_team()
        threat = None
        bestD = None
        for u in ct.get_nearby_units():
            if ct.get_team(u) != myTeam:
                p = ct.get_position(u)
                d = myLoc.distance_squared(p)
                if bestD is None or d < bestD:
                    bestD, threat = d, p
        coreId = None
        haveGun = False
        for b in ct.get_nearby_buildings():
            bTeam = ct.get_team(b)
            bType = ct.get_entity_type(b)
            if bTeam == myTeam and bType == EntityType.CORE:
                coreId = b
            elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
                p = ct.get_position(b)
                d = myLoc.distance_squared(p)
                if bestD is None or d < bestD:
                    bestD, threat = d, p
            elif bTeam == myTeam and bType == EntityType.GUNNER:
                if myLoc.distance_squared(ct.get_position(b)) <= 13:
                    haveGun = True
        if not haveGun and ct.get_global_resources() >= ct.get_gunner_cost():
            aim = threat
            if aim is None and self.mapPf.enemyCorePos is not None:
                aim = self.mapPf.enemyCorePos
            if aim is not None:
                for d in CARDINALS:
                    n = myLoc.add(d)
                    if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                        continue
                    if ct.get_tile_building_id(n) is not None:
                        continue
                    fdx = (aim.x > n.x) - (aim.x < n.x)
                    fdy = (aim.y > n.y) - (aim.y < n.y)
                    for fd in DIRECTIONS:
                        if fd.delta() == (fdx, fdy):
                            if ct.can_build_gunner(n, fd):
                                ct.build_gunner(n, fd)
                                return
                            break
        if coreId is not None and ct.get_hp(coreId) < ct.get_max_hp(coreId):
            corePos = ct.get_position(coreId)
            coreTiles = [corePos, corePos.add(Direction.EAST), corePos.add(Direction.SOUTH),
                         corePos.add(Direction.SOUTH).add(Direction.EAST)]
            for tile in coreTiles:
                if myLoc.distance_squared(tile) == 1 and ct.can_heal(tile):
                    ct.heal(tile)
                    return
            self.mapPf.moveTo(ct, corePos)
            return
        if self.mapPf.teamCore is not None and myLoc.distance_squared(self.mapPf.teamCore) > 4:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)

    def run(self, ct: Controller) -> None:
        if self.mapW is None:
            self.mapH = ct.get_map_height()
            self.mapW = ct.get_map_width()

        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.mapPf.setupMap(ct)
            myLoc = ct.get_position()
            # role latch: the attack builder spawns t1; anything spawned later
            # is the ALARM DEFENDER (see runCore)
            if getattr(self, "_role", None) is None:
                self._role = "defend" if ct.get_current_round() > 6 else "attack"
            if self._role == "defend":
                self.run_defender(ct, myLoc)
                return
            enemyCore = self.mapPf.enemyCorePos
            enemyCoreTiles = [
                enemyCore, 
                enemyCore.add(Direction.EAST), 
                enemyCore.add(Direction.SOUTH),
                enemyCore.add(Direction.SOUTH).add(Direction.EAST)
            ]

            if not self.mySpots:
                self.mySpots = self.gunnerSpots(ct, enemyCoreTiles)

            mySpots = []
            for gunnerSpot in self.mySpots:
                if not ct.is_in_vision(gunnerSpot):
                    mySpots.append(gunnerSpot)
                else:
                    tileBId = ct.get_tile_building_id(gunnerSpot)
                    if tileBId is None and ct.get_tile_env(gunnerSpot) in [Environment.EMPTY]:
                        mySpots.append(gunnerSpot)
            self.mySpots = mySpots

            for gunnerSpot in mySpots:
                ct.draw_indicator_dot(gunnerSpot, 120, 240, 80) 

            if not mySpots:
                # RING FULL: no seat left to build on, so switch to keeping the
                # guns we already placed alive. Also fixes a latent crash - the
                # original indexed mySpots[0] unguarded, so a full ring killed
                # this builder with an IndexError (there are no handlers here).
                myTeam = ct.get_team()
                best, bestHp = None, None
                for u in ct.get_nearby_buildings():
                    if ct.get_team(u) != myTeam:
                        continue
                    if ct.get_entity_type(u) not in (EntityType.GUNNER, EntityType.SENTINEL):
                        continue
                    uPos = ct.get_position(u)
                    if uPos.distance_squared(myLoc) > 1 or not ct.can_heal(uPos):
                        continue
                    hp = ct.get_hp(u)
                    if hp >= ct.get_max_hp(u):
                        continue
                    if bestHp is None or hp < bestHp:
                        bestHp, best = hp, uPos
                if best is not None:
                    ct.heal(best)
                else:
                    self.mapPf.moveTo(ct, enemyCore)
                return

            if self.mySpot is not None:
                if ct.is_in_vision(self.mySpot):
                    tileBId = ct.get_tile_building_id(self.mySpot)
                    if tileBId is not None or ct.get_tile_env(self.mySpot) not in [Environment.EMPTY]:
                        self.mySpot = None
            if self.mySpot is None:
                mySpots.sort(key=lambda gunnerSpot: gunnerSpot.distance_squared(myLoc))
                closestSpot = mySpots[0]
                self.mySpot = closestSpot 

            ct.draw_indicator_line(myLoc, self.mySpot, 40, 120, 200) 
            myDir = self.mySpot.direction_to(enemyCore)

            # only commit a seat when we can actually afford to keep going
            if ct.get_global_resources() > 100 and ct.can_build_gunner(self.mySpot, myDir):
                ct.build_gunner(self.mySpot, myDir)
            
            if myLoc.distance_squared(self.mySpot) > 1:
                self.mapPf.moveTo(ct, self.mySpot)
                ct.draw_indicator_dot(self.mySpot, 200, 60, 110) 

        elif etype == EntityType.GUNNER:
            curTarget = ct.get_gunner_target()
            # get_gunner_target() is None when the engine has no auto-target;
            # can_fire(None) raises TypeError and forfeits the turn (seen as a
            # crash-loop in the fjordgate mirror smoke).
            if curTarget is not None and ct.can_fire(curTarget):
                ct.fire(curTarget)