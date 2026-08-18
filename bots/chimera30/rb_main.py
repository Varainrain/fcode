"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""



# Two things to try out 
# 1) try adding a gate for gunner placement (globalAmmo > 0, or globalTi > 50)
# 2) make healing more often 

from fcode import Controller, Direction, EntityType, Environment, Position

from rb_mapPathfinding import *


GUN_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in gunnerLines}

SENT_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in sentinelLines}

SEAT_SWITCH = 3   # path-cost gap needed before abandoning a claimed seat


class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.mapW = None
        self.mapH = None
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


        convertAmount = 20 - globalAmmo
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)

    def threatenedTiles(self, ct: Controller, myTeam):
        """Empty tiles an enemy gunner would hit if we built there.

        A gunner's shot is eaten by the FIRST non-empty tile, so only the empty
        run in front of it is dangerous - anything behind a blocker is safe.
        Walking GUN_RAY per enemy gunner gives exactly that run.
        """
        bad = set()
        for b in ct.get_nearby_buildings():
            try:
                if ct.get_team(b) == myTeam or ct.get_entity_type(b) != EntityType.GUNNER:
                    continue
                ePos = ct.get_position(b)
                eDir = ct.get_direction(b)
            except Exception:
                continue
            ray = GUN_RAY.get(eDir)
            if ray is None:
                continue
            dx, dy, maxK = ray
            x, y = ePos.x, ePos.y
            for _k in range(1, maxK + 1):
                x += dx
                y += dy
                if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                    break
                t = Position(x, y)
                if not ct.is_in_vision(t):
                    bad.add((x, y))          # unknown - assume covered
                    continue
                try:
                    if ct.get_tile_env(t) == Environment.WALL:
                        break                # wall eats the shot
                    if ct.get_tile_building_id(t) is not None or \
                            ct.get_tile_builder_bot_id(t) is not None:
                        break                # something already absorbs it
                except Exception:
                    break
                bad.add((x, y))              # empty and in the line of fire
        return bad

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
            myTeam = ct.get_team()
            enemyCore = self.mapPf.enemyCorePos
            globalAmmo = ct.get_global_ammo()
            enemyCoreTiles = [
                enemyCore, 
                enemyCore.add(Direction.EAST), 
                enemyCore.add(Direction.SOUTH),
                enemyCore.add(Direction.SOUTH).add(Direction.EAST)
            ]

            # (2) never seat a gunner where an enemy gunner is already aimed -
            # it dies before it earns its 20 titanium back.
            threatened = self.threatenedTiles(ct, myTeam)

            mySpots = []
            for gunnerSpot in self.gunnerSpots(ct, enemyCoreTiles):
                if myLoc != gunnerSpot and (gunnerSpot.x, gunnerSpot.y) not in threatened:
                    if not ct.is_in_vision(gunnerSpot):
                        mySpots.append(gunnerSpot)
                    else:
                        tileBId = ct.get_tile_building_id(gunnerSpot)
                        tileBBId = ct.get_tile_builder_bot_id(gunnerSpot)
                        if tileBBId is None and tileBId is None and ct.get_tile_env(gunnerSpot) in [Environment.EMPTY]:
                            mySpots.append(gunnerSpot)
                            ct.draw_indicator_line(myLoc, gunnerSpot, 240, 120, 200) # pink

            # drop the claim if the seat got taken, or is now under fire
            if self.mySpot is not None:
                if (self.mySpot.x, self.mySpot.y) in threatened:
                    self.mySpot = None
                elif ct.is_in_vision(self.mySpot):
                    tileBId = ct.get_tile_building_id(self.mySpot)
                    if tileBId is not None or ct.get_tile_env(self.mySpot) not in [Environment.EMPTY]:
                        ct.draw_indicator_line(myLoc, self.mySpot, 40, 160, 100) # teal
                        self.mySpot = None

            # (1) SEMI-DYNAMIC SEAT: rank seats by PATH cost, not straight line.
            # A seat 3 tiles away through a wall is worse than one 6 tiles away
            # down a corridor, and claim-once-and-forget could leave the builder
            # walking at a seat that became far or unreachable. fillInDistTable
            # from our own position gives real path cost to every seat in ONE
            # fill; SEAT_SWITCH is hysteresis so it cannot thrash between two
            # seats of near-equal cost and never arrive.
            if mySpots:
                self.mapPf.fillInDistTable(ct, myLoc)
                dm, ds, fc = self.mapPf.distMap, self.mapPf.distStamp, self.mapPf.fillCount

                def pathCost(sp):
                    if ds[sp.x][sp.y] == fc:
                        return dm[sp.x][sp.y]
                    return 4096            # unreachable as far as we know

                mySpots.sort(key=lambda sp: (pathCost(sp), sp.distance_squared(myLoc)))
                best = mySpots[0]
                if self.mySpot is None:
                    self.mySpot = best
                elif best != self.mySpot:
                    if pathCost(self.mySpot) - pathCost(best) >= SEAT_SWITCH:
                        self.mySpot = best     # meaningfully closer - re-target
                ct.draw_indicator_line(myLoc, self.mapPf.teamCore, 10, 80, 255) # blue
                # CRITICAL: moveTo caches its distance table and only refills when
                # prevTarget changes. Our fill above overwrote distMap with
                # distances to OUR OWN position, so moveTo would then steer by a
                # table describing the wrong destination and walk the wrong way.
                # Measured 10.0% vs stock. Invalidating the cache forces moveTo
                # to refill for its real target.
                self.mapPf.prevTarget = None

            teamGunners = []
            enemyGunners = []
            downGunners = []
            teamGunner = None
            for b in ct.get_nearby_buildings():
                if ct.get_entity_type(b) == EntityType.GUNNER:
                    bPos = ct.get_position(b)
                    if ct.get_team(b) != myTeam:
                        enemyGunners.append(bPos)
                    else:
                        teamGunners.append(bPos)
                        if ct.get_hp(b) < 25:
                            downGunners.append(bPos)

            if downGunners:
                downGunners.sort(key=lambda gunnerSpot: gunnerSpot.distance_squared(myLoc))
                teamGunner = downGunners[0]

            # TRIAGE HEAL (8cdcc379 g3): heal beats chew - 4/turn vs the
            # chewer's 2. Endangered adjacent gun (hp<=15) gets the heal;
            # no facing touched, no race tax.
            _tri = None
            _triHp = 16
            for _u in ct.get_nearby_buildings():
                if (ct.get_team(_u) == ct.get_team()
                        and ct.get_entity_type(_u) == EntityType.GUNNER):
                    _up = ct.get_position(_u)
                    if myLoc.distance_squared(_up) == 1:
                        _uhp = ct.get_hp(_u)
                        if _uhp < _triHp:
                            _triHp, _tri = _uhp, _up
            if _tri is not None and ct.can_heal(_tri):
                ct.heal(_tri)
                return

            if self.mySpot: # place some gunners
                ct.draw_indicator_line(myLoc, self.mySpot, 180, 220, 60) 
                ct.draw_indicator_line(self.mapPf.teamCore, self.mySpot, 255, 255, 0)
                myDir = self.mySpot.direction_to(enemyCore)

                if ct.can_build_gunner(self.mySpot, myDir):
                    ct.build_gunner(self.mySpot, myDir)
                
                if myLoc.distance_squared(self.mySpot) > 1:
                    self.mapPf.moveTo(ct, self.mySpot)
                return

            if teamGunner: # try to heal your closest low gunner
                if ct.can_heal(teamGunner):
                    ct.heal(teamGunner)
                
                if myLoc.distance_squared(teamGunner) > 1:
                    # was moveTo(teamGunner) - missing ct, raises TypeError and
                    # DESTROYS the builder. Dormant until the self-destruct above
                    # started freeing seats, which lets mySpot go None and finally
                    # reaches this path (5 crashes on royale).
                    self.mapPf.moveTo(ct, teamGunner)
                return

            # otherwise move to be as close to team gunners as possible
            bestSpot = None
            bestDist = 4096
            for botSpot in ct.get_nearby_tiles():
                spotScore = 0
                for t in teamGunners:
                    spotScore += abs(t.x - botSpot.x) + abs(t.y - botSpot.y)
                if spotScore < bestDist:
                    bestSpot = botSpot
                if spotScore == bestDist and myLoc.distance_squared(bestSpot) > myLoc.distance_squared(botSpot):
                    bestSpot = botSpot
                    
            self.mapPf.moveTo(ct, botSpot)
        elif etype == EntityType.GUNNER:
            curTarget = ct.get_gunner_target()
            # can_fire(None) raises TypeError, and with no exception handler in
            # this bot that PERMANENTLY DESTROYS the gunner. Fires intermittently
            # (2 on nordkap s1, 1 on archipelago) - each one is a lost 20 Ti unit.
            if curTarget is not None and ct.can_fire(curTarget):
                ct.fire(curTarget)
            elif curTarget is None:
                # NO TARGET = this gunner is useless where it sits, and it is
                # squatting on one of only ~12 core-ring seats. Freeing the seat
                # lets the builder reseat a fresh, correctly-aimed gunner.
                # Measured: leaving them alive costs 5.0pp (73.9% vs 78.9%) -
                # the old can_fire(None) CRASH was accidentally doing this, so
                # this makes the recycling deliberate instead of exception-driven.
                ct.self_destruct()