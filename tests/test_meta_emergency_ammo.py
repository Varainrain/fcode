from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bots" / "exp_meta_emergency_ammo"


def load_main():
    sys.path.insert(0, str(BOT))
    try:
        spec = importlib.util.spec_from_file_location("meta_ammo", BOT / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


META = load_main()


def test_emergency_conversion_preserves_reserve():
    assert META.emergency_ammo_conversion(0, 40, True) == 12
    assert META.emergency_ammo_conversion(7, 100, True) == 13
    assert META.emergency_ammo_conversion(20, 100, True) == 0
    assert META.emergency_ammo_conversion(0, 100, False) == 0


def test_only_main_and_readme_change():
    parent = ROOT / "bots" / "exp_trans_40"
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT / name).read_bytes() == (parent / name).read_bytes()


if __name__ == "__main__":
    test_emergency_conversion_preserves_reserve()
    test_only_main_and_readme_change()
    print("emergency ammo tests passed")
