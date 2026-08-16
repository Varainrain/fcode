"""JAVELIN: launcher-relay siege, reverse-engineered from Jython's a2d0b3d2 g3
(midgard, core kill t141) plus local probes of the launcher mechanics.

Measured ground truth this is built on:
  - launch range: dist^2 <= 26 FROM THE LAUNCHER (probe: legal set max 26);
    up to 5 tiles straight / (5,1) diagonal per hop. Throws cost NOTHING
    (ti 456->456, ammo 0->0) - the only cost is the launcher building (~24).
  - relay cadence: land -> build next launcher -> get thrown, every 2 turns.
    Jython's builder crossed midgard (coreDist 48) by t12.
  - sentinels are INDIRECT fire: Jython's sentinel at (5,1) dealt all 882
    core damage with its ray fully blocked by barriers the entire game
    (and v108's own enemy_turret_coverage already models sentinel rays
    ignoring blockers). Barriers protect the sentinel, not the victim.
  - the entomb: barriers on the 12-tile ring around the enemy 2x2 core
    block enemy SPAWNS (radius^2 2 = exactly that ring), enemy gunner
    shots, and enemy builder pathing - while staying passable for us.

Roles: builder myNum JAV_NUM relays itself to the enemy core and runs the
siege; launchers (new entity branch) throw the claimant toward the goal.
Store: SLOT_JAV (12) = javelin's position claim, SLOT_SIEGE (13) = siege
flag the core reads to deepen the ammo ceiling (mortar drinks 10 per shot).
"""
from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS

import attack
import eco

OUT = r"C:/Users/IC3D_/Desktop/ic3d-battlecode/jav_debug.txt"
def _dbg(msg):
    try:
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(msg + chr(10))
    except Exception:
        pass

SLOT_JAV = 12
SLOT_SIEGE = 13
JAV_NUMS = ()          # RETIRED: stealing eco builders 1-2 for a t1 relay
                       # underperformed (3/10 mirror). The 190-game Jython
                       # profile shows first launcher at ~t300 average: the
                       # chain is built MID-GAME by attackers with attack
                       # money. See attack.run's self-relay. run_launcher
                       # below still drives every launcher we build.
ARRIVE_MANH = 5        # within this of the core footprint = siege mode

# all launcher-relative landing offsets, nearest-first tried toward the goal
_OFFS = [(dx, dy) for dx in range(-5, 6) for dy in range(-5, 6)
         if 0 < dx * dx + dy * dy <= 26]

C_JAV = (255, 230, 40)


def _core_tiles(core: Position):
    return [(core.x, core.y), (core.x + 1, core.y),
            (core.x, core.y + 1), (core.x + 1, core.y + 1)]


def _ring_tiles(core: Position, w, h):
    """The 12 tiles around the enemy 2x2 core: its spawn ring, its shot
    lanes, and its builders' doorway, all in one."""
    out = []
    ct4 = set(_core_tiles(core))
    for x in range(core.x - 1, core.x + 3):
        for y in range(core.y - 1, core.y + 3):
            if (x, y) in ct4:
                continue
            if 0 <= x < w and 0 <= y < h:
                out.append((x, y))
    return out


def _manh_to_core(pos: Position, core: Position) -> int:
    return min(abs(pos.x - tx) + abs(pos.y - ty) for tx, ty in _core_tiles(core))


def jav_claim(myLoc: Position) -> int:
    return ((myLoc.x << 5) | myLoc.y) + 1


