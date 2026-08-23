"""fp1 - entry point. Player owns ALL per-unit state and dispatches by unit type.

Behaviour lives in three mixins - EcoBot (eco.py), AttackBot (attack.py) and
GunnerBot (gunner.py) - rather than in free functions taking a bot argument. That
way every field is plain `self.*` and there is exactly ONE place state is
created: __init__ below. Each unit gets its own Player instance, so nothing here
is shared between units - the only cross-unit channel is the 16-slot store.

STORE SLOTS
  0     bots spawned so far. REQUIRED: mapPathfinding.shareTiles does
        `curRound % read_store(0)`, so a 0 is a ZeroDivisionError, and every unit
        latches its own mapPf.myNum from it. myNum == 1 therefore identifies the
        FIRST builder, which is how the attacker knows what it is - no slot is
        spent on roles. Written EVERY core turn, after spawning.
  1-6   RESERVED: a 192-bit tile-sharing bus (shareTiles writes, updateBoard
        reads). Writing anything else here corrupts the shared map team-wide.
  7     core position (x<<5|y) plus up to two enemy-turret offsets as 4-bit signed
        dx,dy at bits 10 and 18. Rewritten every turn, so a dead threat simply
        stops being packed and no TTL is needed.
  8     spawn target for the bot just spawned, x + y*32 + 1. The +1 matters:
        read_store returns 0 for an unwritten slot, and a raw 0 would decode to
        Position(0, 0), a real map corner.
  9-15  free.
Writes are buffered: a value written on round N is visible from round N+1. The
core spawns at most one builder per turn, so slot 8 is unambiguous - the builder
reads it on its own first turn, which is the round after it was written.

No exception handlers, deliberately: an uncaught exception PERMANENTLY destroys
the unit, so every raising engine call is guarded by a type/vision/bounds test
instead.
"""

from fcode import Controller, EntityType, Environment, Position
from mapPathfinding import MapPathfinder
SPAWN_FAR = 25
import eco
import attack
import gunner
import spear

SLOT_MODE = 15      # 0 undecided, 1 = fp engine, 2 = spear engine
SPEAR_DIST = 44     # MEASURED ON THE FINALS MAPS (maps_finals/, 2026-08-23):
                    # hybrid5 PROMOTES 55% on the league pool but REJECTS 43%
                    # on unfamiliar geometry, and the per-map split says why -
                    # spear mode wins 100% at core distance 52 and 48 and 0%
                    # at 36 (open_mid, doorstep, pockets) and 24 (broadside).
                    # 26 was fitted to the league pool's distance spread, so it
                    # sends us to spear mode across a whole band where the spear
                    # loses. 44 keeps the mode only where it measurably pays.
                    # Original note: core-to-core manhattan at or above which
                    # the spear is measured to dominate


