"""Deterministic check for the production-legal v18 siege stand."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, Position

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_siege_stand"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_siege_stand", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)

class Controller:
    def __init__(self): self.moved = None
    def get_position(self): return Position(2, 2)
    def get_global_resources(self): return 100
    def can_build_gunner(self, position, direction): return False
    def can_move(self, direction): return True
    def move(self, direction): self.moved = direction

def test_attacker_steps_behind_occupied_planned_seat():
    player = BOT.Player()
    player.mapPf.enemyCorePos = Position(4, 2)
    player.mapPf.teamCore = Position(0, 2)
    player.findGunnerSpot = lambda _: (Position(2, 2), Direction.EAST)
    ct = Controller()
    player.runAttack(ct)
    assert ct.moved == Direction.WEST

if __name__ == "__main__":
    test_attacker_steps_behind_occupied_planned_seat()
