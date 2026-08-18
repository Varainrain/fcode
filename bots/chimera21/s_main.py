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
                # KICKED MARCH (aa4c2bca game 4: lost the icefloe race by ~3
                # turns): mid-walk, drop a launcher one step behind and stand
                # still one turn - it throws us ~5 tiles toward the ring. Each
                # kick nets ~3 turns; two kicks flip a t33-vs-t48 race. 20 Ti
                # per kick from a 470-Ti bank that only needs ~150 for gunners.
                wait = getattr(self, "_kick_wait", 0)
                if wait > 0:
                    self._kick_wait = wait - 1
                    return          # stand still - the launcher throws us
                kicks = getattr(self, "_kicks", 0)
                if (kicks < 2 and myLoc.distance_squared(self.mySpot) > 36
                        and ct.get_global_resources() >= ct.get_launcher_cost() + 140):
                    bdx = (myLoc.x > self.mySpot.x) - (myLoc.x < self.mySpot.x)
                    bdy = (myLoc.y > self.mySpot.y) - (myLoc.y < self.mySpot.y)
                    for back in (Position(myLoc.x + bdx, myLoc.y),
                                 Position(myLoc.x, myLoc.y + bdy)):
                        if back == myLoc:
                            continue
                        if not (0 <= back.x < self.mapW and 0 <= back.y < self.mapH):
                            continue
                        if ct.get_tile_building_id(back) is None and ct.can_build_launcher(back):
                            ct.build_launcher(back)
                            self._kicks = kicks + 1
                            self._kick_wait = 2   # launcher acts next turns
                            return
                self.mapPf.moveTo(ct, self.mySpot)
                ct.draw_indicator_dot(self.mySpot, 200, 60, 110)

        elif etype == EntityType.LAUNCHER:
            # kick engine: throw the adjacent own builder as far toward the
            # enemy core as a legal landing allows; throws are free
            myLoc = ct.get_position()
            self.mapPf.setupMap(ct)
            foe = self.mapPf.enemyCorePos
            if foe is None and self.mapW:
                foe = Position(self.mapW - myLoc.x - 2, self.mapH - myLoc.y - 2)
            if foe is None:
                return
            myTeam = ct.get_team()
            rider = None
            for u in ct.get_nearby_units():
                if (ct.get_team(u) == myTeam
                        and ct.get_entity_type(u) == EntityType.BUILDER_BOT):
                    p = ct.get_position(u)
                    if p.distance_squared(myLoc) <= 2:
                        rider = p
                        break
            if rider is None:
                return
            cands = []
            for dx in range(-5, 6):
                for dy in range(-5, 6):
                    if dx * dx + dy * dy > 26 or (dx == 0 and dy == 0):
                        continue
                    t = Position(myLoc.x + dx, myLoc.y + dy)
                    if 0 <= t.x < self.mapW and 0 <= t.y < self.mapH:
                        cands.append(t)
            cands.sort(key=lambda t: t.distance_squared(foe))
            for t in cands[:15]:
                if ct.can_launch(rider, t):
                    ct.launch(rider, t)
                    return

        elif etype == EntityType.GUNNER:
            curTarget = ct.get_gunner_target()
            # get_gunner_target() is None when the engine has no auto-target;
            # can_fire(None) raises TypeError and forfeits the turn (seen as a
            # crash-loop in the fjordgate mirror smoke).
            if curTarget is not None and ct.can_fire(curTarget):
                ct.fire(curTarget)