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


        # STALL FIX (6d1a77f5 game 1: Flotte's home gunner shot our lone
        # builder ~t20 and the bot did NOTHING for 110 turns). The attack
        # builder heartbeats slot 8 every turn; when the stamp goes stale
        # the core spawns a replacement from the war bank.
        if self.numSpawned >= 1:
            hb = ct.read_store(8)
            curRound = ct.get_current_round()
            if hb > 0 and curRound - (hb - 1) > 6 and ct.get_global_resources() >= 90:
                for tile in ct.get_nearby_tiles():
                    if ct.can_spawn(tile):
                        ct.spawn_builder(tile)
                        self.numSpawned += 1
                        ct.write_store(0, self.numSpawned)
                        ct.write_store(8, curRound + 1)   # restart staleness clock
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
            ct.write_store(8, ct.get_current_round() + 1)   # heartbeat (stall fix)
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
                    if (tileBId is None
                            and ct.get_tile_builder_bot_id(gunnerSpot) is None
                            and ct.get_tile_env(gunnerSpot) in [Environment.EMPTY]):
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
                    # squatter fix (see lk_main): bots on the seat drop the claim
                    if (tileBId is not None
                            or ct.get_tile_builder_bot_id(self.mySpot) is not None
                            or ct.get_tile_env(self.mySpot) not in [Environment.EMPTY]):
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
                return
            # SELF-DEFENSE (8cdcc379 g3, user-found): a builder chewing us
            # from off-facing is invisible to auto-target. TARGETLESS ONLY -
            # a firing gunner never stops shelling (jav1 gated 39% when hurt
            # gunners rotated mid-race: races are offense-bound, again).
            if curTarget is None and ct.get_hp() < ct.get_max_hp():
                gLoc = ct.get_position()
                gTeam = ct.get_team()
                gDir = ct.get_direction()
                for d in CARDINALS:
                    n = gLoc.add(d)
                    bb = ct.get_tile_builder_bot_id(n)
                    if bb is not None and ct.get_team(bb) != gTeam:
                        for fd in DIRECTIONS:
                            if fd.delta() == (n.x - gLoc.x, n.y - gLoc.y):
                                if fd != gDir and ct.can_rotate(fd):
                                    ct.rotate(fd)
                                break
                        return