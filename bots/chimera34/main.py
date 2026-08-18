"""Entry point. Player.__init__, entity-type dispatch, runCore (incl. the
ray-cast spawn diversifier), and the recall trigger/response.
"""

import os

from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import MapPathfinder, CARDINALS

def _fi(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v is not None else default

def _int_set(key: str, default: str) -> frozenset:
    v = os.environ.get(key, default)
    return frozenset(int(x) for x in v.split(",") if x.strip())

# eco.py/attack.py import _fp/_fi/_prof back from here - defining them above
# the `import eco` / `import attack` lines below is what makes that circular
# import resolve cleanly (the names already exist in this module's namespace
# by the time eco/attack are imported).
import eco
import attack
import g_main
import s_main
import rb_main
import lk_main

# CHIMERA mode split: the CORE (unit 1, runs before any builder exists)
# matches its EXACT position against the rush-map table and broadcasts the
# verdict; every later entity reads it. Exact match is load-bearing:
# royale's cores (9,2)/(9,16) sit one tile from auroraveil's (9,1)/(9,17),
# so any tolerance would rush royale. Unknown maps (future rotations)
# fall through to eco.
SLOT_MODE = 15         # 0 = undecided, 1 = eco (this file), 2 = rush (g_main)
RUSH_CORES = {
    # auroraveil MOVED to the simple rush below: head-to-head the simple rush
    # took auroraveil 14/14 off this gungnir path. Table left empty so the
    # dispatcher and the g_* modules stay wired for future use.
}
# Plain 1-builder gunner rush (s_main): walks to the enemy core ring and fills
# it with point-blank gunners, Ti>100 gate, heal when the ring is full, ammo 28.
# Per-map REPLICATED on independent seeds (10/10 in BOTH runs): fjordgate,
# glacierkeep, icefloe, nordkap, royale. Table gated 119/210 = 56.7% vs v124.
# Fingerprints verified pairwise distinct - royale (9,2)/(9,16) sits ONE TILE
# from auroraveil (9,1)/(9,17), so EXACT match only, never a tolerance.
# glacierkeep moved off gungnir (71%) onto the simple rush (100%).
# royale is deliberately NOT here: it wins 100% vs the _hvadapt reference but
# 0/14 vs chimera's own eco - a rush map has to beat the bot it replaces.
SIMPLE_CORES = {
    # fjordgate + nordkap PULLED (2026-08-17 roster gate, 1260 games): the
    # 1-builder rush went 0-1/6 vs EVERY military archetype on them (wavebot,
    # dummy_siege, fen1/2, jav1, v108base, gungnir), 3/6 vs its own mirrors -
    # it only beats pure eco. Overall: nordkap 25%, fjordgate 30%, the two
    # worst maps in the matrix. The Bisons field win (nordkap t29) was one
    # anecdote vs one slow wave; six archetypes say otherwise.
    # 08-17 late: everything except icefloe MOVED to RB_CORES below - Oogway's
    # rushBest swept our s_main in the rush mirrors 6/6 (auroraveil t44,
    # drumlin t40, glacierkeep t50, drakkarfjord t58). icefloe stays s_main:
    # ours won that race 6/6 against his.
    (20, 20): frozenset({(1, 16), (17, 2)}),    # icefloe
}

# Oogway's rushBest (v140, rb_main): path seats + stuck2 + threat + SD.
# Panel: beats chimera11 71% head-to-head (its rush sweeps our eco AND our
# s_main) but loses the field referees (wavebot 32%, jav1 42%) - a better
# RUSH, not a better BOT. It gets exactly the maps where it swept our rush.
RB_CORES = {
    (20, 20): frozenset({(9, 1), (9, 17)}),     # auroraveil (rb; lkick only split 3/6)
    (30, 30): frozenset({(2, 24), (26, 4)}),    # drakkarfjord (rb; lkick 4/6 borderline)
}

# Oogway's lkick (v143 rushEcon + launcher-kick): beat the hybrid 69%
# head-to-head, jav1 53%, wavebot 52% (his wave fix). Gets the 8 maps it
# swept 6/6. Our modes keep the maps it went 0/6 on (antler/icefloe/midgard
# - picket, s_main race, big-map eco) and the wave-critical leftovers.
LK_CORES = {
    (10, 10): frozenset({(2, 2), (6, 6)}),      # fjordgate
    (20, 20): frozenset({(2, 9), (16, 9),       # frostgate (+yulerune, same fp)
                         (9, 2), (9, 16)}),     # royale
    (20, 26): frozenset({(9, 6), (9, 18)}),     # nordkap
    (25, 25): frozenset({(5, 5), (18, 18)}),    # drumlin
    (30, 30): frozenset({(14, 2), (14, 26),     # glacierkeep
                         (2, 14), (26, 14)}),   # valkyrie
}

ATTACK_MOD = _fi("ATTACK_MOD", 3)          # every Nth spawn is an attacker
DEFEND_NUMS = _int_set("DEFEND_NUMS", "4")
RECALL_HP = _fi("RECALL_HP", 400)          # keep BELOW CORE_MAX_HP=500
RECALL_HP_CRIT = _fi("RECALL_HP_CRIT", 200)
SLOT_CORE_THREAT = 7
SLOT_RECALL = 9
SLOT_BOOTSTRAP = 10   # 1 = no harvester income seen yet
# 8, 10-15 free - grep "SLOT_" across all 3 files before adding a new one


def core_footprint_manhattan(pos: Position, core: Position) -> int:
    return min(
        abs(pos.x - (core.x + dx)) + abs(pos.y - (core.y + dy))
        for dx in (0, 1) for dy in (0, 1)
    )


class Player:
    def __init__(self):
        self.chMode = 0        # SLOT_MODE verdict, latched on first run()
        self.gPlayer = None    # rush-mode delegate, built lazily
        self.sPlayer = None    # simple-rush delegate, built lazily
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.numEco = 0
        self.ecoTargets = []
        self.lastSpawn = -99

        self.mapW = None
        self.mapH = None
        self.allyBuilders = []   # refreshed once/turn, read by eco.py + attack.py
        self.myId = 0
        self.sawIncome = False
        self.lastTi = None

        # EXPLORE STATE (eco.scoreExplore). Per-unit, like mapPf.myNum: each
        # unit gets its own Player instance, so this latches THIS builder's
        # spawn target once and never sees another's.
        self.exploreSpot = None
        self.exploreLatched = False
        self.exploreDone = False

        eco.init_state(self)
        # NOTE: no attack.init_state - attack.py keeps no per-player state (it
        # only reads draw_state/mapW/mapH/mapPf, all set above). Calling a
        # non-existent one raised in __init__, which made unit 1 (the CORE) fail
        # to init and the whole team play ZERO units. Silent: `fcode run` reports
        # it as "[runner] unit N failed to init", not as a traceback.

    def draw_state(self, ct: Controller, color, target: Position = None, dot: bool = True):
        myLoc = ct.get_position()
        if target is not None:
            ct.draw_indicator_line(myLoc, target, *color)
        if dot:
            ct.draw_indicator_dot(myLoc, *color)

    def covered_tiles(self, ct: Controller) -> set:
        return attack.covered_tiles_by_turrets(ct, ct.get_team())

    def nearby_ally_builders(self, ct: Controller) -> list:
        myTeam = ct.get_team()
        allies = []
        for b in ct.get_nearby_units():
            if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.BUILDER_BOT:
                allies.append((b, ct.get_position(b)))
        return allies

    def dist_to_core(self, ct: Controller, pos: Position):
        myLoc = ct.get_position()
        coreCorners = [myLoc, myLoc.add(Direction.EAST), myLoc.add(Direction.SOUTH),
                       myLoc.add(Direction.SOUTH).add(Direction.EAST)]
        coreCorners.sort(key=lambda c: c.distance_squared(pos))
        return coreCorners[0].distance_squared(pos)

    def run_core(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        myTeam = ct.get_team()

        globalAmmo = ct.get_global_ammo()
        globalTitanium = ct.get_global_resources()

        # SPAWN RATE LIMIT: after the opening 5, respawns need an 8-round gap
        # so a death-loop faucet can't feed builders into the same kill zone.
        curRound = ct.get_current_round()

        # REBUILD-FOREVER TRICKLE: while a FRONT exists (slot 14 - our army
        # is engaged forward), respawns come cheaper and faster so the
        # stream of reinforcements to that front never stops. The monster
        # eco funds it; Lorem's grind is exactly this loop.
        if (self.numSpawned < 5
                or (globalTitanium > 360 and curRound - self.lastSpawn >= 8)
                or (ct.read_store(14) > 0 and globalTitanium > 200
                    and curRound - self.lastSpawn >= 6)):
            self.spawnBot(ct)

        ct.write_store(0, self.numSpawned)

        myLoc = ct.get_position()
        compressedLoc = (myLoc.x << 5) | myLoc.y

        teamBuilders = []
        enemyBuilderClose = False
        for u in ct.get_nearby_units():
            if ct.get_team(u) == myTeam and ct.get_entity_type(u) == EntityType.BUILDER_BOT:
                teamBuilders.append(ct.get_position(u))
            elif ct.get_team(u) != myTeam and ct.get_entity_type(u) == EntityType.BUILDER_BOT:
                if self.dist_to_core(ct, ct.get_position(u)) <= 20:
                    enemyBuilderClose = True
        enemyTurretSeen = False
        enemyTurrets = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            enemyTurretSeen = True
            gPos = ct.get_position(b)
            if any(tb.distance_squared(gPos) < 16 for tb in teamBuilders):
                continue # a team builder is already close, they can handle it
            enemyTurrets.append(gPos)
        # furthest from the core first: the near ones already have a builder on
        # them (filtered above), so the far ones are the unanswered threats
        enemyTurrets.sort(key=lambda turretPos: self.dist_to_core(ct, turretPos), reverse=True)
        for i, gPos in enumerate(enemyTurrets[:2]): # only 2 fit in the slot
            dx = gPos.x - myLoc.x
            dy = gPos.y - myLoc.y
            if -8 <= dx <= 7 and -8 <= dy <= 7: # 4-bit signed each, else unsendable
                compressedLoc |= (((dx & 0xF) << 4) | (dy & 0xF)) << (10 + 8 * i)

        ct.write_store(7, compressedLoc)


        _hp = ct.get_hp()
        ct.write_store(SLOT_RECALL, _hp)

        if self.lastTi is not None and globalTitanium > self.lastTi and curRound % 4 != 0:
            self.sawIncome = True
        self.lastTi = globalTitanium

        ct.write_store(SLOT_BOOTSTRAP, 0 if self.sawIncome else 1)

        reserve = 28 if self.sawIncome else max(28, ct.get_harvester_cost())
        # AMMO CEILING: a bot choice, not an engine cap - there is no MAX_AMMO.
        # Swept 2026-08-14 at 5 seeds vs a frozen ammo-16 control, 150 games ea:
        #   16 = 50.0% (control)   20 = 54.0% [46.0, 62.0]   24 = 57.3% [49.4, 65.2]
        # Monotone but inside the 52.1% mirror-gate noise floor; adopted on the
        # trend with bounded downside. A sentinel shot costs 10, so 16 allowed
        # only one queued shot plus change.
        AMMO_CEILING = 24
        # WAR AMMO: with the pool capped at 24 (six gunner shots TEAM-WIDE),
        # a home gunner clearing a sentinel wave (23+ shots) fires 1-2 rounds
        # between refills while the wave pumps 9 hp/turn into the core - the
        # Bisons loss had one covered sentinel live 42 turns. Any enemy turret
        # in core vision, or an enemy builder within footprint-20 (a planter
        # walking in), floods the pool so defense fire is continuous. Reserve
        # is untouched, so building economy keeps its floor.
        if enemyTurretSeen or enemyBuilderClose:
            AMMO_CEILING = 96
            # NOTE: do NOT raise the Ti reserve here "so protect can afford
            # seats" - tried as max(reserve, gunner_cost+10) and it gated
            # 41-43% three times (antler 0-2/10, ragnarok 0-2/10): on knife-
            # fight maps the war state is PERMANENT, so the inflated reserve
            # permanently pinches the economy. The starvation it fixed was
            # worth ~2 turns on the nordkap referee - not worth this.
        convertAmount = min(AMMO_CEILING - globalAmmo, globalTitanium - reserve)
        if convertAmount > 0 and ct.can_convert_ammo(convertAmount):
            ct.convert_ammo(convertAmount)

    def spawnBot (self, ct: Controller):
        nearbyOres = []
        for tile in ct.get_nearby_tiles():
            if ct.get_tile_env(tile) == Environment.ORE_TITANIUM:
                nearbyOres.append(tile)
        nearbyOres.sort(key=lambda ore: self.dist_to_core(ct, ore))
        numOres = len(nearbyOres)
        
        spawnableTiles = []
        for tile in ct.get_nearby_tiles():
            if ct.can_spawn(tile):
                spawnableTiles.append(tile)

        if spawnableTiles:
            mapCenter = Position(self.mapW // 2, self.mapH // 2)
            nextNum = self.numSpawned + 1

            if nextNum % ATTACK_MOD == 0: # attacking bots

                spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(mapCenter))
                closestTile = spawnableTiles[0]
                ct.spawn_builder(closestTile)
                self.numSpawned += 1
                self.lastSpawn = ct.get_current_round()

            else: # eco/defense bot

                if numOres > self.numEco:
                    targetSpot = nearbyOres[self.numEco]
                else:
                    targetSpot = self.pickSpawnTarget(ct)
                if targetSpot is None:
                    targetSpot = mapCenter

                spawnableTiles.sort(key=lambda spawnableTile: spawnableTile.distance_squared(targetSpot))
                closestTile = spawnableTiles[0]
                ct.spawn_builder(closestTile)
                ct.draw_indicator_line(closestTile, targetSpot, 40, 100, 30)
                # +1 SENTINEL: read_store returns 0 for a slot the core has
                # never written, and a raw 0 decodes to Position(0,0) - a real
                # map corner. Offsetting by 1 makes "no target yet" and "target
                # is the top-left tile" distinguishable. eco.scoreExplore reads
                # this back via the latch in builder_bot.
                ct.write_store(8, targetSpot.x + targetSpot.y * 32 + 1)
                self.ecoTargets.append(targetSpot)
                self.numSpawned += 1
                self.numEco += 1
                self.lastSpawn = ct.get_current_round()

    def pickSpawnTarget (self, ct: Controller):
        """Pick a spawn target far from the core, spread away from recent ones.

        SPEED: the old form called dist_to_core() once per candidate tile, and
        that helper does 1 ENGINE CALL (ct.get_position()) plus 3 Position.add,
        5 distance_squared and a 4-element list sort - every time. Over ~108
        nearby tiles that is 108 engine calls per spawn. Measured 0.63ms/call;
        this version measures 0.05ms - a ~12.6x cut on the same maps and seed.

        get_position() is hoisted out (1 call, not 108) and the min over the 2x2
        core footprint is computed directly: the corner set is the product
        {cx,cx+1} x {cy,cy+1}, so min-over-corners of (dx^2 + dy^2) equals
        (min over x) + (min over y). No Position objects, no sort.

        Semantics are unchanged: same >25 filter, same score, same strict-> argmax.
        """
        myLoc = ct.get_position()
        cx = myLoc.x; cy = myLoc.y
        cx1 = cx + 1; cy1 = cy + 1
        # last 4 only - ecoTargets grows every eco spawn and is never trimmed
        recent = [(e.x, e.y) for e in self.ecoTargets[-4:]]
        bestScore = -1
        bestTarget = None
        for spawnTarget in ct.get_nearby_tiles():
            tx = spawnTarget.x; ty = spawnTarget.y
            ax = tx - cx
            if ax < 0: ax = -ax
            bx = tx - cx1
            if bx < 0: bx = -bx
            if bx < ax: ax = bx
            ay = ty - cy
            if ay < 0: ay = -ay
            by = ty - cy1
            if by < 0: by = -by
            if by < ay: ay = by
            targetScore = ax * ax + ay * ay
            if targetScore <= 25:
                continue
            for ex, ey in recent:
                dxe = tx - ex; dye = ty - ey
                targetScore *= dxe * dxe + dye * dye
            if targetScore > bestScore:
                bestTarget = spawnTarget
                bestScore = targetScore
        return bestTarget

    def answer_recall(self, ct: Controller, myLoc) -> bool:
        if self.mapPf.teamCore is None:
            return False
        enemy = self.mapPf.enemyCorePos
        dHome = myLoc.distance_squared(self.mapPf.teamCore)
        if enemy is not None and dHome > myLoc.distance_squared(enemy):
            return False
        if eco.heal_damaged_non_core(ct, self):
            return True
        isClose = False
        teamCore = self.mapPf.teamCore
        coreTiles = [teamCore, teamCore.add(Direction.EAST), teamCore.add(Direction.SOUTH), teamCore.add(Direction.SOUTH).add(Direction.EAST)]  
        for tile in coreTiles:
            if myLoc.distance_squared(tile) < 2:
                isClose = True
        if isClose:
            self.draw_state(ct, eco.C_HEAL_CORE, self.mapPf.teamCore)
            
            for tile in coreTiles:
                if myLoc.distance_squared(tile) == 1 and ct.can_heal(tile):
                    ct.heal(tile)
                    return True
            return True
        self.draw_state(ct, eco.C_HEAL_CORE, self.mapPf.teamCore)
        self.mapPf.moveTo(ct, self.mapPf.teamCore)
        return True

    def far_core_corner(self) -> Position:
        core = self.mapPf.teamCore
        center = Position(self.mapW // 2, self.mapH // 2)
        corners = [core, core.add(Direction.EAST), core.add(Direction.SOUTH),
                   core.add(Direction.SOUTH).add(Direction.EAST)]
        return max(corners, key=lambda corner: corner.distance_squared(center))

    def builder_bot(self, ct: Controller):
        myLoc = ct.get_position()
        self.mapPf.setupMap(ct)
        self.allyBuilders = self.nearby_ally_builders(ct)
        self.myId = ct.get_id()

        # LATCH THE EXPLORE TARGET, once, on this builder's first turn. The core
        # overwrites slot 8 on EVERY eco spawn, so it only holds our target for
        # the moment right after we were spawned - reading it later would give
        # us somebody else's. Safe because the core spawns at most one builder
        # per turn (self.lastSpawn throttles it).
        if not self.exploreLatched:
            self.exploreLatched = True
            _v = ct.read_store(8)
            if _v > 0:                      # 0 = core never wrote one
                _v -= 1                     # undo the +1 sentinel
                _x, _y = _v % 32, _v // 32
                if 0 <= _x < self.mapW and 0 <= _y < self.mapH:
                    self.exploreSpot = Position(_x, _y)

        if self.mapPf.myNum in DEFEND_NUMS and self.mapPf.teamCore is not None:
            self.mapPf.setMoveZone(self.mapPf.teamCore, self.far_core_corner())

        myTeam = ct.get_team()
        for _b in ct.get_nearby_buildings():
            if ct.get_team(_b) != myTeam and ct.get_entity_type(_b) == EntityType.CONVEYOR:
                _p = ct.get_position(_b)
                self.mapPf.enemyConvSeen.add((_p.x, _p.y))

        if ct.can_act() and ct.get_global_resources() >= 28:
            for _d in CARDINALS:
                _n = myLoc.add(_d)
                if (( _n.x, _n.y) in self.mapPf.freshEnemyCuts
                        and ct.get_tile_building_id(_n) is None
                        and ct.can_build_barrier(_n)):
                    ct.build_barrier(_n)
                    del self.mapPf.freshEnemyCuts[(_n.x, _n.y)]
                    return

        # Recall is now a SCORED state inside eco.run (see eco.scoreRecall), so it
        # competes with protect/heal/route/harvest instead of preempting them.
        # This unconditional form is kept only for A/B measurement.
        if not eco.RECALL_STATE:
            coreHp = ct.read_store(SLOT_RECALL)
            if coreHp < 120 or (coreHp < 350 and (self.mapPf.myNum) % 3 == 1):
                if self.answer_recall(ct, myLoc):
                    return
    

        if (self.mapPf.myNum % ATTACK_MOD == 0
                or (self.mapPf.myNum > 5 and ct.read_store(14) > 0)):
            # REBUILD-FOREVER (v157 batch went 7W-13L, all losses the grind
            # class - 1-in-3 replacement walkers trickle and die piecemeal):
            # while a FRONT is hot (slot 14), every post-eco respawn is a
            # SOLDIER, front-routed on arrival (v153). Eco is built by spawns
            # 1-5; wartime replacements are all army - Lorem's loop closed.
            attack.run(ct, self)
        else:
            eco.run(ct, self)

    def run(self, ct: Controller) -> None:
        if self.chMode == 0:
            mode = ct.read_store(SLOT_MODE)
            if mode == 0 and ct.get_entity_type() == EntityType.CORE:
                me = ct.get_position()
                key = (ct.get_map_width(), ct.get_map_height())
                sc = SIMPLE_CORES.get(key)
                rc = RUSH_CORES.get(key)
                rb = RB_CORES.get(key)
                lk = LK_CORES.get(key)
                if lk and (me.x, me.y) in lk:
                    mode = 5
                elif rb and (me.x, me.y) in rb:
                    mode = 4
                elif sc and (me.x, me.y) in sc:
                    mode = 3
                elif rc and (me.x, me.y) in rc:
                    mode = 2
                else:
                    mode = 1
                ct.write_store(SLOT_MODE, mode)
            self.chMode = mode if mode else 1
            if self.chMode == 2:
                self.gPlayer = g_main.Player()
            elif self.chMode == 3:
                self.sPlayer = s_main.Player()
            elif self.chMode == 4:
                self.sPlayer = rb_main.Player()
            elif self.chMode == 5:
                self.sPlayer = lk_main.Player()
        if self.chMode == 2:
            return self.gPlayer.run(ct)
        if self.chMode in (3, 4, 5):
            return self.sPlayer.run(ct)

        if self.mapW is None:
            self.mapH = ct.get_map_height()
            self.mapW = ct.get_map_width()

        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.run_core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builder_bot(ct)
        elif etype == EntityType.GUNNER:
            attack.run_gunner(ct, self)
        elif etype == EntityType.SENTINEL:
            attack.run_sentinel(ct, self)
