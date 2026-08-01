"""STRIKE v1 - a delivery-first bot.

The budget, straight from GameConstants: a core has 500 HP, a gunner does 10
damage on a 1-turn cooldown for 2 ammo, and ammo converts 1:1 from titanium,
once per team per turn, usable the same turn. So a kill is 50 shots = 100 ammo
= 100 Ti, plus 10 gunners at 10 Ti = 100 Ti. TWO HUNDRED TITANIUM against the
500 every core starts with.

The whole kill is funded at turn zero. Ten guns in the firing band end a game in
five turns of fire; Pantheon's median game is 58 turns and only ~3 of those are
shooting. The other 55 are walking. This is a LOGISTICS problem, and every bot
in bots/ - ours worst of all - plays it as an economy problem: we lay 94
conveyors and 6.5 harvesters before landing 2.6 guns anywhere that matters.

So this bot has no economic opening. It spends the starting bank on builders,
walks them straight at the enemy core, and lays a launcher relay on the way: a
launcher throws a friendly builder standing 1-2 tiles away up to 7 tiles on a
1-turn cooldown, so spacing them ~6 apart turns a 30-turn walk into a few hops,
and the road then serves every builder that follows.

Chassis is deliberately NOT from scratch - pathfinding, symmetry and the
core-seat firing checks are the proven generalist-v3 modules. bastion failed
because a new thesis on a new engine loses before the thesis can matter. Only
the POLICY here is new.

MEASURED CAVEAT: grafting the same relay onto exp_siege_on_sight scored 33%
(CI 28-38) because road-building delayed the first gun t35 -> t58. Volume alone
did not pay. This bot only makes sense if the road is the plan from round 1
rather than a tax on a siege that already works.
"""
from fcode import Controller, Direction, EntityType, Environment, Position
from symmetry import SymmetryTracker
from mapPathfinding import *

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

SLOT_ENEMY_CORE = 11

RELAY_SPACING = 6        # a throw from one launcher lands in the next one's pickup range
RELAY_MIN_GAIN = 3       # never spend a throw on a trivial advance
RELAY_MAX = 4
RELAY_RESERVE = 160      # keep guns + the ammo conversion funded before road
AMMO_TARGET = 120        # 100 ammo pays for a whole core; hold a margin
GUN_BAND = 6             # a gun outside this cannot reach their core
STRIKE_BUILDERS = 8
# strike-v1 measured: perfect placement (15/15 guns on the enemy core) and a
# competitive first gun at t32, and it still lost at 27% because it only ever
# built 1.9 guns. It starved. The 500 bank funds the theoretical 200-Ti kill
# exactly once, against someone who never shoots back - guns die and must be
# replaced, and passive income is 10 Ti per 4 turns.
# Pantheon does NOT run zero economy: 4.1 harvesters and 17.7 conveyors, a lean
# supply line feeding continuous gun production. That is the level to hit -
# ours is 5.4 and 31.9, strike-v1 was 0 and 0.
HARVESTER_TARGET = 4


def pack_position(pos: Position) -> int:
    return ((pos.x + 1) << 6) | (pos.y + 1)


def unpack_position(value: int):
    if value == 0:
        return None
    return Position((value >> 6) - 1, (value & 0x3F) - 1)