def run_launcher(ct: Controller, player):
    """Launcher entity turn: throw the claimant builder toward the enemy core."""
    claim = ct.read_store(SLOT_JAV)
    _dbg(f"L t{ct.get_current_round()} pos=({ct.get_position().x},{ct.get_position().y}) claim={claim}")
    if claim <= 0:
        return
    claim -= 1
    bx, by = (claim >> 5) & 0x1F, claim & 0x1F
    myLoc = ct.get_position()
    if abs(bx - myLoc.x) + abs(by - myLoc.y) != 1:
        _dbg(f"L t{ct.get_current_round()} claim ({bx},{by}) not adjacent to ({myLoc.x},{myLoc.y})")
        return                              # claimant is not next to me
    bot = Position(bx, by)
    try:
        bId = ct.get_tile_builder_bot_id(bot)
        if bId is None or ct.get_team(bId) != ct.get_team():
            return
    except Exception:
        return
    # A mid-map launcher sees NEITHER core (vision^2 26), so its own mapPf
    # never learns enemyCorePos and the relay deadlocks (measured: launcher 2
    # at (8,7) idled from t4 on). The core publishes its position in slot 7
    # every turn; decode that and take the 180-rotation (verified to hold on
    # all 15 pool maps).
    goal = None
    try:
        compact = ct.read_store(7)
        if compact > 0:
            tcx, tcy = (compact >> 5) & 0x1F, compact & 0x1F
            goal = Position(player.mapW - tcx - 2, player.mapH - tcy - 2)
    except Exception:
        goal = None
    if goal is None:
        goal = player.mapPf.enemyCorePos
    if goal is None:
        return
    have = _manh_to_core(bot, goal)
    best = None
    bestD = have - 2                        # only throw for real progress
    for dx, dy in _OFFS:
        tx, ty = myLoc.x + dx, myLoc.y + dy
        if not (0 <= tx < player.mapW and 0 <= ty < player.mapH):
            continue
        d = min(abs(tx - gx) + abs(ty - gy) for gx, gy in _core_tiles(goal))
        if d < bestD:
            tgt = Position(tx, ty)
            try:
                if ct.can_launch(bot, tgt):
                    best, bestD = tgt, d
            except Exception:
                pass
    _dbg(f"L t{ct.get_current_round()} have={have} best={(best.x,best.y) if best else None}")
    if best is not None:
        ct.launch(bot, best)
        ct.write_store(SLOT_JAV, 0)         # claim consumed; free the highway


def _relay(ct: Controller, player, myLoc, goal) -> None:
    """Far from the core: leapfrog. Ride any chain launcher ahead of us
    (the mortarist NEVER builds its own - one chain serves everyone), else
    build the next launcher toward the goal."""
    myTeam = ct.get_team()
    locker = player.mapPf.myNum == JAV_NUMS[0]
    myD = _manh_to_core(myLoc, goal)
    bestL, bestD = None, None
    for b in ct.get_nearby_buildings():
        try:
            if ct.get_team(b) != myTeam or ct.get_entity_type(b) != EntityType.LAUNCHER:
                continue
            bPos = ct.get_position(b)
            d = _manh_to_core(bPos, goal)
            if d > myD + 1:
                continue                    # behind us: no ride
            if bestD is None or d < bestD:
                bestD, bestL = d, bPos
        except Exception:
            pass
    if bestL is not None:
        if abs(bestL.x - myLoc.x) + abs(bestL.y - myLoc.y) == 1:
            # the locker's claim always wins; the mortarist queues politely
            if locker or ct.read_store(SLOT_JAV) == 0:
                ct.write_store(SLOT_JAV, jav_claim(myLoc))
            player.draw_state(ct, C_JAV, bestL)
            return                          # hold still; the throw comes
        player.mapPf.moveTo(ct, bestL)
        player.draw_state(ct, C_JAV, bestL)
        return
    if not locker:                          # mortarist without a chain: walk
        player.mapPf.moveTo(ct, goal)
        player.draw_state(ct, C_JAV, goal)
        return
    if ct.get_global_resources() >= ct.get_launcher_cost():
        cands = []
        for d in CARDINALS:
            n = myLoc.add(d)
            if not (0 <= n.x < player.mapW and 0 <= n.y < player.mapH):
                continue
            cands.append((_manh_to_core(n, goal), n))
        cands.sort(key=lambda t: t[0])
        for _, n in cands:
            if ct.can_build_launcher(n):
                ct.build_launcher(n)
                ct.write_store(SLOT_JAV, jav_claim(myLoc))
                player.draw_state(ct, C_JAV, n)
                return
    player.mapPf.moveTo(ct, goal)           # broke or boxed in: walk
    player.draw_state(ct, C_JAV, goal)


