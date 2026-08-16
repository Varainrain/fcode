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
                    and ct.get_entity_type(b) == EntityType.SENTINEL
                    and ct.get_hp(b) < ct.get_max_hp(b)):
                bPos = ct.get_position(b)
                if myLoc.distance_squared(bPos) == 1 and ct.can_heal(bPos):
                    ct.heal(bPos)
                    return
        except Exception:
            pass

    # close enough: plant the next wave piece on ANY adjacent buildable tile,
    # facing the core (fire is indirect - the seat does not need a clear ray,
    # and walking to a "best" seat dies in the victim's building field)
    if dCore <= 45 and ct.get_global_resources() >= ct.get_sentinel_cost():
        target = min(corners, key=lambda c: myLoc.distance_squared(c))
        for d in CARDINALS:
            n = myLoc.add(d)
            if not (0 <= n.x < player.mapW and 0 <= n.y < player.mapH):
                continue
            dx = (target.x > n.x) - (target.x < n.x)
            dy = (target.y > n.y) - (target.y < n.y)
            for fd in DIRECTIONS:
                fdx, fdy = fd.delta()
                if (fdx, fdy) == (dx, dy):
                    try:
                        if ct.can_build_sentinel(n, fd):
                            ct.build_sentinel(n, fd)
                            player.draw_state(ct, C_WAVE, n)
                            return
                    except Exception:
                        pass
                    break

    player.mapPf.moveTo(ct, enemyCore)
    player.draw_state(ct, C_WAVE, enemyCore)
