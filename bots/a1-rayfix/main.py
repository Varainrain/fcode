"""Starter bot - a simple example to demonstrate usage of the Controller API.

Each unit gets its own Player instance; run() is called once per round.
Use Controller.get_entity_type() to branch on what kind of unit you are.
"""

# If the core goes below 400 health, and sees a gunner attacking it, it will immediately send a 'recall' order in the next unused slot, where the other bots will walk back to team core, scored based on their distance to it. Synergizes well with OogwayTestExplore
# and spend up titanium to get to 50 ammo, stopping when it has 20 titanium left

from fcode import Controller, Direction, EntityType, Environment, Position
import os

def _fp(key: str, default: float) -> float:
    v = os.environ.get(key)
    return float(v) if v is not None else default

def _fi(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v is not None else default

def _int_set(key: str, default: str) -> frozenset:
    v = os.environ.get(key, default)
    return frozenset(int(x) for x in v.split(",") if x.strip())

# myNum values (role-assignment slot, not ct.get_id()) whose builder gets a
# home-corner move zone via setMoveZone - see builderBot(). Sweep-configurable.
DEFEND_NUMS = _int_set("DEFEND_NUMS", "4")

S_PROTECT    = _fp("S_PROTECT", 10.0)       # any uncovered turret, any distance
S_HEAL_CORE  = _fp("S_HEAL_CORE", 12.0)     # any visible damaged core
S_HB_FLOOR   = _fp("S_HB_FLOOR", 8.5)       # healBuild floor (must stay > routeConv cap)
S_HB_MISSING = _fi("S_HB_MISSING", 1)       # healBuild damage gate (like best=1)
S_RC_FLOOR   = _fp("S_RC_FLOOR", 3.2)       # routeConv floor
S_RC_CAP     = _fp("S_RC_CAP", 4.0)         # routeConv cap
S_RH_FLOOR   = _fp("S_RH_FLOOR", 2.2)       # routeHarv floor
S_RH_CAP     = _fp("S_RH_CAP", 3.2)         # routeHarv cap
S_HV_FLOOR   = _fp("S_HV_FLOOR", 1.2)       # harvest floor
S_HV_CAP     = _fp("S_HV_CAP", 2.2)         # harvest cap

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
ROUTE_STALL_ROUNDS = 24
ROUTE_COMMIT_MAX_LINKS = 4
RECALL_SLOT = 9      # slots 0-8 are taken; 9 is free
RECALL_HP = 400      # the threshold the file's own opening comment specifies
RECALL = 1
SEAL_SLOT = 13       # seal-duty claim round (10-15 free; 14 reserved: healer claim)
SEAL_TRIAGE_HP = 350 # below this, heals outrank armor (the 0-heal-bug fix)
# Gunner placement scoring, from the Pantheon postmortem's gunner ray model.
GUN_STEP_DISCOUNT = 0.9   # score at step k is discounted by 0.9**k
GUN_W_CORE   = 1000       # enemy core
GUN_W_THREAT = 100        # enemy turret that can shoot back
GUN_W_ECO    = 25         # enemy harvester / conveyor - cuts their income
GUN_W_BOT    = 10         # enemy builder bot
GUN_W_OTHER  = 1
GUN_ROT_SHIFT = 8         # rotation bonus is the all-facings sum over this

def _signed4(v: int) -> int:
    return v - 16 if v >= 8 else v

from mapPathfinding import *

# facing -> (dx, dy, reach). Derived from mapPathfinding.gunnerLines so the
# reach per direction (3 cardinal, 2 diagonal) is defined in exactly one place.
GUN_RAY = {_d: (_dx, _dy, _k) for _dx, _dy, _k, _d in gunnerLines}

# slot 0 numSpawned, slot 1-6 map sharing, slot 7 teamCore loc + up to 2 enemy gunner
# offsets from the core (bits 0-9 core pos, 10-17 gunner1 dx/dy, 18-25 gunner2 dx/dy,
# 4-bit signed each, dx=dy=0 = empty), slot 8 symmetry (mapPathfinding)

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
        self.entombPlaced = 0
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.lastSpawn = -99
        self.mapW = None
        self.mapH = None
        self.visitedCenter = False
        self._allyBuilders = []
        self._myId = 0
        self.sawIncome = False
        self.lastTi = None

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

        # SPAWN RATE LIMIT: the bare Ti>360 respawn is a death-loop faucet --
        # vs not adgato's barrier+gunner nets it fed 76-109 builders (2-3k Ti)
        # into the same kill zone in one game (1c12e4c7 g5, 04b53e8c g4).
        # After the opening 5, respawns need an 8-round gap: legit rebuilds
        # barely notice, the meat grinder loses its supply.
        _rnd = ct.get_current_round()
        if self.numSpawned < 5 or (globalTitanium > 360
                                   and _rnd - self.lastSpawn >= 8):
            spawnableTiles = []
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    spawnableTiles.append(tile)
            if spawnableTiles:
                mapCenter = Position(self.mapW // 2, self.mapH // 2)
                nearbyOres.append(mapCenter)
                nextNum = self.numSpawned + 1
                if nextNum % 2 == 1 and nextNum not in (5, 7): # attacking bots
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(mapCenter))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
                    self.lastSpawn = _rnd
                else: # eco/defense bot
                    sortTarget = nearbyOres[(nextNum //2) % len(nearbyOres)]
                    spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(sortTarget))
                    closestTile = spawnableTiles[0]
                    ct.spawn_builder(closestTile)
                    self.numSpawned += 1
                    self.lastSpawn = _rnd
            ct.write_store(0, self.numSpawned) # used so bots know their roles
        slot7 = (myLoc.x << 5) | myLoc.y
        myTeam = ct.get_team()
        teamBuilders = []
        for u in ct.get_nearby_units():
            if ct.get_team(u) == myTeam and ct.get_entity_type(u) == EntityType.BUILDER_BOT:
                teamBuilders.append(ct.get_position(u))
        gunners = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            gPos = ct.get_position(b)
            if any(tb.distance_squared(gPos) <= 5 for tb in teamBuilders):
                continue # a team builder is already close, they can handle it
            gunners.append((gPos.distance_squared(myLoc), gPos))
        gunners.sort(reverse=True) # furthest from our core first
        for i in range(2):
            if i < len(gunners):
                gPos = gunners[i][1]
                dx = gPos.x - myLoc.x
                dy = gPos.y - myLoc.y
                if -8 <= dx <= 7 and -8 <= dy <= 7:
                    slot7 |= (((dx & 0xF) << 4) | (dy & 0xF)) << (10 + 8 * i)
        ct.write_store(7, slot7)
        # RECALL. main.py has opened with a comment describing this since before
        # this change - "if the core goes below 400 health... send a recall order
        # in the next unused slot, where the other bots will walk back to team
        # core" - and it was never implemented, like ROUTE_STALL_ROUNDS.
        # It matters because the cheapest counter to a besieging turret is not
        # killing it, it is out-healing it: a sentinel deals 18 on reload 2 (9 a
        # turn) and a builder heals +4 for 1 Ti, so three builders at home beat a
        # 30 Ti sentinel for 3 Ti a turn. That only works if anyone is home.
        if RECALL:
            # SEVERITY: 2 = critical (all hands), 1 = hurt (split duty).
            _hp = ct.get_hp()
            hurt = 2 if _hp < 200 else (1 if _hp < RECALL_HP else 0)
            ct.write_store(RECALL_SLOT, hurt)
        # BOOTSTRAP-ONLY AMMO RESERVE.
        # The flat 28 this line drains to is below a harvester's price once the
        # cost scale passes 140%, so on meander/fjordgate the opening spawn burst
        # digs the bank to ~28 and this conversion then eats every passive drip
        # that would have refilled it: zero mined, 1000 turns, 6 of 6 seeds.
        # Reserving the full harvester price fixes both maps (12/12 in the lab)
        # but loses everywhere else - harvCost scales with unit count, so late
        # game it withholds a fortune from ammo and starves the gunners
        # (nordkap 0%, eider 0%, antler 14%). So the reserve is for the bootstrap
        # only and lifts for good once we have real income.
        # Passive titanium arrives in a fixed +10 every PASSIVE_TITANIUM_INTERVAL
        # turns, so a rise on any OTHER turn can only have come from a harvester.
        rnd = ct.get_current_round()
        if self.lastTi is not None and globalTitanium > self.lastTi and rnd % 4 != 0:
            self.sawIncome = True
        self.lastTi = globalTitanium
        reserve = 28 if self.sawIncome else max(28, ct.get_harvester_cost())
        convertAmount = min(16 - globalAmmo, globalTitanium - reserve)
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)
        
    def run(self, ct: Controller) -> None:
        # dev26+: an uncaught exception PERMANENTLY destroys this unit
        # (a CPU timeout only skips the turn). One bad tile query must
        # never cost a unit. This line has shipped on every chassis we
        # have measured; it can only ever SAVE units.
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
    def answerRecall(self, ct: Controller, myLoc) -> bool:
        """Go home and heal while the core is under threshold.

        Only bots already on our own half answer, so a committed siege is not
        abandoned: we compare our distance home against our distance to their
        core, which is observable state rather than a hardcoded radius.
        """
        home = self.mapPf.teamCore
        if home is None:
            return False
        enemy = self.mapPf.enemyCorePos
        dHome = myLoc.distance_squared(home)
        if enemy is not None and dHome > myLoc.distance_squared(enemy):
            return False                       # deep in their half, stay committed
        if self.healDamagedNonCore(ct):
            return True
        if dHome <= 2:
            self.healCore(ct, home)
            return True
        self.drawState(ct, C_HEAL_CORE, home)
        self.mapPf.moveTo(ct, home)
        return True

    def builderBot(self, ct: Controller):
        myLoc = ct.get_position()
        self.mapPf.setupMap(ct)
        # DEFEND DETAIL: builders in DEFEND_NUMS, by role-assignment slot
        # (myNum, the same spawn-order number that decides attack vs eco
        # below - NOT ct.get_id(), which is a per-unit engine ID unrelated
        # to role), never roam past the home corner - constrained via the
        # existing (until now unused) setMoveZone hook.
        if self.mapPf.myNum in DEFEND_NUMS and self.mapPf.teamCore is not None:
            self.mapPf.setMoveZone(self.mapPf.teamCore, self.farCoreCorner())
        # observe enemy conveyors (feeds cut-and-cap memory)
        try:
            _mt = ct.get_team()
            for _b in ct.get_nearby_buildings():
                if (ct.get_team(_b) != _mt
                        and ct.get_entity_type(_b) == EntityType.CONVEYOR):
                    _p = ct.get_position(_b)
                    self.mapPf.enemyConvSeen.add((_p.x, _p.y))
        except Exception:
            pass
        # CUT-AND-CAP: an enemy conveyor died on an adjacent tile within
        # the last 4 rounds -> cap it with a barrier (3 Ti) so the line
        # can NEVER be rebuilt in place. Rare trigger, one action, the
        # exact move Jython used to beat #1 (ic3d spotted it watching
        # Pantheon). Our own death-memory already routes AROUND enemy
        # caps, so this is the offensive half of the same coin.
        try:
            if ct.can_act() and ct.get_global_resources() >= 28:
                _my = ct.get_position()
                for _d in CARDINALS:
                    _n = _my.add(_d)
                    if ((_n.x, _n.y) in getattr(self.mapPf, 'freshEnemyCuts', {})
                            and ct.get_tile_building_id(_n) is None
                            and ct.can_build_barrier(_n)):
                        ct.build_barrier(_n)
                        del self.mapPf.freshEnemyCuts[(_n.x, _n.y)]
                        return
        except Exception:
            pass
        if RECALL:
            try:
                # ECONOMY FLOOR ON RECALL (field evidence: 0241a12b g1 --
                # ONE harvester and 3 conveyors built in 377 rounds while
                # healing 822 hp, because every eco builder on our half
                # answers recall and returns. adgato ran h7/cv44 in the same
                # game and won. g2: healed 1679 (=420 Ti of nursing) and
                # still lost. The two games our economy kept running are the
                # two we won/nearly won.)
                # Nursing a core against a bigger economy is a losing race,
                # so: below 200 hp everyone comes home (a core about to die
                # outranks everything), otherwise HALF the crew heals and
                # half keeps building, alternating by round.
                _rc = ct.read_store(RECALL_SLOT)
                if _rc == 2 or (_rc == 1 and (ct.get_current_round() + self.mapPf.myNum) % 2 == 0):
                    if self.answerRecall(ct, myLoc):
                        return
            except Exception:
                pass
        if self.mapPf.myNum % 2 == 1 and self.mapPf.myNum not in (5, 7): # attacking
            # pathfind to enemy core. if it isnt known pathfind to center of map.
            # once the enemy core is known, calculate all possible tiles that are empty and you can place a gunner on such that it would attack the enemy core
            # score them by their distance, and the number of enemy gunners attacking those tiles (if it has more than 1, dont count it)
            # pathfind to the one with the highest score, and place a gunner there
            # if there are no such spots, the create a gunner to target enemy gunners, scoring based on distance to enemy core, and the best valid spots. 
            # valid spots are scored based on their proximity to the builder bot, as number of enemy gunners attacking them (also limited to one.)
            # continue, until your titanium drops below 80
            self.runAttack(ct)
        else: # economy / defending - both build the same way
            # MEMORYLESS STATE SCORING: every turn every eco state (protect,
            # heal core, heal build, route conv, route harv, harvest) is
            # scored from observable state and the best is executed.
            self.runBestState(ct)

    def sealTiles(self):
        """The gated 12-tile sentinel-line seal (defense_advisor.shield_tiles):
        4 diagonal corners kill diagonal firing lines, 8 cardinal lane tiles
        at distance 2 kill straight lines; the d1 ring stays free for spawns,
        heals and conveyor hookups. Pantheon 4-1 receipt on this geometry."""
        core = self.mapPf.teamCore
        if core is None:
            return []
        corners = [
            Position(core.x - 1, core.y - 1), Position(core.x + 2, core.y - 1),
            Position(core.x - 1, core.y + 2), Position(core.x + 2, core.y + 2),
        ]
        lanes = [
            Position(core.x,     core.y - 2), Position(core.x + 1, core.y - 2),
            Position(core.x,     core.y + 3), Position(core.x + 1, core.y + 3),
            Position(core.x - 2, core.y),     Position(core.x - 2, core.y + 1),
            Position(core.x + 3, core.y),     Position(core.x + 3, core.y + 1),
        ]
        enemy = self.mapPf.enemyCorePos
        if enemy is None:
            # corners never fully close a cardinal approach -- safe to
            # build before we know which side the rush comes from
            cand = corners
        else:
            # ECO GATE: a full 12-tile seal strangles our own economy
            # (conveyors connect cardinally; the 8 lane tiles cover every
            # cardinal approach -- measured: 6 buildings vs 19, 200 vs 770
            # mined). Leave the 2 lane tiles facing AWAY from the enemy
            # open so conveyor lines keep a path to the core.
            dx, dy = enemy.x - core.x, enemy.y - core.y
            if abs(dx) >= abs(dy):
                drop = ({(core.x - 2, core.y), (core.x - 2, core.y + 1)}
                        if dx > 0 else
                        {(core.x + 3, core.y), (core.x + 3, core.y + 1)})
            else:
                drop = ({(core.x, core.y - 2), (core.x + 1, core.y - 2)}
                        if dy > 0 else
                        {(core.x, core.y + 3), (core.x + 1, core.y + 3)})
            cand = [p for p in corners + lanes if (p.x, p.y) not in drop]
            cand.sort(key=lambda p: (p.x - enemy.x) ** 2 + (p.y - enemy.y) ** 2)
        return [p for p in cand if 0 <= p.x < self.mapW and 0 <= p.y < self.mapH]

    def nextSealGap(self, ct: Controller, threats):
        """REACTIVE: only tiles that stand between a live core threat and
        the core. A proactive full seal measured eco-dead on this chassis
        (340 mined/735t -- conveyor lines lost their approach); reactive
        threat-side tiles never fire in normal games and answer the
        sentinel proxy rush when it comes."""
        core = self.mapPf.teamCore
        if core is None or not threats:
            return None
        try:
            cid = ct.get_tile_building_id(core)
            if cid is not None and ct.get_hp(cid) < SEAL_TRIAGE_HP:
                return None                    # triage: armoring a corpse loses
        except Exception:
            pass
        cand = []
        for sp in self.sealTiles():
            dBest = min(abs(sp.x - t.x) + abs(sp.y - t.y) for t in threats)
            dThreat = min(coreFootprintManhattan(t, core) for t in threats)
            if dBest <= dThreat:               # threat-side tiles only
                cand.append((dBest, sp))
        for _, sp in sorted(cand, key=lambda c: c[0]):
            try:
                if not ct.is_in_vision(sp):
                    continue
                if ct.get_tile_building_id(sp) is not None:
                    continue
                if ct.get_tile_env(sp) != Environment.EMPTY:
                    continue
            except Exception:
                continue
            return sp
        return None

    def coreThreats(self, enemyTurrets):
        """Enemy turrets within the stack's measured core-threat radius
        (sentinel_is_core_threat: manhattan 7 -- the scoped radius that
        gated free; the unscoped version bled 17%)."""
        core = self.mapPf.teamCore
        if core is None:
            return []
        return [g for g in enemyTurrets if coreFootprintManhattan(g, core) <= 7]

    def sealTask(self, ct: Controller, myLoc, threats) -> bool:
        """ONE builder per round advances the seal (store-slot claim, the
        sporks one-claimant pattern). Everyone else plays normal eco. The
        whole policy costs at most 12 barriers = 36 Ti and goes inert once
        the seal is complete."""
        if ct.get_global_resources() < 6:
            return False
        gap = self.nextSealGap(ct, threats)
        if gap is None:
            return False
        d1 = abs(myLoc.x - gap.x) + abs(myLoc.y - gap.y)
        if d1 > 4:
            return False                       # someone closer claims instead
        rnd = ct.get_current_round()
        try:
            if ct.read_store(SEAL_SLOT) >= rnd:
                return False                   # today's seal turn is spent
        except Exception:
            return False
        if d1 == 1 and ct.can_build_barrier(gap):
            ct.write_store(SEAL_SLOT, rnd + 1)
            ct.build_barrier(gap)
            return True
        if d1 == 0:
            # standing on the gap: building on your own tile silently fails
            # (PITFALLS #3) -- step off, build next turn
            ct.write_store(SEAL_SLOT, rnd + 1)
            self.drawState(ct, C_IDLE, gap)
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
            return True
        ct.write_store(SEAL_SLOT, rnd + 1)
        self.drawState(ct, C_IDLE, gap)
        self.mapPf.moveTo(ct, gap)
        return True

    def _onCoreRay(self, g, coreTiles, t) -> bool:
        """True if tile t lies strictly between turret g and any core tile
        on a straight cardinal/diagonal line (i.e. capping t would block
        that turret's shot at the core)."""
        for c in coreTiles:
            vx, vy = c.x - g.x, c.y - g.y
            if vx != 0 and vy != 0 and abs(vx) != abs(vy):
                continue                      # not a straight firing line
            tx, ty = t.x - g.x, t.y - g.y
            if vx == 0:
                if tx != 0 or ty * vy <= 0 or abs(ty) >= abs(vy):
                    continue
            elif vy == 0:
                if ty != 0 or tx * vx <= 0 or abs(tx) >= abs(vx):
                    continue
            else:
                if abs(tx) != abs(ty) or tx * vx <= 0 or abs(tx) >= abs(vx):
                    continue
                if tx * vy != ty * vx:
                    continue
            return True
        return False

    def entombTask(self, ct: Controller, myLoc) -> bool:
        """Cap an enemy-core-adjacent tile with OUR barrier (passable only
        to us) so their builders lose the standing spot they heal from."""
        if self.entombPlaced >= 4 or ct.get_global_resources() < 30:
            return False
        # the >=96 Ti branch above may have MOVED us without returning; a
        # stale myLoc can alias our own tile, where build_barrier silently
        # no-ops (PITFALLS #3) while the cap budget still burns
        myLoc = ct.get_position()
        ec = self.mapPf.enemyCorePos
        if ec is None or myLoc.distance_squared(ec) > 18:
            return False
        coreTiles = [ec, ec.add(Direction.EAST), ec.add(Direction.SOUTH),
                     ec.add(Direction.SOUTH).add(Direction.EAST)]
        myTeam = ct.get_team()
        siegeTurrets = []
        try:
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) == myTeam
                        and ct.get_entity_type(b) in (EntityType.GUNNER, EntityType.SENTINEL)
                        and ct.get_position(b).distance_squared(ec) <= 40):
                    siegeTurrets.append(ct.get_position(b))
        except Exception:
            return False
        if not siegeTurrets:
            return False                       # no solo entombing
        for d in CARDINALS:
            spot = myLoc.add(d)
            if not (0 <= spot.x < self.mapW and 0 <= spot.y < self.mapH):
                continue
            dRing = coreFootprintManhattan(spot, ec)
            if dRing != 1:
                continue                       # exactly the heal ring
            try:
                if ct.get_tile_building_id(spot) is not None:
                    continue
                if any(self._onCoreRay(g, coreTiles, spot) for g in siegeTurrets):
                    continue                   # never wall our own shot
                if ct.can_build_barrier(spot):
                    ct.build_barrier(spot)
                    self.entombPlaced += 1
                    return True
            except Exception:
                continue
        return False

    def farCoreCorner(self) -> Position:
        core = self.mapPf.teamCore
        center = Position(self.mapW // 2, self.mapH // 2)
        corners = [core, core.add(Direction.EAST), core.add(Direction.SOUTH),
                   core.add(Direction.SOUTH).add(Direction.EAST)]
        return max(corners, key=lambda corner: corner.distance_squared(center))

    def visibleDefendBots(self, ct: Controller) -> list:
        return []

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
            if ct.get_global_resources() >= 30 and self.attackHarvesterWithGunner(ct):
                return

            if ct.get_global_resources() >= 96:
                gunnerStuff = self.findGunnerSpot(ct)
                if gunnerStuff:
                    gunnerSpot, gunnerDir = gunnerStuff
                    self.drawState(ct, C_TURRET_SPOT, gunnerSpot)
                    if ct.can_build_gunner(gunnerSpot, gunnerDir):
                        ct.build_gunner(gunnerSpot, gunnerDir)

                    myDist = myLoc.distance_squared(gunnerSpot)
                    if myDist < 1:
                        self.mapPf.moveTo(ct, self.mapPf.teamCore)
                    elif myDist > 1:
                        self.mapPf.moveTo(ct, gunnerSpot)
                    else:
                        return

            if self.healTeamGunners(ct):
                return
            
            if self.entombTask(ct, myLoc):
                return

            self.drawState(ct, C_MARCH_ATTACK, self.mapPf.enemyCorePos)
            self.mapPf.moveTo(ct, self.mapPf.enemyCorePos)

    @_prof('harvGun')
    def attackHarvesterWithGunner(self, ct: Controller) -> bool:
        myLoc = ct.get_position()
        harvester = None
        harvesterDist = None
        covered = self.coveredTiles(ct)
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) != EntityType.HARVESTER or ct.get_team(b) == ct.get_team():
                continue
            if ct.get_position(b) in covered:
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
            score = (seatCov, -self.spotValue(ct, spotPos, spotDir, ct.get_team()),
                     -spotPos.distance_squared(enemyCore), myLoc.distance_squared(spotPos))
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


    def rayValue(self, ct: Controller, spotPos, spotDir, myTeam) -> float:
        """What a gunner standing at spotPos facing spotDir can actually shoot.

        Our placement scored only geometry - enemy coverage, distance to the
        enemy core, distance to me - and never asked what the tile can HIT. That
        is why 62% of our gunner-turns have no live target at all: we put guns
        where the map looks right rather than where the shots are.

        The sources describe scoring along the gunner's firing ray with a 0.9**k
        step discount, which favours standing adjacent to the target because
        gunners cannot shoot over obstacles the way sentinels can. The ray is
        blocked by walls and by our OWN buildings (we would be shooting our own
        wall), and the enemy core is counted once at its nearest hit rather than
        for each of the four tiles it occupies.
        """
        dx, dy, maxK = GUN_RAY[spotDir]
        total = 0.0
        x, y = spotPos.x, spotPos.y
        seenCore = False
        for k in range(1, maxK + 1):
            x += dx
            y += dy
            if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                break
            tile = Position(x, y)
            if self.mapPf.fullMap is not None and self.mapPf.fullMap[x][y] == 2:
                break                                  # wall shields everything behind
            if not ct.is_in_vision(tile):
                continue        # get_tile_building_id raises outside vision; an
                                # unseen tile scores nothing but does not block,
                                # matching how gunnerSpots treats unseen tiles
            bId = ct.get_tile_building_id(tile)
            if bId is not None and ct.get_team(bId) == myTeam:
                break                                  # our own building blocks the line
            w = 0.0
            if bId is not None:
                bType = ct.get_entity_type(bId)
                if bType == EntityType.CORE:
                    if seenCore:
                        w = 0.0                        # 2x2 core, count it once
                    else:
                        seenCore = True
                        w = GUN_W_CORE
                elif bType in (EntityType.GUNNER, EntityType.SENTINEL):
                    w = GUN_W_THREAT
                elif bType in (EntityType.HARVESTER, EntityType.CONVEYOR,
                               EntityType.SPLITTER):
                    w = GUN_W_ECO
                else:
                    w = GUN_W_OTHER
            else:
                uId = ct.get_tile_builder_bot_id(tile)
                if uId is not None and ct.get_team(uId) != myTeam:
                    w = GUN_W_BOT
            if w:
                total += w * (GUN_STEP_DISCOUNT ** k)
            # ENGINE TRUTH: a gunner's shot stops at the FIRST non-empty tile
            # ("only empty tiles fail to block the firing line... builder bots
            # and buildings are both targetable and blocking"). This loop used
            # to keep scoring targets BEHIND an enemy blocker, so a spot whose
            # line to the core is interrupted by a 3-Ti barrier still scored
            # the full GUN_W_CORE. Measured consequence (4d3d2db0 g5): 2772
            # damage poured into barriers vs 861 into the core -- their walls
            # ate our ammo at 5:1 while we thought we were sieging.
            if bId is not None:
                break
            if ct.get_tile_builder_bot_id(tile) is not None:
                break
        return total

    def spotValue(self, ct: Controller, spotPos, spotDir, myTeam) -> float:
        """Ray value for the chosen facing, plus a rotation bonus.

        Gunners can rotate, so a tile that also covers other facings keeps
        earning after its first lane is cleared - the sources add exactly this
        as a sum over all facings, scaled down so it breaks ties rather than
        dominating the shot we are placing for.
        """
        base = self.rayValue(ct, spotPos, spotDir, myTeam)
        rot = 0.0
        for d in GUN_RAY:
            if d != spotDir:
                rot += self.rayValue(ct, spotPos, d, myTeam)
        return base + rot / GUN_ROT_SHIFT

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
            score = (seatCov, -self.spotValue(ct, spotPos, spotDir, ct.get_team()),
                     myLoc.distance_squared(spotPos), spotPos.distance_squared(enemyCore))
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
        teamCore = Position((compact >> 5) & 0x1F, compact & 0x1F)
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
                # raw pattern includes tiles behind walls (its own docstring);
                # scoring it directly rotates the gun onto targets it cannot hit
                # and burns 10 Ti doing so. gun_los: +3.4pp over 681 games.
                if not ct.can_fire_from(myPos, d, EntityType.GUNNER, tile):
                    continue
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
            bestEntry = max(directionScores)
            bestScore, _, _, bestDir, bestIsCoreDefense = bestEntry
        if bestDir != myDir:
            _, _, gunnerHits, _ = bestScore
            if bestIsCoreDefense:
                floor = 35
            elif gunnerHits > 0:
                floor = 50
            else:
                floor = 85
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
    def nearbyAllyBuilders(self, ct: Controller, nearbyUnits, myTeam) -> list:
        allies = []
        for b in nearbyUnits:
            if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.BUILDER_BOT:
                allies.append([b, ct.get_position(b)])
        return allies

    def isClosestAllyTo(self, allies, myId, myLoc, target) -> bool:
        for aId, aPos in allies:
            if aId == myId:
                continue
            aDist = aPos.distance_squared(target)
            myDist = myLoc.distance_squared(target)
            if aDist < myDist and aId < myId:
                return False
        return True

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
                    if not self.isClosestAllyTo(self._allyBuilders, self._myId, myLoc, bPos):
                        continue # only the closest builder heals each building
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

    def broadcastGunners(self, ct: Controller) -> list:
        compact = ct.read_store(7)
        corePos = Position((compact >> 5) & 0x1F, compact & 0x1F)
        gunners = []
        for i in range(2):
            gun = (compact >> (10 + 8 * i)) & 0xFF
            if gun == 0:
                continue
            dx = _signed4((gun >> 4) & 0xF)
            dy = _signed4(gun & 0xF)
            gPos = Position(corePos.x + dx, corePos.y + dy)
            gunners.append(gPos)
            ct.draw_indicator_line(corePos, gPos, 255, 255, 0)
        return gunners

    @_prof('eco')
    def runBestState(self, ct: Controller):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        self._allyBuilders = self.nearbyAllyBuilders(ct, ct.get_nearby_units(), myTeam)
        self._myId = ct.get_id()
        covered = self.coveredTiles(ct)
        enemyTurrets = []
        enemySentinels = []
        coreId = None
        for b in ct.get_nearby_buildings():
            bTeam = ct.get_team(b)
            bType = ct.get_entity_type(b)
            if bTeam == myTeam and bType == EntityType.CORE:
                coreId = b
            elif bTeam != myTeam and bType in (EntityType.GUNNER, EntityType.SENTINEL):
                enemyTurrets.append(ct.get_position(b))
                if bType == EntityType.SENTINEL:
                    # SENTINELS ONLY feed the seal: broadening the trigger to
                    # gunners measured 4-of-5 builders dead on drumlin (they
                    # marched into harass fire to place barriers) -- the
                    # chassis turret-response already beats gunner harass
                    enemySentinels.append(ct.get_position(b))
        enemyTurretKeys = set((g.x, g.y) for g in enemyTurrets)
        for g in self.broadcastGunners(ct):
            if (g.x, g.y) not in enemyTurretKeys and (g.x, g.y) not in covered:
                if myLoc.distance_squared(g) <= 32: # only respond to broadcast gunners we're close to
                    enemyTurretKeys.add((g.x, g.y))
                    enemyTurrets.append(g)
        uncoveredTurrets = [g for g in enemyTurrets if (g.x, g.y) not in covered]

        scores = {
            'protect':  self.scoreProtect(ct, myLoc, uncoveredTurrets),
            'healCore': self.scoreHealCore(ct, myLoc, coreId),
            'healBuild': self.scoreHealBuild(ct, myLoc),
            'routeConv': self.scoreRouteConv(ct, myLoc, myTeam),
            'routeHarv': self.scoreRouteHarv(ct, myLoc, myTeam),
            'harvest':  self.scoreHarvest(ct, myLoc, myTeam),
        }
        bestState = max(scores, key=lambda k: scores[k][0])
        bestScore, bestPos = scores[bestState]

        if bestScore <= 0 or bestPos is None:
            if self.mapPf.teamCore is not None:
                self.drawState(ct, C_IDLE, self.mapPf.teamCore)
                if not ct.is_in_vision(self.mapPf.teamCore):
                    self.mapPf.moveTo(ct, self.mapPf.teamCore)
            return

        if bestState == 'protect':
            self.protectTask(ct, bestPos)
        elif bestState == 'healCore':
            self.drawState(ct, C_HEAL_CORE, self.mapPf.teamCore)
            self.healCore(ct, self.mapPf.teamCore)
        elif bestState == 'healBuild':
            self.healPos(ct, bestPos)
        elif bestState == 'routeConv':
            self.routeConveyorTask(ct, myLoc, myTeam)
        elif bestState == 'routeHarv':
            self.routeHarvesterTask(ct, myLoc, myTeam)
        elif bestState == 'harvest':
            self.harvestPos(ct, bestPos)

    def scoreProtect(self, ct: Controller, myLoc, uncoveredTurrets):
        """Priority 10: ANY uncovered enemy turret, ANY distance (old runEco
        had no range gate). Distance only selects the target, never zeroes
        the state out - a 0-8 drumlin/eider regression taught us that."""
        if not uncoveredTurrets or ct.get_global_resources() < ct.get_gunner_cost():
            return 0, None
        target = min(uncoveredTurrets, key=lambda g: g.distance_squared(myLoc))
        return S_PROTECT, target

    def protectTask(self, ct: Controller, target: Position):
        self.drawState(ct, C_FIGHT_TURRET, target)
        if self.buildGunnerFor(ct, target): # try to place gunner there
            return
        if ct.can_fire(target):
            ct.fire(target)
            return
        self.mapPf.moveTo(ct, target) # if you can move towards the gunner

    def scoreHealCore(self, ct: Controller, myLoc, coreId):
        """Priority 8: any visible damaged core, ANY distance (old runEco
        trigger). Distance only matters for choosing the target tile."""
        if coreId is None:
            return 0, None
        maxHP = ct.get_max_hp(coreId)
        missing = maxHP - ct.get_hp(coreId)
        if missing <= 0:
            return 0, None
        core = self.mapPf.teamCore
        if core is None:
            return 0, None
        return S_HEAL_CORE, core

    def scoreHealBuild(self, ct: Controller, myLoc):
        """Band (4.2, 6]: damaged gunner/sentinel/conveyor/harvester. Same
        building set + closest-ally gate as healDamagedNonCore, priority 3 in
        runEco. Within-band urgency = damage fraction + proximity; the floor
        keeps it above routeConv so a far damaged building is never ignored."""
        myTeam = ct.get_team()
        bestScore, bestPos = 0, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType not in (EntityType.GUNNER, EntityType.SENTINEL, EntityType.CONVEYOR, EntityType.HARVESTER):
                continue
            missing = ct.get_max_hp(b) - ct.get_hp(b)
            if missing < S_HB_MISSING:        # can_heal only heals when >=3 missing
                continue
            bPos = ct.get_position(b)
            if not self.isClosestAllyTo(self._allyBuilders, self._myId, myLoc, bPos):
                continue
            score = max(S_HB_FLOOR, 4 + 2 * (missing / ct.get_max_hp(b)) - myLoc.distance_squared(bPos) / 400)
            if score > bestScore:
                bestScore, bestPos = score, bPos
        return bestScore, bestPos

    def healPos(self, ct: Controller, pos: Position):
        myLoc = ct.get_position()
        self.drawState(ct, C_HEAL_BUILD, pos)
        d = myLoc.distance_squared(pos)
        if d == 1:
            if ct.can_heal(pos):
                ct.heal(pos)
            return
        if d < 1:                              # standing on it: heal silently fails, step off
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
            return
        self.mapPf.moveTo(ct, pos)

    def scoreRouteConv(self, ct: Controller, myLoc, myTeam):
        """Band (3.2, 4]: unfinished conveyor chains, priority 4 in runEco.
        Within-band: distance from core + builder. Same candidate loop as
        routeConveyorTask (move-zone + defend-bot exclusions intact)."""
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)
        bestScore, bestEnd = 0, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.CONVEYOR:
                continue
            bPos = ct.get_position(b)
            endTile = bPos.add(ct.get_direction(b))
            if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and self.mapPf.inMoveZone(endTile):
                if endTile.distance_squared(farCorner) <= 20 and any(endTile.distance_squared(dPos) <= 10 for dPos in defendBots):
                    continue
                endId = ct.get_tile_building_id(endTile)
                enemyBarrier = (endId is not None and ct.get_team(endId) != myTeam
                                and ct.get_entity_type(endId) == EntityType.BARRIER)
                if enemyBarrier or self.mapPf.checkPassable(ct, endTile):
                    if endId is not None and not enemyBarrier:
                        endType = ct.get_entity_type(endId)
                        endTeam = ct.get_team(endId)
                        if endType not in [EntityType.GUNNER, EntityType.BUILDER_BOT, EntityType.BARRIER] and endTeam == myTeam:
                            continue
                        if endType not in [EntityType.BARRIER] and endTeam != myTeam:
                            continue
                    bScore = max(S_RC_FLOOR, S_RC_CAP * (1 - endTile.distance_squared(teamCore) / 120) * (1 - myLoc.distance_squared(bPos) / 40))
                    if bScore > bestScore:
                        bestScore = bScore
                        bestEnd = endTile
        return bestScore, bestEnd

    def scoreRouteHarv(self, ct: Controller, myLoc, myTeam):
        """Band (2.2, 3.2]: orphan harvesters + eco siphon, priority 5 in
        runEco. Same candidate loop as routeHarvesterTask."""
        mapW, mapH = self.mapW, self.mapH
        teamCore = self.mapPf.teamCore
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)
        bestScore, bestEnd = 0, None
        for b in ct.get_nearby_buildings():
            if ct.get_entity_type(b) != EntityType.HARVESTER:
                continue
            bPos = ct.get_position(b)
            if myLoc.distance_squared(bPos) > 10:
                continue
            noTeamConv = True
            workingSpots = []
            for possibleDir in CARDINALS:
                endTile = bPos.add(possibleDir)
                if 0 <= endTile.x < mapW and 0 <= endTile.y < mapH and ct.is_in_vision(endTile) and self.mapPf.inMoveZone(endTile):
                    if endTile.distance_squared(farCorner) <= 20 and any(endTile.distance_squared(dPos) <= 10 for dPos in defendBots):
                        continue
                    eId = ct.get_tile_building_id(endTile)
                    if eId is None:
                        if ct.is_tile_passable(endTile) and ct.get_tile_env(endTile) == Environment.EMPTY:
                            workingSpots.append(endTile)
                    elif ct.get_team(eId) == myTeam:
                        eType = ct.get_entity_type(eId)
                        if eType == EntityType.CONVEYOR:
                            noTeamConv = False
                        elif eType in (EntityType.BARRIER, EntityType.GUNNER):
                            workingSpots.append(endTile)
            if noTeamConv and len(workingSpots) > 0:
                workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                bScore = max(S_RH_FLOOR, S_RH_CAP * (1 - workingSpots[0].distance_squared(teamCore) / 220) * (1 - myLoc.distance_squared(bPos) / 60))
                try:
                    # ECO SIPHON (sprint-finals mechanic): connecting an
                    # ENEMY harvester routes a quarter of its output into our
                    # chain. TIME-BOUNDED (round >50): on small maps the boost
                    # made eco builders wire THEIR economy instead of ours.
                    if ct.get_team(b) != myTeam and ct.get_current_round() > 50:
                        bScore *= 2.5
                except Exception:
                    pass
                bScore = min(S_RH_CAP, bScore)
                if bScore > bestScore:
                    bestScore = bScore
                    bestEnd = workingSpots[0]
        return bestScore, bestEnd

    def scoreHarvest(self, ct: Controller, myLoc, myTeam):
        """Band (1.2, 2.2): new harvester on ore, priority 6 in runEco. Same
        gates as harvestTask: move zone, enemy-threat, distance is a penalty
        not a cutoff, and the global-resource/7 affordability gate."""
        teamCore = self.mapPf.teamCore
        if teamCore is None:
            return 0, None
        enemyThreatened = self.mapPf.enemyTurretThreatenedTiles(ct)
        farCorner = self.farCoreCorner()
        defendBots = self.visibleDefendBots(ct)
        bestScore, bestTile = 0, None
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
                        tileScore = max(S_HV_FLOOR, S_HV_CAP * (max(0, 160 - dist) / 160) * (max(0, 220 - myLoc.distance_squared(tile)) / 220))
                        if tileScore > bestScore and ct.get_global_resources() > dist / 7:
                            bestScore = tileScore
                            bestTile = tile
        return bestScore, bestTile

    def harvestPos(self, ct: Controller, tile: Position):
        myLoc = ct.get_position()
        self.drawState(ct, C_HARVEST, tile)
        if tile.distance_squared(myLoc) > 1:
            self.mapPf.moveTo(ct, tile)
        if tile.distance_squared(myLoc) < 1:
            self.mapPf.moveTo(ct, self.mapPf.teamCore)
        if ct.can_build_harvester(tile):
            ct.build_harvester(tile)

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
                endId = ct.get_tile_building_id(endTile) 
                enemyBarrier = (endId is not None and ct.get_team(endId) != myTeam
                                and ct.get_entity_type(endId) == EntityType.BARRIER)
                if enemyBarrier or self.mapPf.checkPassable(ct, endTile):
                    if endId is not None and not enemyBarrier:
                        endType = ct.get_entity_type(endId)
                        endTeam = ct.get_team(endId)
                        if endType not in [EntityType.GUNNER, EntityType.BUILDER_BOT, EntityType.BARRIER] and endTeam == myTeam:
                            continue
                        if endType not in [EntityType.BARRIER] and endTeam != myTeam:
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
            if ct.get_entity_type(b) != EntityType.HARVESTER:
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
                    if eId is None:
                        if ct.is_tile_passable(endTile) and ct.get_tile_env(endTile) == Environment.EMPTY:
                            workingSpots.append(endTile)
                    elif ct.get_team(eId) == myTeam:
                        eType = ct.get_entity_type(eId)
                        if eType == EntityType.CONVEYOR:
                            noTeamConv = False
                        elif eType in (EntityType.BARRIER, EntityType.GUNNER):
                            # blocking our own barrier/gunner - still a valid head,
                            # routeConveyor already knows how to destroy it and build through
                            workingSpots.append(endTile)
            if noTeamConv and len(workingSpots) > 0:
                workingSpots.sort(key=lambda pos: pos.distance_squared(teamCore))
                bScore = max(0, 1 - (workingSpots[0].distance_squared(teamCore) / 220)) * max(0, 1 - (myLoc.distance_squared(bPos) / 60))
                # ECO SIPHON (sprint-finals mechanic): this loop already has
                # NO team filter — connecting an ENEMY harvester routes a
                # quarter of its round-robin output into OUR chain (docs:
                # output goes to the least-recently-used adjacent building,
                # ownership unchecked) AND denies them that flow. The
                # plumbing always existed; this is the aim. Score boost so
                # mid-map builders prefer stealing over marginal home spots.
                try:
                    # TIME-BOUNDED (antler 0/10: on small maps enemy
                    # harvesters are reachable from the opening and the
                    # boost made eco builders wire THEIR economy instead
                    # of building OURS. Same law as the poverty trap:
                    # every policy needs a resource condition AND a time
                    # bound. Siphoning is a mid-game raid.)
                    if ct.get_team(b) != myTeam and ct.get_current_round() > 50:
                        bScore *= 2.5
                except Exception:
                    pass
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
                        # distance is a PENALTY, never a cutoff (restored:
                        # the v61-67 line dropped this; far ore ties at
                        # zero and the winner was scan-order — heart went
                        # 3 harvesters in 409 turns vs Coreflood's 10+)
                        tileScore = max(1, (160 - dist)) * max(1, (220 - myLoc.distance_squared(tile)))
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