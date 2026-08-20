"""CITADEL — economy and defense only. Wins by out-mining to the t1000
tiebreak, or by letting attackers die on the walls. No attack, ever.

Design laws (paid for in the rush wars):
  * Roles are latched from spawn order at birth — NEVER coordinated through
    store counters mid-game (store writes buffer one round; parallel readers
    overshoot: the 44-conveyor/8-gunner incident).
  * Defense exists BEFORE threats arrive (Lorem's law: picket by ~t14).
  * Home spending is tax-free here — there is no race to starve.
  * Sentinels over gunners: indirect fire ignores every wall trick.
  * Heal beats chew: 4/turn vs a melee builder's 2. Wardens ARE the wall.
  * Medic-priority targeting: kill the tender, the position collapses.
  * TLE budget 10ms/turn: one building sweep per unit per turn, maximum.

Store slots:
  0  core X    1  core Y    (written by core every round)
  2  spawn counter (core increments the round BEFORE each spawn, so a new
     builder's first read equals its own number — safe because the core
     spawns at most one builder per round)
"""

from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

SLOT_CORE_X = 0
SLOT_CORE_Y = 1
SLOT_SPAWNED = 2
SLOT_SIEGE = 3           # core sees an enemy -> 1, else 0
SLOT_FOCUS_X = 4         # turret focus-fire tile (last round's pick)
SLOT_FOCUS_Y = 5
SLOT_AXIS = 6            # first observed threat axis: 0 none, 1-4 = NESW

MAX_BUILDERS = 9
# spawn order -> role. Farmers get the economy up; wardens 3/5/7 arrive at
# t~6/10/14 so the first sentinel stands by Lorem-time.
WARDEN_NUMS = (3, 5, 7, 9)

AMMO_CEILING = 30
AMMO_RESERVE = 40
CHAIN_SLACK = 3          # conveyors allowed beyond straight-line distance
RESPAWN_TI = 300         # bank level that funds extra late farmers


def cardinal_toward(a: Position, b: Position) -> Direction:
    """Cardinal step from a toward b (x first)."""
    if b.x != a.x:
        return Direction.EAST if b.x > a.x else Direction.WEST
    if b.y != a.y:
        return Direction.SOUTH if b.y > a.y else Direction.NORTH
    return Direction.CENTRE


def dir8_toward(a: Position, b: Position) -> Direction:
    dx = (b.x > a.x) - (b.x < a.x)
    dy = (b.y > a.y) - (b.y < a.y)
    grid = {(0, -1): Direction.NORTH, (1, -1): Direction.NORTHEAST,
            (1, 0): Direction.EAST, (1, 1): Direction.SOUTHEAST,
            (0, 1): Direction.SOUTH, (-1, 1): Direction.SOUTHWEST,
            (-1, 0): Direction.WEST, (-1, -1): Direction.NORTHWEST,
            (0, 0): Direction.CENTRE}
    return grid[(dx, dy)]


def step_pos(a: Position, d: Direction) -> Position:
    dd = d.delta()
    return Position(a.x + dd[0], a.y + dd[1])


