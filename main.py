"""Khaos rebuild — memoryless state-scoring bot (Pantheon architecture).

Every builder, every turn: score seven candidate states in descending ceiling
order with early exit, run the single best. No mode flags, no multi-turn
commitments — targets are re-derived each turn from the bitmask map layer,
deconflicted through a Voronoi claim partition, with TTL caches for targets
that recently failed.

States (ceiling): attack 9 · heal 8 · route 7.75 · secure 7.5 · harvest 4 ·
disrupt 2 · explore 1.
"""

import random

from fcode import Controller, Direction, EntityType, Environment, Position

import mapanalysis
import mapinfo as mapinfo_mod
import path
import planes
import symmetry

CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
DELTA_TO_DIR = {
    (0, -1): Direction.NORTH, (0, 1): Direction.SOUTH,
    (1, 0): Direction.EAST, (-1, 0): Direction.WEST,
}

GLOBAL_AMMO_BUFFER = 20
MAX_OPEN_BUILDERS = 5
TTL_ROUNDS = 100
CPU_SOFT_STOP = 6500  # stop scoring lower states past this many us


def manhattan(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y)


class Player:
    def __init__(self):
        self.mi = None
        self.myNum = -1
        self.numSpawned = 0
        self.teamCore = None
        self.teamCoreTiles = None
        self.enemyCore = None
        self.symTracker = None
        self.fullmap = None
        self.fullmapVer = -1
        self.routeField = None
        self.routeVer = -1
        self._connected = set()  # own conveyors whose chain reaches the core
        self._homeDisc = None    # cached home-guard disc for builder #1
        self.brokenBarriers = []  # own barriers we broke while walking
        self._plantCache = None   # score-plane best placement cache
        self.enemyField = None    # dist-to-enemy-core field (attack route)
        self.enemyFieldVer = -1
        self.ttl = {}              # (state, x, y) -> expiry round
        self.stuck = 0
        self.lastPos = None
        self.exploreTarget = None
        # turret / launcher state
        self.idleTurns = 0
        self.enemyBotHistory = {}
        self.tapWait = 0  # sentinel one-tap coordination hold counter

    # ------------------------------------------------------------------
    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.core(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.builder(ct)
        elif etype == EntityType.SENTINEL:
            self.sentinel(ct)
        elif etype == EntityType.GUNNER:
            self.gunner(ct)
        elif etype == EntityType.LAUNCHER:
            self.launcher(ct)

    # ------------------------------------------------------------------
    # Core: fan-spawn opening, defensive spawn, ammo buffer
    # ------------------------------------------------------------------
    def core(self, ct: Controller) -> None:
        import math
        pos = ct.get_position()
        if self.mi is None:
            w, h = ct.get_map_width(), ct.get_map_height()
            self.mi = mapinfo_mod.MapInfo(w, h)
            mapanalysis.reset_map(w, h)
        rnd = ct.get_current_round()
        ti = ct.get_global_resources()
        # Pantheon spawn policy: baseline 200 until 12 allies, then 400 —
        # spawn whenever titanium clears baseline + the builder's own cost.
        # (Our old 350/400*scale gates stalled workforce growth exactly
        # during establishment.)
        baseline = 400 if ct.get_unit_count() >= 12 else 200
        wantSpawn = (
            ti >= baseline + ct.get_builder_bot_cost()
            or (rnd >= 30 and ct.get_unit_count() <= 6
                and ti >= ct.get_builder_bot_cost() + 60))
        if wantSpawn:
            candidates = []
            for dx in (-1, 0, 1, 2):
                for dy in (-1, 0, 1, 2):
                    if 0 <= dx <= 1 and 0 <= dy <= 1:
                        continue
                    p = Position(pos.x + dx, pos.y + dy)
                    if ct.can_spawn(p):
                        candidates.append(p)
            if candidates:
                ccx, ccy = pos.x + 0.5, pos.y + 0.5
                pick = None
                # defensive: intruder at the base with no ally on it
                enemyPos, enemyDist, allies = None, 1e9, []
                for eid in ct.get_nearby_units():
                    ep = ct.get_position(eid)
                    if ct.get_team(eid) == ct.get_team():
                        if ct.get_entity_type(eid) == EntityType.BUILDER_BOT:
                            allies.append(ep)
                        continue
                    d = (ep.x - ccx) ** 2 + (ep.y - ccy) ** 2
                    if d < enemyDist:
                        enemyDist, enemyPos = d, ep
                if enemyPos is not None and enemyDist <= 18 and not any(
                        a.distance_squared(enemyPos) <= 8 for a in allies):
                    pick = min(candidates, key=lambda p: manhattan(p, enemyPos))
                elif self.numSpawned < 4:
                    w, h = ct.get_map_width(), ct.get_map_height()
                    primary = math.atan2(h / 2 - ccy, w / 2 - ccx)
                    target = primary + (-1.178, -0.393, 0.393, 1.178)[self.numSpawned]
                    tx, ty = math.cos(target), math.sin(target)

                    def align(p):
                        vx, vy = p.x + 0.5 - ccx, p.y + 0.5 - ccy
                        norm = math.hypot(vx, vy) or 1.0
                        return -(vx * tx + vy * ty) / norm
                    pick = min(candidates, key=align)
                else:
                    pick = candidates[0]
                ct.spawn_builder(pick)
                self.numSpawned += 1
                ct.write_store(0, self.numSpawned)
        # distress: hurt core or enemy building in core vision -> broadcast on
        # slot 7 so fanned-out builders converge to heal/counter-battery.
        distress = ct.get_hp() < ct.get_max_hp()
        if not distress:
            for bid in ct.get_nearby_buildings():
                if ct.get_team(bid) != ct.get_team():
                    distress = True
                    break
        if distress:
            ct.write_store(7, rnd)
        # ammo buffer (raised while distressed so counter-turrets can fire)
        buffer = 40 if distress else GLOBAL_AMMO_BUFFER
        cur = ct.get_global_ammo()
        if cur < buffer:
            spare = ct.get_global_resources() - ct.get_builder_bot_cost()
            amount = min(buffer - cur, spare)
            if amount > 0 and ct.can_convert_ammo(amount):
                ct.convert_ammo(amount)

    # ------------------------------------------------------------------
    # Builder: the memoryless spine
    # ------------------------------------------------------------------
    def builder(self, ct: Controller) -> None:
        mi = self._setup(ct)
        mi.update_vision(ct)
        mi.absorb(ct)
        self._updateCores(ct)
        self._updateSymmetry(ct)

        rnd = ct.get_current_round()
        pos = ct.get_position()
        if self.lastPos == pos:
            self.stuck += 1
        else:
            self.stuck = 0
        self.lastPos = pos

        # ttl sweep
        if rnd % 16 == 0:
            self.ttl = {k: v for k, v in self.ttl.items() if v > rnd}

        # death memory (Ijti fix): ban tiles where our turrets died
        if mi.turret_losses:
            for (lx, ly) in mi.turret_losses:
                self.ttl[('plant', lx, ly)] = rnd + 80
            mi.turret_losses.clear()
            self._plantCache = None

        # claims context: my bit vs other friendly bots
        my_bit = mi.bit(pos.x, pos.y)
        others = mi.own_bots & ~my_bit

        states = (
            (9.0, self._score_attack, self._run_attack),
            (8.0, self._score_heal, self._run_heal),
            (7.75, self._score_route, self._run_route),
            (7.5, self._score_secure, self._run_secure),
            (4.0, self._score_harvest, self._run_harvest),
            (2.0, self._score_disrupt, self._run_disrupt),
            (1.0, self._score_explore, self._run_explore),
        )
        best, bestScore, bestData = None, 0.0, None
        for ceil, scorefn, runfn in states:
            if bestScore >= ceil:
                break
            if ct.get_cpu_time_elapsed() > CPU_SOFT_STOP and best is not None:
                break
            s, data = scorefn(ct, mi, my_bit, others)
            if s > bestScore:
                best, bestScore, bestData = runfn, s, data
        if best is not None:
            best(ct, mi, bestData)

        # passive extras with leftover action/cpu
        self._rebuildBroken(ct, mi)
        self._tryChokeBlock(ct, mi)
        self._healAdjacent(ct)
        mi.share(ct, self.myNum, self.teamCore)
        self._advanceAnalysis(ct)

    # ---- setup helpers ----
    def _setup(self, ct):
        if self.mi is None:
            w, h = ct.get_map_width(), ct.get_map_height()
            self.mi = mapinfo_mod.MapInfo(w, h)
            mapanalysis.configure_map(w, h)
            self.mi.on_block_change = (
                lambda x, y, blocking: mapanalysis.note_structural_tile(
                    x, y, blocking, w, h))
        if self.myNum == -1:
            self.myNum = ct.read_store(0) + 1
        return self.mi

    def _updateCores(self, ct):
        if self.teamCore is None:
            for bid in ct.get_nearby_buildings():
                if (ct.get_entity_type(bid) == EntityType.CORE
                        and ct.get_team(bid) == ct.get_team()):
                    self.teamCore = ct.get_position(bid)
        if self.enemyCore is None:
            for bid in ct.get_nearby_buildings():
                if (ct.get_entity_type(bid) == EntityType.CORE
                        and ct.get_team(bid) != ct.get_team()):
                    self.enemyCore = ct.get_position(bid)

    def _updateSymmetry(self, ct):
        mi = self.mi
        if self.teamCore is None:
            return
        if self.symTracker is None:
            self.symTracker = symmetry.SymmetryTracker(mi.w, mi.h)
        if self.fullmapVer != mi.struct_version or self.fullmap is None:
            fm = [[-1] * mi.h for _ in range(mi.w)]
            for x in range(mi.w):
                col = fm[x]
                for y in range(mi.h):
                    b = 1 << (x + y * mi.w)
                    if not (mi.seen & b):
                        continue
                    if mi.walls & b:
                        col[y] = 2
                    elif mi.blocked & b:
                        col[y] = 3
                    elif mi.ore & b:
                        col[y] = 1
                    else:
                        col[y] = 0
            self.fullmap = fm
            self.fullmapVer = mi.struct_version
        self.symTracker.update(self.fullmap, mi.struct_version, self.teamCore)

    def _enemyCoreGuess(self):
        if self.enemyCore is not None:
            return self.enemyCore
        if self.symTracker is not None and self.teamCore is not None:
            cx, cy = self.symTracker.enemy_core(self.teamCore)
            if 0 <= cx < self.mi.w - 1 and 0 <= cy < self.mi.h - 1:
                return Position(cx, cy)
        return None

    def _homeMask(self):
        """Tiles within squared distance 100 of the core (Pantheon: the very
        first builder restricts all its targets to this disc = home guard)."""
        mi = self.mi
        if self._homeDisc is not None or self.teamCore is None:
            return self._homeDisc or 0
        cx, cy = self.teamCore.x, self.teamCore.y
        m = 0
        for x in range(max(0, cx - 10), min(mi.w, cx + 11)):
            for y in range(max(0, cy - 10), min(mi.h, cy + 11)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= 100:
                    m |= mi.bit(x, y)
        self._homeDisc = m
        return m

    def _coreMask(self):
        mi = self.mi
        if self.teamCore is None:
            return 0
        m = 0
        for dx in (0, 1):
            for dy in (0, 1):
                x, y = self.teamCore.x + dx, self.teamCore.y + dy
                if 0 <= x < mi.w and 0 <= y < mi.h:
                    m |= mi.bit(x, y)
        return m

    # ---- movement ----
    def _moveToward(self, ct, targets_mask, avoid=0):
        if ct.get_move_cooldown() != 0:
            return
        mi = self.mi
        pos = ct.get_position()
        step = path.next_step(mi, (pos.x, pos.y), targets_mask, avoid)
        if step is not None:
            d = DELTA_TO_DIR[step]
            dest = pos.add(d)
            # break-walk own barriers (Pantheon): destroy is free, remember
            # the tile so we rebuild it once we've stepped off.
            if (self._inBounds(dest)
                    and mi.own_barriers & mi.bit(dest.x, dest.y)
                    and not ct.can_move(d)
                    and ct.is_in_vision(dest) and ct.can_destroy(dest)):
                ct.destroy(dest)
                mi.own_barriers &= ~mi.bit(dest.x, dest.y)
                mi.note_tile(dest.x, dest.y, mapinfo_mod.T_EMPTY)
                if len(self.brokenBarriers) < 4:
                    self.brokenBarriers.append(dest)
            if ct.can_move(d):
                ct.move(d)
                self.stuck = 0
                return
        self.stuck += 1
        if self.stuck > 2 + (ct.get_id() % 8):
            dirs = [d for d in CARDINALS if ct.can_move(d)]
            if dirs:
                ct.move(random.choice(dirs))

    # ------------------------------------------------------------------
    # STATE: attack (9) — plant turrets on enemy buildings / push their core
    # ------------------------------------------------------------------
    def _score_attack(self, ct, mi, my_bit, others):
        rnd = ct.get_current_round()
        ti = ct.get_global_resources()
        if ti < ct.get_gunner_cost() + 40:
            return 0.0, None
        # DEFENSIVE counter-battery: enemy building near OUR core — every
        # builder may respond (no role gate), claims still deconflict.
        if self.teamCore is not None:
            home = 0
            for (x, y) in mi.enemy_buildings:
                if self.ttl.get(('atk', x, y), 0) > rnd:
                    continue
                if abs(x - self.teamCore.x) + abs(y - self.teamCore.y) <= 10:
                    home |= mi.bit(x, y)
            if home:
                mine = path.claims(mi, my_bit, others, home)
                if mine:
                    return 9.0, ('bld', mine)
        if rnd < 30 or self.myNum % 3 != 0 or self.myNum == 1:
            return 0.0, None  # builder #1 is the home guard, never sieges
        guess = self._enemyCoreGuess()
        # bit-sliced plane placement (Pantheon): score EVERY legal gunner
        # placement board-wide, take the best above threshold.
        plant = self._bestPlant(ct, mi)
        if plant is not None:
            score, px, py, fk = plant
            # geographic money gate on the PLACEMENT tile
            if self.teamCore is not None and guess is not None:
                dHome = abs(px - self.teamCore.x) + abs(py - self.teamCore.y)
                dEnemy = abs(px - guess.x) + abs(py - guess.y)
                deep = dHome > dEnemy
            else:
                deep = False
            if not deep or ti >= 150:
                mine = path.claims(mi, my_bit, others, mi.bit(px, py))
                if mine:
                    return 9.0, ('plant', (px, py, fk))
        # fallback: walk at remembered enemy buildings (old greedy pathway)
        cands = 0
        for (x, y) in mi.enemy_buildings:
            key = ('atk', x, y)
            if self.ttl.get(key, 0) > rnd:
                continue
            if self.teamCore is not None and guess is not None:
                dHome = abs(x - self.teamCore.x) + abs(y - self.teamCore.y)
                dEnemy = abs(x - guess.x) + abs(y - guess.y)
                onOurHalf = dHome <= dEnemy
            else:
                onOurHalf = True
            if onOurHalf or ti >= 150:
                cands |= mi.bit(x, y)
        if cands:
            mine = path.claims(mi, my_bit, others, cands)
            if mine:
                return 8.9, ('bld', mine)
            return 0.0, None
        if guess is not None:
            return 6.0, ('core', guess)
        return 0.0, None

    PLANT_VALUES = None  # built lazily: EntityType -> placement value

    def _bestPlant(self, ct, mi):
        """Best gunner placement from the score planes, cached per
        (struct, enemy-set). Threshold 20 = better than a lone barrier."""
        if Player.PLANT_VALUES is None:
            Player.PLANT_VALUES = {
                EntityType.CORE: 60, EntityType.GUNNER: 40,
                EntityType.SENTINEL: 40, EntityType.LAUNCHER: 20,
                EntityType.CONVEYOR: 15, EntityType.SPLITTER: 18,
                EntityType.HARVESTER: 8, EntityType.BARRIER: 5,
            }
        key = (mi.struct_version,
               tuple(sorted((k, str(v))
                            for k, v in mi.enemy_buildings.items())))
        if self._plantCache is not None and self._plantCache[0] == key:
            return self._plantCache[1]
        by_value = {}
        for (x, y), etype in mi.enemy_buildings.items():
            v = Player.PLANT_VALUES.get(etype, 5)
            by_value.setdefault(v, [0])[0] = by_value.get(v, [0])[0] \
                | mi.bit(x, y)
        class_masks = [(v, m[0]) for v, m in by_value.items()]
        valid = (mi.seen & ~mi.walls & ~mi.blocked & ~mi.ore
                 & ~mi.own_conveyors & ~mi.own_barriers
                 & ~mi.expand(mi.expand(mi.enemy_bots)))
        # death memory (Ijti fix): freshly-fatal tiles are banned
        rnd = ct.get_current_round()
        for (kind, kx, ky), exp in self.ttl.items():
            if kind == 'plant' and exp > rnd:
                valid &= ~mi.bit(kx, ky)
        best = None
        if class_masks and valid:
            # threat penalty (Ijti fix): unthreatened placements first;
            # threatened only at 2x value (trade, not feeding tube)
            threat = mi.threat()
            best = planes.best_placement(mi, class_masks, valid & ~threat)
            if best is None or best[0] < 20:
                hot = planes.best_placement(mi, class_masks, valid & threat)
                if hot is not None and hot[0] >= 40 \
                        and (best is None or hot[0] > best[0]):
                    best = hot
            if best is not None and best[0] < 20:
                best = None
        self._plantCache = (key, best)
        return best

    def _enemyFieldCached(self, mi, guess):
        key = (mi.struct_version, guess.x, guess.y)
        if self.enemyField is not None and self.enemyFieldVer == key:
            return self.enemyField
        m = 0
        for dx in (0, 1):
            for dy in (0, 1):
                x, y = guess.x + dx, guess.y + dy
                if 0 <= x < mi.w and 0 <= y < mi.h:
                    m |= mi.bit(x, y)
        self.enemyField = path.dist_field(mi, mi.expand(m))
        self.enemyFieldVer = key
        return self.enemyField

    def _run_attack(self, ct, mi, data):
        kind, payload = data
        pos = ct.get_position()
        rnd = ct.get_current_round()
        if kind == 'core':
            # ATTACK ROUTE (Pantheon override): while marching on the enemy
            # core, lay a conveyor trail once we're geographically ahead
            # (dist-to-them <= 1.5x dist-home). Walkable for us, area denial
            # for them; planes convert the head into a gunner on contact.
            if (ct.get_action_cooldown() == 0
                    and ct.get_global_resources()
                    >= ct.get_conveyor_cost() + 120):
                ef = self._enemyFieldCached(mi, payload)
                hf = self._routeFieldCached(ct)
                idx = pos.x + pos.y * mi.w
                if (ef is not None and hf is not None
                        and ef[idx] < 4096 and hf[idx] < 4096
                        and ef[idx] <= 1.5 * hf[idx]):
                    best = None
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = pos.x + dx, pos.y + dy
                        if not (0 <= nx < mi.w and 0 <= ny < mi.h):
                            continue
                        b = mi.bit(nx, ny)
                        if (mi.walls | mi.blocked | mi.own_conveyors
                                | mi.own_barriers | mi.ore) & b:
                            continue
                        d = ef[nx + ny * mi.w]
                        if best is None or d < best[0]:
                            best = (d, nx, ny)
                    if best is not None and best[0] < ef[idx]:
                        _, lx, ly = best
                        link = Position(lx, ly)
                        # face further downhill toward the enemy core
                        fb = None
                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            fx, fy = lx + dx, ly + dy
                            if not (0 <= fx < mi.w and 0 <= fy < mi.h):
                                continue
                            fd = ef[fx + fy * mi.w]
                            if fb is None or fd < fb[0]:
                                fb = (fd, dx, dy)
                        if fb is not None:
                            facing = DELTA_TO_DIR[(fb[1], fb[2])]
                            if (ct.is_in_vision(link)
                                    and ct.can_build_conveyor(link, facing)):
                                ct.build_conveyor(link, facing)
                                mi.own_conveyors |= mi.bit(lx, ly)
                                mi.own_conv_facing[(lx, ly)] = (fb[1], fb[2])
            m = mi.bit(payload.x, payload.y)
            self._moveToward(ct, mi.expand(mi.expand(m)))
            return
        if kind == 'plant':
            px, py, fk = payload
            tile = Position(px, py)
            facing = {'E': Direction.EAST, 'W': Direction.WEST,
                      'N': Direction.NORTH, 'S': Direction.SOUTH}[fk]
            tb = mi.bit(px, py)
            if pos == tile:
                # standing on the placement: step aside
                self._moveToward(ct, mi.expand(tb) & mi.passable() & ~tb)
                return
            if pos.distance_squared(tile) <= 2 \
                    and ct.get_action_cooldown() == 0:
                if ct.is_in_vision(tile) and ct.can_build_gunner(tile, facing):
                    ct.build_gunner(tile, facing)
                    self._plantCache = None
                    return
                self.ttl[('atk', px, py)] = rnd + 20
                self._plantCache = None
                return
            self._moveToward(ct, mi.expand(tb) & mi.passable())
            return
        targets = payload
        tb = targets & -targets
        tx, ty = mi.xy(tb)
        tpos = Position(tx, ty)
        dist = manhattan(pos, tpos)
        if dist <= 3 and ct.get_action_cooldown() == 0:
            # place a turret on an adjacent tile with line to the target
            facing = self._cardinalTo(pos, tpos)
            placed = False
            for d in CARDINALS:
                p = pos.add(d)
                if not self._inBounds(p) or not ct.is_in_vision(p):
                    continue
                f = self._cardinalTo(p, tpos)
                if f == Direction.CENTRE:
                    continue
                if ct.can_build_gunner(p, f):
                    ct.build_gunner(p, f)
                    placed = True
                    break
                if (ct.get_global_resources() >= ct.get_sentinel_cost() + 40
                        and ct.can_build_sentinel(p, f)):
                    ct.build_sentinel(p, f)
                    placed = True
                    break
            if placed:
                self.ttl[('atk', tx, ty)] = rnd + 40
                return
            if facing == Direction.CENTRE:
                self.ttl[('atk', tx, ty)] = rnd + TTL_ROUNDS
                return
        if dist <= 1:
            # cannot place and already adjacent: back off this target a while
            self.ttl[('atk', tx, ty)] = rnd + 30
        self._moveToward(ct, mi.expand(targets) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: heal (8) — repair damaged own buildings, deter intruders
    # ------------------------------------------------------------------
    def _score_heal(self, ct, mi, my_bit, others):
        damaged = 0
        # core distress broadcast: converge on the core even when it's out of
        # our own vision — 2 medics out-heal a sentinel's grind (8 vs 6/round).
        distress = ct.read_store(7)
        if (distress > 0 and ct.get_current_round() - distress < 12
                and self.teamCore is not None):
            damaged |= self._coreMask()
        for bid in ct.get_nearby_buildings():
            if ct.get_team(bid) != ct.get_team():
                continue
            if ct.get_hp(bid) + 2 < ct.get_max_hp(bid):
                p = ct.get_position(bid)
                damaged |= mi.bit(p.x, p.y)
        if damaged:
            mine = path.claims(mi, my_bit, others, damaged)
            if mine:
                return 8.0, ('heal', mine)
        # Pantheon: own sentinel trading with an enemy sentinel counts as very
        # damaged — medics pre-park. Scores 7, BELOW route's 7.75 (the paper's
        # exact number; 8.0 parked the workforce and starved the economy).
        trading = 0
        for (x, y), tk in mi.own_turrets.items():
            if tk != 'S':
                continue
            for (ex, ey), ekind in mi.enemy_turrets.items():
                if ekind == 'S' and (x - ex) ** 2 + (y - ey) ** 2 <= 32:
                    trading |= mi.bit(x, y)
                    break
        if trading:
            mine = path.claims(mi, my_bit, others, trading)
            if mine:
                return 7.0, ('heal', mine)
        # Pantheon chase zone: 8 pathing steps around our conveyor network
        # (was 2 tiles) — intruders get hunted before they reach the chain.
        zone = mi.own_conveyors
        passable = mi.passable()
        for _ in range(8):
            zone = mi.expand(zone) & (passable | zone)
        intruders = mi.enemy_bots & zone
        if intruders:
            mine = path.claims(mi, my_bit, others, intruders)
            if mine:
                return 7.9, ('chase', mine)
        return 0.0, None

    def _run_heal(self, ct, mi, data):
        kind, mask = data
        pos = ct.get_position()
        tb = mask & -mask
        tx, ty = mi.xy(tb)
        tpos = Position(tx, ty)
        if kind == 'heal':
            if pos.distance_squared(tpos) <= 2:
                if ct.can_heal(tpos):
                    ct.heal(tpos)
                return
            self._moveToward(ct, mi.expand(tb) & mi.passable())
            return
        # chase: stand next to the intruder; the launcher/turret net does the
        # rest, and our body denies conveyor-chip tiles
        if pos.distance_squared(tpos) <= 2:
            if ct.get_action_cooldown() == 0:
                for d in CARDINALS:
                    p = pos.add(d)
                    if (self._inBounds(p) and ct.is_in_vision(p)
                            and manhattan(p, tpos) <= 1
                            and ct.can_build_launcher(p)
                            and ct.get_global_resources()
                            >= ct.get_launcher_cost() + 60):
                        ct.build_launcher(p)
                        return
            return
        self._moveToward(ct, mi.expand(tb) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: route (7.75) — stateless chain building down the core gradient
    # ------------------------------------------------------------------
    def _connectedConveyors(self, mi):
        """Own conveyors whose chain (by facing) reaches the core — legal
        merge targets for new routes (Pantheon: routes may end on existing
        conveyors). Fixpoint over remembered facings."""
        coreMask = self._coreMask()
        core_xy = set()
        m = coreMask
        while m:
            lsb = m & -m
            core_xy.add(mi.xy(lsb))
            m ^= lsb
        connected = set()
        changed = True
        while changed:
            changed = False
            for (x, y), (dx, dy) in mi.own_conv_facing.items():
                if (x, y) in connected:
                    continue
                out = (x + dx, y + dy)
                if out in core_xy or out in connected:
                    connected.add((x, y))
                    changed = True
        return connected

    def _routeFieldCached(self, ct):
        mi = self.mi
        key = (mi.struct_version, len(mi.own_conv_facing),
               tuple(sorted(mi.enemy_turrets)))
        if self.routeField is not None and self.routeVer == key:
            return self.routeField
        coreMask = self._coreMask()
        if not coreMask:
            return None
        # Pantheon merge targets: the core PLUS every conveyor already
        # connected to it — new chains join existing trunks instead of each
        # harvester paying for a private line the whole way home. LOADED
        # trunk tiles are excluded (P6): a full conveyor can't accept a new
        # stack, so merging there jams the junction (their +4 penalty, made
        # binary by dev23's hold-1-stack rule).
        self._connected = self._connectedConveyors(mi)
        targets = coreMask
        for (x, y) in self._connected:
            targets |= mi.bit(x, y)
        targets &= ~mi.own_loaded | coreMask
        # Pantheon universal AVOID mask (p7): tiles covered by enemy turrets
        # are HARD-excluded from conveyor route planning, not soft-costed —
        # a link placed under a known gun is titanium fed to the enemy
        # (Landers vault r139: we rebuilt one threatened link 7 times).
        # Existing own conveyors stay routable so trunks aren't orphaned.
        avoid = mi.threat() & ~mi.own_conveyors & ~coreMask
        self.routeField = path.dist_field(mi, targets, avoid_mask=avoid)
        self.routeVer = key
        return self.routeField

    @staticmethod
    def _chainRoot(mi, hx, hy):
        """Adjacent own conveyor whose output is NOT the harvester — a real
        chain root. Inward-facing guards don't count (Khaos guard mask)."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cx, cy = hx + dx, hy + dy
            f = mi.own_conv_facing.get((cx, cy))
            if f is None:
                continue
            if (cx + f[0], cy + f[1]) != (hx, hy):
                return (cx, cy)
        return None

    def _downhillLink(self, mi, field, x, y):
        """Best empty neighbour to lay the next conveyor on, plus the facing
        that conveyor should have (toward ITS best downhill neighbour)."""
        best = None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < mi.w and 0 <= ny < mi.h):
                continue
            b = mi.bit(nx, ny)
            if (mi.walls | mi.blocked | mi.own_conveyors) & b:
                continue
            d = field[nx + ny * mi.w]
            if best is None or d < best[0]:
                best = (d, nx, ny)
        if best is None or best[0] >= 4096:
            return None, None
        _, lx, ly = best
        fbest = None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            fx, fy = lx + dx, ly + dy
            if not (0 <= fx < mi.w and 0 <= fy < mi.h):
                continue
            fd = field[fx + fy * mi.w]
            if fbest is None or fd < fbest[0]:
                fbest = (fd, dx, dy)
        if fbest is None:
            return None, None
        return Position(lx, ly), DELTA_TO_DIR[(fbest[1], fbest[2])]

    def _orphanHarvesters(self, ct, mi):
        rnd = ct.get_current_round()
        orphans = 0
        for (x, y) in mi.own_harvesters:
            key = ('route', x, y)
            if self.ttl.get(key, 0) > rnd:
                continue
            if self._chainRoot(mi, x, y) is None:
                orphans |= mi.bit(x, y)
        return orphans

    def _deadEnds(self, ct, mi):
        """Own conveyors whose output tile has no continuation (Khaos
        dead-end route targets). Guards (facing into a harvester) excluded."""
        rnd = ct.get_current_round()
        coreMask = self._coreMask()
        ends = 0
        for (x, y), (dx, dy) in mi.own_conv_facing.items():
            if self.ttl.get(('route', x, y), 0) > rnd:
                continue
            ox, oy = x + dx, y + dy
            if (ox, oy) in mi.own_harvesters:
                continue  # inward guard, carries nothing
            if not (0 <= ox < mi.w and 0 <= oy < mi.h):
                ends |= mi.bit(x, y)
                continue
            ob = mi.bit(ox, oy)
            if ob & coreMask:
                continue  # delivers into the core: chain complete
            if mi.own_conveyors & ob:
                continue  # continues into another conveyor/splitter
            ends |= mi.bit(x, y)
        return ends

    def _score_route(self, ct, mi, my_bit, others):
        if self.teamCore is None:
            return 0.0, None
        cands = self._orphanHarvesters(ct, mi) | self._deadEnds(ct, mi)
        if not cands:
            return 0.0, None
        mine = path.claims(mi, my_bit, others, cands)
        if not mine:
            return 0.0, None
        near_enemy = mi.expand(mi.expand(mi.enemy_bots))
        important = mine & near_enemy
        return (7.75 if important else 5.0), mine

    def _run_route(self, ct, mi, mask):
        field = self._routeFieldCached(ct)
        rnd = ct.get_current_round()
        hb = mask & -mask
        hx, hy = mi.xy(hb)
        if field is None:
            return
        coreMask = self._coreMask()
        link = facing = None
        if (hx, hy) in mi.own_conv_facing:
            root = (hx, hy)  # dead-end conveyor target: walk from it
        else:
            root = self._chainRoot(mi, hx, hy)
            # P6 cost gate (Pantheon cost(d)): before STARTING a fresh chain,
            # check we can afford ~the whole line. 0.65 discount — income
            # keeps arriving while we build.
            d = field[hx + hy * mi.w]
            if d < 4096:
                est = 3 * d * ct.get_scale_percent() / 100 * 0.65
                if ct.get_global_resources() < est:
                    self.ttl[('route', hx, hy)] = rnd + 30
                    return
        if root is None:
            link, facing = self._downhillLink(mi, field, hx, hy)
        else:
            # follow the actual chain by facings until it breaks / reaches core
            cur = root
            visited = set()
            for _ in range(mi.w + mi.h):
                if cur in visited:
                    self.ttl[('route', hx, hy)] = rnd + 30
                    return
                visited.add(cur)
                f = mi.own_conv_facing.get(cur)
                if f is None:
                    self.ttl[('route', hx, hy)] = rnd + 15
                    return
                ox, oy = cur[0] + f[0], cur[1] + f[1]
                if not (0 <= ox < mi.w and 0 <= oy < mi.h):
                    link, facing = self._downhillLink(mi, field,
                                                      cur[0], cur[1])
                    break
                ob = mi.bit(ox, oy)
                if ob & coreMask or (ox, oy) in self._connected:
                    self.ttl[('route', hx, hy)] = rnd + 30  # chain complete
                    return
                if (ox, oy) in mi.own_conv_facing:
                    cur = (ox, oy)
                    continue
                if mi.own_conveyors & ob:
                    # splitter / facing not yet observed: assume connected
                    self.ttl[('route', hx, hy)] = rnd + 15
                    return
                if (mi.walls | mi.blocked) & ob:
                    link, facing = self._downhillLink(mi, field,
                                                      cur[0], cur[1])
                    break
                # empty output tile: that's the missing link
                link = Position(ox, oy)
                fbest = None
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    fx, fy = ox + dx, oy + dy
                    if not (0 <= fx < mi.w and 0 <= fy < mi.h):
                        continue
                    fd = field[fx + fy * mi.w]
                    if fbest is None or fd < fbest[0]:
                        fbest = (fd, dx, dy)
                if fbest is None:
                    return
                facing = DELTA_TO_DIR[(fbest[1], fbest[2])]
                break
        if link is None:
            self.ttl[('route', hx, hy)] = rnd + 20
            return
        pos = ct.get_position()
        lb = mi.bit(link.x, link.y)
        if pos == link:
            # standing on the link tile: step aside so we can build it
            self._moveToward(ct, mi.expand(lb) & mi.passable() & ~lb)
            return
        if pos.distance_squared(link) <= 2 and ct.get_action_cooldown() == 0:
            if ct.is_in_vision(link) and ct.can_build_conveyor(link, facing):
                ct.build_conveyor(link, facing)
                mi.own_conveyors |= lb
                mi.own_conv_facing[(link.x, link.y)] = (
                    mapinfo_mod.DIR_DELTA[facing])
                return
            self.ttl[('route', hx, hy)] = rnd + 10
            return
        self._moveToward(ct, mi.expand(lb) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: secure (7.5) — guard-conveyor exposed harvesters near enemies
    # ------------------------------------------------------------------
    def _score_secure(self, ct, mi, my_bit, others):
        if not mi.enemy_buildings and not mi.enemy_bots:
            return 0.0, None
        danger = 0
        for (x, y) in mi.enemy_buildings:
            danger |= mi.bit(x, y)
        danger = mi.expand(mi.expand(mi.expand(danger))) | \
            mi.expand(mi.expand(mi.enemy_bots))
        exposed = 0
        for (x, y) in mi.own_harvesters:
            b = mi.bit(x, y)
            if not (danger & mi.expand(b)):
                continue
            open_sides = mi.expand(b) & ~b & mi.passable() & ~mi.own_conveyors
            if open_sides:
                exposed |= open_sides
        if not exposed:
            return 0.0, None
        mine = path.claims(mi, my_bit, others, exposed)
        if not mine:
            return 0.0, None
        return 7.5, mine

    def _run_secure(self, ct, mi, mask):
        pos = ct.get_position()
        tb = mask & -mask
        tx, ty = mi.xy(tb)
        tpos = Position(tx, ty)
        if pos.distance_squared(tpos) <= 2 and ct.get_action_cooldown() == 0:
            if ct.is_in_vision(tpos):
                # find the harvester this side belongs to
                harv = None
                for d in CARDINALS:
                    hp = tpos.add(d)
                    if (self._inBounds(hp)
                            and (hp.x, hp.y) in mi.own_harvesters):
                        harv = (hp, d)
                        break
                if harv is None:
                    return
                hp, inward = harv
                # Khaos: if this side is the harvester's downhill side, face
                # OUTWARD so the guard doubles as the chain root; otherwise
                # face INTO the harvester so it never carries resources.
                facing = inward
                field = self._routeFieldCached(ct)
                if field is not None:
                    dlink, dfacing = self._downhillLink(mi, field, hp.x, hp.y)
                    if dlink is not None and dlink == tpos:
                        facing = dfacing
                if ct.can_build_conveyor(tpos, facing):
                    ct.build_conveyor(tpos, facing)
                    mi.own_conveyors |= mi.bit(tpos.x, tpos.y)
                    mi.own_conv_facing[(tpos.x, tpos.y)] = (
                        mapinfo_mod.DIR_DELTA[facing])
                return
            return
        self._moveToward(ct, mi.expand(tb) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: harvest (4)
    # ------------------------------------------------------------------
    def _score_harvest(self, ct, mi, my_bit, others):
        rnd = ct.get_current_round()
        # exclude only ore in the CLOSE disc of an enemy turret. The full
        # facing-agnostic band mask vetoed most of the ore field on turret-y
        # maps (quarry: 5-10k mined vs botv2's 18k) — band-edge mining is
        # viable with heal upkeep (v29 lesson).
        hot = 0
        for (x, y) in mi.enemy_turrets:
            hot |= mi.bit(x, y)
        hot = mi.expand(mi.expand(hot))
        cands = mi.ore & mi.seen & ~mi.blocked & ~mi.walls & ~hot
        pruned = 0
        for lsb in mi.iter_bits(cands):
            x, y = mi.xy(lsb)
            if (x, y) in mi.own_harvesters:
                continue
            if self.ttl.get(('harv', x, y), 0) > rnd:
                continue
            pruned |= lsb
        if self.myNum == 1:
            pruned &= self._homeMask()  # home guard mines home ore only
        if not pruned:
            return 0.0, None
        mine = path.claims(mi, my_bit, others, pruned)
        if not mine:
            return 0.0, None
        if ct.get_global_resources() < ct.get_harvester_cost():
            return 0.5, mine
        return 4.0, mine

    def _run_harvest(self, ct, mi, mask):
        pos = ct.get_position()
        target = path.closest(mi, mi.bit(pos.x, pos.y), mask)
        if not target:
            target = mask & -mask
        tx, ty = mi.xy(target)
        tpos = Position(tx, ty)
        rnd = ct.get_current_round()
        if pos == tpos:
            # standing on the ore: sidestep so we can build it
            self._moveToward(ct, mi.expand(target) & mi.passable() & ~target)
            return
        if pos.distance_squared(tpos) <= 2 and ct.get_action_cooldown() == 0:
            if ct.is_in_vision(tpos) and ct.can_build_harvester(tpos):
                ct.build_harvester(tpos)
                mi.own_harvesters[(tx, ty)] = True
                return
            self.ttl[('harv', tx, ty)] = rnd + 25
            return
        self._moveToward(ct, mi.expand(target) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: disrupt (2) — barrier enemy-half ore when rich
    # ------------------------------------------------------------------
    def _score_disrupt(self, ct, mi, my_bit, others):
        if self.myNum == 1:
            return 0.0, None  # home guard stays home
        if ct.get_global_resources() < 5 * ct.get_harvester_cost():
            return 0.0, None
        guess = self._enemyCoreGuess()
        if guess is None or self.teamCore is None:
            return 0.0, None
        rnd = ct.get_current_round()
        cands = 0
        for lsb in mi.iter_bits(mi.ore & mi.seen & ~mi.blocked
                                & ~mi.threat()):
            x, y = mi.xy(lsb)
            p = Position(x, y)
            if manhattan(p, guess) < manhattan(p, self.teamCore) - 2:
                if self.ttl.get(('dis', x, y), 0) <= rnd:
                    cands |= lsb
        if not cands:
            return 0.0, None
        mine = path.claims(mi, my_bit, others, cands)
        if not mine:
            return 0.0, None
        return 2.0, mine

    def _run_disrupt(self, ct, mi, mask):
        pos = ct.get_position()
        tb = mask & -mask
        tx, ty = mi.xy(tb)
        tpos = Position(tx, ty)
        rnd = ct.get_current_round()
        if pos.distance_squared(tpos) <= 2 and pos != tpos \
                and ct.get_action_cooldown() == 0:
            if ct.is_in_vision(tpos) and ct.can_build_barrier(tpos):
                ct.build_barrier(tpos)
                self.ttl[('dis', tx, ty)] = rnd + 1000
                return
            self.ttl[('dis', tx, ty)] = rnd + 50
            return
        if pos == tpos:
            self._moveToward(ct, mi.expand(tb) & mi.passable() & ~tb)
            return
        self._moveToward(ct, mi.expand(tb) & mi.passable())

    # ------------------------------------------------------------------
    # STATE: explore (1)
    # ------------------------------------------------------------------
    def _score_explore(self, ct, mi, my_bit, others):
        return 1.0, None

    def _run_explore(self, ct, mi, _):
        pos = ct.get_position()
        if (self.exploreTarget is not None
                and manhattan(pos, self.exploreTarget) <= 2):
            self.exploreTarget = None
        if self.exploreTarget is None or self.stuck > 4:
            frontier = mi.frontier() & mi.passable()
            if self.myNum == 1:
                frontier &= self._homeMask()  # guard patrols home only
            picked = None
            if frontier:
                bits = list(mi.iter_bits(frontier))
                picked = random.choice(bits[:64])
            if picked:
                x, y = mi.xy(picked)
                self.exploreTarget = Position(x, y)
            elif self.myNum == 1 and self.teamCore is not None:
                self.exploreTarget = Position(
                    max(0, min(mi.w - 1,
                               self.teamCore.x + random.randint(-4, 4))),
                    max(0, min(mi.h - 1,
                               self.teamCore.y + random.randint(-4, 4))))
            else:
                self.exploreTarget = Position(random.randrange(mi.w),
                                              random.randrange(mi.h))
        t = self.exploreTarget
        self._moveToward(ct, mi.bit(t.x, t.y))

    # ------------------------------------------------------------------
    # passive extras
    # ------------------------------------------------------------------
    def _rebuildBroken(self, ct, mi):
        """Replace own barriers we destroyed to walk through (Pantheon)."""
        if not self.brokenBarriers or ct.get_action_cooldown() != 0:
            return
        pos = ct.get_position()
        for p in list(self.brokenBarriers):
            if pos == p:
                continue  # still standing on it; rebuild after stepping off
            if pos.distance_squared(p) > 2:
                self.brokenBarriers.remove(p)  # walked away: let it go
                continue
            if ct.is_in_vision(p) and ct.can_build_barrier(p):
                ct.build_barrier(p)
                mi.own_barriers |= mi.bit(p.x, p.y)
                mi.note_tile(p.x, p.y, mapinfo_mod.T_BLOCK)
            self.brokenBarriers.remove(p)
            return

    def _tryChokeBlock(self, ct, mi):
        if ct.get_action_cooldown() != 0 or not mapanalysis.chokes \
                or self.teamCore is None:
            return
        pos = ct.get_position()
        enemyRef = self._enemyCoreGuess()
        ti = ct.get_global_resources()
        for choke in mapanalysis.chokes:
            tile, clearance = choke[0], choke[1]
            p = Position(tile[0], tile[1])
            if pos.distance_squared(p) > 2:
                continue
            if (enemyRef is not None
                    and manhattan(p, self.teamCore) >= manhattan(p, enemyRef)):
                continue
            if not self._inBounds(p) or not ct.is_in_vision(p):
                continue
            if ct.get_tile_building_id(p) is not None:
                continue
            if ct.get_tile_env(p) == Environment.ORE_TITANIUM:
                continue
            if clearance <= 1.2:
                if ti >= ct.get_barrier_cost() + 30 and ct.can_build_barrier(p):
                    ct.build_barrier(p)
                    return
            elif ti >= 100 and ct.can_build_launcher(p):
                ct.build_launcher(p)
                return

    def _healAdjacent(self, ct):
        if ct.get_action_cooldown() != 0:
            return
        pos = ct.get_position()
        if ct.get_hp() < ct.get_max_hp() and ct.can_heal(pos):
            ct.heal(pos)
            return
        # Pantheon 6-tier heal priority: (very damaged?, type tier, damage)
        TIER = {EntityType.CORE: 6, EntityType.GUNNER: 5,
                EntityType.SENTINEL: 5, EntityType.LAUNCHER: 5,
                EntityType.HARVESTER: 4, EntityType.CONVEYOR: 3,
                EntityType.SPLITTER: 2, EntityType.BARRIER: 2}
        best = None
        for bid in ct.get_nearby_buildings(2):
            if ct.get_team(bid) != ct.get_team():
                continue
            dmg = ct.get_max_hp(bid) - ct.get_hp(bid)
            if dmg >= 4:
                p = ct.get_position(bid)
                key = (1 if dmg >= 12 else 0,
                       TIER.get(ct.get_entity_type(bid), 1), dmg)
                if best is None or key > best[0]:
                    best = (key, p)
        if best is not None and ct.can_heal(best[1]):
            ct.heal(best[1])

    def _advanceAnalysis(self, ct):
        job = mapanalysis.job
        if job is None and ct.get_cpu_time_elapsed() < mapanalysis.CPU_BUDGET_US:
            job = mapanalysis.get_job()
        while (job is not None
               and ct.get_cpu_time_elapsed() < mapanalysis.CPU_BUDGET_US
               and job.phase != mapanalysis.DONE):
            job.step()

    # ------------------------------------------------------------------
    # Turrets (ported from botv2 — proven handlers)
    # ------------------------------------------------------------------
    def sentinel(self, ct: Controller) -> None:
        if self.teamCore is None:
            for bid in ct.get_nearby_buildings():
                if (ct.get_entity_type(bid) == EntityType.CORE
                        and ct.get_team(bid) == ct.get_team()):
                    self.teamCore = ct.get_position(bid)
        team = ct.get_team()
        seesEnemy = False
        for eid in ct.get_nearby_entities():
            if ct.get_team(eid) != team:
                seesEnemy = True
                break
        if seesEnemy:
            self.idleTurns = 0
        else:
            self.idleTurns += 1
            if self.idleTurns > 40 and ct.get_current_round() > 150:
                nearHarv = any(
                    ct.get_team(b) == team
                    and ct.get_entity_type(b) == EntityType.HARVESTER
                    for b in ct.get_nearby_buildings(8))
                nearCore = (self.teamCore is not None
                            and manhattan(ct.get_position(),
                                          self.teamCore) <= 6)
                if not nearHarv and not nearCore:
                    ct.self_destruct()
                    return
        priority = {
            EntityType.CORE: 5, EntityType.SENTINEL: 3, EntityType.GUNNER: 3,
            EntityType.BARRIER: 2, EntityType.LAUNCHER: 2,
            EntityType.CONVEYOR: 1,
        }
        targets = set(priority)
        bestTile, bestKey = None, None
        for tile in ct.get_attackable_tiles():
            if not self._inBounds(tile) or not ct.is_in_vision(tile):
                continue
            buildingID = ct.get_tile_building_id(tile)
            builderID = ct.get_tile_builder_bot_id(tile)
            if builderID is not None and ct.get_team(builderID) == team:
                continue
            if buildingID is not None and ct.get_team(buildingID) == team:
                continue
            tilePriority, targetHp = 0, 0
            if buildingID is not None:
                btype = ct.get_entity_type(buildingID)
                if btype not in targets:
                    continue
                tilePriority = priority.get(btype, 1)
                targetHp = ct.get_hp(buildingID)
                if builderID is not None:
                    tilePriority += 2
            elif builderID is not None:
                continue
            key = (tilePriority, 1 if 0 < targetHp <= 18 else 0, -targetHp)
            if bestTile is None or key > bestKey:
                bestKey, bestTile = key, tile
        if bestTile is None:
            return
        # Pantheon one-tap lock: if the target survives one shot and a
        # LOWER-id ally sentinel also covers it, hold fire — lower id acts
        # first, so next turn both shots land the same round (36 dmg kills
        # anything but a core chunk) before enemy medics can heal. Bounded
        # wait so a dead ally can't deadlock us.
        targetHp = 0
        bid = ct.get_tile_building_id(bestTile) \
            if ct.is_in_vision(bestTile) else None
        if bid is not None:
            targetHp = ct.get_hp(bid)
        if targetHp > 18 and self.tapWait < 2:
            myId = ct.get_id()
            myPos = ct.get_position()
            for aid in ct.get_nearby_entities():
                if (aid < myId and ct.get_team(aid) == ct.get_team()
                        and ct.get_entity_type(aid) == EntityType.SENTINEL
                        and ct.get_position(aid).distance_squared(bestTile)
                        <= 32):
                    self.tapWait += 1
                    return
        self.tapWait = 0
        if ct.can_fire(bestTile):
            ct.fire(bestTile)

    def gunner(self, ct: Controller) -> None:
        target = ct.get_gunner_target()
        if target is not None:
            builder_id = ct.get_tile_builder_bot_id(target)
            building_id = ct.get_tile_building_id(target)
            tid = builder_id if builder_id is not None else building_id
            if tid is not None and ct.get_team(tid) != ct.get_team():
                if ct.can_fire(target):
                    ct.fire(target)
                return
        if ct.get_global_resources() < 60 or ct.get_action_cooldown() != 0:
            return
        my_pos = ct.get_position()
        current = ct.get_direction()
        cands = []
        for eid in ct.get_nearby_entities(13):
            et = ct.get_entity_type(eid)
            if et not in (EntityType.GUNNER, EntityType.SENTINEL,
                          EntityType.BUILDER_BOT):
                continue
            if ct.get_team(eid) == ct.get_team():
                continue
            ep = ct.get_position(eid)
            dx, dy = ep.x - my_pos.x, ep.y - my_pos.y
            if dx != 0 and dy != 0:
                continue
            if dx > 0:
                f = Direction.EAST
            elif dx < 0:
                f = Direction.WEST
            elif dy > 0:
                f = Direction.SOUTH
            elif dy < 0:
                f = Direction.NORTH
            else:
                continue
            if f == current:
                continue
            pr = 0 if et in (EntityType.GUNNER, EntityType.SENTINEL) else 1
            cands.append((pr, my_pos.distance_squared(ep),
                          CARDINALS.index(f), f))
        if cands:
            f = min(cands)[3]
            if ct.can_rotate(f):
                ct.rotate(f)

    def launcher(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        if self.teamCore is None:
            for bid in ct.get_nearby_buildings():
                if (ct.get_entity_type(bid) == EntityType.CORE
                        and ct.get_team(bid) == ct.get_team()):
                    self.teamCore = ct.get_position(bid)
        anchor = self.teamCore if self.teamCore is not None else myLoc
        team = ct.get_team()
        hist = self.enemyBotHistory
        for uid in ct.get_nearby_units():
            if (ct.get_team(uid) != team
                    and ct.get_entity_type(uid) == EntityType.BUILDER_BOT):
                ep = ct.get_position(uid)
                lst = hist.setdefault(uid, [])
                if not lst or lst[-1] != ep:
                    lst.append(ep)
                    if len(lst) > 12:
                        lst.pop(0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                adjacent = Position(myLoc.x + dx, myLoc.y + dy)
                if (not self._inBounds(adjacent)
                        or not ct.is_in_vision(adjacent)):
                    continue
                bot_id = ct.get_tile_builder_bot_id(adjacent)
                if bot_id is None or ct.get_team(bot_id) == team:
                    continue
                walked = set(hist.get(bot_id, ())[:-3])
                # Pantheon region-minimizing throw: flood the area the bot
                # could navigate from each destination (enemy-POV, unseen =
                # impassable) and throw into the SMALLEST pocket. Trail tiles
                # (trap: forced retrace) outrank everything.
                mi = self.mi
                if mi is None:
                    w, h = ct.get_map_width(), ct.get_map_height()
                    self.mi = mi = mapinfo_mod.MapInfo(w, h)
                mi.update_vision(ct)
                epass = mi.seen & ~mi.walls & ~mi.blocked
                best, bestKey = None, None
                for tile in ct.get_nearby_tiles(26):
                    if not ct.can_launch(adjacent, tile):
                        continue
                    seed = mi.bit(tile.x, tile.y)
                    region = seed
                    for _ in range(12):
                        grown = mi.expand(region) & epass
                        if grown == region:
                            break
                        region = grown
                    size = bin(region).count('1')
                    key = (1 if tile in walked else 0,
                           -size, manhattan(anchor, tile))
                    if bestKey is None or key > bestKey:
                        bestKey, best = key, tile
                if best is not None:
                    ct.launch(adjacent, best)
                    return

    # ---- misc ----
    def _inBounds(self, p):
        mi = self.mi
        if mi is None:
            return False
        return 0 <= p.x < mi.w and 0 <= p.y < mi.h

    @staticmethod
    def _cardinalTo(origin, target):
        dx = target.x - origin.x
        dy = target.y - origin.y
        if abs(dx) >= abs(dy) and dx != 0:
            return Direction.EAST if dx > 0 else Direction.WEST
        if dy != 0:
            return Direction.SOUTH if dy > 0 else Direction.NORTH
        return Direction.CENTRE
