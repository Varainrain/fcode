"""Map-symmetry prediction (Khaos blueprint Tier A, section 3).

Florent maps are symmetric by reflection or rotation. By comparing observed
static terrain (wall / ore / empty) against its mirror under each hypothesis we
eliminate the inconsistent ones, then predict the enemy core corner from the
surviving symmetry. Default to ROTATIONAL while ambiguous (Khaos default).

fullMap tile codes (from main.py):
  -1 unseen · 0 empty/passable · 1 ore · 2 wall · 3 building/unpassable(dynamic)

Only codes {0,1,2} are static terrain we can trust for symmetry; code 3 hides
the underlying terrain (a harvester sits on ore), so we skip those tiles.
"""

# symmetry ids, in preference order (rotational first, Khaos default)
ROTATIONAL = 0  # 180 rotation
HORIZONTAL = 1  # flip x
VERTICAL = 2    # flip y
_ALL = (ROTATIONAL, HORIZONTAL, VERTICAL)


def _terrain(code: int) -> int:
    """Collapse a fullMap code to a static-terrain class, or -1 if unknown."""
    # wall stays wall; ore vs empty are the two passable classes.
    if code == 2:
        return 2
    if code == 1:
        return 1
    if code == 0:
        return 0
    return -1  # -1 unseen or 3 building -> terrain unknown


def _mirror(x: int, y: int, w: int, h: int, sym: int):
    if sym == ROTATIONAL:
        return w - 1 - x, h - 1 - y
    if sym == HORIZONTAL:
        return w - 1 - x, y
    return x, h - 1 - y  # VERTICAL


def _core_corner(cx: int, cy: int, w: int, h: int, sym: int):
    """Predicted enemy core top-left corner for a 2x2 core mirrored under sym."""
    if sym == ROTATIONAL:
        return w - 2 - cx, h - 2 - cy
    if sym == HORIZONTAL:
        return w - 2 - cx, cy
    return cx, h - 2 - cy  # VERTICAL


class SymmetryTracker:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.alive = list(_ALL)          # surviving hypotheses
        self._ver = -1                   # struct_version this was computed at
        self._core = None                # cached (cx, cy) our core corner

    def update(self, full_map, struct_version: int, core_corner) -> None:
        """Recompute survivors when the shared structural map changed.

        Cheap: <=900 tiles x 3 symmetries, only on struct_version change.
        """
        if core_corner is not None:
            self._core = (core_corner.x, core_corner.y)
        if struct_version == self._ver and len(self.alive) <= 1:
            return  # already resolved, nothing new can help
        if struct_version == self._ver:
            return
        self._ver = struct_version
        w, h = self.w, self.h
        alive = []
        for sym in self.alive:
            ok = True
            for x in range(w):
                col = full_map[x]
                for y in range(h):
                    t = _terrain(col[y])
                    if t < 0:
                        continue
                    mx, my = _mirror(x, y, w, h, sym)
                    mt = _terrain(full_map[mx][my])
                    if mt < 0:
                        continue
                    if t != mt:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                alive.append(sym)
        # never let noise eliminate everything; keep rotational as a floor
        self.alive = alive if alive else [ROTATIONAL]

    def resolved(self) -> bool:
        return len(self.alive) == 1

    def best(self) -> int:
        return self.alive[0] if self.alive else ROTATIONAL

    def enemy_core(self, core_corner):
        """Best-guess enemy core corner (Position-like via factory in caller)."""
        cx, cy = core_corner.x, core_corner.y
        return _core_corner(cx, cy, self.w, self.h, self.best())

    def enemy_core_candidates(self, core_corner):
        """All surviving enemy-core corners, most-likely first (as (x,y))."""
        cx, cy = core_corner.x, core_corner.y
        seen = set()
        out = []
        for sym in self.alive:
            c = _core_corner(cx, cy, self.w, self.h, sym)
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out
