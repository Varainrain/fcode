"""mapforge — compile .map26 files (ic3d's stress-suite idea, 2026-08-10).

Wire format (verified by roundtrip against the league pool):
  field1 varint W, field2 varint H,
  field3 message per row {field1: bytes, one per tile: 0 empty/1 wall/2 ore},
  field4 message per core {field1 id, field2 team, field3 {field1 x, field2 y}}
League maps are 180-degree rotationally symmetric; forge() enforces it by
mirroring tiles and placing core B at the rotation of core A (2x2 footprint:
Bx = W-2-Ax, By = H-2-Ay).

Suite (maps_stress/, NEVER in maps/ -- the ship gate stays league-pure):
  knife     10x10 cores d8   -- fjordgate-extreme rush bench
  fortress  24x24 walled pockets, 2 gates -- bounced-siege bench
  goldrush  30x20 ore in far fields -- harvester-race bench (the h21 war)
  corner    20x20 cores at map corners -- seal/CB geometry at edges
  maze      24x24 corridor walls -- pathing + TLE bench
  barren    22x22 8 ore tiles total -- poverty/eco-efficiency bench
"""
import sys, os


def _varint(n):
    out = b''
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            out += bytes([b])
            return out


def _tag(field, wtype):
    return _varint((field << 3) | wtype)


def _ld(field, payload):
    return _tag(field, 2) + _varint(len(payload)) + payload


def _vf(field, val):
    return _tag(field, 0) + _varint(val)


def compile_map(W, H, tiles, coreA):
    """tiles: dict (x,y)->1|2 (empty omitted). coreA: (x,y) top-left of 2x2.
    Core B and tile symmetry are generated automatically."""
    ax, ay = coreA
    bx, by = W - 2 - ax, H - 2 - ay
    grid = [[0] * W for _ in range(H)]
    for (x, y), v in tiles.items():
        grid[y][x] = v
        grid[H - 1 - y][W - 1 - x] = v          # 180-degree symmetry
    for cx, cy in ((ax, ay), (bx, by)):         # clear core footprints
        for dx in (0, 1):
            for dy in (0, 1):
                grid[cy + dy][cx + dx] = 0
    out = _vf(1, W) + _vf(2, H)
    for y in range(H):
        out += _ld(3, _ld(1, bytes(grid[y])))
    for cid, team, (cx, cy) in ((1, 0, (ax, ay)), (2, 1, (bx, by))):
        pos = _vf(1, cx) + _vf(2, cy)
        out += _ld(4, _vf(1, cid) + _vf(2, team) + _ld(3, pos))
    return out


def roundtrip_check():
    sys.path.insert(0, '.')
    import replay_stats as rs
    data = open('maps/snowflake.map26', 'rb').read()
    top = rs.walk(data)
    W, H = top[(1, 'v')][0], top[(2, 'v')][0]
    tiles = {}
    for y, row in enumerate(top[(3, 'm')]):
        for x, b in enumerate(rs.walk(row)[(1, 'm')][0]):
            if b:
                tiles[(x, y)] = b
    cA = rs.walk(rs.walk(top[(4, 'm')][0])[(3, 'm')][0])
    rebuilt = compile_map(W, H, tiles, (cA[(1, 'v')][0], cA[(2, 'v')][0]))
    ok = rebuilt == data
    print('roundtrip snowflake:', 'BYTE-IDENTICAL' if ok else f'DIFFERS ({len(rebuilt)} vs {len(data)})')
    return ok


def suite():
    os.makedirs('maps_stress', exist_ok=True)
    maps = {}

    # knife: 10x10, cores (1,1)/(7,7), ore hugging each core
    maps['knife'] = (10, 10, {(0, 3): 2, (3, 0): 2, (4, 1): 2}, (1, 1))

    # fortress: 24x24, cores walled into pockets with two 1-tile gates
    t = {}
    ax, ay = 3, 10
    for x in range(ax - 2, ax + 5):
        for y in (ay - 3, ay + 4):
            if 0 <= x < 24:
                t[(x, y)] = 1
    for y in range(ay - 3, ay + 5):
        t[(ax + 4, y)] = 1
    del t[(ax + 4, ay)]                          # east gate
    del t[(ax, ay - 3)]                          # north gate
    for i in range(4):
        t[(1, 4 + i)] = 2
        t[(8 + i, 2)] = 2
    maps['fortress'] = (24, 24, t, (ax, ay))

    # goldrush: 30x20, cores centre-ish, rich ore fields in far corners
    t = {}
    for x in range(1, 6):
        for y in range(1, 4):
            if (x + y) % 2 == 0:
                t[(x, y)] = 2
    for x in range(1, 4):
        for y in range(15, 18):
            if (x + y) % 2 == 1:
                t[(x, y)] = 2
    maps['goldrush'] = (30, 20, t, (12, 9))

    # corner: 20x20, cores jammed into opposite corners
    maps['corner'] = (20, 20, {(4, 0): 2, (0, 4): 2, (5, 5): 2}, (0, 0))

    # maze: 24x24, staggered corridor walls
    t = {}
    for i, x in enumerate(range(5, 20, 4)):
        for y in range(0 if i % 2 else 6, 18 if i % 2 else 24):
            t[(x, y)] = 1
    t[(2, 4)] = 2
    t[(3, 20)] = 2
    maps['maze'] = (24, 24, t, (2, 10))

    # barren: 22x22, exactly 4 ore per side
    maps['barren'] = (22, 22, {(0, 6): 2, (6, 0): 2, (10, 3): 2, (3, 10): 2}, (2, 2))

    for name, (W, H, tiles, coreA) in maps.items():
        data = compile_map(W, H, tiles, coreA)
        path = f'maps_stress/{name}.map26'
        open(path, 'wb').write(data)
        print(f'{name:9} {W}x{H} -> {path} ({len(data)}b)')


if __name__ == '__main__':
    if roundtrip_check():
        suite()
    else:
        sys.exit(1)
