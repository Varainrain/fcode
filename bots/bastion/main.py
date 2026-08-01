"""BASTION — a from-scratch concept bot with ONE thesis: NEVER DIE.

(19 measured graft failures say mechanisms only work inside a design built
for them. This is the Ijti absorb strategy built AS the design, from their
spec: 15 replays, 12 with barrier placements. They beat lastpopperian_ 4-1
twice by TAKING the first core hit at t35-55 and winning at t218-285.)

The three commitments (each half-measure was measured useless alone):
  GARRISON   two builders live within ~4 of the core, forever. Response to
             a new enemy turret in 1-2 turns because the bodies are home.
  PRE-ARMOR  barriers at t15 in the enemy-facing seat zone (manhattan 2-3,
             diagonals first — where siege guns must sit). Own barriers
             are PASSABLE to own units, so armor never chokes movement.
  REBUILD    a broken barrier is replaced within a few turns, forever.
             Economics: attacker pays 3 shots / 6 ammo per 30hp barrier,
             we repay 3 Ti + one action. With income, the wall is infinite.
Plus: garrison HEALS the core (4hp/1Ti each), and seats a counter-gunner
with line of sight when a siege gun parks (gunner kills gunner in 4 turns;
a builder needs 20 — never plink).
Economy: mech-v1's outward network growth (measured 550+ mined). Fat econ
wins the t1000 tiebreak if nobody dies — that is a WIN condition here.
Attack: at t100, one builder converts to a lastpop-style seat siege —
the grind counter-kill, after the absorb has held.

Roles by CLAIM SLOTS (store 8/9), never by spawn index — the core bumps
slot 0 before a new builder ever runs (off-by-one) and can bump it again
before its first turn (race): both documented silent killers.
"""

from collections import deque

from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
DELTA = {(0, -1): Direction.NORTH, (0, 1): Direction.SOUTH,
         (1, 0): Direction.EAST, (-1, 0): Direction.WEST}

AMMO_BUFFER = 30      # gunner shot costs 2; keep a line of guns fed
RESERVE = 5           # never spend the last few Ti
GUNS_PER_RUSHER = 3   # (unused by bastion's siege; kept for run_gunner)

GARRISON_SLOT = 8     # store: how many garrison claims taken
GARRISON_N = 2        # Ijti keeps ~2 bodies home
HOME_R = 4            # garrison leash (manhattan from core footprint)
PREARMOR_ROUND = 15   # their pre-armor timing on dangerous maps
PREARMOR_N = 4        # barriers in the seat zone
SIEGE_SLOT = 9        # store: siege claims taken
SIEGE_N = 1           # one grinder, after the absorb holds
SIEGE_ROUND = 100
SIEGE_MIN, SIEGE_MAX = 2, 5
TURRET_NEAR = 6       # enemy turret this close to core = under siege


