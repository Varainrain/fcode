"""Deterministic check for the production-legal v18 harvest stand."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from fcode import Direction, Position

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bots" / "exp_v18_harvest_stand"
sys.path.insert(0, str(BOT_DIR))
spec = spec_from_file_location("v18_harvest_stand", BOT_DIR / "main.py")
BOT = module_from_spec(spec)
spec.loader.exec_module(BOT)

class Controller:
    def __init__(self): self.moved = None
    def is_in_vision(self, position): return True
    def get_tile_building_id(self, position): return None
    def get_global_resources(self): return 100
    def can_build_harvester(self, position): return False
    def get_position(self): return Position(1, 1)
    def can_move(self, direction): return True
    def move(self, direction): self.moved = direction

def test_builder_steps_off_ore_toward_core():
    player = BOT.Player()
    player.mapW = player.mapH = 3
    player.mapPf.teamCore = Position(0, 1)
    player.mapPf.fullMap = [[-1] * 3 for _ in range(3)]
    player.mapPf.fullMap[1][1] = 1
    player.mapPf.enemyTurretThreatenedTiles = lambda _: set()
    ct = Controller()
    assert player.harvestTask(ct, Position(1, 1), 0)
    assert ct.moved == Direction.WEST

if __name__ == "__main__":
    test_builder_steps_off_ore_toward_core()
