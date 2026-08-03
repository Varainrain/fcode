"""Deterministic ordering checks for attack-first immediate pressure."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v20_opportunistic_pressure"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location(
    "v20_opportunistic_pressure", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_safer_immediate_pressure_plan_wins_deterministically():
    safe = BOT.immediatePressureScore(0, Position(4, 2), Direction.EAST)
    covered = BOT.immediatePressureScore(1, Position(1, 1), Direction.NORTH)
    assert safe < covered
    assert BOT.immediatePressureScore(
        0, Position(2, 3), Direction.SOUTH) < BOT.immediatePressureScore(
        0, Position(3, 2), Direction.NORTH)


if __name__ == "__main__":
    test_safer_immediate_pressure_plan_wins_deterministically()
