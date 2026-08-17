"""kladde-style SENTINEL WAVE attack, as a faithful test dummy.

From the 3413cca2 g5 autopsy (they killed our core t124 on midgard):
sentinels leapfrog toward the victim's core as mobile artillery -
(13,4) -> (22,2) -> (21,27) - each new one built a hop closer, first core
hit t85, seven built over the game. Attackers escort and heal.

Replaces attack.run for the dummy: every attacker walks toward the enemy
core and, whenever affordable, plants a sentinel FACING the enemy core at
its current position once within ~2x sentinel range, stepping the wave
closer each time. Simple, relentless, and exactly the shape that beat us.
"""
from fcode import Controller, Direction, EntityType, Environment, Position
from mapPathfinding import CARDINALS, DIRECTIONS, sentinelLines

OUT = r"C:/Users/IC3D_/Desktop/ic3d-battlecode/wave_debug.txt"
def _dbg(m):
    try:
        with open(OUT,"a",encoding="utf-8") as f: f.write(m+chr(10))
    except Exception: pass

C_WAVE = (255, 80, 80)


def wave_run(ct: Controller, player):
    myLoc = ct.get_position()
    myTeam = ct.get_team()
    enemyCore = player.mapPf.enemyCorePos
    if enemyCore is None:
        return
    corners = [enemyCore, enemyCore.add(Direction.EAST), enemyCore.add(Direction.SOUTH),
               enemyCore.add(Direction.SOUTH).add(Direction.EAST)]
    dCore = min(myLoc.distance_squared(c) for c in corners)
    r_ = ct.get_current_round()
    if r_ % 10 == 0:
        _dbg(f"t{r_} num={player.mapPf.myNum} pos=({myLoc.x},{myLoc.y}) dCore={dCore} ti={ct.get_global_resources()} cost={ct.get_sentinel_cost()}")

    # heal the nearest damaged friendly sentinel (the wave's sustain)
    for b in ct.get_nearby_buildings():
        try:
            if (ct.get_team(b) == myTeam
                    and ct.get_entity_type(b) == EntityType.SENTINEL):
                bPos = ct.get_position(b)
                # WALL BEFORE HEAL (fixture v2): the heal early-return starved
                # the walling to ~2 barriers/game. Armor first - an unhealed
                # sentinel behind a wall outlives a healed one in the open.
                if myLoc.distance_squared(bPos) <= 2 and ct.get_global_resources() >= 12:
                    tgt = min(corners, key=lambda c: bPos.distance_squared(c))
                    wdx = (tgt.x > bPos.x) - (tgt.x < bPos.x)
                    wdy = (tgt.y > bPos.y) - (tgt.y < bPos.y)
                    w = Position(bPos.x + wdx, bPos.y + wdy)
                    if (myLoc.distance_squared(w) <= 2
                            and ct.get_tile_building_id(w) is None
                            and ct.can_build_barrier(w)):
                        ct.build_barrier(w)
                        return
                if (ct.get_hp(b) < ct.get_max_hp(b)
                        and myLoc.distance_squared(bPos) == 1 and ct.can_heal(bPos)):
                    ct.heal(bPos)
                    return
        except Exception:
            pass

    # ARMORED PLANT (fixture v3): wall FIRST on the core-ward tile, step back,
    # then plant the sentinel where we stood - it ends up behind its own wall,
    # facing the core. Builds need ORTHOGONAL adjacency, which is why walling
    # an already-planted sentinel's far side never fired (1-2 walls/game).
    if dCore <= 45 and ct.get_global_resources() >= ct.get_sentinel_cost() + 3:
        target = min(corners, key=lambda c: myLoc.distance_squared(c))
        st = getattr(player, "_wv_state", "wall")
        if st == "plant":
            spot = getattr(player, "_wv_spot", None)
            if spot is not None and myLoc.x == spot.x and myLoc.y == spot.y:
                # still standing where the sentinel goes - step back first
                back = Position(myLoc.x - (target.x > myLoc.x) + (target.x < myLoc.x),
                                myLoc.y - (target.y > myLoc.y) + (target.y < myLoc.y))
                player.mapPf.moveTo(ct, back)
                return
            # stepped back: plant on the old spot (its core-ward side is walled)
            player._wv_state = "wall"
            if spot is not None and myLoc.distance_squared(spot) == 1:
                dx = (target.x > spot.x) - (target.x < spot.x)
                dy = (target.y > spot.y) - (target.y < spot.y)
                for fd in DIRECTIONS:
                    if fd.delta() == (dx, dy):
                        try:
                            if ct.can_build_sentinel(spot, fd):
                                ct.build_sentinel(spot, fd)
                                player.draw_state(ct, C_WAVE, spot)
                                return
                        except Exception:
                            pass
                        break
        else:
            wdx = (target.x > myLoc.x) - (target.x < myLoc.x)
            wdy = (target.y > myLoc.y) - (target.y < myLoc.y)
            for w in (Position(myLoc.x + wdx, myLoc.y), Position(myLoc.x, myLoc.y + wdy)):
                if w == myLoc:
                    continue
                try:
                    if ct.get_tile_building_id(w) is None and ct.can_build_barrier(w):
                        ct.build_barrier(w)
                        player._wv_state = "plant"
                        player._wv_spot = Position(myLoc.x, myLoc.y)
                        # step back happens next turn via the act-xor-move rule:
                        # we act now, move away next turn, plant the turn after
                        return
                except Exception:
                    pass

    player.mapPf.moveTo(ct, enemyCore)
    player.draw_state(ct, C_WAVE, enemyCore)
