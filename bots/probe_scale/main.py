"""probe_scale - measures the 2.3.6 cost-scaling formula.

Core spawns exactly ONE builder and never spawns again. The builder builds a
conveyor every turn it can. If scale% tracks buildings as well as units, the
curve rises ~1 per conveyor with the unit count pinned at 2.
"""
from fcode import Controller, Direction, EntityType, Environment, Position

LOG = "/tmp/scale_probe.csv"


class Player:
    def __init__(self):
        self.spawned = 0
        self.built = 0

    def run(self, ct: Controller) -> None:
        etype = ct.get_entity_type()
        if etype == EntityType.CORE:
            self.runCore(ct)
        elif etype == EntityType.BUILDER_BOT:
            self.runBuilder(ct)

    def runCore(self, ct: Controller) -> None:
        if self.spawned < 1:
            for tile in ct.get_nearby_tiles():
                if ct.can_spawn(tile):
                    ct.spawn_builder(tile)
                    self.spawned += 1
                    break
        try:
            with open(LOG, "a") as fh:
                fh.write("%d,%d,%.3f,%d,%d,%d\n" % (
                    ct.get_current_round(), ct.get_unit_count(),
                    ct.get_scale_percent(), ct.get_gunner_cost(),
                    ct.get_conveyor_cost(), ct.get_global_resources()))
        except Exception:
            pass

    def runBuilder(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
            spot = myLoc.add(d)
            try:
                if ct.can_build_conveyor(spot, d):
                    ct.build_conveyor(spot, d)
                    self.built += 1
                    return
            except Exception:
                pass
        for d in (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST):
            try:
                if ct.can_move(d):
                    ct.move(d)
                    return
            except Exception:
                pass
