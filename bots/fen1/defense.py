"""FENRIR defense: the anti-launcher-meta layer.

The entire top 5 runs the same offense - launcher-ferried builders entomb
the victim's spawn ring and a sentinel kills the core with INDIRECT fire
(882 dmg through a fully-blocked ray, measured in a2d0b3d2 g3). v108 has no
answer: gunners are direct-fire (the attacker's barriers blank them) and
healing loses to sustained bombardment (the all-heal ledger, again).

Two counters, both cheap, both aimed at the meta's exact mechanisms:

1. COUNTER-BATTERY. Indirect fire cuts both ways: THEIR barriers cannot
   protect THEIR sentinel from OURS. The core is the sensor (vision^2 36
   covers every tile a sentinel can legally fire from, 32) and publishes
   parked enemy sentinels in SLOT_RADAR; a defender seats our sentinel on a
   ray to the threat and heals it. A healed sentinel (12 hp/turn from one
   adjacent builder... 4/turn) against 9 dmg/turn incoming wins the duel;
   theirs dies in 3 of our shots.

2. RING VACCINE. Their entomb needs our core's 12 ring tiles EMPTY - so we
   occupy the far-side ones ourselves with owner-passable barriers (~4 Ti
   each) and leave the centre-facing lanes open for our own spawns. A tile
   we hold is a tile they can neither wall NOR land a thrown builder on.

Store: SLOT_RADAR (11) = up to 2 enemy-sentinel offsets from the team core,
(dx,dy) as signed nibbles, one byte each. SLOT_CB_CLAIM (14) = round-stamp
so only one defender chases counter-battery at a time.
"""
from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS, sentinelLines

SLOT_RADAR = 11
SLOT_CB_CLAIM = 14
VACCINE_MIN_ROUND = 30
VACCINE_MIN_TI = 24    # measured: the shared pool hovers at 20-50 mid-game;
                       # a 60 floor meant the vaccine almost never fired.
                       # A barrier is ~4-6 Ti - 24 is already conservative.
C_DEF = (80, 220, 255)


def core_publish_radar(ct: Controller, myLoc: Position, myTeam) -> None:
    """Runs on the CORE turn: publish parked enemy sentinels near us."""
    slot = 0
    n = 0
    for b in ct.get_nearby_buildings():
        if n >= 2:
            break
        try:
            if ct.get_team(b) == myTeam:
                continue
            if ct.get_entity_type(b) != EntityType.SENTINEL:
                continue
            sPos = ct.get_position(b)
            if min(sPos.distance_squared(Position(myLoc.x + ox, myLoc.y + oy))
                   for ox in (0, 1) for oy in (0, 1)) > 36:
                continue
            dx = sPos.x - myLoc.x
            dy = sPos.y - myLoc.y
            if -8 <= dx <= 7 and -8 <= dy <= 7:
                slot |= (((dx & 0xF) << 4) | (dy & 0xF)) << (8 * n)
                n += 1
        except Exception:
            pass
    ct.write_store(SLOT_RADAR, slot)


def _radar_threats(ct: Controller, teamCore: Position):
    out = []
    try:
        slot = ct.read_store(SLOT_RADAR)
    except Exception:
        return out
    if not slot or teamCore is None:
        return out
    for i in (0, 1):
        b = (slot >> (8 * i)) & 0xFF
        if b == 0:
            continue
        dx = (b >> 4) & 0xF
        dy = b & 0xF
        if dx >= 8:
            dx -= 16
        if dy >= 8:
            dy -= 16
        out.append(Position(teamCore.x + dx, teamCore.y + dy))
    return out


