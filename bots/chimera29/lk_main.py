"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""



# Two things to try out 
# 1) try adding a gate for gunner placement (globalAmmo > 0, or globalTi > 50)
# 2) make healing more often 

from fcode import Controller, Direction, EntityType, Environment, Position

from lk_mapPathfinding import *


GUN_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in gunnerLines}

SENT_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in sentinelLines}

SEAT_SWITCH = 3   # path-cost gap needed before abandoning a claimed seat

LKICK_TI_GATE = 200      # only worth the detour with titanium to spare
LKICK_MAX_CHASE_DSQ = 12 # only engage a SHORT detour - big chases cost rush tempo
LKICK_MAX_CHASE_TURNS = 6  # give up and resume the rush if we can't close in fast


class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.mapW = None
        self.mapH = None
        self.mySpot = None
        self.lastCoreHp = None   # enemy core HP, last time we could see it
        self.lkickDone = False
        self.lkickChaseTurns = 0

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

    def threatenedTiles(self, ct: Controller, myTeam, includeSentinels=False):
        """Empty tiles an enemy gunner (or, optionally, sentinel) would hit if we
        built there.

        A gunner's shot is eaten by the FIRST non-empty tile, so only the empty
        run in front of it is dangerous - anything behind a blocker is safe.
        Walking GUN_RAY per enemy gunner gives exactly that run. Sentinels ignore
        walls/units entirely, so they cover their whole line regardless of what's
        in front - includeSentinels defaults False so existing seat-picking
        callers are unaffected; the launcher-kick gate opts in explicitly.
        """
        bad = set()
        for b in ct.get_nearby_buildings():
            try:
                if ct.get_team(b) == myTeam:
                    continue
                et = ct.get_entity_type(b)
                if et == EntityType.GUNNER:
                    rays, blockable = GUN_RAY, True
                elif includeSentinels and et == EntityType.SENTINEL:
                    rays, blockable = SENT_RAY, False  # sentinels ignore walls/units
                else:
                    continue
                ePos = ct.get_position(b)
                eDir = ct.get_direction(b)
            except Exception:
                continue
            ray = rays.get(eDir)
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
                if not blockable:
                    bad.add((x, y))          # unblockable - every tile on the line is bad
                    continue
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

            # ---------------- LAUNCHER-KICK: v143-ORIGINAL (mySpot-gated, chase) ----
            if (not self.lkickDone and self.mySpot is None
                    and ct.get_global_resources() > LKICK_TI_GATE):
                enemyPos, bestDsq = None, None
                for u in ct.get_nearby_units():
                    try:
                        if (ct.get_entity_type(u) == EntityType.BUILDER_BOT
                                and ct.get_team(u) != myTeam):
                            epos = ct.get_position(u)
                            dsq = myLoc.distance_squared(epos)
                            if dsq <= LKICK_MAX_CHASE_DSQ and (bestDsq is None or dsq < bestDsq):
                                bestDsq, enemyPos = dsq, epos
                    except Exception:
                        continue
                if enemyPos is not None:
                    if bestDsq <= 2:
                        covered = self.threatenedTiles(ct, myTeam, includeSentinels=True)
                        built = False
                        for d in DIRECTIONS:
                            spot = myLoc.add(d)
                            if spot.distance_squared(enemyPos) > 2:
                                continue
                            if (spot.x, spot.y) in covered:
                                continue
                            try:
                                if ct.can_build_launcher(spot):
                                    ct.build_launcher(spot)
                                    built = True
                                    break
                            except Exception:
                                pass
                        self.lkickDone = True
                        if built:
                            return
                    else:
                        self.lkickChaseTurns += 1
                        if self.lkickChaseTurns > LKICK_MAX_CHASE_TURNS:
                            self.lkickDone = True
                        else:
                            self.mapPf.moveTo(ct, enemyPos)
                            return
            # ----------------------------------------------------------------

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
                    # SQUATTER FIX (51ec6e92 g4): a BUILDER BOT on the claimed
                    # seat is not a building - the claim survived and we froze
                    # marching at an occupied tile forever. Any bot there
                    # drops the claim; the ring has more seats.
                    tileBBId = ct.get_tile_builder_bot_id(self.mySpot)
                    if (tileBId is not None or tileBBId is not None
                            or ct.get_tile_env(self.mySpot) not in [Environment.EMPTY]):
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
                # remember the enemy core's HP - vision of it is intermittent
                try:
                    if (ct.get_entity_type(b) == EntityType.CORE
                            and ct.get_team(b) != myTeam):
                        self.lastCoreHp = ct.get_hp(b)
                except Exception:
                    pass
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

            # ---------- IS ANOTHER GUNNER ECONOMICALLY VIABLE? ----------
            # User's rule: only place if (Ti - gunnerCost) > coreHealth * 4/7.
            # 4/7 is AMMO_PER_SHOT / GUNNER_DAMAGE - i.e. the titanium-equivalent
            # (via ammo) needed to finish the core from its last-seen HP. If the
            # remaining titanium after paying for the gunner can't even cover
            # that ammo bill, the gunner isn't worth placing - hold and heal.
            placeViable = True
            try:
                gunCost = ct.get_gunner_cost()
            except Exception:
                gunCost = 20
            tiAfter = ct.get_global_resources() - gunCost
            # Only gates an ADDITIONAL gunner, never the first - teamGunners must
            # be non-empty. Without this, an early core sighting (e.g. during a
            # launcher-kick detour, before any gunner is placed) can lock
            # placeViable False forever, since nothing damages the core to bring
            # lastCoreHp down without a gunner already seated. Confirmed live:
            # this exact path caused a 0-buildings, turn-92 core loss on midgard.
            # Only gates an ADDITIONAL gunner, never the first - teamGunners must
            # be non-empty. Without this, an early core sighting can lock
            # placeViable False forever, since nothing damages the core to bring
            # lastCoreHp down without a gunner already seated.
            if self.lastCoreHp is not None and teamGunners:
                if tiAfter <= self.lastCoreHp * 4.0 / 7.0:
                    placeViable = False

            if not placeViable and teamGunner is not None:
                if ct.can_heal(teamGunner):
                    ct.heal(teamGunner)
                if myLoc.distance_squared(teamGunner) > 1:
                    self.mapPf.moveTo(ct, teamGunner)
                return

            if placeViable and self.mySpot: # place some gunners
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
                    bestDist = spotScore
                if spotScore == bestDist and myLoc.distance_squared(bestSpot) > myLoc.distance_squared(botSpot):
                    bestSpot = botSpot
                    
            self.mapPf.moveTo(ct, bestSpot)
        elif etype == EntityType.GUNNER:
            curTarget = ct.get_gunner_target()
            # can_fire(None) raises TypeError, and with no exception handler in
            # this bot that PERMANENTLY DESTROYS the gunner. Fires intermittently
            # (2 on nordkap s1, 1 on archipelago) - each one is a lost 20 Ti unit.
            if curTarget is not None and ct.can_fire(curTarget):
                ct.fire(curTarget)
                return
            # SELF-DEFENSE (8cdcc379 g3): face the chewer - TARGETLESS ONLY
            # (jav1 39% when firing gunners rotated; offense-bound races)
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
            if curTarget is None:
                # NO TARGET = this gunner is useless where it sits, and it is
                # squatting on one of only ~12 core-ring seats. Freeing the seat
                # lets the builder reseat a fresh, correctly-aimed gunner.
                # Measured: leaving them alive costs 5.0pp (73.9% vs 78.9%) -
                # the old can_fire(None) CRASH was accidentally doing this, so
                # this makes the recycling deliberate instead of exception-driven.
                ct.self_destruct()
        elif etype == EntityType.LAUNCHER:
            # Stateless by necessity: each unit gets its OWN Player instance, so
            # nothing set by the builder that built this launcher carries over.
            # Re-scan live every turn instead of trusting self state.
            myLoc = ct.get_position()
            myTeam = ct.get_team()
            for u in ct.get_nearby_units():
                try:
                    if (ct.get_entity_type(u) != EntityType.BUILDER_BOT
                            or ct.get_team(u) == myTeam):
                        continue
                except Exception:
                    continue
                epos = ct.get_position(u)
                if myLoc.distance_squared(epos) > 2:
                    continue
                bestTile, bestD = None, -1
                for cand in ct.get_nearby_tiles():
                    if myLoc.distance_squared(cand) > 26:
                        continue
                    d = epos.distance_squared(cand)
                    if d <= bestD:
                        continue
                    try:
                        if ct.can_launch(epos, cand):
                            bestTile, bestD = cand, d
                    except Exception:
                        continue
                if bestTile is not None:
                    try:
                        ct.launch(epos, bestTile)
                    except Exception:
                        pass
                break   # one enemy builder expected - stop scanning once handled