class Player(eco.EcoBot, attack.AttackBot, gunner.GunnerBot):
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.spear = None       # lazily built when the map calls for it
        self.mapW = None
        self.mapH = None

        # --- core only ---
        self.numSpawned = 0
        self.lastCoreHp = None
        self.hurtRound = 0
        self.numOre = 0            # ore openers dispatched so far (max 3)
        self.oreTiles = []         # spawn tiles already taken by an ore opener
        self.recentTiles = []      # the last 4 spawn tiles used, for the dedup
        self.recentTargets = []    # targets handed out, for the spread term

        # --- builder identity, latched once from the store on turn 1 ---
        self.spawnTarget = None
        self.latched = False
        self.lastBand = None
        self.allyPos = []          # team builders in vision, refreshed each turn

        # --- builder economy ---
        self.norms = None          # (core, self, target) falloff normalisers
        self.myOre = None          # committed claim; never re-ranked while walking
        self.myOreScore = 0.0
        self.myHarvester = None    # the harvester THIS bot built
        self.chainDone = False     # a segment of my chain points INTO a core tile
        self.oreTaken = {}         # (x,y) -> round we last saw a building on that ore
        self.ringTurns = 0         # turns spent on the opening core ring
        self.ringPlaced = False    # this builder's one ring conveyor is up
        self.ringPick = None
        self.projectEnd = None     # open end of MY conveyor project
        self.builtConv = set()     # tiles I put a conveyor on, for repair
        self.projectSuper = False  # my project reached the core -> guard it
        self.guardGoal = None      # patrol endpoint while guarding
        self.patrolSeen = {}       # waypoint -> round last visited

        # --- routing state read by the carried convroute block ---
        self.convMap = None
        self.convDirs = {}
        self.convLoop = {}
        self.convRound = -1
        self._fDist = None
        self._fStat = None

        # --- gunner ---
        self.rotations = 0
        self.idleTurns = 0

        # --- attacker memory. One attacker, never replaced, so this stays
        # --- coherent all game; it dies with the unit. ---
        self.oreHadHarv = set()    # (x,y) that held an enemy harvester
        self.convTiSeen = {}       # (x,y) -> round an enemy conveyor held titanium
        self.banned = {}           # (x,y) -> round a ban expires (its HP rose)
        self.hpSeen = {}           # (x,y) -> last observed HP, for the trend test

    # ------------------------------------------------------------------ run

    def run(self, ct: Controller) -> None:
        if self.mapW is None:
            self.mapW = ct.get_map_width()
            self.mapH = ct.get_map_height()

        # MAP DISPATCH. Measured head-to-head against this very engine, the
        # sentinel spear's record is decided by core-to-core distance:
        #   dist <= 20  ->  0-2 wins of 4      (fp engine is better)
        #   dist 24     ->  2 of 4
        #   dist >= 28  ->  4 of 4 EVERY MAP   (jotunheim, icefloe,
        #                                       yggdrasil, midgard)
        # A long march means the defender's economy and counter-attack
        # arrive too late to answer four sentinels; a short one means they
        # arrive in time. So pick the engine the map calls for. The core
        # decides on its first turn and publishes to slot 15; the spear
        # engine never writes that slot.
        mode = ct.read_store(SLOT_MODE)
        if mode == 0 and ct.get_entity_type() == EntityType.CORE:
            me = ct.get_position()
            foe_x = self.mapW - 2 - me.x
            foe_y = self.mapH - 2 - me.y
            dist = abs(me.x - foe_x) + abs(me.y - foe_y)
            mode = 2 if dist >= SPEAR_DIST else 1
            ct.write_store(SLOT_MODE, mode)
        if mode == 2:
            if self.spear is None:
                self.spear = spear.SpearPlayer()
            return self.spear.run(ct)

        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.run_core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.run_builder(ct)
        elif etype == EntityType.GUNNER:
            # Without this a placed gunner is 20 Ti of scenery.
            self.run_gunner(ct)
        elif etype == EntityType.SENTINEL:
            # fp14: sentinels re-added ON EVIDENCE - 100% of core damage in
            # the Leviathan/Juusto forensics (both directions) was sentinel
            # -18; their fire is INDIRECT so the meta's barrier cages never
            # block it. Deploy is CONDITIONAL (see atk_sent_siege) so the
            # open-field game stays pure fp.
            self.run_sentinel(ct)

    # ----------------------------------------------------------------- core

    def run_core(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        myTeam = ct.get_team()

        # AMMO. Ammo starts at 0 with no passive income and convert_ammo is the
        # only source, so without this no turret ever fires. It does NOT consume
        # the core's action cooldown, so it never costs a spawn - the two compete
        # for titanium only. Ceiling 20 banks five gunner shots; the 60 floor keeps
        # converting from ever starving a build.
        want = 20 - ct.get_global_ammo()
        # Never convert away the price of a conveyor: an unconnected harvester
        # yields nothing, so a chain stranded for want of one 3-Ti segment costs
        # far more than the ammo. Scales with the team's building count.
        spare = ct.get_global_resources() - ct.get_conveyor_cost() * 4
        amt = want if want < spare else spare
        if amt > 0 and ct.can_convert_ammo(amt):
            ct.convert_ammo(amt)

        if self.spawn_allowed(ct):
            self.spawn_bot(ct)
        ct.write_store(0, self.numSpawned)
        ct.write_store(7, self.pack_threats(ct, myLoc, myTeam))
        # Slot 9: the round the core last LOST hp. A direct measurement of
        # being attacked - no inference about the opponent, and it keeps
        # working against an opponent whose units we never see.
        _hp = ct.get_hp()
        if self.lastCoreHp is not None and _hp < self.lastCoreHp:
            self.hurtRound = ct.get_current_round()
        self.lastCoreHp = _hp
        ct.write_store(9, self.hurtRound)

    def spawn_allowed(self, ct: Controller) -> bool:
        if ct.get_action_cooldown() != 0:
            return False
        if self.numSpawned < 4:
            # THE FOUR OPENERS: at least four bots go out regardless of balance,
            # as soon as each is affordable.
            return ct.get_global_resources() >= ct.get_builder_bot_cost()
        # CREW FLOOR: below 4 living units (get_unit_count incl. core), spawn
        # whenever affordable - the 349 gate is ~140 passive-income rounds
        # away after a wipe and the team is dead long before.
        if ct.get_unit_count() < 4:
            return ct.get_global_resources() >= ct.get_builder_bot_cost()
        # Then one more bot per turn the balance is over 349, tested BEFORE paying
        # the builder's cost, with no minimum round gap between spawns.
        return ct.get_global_resources() > 349

    def spawn_bot(self, ct: Controller) -> None:
        # The spawn ring is exactly the 12 tiles at distance_squared 1-2 from the
        # 2x2 footprint; can_spawn also covers affordability and the 50-unit cap.
        spawnable = [t for t in ct.get_nearby_tiles() if ct.can_spawn(t)]
        if not spawnable:
            return
        myLoc = ct.get_position()

        # target 0 = "no spawn target". Only bots 5+ get one; the attacker knows
        # its job from myNum == 1, and an ore opener's target IS its ore.
        target = None

        if self.numSpawned == 0:
            # THE ATTACKER, first spawn, on the spawnable tile nearest the enemy
            # core. No ore and no spawn target.
            tile = min(spawnable,
                       key=lambda t: t.distance_squared(self.enemy_core_guess(myLoc)))
        else:
            ores = self.nearby_ores(ct, myLoc)
            if self.numOre < 3 and self.numOre < len(ores):
                # ORE OPENERS: up to three bots, each taking the next-nearest ore
                # and spawning on the spawnable tile closest to THAT ore. Two ore
                # bots may never share a spawn tile; the exclusion is dropped
                # rather than losing the spawn. The ore travels through slot 8 and
                # the builder ASSIGNS it to itself (self.myOre) on latch.
                target = ores[self.numOre]
                cands = [t for t in spawnable
                         if (t.x, t.y) not in self.oreTiles] or spawnable
                tile = min(cands, key=lambda t: t.distance_squared(target))
                self.oreTiles.append((tile.x, tile.y))
                self.numOre += 1
            else:
                # EVERYONE ELSE: spawnable tiles in order of distance to the map
                # centre, skipping the last 4 tiles used so consecutive bots fan
                # out. The dedup is dropped rather than allowed to starve a spawn.
                # TARGET FIRST, then the spawn tile nearest it. The old form
                # derived the target FROM the tile, and chose the tile "nearest the
                # map centre" - so every bot 5+ left by the same lane and the whole
                # economy clustered centreward (seen directly in a replay). Scoring
                # TARGETS lets the spread term be multiplicative over recent
                # targets, which is what actually separates directions.
                target = self.pick_spawn_target(ct, myLoc)
                if target is None:
                    target = Position(self.mapW // 2, self.mapH // 2)
                tile = min(spawnable, key=lambda t: t.distance_squared(target))
                self.recentTargets.append((target.x, target.y))
                if len(self.recentTargets) > 4:
                    self.recentTargets.pop(0)

        ct.spawn_builder(tile)
        # 0 encodes "none": read_store returns 0 for an unwritten slot, and the +1
        # keeps a real Position(0, 0) from colliding with it.
        ct.write_store(8, 0 if target is None else target.x + target.y * 32 + 1)
        if target is not None:
            ct.draw_indicator_line(tile, target, 40, 100, 30)
        self.numSpawned += 1
        self.recentTiles.append((tile.x, tile.y))
        if len(self.recentTiles) > 4:
            self.recentTiles.pop(0)

    def pick_spawn_target(self, ct: Controller, core: Position):
        """A tile far from the core and spread away from the last few targets.

        score = dsq(tile, core footprint) * PRODUCT over recent targets of
        dsq(tile, that target)

        MULTIPLICATIVE on purpose: a tile near ANY recent target is crushed, while
        an additive spread term lets one far axis mask a collision. The
        SPAWN_FAR filter keeps targets off our own doorstep.

        The footprint minimum is arithmetic, not a sort: the corner set is the
        product {cx,cx+1} x {cy,cy+1}, so min-over-corners of dx^2+dy^2 equals
        (min over x) + (min over y). That avoids an engine call and a 4-element
        sort per candidate tile - the documented dist_to_core pathology, which
        measured 108 engine calls per spawn."""
        cx, cy = core.x, core.y
        recent = self.recentTargets[-4:]
        best, bestT = -1, None
        for t in ct.get_nearby_tiles():
            ax = t.x - cx
            if ax < 0:
                ax = -ax
            bx = t.x - (cx + 1)
            if bx < 0:
                bx = -bx
            if bx < ax:
                ax = bx
            ay = t.y - cy
            if ay < 0:
                ay = -ay
            by = t.y - (cy + 1)
            if by < 0:
                by = -by
            if by < ay:
                ay = by
            score = ax * ax + ay * ay
            if score <= SPAWN_FAR:
                continue
            for ex, ey in recent:
                dx = t.x - ex
                dy = t.y - ey
                score *= dx * dx + dy * dy
            if score > best:
                best, bestT = score, t
        return bestT

    def nearby_ores(self, ct: Controller, myLoc: Position) -> list:
        """Ore the CORE can see (r^2=36, about 6 tiles), sorted by MANHATTAN
        distance to the 2x2 footprint. Ore beyond core vision is invisible here -
        only the builders' shared fullMap knows about it - which is why the third
        opener can find nothing on a big map and falls through to the map-centre
        branch."""
        ores = [t for t in ct.get_nearby_tiles()
                if ct.get_tile_env(t) == Environment.ORE_TITANIUM]
        ores.sort(key=lambda o: self.footprint_manhattan(o, myLoc))
        return ores

    @staticmethod
    def footprint_manhattan(pos: Position, core: Position) -> int:
        return min(abs(pos.x - (core.x + dx)) + abs(pos.y - (core.y + dy))
                   for dx in (0, 1) for dy in (0, 1))

    def enemy_core_guess(self, myLoc: Position) -> Position:
        """The enemy core sits at the ROTATIONAL opposite even on maps whose tile
        symmetry is a reflection - it is a core-placement rule, not a terrain
        inference. Clamped, because nothing else bounds-checks it."""
        ec = self.mapPf.enemyCorePos
        if ec is not None:
            return ec
        x = min(max(self.mapW - myLoc.x - 2, 0), self.mapW - 1)
        y = min(max(self.mapH - myLoc.y - 2, 0), self.mapH - 1)
        return Position(x, y)

    def outward_target(self, tile: Position, core: Position) -> Position:
        """The core-CENTRE -> spawn-tile direction, run outward to manhattan 12.
        The centre is (cx + 0.5, cy + 0.5), not the footprint corner, so the eight
        ring tiles give eight distinct directions instead of collapsing pairs of
        them. Purely a scoring ANCHOR, so it need not be passable, only in
        bounds."""
        cx, cy = core.x + 0.5, core.y + 0.5
        dx, dy = tile.x - cx, tile.y - cy
        m = abs(dx) + abs(dy)
        if m == 0:
            return Position(self.mapW // 2, self.mapH // 2)
        scale = 12.0 / m
        x = min(max(int(round(cx + dx * scale)), 0), self.mapW - 1)
        y = min(max(int(round(cy + dy * scale)), 0), self.mapH - 1)
        return Position(x, y)

    def pack_threats(self, ct: Controller, myLoc: Position, myTeam) -> int:
        """Core position plus up to two enemy turrets in one int. Core vision is
        r^2=36 against a builder's r^2=20, so the core is the best sensor for
        threats near itself, and the store reaches every unit with no vision
        requirement and no scan cost."""
        packed = (myLoc.x << 5) | myLoc.y
        turrets = [ct.get_position(b) for b in ct.get_nearby_buildings()
                   if ct.get_team(b) != myTeam
                   and ct.get_entity_type(b) in (EntityType.GUNNER, EntityType.SENTINEL)]
        turrets.sort(key=lambda p: self.footprint_manhattan(p, myLoc))
        for i, pos in enumerate(turrets[:2]):
            dx, dy = pos.x - myLoc.x, pos.y - myLoc.y
            if -8 <= dx <= 7 and -8 <= dy <= 7:      # 4-bit signed each
                packed |= (((dx & 0xF) << 4) | (dy & 0xF)) << (10 + 8 * i)
        return packed

    # -------------------------------------------------------------- builder

    def run_builder(self, ct: Controller) -> None:
        self.mapPf.setupMap(ct)
        if not self.latched:
            # Once, on turn 1: slot 8 is overwritten by the next spawn, so reading
            # it later would pick up somebody else's target. 0 = "no target",
            # which is what the attacker is given.
            self.latched = True
            v = ct.read_store(8)
            if v > 0:
                v -= 1
                x, y = v % 32, v // 32
                if 0 <= x < self.mapW and 0 <= y < self.mapH:
                    self.spawnTarget = Position(x, y)
                    # An ore opener is ASSIGNED its ore, not merely anchored on it.
                    # If the tile is still unknown to THIS bot on turn 1 (the core
                    # sees r^2=36, a builder r^2=20) the assignment is not lost:
                    # eco step 8 takes a spawn target that is ore as its first
                    # claim without scanning, and it re-checks every turn.
                    if self.mapPf.fullMap is not None \
                            and self.mapPf.fullMap[x][y] == 1:
                        self.myOre = self.spawnTarget
        # Role from spawn ORDER, not a store slot: myNum is latched from slot 0
        # (bots spawned so far), so the first builder reads 1.
        if self.mapPf.myNum == 1 or self.mapPf.myNum % 5 == 0:
            self.run_attack(ct)
        else:
            self.run_eco(ct)
