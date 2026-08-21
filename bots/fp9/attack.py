"""fp1 attack bot - a strict PRIORITY QUEUE, exactly as specified.

The spec is an ORDER, not a scoring problem: try each step in turn, the first one
that ACTUALLY ACTS wins, a step that cannot act falls through to the next.

  1. barrier the tiles their economy needs back   -> atk_deny
  2. break their core-adjacent trunk / harvesters  -> atk_break_trunk
  3. seat gunners on their core                    -> atk_siege
  4. walk to their core                            -> atk_approach

Every method here is `atk_`-prefixed ON PURPOSE. Player is
`Player(EcoBot, AttackBot)`, so EcoBot wins every MRO tie: an earlier version of
this file called its helper `_walk_adjacent`, EcoBot has one too, and the
attacker silently ran ECO's version - which returns None, so every step read
"did not act" and the whole priority queue fell through to idle. MEASURED: 515
idle turns of 561 on midgard. Never share a method name with eco.py.

Distances: MANHATTAN for every sort, distance-SQUARED for every test.
No exception handlers anywhere - every call that can raise is guarded by a TYPE
or VISION check instead.
"""

from fcode import Controller, EntityType, Position
from mapPathfinding import CARDINALS
import eco

BAN_TURNS = 20        # a target whose HP rose is being healed: leave it alone
TI_WINDOW = 5         # "titanium seen on them in the past 5 turns"
GUN_TI = 70           # step 2: place a gunner to help kill a building above this
SIEGE_TI = 250        # step 3: place a core-siege gunner above this
ARRIVE_DSQ = 8        # step 4: walk to the enemy core while dsq > 8
OCC_WINDOW = 20       # unspecified: how long "their building is still on that
                      # tile" is believed once we can no longer see the tile


