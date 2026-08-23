"""fp1 eco builder - the nine steps of botStrategy.md section 3.

Priority queue: the steps are attempted in this exact order and the FIRST one
that actually performs an action ends the turn; a step that cannot act falls
through to the next. Scores are never compared across steps. If every step
declines, the bot takes any legal cardinal move so no turn is wasted entirely.

No error handling anywhere. Every call that can raise is guarded by a TYPE check
(get_direction) or a VISION check (get_tile_building_id, get_tile_builder_bot_id)
instead, per botStrategy.md section 0.
"""

from fcode import Controller, EntityType, Environment, Position
from mapPathfinding import CARDINALS, DIRECTIONS
import convroute
from convroute import route_conveyor

# convroute.py is carried verbatim and reads these three names out of its OWN
# module globals without ever defining them (a NameError the moment any team
# conveyor exists). It must not be edited, so inject them from here. Values are
# the routing costs botStrategy.md section 3 step 5 specifies.
convroute.CONV_GUNNER_COST = 5      # route through our own gunner
convroute.CONV_JOIN_FREE = 4        # join an existing free conveyor
convroute.CONV_JOIN_LOADED = 28     # join a LOADED one: its trunk slot is taken

SLOT_THREAT = 7     # core position + up to 2 enemy turrets (section 1.1)
RING_TARGET = 4     # conveyors that should point into the core (step 1)
RING_TURNS = 5      # turns one builder may spend on step 1 before giving up
F_FLOOR = 0.05      # falloff floor (step 8)
LEASH_MUL = 4.0
WARD_R2 = 64
DEFEND_TI = 100      # counter-gunner state needs this much
HARV_TI = 45         # a NEW harvester needs this much. Was 100: a
                     # POVERTY TRAP - while a siege or a defence keeps the
                     # bank under 100 no harvester is ever started. Juusto
                     # beat us with 9-22 harvesters against our 2-9 in
                     # every scrim loss; a harvester costs ~20 and repays
                     # itself, so 45 keeps a chain float and still farms.
HOME_TTL = 20      # rounds a damage report stays fresh
HOME_R2 = 25       # already-home radius, where step_heal takes over     # steeper leash once this bot finished a super project


def _snapshot(ct: Controller):
    """State that changes if and only if this unit actually did something.
    Acting and moving are mutually exclusive per round and both set a cooldown,
    so this catches a build, a heal, a destroy or a move. attack.py imports it."""
    return (ct.get_position(), ct.get_action_cooldown(), ct.can_act())


def _acted(ct: Controller, before) -> bool:
    return _snapshot(ct) != before


def _fall(dsq, norm):
    return max(F_FLOOR, 1.0 - float(dsq) / norm)


def _man(a: Position, b: Position) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


def _we_cover(ct: Controller, myTeam, tile: Position) -> bool:
    """Is one of OUR turrets already attacking this tile? get_gunner_target() is
    self-only, so a builder cannot ask a gunner what it is shooting; can_fire_from
    is the blocker-aware answer for a turret we can see."""
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) != myTeam:
            continue
        bType = ct.get_entity_type(b)
        if bType not in (EntityType.GUNNER, EntityType.SENTINEL):
            continue
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


