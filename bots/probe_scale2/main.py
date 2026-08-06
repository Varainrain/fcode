"""probe_scale2 - does the 2.3.6 cost scale track buildings ALIVE or buildings EVER BUILT?

One builder. Rounds 0-40: build a conveyor whenever possible. Rounds 40+:
destroy its own conveyors one per turn. If scale% falls back as they die the
term is "alive"; if it stays put the term is cumulative and building is a
permanent tax on every future purchase.
"""
from fcode import Controller, Direction, EntityType, Position

LOG = "/tmp/scale_probe2.csv"
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]


class Player:
    def __init__(self):
        self.spawned = 0
        self.mine = []

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
                fh.write("%d,%d,%.3f,%d\n" % (
                    ct.get_current_round(), ct.get_unit_count(),
                    ct.get_scale_percent(), ct.get_gunner_cost()))
        except Exception:
            pass

    def runBuilder(self, ct: Controller) -> None:
        myLoc = ct.get_position()
        rnd = ct.get_current_round()
        if rnd < 40:
            for d in CARDINALS:
                spot = myLoc.add(d)
                try:
                    if ct.can_build_conveyor(spot, d):
                        ct.build_conveyor(spot, d)
                        self.mine.append(spot)
                        return
                except Exception:
                    pass
            for d in CARDINALS:
                try:
                    if ct.can_move(d):
                        ct.move(d)
                        return
                except Exception:
                    pass
            return
        for spot in list(self.mine):
            try:
                if ct.can_destroy(spot):
                    ct.destroy(spot)
                    self.mine.remove(spot)
                    return
            except Exception:
                pass
        for d in CARDINALS:
            try:
                if ct.can_move(d):
                    ct.move(d)
                    return
            except Exception:
                pass