def _manh(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _we_cover(ct: Controller, myTeam, tile: Position) -> bool:
    """Is one of OUR turrets already shooting this tile? get_gunner_target() is
    self-only, so ask can_fire_from() about each turret we can see instead."""
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        bType = ct.get_entity_type(b)
        if bType not in (EntityType.GUNNER, EntityType.SENTINEL):
            continue
        # get_direction only raises on things WITHOUT a facing; turrets have one.
        if ct.can_fire_from(ct.get_position(b), ct.get_direction(b), bType, tile):
            return True
    return False


class AttackBot:
    """The single attacker. Mixed into Player, so all state is `self.*`."""

    # NOT initialised in main.py's Player.__init__ (both reported):
    #   atkConvHere  (x,y) -> the (x,y) an enemy conveyor there OUTPUTS to
    #   atkOccupied  (x,y) -> round an ENEMY building was last seen on that tile
    # Class-level defaults so the first read cannot raise; the per-unit dicts are
    # created in atk_observe().
    atkConvHere = None
    atkOccupied = None

    def run_attack(self, ct: Controller):
        myLoc = ct.get_position()
        myTeam = ct.get_team()
        self.atk_observe(ct, myTeam)
        for step in (self.atk_deny, self.atk_break_trunk,
                     self.atk_siege, self.atk_approach):
            if step(ct, myLoc, myTeam):
                return

    # ------------------------------------------------------------------ memory

    def atk_observe(self, ct: Controller, myTeam):
        """Per-unit memory: which ore held a harvester, which tiles held an enemy
        conveyor and where it pointed, which of those carried titanium and when,
        which tiles are still occupied, and the HP trend that drives the ban list."""
        if self.atkConvHere is None:
            self.atkConvHere = {}
        if self.atkOccupied is None:
            self.atkOccupied = {}
        curRound = ct.get_current_round()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            bType = ct.get_entity_type(b)
            bPos = ct.get_position(b)
            key = (bPos.x, bPos.y)
            self.atkOccupied[key] = curRound
            if bType == EntityType.HARVESTER:
                self.oreHadHarv.add(key)
            elif bType in (EntityType.CONVEYOR, EntityType.SPLITTER):
                # Both calls raise on types without storage / without a facing,
                # so they are reached only for CONVEYOR and SPLITTER.
                out = bPos.add(ct.get_direction(b))
                self.atkConvHere[key] = (out.x, out.y)
                if ct.get_stored_resource(b) is not None:
                    self.convTiSeen[key] = curRound
            # BAN: rising HP means an enemy builder heals it +4 against our 2 dmg,
            # which we can never out-damage - unless a gunner of ours is on it.
            hp = ct.get_hp(b)
            prev = self.hpSeen.get(key)
            if prev is not None and hp > prev and not _we_cover(ct, myTeam, bPos):
                self.banned[key] = curRound + BAN_TURNS
            self.hpSeen[key] = hp

    def _atk_banned(self, pos: Position, curRound) -> bool:
        return self.banned.get((pos.x, pos.y), -1) > curRound

    def _atk_forget(self, key):
        """Unspecified: once a tile is barriered, drop it from memory, otherwise
        can_build_barrier stays False there and we would walk to it forever."""
        self.oreHadHarv.discard(key)
        self.atkConvHere.pop(key, None)
        self.convTiSeen.pop(key, None)
        self.atkOccupied.pop(key, None)

    def _atk_core_tiles(self):
        ec = self.mapPf.enemyCorePos
        if ec is None:
            return []
        return [Position(ec.x + dx, ec.y + dy) for dx in (0, 1) for dy in (0, 1)]

    def _atk_core_adjacent(self, key) -> bool:
        """Cardinally adjacent to the ENEMY core's 2x2 footprint - a conveyor has
        to be orthogonally adjacent to output into it."""
        for c in self._atk_core_tiles():
            if abs(key[0] - c.x) + abs(key[1] - c.y) == 1:
                return True
        return False

    def _atk_ti_fresh(self, key, curRound) -> bool:
        seen = self.convTiSeen.get(key)
        return seen is not None and curRound - seen <= TI_WINDOW

    def _atk_feeder_fresh(self, key, curRound) -> bool:
        """The OTHER of the two conveyors: a remembered conveyor tile that points
        INTO `key` and carried titanium recently."""
        pos = Position(key[0], key[1])
        for d in CARDINALS:
            n = pos.add(d)
            nKey = (n.x, n.y)
            if self.atkConvHere.get(nKey) == key and self._atk_ti_fresh(nKey, curRound):
                return True
        return False

    # ------------------------------------------------------------- 1. denial

    def atk_deny(self, ct: Controller, myLoc, myTeam) -> bool:
        """Ore that previously held an enemy harvester, plus core-adjacent tiles
        that previously held a conveyor where that conveyor OR its feeder carried
        titanium within 5 turns. Walk until dsq 1, then barrier."""
        curRound = ct.get_current_round()
        cands = list(self.oreHadHarv)
        for key in self.atkConvHere:
            if not self._atk_core_adjacent(key):
                continue
            if self._atk_ti_fresh(key, curRound) or self._atk_feeder_fresh(key, curRound):
                cands.append(key)
        if not cands:
            return False
        cands.sort(key=lambda k: abs(k[0] - myLoc.x) + abs(k[1] - myLoc.y))
        for key in cands:
            tile = Position(key[0], key[1])
            # "PREVIOUSLY held": a tile still holding a building cannot take a
            # barrier at all. Ours means the denial is already done, so forget it;
            # theirs has to die first, which is step 2's job - so fall through
            # rather than walk to it forever (MEASURED: 337 of 382 turns spent
            # ping-ponging between harvester-occupied ore before this guard).
            # The occupancy memory is what makes the skip stable: judging it by
            # vision alone flipped the choice every single turn as the walk
            # carried the tile in and out of range (MEASURED: 408 of 414 step-1
            # turns oscillating between two tiles, 1 barrier placed in a game).
            # is_in_vision first: get_tile_building_id RAISES outside vision.
            if ct.is_in_vision(tile):
                bId = ct.get_tile_building_id(tile)
                if bId is not None:
                    if ct.get_team(bId) == myTeam:
                        self._atk_forget(key)
                    continue
            elif curRound - self.atkOccupied.get(key, -OCC_WINDOW - 1) < OCC_WINDOW:
                continue
            if myLoc.distance_squared(tile) == 1:
                if ct.can_build_barrier(tile):
                    ct.build_barrier(tile)
                    self._atk_forget(key)
                    return True
                continue
            if self._atk_walk_adjacent(ct, myLoc, tile):
                return True
        return False

    # --------------------------------------------------------- 2. their trunk

    def atk_break_trunk(self, ct: Controller, myLoc, myTeam) -> bool:
        """Conveyors adjacent to their core that another enemy conveyor points
        into (their trunk terminal - one single-file trunk carries everything), or
        nearby enemy harvesters."""
        curRound = ct.get_current_round()
        targets = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            bType = ct.get_entity_type(b)
            bPos = ct.get_position(b)
            if self._atk_banned(bPos, curRound):
                continue
            if bType == EntityType.HARVESTER:
                targets.append(bPos)
            elif bType == EntityType.CONVEYOR:
                if self._atk_core_adjacent((bPos.x, bPos.y)) \
                        and self._atk_has_feeder(ct, bPos, myTeam):
                    targets.append(bPos)
        if not targets:
            return False
        targets.sort(key=lambda p: _manh(p, myLoc))
        for tile in targets:
            d = myLoc.distance_squared(tile)
            if d > 1:
                # A NEIGHBOUR of the target, never the target: standing on it
                # makes it permanently unbuildable and unattackable from here.
                if self._atk_walk_adjacent(ct, myLoc, tile):
                    return True
                continue
            if d < 1:
                if self._atk_move_away(ct, myLoc, tile):
                    return True
                continue
            if ct.get_global_resources() > GUN_TI and not _we_cover(ct, myTeam, tile):
                # allowRotCov unspecified here (only step 3 demands turret
                # safety), so allow a seat a turret could merely rotate onto.
                seat = self.find_gun_seat(ct, tile, myLoc, myTeam, True)
                if seat is not None and myLoc.distance_squared(seat[0]) == 1 \
                        and ct.can_build_gunner(seat[0], seat[1]):
                    ct.build_gunner(seat[0], seat[1])
                    return True
            if ct.can_fire(tile):
                ct.fire(tile)
                return True
        return False

    def _atk_has_feeder(self, ct: Controller, pos: Position, myTeam) -> bool:
        """Another enemy conveyor pointing INTO pos. A conveyor outputs to the
        side it FACES, so a feeder is a neighbour whose facing lands on pos."""
        for d in CARDINALS:
            n = pos.add(d)
            if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                continue
            if not ct.is_in_vision(n):
                continue
            nId = ct.get_tile_building_id(n)
            if nId is None or ct.get_team(nId) == myTeam:
                continue
            if ct.get_entity_type(nId) not in (EntityType.CONVEYOR, EntityType.SPLITTER):
                continue
            if n.add(ct.get_direction(nId)) == pos:
                return True
        return False

    # ---------------------------------------------------------- 3. core siege

    def atk_siege(self, ct: Controller, myLoc, myTeam) -> bool:
        """Gunner seats on their core that no enemy turret can hit, even by
        rotating (allowRotCov=False), ranked by real PATH weight."""
        if ct.get_global_resources() <= SIEGE_TI:
            return False
        seats, seen = [], set()
        for corner in self._atk_core_tiles():
            seat = self.find_gun_seat(ct, corner, myLoc, myTeam, False)
            if seat is None:
                continue
            key = (seat[0].x, seat[0].y)
            if key in seen:
                continue
            seen.add(key)
            seats.append(seat)
        if not seats:
            return False
        seats.sort(key=lambda s: self._atk_path_cost(ct, s[0]))
        spot, facing = seats[0]
        if myLoc.distance_squared(spot) == 1:
            if ct.can_build_gunner(spot, facing):
                ct.build_gunner(spot, facing)
                return True
            return False
        return self._atk_walk_adjacent(ct, myLoc, spot)

    def _atk_path_cost(self, ct: Controller, target: Position) -> int:
        cost = self.mapPf.fillInDistTable(ct, target)
        self.mapPf.prevTarget = None   # MANDATORY: moveTo caches on prevTarget
        return cost

    # ------------------------------------------------------------ 4. approach

    def atk_approach(self, ct: Controller, myLoc, myTeam) -> bool:
        target = self.mapPf.enemyCorePos
        if target is None:
            return False
        if myLoc.distance_squared(target) <= ARRIVE_DSQ:
            return False
        return self._atk_walk_to(ct, target)

    # -------------------------------------------------------------- movement

    def _atk_walk_to(self, ct: Controller, target: Position) -> bool:
        before = eco._snapshot(ct)
        self.mapPf.moveTo(ct, target)
        return eco._acted(ct, before)

    def _atk_walk_adjacent(self, ct: Controller, myLoc, tile: Position) -> bool:
        """Aim at the nearest passable cardinal NEIGHBOUR of the target: every
        builder action needs dsq == 1 to the target."""
        cands = []
        for d in CARDINALS:
            n = tile.add(d)
            if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                continue
            if self.mapPf.fullMap is not None and self.mapPf.fullMap[n.x][n.y] in (2, 3):
                continue
            cands.append(n)
        if not cands:
            return False
        cands.sort(key=lambda p: myLoc.distance_squared(p))
        return self._atk_walk_to(ct, cands[0])

    def _atk_move_away(self, ct: Controller, myLoc, tile: Position) -> bool:
        """dsq < 1 means we are standing ON it. Unspecified how to retreat, so:
        the cardinal step that puts the most distance between us."""
        best, bestD = None, None
        for d in CARDINALS:
            n = myLoc.add(d)
            if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                continue
            if not ct.can_move(d):
                continue
            dd = n.distance_squared(tile)
            if bestD is None or dd > bestD:
                best, bestD = d, dd
        if best is None:
            return False
        ct.move(best)
        return True
