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
from mapPathfinding import CARDINALS, DIRECTIONS
import eco

BAN_TURNS = 20        # a target whose HP rose is being healed: leave it alone
SENT_TI = 90          # sentinel siege gate once the gunner path is dead
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



def _gun_seat_dead(bot, ct, spot) -> bool:
    """Refuse a gunner seat we have already fed twice, and keep a loose global
    backstop. MEASURED (v197 vs I Stone, game 2, a 1000-turn loss on titanium):
    from turn 300 to the end we rebuilt a gunner every four turns and built
    NOTHING else - 170 of them, no conveyor, no harvester, no builder. The
    siege and counter-battery seat searches are deterministic, so when an
    opponent kills a gunner for free we re-pick the same doomed tile forever
    while they farm us to death. Every v197 loss was a 1000-turn titanium
    race; every win was a core kill. This is the spear's grave memory: a
    seat gets one retry, then it is dead to us. Total count is NOT capped
    tightly on purpose - a game we won built 54 gunners, so the thing to
    stop is the repetition, not the volume."""
    key = (spot.x, spot.y)
    seats = getattr(bot, 'gunSeats', None)
    if seats is None:
        seats = bot.gunSeats = {}
    if seats.get(key, 0) >= 2:
        return True
    return getattr(bot, 'gunsBuilt', 0) >= 12 + ct.get_current_round() // 60


