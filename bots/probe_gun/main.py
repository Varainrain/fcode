"""probe_gun - close the one number neither source settles: the scale increment
per GUNNER. The notebook cites +10% (Automata spec) and +20% (Alternative spec)
from two different documents and cannot say which engine is live.

Core spawns exactly one builder on round 0 (gated on the round, not on instance
state - earlier probes kept spawning because unit count, not the flag, was the
thing that moved). The builder walks clear of the core, then builds a gunner
every turn it can. Unit count is then fixed, so every scale change is a building.
"""
from fcode import Controller, Direction, EntityType, Position

LOG = "/tmp/gun_probe.csv"
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]


class Player:
    def run(self, ct: Controller) -> None:
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            if ct.get_current_round() == 0:
                for tile in ct.get_nearby_tiles():
                    if ct.can_spawn(tile):
                        ct.spawn_builder(tile)
                        break
            try:
                open(LOG, "a").write("%d,%d,%.3f,%d;" % (
                    ct.get_current_round(), ct.get_unit_count(),
                    ct.get_scale_percent(), ct.get_gunner_cost()))
            except Exception:
                pass
        elif et == EntityType.BUILDER_BOT:
            if ct.get_current_round() < 6:
                for d in CARDINALS:
                    if ct.can_move(d):
                        ct.move(d)
                        return
                return
            for d in CARDINALS:
                spot = ct.get_position().add(d)
                if ct.can_build_gunner(spot, d):
                    ct.build_gunner(spot, d)
                    return
            for d in CARDINALS:
                if ct.can_move(d):
                    ct.move(d)
                    return
