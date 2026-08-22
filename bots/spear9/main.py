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
from mapPathfinding import MapPathfinder

CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]
DIR8 = [Direction.NORTH, Direction.NORTHEAST, Direction.EAST,
        Direction.SOUTHEAST, Direction.SOUTH, Direction.SOUTHWEST,
        Direction.WEST, Direction.NORTHWEST]

SLOT_CX = 0
SLOT_CY = 1
SLOT_N = 2
SLOT_BUILT = 3
CANARY = True      # sentinels placed so far (builder writes)

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
        self.mapPf = MapPathfinder()
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

    def _foe_tiles(self):
        f = self.foe
        return [Position(f.x + a, f.y + b) for a in (0, 1) for b in (0, 1)]

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
        self.mapPf.setupMap(ct)
        self._latch(ct, pos)
        can_act = ct.get_action_cooldown() == 0
        my = ct.get_team()

        # GRAVE MEMORY. Measured (match 94442a57 g1): we rebuilt a
        # sentinel on tile (5,6) TEN TIMES - t14,23,30,37,44,51,65,89,121,
        # 149 - and it died within 6-9 turns every single time, ~300 Ti
        # posted into one kill zone while the game was lost 5-0. A tile
        # that killed our sentinel is covered by something we cannot see
        # and must never be seated again.
        if getattr(self, 'placed', None) is None:
            self.placed = {}
            self.graves = set()
        if getattr(self, 'lost', None) is None:
            self.lost = {}
        for tile in list(self.placed):
            p = Position(tile[0], tile[1])
            if ct.is_in_vision(p) and ct.get_tile_building_id(p) is None:
                # ONE reuse. Measured (match 55e81425 g1): they lose (22,9)
                # at t90 and (23,9) at t91, rebuild (23,9) at t92 - the SAME
                # tile - and never touch it again. Banning it outright is
                # too strict; rebuilding forever fed 300 Ti to one gunner.
                self.lost[tile] = self.lost.get(tile, 0) + 1
                if self.lost[tile] >= 2:
                    self.graves.add(tile)
                del self.placed[tile]

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

        # HEAL BEFORE BUILD. After they lost two seats, adgato rebuilt
        # ONE and then healed the damaged survivor for twelve straight
        # turns. Ours ran off to build instead, leaving a wounded sentinel
        # to die - so a hurt neighbour outranks the next seat.
        if can_act and self.built >= 2:
            hurt, hv = None, 10 ** 9
            for b in ct.get_nearby_buildings():
                if (ct.get_team(b) == my
                        and ct.get_entity_type(b) == EntityType.SENTINEL):
                    h = ct.get_hp(b)
                    if h >= ct.get_max_hp(b):
                        continue
                    p2 = ct.get_position(b)
                    if pos.distance_squared(p2) == 1 and h < hv:
                        hv, hurt = h, p2
            if hurt is not None and ct.can_heal(hurt):
                ct.heal(hurt)
                return

        # BUILD PHASE: attempt a slot every turn while fewer than 4 stand
        # (or rebuild below 3)
        want_build = (self.built < 4) or (sents < 3)
        if len(self.graves) >= 3 and sents >= 1:
            want_build = False      # three graves: stop paying the toll
        ct.write_store(12, self.built)
        if not (want_build and can_act):
            ct.write_store(10, 5)
        elif ct.get_global_resources() < ct.get_sentinel_cost():
            ct.write_store(10, 1)
            ct.write_store(8, min(4000000000, ct.get_sentinel_cost()))
            ct.write_store(7, ct.get_global_resources())
        # BANK THE WHOLE VOLLEY BEFORE OPENING IT. not adgato places four
        # sentinels inside five turns (t31-36 on 20x20) and kills at t54;
        # ours used to plant the first the moment it arrived (t19) and then
        # starve 28 turns while SCALED costs outran a spear with no
        # economy. A staggered volley is a quarter of the dps for most of
        # the fight. Once the first one is down, keep flowing.
        need = ct.get_sentinel_cost()
        if self.built == 0:
            need = need * 3
        if want_build and can_act \
                and ct.get_global_resources() >= need:
            # fp14-proven ray scan: walk each of 8 rays outward from each
            # enemy-core tile; the FIRST adjacent-and-buildable ray tile
            # gets the sentinel (facing back up the ray). Terrain handles
            # itself: unbuildable tiles simply fail can_build and the scan
            # moves on. If nothing is adjacent, walk at the nearest
            # candidate seen this turn.
            # NOT ADGATO'S ACTUAL GEOMETRY (measured, match 7e4b7783 g4,
            # their cores at (2,1) vs (16,17)): the four sentinels sat at
            # (12,13),(13,13),(12,14),(13,14) - a solid 2x2 BLOCK, every
            # one on a diagonal ray striking a core tile at distance 3-4,
            # placed t31/33/34/36. Their other games show the same shape:
            # three-in-a-row plus one, always mutually adjacent.
            #
            # Compactness is the whole trick. One tile of walking between
            # placements means four sentinels inside five turns, and one
            # escort tile can heal several of them. Our old scan took the
            # first free tile on EACH ray, scattering the volley around the
            # core and spending turns walking between rays.
            # THE MEASURED BLOCK. In match 7e4b7783 g4 (cores (2,1) vs
            # (16,17)) their four sentinels were (12,13),(13,13),(12,14),
            # (13,14): a 2x2 block sitting on the diagonal toward our side,
            # every tile firing down that diagonal into a core tile at
            # range 3-4. Build that shape deterministically rather than
            # scanning rays - scanning scattered the volley and wasted the
            # walk turns that make the difference between a t54 kill and a
            # t66 one.
            # Ray scan over every seat with a real firing line, then SORT
            # for compactness (see below). A hard-coded 2x2 block matching
            # their measured geometry was tried and is far worse: when its
            # four tiles are unusable the bot does nothing at all (icefloe
            # lost a tiebreak to a do-nothing opponent; 3% vs fp14). Terrain
            # varies per map - the scan finds the block where one exists.
            cands = []
            for t in self._foe_tiles():
                for d8 in DIR8:
                    dd = d8.delta()
                    reach = 5 if 0 in (dd[0], dd[1]) else 4
                    # d2 INCLUDED: measured on the match where their spear
                    # killed our v180 at t48 - their seats sat at distance
                    # 2-4 from our core ((5,13) is diagonal-2 off a core
                    # tile). Closer seats = shorter walk = earlier volley,
                    # and the spear is nothing but a tempo race.
                    for k in range(2, reach + 1):
                        x = t.x + dd[0] * k
                        y = t.y + dd[1] * k
                        if not (0 <= x < self.w and 0 <= y < self.h):
                            break
                        s = Position(x, y)
                        if (x, y) in self.graves:
                            continue        # this tile already ate one
                        if ct.is_in_vision(s):
                            if ct.get_tile_building_id(s) is not None:
                                continue
                            if ct.get_tile_builder_bot_id(s) is not None:
                                continue
                        cands.append((s, t))
            if cands:
                anchor = getattr(self, 'cluster', None)
                def key(c):
                    s = c[0]
                    # hug the last sentinel first (the 2x2 block), then us
                    near = cheb(s, anchor) if anchor is not None else 0
                    return (near, pos.distance_squared(s))
                cands.sort(key=key)
                walk_to = None
                standing_on = False
                for s, t in cands:
                    d = pos.distance_squared(s)
                    if d == 0:
                        # WE ARE STANDING ON THE SEAT. It can never be built
                        # from here (builds need adjacency) and walking to
                        # it is a no-op, so the old code oscillated on it
                        # for 28 turns while the volley sat at one sentinel.
                        standing_on = True
                        continue
                    if d == 1:
                        back = dir8_toward(s, t)
                        if back is not None \
                                and ct.can_build_sentinel(s, back):
                            ct.build_sentinel(s, back)
                            self.built += 1
                            self.placed[(s.x, s.y)] = ct.get_current_round()
                            self.cluster = s      # next one lands beside it
                            ct.write_store(SLOT_BUILT, self.built)
                            return
                    elif walk_to is None:
                        walk_to = s
                if standing_on and ct.get_move_cooldown() == 0:
                    for dstep in CARDINALS:
                        n = step(pos, dstep)
                        if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                            continue
                        if ct.is_in_vision(n) \
                                and ct.get_tile_building_id(n) is not None:
                            continue
                        ct.move(dstep)      # step aside, build it next turn
                        return
                if walk_to is not None:
                    self._go(ct, pos, walk_to)
                return

        # ACT-XOR-MOVE LOCK: moving resets the action cooldown, so a
        # builder that walks every turn can never build again (sentinel 1
        # only ever landed because a money-wait forced idle turns). When a
        # build is wanted and funded but the cooldown blocks it: STAND
        # STILL and let it clear.
        if want_build and not can_act \
                and ct.get_global_resources() >= ct.get_sentinel_cost():
            return

        # HEAL-SEAT SEAL (Bean counters' masterstroke, extracted from 20 of
        # their games and already PROMOTE-gated inside fp14): once the
        # volley stands, barrier the enemy core's orthogonal perimeter.
        # Healing needs orthogonal adjacency, so an occupied seat is a
        # tender that cannot tend - and that is exactly how heal-tanks
        # (Leviathan, kladde) survive a spear: they refunded 792 and 684 hp,
        # 100% of everything we dealt. Our own fire is unaffected: sentinel
        # shots are indirect and ignore barriers.
        # STALL DETECTOR: seal only once their core stops dropping under a
        # standing volley - i.e. a tender is out-healing us. Sealing by
        # default costs tempo and loses games the plain spear wins.
        foe_hp = None
        if ct.is_in_vision(self.foe):
            fid = ct.get_tile_building_id(self.foe)
            if fid is not None:
                foe_hp = ct.get_hp(fid)
        if foe_hp is not None:
            prev = getattr(self, 'foe_hp', None)
            if prev is None or foe_hp < prev:
                self.stall = 0
            elif self.built >= 2:
                self.stall = getattr(self, 'stall', 0) + 1
            self.foe_hp = foe_hp
        if self.built >= 4 and can_act \
                and getattr(self, 'stall', 0) >= 8 \
                and ct.get_global_resources() >= ct.get_barrier_cost() + 30:
            f = self.foe
            ring = []
            for a in (0, 1):
                ring.append(Position(f.x + a, f.y - 1))
                ring.append(Position(f.x + a, f.y + 2))
                ring.append(Position(f.x - 1, f.y + a))
                ring.append(Position(f.x + 2, f.y + a))
            ring = [t for t in ring
                    if 0 <= t.x < self.w and 0 <= t.y < self.h]
            ring.sort(key=lambda t: pos.distance_squared(t))
            for t in ring:
                if ct.is_in_vision(t):
                    if ct.get_tile_building_id(t) is not None:
                        continue
                    if ct.get_tile_builder_bot_id(t) is not None:
                        continue
                if pos.distance_squared(t) == 1:
                    if ct.can_build_barrier(t):
                        ct.build_barrier(t)
                        return
                    continue
                if pos.distance_squared(t) <= 9:
                    self._go(ct, pos, t)
                    return
                break

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
        # real pathfinding (fp's Dial's-algorithm mover) - three separate
        # greedy-orbit bugs earned this transplant
        self.mapPf.moveTo(ct, target)
