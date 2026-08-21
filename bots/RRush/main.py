"""RRUSH - 1:1 replica of "not adgato"'s sentinel spear (5-0 over HTTP 418,
extracted from all 5 games; invariant footprint per game: 1 builder,
4 sentinels, NOTHING else).

The whole bot:
  * Core spawns exactly ONE builder at t0, then only converts ammo.
  * The builder marches at the enemy core banking 100% of passive income.
  * On arrival: four sentinels on EXACT RAYS from the enemy core -
    cardinal d5, cardinal d4 (major-delta axis, our side), then the
    approach-side diagonal d4 and d3 - all facing the core. Built
    back-to-back as income allows (~5-turn window).
  * The builder parks orthogonally adjacent to the frontline sentinel and
    heals whichever adjacent sentinel is lowest (+4 beats a single
    gunner's -7 focus).
  * No rebuild while >=3 sentinels live (their 5-0 never needed one);
    below 3, rebuild the first free slot. A builder death before 4 are
    placed spawns ONE replacement (2-round spacing; resumes from the
    store's built count).
  * Kill math: 4x18/2t gross = dead core 16-20 turns after first shot.

Ammo: shots cost 10; the core reserves (4-built)*sentinel_cost in cash
first, then converts surplus (<=20/round) toward a 60 buffer.
"""

from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

SLOT_CX = 0
SLOT_CY = 1
SLOT_N = 2
SLOT_BUILT = 3      # sentinels placed so far (builder writes)

AMMO_BUF = 60


def step(a, d):
    dd = d.delta()
    return Position(a.x + dd[0], a.y + dd[1])


def dir8_toward(a, b):
    dx = (b.x > a.x) - (b.x < a.x)
    dy = (b.y > a.y) - (b.y < a.y)
    m = {(0, -1): Direction.NORTH, (1, -1): Direction.NORTHEAST,
         (1, 0): Direction.EAST, (1, 1): Direction.SOUTHEAST,
         (0, 1): Direction.SOUTH, (-1, 1): Direction.SOUTHWEST,
         (-1, 0): Direction.WEST, (-1, -1): Direction.NORTHWEST}
    return m.get((dx, dy))


def cheb(a, b):
    return max(abs(a.x - b.x), abs(a.y - b.y))