def counter_battery(ct: Controller, player, myLoc: Position) -> bool:
    """Seat OUR sentinel on a ray to a parked enemy sentinel, then heal it.
    True = this turn is spent."""
    teamCore = player.mapPf.teamCore
    threats = _radar_threats(ct, teamCore)
    if not threats:
        return False
    myTeam = ct.get_team()
    rnd = ct.get_current_round()

    # do we already have a defending sentinel? then keep it alive
    for b in ct.get_nearby_buildings():
        try:
            if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.SENTINEL:
                bPos = ct.get_position(b)
                if teamCore is not None and bPos.distance_squared(teamCore) <= 50:
                    if (ct.get_hp(b) < ct.get_max_hp(b)
                            and myLoc.distance_squared(bPos) == 1
                            and ct.can_heal(bPos)):
                        ct.heal(bPos)
                        player.draw_state(ct, C_DEF, bPos)
                        return True
                    return False        # battery standing; not our turn to act
        except Exception:
            pass

    # one chaser at a time (round-stamp claim, stale after 2 rounds)
    try:
        claim = ct.read_store(SLOT_CB_CLAIM)
        if claim and rnd - claim < 2:
            return False
    except Exception:
        return False
    if ct.get_global_resources() < ct.get_sentinel_cost():
        return False

    threat = threats[0]
    best = None
    bestKey = None
    try:
        seats = player.mapPf.gunnerSpots(threat, player.mapW, player.mapH,
                                         True, lines=sentinelLines)
    except Exception:
        return False
    for sPos, sDir in seats:
        try:
            if not ct.is_in_vision(sPos):
                continue
            if ct.get_tile_building_id(sPos) is not None:
                continue
            if ct.get_tile_env(sPos) == Environment.WALL:
                continue
            if ct.get_tile_builder_bot_id(sPos) is not None:
                continue
            # seat on OUR side of the threat: nearer our core than the threat is
            if teamCore is not None and sPos.distance_squared(teamCore) > threat.distance_squared(teamCore) + 8:
                continue
            key = (myLoc.distance_squared(sPos), sPos.distance_squared(threat))
            if bestKey is None or key < bestKey:
                bestKey, best = key, (sPos, sDir)
        except Exception:
            pass
    if best is None:
        return False
    sPos, sDir = best
    ct.write_store(SLOT_CB_CLAIM, rnd)
    if myLoc.distance_squared(sPos) == 1 and ct.can_build_sentinel(sPos, sDir):
        ct.build_sentinel(sPos, sDir)
        player.draw_state(ct, C_DEF, sPos)
        return True
    player.mapPf.moveTo(ct, sPos)
    player.draw_state(ct, C_DEF, sPos)
    return True


def ring_vaccine(ct: Controller, player, myLoc: Position) -> bool:
    """Occupy the far-side ring tiles of OUR core so the meta's entomb (and
    thrown-builder landings there) has nowhere to go. Leaves the 5 tiles
    nearest map centre open as spawn lanes. True = turn spent."""
    teamCore = player.mapPf.teamCore
    if teamCore is None:
        return False
    if ct.get_current_round() < VACCINE_MIN_ROUND:
        return False
    if ct.get_global_resources() < VACCINE_MIN_TI:
        return False
    w, h = player.mapW, player.mapH
    centre = Position(w // 2, h // 2)
    coreT = {(teamCore.x + a, teamCore.y + b) for a in (0, 1) for b in (0, 1)}
    ring = []
    for x in range(teamCore.x - 1, teamCore.x + 3):
        for y in range(teamCore.y - 1, teamCore.y + 3):
            if (x, y) in coreT or not (0 <= x < w and 0 <= y < h):
                continue
            ring.append(Position(x, y))
    if len(ring) <= 5:
        return False                    # cramped corner core: all lanes needed
    ring.sort(key=lambda p: p.distance_squared(centre), reverse=True)
    for p in ring[:-5]:                 # farthest from centre first; keep 5 lanes
        try:
            env = ct.get_tile_env(p)
            if env == Environment.WALL or env == Environment.ORE_TITANIUM:
                continue
            if ct.get_tile_building_id(p) is not None:
                continue
            if ct.get_tile_builder_bot_id(p) is not None:
                continue
        except Exception:
            continue
        if myLoc.x == p.x and myLoc.y == p.y:
            continue    # standing ON the target: build a different ring tile
                        # first (measured: dist==1 never fires from dist 0 and
                        # moveTo(self) is a no-op - the defender pinned there)
        if myLoc.distance_squared(p) == 1 and ct.can_build_barrier(p):
            ct.build_barrier(p)
            player.draw_state(ct, C_DEF, p)
            return True
        player.mapPf.moveTo(ct, p)
        player.draw_state(ct, C_DEF, p)
        return True
    return False