def _gun_seat_used(bot, spot) -> None:
    key = (spot.x, spot.y)
    seats = getattr(bot, 'gunSeats', None)
    if seats is None:
        seats = bot.gunSeats = {}
    seats[key] = seats.get(key, 0) + 1
    bot.gunsBuilt = getattr(bot, 'gunsBuilt', 0) + 1


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
                     self.atk_siege, self.atk_sent_siege,
                     self.atk_seal, self.atk_approach, self.atk_breach):
            if step(ct, myLoc, myTeam):
                return
        # FALL BACK TO THE ECONOMY. run_eco ends with a guaranteed move when
        # every step declines; this ladder had NOTHING, so an attacker whose
        # seven steps all say no simply stood still - forever.
        # MEASURED in the Pantheon 5-0 (411fce84 g2, 275 turns): builder 4 made
        # 24 moves and sat motionless for 231 CONSECUTIVE turns, builder 6 for
        # 186. Pantheon's worst builder idled 75. The role split is
        # `myNum == 1 or myNum % 5 == 0`, so a four or five builder crew fields
        # TWO attackers - which is exactly the two dead bots, about 40% of our
        # workforce, and what ic3d watched standing around in the visualiser.
        # An attacker with nothing to attack should farm, not spectate.
        self.run_eco(ct)

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
        seats = [s for s in seats if not _gun_seat_dead(self, ct, s[0])]
        if not seats:
            return False
        seats.sort(key=lambda s: self._atk_path_cost(ct, s[0]))
        spot, facing = seats[0]
        if myLoc.distance_squared(spot) == 1:
            if ct.can_build_gunner(spot, facing):
                ct.build_gunner(spot, facing)
                _gun_seat_used(self, spot)
                return True
            return False
        return self._atk_walk_adjacent(ct, myLoc, spot)

    def _atk_path_cost(self, ct: Controller, target: Position) -> int:
        cost = self.mapPf.fillInDistTable(ct, target)
        self.mapPf.prevTarget = None   # MANDATORY: moveTo caches on prevTarget
        return cost

    # ------------------------------------------------- 3.5 sentinel siege

    def _atk_enemy_covers(self, ct: Controller, myTeam, tile) -> bool:
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            if ct.can_fire_from(ct.get_position(b), ct.get_direction(b),
                                bType, tile):
                return True
        return False

    def atk_sent_siege(self, ct: Controller, myLoc, myTeam) -> bool:
        """Sentinel seats on straight rays to the enemy core. Runs when the
        gunner siege declined - which is exactly the walled/heal-tanked case:
        sentinel fire is INDIRECT (no barrier blocks it) and one seat's
        18-per-2-turns out-paces a tender pair's heal where a lone gunner's
        7 cannot. Reach: 5 cardinal / 4 diagonal from the target tile.

        CONDITIONAL: sentinels are pricier dps than gunners in the open
        field (ambient sentinel-first was a measured in-family tax, double
        REJECT) - they deploy only when the gunner path is proven dead:
        the heal-stall flag, or rich with no gunner seat (walled core)."""
        if ct.read_store(10) == 1:
            self.gunsDead = True    # persisted: a dead attacker's verdict
                                    # must outlive it (Jython g1: zero
                                    # sentinels after the finder died)
        if not getattr(self, 'gunsDead', False):
            rich = ct.get_global_resources() > SIEGE_TI + 50
            if not rich:
                return False
            probe = None
            for corner in self._atk_core_tiles():
                probe = self.find_gun_seat(ct, corner, myLoc, myTeam, False)
                if probe is not None:
                    break
            if probe is not None:
                return False    # gunner seats exist - let them work
            self.gunsDead = True
            ct.write_store(10, 1)
        r_ = ct.get_current_round()
        if r_ < 30:
            return False        # the seed money farms first (g3: an early
                                # siege bankrupted us into 0 titanium)
        floor_ = SENT_TI + (90 if r_ < 120 else 0)
        if ct.get_global_resources() <= floor_:
            return False
        seats = []
        for corner in self._atk_core_tiles():
            for d in DIRECTIONS:
                dd = d.delta()
                reach = 5 if 0 in (dd[0], dd[1]) else 4
                for k in range(2, reach + 1):
                    x = corner.x + dd[0] * k
                    y = corner.y + dd[1] * k
                    if not (0 <= x < self.mapW and 0 <= y < self.mapH):
                        break
                    seat = Position(x, y)
                    if ct.is_in_vision(seat):
                        if ct.get_tile_building_id(seat) is not None:
                            continue
                        if ct.get_tile_builder_bot_id(seat) is not None:
                            continue
                    if self._atk_enemy_covers(ct, myTeam, seat):
                        continue
                    # face BACK along the ray toward the core tile
                    back = None
                    for d2 in DIRECTIONS:
                        d2d = d2.delta()
                        if (d2d[0], d2d[1]) == (-dd[0], -dd[1]):
                            back = d2
                            break
                    if back is not None:
                        seats.append((seat, back))
                    break       # first free tile per ray is the seat
        if not seats:
            return False
        seats.sort(key=lambda s: _manh(s[0], myLoc))
        spot, facing = seats[0]
        if myLoc.distance_squared(spot) == 1:
            if ct.can_build_sentinel(spot, facing):
                ct.build_sentinel(spot, facing)
                return True
            return False
        return self._atk_walk_adjacent(ct, myLoc, spot)

    # ---------------------------------------------------- 3.7 heal-seat seal

    def atk_seal(self, ct: Controller, myLoc, myTeam) -> bool:
        """Bean counters' masterstroke, ported: barrier the enemy core's
        orthogonal perimeter (dB1) so tender builders have NO tile to
        stand on and heal from - the heal race is won by REMOVING the
        seats, not out-DPSing them. Safe for us because our core damage
        is sentinel-based and sentinel fire is indirect: our own barriers
        never block it. Runs only once a sentinel of ours stands near
        their core (before that, the money belongs to the siege)."""
        ec = self.mapPf.enemyCorePos
        if ec is None:
            return False
        have_sent = False
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == myTeam
                    and ct.get_entity_type(b) == EntityType.SENTINEL
                    and _manh(ct.get_position(b), ec) <= 7):
                have_sent = True
                break
        if not have_sent:
            return False
        hurt_r = ct.read_store(9)
        if hurt_r and ct.get_current_round() - hurt_r < 30:
            return False        # home core under fire - no away barriers
        if ct.get_global_resources() < ct.get_barrier_cost() + 40:
            return False
        ring = []
        for a2 in (0, 1):
            ring.append(Position(ec.x + a2, ec.y - 1))
            ring.append(Position(ec.x + a2, ec.y + 2))
            ring.append(Position(ec.x - 1, ec.y + a2))
            ring.append(Position(ec.x + 2, ec.y + a2))
        ring = [t for t in ring
                if 0 <= t.x < self.mapW and 0 <= t.y < self.mapH]
        ring.sort(key=lambda t: _manh(t, myLoc))
        for t in ring:
            if ct.is_in_vision(t):
                if ct.get_tile_building_id(t) is not None:
                    continue
                if ct.get_tile_builder_bot_id(t) is not None:
                    continue
            if myLoc.distance_squared(t) == 1:
                if ct.can_build_barrier(t):
                    ct.build_barrier(t)
                    return True
                continue
            return self._atk_walk_adjacent(ct, myLoc, t)
        return False

    # ------------------------------------------------------------ 4. approach

    def atk_approach(self, ct: Controller, myLoc, myTeam) -> bool:
        target = self.mapPf.enemyCorePos
        if target is None:
            return False
        if myLoc.distance_squared(target) <= ARRIVE_DSQ:
            return False
        return self._atk_walk_to(ct, target)

    # ------------------------------------------------------------ 6. breach

    def atk_breach(self, ct: Controller, myLoc, myTeam) -> bool:
        """Terminal step: everything declined and we stand at a walled core.
        Chew the nearest cage barrier (2 dmg, 30 hp - slow, but infinitely
        better than the measured alternative: standing frozen next to a wall
        for 500 turns)."""
        ec = self.mapPf.enemyCorePos
        if ec is None or myLoc.distance_squared(ec) > 32:
            return False
        best, bestD = None, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            if ct.get_entity_type(b) != EntityType.BARRIER:
                continue
            bPos = ct.get_position(b)
            near_core = False
            for c in self._atk_core_tiles():
                if bPos.distance_squared(c) <= 8:
                    near_core = True
                    break
            if not near_core:
                continue
            d = _manh(bPos, myLoc)
            if bestD is None or d < bestD:
                bestD, best = d, bPos
        if best is None:
            return False
        if myLoc.distance_squared(best) == 1:
            if ct.can_fire(best):
                ct.fire(best)
                return True
            return False
        return self._atk_walk_adjacent(ct, myLoc, best)

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
