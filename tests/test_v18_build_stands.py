"""Deterministic checks for production-legal build stands on v18."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, Position


ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_build_stands"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_build_stands", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)


class StepController:
    def __init__(self):
        self.position = Position(2, 2)
        self.moved = None

    def get_position(self): return self.position
    def can_move(self, direction): return True
    def move(self, direction): self.moved = direction


class AttackController(StepController):
    def get_global_resources(self): return 100
    def can_build_gunner(self, position, direction): return False


def test_step_off_prefers_behind_gun_and_toward_core_for_ore():
    player = BOT.Player()
    ct = StepController()
    assert player.stepOffBuildTile(ct, Position(4, 2), preferFarther=True)
    assert ct.moved == Direction.WEST
    ct.moved = None
    assert player.stepOffBuildTile(ct, Position(0, 2), preferFarther=False)
    assert ct.moved == Direction.WEST


def test_attacker_on_gun_seat_does_not_retreat_home():
    player = BOT.Player()
    player.mapPf.enemyCorePos = Position(4, 2)
    player.mapPf.teamCore = Position(0, 2)
    player.findGunnerSpot = lambda _: (Position(2, 2), Direction.EAST)
    ct = AttackController()
    player.runAttack(ct)
    assert ct.moved == Direction.WEST


if __name__ == "__main__":
    test_step_off_prefers_behind_gun_and_toward_core_for_ore()
    test_attacker_on_gun_seat_does_not_retreat_home()
