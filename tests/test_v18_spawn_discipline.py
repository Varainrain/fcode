"""Deterministic checks for congestion-aware spawning on the v18 chassis."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_spawn_discipline"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_spawn_discipline", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


def test_opening_four_ignore_congestion():
    assert BOT.extraSpawnAllowed(0, 0, 20)
    assert BOT.extraSpawnAllowed(3, 0, 20)


def test_extra_spawn_stops_at_six_and_resumes_after_dispersal():
    assert BOT.extraSpawnAllowed(4, 361, 5)
    assert not BOT.extraSpawnAllowed(4, 361, 6)
    assert BOT.extraSpawnAllowed(4, 361, 4)
    assert not BOT.extraSpawnAllowed(4, 360, 0)


if __name__ == "__main__":
    test_opening_four_ignore_congestion()
    test_extra_spawn_stops_at_six_and_resumes_after_dispersal()