class Player:
    def __init__(self):
        self.role = None         # 'farm' | 'ward', latched at birth
        self.num = 0             # my spawn number, latched at birth
        self.core = None         # our core position (from store)
        self.map_w = None
        self.map_h = None
        # farmer state
        self.ore_target = None   # ore tile I intend to harvest
        self.chain_at = None     # next chain tile to fill
        self.chain_left = 0      # conveyor budget remaining for this chain
        self.explore_to = None
        self.shield_at = None    # barrier spot guarding my latest farm
        self.shield_tries = 0
        self.stuck = 0
        self.last_pos = None
        # warden state
        self.threat_axis = 0     # core-only: latched first threat axis
        self.seat = None         # my turret seat (position, facing)
        self.seat_kind = 'sentinel'
        self.seat_built = False
        self.seat_tries = 0      # failed builds at this seat
        self.piece_seen = 0      # rounds a siege piece has sat near home
        self.war_home = 0        # rounds left of stay-home war footing

    # ------------------------------------------------------------------
    def run(self, ct: Controller) -> None:
        if self.map_w is None:
            self.map_w = ct.get_map_width()
            self.map_h = ct.get_map_height()
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            self._core(ct)
        elif et == EntityType.BUILDER_BOT:
            self._builder(ct)
        elif et in (EntityType.SENTINEL, EntityType.GUNNER):
            self._turret(ct)

    # ------------------------------------------------------------------
    # CORE: publish position, spawn on schedule, keep the ammo pool topped.
    # ------------------------------------------------------------------
    def _core(self, ct: Controller) -> None:
        pos = ct.get_position()
        ct.write_store(SLOT_CORE_X, pos.x)
        ct.write_store(SLOT_CORE_Y, pos.y)

        my_team = ct.get_team()
        # 0 quiet / 1 enemies close / 2 the core is actually being hurt or
        # shelled. Only level 2 militarises spawning - level-1 pestering
        # must not stop the farm (the nordkap 0-mined regression).
        siege = 0
        for u in ct.get_nearby_units():
            if (ct.get_team(u) != my_team
                    and ct.get_position(u).distance_squared(pos) <= 18):
                siege = 1
                break
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) != my_team
                    and ct.get_entity_type(b) in (
                        EntityType.GUNNER, EntityType.SENTINEL,
                        EntityType.LAUNCHER)
                    and ct.get_position(b).distance_squared(pos) <= 64):
                siege = 2
                break
        if siege == 2 and ct.get_hp() >= (ct.get_max_hp() * 7) // 10:
            siege = 1      # shelled but holding: keep farming
        if siege < 2 and ct.get_hp() < (ct.get_max_hp() * 7) // 10:
            siege = 2
        ct.write_store(SLOT_SIEGE, siege)

        if self.threat_axis == 0:
            first = None
            for u in ct.get_nearby_units():
                if ct.get_team(u) != my_team:
                    p = ct.get_position(u)
                    if p.distance_squared(pos) <= 64:
                        first = p
                        break
            if first is None:
                for b in ct.get_nearby_buildings():
                    if (ct.get_team(b) != my_team
                            and ct.get_entity_type(b) in (
                                EntityType.GUNNER, EntityType.SENTINEL,
                                EntityType.LAUNCHER)):
                        first = ct.get_position(b)
                        break
            if first is not None:
                d = cardinal_toward(pos, first)
                if d in CARDINALS:
                    self.threat_axis = 1 + CARDINALS.index(d)
                    ct.write_store(SLOT_AXIS, self.threat_axis)

        spawned = self.num  # the core reuses .num as its spawn counter
        ti = ct.get_global_resources()
        alive = ct.get_unit_count() - 1     # builders alive (minus the core)
        # the lifetime counter never notices deaths - on nordkap the first
        # seven builders went extinct and the citadel froze at bank 24
        # forever. Live-count replacement keeps a minimum crew on any map.
        # enemy SIEGE SENTINELS near home (the wavebot signature) mean the
        # next 60 Ti is ammo and wall, not farmers - but a mere hunt gunner
        # (the jav1 signature) must not stop the build-out
        sent_near = False
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) != my_team
                    and ct.get_entity_type(b) == EntityType.SENTINEL
                    and ct.get_position(b).distance_squared(pos) <= 64):
                sent_near = True
                break
        crew_cap = 7 if sent_near else MAX_BUILDERS
        want_spawn = (spawned < crew_cap
                      or (ti > RESPAWN_TI and spawned < 14)
                      or (alive < 4
                          and ti >= ct.get_builder_bot_cost() + 10))
        if want_spawn and ti >= ct.get_builder_bot_cost():
            # write the number FIRST (visible next round, when the new
            # builder takes its first turn), then spawn
            ct.write_store(SLOT_SPAWNED, spawned + 1)
            for d in CARDINALS:
                sp = step_pos(pos, d)
                if ct.can_spawn(sp):
                    ct.spawn_builder(sp)
                    self.num = spawned + 1
                    break

        ammo = ct.get_global_ammo()
        # the defense fund: conversion must never pin the bank below the
        # price of a sentinel, or dead seats stay dead (the one-sentinel
        # wavebot loss - ammo siphon strangled every rebuild)
        reserve = ct.get_sentinel_cost() + AMMO_RESERVE
        ceiling = 120 if siege else AMMO_CEILING
        want = min(ceiling - ammo, ct.get_global_resources() - reserve)
        if want > 0 and ct.can_convert_ammo(want):
            ct.convert_ammo(want)

    # ------------------------------------------------------------------
    # BUILDER dispatch: latch identity once, then live one role forever.
    # ------------------------------------------------------------------
    def _builder(self, ct: Controller) -> None:
        pos = ct.get_position()
        if self.role is None:
            self.num = ct.read_store(SLOT_SPAWNED)
            self.role = ('ward' if (self.num in WARDEN_NUMS
                                    or (self.num > MAX_BUILDERS
                                        and self.num % 2 == 1))
                         else 'farm')
        if self.core is None or (self.core.x == 0 and self.core.y == 0):
            self.core = Position(ct.read_store(SLOT_CORE_X),
                                 ct.read_store(SLOT_CORE_Y))

        if self.last_pos is not None and self.last_pos == pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last_pos = pos

        if self.role == 'ward':
            self._warden(ct, pos)
        else:
            self._farmer(ct, pos)

    # ------------------------------------------------------------------
    # FARMER: harvester on nearest free ore -> lay ONE budgeted chain to the
    # network -> next ore. No shared state; claims are positional (a
    # harvester standing on the tile = claimed).
    # ------------------------------------------------------------------
    def _farmer(self, ct: Controller, pos: Position) -> None:
        can_act = ct.get_action_cooldown() == 0

        # 1) chain duty: fill chain_at with a conveyor facing onward to core
        if self.chain_at is not None and self.chain_left > 0:
            tgt = self.chain_at
            # (the final link MUST be built before the chain closes - closing
            # on touch-check first left every chain one conveyor short of the
            # core and nothing ever delivered: the 0-mined bug)
            blocker = (ct.is_in_vision(tgt)
                       and ct.get_tile_building_id(tgt)) or None
            if blocker is not None:
                if (ct.get_team(blocker) == ct.get_team()
                        and ct.get_entity_type(blocker) == EntityType.CONVEYOR):
                    self._chain_done()      # network reached
                else:
                    self._chain_detour(ct, tgt)
            elif pos.distance_squared(tgt) == 1:
                if can_act:
                    face = cardinal_toward(tgt, self.core)
                    if ct.can_build_conveyor(tgt, face):
                        ct.build_conveyor(tgt, face)
                        self.chain_left -= 1
                        if self._touches_core(tgt):
                            self._chain_done()      # delivered - link complete
                        else:
                            self.chain_at = step_pos(tgt, face)
                    elif ct.get_global_resources() < ct.get_conveyor_cost():
                        pass    # broke THIS turn - wait, never abandon the
                                # chain over transient poverty (the t11 death:
                                # two sentinels drained the bank and the whole
                                # economy silently stopped forever)
                    else:
                        self._chain_detour(ct, tgt)   # unbuildable terrain
                return
            else:
                self._move_to(ct, tgt)
                return
            # falls through here only when the chain just closed

        # 1.5) shield duty: one barrier on the far side of my harvester
        # (after the chain - shield-first delayed chains past the pressure
        # window and zeroed three maps' economies)
        if self.shield_at is not None:
            sh = self.shield_at
            self.shield_tries += 1
            if (self.shield_tries > 20
                    or (ct.is_in_vision(sh)
                        and ct.get_tile_building_id(sh) is not None)):
                self.shield_at = None
                self.shield_tries = 0
            elif pos.distance_squared(sh) == 1:
                if can_act:
                    if ct.can_build_barrier(sh):
                        ct.build_barrier(sh)
                    self.shield_at = None
                    self.shield_tries = 0
                return
            else:
                self._move_to(ct, sh)
                return

        # 2) harvester duty - or TAP an enemy harvester instead (engine
        # splits a harvester's output round-robin among ALL adjacent
        # conveyor chains; jav1's own source calls a single adjacent tap
        # ~25% of the yield. Their stolen-ore farms sit closer to our core
        # than their own - short chains, free money, and every coin we
        # siphon keeps them under their Ti gates: 30 hunt, 120 siege,
        # 360 respawns.)
        if self.ore_target is None:
            self.ore_target = self._find_free_ore(ct, pos)
            tap = self._find_tap(ct, pos)
            if tap is not None:
                tap_tile, _ = tap
                if pos.distance_squared(tap_tile) == 1:
                    if can_act:
                        face = cardinal_toward(tap_tile, self.core)
                        if ct.can_build_conveyor(tap_tile, face):
                            ct.build_conveyor(tap_tile, face)
                            # hand the rest to the normal chain machinery
                            self.chain_at = step_pos(tap_tile, face)
                            dist = (abs(tap_tile.x - self.core.x)
                                    + abs(tap_tile.y - self.core.y))
                            self.chain_left = dist + CHAIN_SLACK
                            self.ore_target = None
                    return
                self._move_to(ct, tap_tile)
                return
        if self.ore_target is not None:
            ore = self.ore_target
            if ct.is_in_vision(ore) and ct.get_tile_building_id(ore) is not None:
                self.ore_target = None      # someone harvested it already
                return
            if pos.distance_squared(ore) == 1:
                if can_act and ct.can_build_harvester(ore):
                    ct.build_harvester(ore)
                    # open this harvester's chain, budgeted
                    face = cardinal_toward(ore, self.core)
                    self.chain_at = step_pos(ore, face)
                    dist = abs(ore.x - self.core.x) + abs(ore.y - self.core.y)
                    self.chain_left = dist + CHAIN_SLACK
                    self.ore_target = None
                    foe = Position(self.map_w - 2 - self.core.x,
                                   self.map_h - 2 - self.core.y)
                    fd = cardinal_toward(ore, foe)
                    if fd != Direction.CENTRE:
                        self.shield_at = step_pos(ore, fd)
                return
            self._move_to(ct, ore)
            return

        # 3) nothing to farm in sight: explore, quadrant keyed by my number
        if (self.explore_to is None
                or pos.distance_squared(self.explore_to) <= 4
                or self.stuck > 4):
            self.explore_to = self._explore_point()
        self._move_to(ct, self.explore_to)

    def _touches_core(self, t: Position) -> bool:
        c = self.core
        for dx in (0, 1):
            for dy in (0, 1):
                if abs(t.x - (c.x + dx)) + abs(t.y - (c.y + dy)) <= 1:
                    return True
        return False

    def _chain_done(self):
        self.chain_at = None
        self.chain_left = 0

    def _chain_detour(self, ct: Controller, tgt: Position) -> None:
        """Reroute the chain one tile around an obstacle, other-axis first."""
        dx = (self.core.x > tgt.x) - (self.core.x < tgt.x)
        dy = (self.core.y > tgt.y) - (self.core.y < tgt.y)
        cand = []
        if dy != 0:
            cand.append(Position(tgt.x, tgt.y + dy))
        if dx != 0:
            cand.append(Position(tgt.x + dx, tgt.y))
        for c2 in cand:
            if not ct.is_in_vision(c2) or ct.get_tile_building_id(c2) is None:
                self.chain_at = c2
                return
        self._chain_done()

    def _find_tap(self, ct: Controller, pos: Position):
        """Free tile beside an enemy harvester, none of ours there yet."""
        my_team = ct.get_team()
        best, bd = None, 9999
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == my_team
                    or ct.get_entity_type(b) != EntityType.HARVESTER):
                continue
            hp_ = ct.get_position(b)
            spot, ours = None, False
            for d in CARDINALS:
                t = step_pos(hp_, d)
                if not (0 <= t.x < self.map_w and 0 <= t.y < self.map_h):
                    continue
                if not ct.is_in_vision(t):
                    continue
                tb = ct.get_tile_building_id(t)
                if tb is not None:
                    if (ct.get_team(tb) == my_team
                            and ct.get_entity_type(tb)
                            == EntityType.CONVEYOR):
                        ours = True      # already tapped
                        break
                    continue
                if (ct.get_tile_env(t) == Environment.EMPTY
                        and ct.is_tile_passable(t)):
                    if spot is None:
                        spot = t
            if ours or spot is None:
                continue
            d2 = self.core.distance_squared(hp_)
            if d2 < bd:
                bd, best = d2, (spot, hp_)
        return best

    def _find_free_ore(self, ct: Controller, pos: Position):
        foe = None
        if self.core is not None:
            foe = Position(self.map_w - 2 - self.core.x,
                           self.map_h - 2 - self.core.y)
        best, bk = None, (2, 9999)
        for t in ct.get_nearby_tiles():
            if ct.get_tile_env(t) == Environment.ORE_TITANIUM:
                if ct.get_tile_building_id(t) is not None:
                    continue
                risky = 0
                if foe is not None and self.core is not None:
                    risky = (1 if t.distance_squared(foe)
                             < t.distance_squared(self.core) else 0)
                k = (risky, pos.distance_squared(t))
                if k < bk:
                    bk, best = k, t
        return best

    def _explore_point(self) -> Position:
        q = self.num % 4
        x = self.map_w // 4 if q in (0, 3) else (3 * self.map_w) // 4
        y = self.map_h // 4 if q in (0, 1) else (3 * self.map_h) // 4
        return Position(x, y)

    # ------------------------------------------------------------------
    # WARDEN: claim a personal sentinel seat (keyed by MY number — no shared
    # counters), build it, then live at the wall: heal the core, heal the
    # turrets, answer close threats with an emergency gunner.
    # ------------------------------------------------------------------
    def _warden(self, ct: Controller, pos: Position) -> None:
        can_act = ct.get_action_cooldown() == 0

        if not self.seat_built and self.core is not None:
            self.seat = self._my_seat(ct)   # re-aim until built - the
                                            # threat axis may only be
                                            # known after we spawned

        # 0) emergency: enemy near home -> answering turret NOW, wherever
        # we stand. Sentinel if we can pay (indirect, outranges the siege
        # pieces that killed us on royale); gunner as the poverty fallback.
        threat = self._home_threat(ct)
        if threat is not None and can_act:
            if ct.get_global_resources() >= ct.get_sentinel_cost():
                for d in CARDINALS:
                    sp = step_pos(pos, d)
                    face = cardinal_toward(sp, threat)
                    if (face != Direction.CENTRE
                            and ct.can_build_sentinel(sp, face)):
                        ct.build_sentinel(sp, face)
                        return
            elif ct.get_global_resources() >= ct.get_gunner_cost() + 10:
                for d in CARDINALS:
                    sp = step_pos(pos, d)
                    face = cardinal_toward(sp, threat)
                    if face != Direction.CENTRE and ct.can_build_gunner(sp, face):
                        ct.build_gunner(sp, face)
                        return

        # 0.5) sally: an emplaced enemy turret grinding the core will
        # never be removed by our turrets (their tenders out-heal our dps)
        # or by emergency builds (no free tiles in a crowded fortress).
        # Wardens 5/7 walk out and chew it: 2 dmg a turn, 40 hp target,
        # and builders are the one piece live-count respawn replaces free.
        if self.num != WARDEN_NUMS[0]:
            piece = self._siege_piece(ct)
            self.piece_seen = self.piece_seen + 1 if piece is not None else 0
            # only sortie from a stable house at a PERSISTENT grind piece -
            # rushes resolve inside 15 rounds and need the heal corps home
            # (nordkap t32); grind sieges last forever and must be chewed
            # off (royale t99 -> t123)
            hurt = False
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) == ct.get_team()
                        and ct.get_entity_type(b) == EntityType.CORE
                        and ct.get_hp(b) < (ct.get_max_hp(b) * 13) // 20):
                    hurt = True
                    break
            if hurt:
                # hurt = stay home... except against a LONE unescorted
                # grinder (the t995 death march: one gunner, -3/turn,
                # sally locked out by its own safety gate). Mass tells
                # rushes (many pieces/units) from grinders (one piece).
                pieces = 0
                reach = {EntityType.GUNNER: 13, EntityType.SENTINEL: 32,
                         EntityType.LAUNCHER: 26}
                for b in ct.get_nearby_buildings():
                    bt = ct.get_entity_type(b)
                    if (ct.get_team(b) != ct.get_team()
                            and bt in reach
                            and ct.get_position(b).distance_squared(
                                self.core) <= reach[bt]):
                        pieces += 1
                units = 0
                for u in ct.get_nearby_units():
                    if (ct.get_team(u) != ct.get_team()
                            and ct.get_position(u).distance_squared(
                                self.core) <= 18):
                        units += 1
                if pieces <= 1 and units == 0:
                    hurt = False
            if (piece is not None and not hurt
                    and self.piece_seen >= 12):
                if pos.distance_squared(piece) == 1:
                    if can_act and ct.can_fire(piece):
                        ct.fire(piece)
                else:
                    self._move_to(ct, piece)
                return

        # 1) my sentinel seat (rebuilt every time it dies - a latched
        # seat_built with a dead sentinel is an unmanned wall)
        if (self.seat_built and self.seat is not None
                and ct.is_in_vision(self.seat[0])
                and ct.get_tile_building_id(self.seat[0]) is None):
            self.seat_built = False
        if not self.seat_built and self.seat is not None:
            spot, face = self.seat
            if ct.is_in_vision(spot) and ct.get_tile_building_id(spot) is not None:
                self.seat_built = True      # something stands there — fine
            elif pos.distance_squared(spot) == 1:
                if self.seat_kind == 'sentinel':
                    cost_ok = (ct.get_global_resources()
                               >= ct.get_sentinel_cost())
                    buildable = ct.can_build_sentinel(spot, face)
                else:
                    cost_ok = (ct.get_global_resources()
                               >= ct.get_gunner_cost())
                    buildable = ct.can_build_gunner(spot, face)
                if can_act and cost_ok:
                    if buildable:
                        if self.seat_kind == 'sentinel':
                            ct.build_sentinel(spot, face)
                        else:
                            ct.build_gunner(spot, face)
                        self.seat_built = True
                    else:
                        # unbuildable seat (terrain) - standing here retrying
                        # forever made wardens 5/7 statues on royale
                        self.seat_tries += 1
                        if self.seat_tries >= 3:
                            self.seat_tries = 0
                            for d in CARDINALS:
                                alt = step_pos(spot, d)
                                if (alt != pos
                                        and 0 <= alt.x < self.map_w
                                        and 0 <= alt.y < self.map_h
                                        and ct.is_tile_passable(alt)):
                                    self.seat = (alt, face)
                                    break
                    return
                # can't afford the seat yet: heal something meanwhile
            else:
                self._move_to(ct, spot)
                return

        # 2) heal duty: the wall's whole job
        if can_act and self._heal_something(ct, pos):
            return

        # 3) hold position - adjacent to the core when it needs healing
        # (a warden idling at its seat 3 tiles out heals nothing)
        if self.core is not None:
            need_touch = False
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) == ct.get_team()
                        and ct.get_entity_type(b) == EntityType.CORE
                        and ct.get_hp(b) < ct.get_max_hp(b)):
                    need_touch = True
                    break
            if (need_touch
                    and (self.num == WARDEN_NUMS[0]
                         or ct.get_current_round() > 60)
                    and not self._touches_core(pos)):
                # only the home warden crowds in - everyone hugging the
                # footprint blocks spawn tiles, chains and emergency build
                # space (the nordkap t34 self-choke)
                self._move_to(ct, self.core)
            elif pos.distance_squared(self.core) > 8:
                self._move_to(ct, self.core)

    def _my_seat(self, ct: Controller):
        try:
            idx = WARDEN_NUMS.index(self.num)
        except ValueError:
            idx = self.num % 3
        # one far-reaching sentinel; the rest gunners - a gunner turn of fire
        # costs 4 ammo to a sentinel's 10-per-2, and base cost is 20 vs 30,
        # which matters twice over once scaled costs kick in
        self.seat_kind = 'sentinel' if idx <= 1 else 'gunner'
        # COVERAGE PICKET (from jav1's own source): its creep refuses gunner
        # seats our rays cover >1x and sentinel seats we cover AT ALL, its
        # harvester-hunt skips harvesters inside our covered tiles, and its
        # farmers refuse turret-threatened ore. Seats therefore sit ON the
        # enemy-approach rays of our core, FACING the enemy core - occupancy
        # denies the tile, the facing line denies the lane behind it.
        foe = Position(self.map_w - 2 - self.core.x,
                       self.map_h - 2 - self.core.y)
        axis = ct.read_store(SLOT_AXIS)
        if 1 <= axis <= 4:
            d1 = CARDINALS[axis - 1]     # observed threat, not guessed
        else:
            d1 = cardinal_toward(self.core, foe)
            if d1 == Direction.CENTRE:
                d1 = Direction.NORTH
        perp = ([Direction.NORTH, Direction.SOUTH]
                if d1 in (Direction.EAST, Direction.WEST)
                else [Direction.EAST, Direction.WEST])
        if (step_pos(self.core, perp[1]).distance_squared(foe)
                < step_pos(self.core, perp[0]).distance_squared(foe)):
            perp = [perp[1], perp[0]]
        # SHIELD-WALL PICKET. Sentinels fire only along their facing line
        # and never rotate; enemy creep gunners must sit on our core's own
        # rays (reach 3) to hurt it. Two sentinels stand DIRECTLY on the
        # threat-side edge of the footprint - their bodies block the two
        # cardinal fire lanes outright, their lines sweep every farther
        # seat on those columns, and the rotating gunner takes the knee.
        dd = d1.delta()
        pd = perp[0].delta()
        cx, cy = self.core.x, self.core.y
        if dd[0] != 0:
            fx = cx + 2 if dd[0] > 0 else cx - 1
            s0 = Position(fx, cy)
            s1 = Position(fx, cy + 1)
            g0 = Position(fx, cy - 1 if pd[1] < 0 else cy + 2)
        else:
            fy = cy + 2 if dd[1] > 0 else cy - 1
            s0 = Position(cx, fy)
            s1 = Position(cx + 1, fy)
            g0 = Position(cx - 1 if pd[0] < 0 else cx + 2, fy)
        if self.num in WARDEN_NUMS:
            if dd[0] != 0:
                g1 = Position(s0.x, cy + 2 if g0.y < cy else cy - 1)
            else:
                g1 = Position(cx + 2 if g0.x < cx else cx - 1, s0.y)
            spot = [s0, s1, g0, g1][idx % 4]
            face = d1
        else:
            lane = [d1, perp[0], perp[1]][idx]
            side = perp[idx % 2] if lane == d1 else d1
            spot = self.core
            for _ in range(3):
                spot = step_pos(spot, lane)
            spot = step_pos(spot, side)
            face = lane
        spot = Position(max(0, min(self.map_w - 1, spot.x)),
                        max(0, min(self.map_h - 1, spot.y)))
        return (spot, face)

    def _siege_piece(self, ct: Controller):
        """Nearest enemy turret building emplaced near our core."""
        if self.core is None:
            return None
        my_team = ct.get_team()
        best, bd = None, 33
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != my_team and ct.get_entity_type(b) in (
                    EntityType.GUNNER, EntityType.SENTINEL):
                p = ct.get_position(b)
                d = p.distance_squared(self.core)
                if d < bd:
                    bd, best = d, p
        return best

    def _home_threat(self, ct: Controller):
        if self.core is None:
            return None
        my_team = ct.get_team()
        best, bd = None, 19
        for u in ct.get_nearby_units():
            if ct.get_team(u) != my_team:
                p = ct.get_position(u)
                d = p.distance_squared(self.core)
                if d < bd:
                    bd, best = d, p
        bd = max(bd, 37)
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != my_team and ct.get_entity_type(b) in (
                    EntityType.GUNNER, EntityType.SENTINEL, EntityType.LAUNCHER):
                p = ct.get_position(b)
                d = p.distance_squared(self.core)
                if d < bd:
                    bd, best = d, p
        return best

    def _heal_something(self, ct: Controller, pos: Position) -> bool:
        my_team = ct.get_team()
        target = None
        worst = 1.0
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != my_team:
                continue
            bt = ct.get_entity_type(b)
            if bt not in (EntityType.CORE, EntityType.SENTINEL,
                          EntityType.GUNNER, EntityType.HARVESTER):
                continue
            p = ct.get_position(b)
            hp = ct.get_hp(b) / ct.get_max_hp(b)
            if hp >= 1.0:
                continue
            if bt == EntityType.CORE:
                tiles = [p, step_pos(p, Direction.EAST),
                         step_pos(p, Direction.SOUTH),
                         step_pos(step_pos(p, Direction.EAST), Direction.SOUTH)]
                for t in tiles:
                    if pos.distance_squared(t) == 1 and hp < worst:
                        worst, target = hp, t
            elif pos.distance_squared(p) == 1 and hp < worst:
                worst, target = hp, p
        if target is not None and ct.can_heal(target):
            ct.heal(target)
            return True
        return False

    # ------------------------------------------------------------------
    # TURRETS: medic-priority. The tender is worth more than the tended.
    # ------------------------------------------------------------------
    def _turret(self, ct: Controller) -> None:
        my_team = ct.get_team()
        best, score = None, 0
        for tile in ct.get_attackable_tiles():
            if not ct.is_in_vision(tile):
                continue
            b_id = ct.get_tile_building_id(tile)
            bb_id = ct.get_tile_builder_bot_id(tile)
            if bb_id is not None and ct.get_team(bb_id) == my_team:
                continue
            if b_id is not None and ct.get_team(b_id) == my_team:
                continue
            s = 0
            if bb_id is not None:
                s = 4                    # enemy builder = planter/medic/chewer
            elif b_id is not None:
                bt = ct.get_entity_type(b_id)
                if bt in (EntityType.GUNNER, EntityType.SENTINEL,
                          EntityType.LAUNCHER):
                    s = 3
                elif bt == EntityType.HARVESTER:
                    s = 2
                elif bt == EntityType.CORE:
                    s = 1
            if s > score:
                score, best = s, tile
        # focus fire: prefer last round's shared target if it still holds
        # a live enemy in MY pattern - split fire never outpaces tenders
        if best is not None:
            fx, fy = ct.read_store(SLOT_FOCUS_X), ct.read_store(SLOT_FOCUS_Y)
            if (fx, fy) != (0, 0) and (fx != best.x or fy != best.y):
                f = Position(fx, fy)
                for tile in ct.get_attackable_tiles():
                    if tile.x == fx and tile.y == fy and ct.is_in_vision(f):
                        fb = ct.get_tile_building_id(f)
                        fu = ct.get_tile_builder_bot_id(f)
                        occupied = ((fu is not None
                                     and ct.get_team(fu) != my_team)
                                    or (fb is not None
                                        and ct.get_team(fb) != my_team))
                        if occupied:
                            best = f
                        break
        if best is not None and ct.can_fire(best):
            ct.fire(best)
            ct.write_store(SLOT_FOCUS_X, best.x)
            ct.write_store(SLOT_FOCUS_Y, best.y)
            return
        if (best is None
                and ct.get_entity_type() == EntityType.GUNNER):
            my_pos = ct.get_position()
            tgt = None
            td = 14
            for u in ct.get_nearby_units():
                if ct.get_team(u) != my_team:
                    p = ct.get_position(u)
                    d = p.distance_squared(my_pos)
                    if d < td:
                        td, tgt = d, p
            if tgt is None:
                for b in ct.get_nearby_buildings():
                    if ct.get_team(b) != my_team:
                        p = ct.get_position(b)
                        d = p.distance_squared(my_pos)
                        if d < td:
                            td, tgt = d, p
            if tgt is not None:
                want = dir8_toward(my_pos, tgt)
                if want != Direction.CENTRE and ct.can_rotate(want):
                    ct.rotate(want)

    # ------------------------------------------------------------------
    def _move_to(self, ct: Controller, target: Position) -> None:
        if ct.get_move_cooldown() != 0:
            return
        pos = ct.get_position()
        here = pos.distance_squared(target)
        options = []
        for d in CARDINALS:
            n = step_pos(pos, d)
            if not (0 <= n.x < self.map_w and 0 <= n.y < self.map_h):
                continue
            if not ct.is_tile_passable(n):
                continue
            nd = n.distance_squared(target)
            # non-regressing steps always allowed; regressing ones only when
            # stuck (walking around our own conveyor chains needs sidesteps
            # IMMEDIATELY, not after three wasted turns - the t56 crawl)
            if nd < here or (nd == here) or self.stuck > 1:
                options.append((nd, d))
        if options:
            options.sort(key=lambda o: o[0])
            ct.move(options[0][1])
