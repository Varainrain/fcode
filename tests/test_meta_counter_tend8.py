"""Tests for the duel-length eight-heal countergun maintenance budget."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_meta_counter_tend8"
PARENT = ROOT / "bots" / "meta-generalist-v1"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("meta_counter_tend8", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class TendController:
    def __init__(self):
        self.heals = 0

    def is_in_vision(self, pos): return False
    def get_position(self, entity_id=None): return Position(3, 3)
    def get_hp(self, entity_id=None): return 20
    def get_max_hp(self, entity_id=None): return 40
    def can_heal(self, pos): return True
    def heal(self, pos): self.heals += 1


def test_maintenance_covers_one_symmetric_gunner_duel():
    player = BOT.Player()
    player._friendly_covering_gunner = lambda ct, threat: 7
    fallbacks = []
    player._heal_or_approach_core = lambda ct, pos: fallbacks.append(pos)
    ct = TendController()
    for _ in range(BOT.COUNTER_TEND_HEAL_LIMIT + 2):
        player._run_home_defense(ct, Position(3, 4), Position(3, 1))
    assert ct.heals == BOT.COUNTER_TEND_HEAL_LIMIT == 8
    assert len(fallbacks) == 2


def test_scope_and_no_fingerprints():
    for name in ("initialSpawning.py", "mapPathfinding.py", "symmetry.py"):
        assert (BOT_DIR / name).read_bytes() == (PARENT / name).read_bytes()
    source = (BOT_DIR / "main.py").read_text(encoding="utf-8").lower()
    for fingerprint in ("sweden.map", "string.map", "bridge.map", "ijti"):
        assert fingerprint not in source


if __name__ == "__main__":
    test_maintenance_covers_one_symmetric_gunner_duel()
    test_scope_and_no_fingerprints()
