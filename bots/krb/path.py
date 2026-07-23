"""Bitmask pathfinding (Pantheon/Khaos rebuild).

All searches operate on MapInfo big-int masks. The Dial's variant runs in
REVERSE from a target mask with a circular array of frontier bitmasks as the
bucket queue (Khaos figure 12): plain step cost 1, stepping into soft threat
+THREAT, so paths detour around enemy turret envelopes unless forced.

dist_field() unrolls the same search into a per-tile int list for gradient
consumers (conveyor routing).
"""

THREAT_EXTRA = 12          # entering a threat tile costs 1 + THREAT_EXTRA
DIAG_EXTRA = 5             # 2.3 diagonal firing lane: lean out, don't detour
BARRIER_EXTRA = 14         # entering an OWN barrier costs 1 + 14 (Pantheon 15:
                           # the mover destroys it, spending its action)
RING = THREAT_EXTRA + BARRIER_EXTRA + 3  # ring must exceed max edge cost


def next_step(mi, start_xy, targets_mask, avoid_mask=0, max_iters=None):
    """Reverse Dial's from targets; returns (dx, dy) for the best first step
    from start, or None if unreachable. avoid_mask tiles are impassable.
    Own barriers are break-walkable at +BARRIER_EXTRA."""
    barriers = mi.own_barriers & ~avoid_mask
    passable = (mi.passable() | barriers) & ~avoid_mask
    targets = targets_mask & mi.board
    if not targets:
        return None
    threat = mi.threat()
    diagm = mi.threat_diag() & ~threat   # cardinal threat cost dominates
    sx, sy = start_xy
    sbit = mi.bit(sx, sy)
    nbrs = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = sx + dx, sy + dy
        if 0 <= nx < mi.w and 0 <= ny < mi.h:
            nbrs.append((mi.bit(nx, ny), dx, dy))
    nbr_all = 0
    for b, _, _ in nbrs:
        nbr_all |= b
    # the start tile itself counts as reachable ground for the wavefront
    passable |= sbit | targets

    ring = [0] * RING
    ring[0] = targets
    visited = 0
    found = {}
    if max_iters is None:
        max_iters = (mi.w + mi.h) * (THREAT_EXTRA + 1) + 5
    for dist in range(max_iters):
        cur = ring[dist % RING] & ~visited
        ring[dist % RING] = 0
        if not cur:
            if not any(ring):
                break
            continue
        visited |= cur
        hit = cur & nbr_all
        if hit:
            for b, dx, dy in nbrs:
                if (hit & b) and b not in found:
                    found[b] = dist
            if len(found) == len(nbrs):
                break
        nxt = mi.expand(cur) & passable & ~visited
        for extra, mask in (
                (0, ~threat & ~diagm & ~barriers),
                (THREAT_EXTRA, threat & ~barriers),
                (DIAG_EXTRA, diagm & ~barriers),
                (BARRIER_EXTRA, barriers & ~threat & ~diagm),
                (THREAT_EXTRA + BARRIER_EXTRA, barriers & threat),
                (DIAG_EXTRA + BARRIER_EXTRA, barriers & diagm)):
            m = nxt & mask
            if m:
                ring[(dist + 1 + extra) % RING] |= m
    if not found:
        return None
    best = min(found.items(), key=lambda kv: kv[1])[0]
    for b, dx, dy in nbrs:
        if b == best:
            return (dx, dy)
    return None


def dist_field(mi, targets_mask, avoid_mask=0):
    """Full-map cost-to-target list indexed [x + y*w]; 4096 = unreachable."""
    barriers = mi.own_barriers & ~avoid_mask
    passable = (mi.passable() | barriers
                | (targets_mask & mi.board)) & ~avoid_mask
    threat = mi.threat()
    field = [4096] * mi.n
    ring = [0] * RING
    ring[0] = targets_mask & mi.board
    visited = 0
    max_iters = (mi.w + mi.h) * (THREAT_EXTRA + 1) + 5
    for dist in range(max_iters):
        cur = ring[dist % RING] & ~visited
        ring[dist % RING] = 0
        if not cur:
            if not any(ring):
                break
            continue
        visited |= cur
        m = cur
        while m:
            lsb = m & -m
            field[lsb.bit_length() - 1] = dist
            m ^= lsb
        nxt = mi.expand(cur) & passable & ~visited
        plain = nxt & ~threat & ~barriers
        hot = nxt & threat & ~barriers
        barr = nxt & barriers & ~threat
        both = nxt & barriers & threat
        if plain:
            ring[(dist + 1) % RING] |= plain
        if hot:
            ring[(dist + 1 + THREAT_EXTRA) % RING] |= hot
        if barr:
            ring[(dist + 1 + BARRIER_EXTRA) % RING] |= barr
        if both:
            ring[(dist + 1 + THREAT_EXTRA + BARRIER_EXTRA) % RING] |= both
    return field


def closest(mi, start_mask, candidates_mask, avoid_mask=0, max_steps=None):
    """Unweighted BFS over passable tiles; returns the candidate bit reached
    first (lowest bit as tiebreak) or 0."""
    passable = mi.passable() & ~avoid_mask
    front = start_mask & mi.board
    visited = front
    cands = candidates_mask & mi.board
    if front & cands:
        hit = front & cands
        return hit & -hit
    if max_steps is None:
        max_steps = mi.w + mi.h
    for _ in range(max_steps):
        front = mi.expand(front) & (passable | cands) & ~visited
        if not front:
            return 0
        visited |= front
        hit = front & cands
        if hit:
            return hit & -hit
    return 0


def claims(mi, my_bit, others_mask, candidates_mask, max_steps=None):
    """Khaos claim partition: simultaneous competing floodfills. Returns the
    subset of candidates MY region reaches strictly first (ties -> others,
    keeping the claim conservative)."""
    passable = mi.passable()
    cands = candidates_mask & mi.board
    if not cands:
        return 0
    my_front = my_bit
    other_front = others_mask & mi.board
    claimed = my_front | other_front
    mine = my_front & cands
    cands &= ~other_front
    if max_steps is None:
        max_steps = mi.w + mi.h
    remaining = cands & ~mine
    for _ in range(max_steps):
        if not remaining or not (my_front or other_front):
            break
        other_front = mi.expand(other_front) & (passable | cands) & ~claimed
        claimed |= other_front
        remaining &= ~other_front
        my_front = mi.expand(my_front) & (passable | cands) & ~claimed
        claimed |= my_front
        mine |= my_front & remaining
        remaining &= ~my_front
    return mine
