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

SLOT_JAV = 12
SLOT_SIEGE = 13
JAV_NUMS = (1,)        # GUNGNIR: the t1 relay is BACK, and this time the
                       # economics match the blueprint. e3eb4324 (Jython 4-1
                       # over #2 Lorem): THREE builders total, launcher t1,
                       # relay t2, at the enemy core by t6-t12, entomb from
                       # t9, TWO sentinels t36-47, core dead t79-91. The t1
                       # javelin only failed before because it fought our
                       # own 5-spawn eco for the opening bank - GUNGNIR
                       # spawns 3, so the bank belongs to the spear.
ARRIVE_MANH = 5        # within this of the core footprint = siege mode
MORTARS = 2            # two guns = kill in ~30 firing turns, not 60

# all launcher-relative landing offsets, nearest-first tried toward the goal
_OFFS = [(dx, dy) for dx in range(-5, 6) for dy in range(-5, 6)
         if 0 < dx * dx + dy * dy <= 26]

C_JAV = (255, 230, 40)
C_DEF_SUSTAIN = (120, 255, 120)


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
    if claim <= 0:
        return
    claim -= 1
    bx, by = (claim >> 5) & 0x1F, claim & 0x1F
    myLoc = ct.get_position()
    if abs(bx - myLoc.x) + abs(by - myLoc.y) != 1:
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

    # our mortars: count OUR sentinels near the siege (vision is small, so
    # keep a memory of the ones we built and forget them when seen dead)
    mortars = []
    seen = set()
    for b in ct.get_nearby_buildings():
        if ct.get_team(b) == myTeam and ct.get_entity_type(b) == EntityType.SENTINEL:
            bPos = ct.get_position(b)
            mortars.append((b, bPos))
            seen.add((bPos.x, bPos.y))
    mem = list(getattr(player, "_jav_mortars", []))
    for mx, my_ in mem:
        if (mx, my_) in seen:
            continue
        mp = Position(mx, my_)
        try:
            if ct.is_in_vision(mp) and ct.get_tile_building_id(mp) is None:
                continue                    # died: drop from memory
        except Exception:
            pass
        mortars.append((None, mp))          # out of sight, assume alive
    player._jav_mortars = [(p.x, p.y) for _, p in mortars]
    nMortars = len(mortars)

    ct.write_store(SLOT_SIEGE, 2 if nMortars else 1)

    # THE BLUEPRINT ORDER (e3eb4324 g1/g3, Jython vs #2 Lorem): entomb
    # FIRST (barriers t9-t35, spawn-lock + shot-block while the victim has
    # nothing there), THEN two sentinels (t36-47), first hit t41-48, core
    # dead t79-91. Seal until the ring is mostly shut, then guns, then
    # finish the ring and sustain.
    # FULL seal, like the blueprint's 12-14 barriers: every open ring tile
    # is a doorway for a defender to walk out and shoot the mortar (measured:
    # with 4 tiles left open, our lone mortar died after 8 shots - 144 dmg -
    # and the siege collapsed). <=2 left is body-blocked tolerance, not
    # policy.
    sealFirst = len(empty_ring) > 2 and nMortars == 0
    sealAfter = empty_ring and nMortars >= 1
    if (sealFirst or sealAfter) and ct.get_global_resources() >= ct.get_barrier_cost():
        empty_ring.sort(key=lambda p: myLoc.distance_squared(p))
        near = empty_ring[0]
        if myLoc.distance_squared(near) == 1 and ct.can_build_barrier(near):
            ct.build_barrier(near)
            player.draw_state(ct, C_JAV, near)
            return
        player.mapPf.moveTo(ct, near)
        player.draw_state(ct, C_JAV, near)
        return

    # 2) mortars, up to MORTARS of them - two guns halve the kill clock
    if nMortars < MORTARS:
        spot = attack.find_sentinel_spot(ct, player)
        if spot is not None:
            sPos, sDir = spot
            if (ct.get_global_resources() >= ct.get_sentinel_cost()
                    and ct.can_build_sentinel(sPos, sDir)):
                ct.build_sentinel(sPos, sDir)
                player._jav_mortars = player._jav_mortars + [(sPos.x, sPos.y)]
                ct.write_store(SLOT_SIEGE, 2)
                player.draw_state(ct, C_JAV, sPos)
                return
            if myLoc.distance_squared(sPos) > 1:
                player.mapPf.moveTo(ct, sPos)
            player.draw_state(ct, C_JAV, sPos)
            return

    # 3) sustain: heal the weakest mortar in reach, stay close to the front
    best, bestHp = None, None
    for bId, bPos in mortars:
        if bId is None:
            continue
        try:
            hp = ct.get_hp(bId)
            if (hp < ct.get_max_hp(bId)
                    and myLoc.distance_squared(bPos) == 1 and ct.can_heal(bPos)):
                if bestHp is None or hp < bestHp:
                    bestHp, best = hp, bPos
        except Exception:
            pass
    if best is not None:
        ct.heal(best)
        player.draw_state(ct, C_DEF_SUSTAIN, best)
        return
    if mortars and myLoc.distance_squared(mortars[0][1]) > 2:
        player.mapPf.moveTo(ct, mortars[0][1])
        return
    player.draw_state(ct, C_JAV, goal, dot=True)


def home_garrison(ct: Controller, player, myLoc) -> bool:
    """ONE early gunner at home. The pure blueprint races even against an
    attacking incumbent (v119's walkers first-hit our empty house ~t55 and
    kill by t87 on midgard - a race-tie with our own siege clock). One
    gunner (~50 Ti, ~5 turns of mortar delay) costs their push 15-20 turns:
    that margin IS the race. Builder 2's job, once, between t15 and t60."""
    rnd = ct.get_current_round()
    if rnd < 15 or rnd > 60:
        return False
    teamCore = player.mapPf.teamCore
    if teamCore is None:
        return False
    if myLoc.distance_squared(teamCore) > 20:
        return False
    myTeam = ct.get_team()
    for b in ct.get_nearby_buildings():
        try:
            if (ct.get_team(b) == myTeam
                    and ct.get_entity_type(b) == EntityType.GUNNER):
                return False                # garrison exists
        except Exception:
            pass
    if ct.get_global_resources() < ct.get_gunner_cost() + 20:
        return False
    centre = Position(player.mapW // 2, player.mapH // 2)
    from mapPathfinding import DIRECTIONS
    for d in CARDINALS:
        n = myLoc.add(d)
        if not (0 <= n.x < player.mapW and 0 <= n.y < player.mapH):
            continue
        if _manh_to_core(n, teamCore) < 1:
            continue                        # not on the spawn ring itself
        dx = (centre.x > n.x) - (centre.x < n.x)
        dy = (centre.y > n.y) - (centre.y < n.y)
        for fd in DIRECTIONS:
            if fd.delta() == (dx, dy):
                try:
                    if ct.can_build_gunner(n, fd):
                        ct.build_gunner(n, fd)
                        return True
                except Exception:
                    pass
                break
    return False


def run_javelin(ct: Controller, player) -> bool:
    """The javelin builder's whole turn. True = handled."""
    goal = player.mapPf.enemyCorePos
    if goal is None:
        return False
    # NO eco-breath gate: the blueprint relays at t1-t2. That only bankrupts
    # a 5-spawn opening - GUNGNIR spawns 3, so the bank funds the spear.
    myLoc = ct.get_position()
    if _manh_to_core(myLoc, goal) > ARRIVE_MANH:
        _relay(ct, player, myLoc, goal)
    else:
        _siege(ct, player, myLoc, goal)
    return True