class Player:
    def __init__(self):
        self.core = None
        self.foe = None
        self.foe_seen = False
        self.w = None
        self.h = None
        self.stuck = 0
        self.last = None
        self.built = 0
        self.last_spawn = -9

    # ------------------------------------------------------------------
    def run(self, ct: Controller) -> None:
        if self.w is None:
            self.w = ct.get_map_width()
            self.h = ct.get_map_height()
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            self._core_turn(ct)
        elif et == EntityType.BUILDER_BOT:
            self._spear(ct)
        elif et == EntityType.SENTINEL:
            self._sentinel(ct)

    # ------------------------------------------------------------------
    def _core_turn(self, ct):
        pos = ct.get_position()
        ct.write_store(SLOT_CX, pos.x)
        ct.write_store(SLOT_CY, pos.y)
        r = ct.get_current_round()
        alive = ct.get_unit_count() - 1
        built = ct.read_store(SLOT_BUILT)
        # exactly one builder; ONE replacement only while the spear is
        # unfinished (2-round spacing so the newborn's store read settles)
        n = ct.read_store(SLOT_N)
        need = (n == 0) or (alive == 0 and built < 4)
        if (need and r - self.last_spawn >= 2
                and ct.get_global_resources() >= ct.get_builder_bot_cost()):
            ct.write_store(SLOT_N, n + 1)
            for d in CARDINALS:
                sp = step(pos, d)
                if ct.can_spawn(sp):
                    ct.spawn_builder(sp)
                    self.last_spawn = r
                    break
        # ammo: sentinel bodies outrank buffer depth
        ti = ct.get_global_resources()
        reserve = max(0, (4 - built)) * ct.get_sentinel_cost()
        surplus = ti - reserve
        ammo = ct.get_global_ammo()
        want = min(20, AMMO_BUF - ammo, surplus)
        if built > 0 and want > 0 and ct.can_convert_ammo(want):
            ct.convert_ammo(want)

    # ------------------------------------------------------------------
    def _latch(self, ct, pos):
        if self.core is None or (self.core.x == 0 and self.core.y == 0):
            self.core = Position(ct.read_store(SLOT_CX),
                                 ct.read_store(SLOT_CY))
            self.foe = Position(self.w - 2 - self.core.x,
                                self.h - 2 - self.core.y)
        if not self.foe_seen:
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) != ct.get_team()
                        and ct.get_entity_type(b) == EntityType.CORE):
                    self.foe = ct.get_position(b)
                    self.foe_seen = True
        if self.last is not None and self.last == pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last = pos

    def _slots(self):
        """Four ray tiles: cardinal d5, d4 on the major axis (our side),
        then approach-side diagonal d4, d3. Fallbacks walk closer on the
        same ray. All within reach (cardinal <=5, diagonal <=4)."""
        f = self.foe
        c = self.core
        dx = c.x - f.x
        dy = c.y - f.y
        if abs(dx) >= abs(dy):
            card = Direction.EAST if dx > 0 else Direction.WEST
        else:
            card = Direction.SOUTH if dy > 0 else Direction.NORTH
        cd = card.delta()
        # diagonal adjacent to the cardinal, on the side nearer our lane
        sy = 1 if dy > 0 else -1
        sx = 1 if dx > 0 else -1
        if abs(dx) >= abs(dy):
            diag = (cd[0], sy if dy != 0 else 1)
        else:
            diag = (sx if dx != 0 else 1, cd[1])
        out = []
        for k in (5, 4, 3, 2):
            out.append((Position(f.x + cd[0] * k, f.y + cd[1] * k), 'c'))
        for k in (4, 3, 2):
            out.append((Position(f.x + diag[0] * k, f.y + diag[1] * k),
                        'd'))
        for k in (4, 3):
            out.append((Position(f.x - diag[0] * k + 2 * cd[0] * k,
                                 f.y - diag[1] * k + 2 * cd[1] * k), 'd'))
        return [(t, kind) for (t, kind) in out
                if 0 <= t.x < self.w and 0 <= t.y < self.h]

    def _spear(self, ct):
        pos = ct.get_position()
        self._latch(ct, pos)
        can_act = ct.get_action_cooldown() == 0
        my = ct.get_team()

        # count my live sentinels near the foe + publish
        sents = 0
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == my
                    and ct.get_entity_type(b) == EntityType.SENTINEL):
                sents += 1
        if self.built > 0:
            ct.write_store(SLOT_BUILT, self.built)

        far = cheb(pos, self.foe)
        if far > 7 and self.built == 0:
            # THE MARCH: no building, no fighting, bank everything
            self._go(ct, pos, self.foe)
            return

        # BUILD PHASE: attempt a slot every turn while fewer than 4 stand
        # (or rebuild below 3)
        want_build = (self.built < 4) or (sents < 3)
        if want_build and can_act \
                and ct.get_global_resources() >= ct.get_sentinel_cost():
            for (t, kind) in self._slots():
                if ct.is_in_vision(t):
                    bid = ct.get_tile_building_id(t)
                    if bid is not None:
                        continue
                    bb = ct.get_tile_builder_bot_id(t)
                    if bb is not None and bb != ct.get_id():
                        continue
                if pos.x == t.x and pos.y == t.y:
                    # NEVER stand on a slot tile (spec) - it becomes
                    # unbuildable under our own feet. Step off sideways.
                    for d in CARDINALS:
                        n = step(pos, d)
                        if (0 <= n.x < self.w and 0 <= n.y < self.h
                                and ct.is_tile_passable(n)
                                and ct.get_move_cooldown() == 0):
                            ct.move(d)
                            return
                    return
                if pos.distance_squared(t) == 1:
                    face = dir8_toward(t, self.foe)
                    if face is not None \
                            and ct.can_build_sentinel(t, face):
                        ct.build_sentinel(t, face)
                        self.built += 1
                        ct.write_store(SLOT_BUILT, self.built)
                        return
                    continue
                # walk to a NEIGHBOR of the slot, never the slot itself
                best_n, bd = None, 10 ** 9
                for d in CARDINALS:
                    n = step(t, d)
                    if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                        continue
                    if (ct.is_in_vision(n)
                            and ct.get_tile_building_id(n) is not None):
                        continue
                    dn = pos.distance_squared(n)
                    if dn < bd:
                        bd, best_n = dn, n
                if best_n is not None:
                    self._go(ct, pos, best_n)
                    return

        # ESCORT: heal the lowest adjacent sentinel; else hug the
        # frontline one (closest to the enemy core)
        if can_act:
            worst, target = 10 ** 9, None
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) == my
                        and ct.get_entity_type(b) == EntityType.SENTINEL):
                    hp = ct.get_hp(b)
                    if hp >= ct.get_max_hp(b):
                        continue
                    p = ct.get_position(b)
                    if pos.distance_squared(p) == 1 and hp < worst:
                        worst, target = hp, p
            if target is not None and ct.can_heal(target):
                ct.heal(target)
                return
        front, fd = None, 10 ** 9
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == my
                    and ct.get_entity_type(b) == EntityType.SENTINEL):
                p = ct.get_position(b)
                d = cheb(p, self.foe)
                if d < fd:
                    fd, front = d, p
        if front is not None and pos.distance_squared(front) > 1:
            self._go(ct, pos, front)

    # ------------------------------------------------------------------
    def _sentinel(self, ct):
        my = ct.get_team()
        best, rank = None, 0
        for t in ct.get_attackable_tiles():
            if not ct.is_in_vision(t):
                continue
            bId = ct.get_tile_building_id(t)
            bb = ct.get_tile_builder_bot_id(t)
            if bId is not None and ct.get_team(bId) == my:
                continue
            if bb is not None and ct.get_team(bb) == my:
                continue
            r = 0
            if bb is not None:
                r = 2
            if bId is not None:
                bt = ct.get_entity_type(bId)
                if bt == EntityType.CORE:
                    r = 9
                elif bt in (EntityType.GUNNER, EntityType.SENTINEL):
                    r = 3
            if r > rank:
                rank, best = r, t
        if best is not None and ct.can_fire(best):
            ct.fire(best)

    # ------------------------------------------------------------------
    def _go(self, ct, pos, target):
        if ct.get_move_cooldown() != 0:
            return
        here = pos.distance_squared(target)
        opts = []
        for d in CARDINALS:
            n = step(pos, d)
            if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                continue
            if not ct.is_tile_passable(n):
                continue
            nd = n.distance_squared(target)
            if nd < here or nd == here or self.stuck > 2:
                opts.append((nd, d))
        if opts:
            opts.sort(key=lambda o: o[0])
            ct.move(opts[0][1])