class EcoBot:
    """Mixed into Player, so all per-unit state is self.* and is created in one
    place: Player.__init__ in main.py."""

    # Class-level default so the field is safe before main.py initialises it.
    # Assigning to self.ringPlaced creates a normal per-instance attribute.
    ringPlaced = False      # this builder has placed its own ring conveyor

    def run_eco(self, ct: Controller):
        myLoc = ct.get_position()
        myTeam = ct.get_team()

        # STEP 2: rebuild allyPos from vision - the voronoi input for step 4. It
        # is bookkeeping and never ends the turn, so it runs ahead of the queue
        # rather than sitting in it.
        myId = ct.get_id()
        self.allyPos = [ct.get_position(u) for u in ct.get_nearby_units()
                        if u != myId and ct.get_team(u) == myTeam
                        and ct.get_entity_type(u) == EntityType.BUILDER_BOT]

        for step in (self.step_core_siege,
                     self.step_relay_alarm,
                     self.step_ring,
                     self.step_counter_turret,
                     self.step_deny_seats,
                     self.step_heal,
                     self.step_home,
                     self.step_repair,
                     self.step_project,
                     self.step_adopt,
                     self.step_my_ore,
                     self.step_assign_ore,
                     self.step_guard,
                     self.step_regroup):
            if step(ct, myLoc, myTeam):
                self.lastBand = step.__name__
                return

        self.lastBand = 'idle'
        for d in CARDINALS:
            if ct.can_move(d):
                ct.move(d)
                return

    def step_home(self, ct: Controller, myLoc, myTeam) -> bool:
        """COME HOME WHILE THE CORE IS UNDER ATTACK.

        step_heal only fires on buildings this builder can SEE (r^2=20), so a
        builder out at distant ore never learns the core is being destroyed. The
        core publishes the round it last lost hp on slot 9; while that is fresh,
        everyone within reach walks back. Once close enough, step_heal takes over
        and does the actual healing - healing is 1 Ti for +4 HP, the most
        titanium-efficient action in the game.

        Deliberately does NOT fire when already near the core, so it cannot
        preempt the heal itself."""
        hurt = ct.read_store(9)
        if hurt <= 0:
            return False
        if ct.get_current_round() - hurt > HOME_TTL:
            return False            # the attack is over; go back to work
        core = self.mapPf.teamCore
        if core is None:
            return False
        if myLoc.distance_squared(core) <= HOME_R2:
            return False            # close enough for step_heal to reach it
        before = _snapshot(ct)
        self.mapPf.moveTo(ct, core)
        return _acted(ct, before)

    def step_adopt(self, ct: Controller, myLoc, myTeam) -> bool:
        """ADOPT ORPHANED INFRASTRUCTURE - ownership is deliberately NOT checked.

        Two orphan signatures, both read from vision:
          * a friendly CONVEYOR whose facing points into an EMPTY tile. That is a
            dangling chain end: everything upstream of it delivers nothing. It
            covers a chain abandoned when its builder died AND a chain CUT by an
            attack, which is the case the base bot never repairs.
          * a friendly HARVESTER with no adjacent friendly conveyor at all - an
            unconnected harvester banks nothing and mines nothing.

        A conveyor pointing into a CORE tile is not dangling (the core is a
        building, so the emptiness test excludes it), and neither are the ring
        terminals from step 1."""
        if self.projectEnd is not None:
            return False            # finish my own chain first
        core = self.mapPf.teamCore
        if core is None:
            return False
        best, bestEnd = None, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            bType = ct.get_entity_type(b)
            pos = ct.get_position(b)
            cand = None
            if bType == EntityType.CONVEYOR:
                out = pos.add(ct.get_direction(b))
                if not (0 <= out.x < self.mapW and 0 <= out.y < self.mapH):
                    continue
                if not ct.is_in_vision(out):
                    continue        # get_tile_building_id raises outside vision
                if ct.get_tile_building_id(out) is not None:
                    continue        # feeds something: not dangling
                if self.mapPf.fullMap[out.x][out.y] in (2, 3):
                    continue        # points into a wall: nothing to build
                cand = out
            elif bType == EntityType.HARVESTER:
                linked = False
                for d in CARDINALS:
                    n = pos.add(d)
                    if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                        continue
                    if not ct.is_in_vision(n):
                        continue
                    nId = ct.get_tile_building_id(n)
                    if (nId is not None and ct.get_team(nId) == myTeam
                            and ct.get_entity_type(nId) in (EntityType.CONVEYOR,
                                                            EntityType.SPLITTER)):
                        linked = True
                        break
                if linked:
                    continue
                cand = self._chain_start(pos)
                if cand is None:
                    continue
            else:
                continue
            # VORONOI, same rule step_heal uses: only help with a chain if no
            # ally I can see is closer to it. Without this every builder adopts
            # the same dangling end and they queue up on one chain - and, before
            # the convroute fix, destroyed each other's segments.
            if not self._win_heal(myLoc, cand):
                continue
            d = myLoc.distance_squared(cand)
            if best is None or d < best:
                best, bestEnd = d, cand
        if bestEnd is None:
            return False
        self.projectEnd = bestEnd
        self.projectSuper = False   # adopted work is not my finished super chain
        return self.step_project(ct, myLoc, myTeam)

    def step_repair(self, ct: Controller, myLoc, myTeam) -> bool:
        """Rebuild MY OWN infrastructure that has been destroyed.

        step_heal repairs a DAMAGED building; it can do nothing about a destroyed
        one, because a missing conveyor is not in get_nearby_buildings() at all. So
        remember every tile we put a conveyor on, and treat a remembered tile that
        is visibly EMPTY as a hole in our own chain. A hole anywhere upstream means
        everything above it delivers NOTHING, so this outranks starting new work.

        The harvester is handled separately: rebuilding it means re-claiming the
        ore, not laying a conveyor on it."""
        harv = self.myHarvester
        if harv is not None and ct.is_in_vision(harv) \
                and ct.get_tile_building_id(harv) is None \
                and self.mapPf.fullMap[harv.x][harv.y] == 1:
            # Our harvester is gone and the ore is bare again: retake it.
            self.myOre = harv
            self.myHarvester = None
            return self.step_my_ore(ct, myLoc, myTeam)
        if self.projectEnd is not None:
            return False
        # CONVEYOR GRAVES. MEASURED in the v198 loss to kladde (e230dcf0):
        # they start shooting our conveyors at t37 and t28 - one hundred and
        # twenty to two hundred and thirty rounds BEFORE they touch the core -
        # and deal 824 damage to our supply lines in game 1 alone, about
        # forty conveyors. Our only response is this repair step, so we walk
        # back and rebuild: tile (10,15) SEVEN times, (9,16) four times, 13
        # wasted builds feeding a shooter nobody looks for. Losing conveyors
        # is not a chore, it is the opening move of the kill, but nothing in
        # the bot treats it as an attack - hurtRound (slot 9) only watches the
        # CORE. A tile that has already eaten two of our conveyors is a tile
        # inside someone's firing line; stop paying rent on it and let the
        # router find another way. This SAVES builder-turns and titanium,
        # which is the constraint the failed siege response could not meet.
        counts = getattr(self, 'convN', None) or {}
        holes, graves = [], []
        for (x, y) in self.builtConv:
            t = Position(x, y)
            # THRESHOLD 5, not 3. A hole upstream means everything above it
            # delivers NOTHING, so abandoning a mid-chain tile without a
            # reroute kills the whole chain - at 3 this gates 67% vs jav1
            # where the live bot gets 73%. The pathological tile in the
            # kladde loss was rebuilt SEVEN times, so 5 still cuts the
            # hopeless ones while leaving ordinary repair alone.
            if counts.get((x, y), 0) >= 5:
                graves.append((x, y))
                continue
            if not ct.is_in_vision(t):
                continue        # get_tile_building_id raises outside vision
            if ct.get_tile_building_id(t) is not None:
                continue
            if self.mapPf.fullMap[t.x][t.y] in (2, 3):
                continue        # became a wall in our own map memory: not a hole
            holes.append(t)
        for g in graves:        # discard AFTER the loop: never mutate mid-iteration
            self.builtConv.discard(g)
        if not holes:
            return False
        holes.sort(key=lambda t: myLoc.distance_squared(t))
        self.projectEnd = holes[0]
        return self.step_project(ct, myLoc, myTeam)

    def _patrol_next(self, ct: Controller, myLoc):
        """Next waypoint on a real circuit over our own infrastructure.

        A patrol between the core and an ADJACENT harvester is a two-step shuffle
        that watches nothing. Instead cycle over the core plus every friendly
        harvester we can see, preferring the one we have visited least recently, and
        require the leg to be at least PATROL_MIN long so the circuit actually
        covers the corridor where conveyors get cut."""
        core = self.mapPf.teamCore
        if core is None:
            return None
        stops = [core]
        myTeam = ct.get_team()
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) == myTeam
                    and ct.get_entity_type(b) == EntityType.HARVESTER):
                stops.append(ct.get_position(b))
        if self.myHarvester is not None:
            stops.append(self.myHarvester)
        best, bestT = None, None
        for s in stops:
            if myLoc.distance_squared(s) <= 1:
                continue            # standing on it; go somewhere else
            seen = self.patrolSeen.get((s.x, s.y), -999)
            if best is None or seen < best:
                best, bestT = seen, s
        if bestT is None:
            return core
        self.patrolSeen[(bestT.x, bestT.y)] = ct.get_current_round()
        return bestT

    # ------------------------------------------------------------- 1. ring

    def step_ring(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 1: each builder contributes AT MOST ONE conveyor to the core ring,
        and gives up after RING_TURNS turns of effort."""
        if self.ringPlaced or self.ringTurns > RING_TURNS:
            return False
        coreTiles = self._core_tiles()
        if not coreTiles:
            return False
        coreKeys = set((t.x, t.y) for t in coreTiles)
        have, free = 0, []
        for c in coreTiles:
            for d in CARDINALS:
                n = c.add(d)
                if not (0 <= n.x < self.mapW and 0 <= n.y < self.mapH):
                    continue
                if (n.x, n.y) in coreKeys:
                    continue
                if not ct.is_in_vision(n):
                    continue        # get_tile_building_id raises outside vision
                bId = ct.get_tile_building_id(n)
                if bId is not None:
                    # Type first: get_direction raises on anything with no facing.
                    if (ct.get_entity_type(bId) == EntityType.CONVEYOR
                            and ct.get_team(bId) == myTeam
                            and n.add(ct.get_direction(bId)) == c):
                        have += 1
                    continue
                if ct.get_tile_env(n) == Environment.EMPTY and ct.is_tile_passable(n):
                    free.append((n, c))
        # The count is re-read live, so bot 2 sees bot 1's conveyor and picks a
        # different tile, and nobody acts once four exist.
        if have >= RING_TARGET or not free:
            return False
        free.sort(key=lambda f: myLoc.distance_squared(f[0]))
        spot, coreTile = free[0]
        before = _snapshot(ct)
        if myLoc.distance_squared(spot) == 1:
            # A terminal conveyor must FACE INTO a core tile; adjacency alone
            # delivers nothing.
            facing = spot.direction_to(coreTile)
            if ct.can_build_conveyor(spot, facing):
                ct.build_conveyor(spot, facing)
                if _acted(ct, before):
                    self.ringPlaced = True
                    self.ringTurns += 1
                    return True
            return False
        self._walk_adjacent(ct, myLoc, spot)
        acted = _acted(ct, before)
        if acted:
            self.ringTurns += 1
        return acted

    # --------------------------------------------------- 3. counter a turret

    def step_core_siege(self, ct: Controller, myLoc, myTeam) -> bool:
        """EMERGENCY: our core is being shot RIGHT NOW.

        Measured against not adgato's sentinel spear (match 0efa579a, five
        games): we dealt ZERO damage to their sentinels in four of them,
        and the only two games we won were the two where our core received
        400+ healing (the losses got 76-132). So the whole answer is two
        things done at once - kill the shooters, and pile heals on the core
        - which is exactly how Leviathan 5-0'd that same spear.

        Home builders only; the attacker is a separate role and stays
        committed (in both wins it killed their core while we held on)."""
        hurt = ct.read_store(9)         # round our core last LOST hp
        if hurt <= 0:
            return False
        if ct.get_current_round() - hurt > 15:
            return False                # quiet again: back to work
        core = self.mapPf.teamCore
        if core is None or _man(myLoc, core) > 12:
            return False
        # HARD GATE: only a core actually losing the race. Firing on any
        # scratch cost us the race entirely - fp14/fp15 WIN this matchup by
        # killing the spear's undefended core (t65/t112 on holmgang), and a
        # broad defensive reflex turned that into a t34 loss. Defence here
        # buys survival only when survival is genuinely in doubt.
        coreId = None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam \
                    and ct.get_entity_type(b) == EntityType.CORE:
                coreId = b
                break
        if coreId is None:
            return False
        if ct.get_hp(coreId) * 10 > ct.get_max_hp(coreId) * 6:
            return False                # above 60%: keep racing
        # THE TARGET IS THE ESCORT, NOT THE TURRET. Their builder heals each
        # sentinel +4/turn, so our 2-dmg chew on a tended sentinel is net
        # ZERO while costing us a +4 healer at the core - measured: chewing
        # turrets turned four spot-check wins into losses. The escort itself
        # cannot be healed (no self-heal in this engine): 40hp, and killing
        # it ends the healing AND the rebuilds at once.
        escort, ed = None, None
        for u in ct.get_nearby_units():
            if ct.get_team(u) == myTeam:
                continue
            p = ct.get_position(u)
            if _man(p, core) > 8:
                continue
            d = myLoc.distance_squared(p)
            if ed is None or d < ed:
                ed, escort = d, p
        before = _snapshot(ct)
        # 1. chew the escort ONLY when already standing next to it - free,
        #    and their sentinels are the one thing it cannot heal through
        if escort is not None and myLoc.distance_squared(escort) == 1 \
                and ct.can_fire(escort):
            ct.fire(escort)
            return True
        # 2. HEAL: the +400-hp signal that separated our two wins from the
        #    three losses. A guaranteed +4 beats chewing a tended sentinel,
        #    which their escort cancels exactly.
        for t in self._core_tiles():
            if myLoc.distance_squared(t) == 1 and ct.can_heal(t):
                ct.heal(t)
                return True
        # 3. join the heal battery. No walking at the siege: builders sent
        #    into sentinel lines just die and stop healing.
        self.mapPf.moveTo(ct, core)
        return _acted(ct, before)

    def step_relay_alarm(self, ct: Controller, myLoc, myTeam) -> bool:
        """Jython tell: 5 launchers at t1 relay a kill-builder to our core
        by t6-7. On >=3 enemy launchers before t25, the nearest builder
        posts ONE gunner two tiles out on the enemy-facing side and shoots
        the arrival before its first barrier stands."""
        if ct.get_current_round() > 25 or getattr(self, 'relayDone', False):
            return False
        lau = 0
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam \
                    and ct.get_entity_type(b) == EntityType.LAUNCHER:
                lau += 1
        if lau < 3:
            return False
        core = self.mapPf.teamCore
        if core is None:
            return False
        if ct.get_global_resources() < ct.get_gunner_cost() + 10:
            return False
        foe = self.mapPf.enemyCorePos
        for d in CARDINALS:
            sp = Position(core.x + d.delta()[0] * 2,
                          core.y + d.delta()[1] * 2)
            if not (0 <= sp.x < self.mapW and 0 <= sp.y < self.mapH):
                continue
            if myLoc.distance_squared(sp) == 1:
                fd = d
                if foe is not None:
                    dx = (foe.x > sp.x) - (foe.x < sp.x)
                    dy = (foe.y > sp.y) - (foe.y < sp.y)
                    for dd8 in DIRECTIONS:
                        if dd8.delta() == (dx, dy):
                            fd = dd8
                            break
                if ct.can_build_gunner(sp, fd):
                    ct.build_gunner(sp, fd)
                    self.relayDone = True
                    return True
            else:
                before = _snapshot(ct)
                self.mapPf.moveTo(ct, sp)
                if _acted(ct, before):
                    return True
        return False

    def step_deny_seats(self, ct: Controller, myLoc, myTeam) -> bool:
        """SEAT DENIAL. An enemy sentinel has to stand on a straight ray to
        our core, 2-5 tiles out, to hit it - and a tile that already holds a
        building cannot be built on. A conveyor costs 3 titanium and is
        PASSABLE, so paving those tiles denies the whole spear meta a place
        to stand without walling ourselves in. Cheapest defence in the game
        if it holds."""
        core = self.mapPf.teamCore
        if core is None:
            return False
        if ct.get_global_resources() < 120:
            return False        # never at the cost of the real economy
        if ct.get_current_round() > 260:
            return False
        # ONLY AGAINST AN ACTUAL SPEAR. Paving by default is 90% vs a spear
        # but 12% in-family - the titanium and the builder-turns have to
        # come from somewhere. The tell is an enemy BUILDER loitering near
        # our core with no economy of its own, or a sentinel already up.
        # THE TELL MUST BE A SENTINEL, NOT A VISITOR. Triggering on any
        # enemy builder within 9 tiles fired on turn 3 of nearly every game
        # - measured in the Focalground loss: 24 of our 31 conveyors went
        # up within 4 tiles of our core, we finished with THREE harvesters
        # and died at t48. Pave only when a spear is actually assembling,
        # and never more than six tiles' worth.
        if getattr(self, 'paved', 0) >= 6:
            return False
        threat = False
        for b in ct.get_nearby_buildings():
            if (ct.get_team(b) != myTeam
                    and ct.get_entity_type(b) == EntityType.SENTINEL
                    and _man(ct.get_position(b), core) <= 10):
                threat = True
                break
        if not threat and ct.get_current_round() >= 40:
            for u in ct.get_nearby_units():
                if ct.get_team(u) != myTeam                         and _man(ct.get_position(u), core) <= 5:
                    threat = True
                    break
        if not threat:
            return False
        best, bd = None, None
        for cx, cy in ((core.x, core.y), (core.x + 1, core.y),
                       (core.x, core.y + 1), (core.x + 1, core.y + 1)):
            for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1),
                           (0, 1), (-1, 1), (-1, 0), (-1, -1)):
                reach = 4 if (dx == 0 or dy == 0) else 3
                for k in range(2, reach + 1):
                    t = Position(cx + dx * k, cy + dy * k)
                    if not (0 <= t.x < self.mapW and 0 <= t.y < self.mapH):
                        break
                    if not ct.is_in_vision(t):
                        continue
                    if ct.get_tile_env(t) != Environment.EMPTY:
                        continue
                    if ct.get_tile_building_id(t) is not None:
                        continue
                    if ct.get_tile_builder_bot_id(t) is not None:
                        continue
                    d = myLoc.distance_squared(t)
                    if bd is None or d < bd:
                        bd, best = d, t
        if best is None:
            return False
        before = _snapshot(ct)
        if myLoc.distance_squared(best) == 1:
            face = CARDINALS[0]
            for d in CARDINALS:
                if best.add(d).distance_squared(core) <                         best.distance_squared(core):
                    face = d
                    break
            if ct.can_build_conveyor(best, face):
                ct.build_conveyor(best, face)
                self.paved = getattr(self, 'paved', 0) + 1
                return True
            return False
        self._walk_adjacent(ct, myLoc, best)
        return _acted(ct, before)

    def step_counter_turret(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 3: every enemy GUNNER/SENTINEL in vision plus any decoded from
        slot 7, so a bot that cannot see the turret still responds. Any turret
        qualifies wherever it is on the map."""
        # A gunner we cannot buy is not a defence; walking to its seat is
        # strictly worse than doing economy work, and this state outranks
        # the economy.
        if ct.get_global_resources() < DEFEND_TI:
            return False
        threats = self._decode_threats(ct)
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            if ct.get_entity_type(b) not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            threats.append(ct.get_position(b))
        live = [t for t in threats if not _we_cover(ct, myTeam, t)]
        if not live:
            return False
        core = self.mapPf.teamCore
        if core is not None:
            live.sort(key=lambda p: p.distance_squared(core))
        # allowRotCov=True: only the turret's CURRENT line of fire is rejected. A
        # tile a turret could reach by rotating is acceptable, because this seat's
        # whole purpose is shooting a turret.
        seat = self.find_gun_seat(ct, live[0], myLoc, myTeam, True)
        if seat is None:
            # NO GUNNER SEAT MEANS THE TARGET IS WALLED, NOT SAFE. Verified in
            # the 2.3.9 stubs: for gunners "only empty tiles fail to block the
            # firing line", while sentinel fire carries no such rule (we
            # measured 882 damage through a fully-blocked ray). So a barrier
            # wall is a ONE-WAY FILTER - it stops our gunners while their
            # sentinels shoot straight over it. Measured in the v198 loss to
            # kladde (e230dcf0): they wall from t33, plant sentinels behind it,
            # and hit the core for 18/turn while we answer with 4/turn of
            # healing and 3-11 useless gunners. Giving up here is why we heal
            # until we die. Answer a walled turret with the weapon that
            # ignores walls.
            return self._counter_sentinel(ct, live[0], myLoc, myTeam)
        spot, facing = seat
        if _gun_seat_dead(self, ct, spot):
            return False
        before = _snapshot(ct)
        if myLoc.distance_squared(spot) == 1:
            if ct.can_build_gunner(spot, facing):
                ct.build_gunner(spot, facing)
                _gun_seat_used(self, spot)
        else:
            self._walk_adjacent(ct, myLoc, spot)
        return _acted(ct, before)

    def _counter_sentinel(self, ct: Controller, target, myLoc, myTeam) -> bool:
        """Counter-battery with a SENTINEL, for a turret our gunners cannot
        reach. Only fires when find_gun_seat has already failed, so this never
        competes with the cheaper gunner answer - it exists for the walled
        case, which is precisely the case that kills us.

        Seats must be ORTHOGONALLY adjacent to build (2.3.0 rule); facing is
        still 8-way. The seat graves apply: a tile that has eaten two of our
        turrets is inside someone's line and does not get a third."""
        if ct.get_global_resources() < ct.get_sentinel_cost() + 10:
            return False
        pick = None
        for d in CARDINALS:
            spot = myLoc.add(d)
            if not (0 <= spot.x < self.mapW and 0 <= spot.y < self.mapH):
                continue
            if not ct.is_tile_empty(spot):
                continue
            for f in DIRECTIONS:
                try:
                    if ct.can_fire_from(spot, f, EntityType.SENTINEL, target):
                        pick = (spot, f)
                        break
                except Exception:
                    pass
            if pick is not None:
                break
        if pick is None:
            return False
        spot, facing = pick
        if _gun_seat_dead(self, ct, spot):
            return False
        before = _snapshot(ct)
        if ct.can_build_sentinel(spot, facing):
            ct.build_sentinel(spot, facing)
            _gun_seat_used(self, spot)
        return _acted(ct, before)

    def _decode_threats(self, ct: Controller):
        """Slot 7 per section 1.1: core position in the low 10 bits, then up to two
        enemy-turret offsets as 4-bit SIGNED dx,dy at bit 10 and bit 18. The core
        rewrites it every turn, so a dead turret simply stops being packed."""
        packed = ct.read_store(SLOT_THREAT)
        if packed <= 0:
            return []
        cx, cy = (packed >> 5) & 0x1F, packed & 0x1F
        out = []
        for i in (0, 1):
            field = (packed >> (10 + 8 * i)) & 0xFF
            if field == 0:
                continue        # 0 means no turret: (0,0) would be the core itself
            dx, dy = (field >> 4) & 0xF, field & 0xF
            if dx > 7:
                dx -= 16        # sign-extend 4-bit two's complement
            if dy > 7:
                dy -= 16
            x, y = cx + dx, cy + dy
            if 0 <= x < self.mapW and 0 <= y < self.mapH:
                out.append(Position(x, y))
        return out

    def _enemy_cover(self, ct: Controller, myTeam):
        """(tiles an enemy turret hits with its CURRENT facing, tiles a GUNNER
        could hit only after rotating), as SEPARATE sets. Summing them would make
        two gunners that each have to rotate look identical to one already aimed
        at you. Sentinel facing is permanent, so a sentinel is `direct` only."""
        direct, rot = set(), set()
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) == myTeam:
                continue
            bType = ct.get_entity_type(b)
            if bType not in (EntityType.GUNNER, EntityType.SENTINEL):
                continue
            bPos, bDir = ct.get_position(b), ct.get_direction(b)
            for t in ct.get_attackable_tiles_from(bPos, bDir, bType):
                direct.add((t.x, t.y))
            if bType == EntityType.GUNNER:
                for d in DIRECTIONS:
                    if d == bDir:
                        continue
                    for t in ct.get_attackable_tiles_from(bPos, d, EntityType.GUNNER):
                        rot.add((t.x, t.y))
        return direct, rot

    def find_gun_seat(self, ct: Controller, target: Position, myLoc, myTeam,
                      allowRotCov: bool):
        """Seat minimising dsq to me that a GUNNER could stand on and actually hit
        `target`: empty of buildings AND builder bots, and outside enemy turret
        coverage. allowRotCov permits a seat only a rotation could reach.
        Also called from attack.py."""
        direct, rot = self._enemy_cover(ct, myTeam)
        best, bestSeat = None, None
        for spot, facing in self.mapPf.gunnerSpots(target, self.mapW, self.mapH, True):
            key = (spot.x, spot.y)
            if key in direct or (not allowRotCov and key in rot):
                continue
            if not ct.is_in_vision(spot):
                continue        # the two get_tile_*_id calls below raise outside it
            if ct.get_tile_building_id(spot) is not None:
                continue
            if ct.get_tile_builder_bot_id(spot) is not None:
                continue        # a bot standing there makes it unbuildable
            if not ct.can_fire_from(spot, facing, EntityType.GUNNER, target):
                continue
            d = myLoc.distance_squared(spot)
            if best is None or d < best:
                best, bestSeat = d, (spot, facing)
        return bestSeat

    # -------------------------------------------------------------- 4. heal

    def step_heal(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 4: heal friendly buildings below max HP, largest damage fraction
        first. Voronoi: every building but the core goes to the ally with the
        smallest MANHATTAN distance to it. The core is exempt - one healer is
        +4 HP/turn against a sentinel's 9, so a lone healer loses by
        construction and it may have several."""
        cands = []
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam:
                continue
            hp, mx = ct.get_hp(b), ct.get_max_hp(b)
            if mx <= 0 or hp >= mx:
                continue
            isCore = ct.get_entity_type(b) == EntityType.CORE
            pos = ct.get_position(b)
            coreTiles = self._core_tiles() if isCore else None
            if coreTiles:
                # Healing needs orthogonal adjacency to A tile of the 2x2 core.
                pos = min(coreTiles, key=lambda p: myLoc.distance_squared(p))
            if not isCore and not self._win_heal(myLoc, pos):
                continue
            cands.append((1.0 - float(hp) / float(mx), pos))
        if not cands:
            return False
        cands.sort(key=lambda c: -c[0])
        for _frac, pos in cands:
            before = _snapshot(ct)
            if myLoc.distance_squared(pos) == 1:
                if ct.can_heal(pos):
                    ct.heal(pos)
            else:
                self._walk_adjacent(ct, myLoc, pos)
            if _acted(ct, before):
                return True
        return False

    def _win_heal(self, myLoc, pos: Position) -> bool:
        """The voronoi, over the ally positions recorded in step 2."""
        myD = _man(myLoc, pos)
        for a in self.allyPos:
            if _man(a, pos) < myD:
                return False
        return True

    # ----------------------------------------------------------- 5. project

    def step_project(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 5: grow my conveyor project. route_conveyor builds a segment at the
        open end facing the cheapest cardinal neighbour; the project then advances
        to the tile that segment outputs into, and finishes when that tile already
        holds a building - as a SUPER project if it is a core footprint tile,
        otherwise as a normal one."""
        end = self.projectEnd
        core = self.mapPf.teamCore
        if end is None or core is None:
            return False
        if not (0 <= end.x < self.mapW and 0 <= end.y < self.mapH):
            self.projectEnd = None
            return False
        before = _snapshot(ct)
        # route_conveyor reads get_tile_building_id(end), which RAISES out of
        # vision (builder r^2=20), and the end drifts out of vision as we walk.
        if not ct.is_in_vision(end):
            self.mapPf.moveTo(ct, end)
            return _acted(ct, before)
        route_conveyor(ct, self, end)
        if not _acted(ct, before):
            return False
        # route_conveyor can MOVE us, so `end` may be out of vision now even
        # though it was visible when we checked above - and get_tile_building_id
        # RAISES outside vision, which permanently destroys this builder. The
        # crash is dormant in the base bot and goes live the moment anything
        # changes which path we walk. Re-check before reading.
        if not ct.is_in_vision(end):
            return True
        bId = ct.get_tile_building_id(end)
        if bId is None or ct.get_entity_type(bId) != EntityType.CONVEYOR:
            return True         # we only moved, or cleared the tile: end stands
        # Remember it, so a hole here is detectable later. A destroyed conveyor
        # leaves nothing behind for get_nearby_buildings() to report.
        self.builtConv.add((end.x, end.y))
        # Count every conveyor we lay per tile. A tile we keep laying is a tile
        # something keeps shooting - see the grave check in step_repair.
        key = (end.x, end.y)
        counts = getattr(self, 'convN', None)
        if counts is None:
            counts = self.convN = {}
        counts[key] = counts.get(key, 0) + 1
        out = end.add(ct.get_direction(bId))
        if not (0 <= out.x < self.mapW and 0 <= out.y < self.mapH):
            self.projectEnd = None
        elif core.x <= out.x <= core.x + 1 and core.y <= out.y <= core.y + 1:
            self.projectEnd = None          # outputs into the core: SUPER project
            self.projectSuper = True
            self.chainDone = True
        elif not ct.is_in_vision(out) or ct.get_tile_building_id(out) is None:
            self.projectEnd = out           # keep growing
        else:
            self.projectEnd = None          # ended on another building: normal
        return True

    # --------------------------------------------------------- 6. my own ore

    def step_my_ore(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 6: walk to a cardinal NEIGHBOUR of my ore (never onto it) and build
        a harvester, then OPEN the project that routes it back."""
        ore = self.myOre
        if ore is None:
            return False
        d = myLoc.distance_squared(ore)
        if not self._ore_free(ct, ore):
            # Blocked. If it is one of OUR OWN buildings and we are adjacent,
            # clear it; anything else means the claim is gone. A harvester of ours
            # is excluded - the ore is already being worked, so demolishing it
            # would only undo our own economy.
            if d == 1:
                bId = ct.get_tile_building_id(ore)
                if (bId is not None and ct.get_team(bId) == myTeam
                        and ct.get_entity_type(bId) not in (EntityType.HARVESTER,
                                                            EntityType.CORE)
                        and ct.can_destroy(ore)):
                    before = _snapshot(ct)
                    ct.destroy(ore)
                    if _acted(ct, before):
                        return True
            self.myOre = None
            return False
        if d == 0:
            self.myOre = None       # standing on it makes it unbuildable
            return False
        before = _snapshot(ct)
        if d == 1:
            if ct.get_global_resources() < HARV_TI:
                return False    # too poor to open a NEW chain; route/heal instead
            if ct.can_build_harvester(ore):
                ct.build_harvester(ore)
            if not _acted(ct, before):
                return False        # most likely unaffordable: fall through
            self.myHarvester = ore
            self.myOre = None
            self.projectEnd = self._chain_start(ore)
            return True
        self._walk_adjacent(ct, myLoc, ore)
        return _acted(ct, before)

    def _chain_start(self, harv: Position):
        """Where the new chain starts routing back from: the free cardinal
        neighbour of the harvester minimising dsq to our core."""
        core = self.mapPf.teamCore
        cands = [n for n in [harv.add(d) for d in CARDINALS]
                 if 0 <= n.x < self.mapW and 0 <= n.y < self.mapH
                 and self.mapPf.fullMap[n.x][n.y] not in (2, 3)]
        if not cands:
            return None
        if core is not None:
            cands.sort(key=lambda p: p.distance_squared(core))
        return cands[0]

    # ------------------------------------------------------------- 7. guard

    def step_guard(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 7: patrol my finished super project, so the vision-limited steps 3,
        4, 5 and 6 keep firing on the things this bot built."""
        if not self.projectSuper or self.myHarvester is None:
            return False
        core = self.mapPf.teamCore
        if core is None:
            return False
        goal = self.guardGoal
        if goal is None or myLoc.distance_squared(goal) <= 1:
            goal = self._patrol_next(ct, myLoc)
            if goal is None:
                return False
            self.guardGoal = goal
        before = _snapshot(ct)
        self.mapPf.moveTo(ct, goal)
        return _acted(ct, before)

    # -------------------------------------------------------- 8. assign ore

    def step_assign_ore(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 8: scan the whole fullMap for ore. Reaching this step already means
        not guarding, no project, no turret to answer and nothing to heal."""
        core = self.mapPf.teamCore
        fm = self.mapPf.fullMap
        if core is None or fm is None:
            return False
        # spawnTarget is None only if slot 8 was never written for this bot;
        # unspecified, so fall back to the core.
        tgt = self.spawnTarget if self.spawnTarget is not None else core
        tgtIsOre = fm[tgt.x][tgt.y] == 1
        first = self.myHarvester is None
        # The core assigns bots 2-4 an ore tile as their target: take it unscanned.
        if first and tgtIsOre and self._ore_free(ct, tgt):
            self.myOre = tgt
            return self.step_my_ore(ct, myLoc, myTeam)
        norm = self._norm()
        threatened = self.mapPf.enemyTurretThreatenedTiles(ct)
        # WARDEN: this builder stays on our own infrastructure so that
        # breaks and barriers get noticed at all - both repair paths are
        # vision-limited (r^2=20), so coverage is the binding constraint.
        _ward = (self.mapPf.myNum % 3) == 0
        anchor, leashMul = self._leash_anchor(ct, myTeam)
        best, bestTile = None, None
        for x in range(self.mapW):
            col = fm[x]
            for y in range(self.mapH):
                if col[y] != 1 or (x, y) in threatened:
                    continue
                if _ward and (x - core.x) * (x - core.x) \
                        + (y - core.y) * (y - core.y) > WARD_R2:
                    continue        # a warden does not range out

                tile = Position(x, y)
                if not self._ore_free(ct, tile):
                    continue
                raw = _fall(tile.distance_squared(core), norm)
                if first:
                    # A fixed anchor, so the preference cannot drift as we walk.
                    # An outward direction marker is not an ore anchor, so bots 5+
                    # rank their first ore by closeness to themselves instead.
                    raw *= _fall(tile.distance_squared(tgt if tgtIsOre else myLoc),
                                 norm)
                else:
                    raw *= (_fall(tile.distance_squared(myLoc), norm)
                            * _fall(tile.distance_squared(tgt), norm)
                            * _fall(tile.distance_squared(anchor) * leashMul, norm))
                if best is None or raw > best:
                    best, bestTile = raw, tile
        if bestTile is None:
            return False
        # Claimed, then acted on through step 6 with no re-ranking mid-walk.
        self.myOre = bestTile
        return self.step_my_ore(ct, myLoc, myTeam)

    def _leash_anchor(self, ct: Controller, myTeam):
        """Keeps the economy compact instead of sprawling: my own harvester at a
        four-times-steeper falloff once my super project is finished, otherwise the
        nearest friendly conveyor in vision, or the core if there is none."""
        if self.projectSuper and self.myHarvester is not None:
            return self.myHarvester, LEASH_MUL
        myLoc = ct.get_position()
        best, bestD = self.mapPf.teamCore, None
        for b in ct.get_nearby_buildings():
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.CONVEYOR:
                continue
            pos = ct.get_position(b)
            d = myLoc.distance_squared(pos)
            if bestD is None or d < bestD:
                best, bestD = pos, d
        return best, 1.0

    def _norm(self):
        """One normaliser for every falloff term, scaled to the map so no term
        collapses on a large board."""
        if self.norms is None:
            self.norms = float(self.mapW * self.mapW + self.mapH * self.mapH) / 4.0
        return self.norms

    def _ore_free(self, ct: Controller, tile: Position) -> bool:
        """Ore with nothing built on it. get_tile_building_id RAISES outside vision,
        and there is no engine fog memory, so out of vision fall back to what we
        last saw (oreTaken) - otherwise a tile we watched a harvester go up on
        would look free again the moment it left vision."""
        if self.mapPf.fullMap[tile.x][tile.y] != 1:
            return False
        if not ct.is_in_vision(tile):
            return (tile.x, tile.y) not in self.oreTaken
        if ct.get_tile_building_id(tile) is not None:
            self.oreTaken[(tile.x, tile.y)] = ct.get_current_round()
            return False
        self.oreTaken.pop((tile.x, tile.y), None)
        return True

    # ----------------------------------------------------------- 9. regroup

    def step_regroup(self, ct: Controller, myLoc, myTeam) -> bool:
        """STEP 9: move toward the team core."""
        core = self.mapPf.teamCore
        if core is None:
            return False
        before = _snapshot(ct)
        self.mapPf.moveTo(ct, core)
        return _acted(ct, before)

    # ----------------------------------------------------------- shared bits

    def _core_tiles(self):
        c = self.mapPf.teamCore
        if c is None:
            return []
        return [Position(c.x + dx, c.y + dy) for dx in (0, 1) for dy in (0, 1)]

    def _walk_adjacent(self, ct: Controller, myLoc, tile: Position):
        """Head for the cardinal NEIGHBOUR of the tile nearest me, never the tile
        itself: every build and heal needs orthogonal adjacency, and standing on a
        build target makes it permanently unbuildable."""
        cands = [n for n in [tile.add(d) for d in CARDINALS]
                 if 0 <= n.x < self.mapW and 0 <= n.y < self.mapH
                 and self.mapPf.fullMap[n.x][n.y] not in (2, 3)]
        if not cands:
            return
        cands.sort(key=lambda p: myLoc.distance_squared(p))
        self.mapPf.moveTo(ct, cands[0])
