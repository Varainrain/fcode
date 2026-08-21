"""KMIMIC - faithful replica of the 'kladde chatte tville' counter-script
that went 0-5 and 1-4 on our v155, built from the 15-game autopsy:
  1. modest home economy (2 farms)
  2. TENDERS: two builders parked at the home core healing it (+8/turn -
     out-heals any lone siege gunner forever)
  3. CAGER: one builder crosses early, rings the ENEMY core with barriers,
     then plants core-adjacent sentinels and tends them
  4. sentinels deliver 28 x 18 into the (typically) unhealed enemy core
Sparring referee only - never uploaded.
"""

from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

SLOT_N = 2


def step(a, d):
    dd = d.delta()
    return Position(a.x + dd[0], a.y + dd[1])


def toward(a, b):
    if b.x != a.x:
        return Direction.EAST if b.x > a.x else Direction.WEST
    if b.y != a.y:
        return Direction.SOUTH if b.y > a.y else Direction.NORTH
    return Direction.CENTRE


class Player:
    def __init__(self):
        self.num = 0
        self.core = None
        self.foe = None
        self.w = None
        self.h = None
        self.ore = None
        self.chain = None
        self.stuck = 0
        self.last = None
        self.cage_done = 0

    def run(self, ct: Controller) -> None:
        if self.w is None:
            self.w = ct.get_map_width()
            self.h = ct.get_map_height()
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            self._core(ct)
        elif et == EntityType.BUILDER_BOT:
            self._builder(ct)
        elif et == EntityType.SENTINEL:
            self._sentinel(ct)

    def _core(self, ct):
        pos = ct.get_position()
        ct.write_store(0, pos.x)
        ct.write_store(1, pos.y)
        n = self.num
        ti = ct.get_global_resources()
        if n < 5 and ti >= ct.get_builder_bot_cost():
            ct.write_store(SLOT_N, n + 1)
            for d in CARDINALS:
                sp = step(pos, d)
                if ct.can_spawn(sp):
                    ct.spawn_builder(sp)
                    self.num = n + 1
                    break
        ammo = ct.get_global_ammo()
        want = min(60 - ammo, ti - 70)
        if want > 0 and ct.can_convert_ammo(want):
            ct.convert_ammo(want)

    def _builder(self, ct):
        pos = ct.get_position()
        if self.num == 0:
            self.num = ct.read_store(SLOT_N)
        if self.core is None or (self.core.x == 0 and self.core.y == 0):
            self.core = Position(ct.read_store(0), ct.read_store(1))
            self.foe = Position(self.w - 2 - self.core.x,
                                self.h - 2 - self.core.y)
        if self.last is not None and self.last == pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.last = pos
        if self.num in (1, 2):
            self._farm(ct, pos)
        elif self.num in (3, 4):
            self._tend(ct, pos)
        else:
            self._cage(ct, pos)

    # ---- tenders: the heal loop that erased 665/714/833 rush damage
    def _tend(self, ct, pos):
        my = ct.get_team()
        best, hp = None, 10 ** 9
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != my:
                continue
            bt = ct.get_entity_type(b)
            if bt not in (EntityType.CORE, EntityType.SENTINEL,
                          EntityType.GUNNER):
                continue
            if ct.get_hp(b) >= ct.get_max_hp(b):
                continue
            p = ct.get_position(b)
            tiles = [p]
            if bt == EntityType.CORE:
                tiles = [p, step(p, Direction.EAST), step(p, Direction.SOUTH),
                         step(step(p, Direction.EAST), Direction.SOUTH)]
            for t in tiles:
                if pos.distance_squared(t) == 1 and ct.get_hp(b) < hp:
                    hp, best = ct.get_hp(b), t
        if best is not None and ct.can_heal(best):
            ct.heal(best)
            return
        if pos.distance_squared(self.core) > 2:
            self._go(ct, pos, self.core)

    # ---- the cager: cross, ring with barriers, plant sentinels, tend
    def _cage(self, ct, pos):
        foe = self.foe
        ftiles = [foe, step(foe, Direction.EAST), step(foe, Direction.SOUTH),
                  step(step(foe, Direction.EAST), Direction.SOUTH)]
        near = min(pos.distance_squared(t) for t in ftiles)
        if near > 4:
            self._go(ct, pos, foe)
            return
        ti = ct.get_global_resources()
        # barriers on free tiles adjacent to their footprint
        if self.cage_done < 6 and ti >= 10:
            for t in ftiles:
                for d in CARDINALS:
                    n = step(t, d)
                    if n in ftiles:
                        continue
                    if pos.distance_squared(n) == 1 \
                            and ct.can_build_barrier(n):
                        ct.build_barrier(n)
                        self.cage_done += 1
                        return
        # then sentinels two out, facing back at the core
        if ti >= ct.get_sentinel_cost():
            for t in ftiles:
                for d in CARDINALS:
                    s = step(step(t, d), d)
                    if pos.distance_squared(s) == 1:
                        back = toward(s, t)
                        if back != Direction.CENTRE \
                                and ct.can_build_sentinel(s, back):
                            ct.build_sentinel(s, back)
                            return
        # tend the siege
        my = ct.get_team()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == my \
                    and ct.get_entity_type(b) == EntityType.SENTINEL \
                    and ct.get_hp(b) < ct.get_max_hp(b):
                p = ct.get_position(b)
                if pos.distance_squared(p) == 1 and ct.can_heal(p):
                    ct.heal(p)
                    return
                if pos.distance_squared(p) > 2:
                    self._go(ct, pos, p)
                    return
        # orbit the cage
        self._go(ct, pos, foe)

    # ---- simple farm: harvester on nearest ore + straight chain home
    def _farm(self, ct, pos):
        if self.chain is not None:
            tgt = self.chain
            if ct.is_in_vision(tgt) and ct.get_tile_building_id(tgt) is not None:
                self.chain = None
            elif pos.distance_squared(tgt) == 1:
                face = toward(tgt, self.core)
                if ct.can_build_conveyor(tgt, face):
                    ct.build_conveyor(tgt, face)
                    nxt = step(tgt, face)
                    done = False
                    for c in (self.core, step(self.core, Direction.EAST),
                              step(self.core, Direction.SOUTH),
                              step(step(self.core, Direction.EAST),
                                   Direction.SOUTH)):
                        if abs(tgt.x - c.x) + abs(tgt.y - c.y) <= 1:
                            done = True
                    self.chain = None if done else nxt
                return
            else:
                self._go(ct, pos, tgt)
                return
        if self.ore is None:
            best, bd = None, 10 ** 9
            for t in ct.get_nearby_tiles():
                if ct.get_tile_env(t) == Environment.ORE_TITANIUM \
                        and ct.get_tile_building_id(t) is None:
                    d = pos.distance_squared(t)
                    if d < bd:
                        bd, best = d, t
            self.ore = best
        if self.ore is not None:
            ore = self.ore
            if ct.is_in_vision(ore) and ct.get_tile_building_id(ore) is not None:
                self.ore = None
                return
            if pos.distance_squared(ore) == 1:
                if ct.can_build_harvester(ore):
                    ct.build_harvester(ore)
                    face = toward(ore, self.core)
                    self.chain = step(ore, face)
                    self.ore = None
                return
            self._go(ct, pos, ore)
            return
        self._tend(ct, pos)

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
            if nd <= here or self.stuck > 1:
                opts.append((nd, d))
        if opts:
            opts.sort(key=lambda o: o[0])
            ct.move(opts[0][1])