class Player:
    def __init__(self):
        self.mapPf = MapPathfinder()
        self.numSpawned = 0
        self.mapW = None
        self.mapH = None
        self.symmetry = None
        self.symmetryVersion = 0
        self.enemyCorePos = None

    # ---------------------------------------------------------------- core

    def runCore(self, ct: Controller) -> None:
        titanium = ct.get_global_resources()
        # Ammo IS the weapon: 1:1, once per turn, usable immediately. There is
        # no reason to sit on titanium we are not about to spend on guns.
        ammo = ct.get_global_ammo()
        if ammo < AMMO_TARGET:
            want = min(AMMO_TARGET - ammo, max(titanium - 150, 0))
            if want > 0 and ct.can_convert_ammo(want):
                ct.convert_ammo(want)
        self.numSpawned = ct.read_store(0)
        if self.numSpawned < STRIKE_BUILDERS:
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    ct.spawn_builder(tile)
                    self.numSpawned += 1
                    ct.write_store(0, self.numSpawned)
                    return

    # ------------------------------------------------------------ launcher

    def runLauncher(self, ct: Controller) -> None:
        """Throw any friendly builder that walks past, toward their core."""
        target = self._enemy_core_target()
        if target is None:
            return
        me = ct.get_position()
        my_team = ct.get_team()
        tiles = ct.get_attackable_tiles_from(
            me, Direction.NORTH, EntityType.LAUNCHER)
        if not tiles:
            return
        for uid in ct.get_nearby_units():
            if (ct.get_team(uid) != my_team
                    or ct.get_entity_type(uid) != EntityType.BUILDER_BOT):
                continue
            bot = ct.get_position(uid)
            here = abs(bot.x - target.x) + abs(bot.y - target.y)
            best, best_d = None, here - RELAY_MIN_GAIN
            for t in tiles:
                d = abs(t.x - target.x) + abs(t.y - target.y)
                if d < best_d and ct.can_launch(bot, t):
                    best, best_d = t, d
            if best is not None:
                ct.launch(bot, best)
                return

    # ------------------------------------------------------------- builder

    def builderBot(self, ct: Controller) -> None:
        self.mapPf.setupMap(ct)
        self._update_enemy_core(ct)
        target = self._enemy_core_target()
        if target is None:
            return
        myLoc = ct.get_position()
        dist = abs(myLoc.x - target.x) + abs(myLoc.y - target.y)

        # SUPPLY LINE FIRST, but only just enough of one. A builder standing on
        # ore early takes it; nobody detours for it and nobody lays conveyor.
        if self._take_nearby_ore(ct, myLoc):
            return

        if dist <= GUN_BAND + 2:
            if self._build_core_gun(ct, myLoc, target):
                return
            self.mapPf.moveTo(ct, target)
            return

        if self._lay_relay(ct, myLoc, target):
            return
        self.mapPf.moveTo(ct, target)

    def _take_nearby_ore(self, ct: Controller, myLoc: Position) -> bool:
        """Build a harvester if one is free right here. No detours, no chains."""
        if not ct.can_act():
            return False
        built = ct.read_store(1)
        if built >= HARVESTER_TARGET:
            return False
        for d in CARDINALS:
            spot = myLoc.add(d)
            if ct.get_tile_env(spot) != Environment.ORE_TITANIUM:
                continue
            if ct.get_tile_building_id(spot) is not None:
                continue
            if ct.can_build_harvester(spot):
                ct.build_harvester(spot)
                ct.write_store(1, built + 1)
                return True
        return False

    def _build_core_gun(self, ct: Controller, myLoc: Position,
                        target: Position) -> bool:
        """Only seats that can actually fire on the core. No mid-map brawling."""
        if not ct.can_act():
            return False
        core_tiles = [Position(target.x + dx, target.y + dy)
                      for dx in (0, 1) for dy in (0, 1)]
        for d in CARDINALS:
            seat = myLoc.add(d)
            if not (0 <= seat.x < self.mapW and 0 <= seat.y < self.mapH):
                continue
            if ct.get_tile_building_id(seat) is not None:
                continue
            for facing in DIRECTIONS:
                for core_tile in core_tiles:
                    if not ct.can_fire_from(
                            seat, facing, EntityType.GUNNER, core_tile):
                        continue
                    if ct.can_build_gunner(seat, facing):
                        ct.build_gunner(seat, facing)
                        return True
        return False

    def _lay_relay(self, ct: Controller, myLoc: Position,
                   target: Position) -> bool:
        if ct.get_global_resources() <= RELAY_RESERVE or not ct.can_act():
            return False
        built = 0
        for uid in ct.get_nearby_buildings():
            if (ct.get_team(uid) == ct.get_team()
                    and ct.get_entity_type(uid) == EntityType.LAUNCHER):
                built += 1
                lp = ct.get_position(uid)
                if abs(lp.x - myLoc.x) + abs(lp.y - myLoc.y) < RELAY_SPACING:
                    return False
        if built >= RELAY_MAX:
            return False
        for d in CARDINALS:
            spot = myLoc.add(d)
            if ct.can_build_launcher(spot):
                ct.build_launcher(spot)
                return True
        return False

    # ---------------------------------------------------------------- guns

    def runGunner(self, ct: Controller) -> None:
        curTarget = ct.get_gunner_target()
        if curTarget is not None:
            tid = ct.get_tile_building_id(curTarget)
            bb = ct.get_tile_builder_bot_id(curTarget)
            if bb is not None and ct.get_team(bb) == ct.get_team():
                return
            if tid is not None and ct.get_team(tid) != ct.get_team():
                if ct.can_fire(curTarget):
                    ct.fire(curTarget)
                    return
        myPos = ct.get_position()
        myDir = ct.get_direction()
        best, bestDir = 0, myDir
        for d in DIRECTIONS:
            score = 0
            for tile in ct.get_attackable_tiles_from(
                    myPos, d, EntityType.GUNNER):
                tid = ct.get_tile_building_id(tile)
                if tid is not None and ct.get_team(tid) != ct.get_team():
                    t = ct.get_entity_type(tid)
                    score += 1000 if t == EntityType.CORE else 4
            if score > best:
                best, bestDir = score, d
        if bestDir != myDir and ct.can_rotate(bestDir):
            ct.rotate(bestDir)

    # -------------------------------------------------------------- shared

    def _update_enemy_core(self, ct: Controller) -> None:
        if self.mapPf.mapChanged:
            self.symmetryVersion += 1
        if self.mapPf.teamCore is not None:
            self.symmetry.update(
                self.mapPf.fullMap, self.symmetryVersion, self.mapPf.teamCore)
        for bid in ct.get_nearby_buildings():
            if (ct.get_team(bid) != ct.get_team()
                    and ct.get_entity_type(bid) == EntityType.CORE):
                self.enemyCorePos = ct.get_position(bid)
                ct.write_store(SLOT_ENEMY_CORE, pack_position(self.enemyCorePos))
                return
        shared = unpack_position(ct.read_store(SLOT_ENEMY_CORE))
        if shared is not None:
            self.enemyCorePos = shared

    def _enemy_core_target(self):
        if self.enemyCorePos is not None:
            return self.enemyCorePos
        if self.mapPf.teamCore is None:
            return None
        x, y = self.symmetry.enemy_core(self.mapPf.teamCore)
        return Position(x, y)

    def run(self, ct: Controller) -> None:
        # dev26+: an uncaught exception PERMANENTLY destroys the unit
        try:
            if self.mapW is None:
                self.mapH = ct.get_map_height()
                self.mapW = ct.get_map_width()
                self.symmetry = SymmetryTracker(self.mapW, self.mapH)
            etype = ct.get_entity_type()
            if etype == EntityType.CORE:
                self.runCore(ct)
            elif etype == EntityType.BUILDER_BOT:
                self.builderBot(ct)
            elif etype == EntityType.GUNNER:
                self.runGunner(ct)
            elif etype == EntityType.LAUNCHER:
                self.runLauncher(ct)
        except Exception:
            pass