def _siege(ct: Controller, player, myLoc, goal) -> None:
    """At the core: entomb its ring with our barriers, then stand up the
    mortar sentinel, then sustain (heal it, refill the ring).

    STAGED (measured: an unstaged siege pinned our titanium at ~20 all game,
    the mortar never got funded, eco mined 480 vs their 950 and we lost the
    race at t92): a few cheap barriers first, then SAVE for the sentinel,
    and only once the mortar stands does the core open the ammo pipe
    (SLOT_SIEGE=2)."""
    ct.write_store(SLOT_JAV, 0)             # relay over; free the launchers
    myTeam = ct.get_team()

    empty_ring = []
    for x, y in _ring_tiles(goal, player.mapW, player.mapH):
        p = Position(x, y)
        try:
            if not ct.is_in_vision(p):
                continue
            if ct.get_tile_env(p) == Environment.WALL:
                continue
            if ct.get_tile_building_id(p) is not None:
                continue
            if ct.get_tile_builder_bot_id(p) is not None:
                continue
            empty_ring.append(p)
        except Exception:
            pass

    # our mortar: a sentinel of ours near the siege (builder vision is small,
    # so also trust a short memory of having built one)
    haveMortar = False
    mortarPos = None
    mortarId = None
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.SENTINEL:
            haveMortar = True
            mortarPos = ct.get_position(b)
            mortarId = b
            break
    mem = getattr(player, "_jav_mortar", None)
    if not haveMortar and mem is not None:
        mp = Position(mem[0], mem[1])
        try:
            if ct.is_in_vision(mp) and ct.get_tile_building_id(mp) is None:
                player._jav_mortar = None   # it died; rebuild below
            else:
                haveMortar = True           # out of sight, assume alive
                mortarPos = mp
        except Exception:
            haveMortar = True
            mortarPos = mp

    ct.write_store(SLOT_SIEGE, 2 if haveMortar else 1)

    # THE SPAWN LOCK IS THE WEAPON (Jython: 19 barriers, one sentinel). A
    # fully sealed ring = the enemy cannot spawn AT ALL (radius^2 2 covers
    # exactly these 12 tiles): their army stops growing the moment it
    # closes, which is what buys the mortar its 60-turn grind. The LOCKER
    # (myNum 1) always seals; the MORTARIST (2) guns first, seals after.
    locker = player.mapPf.myNum == JAV_NUMS[0]
    wantSeal = empty_ring and (locker or haveMortar)
    if wantSeal and ct.get_global_resources() >= ct.get_barrier_cost():
        empty_ring.sort(key=lambda p: myLoc.distance_squared(p))
        near = empty_ring[0]
        if myLoc.distance_squared(near) == 1 and ct.can_build_barrier(near):
            ct.build_barrier(near)
            player.draw_state(ct, C_JAV, near)
            return
        player.mapPf.moveTo(ct, near)
        player.draw_state(ct, C_JAV, near)
        return

    # 2) mortar: park at the seat and SAVE - build the moment it is affordable
    if not haveMortar and not locker:
        spot = attack.find_sentinel_spot(ct, player)
        if spot is not None:
            sPos, sDir = spot
            if (ct.get_global_resources() >= ct.get_sentinel_cost()
                    and ct.can_build_sentinel(sPos, sDir)):
                ct.build_sentinel(sPos, sDir)
                player._jav_mortar = (sPos.x, sPos.y)
                ct.write_store(SLOT_SIEGE, 2)
                player.draw_state(ct, C_JAV, sPos)
                return
            if myLoc.distance_squared(sPos) > 1:
                player.mapPf.moveTo(ct, sPos)
            player.draw_state(ct, C_JAV, sPos)
            return

    # 3) sustain: heal the mortar, then idle next to it (body-block)
    if haveMortar and mortarPos is not None:
        if (mortarId is not None
                and ct.get_hp(mortarId) < ct.get_max_hp(mortarId)
                and myLoc.distance_squared(mortarPos) == 1 and ct.can_heal(mortarPos)):
            ct.heal(mortarPos)
            return
        if myLoc.distance_squared(mortarPos) > 2:
            player.mapPf.moveTo(ct, mortarPos)
            return
    player.draw_state(ct, C_JAV, goal, dot=True)


def run_javelin(ct: Controller, player) -> bool:
    """The javelin builder's whole turn. True = handled."""
    goal = player.mapPf.enemyCorePos
    if goal is None:
        return False
    # ECO BREATH FIRST (measured: relaying off the opening bank starved the
    # harvester bootstrap - 870 mined vs 1670 - and the siege sat broke at
    # the gates). Jython's own timeline: eco t0-12, relay after. Until the
    # first income tick, this builder is just an eco builder.
    if ct.read_store(eco.SLOT_BOOTSTRAP) == 1 and ct.get_current_round() < 25:
        return False
    myLoc = ct.get_position()
    _dbg(f"J t{ct.get_current_round()} pos=({myLoc.x},{myLoc.y}) manh={_manh_to_core(myLoc, goal)} ti={ct.get_global_resources()}")
    if _manh_to_core(myLoc, goal) > ARRIVE_MANH:
        _relay(ct, player, myLoc, goal)
    else:
        _siege(ct, player, myLoc, goal)
    return True
