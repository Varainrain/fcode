"""finalsforge — 15 plausible FINALS maps (ic3d's request, 2026-08-23).

Why: the Stockholm finals run on maps we have never seen, and our whole gate
history is measured on the 15-map league pool. A bot tuned to that pool can
be tuned to its quirks - the Aug-15 rotation already voided every number we
had. These maps deliberately span the axes the pool does NOT: core distance
from 10 to 46, sizes 16x16 to 32x32, open fields through corridor mazes,
ore at the door and ore only in contested middle ground.

They are NOT balanced or pretty. They are a VERSATILITY harness: a champion
that only wins at one core distance or only with ore nearby will show it here
long before the finals do.

    python finalsforge.py            # writes maps_finals/*.map26

Kept out of maps/ on purpose - the ship gate stays league-pure (same rule as
maps_stress/). Gate with lab_finals.py.
"""
import os
import sys

sys.path.insert(0, '.')
from mapforge import compile_map


def ring(t, cx, cy, r, val=1, gaps=()):
    """A square wall ring of radius r around (cx,cy), minus gap directions."""
    for d in range(-r, r + 1):
        for (x, y) in ((cx + d, cy - r), (cx + d, cy + r),
                       (cx - r, cy + d), (cx + r, cy + d)):
            if (x, y) in gaps:
                continue
            t[(x, y)] = val


def maps():
    M = {}

    # ---- 1-3: CORE DISTANCE SWEEP on an open field. The single axis our
    # hybrid dispatches on (it switches to the spear past distance 26), so
    # the finals must be probed either side of that line.
    M['open_close'] = (18, 18, {(3, 8): 2, (8, 3): 2, (5, 5): 2}, (2, 2))
    M['open_mid'] = (24, 24, {(4, 12): 2, (12, 4): 2, (7, 7): 2, (2, 9): 2}, (2, 2))
    M['open_far'] = (32, 32, {(5, 16): 2, (16, 5): 2, (9, 9): 2, (3, 12): 2}, (2, 2))

    # ---- 4-5: DIAGONAL vs ORTHOGONAL approach. Cores on a diagonal make
    # every ray oblique; cores on a rank make head-on gunner lines.
    M['diagonal'] = (26, 26, {(6, 6): 2, (3, 10): 2, (10, 3): 2}, (2, 2))
    M['broadside'] = (30, 20, {(6, 9): 2, (10, 4): 2, (4, 14): 2}, (2, 9))

    # ---- 6-7: ORE AT THE DOOR vs ORE IN THE MIDDLE. Decides whether the
    # economy is safe or must be fought for - our losses correlate with
    # harvester count, so this is the axis that matters most.
    M['doorstep'] = (24, 24, {(2, 4): 2, (4, 2): 2, (3, 3): 2, (1, 5): 2, (5, 1): 2}, (2, 2))
    t = {}
    for i in range(6):
        t[(11 + (i % 2), 8 + i)] = 2
    M['contested'] = (26, 26, t, (2, 2))

    # ---- 8-9: CHOKEPOINTS. One gate and two gates: a siege bot that can
    # only win by walking a wide front will stall here.
    t = {}
    for y in range(24):
        if y not in (11, 12):
            t[(12, y)] = 1
    t.update({(4, 6): 2, (6, 4): 2, (3, 3): 2})
    M['onegate'] = (24, 24, t, (2, 2))
    t = {}
    for y in range(28):
        if y not in (6, 7, 20, 21):
            t[(14, y)] = 1
    t.update({(4, 8): 2, (8, 4): 2, (5, 5): 2, (3, 11): 2})
    M['twogate'] = (28, 28, t, (2, 2))

    # ---- 10: CORRIDOR MAZE. Pathfinding and TLE pressure; also the map
    # where phantom walls would hurt most.
    t = {}
    for x in range(2, 24):
        if x % 4 == 0:
            for y in range(2, 24):
                if (y + x) % 9 not in (0, 1):
                    t[(x, y)] = 1
    t.update({(3, 6): 2, (6, 3): 2, (2, 10): 2})
    M['corridors'] = (26, 26, t, (1, 1))

    # ---- 11: FORTRESS POCKETS. Core walled with a single door - the shape
    # every cage attack (O(1), Bean, HTTP 418) tries to create by hand.
    t = {}
    ring(t, 4, 4, 3, gaps=((7, 4),))
    t.update({(2, 6): 2, (6, 2): 2, (10, 10): 2, (12, 8): 2})
    M['pockets'] = (26, 26, t, (3, 3))

    # ---- 12: BARREN. Almost no ore: whoever wastes titanium loses. Our
    # treadmill bugs (gunner seats, conveyor rebuilds) are fatal here.
    M['barrenfin'] = (24, 24, {(5, 5): 2, (9, 3): 2}, (2, 2))

    # ---- 13: RICH. Ore everywhere: pure economy scaling, no excuses.
    t = {}
    for i in range(10):
        t[(3 + i, 3 + (i % 4))] = 2
        t[(2 + (i % 5), 9 + i)] = 2
    M['richfield'] = (28, 28, t, (1, 1))

    # ---- 14: LOPSIDED. Wide and short - long horizontal march, no vertical
    # room to manoeuvre around a siege line.
    t = {}
    for x in range(8, 26):
        if x % 5:
            t[(x, 8)] = 1
    t.update({(4, 4): 2, (6, 10): 2, (3, 12): 2})
    M['lopsided'] = (34, 16, t, (2, 6))

    # ---- 15: SCATTERED COVER. Random-ish blocks: no clean firing lines,
    # the closest thing here to an unfamiliar hand-made finals map.
    t = {}
    for i in range(40):
        x = (i * 7 + 3) % 26
        y = (i * 11 + 5) % 26
        if 2 < x < 24 and 2 < y < 24:
            t[(x, y)] = 1
    for (x, y) in ((4, 7), (7, 4), (11, 11), (5, 13)):
        t[(x, y)] = 2
    M['scatter'] = (28, 28, t, (1, 1))
    return M


def main():
    os.makedirs('maps_finals', exist_ok=True)
    made = []
    for name, (W, H, tiles, coreA) in maps().items():
        # Never let a WALL sit on a core footprint or its immediate ring - a
        # sealed core is not a hard map, it is a broken one. Ore there is
        # fine and is the entire point of the doorstep map, so only walls are
        # cleared (clearing everything cut doorstep from 10 ore tiles to 4).
        ax, ay = coreA
        for dx in range(-1, 3):
            for dy in range(-1, 3):
                if tiles.get((ax + dx, ay + dy)) == 1:
                    tiles.pop((ax + dx, ay + dy), None)
        blob = compile_map(W, H, tiles, coreA)
        path = os.path.join('maps_finals', name + '.map26')
        with open(path, 'wb') as f:
            f.write(blob)
        bx, by = W - 2 - ax, H - 2 - ay
        dist = abs(bx - ax) + abs(by - ay)
        made.append((name, W, H, dist, sum(1 for v in tiles.values() if v == 2),
                     sum(1 for v in tiles.values() if v == 1)))
    print(f"{'map':<14}{'size':>9}{'coredist':>10}{'ore':>6}{'walls':>7}")
    for n, W, H, d, ore, wall in made:
        print(f"{n:<14}{W:>4}x{H:<4}{d:>10}{ore*2:>6}{wall*2:>7}")
    print(f"\n{len(made)} maps written to maps_finals/")


main()
