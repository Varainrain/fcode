"""RINGBOT — a minimal SIEGE sparring bot (not for the ladder).

Purpose: our whole archetype panel dies to our siege by ~t200, so every
defensive change we make gates NEUTRAL and tells us nothing. Meanwhile the
three teams above us on the ladder all win the same way, and we had no
opponent that reproduces it:

  Bean counters (2210)  ring of gunners at d2 + barriers at d1-d3 from t50,
                        our core dead t117 (match ed6806d3 g1)
  O(1)                  5 barriers on our 12-tile spawn ring t48-t102, two
                        gunners INSIDE the ring, core dead t220 (561f58b5 g1)
  HTTP 418              barriers t49-t68, gunner t111, core dead t177
                        (4a6904bf g2)

RINGBOT does exactly that and nothing else: march at the enemy core, wall its
12-tile spawn ring with 3-Ti barriers, then plant gunners two tiles out aimed
at the core, and rebuild whatever gets shot down. It is deliberately crude —
it does no economy beyond the opening — so it is NOT a strength benchmark. It
is a MECHANISM benchmark: it answers "does our bot notice and survive a ring
siege", which nothing else in the panel asks.

Note the core converts ammo. A siege bot whose gunners cannot fire measures
nothing, and ammo is a core-converted global pool in this engine.
"""
import random
from fcode import Controller, Direction, EntityType, Position

DIRS = [d for d in Direction if d != Direction.CENTRE]
CARD = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

S_CX, S_CY = 0, 1


class Player:
    def __init__(self):
        self.n = 0
        self.w = self.h = None
        self.team = None
        self.core = None
        self.last = None
        self.stuck = 0
        self.placed = 0          # barriers this builder has landed on the ring

    def run(self, ct):
        try:
            self._run(ct)
        except Exception:
            pass

    def _run(self, ct):
        if self.w is None:
            self.w = ct.get_map_width()
            self.h = ct.get_map_height()
            self.team = ct.get_team()
        t = ct.get_entity_type()
        if t == EntityType.CORE:
            self._core(ct)
        elif t == EntityType.BUILDER_BOT:
            self._builder(ct)
        elif t == EntityType.GUNNER:
            tg = ct.get_gunner_target()
            if tg is not None and ct.can_fire(tg):
                ct.fire(tg)
        elif t == EntityType.SENTINEL:
            for tile in ct.get_attackable_tiles():
                if ct.can_fire(tile):
                    ct.fire(tile)
                    return

    def _inb(self, p):
        return 0 <= p.x < self.w and 0 <= p.y < self.h

    def _enemy_core(self):
        """The map is 180-degree symmetric, so the mirror IS the enemy core."""
        if self.core is None:
            return Position(self.w // 2, self.h // 2)
        return Position(self.w - 2 - self.core.x, self.h - 2 - self.core.y)

    def _ring(self, c):
        """The 12 tiles touching the enemy's 2x2 core footprint - exactly the
        tiles its core spawns onto, which is why walling them strangles it."""
        foot = set()
        for dx in (0, 1):
            for dy in (0, 1):
                foot.add((c.x + dx, c.y + dy))
        out = []
        for (fx, fy) in sorted(foot):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    t = (fx + dx, fy + dy)
                    if t in foot or t in [(p.x, p.y) for p in out]:
                        continue
                    p = Position(t[0], t[1])
                    if self._inb(p):
                        out.append(p)
        return out

    # ------------------------------------------------------------------ core

    def _core(self, ct):
        p = ct.get_position()
        ct.write_store(S_CX, p.x)
        ct.write_store(S_CY, p.y)
        # AMMO: the only source in this engine. Without it the siege gunners
        # are scenery and the benchmark measures nothing.
        want = 20 - ct.get_global_ammo()
        spare = ct.get_global_resources() - 40
        amt = want if want < spare else spare
        if amt > 0 and ct.can_convert_ammo(amt):
            ct.convert_ammo(amt)
        if self.n >= 8 or ct.get_unit_count() >= 45:
            return
        if ct.get_global_resources() < ct.get_builder_bot_cost():
            return
        for d in random.sample(DIRS, len(DIRS)):
            sp = p.add(d)
            if self._inb(sp) and ct.can_spawn(sp):
                ct.spawn_builder(sp)
                self.n += 1
                return

    # --------------------------------------------------------------- builder

    def _builder(self, ct):
        p = ct.get_position()
        if self.core is None:
            x, y = ct.read_store(S_CX), ct.read_store(S_CY)
            if x or y:
                self.core = Position(x, y)
        self.stuck = self.stuck + 1 if self.last == p else 0
        self.last = p
        ec = self._enemy_core()

        if ct.get_action_cooldown() == 0:
            # 1. WALL THE RING first - barriers are 3 Ti and seal their spawns.
            if self.placed < 3 and self._wall(ct, p, ec):
                return
            # 2. Then turrets two tiles out, aimed at the core.
            if self._gun(ct, p, ec):
                return
            # 3. Keep walling once the guns are up.
            if self._wall(ct, p, ec):
                return
        self._step(ct, ec)

    def _wall(self, ct, p, ec):
        for tile in self._ring(ec):
            if p.distance_squared(tile) != 1:
                continue
            try:
                if ct.can_build_barrier(tile):
                    ct.build_barrier(tile)
                    self.placed += 1
                    return True
            except Exception:
                pass
        return False

    def _gun(self, ct, p, ec):
        if ct.get_global_resources() < ct.get_gunner_cost() + 5:
            return False
        for d in DIRS:
            g = p.add(d)
            if not self._inb(g) or g.distance_squared(ec) > 8:
                continue
            if not ct.is_tile_empty(g):
                continue
            facing = None
            for f in CARD:
                try:
                    if ct.can_fire_from(g, f, EntityType.GUNNER, ec):
                        facing = f
                        break
                except Exception:
                    pass
            if facing is None:
                continue
            try:
                if ct.can_build_gunner(g, facing):
                    ct.build_gunner(g, facing)
                    return True
            except Exception:
                pass
        return False

    def _step(self, ct, goal):
        if ct.get_move_cooldown() != 0:
            return
        p = ct.get_position()
        d = p.direction_to(goal)
        if d == Direction.CENTRE or self.stuck > 2:
            d = random.choice(DIRS)
        for _ in range(8):
            if self._inb(p.add(d)) and ct.can_move(d):
                ct.move(d)
                return
            d = d.rotate_right()
