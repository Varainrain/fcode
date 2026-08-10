"""Protocol and scope tests for the higher-reserve late route repair."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_waller_route_reserve"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("waller_route_reserve", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_reserve_is_the_only_parent_change():
    parent = ROOT / "bots" / "exp_waller_route_light"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (parent / name).read_bytes()
    expected = (parent / "main.py").read_text(encoding="utf-8").replace(
        "LATE_ROUTE_RESOURCE_FLOOR = 100",
        "LATE_ROUTE_RESOURCE_FLOOR = 200",
        1,
    )
    assert (BOT_DIR / "main.py").read_text(encoding="utf-8") == expected


def test_repair_preserves_a_real_combat_reserve():
    allowed = BOT.late_route_repair_allowed
    assert not allowed(BOT.LATE_ROUTE_REPAIR_START, 199, 1)
    assert allowed(BOT.LATE_ROUTE_REPAIR_START, 200, 1)
    assert not allowed(
        BOT.LATE_ROUTE_REPAIR_START, 500, BOT.LATE_ROUTE_MAX_LINKS + 1)


def test_no_fingerprints():
    source = "\n".join(
        (BOT_DIR / name).read_text(encoding="utf-8").lower()
        for name in ("main.py", "mapPathfinding.py")
    )
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_reserve_is_the_only_parent_change()
    test_repair_preserves_a_real_combat_reserve()
    test_no_fingerprints()
