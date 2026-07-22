"""Bitmask map-info layer (Pantheon/Khaos rebuild).

The whole map lives in Python big-int masks: bit n = x + y*W. Geometric
neighbour expansion is 4 shifts; derived masks (threat, placeable, frontier)
are boolean algebra over whole boards. On <=30x30 maps a board is <=900 bits.

Static knowledge (seen/walls/ore) accumulates and is shared through the comm
store with the same 12-bit tile protocol botv2 uses (slots 1..6, 16 tiles per
broadcast, rotation keyed on slot 0's spawn counter).

>>> m = MapInfo(4, 3)
>>> b = m.bit(1, 1)
>>> sorted(m.xy(t) for t in m.iter_bits(m.expand(b) & ~b))
[(0, 1), (1, 0), (1, 2), (2, 1)]
>>> m.xy(m.east(b))
(2, 1)
>>> m.east(m.bit(3, 1))  # east edge does not wrap
0
"""

from fcode import Direction, EntityType, Environment, Position

DIR_DELTA = {
    Direction.NORTH: (0, -1), Direction.SOUTH: (0, 1),
    Direction.EAST: (1, 0), Direction.WEST: (-1, 0),
}

# tile type codes shared through the store (identical to botv2)
T_EMPTY, T_ORE, T_WALL, T_BLOCK = 0, 1, 2, 3

GUNNER_RAY = 3      # threat approximation: gunner cross length
SENT_BAND = 5       # sentinel band length (3 wide)


