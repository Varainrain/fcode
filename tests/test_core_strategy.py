"""Deterministic protocol tests for the core-race experiments."""

from pathlib import Path
import importlib.util
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class Pos:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def read_varint(buf, index):
    value = 0
    shift = 0
    while True:
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7


def parse_map(path):
    buf = path.read_bytes()
    index = 0
    width = height = None
    rows = []
    cores = []
    while index < len(buf):
        tag, index = read_varint(buf, index)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, index = read_varint(buf, index)
            if field == 1:
                width = value
            elif field == 2:
                height = value
        elif wire == 2:
            length, index = read_varint(buf, index)
            payload = buf[index:index + length]
            index += length
            if field == 3:
                inner = 0
                _, inner = read_varint(payload, inner)
                row_length, inner = read_varint(payload, inner)
                rows.append(payload[inner:inner + row_length])
            elif field == 4:
                cores.append(parse_core(payload))
        else:
            raise AssertionError(f"unsupported map wire type {wire}")
    return width, height, rows, cores


def parse_core(payload):
    index = 0
    team = x = y = 0
    while index < len(payload):
        tag, index = read_varint(payload, index)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, index = read_varint(payload, index)
            if field == 1:
                team = value
        elif wire == 2:
            length, index = read_varint(payload, index)
            nested = payload[index:index + length]
            index += length
            inner = 0
            while inner < len(nested):
                nested_tag, inner = read_varint(nested, inner)
                nested_field, nested_wire = nested_tag >> 3, nested_tag & 7
                if nested_wire != 0:
                    break
                value, inner = read_varint(nested, inner)
                if nested_field == 1:
                    x = value
                elif nested_field == 2:
                    y = value
        else:
            raise AssertionError(f"unsupported core wire type {wire}")
    return team, x, y


def load_symmetry_module(bot_name):
    path = ROOT / "bots" / bot_name / "symmetry.py"
    spec = importlib.util.spec_from_file_location(f"{bot_name}_symmetry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_map_core_predictions(bot_name="exp_symmetry"):
    symmetry = load_symmetry_module(bot_name)
    checked = 0
    for path in sorted((ROOT / "maps").glob("*.map26")):
        width, height, rows, cores = parse_map(path)
        # map bytes: 0 empty, 1 wall, 2 ore. Bot map: 0 empty, 1 ore, 2 wall.
        translate = {0: 0, 1: 2, 2: 1}
        full_map = [
            [translate[rows[y][x]] for y in range(height)]
            for x in range(width)
        ]
        assert len(cores) == 2, path.name
        for source_index, target_index in ((0, 1), (1, 0)):
            _, source_x, source_y = cores[source_index]
            _, target_x, target_y = cores[target_index]
            tracker = symmetry.SymmetryTracker(width, height)
            tracker.update(full_map, 1, Pos(source_x, source_y))
            predicted = tracker.enemy_core(Pos(source_x, source_y))
            assert predicted == (target_x, target_y), (
                path.name, (source_x, source_y), predicted, (target_x, target_y),
                tracker.alive)
            checked += 1
    assert checked == 42


def test_stable_role_protocol(bot_name="exp_roles"):
    source = (ROOT / "bots" / bot_name / "main.py").read_text(encoding="utf-8")
    assert "SLOT_WALLER_ID = 8" in source
    assert "SLOT_SIEGER_1_ID = 9" in source
    assert "SLOT_SIEGER_2_ID = 10" in source
    assert "spawned_id + 1" in source
    assert "get_id() > 4" not in source
    assert "mySpawnIdx" not in source


def test_core_sniper_protocol(bot_name="exp_core_sniper"):
    source = (ROOT / "bots" / bot_name / "main.py").read_text(encoding="utf-8")
    assert "SIEGE_START = 45" in source
    assert "SIEGE_TITANIUM_FLOOR = 120" in source
    assert "ct.can_fire_from(" in source
    assert "ct.can_build_gunner(seat, facing)" in source
    assert "curScore += 1000" in source
    test_stable_role_protocol(bot_name)


def test_local_promotion_package(bot_name="core-sniper-v1"):
    required = {
        "main.py",
        "initialSpawning.py",
        "mapPathfinding.py",
        "symmetry.py",
    }
    bot_dir = ROOT / "bots" / bot_name
    for name in required:
        assert (ROOT / name).read_bytes() == (bot_dir / name).read_bytes(), name
    with zipfile.ZipFile(ROOT / "bot.zip") as archive:
        assert set(archive.namelist()) == required
        for name in required:
            assert archive.read(name) == (bot_dir / name).read_bytes(), name


def test_generalist_v2_protocol():
    test_all_map_core_predictions("generalist-v2")
    test_core_sniper_protocol("generalist-v2")


def test_generalist_v3_protocol():
    test_all_map_core_predictions("generalist-v3")
    test_core_sniper_protocol("generalist-v3")


if __name__ == "__main__":
    test_all_map_core_predictions()
    test_all_map_core_predictions("exp_roles")
    test_all_map_core_predictions("exp_core_sniper")
    test_all_map_core_predictions("core-sniper-v1")
    test_stable_role_protocol()
    test_core_sniper_protocol()
    test_core_sniper_protocol("core-sniper-v1")
    test_generalist_v2_protocol()
    test_generalist_v3_protocol()
    test_local_promotion_package()
    print("core strategy protocol tests passed")
