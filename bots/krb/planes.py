"""Bit-sliced score planes (Pantheon figure 14) for gunner placement.

A plane stack is a list of NUM_PLANES big-int bitmasks; the integer score of
tile n is sum(((planes[i] >> n) & 1) << i). add_const() adds a constant to
every tile of a mask in O(NUM_PLANES) whole-board ops — cost independent of
how many tiles are in the mask. argmax_mask() extracts the best-scoring tiles
in one MSB-down pass.

Scoring: for each facing, shift every enemy-class mask BACKWARD along the
facing k=1..3 steps with wall clipping; tiles that survive are placements
whose forward ray hits that enemy at range k. Score is discounted with range
(gunners can't shoot over buildings, so adjacency is king).
"""

NUM_PLANES = 8
MAX_SCORE = (1 << NUM_PLANES) - 1

# enemy class -> base placement value (hit at range 1)
# range discount ~0.9^k like Pantheon
RAY_STEPS = 3
DISCOUNT = (1.0, 0.9, 0.81)


def add_const(planes, c, mask):
    """Add constant c to every tile in mask (ripple-carry over planes)."""
    if not mask or c <= 0:
        return
    i = 0
    while c and i < NUM_PLANES:
        if c & 1:
            carry = planes[i] & mask
            planes[i] ^= mask
            j = i + 1
            while carry and j < NUM_PLANES:
                new_carry = planes[j] & carry
                planes[j] ^= carry
                carry = new_carry
                j += 1
        c >>= 1
        i += 1


def argmax_mask(planes, cands):
    """(best_score, mask_of_best_tiles) among cands; (0, 0) if none."""
    if not cands:
        return 0, 0
    best = 0
    cur = cands
    for i in range(NUM_PLANES - 1, -1, -1):
        t = cur & planes[i]
        if t:
            cur = t
            best |= 1 << i
    return best, cur


def gunner_planes(mi, class_masks, valid_mask):
    """Per-facing plane stacks for gunner placements.

    class_masks: list of (value, enemy_mask). Returns {facing_key: planes}
    with facing_key in 'E','W','N','S' — the direction the built gunner faces.
    A placement facing E hits targets to its EAST, so target masks are shifted
    WEST (backward) onto placement tiles.
    """
    # 2.3: facing is 8-way. Diagonal rays reach 2 steps (d^2=8 <= 13; a 3rd
    # step is 18 > 13) — the angles that cardinal-thinking walls don't deny.
    shifts_back = {
        'E': (mi.west, 3), 'W': (mi.east, 3),
        'N': (mi.south, 3), 'S': (mi.north, 3),
        'NE': (lambda m: mi.south(mi.west(m)), 2),
        'NW': (lambda m: mi.south(mi.east(m)), 2),
        'SE': (lambda m: mi.north(mi.west(m)), 2),
        'SW': (lambda m: mi.north(mi.east(m)), 2),
    }
    out = {}
    nw = ~mi.walls
    for fk, (back, steps) in shifts_back.items():
        planes = [0] * NUM_PLANES
        for value, emask in class_masks:
            if not emask:
                continue
            s = emask
            for k in range(steps):
                s = back(s) & nw
                if not s:
                    break
                v = int(value * DISCOUNT[k])
                if v <= 0:
                    continue
                add_const(planes, v, s & valid_mask)
        out[fk] = planes
    return out


def best_placement(mi, class_masks, valid_mask):
    """(score, x, y, facing_key) of the best gunner placement, or None."""
    stacks = gunner_planes(mi, class_masks, valid_mask)
    best = None
    for fk, planes in stacks.items():
        score, mask = argmax_mask(planes, valid_mask)
        if score > 0 and mask:
            lsb = mask & -mask
            x, y = mi.xy(lsb)
            if best is None or score > best[0]:
                best = (score, x, y, fk)
    return best