class MapInfo:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.n = w * h
        self.board = (1 << self.n) - 1
        col0 = 0
        for y in range(h):
            col0 |= 1 << (y * w)
        self.not_col0 = self.board & ~col0
        self.not_colL = self.board & ~(col0 << (w - 1))

        # accumulated static knowledge
        self.seen = 0
        self.walls = 0
        self.ore = 0
        self.blocked = 0        # non-walkable buildings (shared, any team)
        self.struct_version = 0

        # remembered point features (local to this unit, refreshed on sight)
        self.enemy_turrets = {}   # (x,y) -> 'G' | 'S'
        self.enemy_buildings = {}  # (x,y) -> EntityType
        self.own_harvesters = {}   # (x,y) -> True
        self.own_turrets = {}      # (x,y) -> True (death detection)
        self.turret_losses = []    # tiles where an own turret just died
        self._threat_cache = (None, 0)

        # per-turn dynamic masks
        self.own_bots = 0
        self.enemy_bots = 0
        self.own_conveyors = 0
        self.own_barriers = 0   # break-walkable at cost (Pantheon 15)
        self.own_loaded = 0     # own conveyors holding a stack (jam-avoid)
        # remembered facings of own conveyors: (x,y) -> (dx,dy) output delta
        self.own_conv_facing = {}

        # outgoing share queue: list of (x, y, code)
        self.out_tiles = []
        # optional hook: called (x, y, blocking) on structural changes so the
        # chokepoint analyzer can invalidate incrementally
        self.on_block_change = None

    # ---- geometry ----
    def bit(self, x: int, y: int) -> int:
        return 1 << (x + y * self.w)

    def xy(self, single_bit: int):
        n = single_bit.bit_length() - 1
        return n % self.w, n // self.w

    def east(self, m):
        return (m << 1) & self.not_col0

    def west(self, m):
        return (m >> 1) & self.not_colL

    def south(self, m):
        return (m << self.w) & self.board

    def north(self, m):
        return m >> self.w

    def expand(self, m):
        return m | self.east(m) | self.west(m) | self.south(m) | self.north(m)

    def iter_bits(self, m):
        while m:
            lsb = m & -m
            yield lsb
            m ^= lsb

    # ---- derived masks ----
    def passable(self):
        """Tiles a builder could stand on (unknown treated optimistically)."""
        return self.board & ~self.walls & ~self.blocked

    def threat(self):
        """Soft-threat mask from remembered enemy turrets (facing unknown:
        gunner = cardinal cross len 3, sentinel = 3-wide bands len 5)."""
        key = tuple(sorted(self.enemy_turrets.items()))
        cached, ver = self._threat_cache
        if cached is not None and ver == key:
            return cached
        t = 0
        shifts = (self.east, self.west, self.north, self.south)
        for (x, y), kind in self.enemy_turrets.items():
            b = self.bit(x, y)
            if kind == 'G':
                for shift in shifts:
                    ray = b
                    for _ in range(GUNNER_RAY):
                        ray = shift(ray) & ~self.walls
                        t |= ray
            else:
                t |= self.expand(b)
                for shift in shifts:
                    ray = b
                    acc = 0
                    for _ in range(SENT_BAND):
                        ray = shift(ray) & ~self.walls
                        acc |= ray
                    t |= self.expand(acc)  # widen the ray into a 3-wide band
        t &= self.board
        self._threat_cache = (t, key)
        return t

    def frontier(self):
        """Seen tiles adjacent to unseen ones — exploration targets."""
        unseen = self.board & ~self.seen
        return self.expand(unseen) & self.seen & ~self.walls

    # ---- knowledge updates ----
    def note_tile(self, x, y, code, share=True):
        b = self.bit(x, y)
        old_wall = self.walls & b
        old_block = self.blocked & b
        newly = not (self.seen & b)
        self.seen |= b
        if code == T_WALL:
            self.walls |= b
        elif code == T_BLOCK:
            self.blocked |= b
        else:
            changed = old_block != 0
            self.blocked &= ~b
            if code == T_ORE:
                self.ore |= b
            if changed:
                self.struct_version += 1
                if self.on_block_change:
                    self.on_block_change(x, y, False)
        if (code in (T_WALL, T_BLOCK)) and not (old_wall or old_block):
            self.struct_version += 1
            if self.on_block_change:
                self.on_block_change(x, y, True)
        if share and (newly or (code == T_BLOCK) != bool(old_block)):
            self.out_tiles.append((x, y, code))
            if len(self.out_tiles) > 96:
                del self.out_tiles[:32]

    def update_vision(self, ct):
        """Per-turn scan: static tiles into masks, dynamic entities rebuilt.

        Vision-delta optimization (Pantheon update_move): env is immutable, so
        for already-seen tiles we skip get_tile_env entirely — walls skip ALL
        queries (nothing can stand on them), other seen tiles derive env from
        the ore mask and only pay the building-id query."""
        my_team = ct.get_team()
        get_env = ct.get_tile_env
        get_bid = ct.get_tile_building_id
        note = self.note_tile
        self.own_bots = 0
        self.enemy_bots = 0
        self.own_conveyors = 0
        self.own_barriers = 0
        self.own_loaded = 0  # own conveyors currently holding a stack
        get_stored = ct.get_stored_resource
        WALKABLE = (EntityType.CONVEYOR, EntityType.SPLITTER)
        seen = self.seen
        walls = self.walls
        ore = self.ore
        for tile in ct.get_nearby_tiles():
            x, y = tile.x, tile.y
            b = 1 << (x + y * self.w)
            if seen & b:
                if walls & b:
                    continue  # immutable, uninhabitable: zero queries
                env = (Environment.ORE_TITANIUM if ore & b
                       else Environment.EMPTY)
            else:
                env = get_env(tile)
            if env == Environment.WALL:
                note(x, y, T_WALL)
                continue
            bid = get_bid(tile)
            if bid is None:
                note(x, y, T_ORE if env == Environment.ORE_TITANIUM else T_EMPTY)
                self.enemy_buildings.pop((x, y), None)
                self.enemy_turrets.pop((x, y), None)
                self.own_harvesters.pop((x, y), None)
                if self.own_turrets.pop((x, y), None):
                    self.turret_losses.append((x, y))
                self.own_conv_facing.pop((x, y), None)
                continue
            etype = ct.get_entity_type(bid)
            team = ct.get_team(bid)
            if etype in WALKABLE:
                note(x, y, T_ORE if env == Environment.ORE_TITANIUM else T_EMPTY)
                if team == my_team:
                    self.own_conveyors |= self.bit(x, y)
                    if get_stored(bid) is not None:
                        self.own_loaded |= self.bit(x, y)
                    if etype == EntityType.CONVEYOR:
                        d = DIR_DELTA.get(ct.get_direction(bid))
                        if d is not None:
                            self.own_conv_facing[(x, y)] = d
                else:
                    self.enemy_buildings[(x, y)] = etype
                continue
            note(x, y, T_BLOCK)
            if team != my_team:
                self.enemy_buildings[(x, y)] = etype
                if etype == EntityType.GUNNER:
                    self.enemy_turrets[(x, y)] = 'G'
                elif etype == EntityType.SENTINEL:
                    self.enemy_turrets[(x, y)] = 'S'
            else:
                self.enemy_buildings.pop((x, y), None)
                if etype == EntityType.HARVESTER:
                    self.own_harvesters[(x, y)] = True
                elif etype == EntityType.BARRIER:
                    self.own_barriers |= self.bit(x, y)
                elif etype in (EntityType.GUNNER, EntityType.SENTINEL,
                               EntityType.LAUNCHER):
                    self.own_turrets[(x, y)] = True
        for uid in ct.get_nearby_units():
            if ct.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            p = ct.get_position(uid)
            if ct.get_team(uid) == my_team:
                self.own_bots |= self.bit(p.x, p.y)
            else:
                self.enemy_bots |= self.bit(p.x, p.y)

    # ---- comm store share (botv2 12-bit protocol, slots 1..6) ----
    def share(self, ct, my_num: int, core: Position):
        spawn_count = ct.read_store(0)
        if spawn_count <= 0 or my_num < 1 or core is None:
            return
        if ct.get_current_round() % spawn_count + 1 != my_num:
            return
        self.out_tiles.sort(
            key=lambda t: abs(t[0] - core.x) + abs(t[1] - core.y),
            reverse=True)
        combined = 0
        for i in range(16):
            if i < len(self.out_tiles):
                x, y, code = self.out_tiles[i]
                val = ((x & 0x1F) << 7) | ((y & 0x1F) << 2) | (code & 0x3)
            else:
                val = 0xFFF
            combined = (combined << 12) | val
        for i in range(6):
            ct.write_store(6 - i, (combined >> (32 * i)) & 0xFFFFFFFF)
        del self.out_tiles[:16]

    def absorb(self, ct):
        combined = 0
        for i in range(1, 7):
            combined = (combined << 32) | ct.read_store(i)
        for i in range(16):
            val = (combined >> (12 * (15 - i))) & 0xFFF
            if val == 0xFFF:
                continue
            x = (val >> 7) & 0x1F
            y = (val >> 2) & 0x1F
            if x >= self.w or y >= self.h:
                continue
            self.note_tile(x, y, val & 0x3, share=False)
            self.out_tiles = [t for t in self.out_tiles
                              if not (t[0] == x and t[1] == y)]


if __name__ == "__main__":
    import doctest
    doctest.testmod()
