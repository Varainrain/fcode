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

MAX_BUILDERS = 7
# spawn order -> role. Farmers get the economy up; wardens 3/5/7 arrive at
# t~6/10/14 so the first sentinel stands by Lorem-time.
WARDEN_NUMS = (3, 5, 7)

AMMO_CEILING = 30
AMMO_RESERVE = 40
CHAIN_SLACK = 3          # conveyors allowed beyond straight-line distance
RESPAWN_TI = 400         # bank level that funds extra late farmers


def cardinal_toward(a: Position, b: Position) -> Direction:
    """Cardinal step from a toward b (x first)."""
    if b.x != a.x:
        return Direction.EAST if b.x > a.x else Direction.WEST
    if b.y != a.y:
        return Direction.SOUTH if b.y > a.y else Direction.NORTH
    return Direction.CENTRE


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
        self.stuck = 0
        self.last_pos = None
        # warden state
        self.seat = None         # my sentinel seat (position, facing)
        self.seat_built = False

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

        spawned = self.num  # the core reuses .num as its spawn counter
        ti = ct.get_global_resources()
        want_spawn = (spawned < MAX_BUILDERS
                      or (ti > RESPAWN_TI and spawned < 12))
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
        want = min(AMMO_CEILING - ammo, ct.get_global_resources() - AMMO_RESERVE)
        if want > 0 and ct.can_convert_ammo(want):
            ct.convert_ammo(want)

    # ------------------------------------------------------------------
    # BUILDER dispatch: latch identity once, then live one role forever.
    # ------------------------------------------------------------------
    def _builder(self, ct: Controller) -> None:
        pos = ct.get_position()
        if self.role is None:
            self.num = ct.read_store(SLOT_SPAWNED)
            self.role = 'ward' if self.num in WARDEN_NUMS else 'farm'
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

        # 2) harvester duty
        if self.ore_target is None:
            self.ore_target = self._find_free_ore(ct, pos)
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

    def _find_free_ore(self, ct: Controller, pos: Position):
        best, bd = None, 9999
        for t in ct.get_nearby_tiles():
            if ct.get_tile_env(t) == Environment.ORE_TITANIUM:
                if ct.get_tile_building_id(t) is not None:
                    continue
                d = pos.distance_squared(t)
                if d < bd:
                    bd, best = d, t
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

        if self.seat is None and self.core is not None:
            self.seat = self._my_seat()

        # 0) emergency: enemy near home -> a gunner facing it beats all else
        threat = self._home_threat(ct)
        if (threat is not None and can_act
                and ct.get_global_resources() >= ct.get_gunner_cost() + 10):
            for d in CARDINALS:
                sp = step_pos(pos, d)
                face = cardinal_toward(sp, threat)
                if face != Direction.CENTRE and ct.can_build_gunner(sp, face):
                    ct.build_gunner(sp, face)
                    return

        # 1) my sentinel seat
        if not self.seat_built and self.seat is not None:
            spot, face = self.seat
            if ct.is_in_vision(spot) and ct.get_tile_building_id(spot) is not None:
                self.seat_built = True      # something stands there — fine
            elif pos.distance_squared(spot) == 1:
                if (can_act
                        and ct.get_global_resources() >= ct.get_sentinel_cost()
                        and ct.can_build_sentinel(spot, face)):
                    ct.build_sentinel(spot, face)
                    self.seat_built = True
                return
            else:
                self._move_to(ct, spot)
                return

        # 2) heal duty: the wall's whole job
        if can_act and self._heal_something(ct, pos):
            return

        # 3) hold position at ring distance
        if self.core is not None and pos.distance_squared(self.core) > 8:
            self._move_to(ct, self.core)

    def _my_seat(self):
        try:
            idx = WARDEN_NUMS.index(self.num)
        except ValueError:
            idx = self.num % 3
        centre = Position(self.map_w // 2, self.map_h // 2)
        d1 = cardinal_toward(self.core, centre)
        if d1 == Direction.CENTRE:
            d1 = Direction.NORTH
        perp = ([Direction.NORTH, Direction.SOUTH]
                if d1 in (Direction.EAST, Direction.WEST)
                else [Direction.EAST, Direction.WEST])
        lane = [d1, perp[0], perp[1]][idx]
        side = perp[idx % 2] if lane == d1 else d1
        spot = self.core
        for _ in range(2):
            spot = step_pos(spot, lane)
        # one lateral step so the seat sits OFF the cardinal approach lane -
        # chains and seats were fighting for the same tiles
        spot = step_pos(spot, side)
        spot = Position(max(0, min(self.map_w - 1, spot.x)),
                        max(0, min(self.map_h - 1, spot.y)))
        return (spot, lane)

    def _home_threat(self, ct: Controller):
        if self.core is None:
            return None
        my_team = ct.get_team()
        best, bd = None, 37
        for u in ct.get_nearby_units():
            if ct.get_team(u) != my_team:
                p = ct.get_position(u)
                d = p.distance_squared(self.core)
                if d < bd:
                    bd, best = d, p
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
                elif bt == EntityType.CORE:
                    s = 1
            if s > score:
                score, best = s, tile
        if best is not None and ct.can_fire(best):
            ct.fire(best)

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