class Player:
    def __init__(self):
        self.idx = None          # spawn order = role
        self.role = None
        self.core = None         # our core (top-left tile of the 2x2)
        self.enemy = None        # enemy core guess (point mirror)
        self.w = self.h = None
        self.walls = set()       # known impassable tiles
        self.spawned = 0
        self.guns = 0
        self.stuck = 0
        self.last = None
        self.chain = None        # econ: head of the conveyor line being laid
        self._zone = None         # cached seat-zone tiles
        self._armored = 0         # pre-armor barriers I have placed

    # ------------------------------------------------------------------
    def run(self, ct: Controller) -> None:
        # dev26: an uncaught exception permanently destroys this unit
        try:
            if self.w is None:
                self.w, self.h = ct.get_map_width(), ct.get_map_height()
            t = ct.get_entity_type()
            if t == EntityType.CORE:
                self.run_core(ct)
            elif t == EntityType.BUILDER_BOT:
                self.run_builder(ct)
            elif t == EntityType.GUNNER:
                self.run_gunner(ct)
        except Exception:
            pass

    # ---------------------------------------------------------- the core
    def run_core(self, ct: Controller) -> None:
        if self.core is None:
            self.core = ct.get_position()
        ti = ct.get_global_resources()
        # keep the crew coming — builders are how everything happens
        if ti > ct.get_builder_bot_cost() + RESERVE:
            for p in ct.get_nearby_tiles():
                if ct.can_spawn(p):
                    ct.spawn_builder(p)
                    self.spawned += 1
                    ct.write_store(0, self.spawned)
                    break
        # feed the guns
        ammo = ct.get_global_ammo()
        if ammo < AMMO_BUFFER and ti > 90:
            amt = min(AMMO_BUFFER - ammo, ti - 80)
            if amt > 0 and ct.can_convert_ammo(amt):
                ct.convert_ammo(amt)

    # ------------------------------------------------------- the builders
    def run_builder(self, ct: Controller) -> None:
        pos = ct.get_position()
        self.observe(ct)
        if self.core is None:
            for b in ct.get_nearby_buildings():
                if (ct.get_entity_type(b) == EntityType.CORE
                        and ct.get_team(b) == ct.get_team()):
                    self.core = ct.get_position(b)
                    break
        if self.core is None:
            return
        if self.enemy is None:
            self.enemy = Position(self.w - 1 - self.core.x,
                                  self.h - 1 - self.core.y)
        if self.role is None:
            taken = ct.read_store(GARRISON_SLOT)
            if taken < GARRISON_N:
                ct.write_store(GARRISON_SLOT, taken + 1)
                self.role = "garrison"
            else:
                self.role = "econ"
            self.idx = ct.read_store(0)
        # decide AT the trigger round, never before (latch-bug lesson)
        if (self.role == "econ"
                and ct.get_current_round() >= SIEGE_ROUND):
            taken = ct.read_store(SIEGE_SLOT)
            if taken < SIEGE_N:
                ct.write_store(SIEGE_SLOT, taken + 1)
                self.role = "siege"
        # unstick: bots that haven't moved in a while take any legal step
        if self.last == (pos.x, pos.y):
            self.stuck += 1
        else:
            self.stuck = 0
        self.last = (pos.x, pos.y)

        if self.role == "garrison":
            self.do_garrison(ct, pos)
        elif self.role == "siege":
            self.do_siege(ct, pos)
        else:
            self.do_econ(ct, pos)

    # ---- role: garrison — the thesis
    def _seatZone(self, ct: Controller):
        """Enemy-facing tiles at manhattan 2-3 from the core footprint,
        diagonals first — where siege guns sit (lastpopperian_ autopsy:
        seats at d2-5, diagonals preferred) and where Ijti pre-armors."""
        if self._zone is not None:
            return self._zone
        foot = [(self.core.x + a, self.core.y + b)
                for a in (0, 1) for b in (0, 1)]
        eg = (self.w - 1 - self.core.x, self.h - 1 - self.core.y)
        cd = abs(self.core.x - eg[0]) + abs(self.core.y - eg[1])
        out = []
        for dx in range(-3, 5):
            for dy in range(-3, 5):
                x, y = self.core.x + dx, self.core.y + dy
                if not (0 <= x < self.w and 0 <= y < self.h):
                    continue
                if (x, y) in foot:
                    continue
                d = min(abs(x - c[0]) + abs(y - c[1]) for c in foot)
                if not (2 <= d <= 3):
                    continue
                if abs(x - eg[0]) + abs(y - eg[1]) > cd:
                    continue                    # home side stays open
                diag = (x != self.core.x and x != self.core.x + 1
                        and y != self.core.y and y != self.core.y + 1)
                out.append((0 if diag else 1, d, Position(x, y)))
        out.sort(key=lambda t: (t[0], t[1]))
        self._zone = [t[2] for t in out]
        return self._zone

    def _laneTile(self, ct: Controller, tp, foot):
        """First free tile on the straight 8-dir ray from an enemy turret
        to a core foot tile — a barrier there eats the shots."""
        for c in foot:
            dx, dy = c[0] - tp[0], c[1] - tp[1]
            if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
                continue
            sx = (dx > 0) - (dx < 0)
            sy = (dy > 0) - (dy < 0)
            x, y = tp[0] + sx, tp[1] + sy
            while (x, y) != c:
                q = Position(x, y)
                try:
                    if (ct.is_in_vision(q)
                            and ct.get_tile_building_id(q) is None
                            and ct.get_tile_env(q) == Environment.EMPTY):
                        return q
                except Exception:
                    pass
                x += sx
                y += sy
        return None

    def do_garrison(self, ct: Controller, pos: Position) -> None:
        """Priorities, in Ijti's measured order:
        1. heal a damaged core (4hp per builder-turn, 1 Ti)
        2. block the lane of any enemy turret at the doorstep (this IS the
           rebuild loop: when the barrier dies the lane opens and this
           fires again — observed on Ijti: replacements every ~4 turns)
        3. counter-SEAT a gunner with line of sight to that turret
        4. pre-armor the seat zone from t15
        5. hold the leash, mine opportunistically, never leave"""
        foot = [(self.core.x + a, self.core.y + b)
                for a in (0, 1) for b in (0, 1)]
        ti = ct.get_global_resources()
        # 1. heal
        if ct.can_act():
            for c in foot:
                cp = Position(c[0], c[1])
                if manhattan(pos, cp) == 1:
                    try:
                        cid = ct.get_tile_building_id(cp)
                        if (cid is not None
                                and ct.get_hp(cid) < 500 and ti > 2
                                and ct.can_heal(cp)):
                            ct.heal(cp)
                            return
                    except Exception:
                        pass
        # find the siege gun, if any
        threat = None
        for b in ct.get_nearby_entities():
            try:
                if ct.get_team(b) == ct.get_team():
                    continue
                if ct.get_entity_type(b) not in (EntityType.GUNNER,
                                                 EntityType.SENTINEL):
                    continue
                bp = ct.get_position(b)
                if min(abs(bp.x - c[0]) + abs(bp.y - c[1])
                       for c in foot) <= TURRET_NEAR:
                    threat = bp
                    break
            except Exception:
                continue
        # 2. lane barrier / rebuild loop
        if threat is not None and ti > 5:
            lane = self._laneTile(ct, (threat.x, threat.y), foot)
            if lane is not None:
                d = manhattan(pos, lane)
                if d == 1:
                    if ct.can_act() and ct.can_build_barrier(lane):
                        ct.build_barrier(lane)
                        return
                elif d > 1:
                    self.step_to(ct, lane)
                    return
        # 3. counter-seat: a gunner kills a gunner in 4 turns; a builder
        #    needs 20 — never plink (2nd-place Turret Takedown)
        if (threat is not None and ct.can_act()
                and ti > ct.get_gunner_cost() + RESERVE):
            for d in CARDINALS:
                spot = pos.add(d)
                if not (0 <= spot.x < self.w and 0 <= spot.y < self.h):
                    continue
                try:
                    if not ct.is_in_vision(spot):
                        continue
                    if ct.get_tile_building_id(spot) is not None:
                        continue
                    for f in DIRECTIONS:
                        if not ct.can_fire_from(spot, f, EntityType.GUNNER,
                                                threat):
                            continue
                        if ct.can_build_gunner(spot, f):
                            ct.build_gunner(spot, f)
                            return
                        break
                except Exception:
                    continue
        # 4. pre-armor
        if (ct.get_current_round() >= PREARMOR_ROUND and ti > 20
                and self._armored < PREARMOR_N and ct.can_act()):
            for z in self._seatZone(ct):
                try:
                    if not ct.is_in_vision(z):
                        continue
                    if ct.get_tile_building_id(z) is not None:
                        continue
                    if ct.get_tile_env(z) != Environment.EMPTY:
                        continue
                except Exception:
                    continue
                if manhattan(pos, z) == 1:
                    if ct.can_build_barrier(z):
                        ct.build_barrier(z)
                        self._armored += 1
                        return
                    break
                self.step_to(ct, z)
                return
        # 5. hold the leash — mine adjacent ore opportunistically
        homeD = min(abs(pos.x - c[0]) + abs(pos.y - c[1]) for c in foot)
        if homeD > HOME_R:
            self.step_to(ct, self.core)
            return
        if ct.can_act() and ti > ct.get_harvester_cost() + RESERVE:
            for t in self.visible_ore(ct):
                if manhattan(pos, t) == 1 and self.touches_net(ct, t):
                    if ct.can_build_harvester(t):
                        ct.build_harvester(t)
                        return

    # ---- role: siege (the grind counter-kill, lastpop seat logic)
    def do_siege(self, ct: Controller, pos: Position) -> None:
        target = self.enemy_core_tile(ct)
        if target is None:
            return
        if manhattan(pos, target) > SIEGE_MAX + 3:
            self.step_to(ct, target)
            return
        # cap: at most 3 of our guns near their core — v0 planted one every
        # turn forever (1000+ creates vs nop) and would bankrupt any econ
        mine = 0
        for b in ct.get_nearby_entities():
            try:
                if (ct.get_team(b) == ct.get_team()
                        and ct.get_entity_type(b) == EntityType.GUNNER
                        and manhattan(ct.get_position(b), target) <= SIEGE_MAX):
                    mine += 1
            except Exception:
                continue
        if mine >= 3:
            return
        seat = None
        for t in ct.get_nearby_tiles():
            if not (SIEGE_MIN <= manhattan(t, target) <= SIEGE_MAX):
                continue
            try:
                if not ct.is_in_vision(t):
                    continue
                if ct.get_tile_building_id(t) is not None:
                    continue
                if ct.get_tile_env(t) != Environment.EMPTY:
                    continue
            except Exception:
                continue
            face = None
            for f in DIRECTIONS:
                try:
                    if ct.can_fire_from(t, f, EntityType.GUNNER, target):
                        face = f
                        break
                except Exception:
                    continue
            if face is None:
                continue
            diag = (t.x != target.x and t.y != target.y)
            key = (0 if diag else 1, manhattan(pos, t))
            if seat is None or key < seat[0]:
                seat = (key, t, face)
        if seat is not None:
            _, spot, face = seat
            if manhattan(pos, spot) == 1:
                if (ct.can_act()
                        and ct.get_global_resources()
                        > ct.get_gunner_cost() + RESERVE
                        and ct.can_build_gunner(spot, face)):
                    ct.build_gunner(spot, face)
                return
            self.step_to(ct, spot)
            return
        self.step_to(ct, target)

    # ---- role: waller (unused)
    def do_wall(self, ct: Controller, pos: Position) -> None:
        holes = self.wall_tiles(ct)
        if not holes:                       # ring sealed — go mine
            self.role = "econ"
            return self.do_econ(ct, pos)
        if ct.can_act():
            for h in holes:
                if manhattan(pos, h) != 1:
                    continue
                face = self.chain_face(ct, h)
                if face is not None and ct.can_build_conveyor(h, face):
                    ct.build_conveyor(h, face)
                    return
        self.step_to(ct, min(holes, key=lambda q: manhattan(pos, q)))

    def wall_tiles(self, ct: Controller):
        """Tiles an enemy gunner would shoot our core from: the ring on the
        enemy-facing half, plus the cardinal firing lanes at distance 2-3
        and the 2-step diagonals (facing is 8-way). The HOME half stays
        open on purpose — the core spawns builders onto those tiles and
        they are its only heal positions."""
        cx, cy = self.core.x, self.core.y
        foot = {(cx + a, cy + b) for a in (0, 1) for b in (0, 1)}
        eg = self.enemy
        cd = abs(cx + 0.5 - eg.x) + abs(cy + 0.5 - eg.y)
        cand = []
        for x in range(cx - 1, cx + 3):     # the ring, enemy half only
            for y in range(cy - 1, cy + 3):
                if (x, y) in foot:
                    continue
                if abs(x - eg.x) + abs(y - eg.y) <= cd:
                    cand.append((x, y))
        for o in (0, 1):                    # cardinal lanes
            for d in (2, 3):
                cand += [(cx - d, cy + o), (cx + 1 + d, cy + o),
                         (cx + o, cy - d), (cx + o, cy + 1 + d)]
        for a in (0, 1):                    # 2-step diagonals
            for b in (0, 1):
                for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                    cand.append((cx + a + 2 * dx, cy + b + 2 * dy))
        out = []
        for (x, y) in cand:
            if not (0 <= x < self.w and 0 <= y < self.h):
                continue
            p = Position(x, y)
            if not ct.is_in_vision(p):
                continue
            if ct.get_tile_building_id(p) is not None:
                continue
            if ct.get_tile_env(p) != Environment.EMPTY:
                continue
            out.append(p)
        out.sort(key=lambda q: abs(q.x - eg.x) + abs(q.y - eg.y))
        return out

    def chain_face(self, ct: Controller, tile: Position):
        """Facing for a wall conveyor: it must output into the core or an
        existing own conveyor. A dead-end conveyor swallows every harvest
        chain that later routes into it (measured: 160 mined vs 1500)."""
        foot = {(self.core.x + a, self.core.y + b)
                for a in (0, 1) for b in (0, 1)}
        best = None
        for d in CARDINALS:
            n = tile.add(d)
            if (n.x, n.y) in foot:
                return d
            if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                continue
            if not ct.is_in_vision(n):
                continue
            bid = ct.get_tile_building_id(n)
            if (bid is not None and ct.get_team(bid) == ct.get_team()
                    and ct.get_entity_type(bid) == EntityType.CONVEYOR):
                dd = manhattan(n, self.core)
                if best is None or dd < best[0]:
                    best = (dd, d)
        return best[1] if best else None

    # ---- role: economy
    # A harvester only pays if its output reaches the core, so this runs as
    # two explicit phases: plant one harvester, then walk its conveyor line
    # home before planting the next. (v1 planted harvesters and never wired
    # them: 0 titanium mined all game.)
    def do_econ(self, ct: Controller, pos: Position) -> None:
        # RULE: only ever plant a harvester that is ALREADY touching the
        # network (core or our conveyors), and only ever lay a conveyor
        # that touches it too. Connectivity is then true by construction.
        # (v1 chained backward from the harvester and skipped blocked
        # tiles, leaving gaps — 1 harvester + 1 disconnected conveyor and
        # 0 titanium mined across a whole game.)
        free_ore = self.visible_ore(ct)
        # A) ore already on the network -> plant it
        for t in free_ore:
            if not self.touches_net(ct, t):
                continue
            if manhattan(pos, t) == 1:
                if (ct.can_act()
                        and ct.get_global_resources()
                        > ct.get_harvester_cost() + RESERVE
                        and ct.can_build_harvester(t)):
                    ct.build_harvester(t)
                return
            self.step_to(ct, t)
            return
        # B) grow the network one tile toward the nearest free ore
        if free_ore:
            goal = min(free_ore, key=lambda t: manhattan(pos, t)
                       + 2 * manhattan(t, self.core))
            spot = self.grow_spot(ct, pos, goal)
            if spot is not None:
                tile, face = spot
                if manhattan(pos, tile) == 1:
                    if (ct.can_act()
                            and ct.get_global_resources()
                            > ct.get_conveyor_cost() + RESERVE
                            and ct.can_build_conveyor(tile, face)):
                        ct.build_conveyor(tile, face)
                    return
                self.step_to(ct, tile)
                return
            self.step_to(ct, goal)
            return
        ore = None
        for t in ct.get_nearby_tiles():
            try:
                if ct.get_tile_env(t) != Environment.ORE_TITANIUM:
                    continue
            except Exception:
                continue
            if ct.get_tile_building_id(t) is not None:
                continue
            # prefer ore near HOME: the conveyor line back is the expensive
            # part (one tile per ~2 turns under act-xor-move), so a close
            # patch pays far sooner than a rich far one
            score = manhattan(pos, t) + 2 * manhattan(t, self.core)
            if ore is None or score < ore[0]:
                ore = (score, t)
        ore = ore[1] if ore else None
        if ore is None:
            # No ore in vision. Walking home would park us there forever —
            # on a 26x26 map that meant 0 titanium mined all game. Sweep
            # outward instead, each econ bot on its own heading.
            self.probe = getattr(self, "probe", 0) + 1
            ring = 4 + (self.probe // 12) * 3
            ang = (self.idx * 2 + self.probe // 24) % 4
            dx, dy = ((1, 0), (0, 1), (-1, 0), (0, -1))[ang]
            goal = Position(
                max(0, min(self.w - 1, self.core.x + dx * ring)),
                max(0, min(self.h - 1, self.core.y + dy * ring)))
            self.step_to(ct, goal)
            return
        if manhattan(pos, ore) > 1:
            self.step_to(ct, ore)
            return
        if (ct.can_act()
                and ct.get_global_resources() > ct.get_harvester_cost() + RESERVE
                and ct.can_build_harvester(ore)):
            ct.build_harvester(ore)
            self.chain = ore                # start wiring from here
            return
        self.step_to(ct, self.core)

    def visible_ore(self, ct: Controller):
        out = []
        for t in ct.get_nearby_tiles():
            try:
                if ct.get_tile_env(t) != Environment.ORE_TITANIUM:
                    continue
                if ct.get_tile_building_id(t) is not None:
                    continue
            except Exception:
                continue
            out.append(t)
        return out

    def net_face(self, ct: Controller, tile: Position):
        """Direction from `tile` into our network (core foot or one of our
        conveyors), or None if it doesn't touch the network."""
        foot = {(self.core.x + a, self.core.y + b)
                for a in (0, 1) for b in (0, 1)}
        for d in CARDINALS:
            n = tile.add(d)
            if (n.x, n.y) in foot:
                return d
            if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                continue
            try:
                if not ct.is_in_vision(n):
                    continue
                bid = ct.get_tile_building_id(n)
            except Exception:
                continue
            if (bid is not None and ct.get_team(bid) == ct.get_team()
                    and ct.get_entity_type(bid) == EntityType.CONVEYOR):
                return d
        return None

    def touches_net(self, ct: Controller, tile: Position) -> bool:
        return self.net_face(ct, tile) is not None

    def grow_spot(self, ct: Controller, pos: Position, goal: Position):
        """Best empty tile that touches the network and moves us toward
        `goal`, plus the facing that points back into the network."""
        best = None
        for t in ct.get_nearby_tiles():
            try:
                if ct.get_tile_building_id(t) is not None:
                    continue
                if ct.get_tile_env(t) != Environment.EMPTY:
                    continue
            except Exception:
                continue
            face = self.net_face(ct, t)
            if face is None:
                continue
            score = manhattan(t, goal) * 2 + manhattan(pos, t)
            if best is None or score < best[0]:
                best = (score, t, face)
        return (best[1], best[2]) if best else None

    def chain_next(self, ct: Controller):
        """Next (tile, facing) to lay, walking from self.chain toward the
        core. Returns None once the line touches the core or an existing
        conveyor — a chain that dead-ends swallows everything routed in."""
        foot = {(self.core.x + a, self.core.y + b)
                for a in (0, 1) for b in (0, 1)}
        head = self.chain
        best = None
        for d in CARDINALS:
            n = head.add(d)
            if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                continue
            if (n.x, n.y) in foot:
                return None                 # home already
            if (n.x, n.y) in self.walls:
                continue
            if ct.is_in_vision(n):
                bid = ct.get_tile_building_id(n)
                if bid is not None:
                    if (ct.get_team(bid) == ct.get_team()
                            and ct.get_entity_type(bid) == EntityType.CONVEYOR):
                        return None         # joined the existing network
                    continue
            dd = manhattan(n, self.core)
            if best is None or dd < best[0]:
                best = (dd, n)
        if best is None:
            return None
        tile = best[1]
        # face the step after this one (or the core if we arrive)
        face, fbest = None, None
        for d in CARDINALS:
            n = tile.add(d)
            if not (0 <= n.x < self.w and 0 <= n.y < self.h):
                continue
            dd = manhattan(n, self.core)
            if fbest is None or dd < fbest:
                fbest, face = dd, d
        return (tile, face) if face else None

    # ---- role: rush
    def do_rush(self, ct: Controller, pos: Position) -> None:
        target = self.enemy_core_tile(ct)
        # plant a gunner that can actually hit the core from where it stands
        if (self.guns < GUNS_PER_RUSHER and ct.can_act()
                and ct.get_global_resources() > ct.get_gunner_cost() + RESERVE):
            for d in CARDINALS:
                spot = pos.add(d)
                if not (0 <= spot.x < self.w and 0 <= spot.y < self.h):
                    continue
                if not ct.is_in_vision(spot):
                    continue
                if ct.get_tile_building_id(spot) is not None:
                    continue
                for f in DIRECTIONS:
                    try:
                        if not ct.can_fire_from(spot, f, EntityType.GUNNER, target):
                            continue
                    except Exception:
                        continue
                    if ct.can_build_gunner(spot, f):
                        ct.build_gunner(spot, f)
                        self.guns += 1
                        return
        # standing on an enemy building next to their core: break it
        if ct.can_act():
            for d in CARDINALS:
                n = pos.add(d)
                if not ct.is_in_vision(n):
                    continue
                bid = ct.get_tile_building_id(n)
                if bid is not None and ct.get_team(bid) != ct.get_team():
                    if manhattan(n, target) <= 4 and ct.can_fire(n):
                        ct.fire(n)
                        return
        self.step_to(ct, target)

    def enemy_core_tile(self, ct: Controller) -> Position:
        for b in ct.get_nearby_buildings():
            try:
                if (ct.get_entity_type(b) == EntityType.CORE
                        and ct.get_team(b) != ct.get_team()):
                    self.enemy = ct.get_position(b)
                    return self.enemy
            except Exception:
                pass
        return self.enemy

    # --------------------------------------------------------- the guns
    def run_gunner(self, ct: Controller) -> None:
        tgt = ct.get_gunner_target()
        if tgt is not None:
            bid = ct.get_tile_building_id(tgt)
            bot = ct.get_tile_builder_bot_id(tgt)
            if bot is not None and ct.get_team(bot) == ct.get_team():
                return                      # never shoot our own
            if bid is not None and ct.get_team(bid) != ct.get_team():
                if ct.can_fire(tgt):
                    ct.fire(tgt)
                    return
        # nothing in the lane: turn toward whatever we can hit
        if ct.get_global_resources() < 60:
            return
        me = ct.get_position()
        for f in DIRECTIONS:
            try:
                tiles = ct.get_attackable_tiles_from(me, f, EntityType.GUNNER)
            except Exception:
                continue
            for t in tiles:
                bid = ct.get_tile_building_id(t)
                if bid is not None and ct.get_team(bid) != ct.get_team():
                    if f != ct.get_direction() and ct.can_rotate(f):
                        ct.rotate(f)
                        return
                    break

    # ------------------------------------------------------------ moving
    def observe(self, ct: Controller) -> None:
        for t in ct.get_nearby_tiles():
            try:
                if ct.get_tile_env(t) == Environment.WALL:
                    self.walls.add((t.x, t.y))
            except Exception:
                pass

    def step_to(self, ct: Controller, goal: Position) -> None:
        """BFS over known terrain (unknown assumed passable), one step."""
        if goal is None or ct.get_move_cooldown() != 0:
            return
        pos = ct.get_position()
        if self.stuck > 3:                  # jiggle out of a jam
            for d in CARDINALS:
                if ct.can_move(d):
                    ct.move(d)
                    return
        start = (pos.x, pos.y)
        end = (goal.x, goal.y)
        if start == end:
            return
        prev = {start: None}
        q = deque([start])
        hit = None
        while q:
            cur = q.popleft()
            if cur == end:
                hit = cur
                break
            x, y = cur
            for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0)):
                n = (x + dx, y + dy)
                if not (0 <= n[0] < self.w and 0 <= n[1] < self.h):
                    continue
                if n in prev or n in self.walls:
                    continue
                prev[n] = cur
                q.append(n)
        if hit is None:                     # unreachable: drift toward it
            for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0)):
                n = Position(pos.x + dx, pos.y + dy)
                if (0 <= n.x < self.w and 0 <= n.y < self.h
                        and manhattan(n, goal) < manhattan(pos, goal)
                        and ct.can_move(DELTA[(dx, dy)])):
                    ct.move(DELTA[(dx, dy)])
                    return
            return
        node = hit
        while prev[node] is not None and prev[node] != start:
            node = prev[node]
        d = DELTA.get((node[0] - start[0], node[1] - start[1]))
        if d is not None and ct.can_move(d):
            ct.move(d)


def manhattan(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)
