"""probe_launch - can a launcher throw an ENEMY builder bot, or only a friendly one?

The notebook says Pantheon flung enemy healers away from siege zones, and that
FCL launchers "can throw both friendly and enemy builder bots". This repo only
ever probe-verified throwing our OWN builders. The API docstring says "the
builder bot at bot_pos" without mentioning team, so it is genuinely ambiguous
and has to be measured.

Method: build a launcher near our own core and wait - enemy attackers come to
us. Every turn the launcher scans for builder bots in range and, for each,
records can_launch() and the result of actually calling launch(), tagged by
team. Friendly bots are the control: we already know that case works.

    fcode run probe_launch sub_v58 maps/hive.map26 --seed 1 --tle 10
    then read /tmp/launch_probe.txt
"""
from fcode import Controller, Direction, EntityType, Position

LOG = "/tmp/launch_probe.txt"
CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]


def note(text):
    try:
        open(LOG, "a").write(text + ";")
    except Exception:
        pass


class Player:
    def __init__(self):
        self.spawned = 0
        self.built = False
        self.tries = 0

    def run(self, ct: Controller) -> None:
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            if ct.get_current_round() == 0:
                for tile in ct.get_nearby_tiles():
                    if ct.can_spawn(tile):
                        ct.spawn_builder(tile)
                        break
        elif et == EntityType.BUILDER_BOT:
            self.builder(ct)
        elif et == EntityType.LAUNCHER:
            self.launcher(ct)

    def builder(self, ct: Controller) -> None:
        # Walk at the enemy until one of THEIR builders is close, then drop the
        # launcher right next to it. The first probe only ever saw enemies at
        # d2=18-25, where even a FRIENDLY pickup fails, so it could not separate
        # "wrong team" from "out of pickup range".
        if self.built:
            return
        myTeam = ct.get_team()
        myLoc = ct.get_position()
        near = None
        for u in ct.get_nearby_units():
            try:
                if ct.get_entity_type(u) == EntityType.BUILDER_BOT and ct.get_team(u) != myTeam:
                    p = ct.get_position(u)
                    if near is None or myLoc.distance_squared(p) < myLoc.distance_squared(near):
                        near = p
            except Exception:
                pass
        if near is not None and myLoc.distance_squared(near) <= 9:
            for d in CARDINALS:
                spot = myLoc.add(d)
                try:
                    if spot.distance_squared(near) <= 2 and ct.can_build_launcher(spot):
                        ct.build_launcher(spot)
                        self.built = True
                        note("launcher built at %d,%d next to enemy at %d,%d (d2=%d)"
                             % (spot.x, spot.y, near.x, near.y, spot.distance_squared(near)))
                        return
                except Exception:
                    pass
        target = near if near is not None else self.enemyGuess(ct)
        if target is None:
            return
        d = myLoc.direction_to(target)
        for cand in (d,) + tuple(CARDINALS):
            try:
                if cand in CARDINALS and ct.can_move(cand):
                    ct.move(cand)
                    return
            except Exception:
                pass

    def enemyGuess(self, ct: Controller):
        w, h = ct.get_map_width(), ct.get_map_height()
        p = ct.get_position()
        return Position(w - 1 - p.x, h - 1 - p.y)

    def launcher(self, ct: Controller) -> None:
        if self.tries > 40:
            return
        myPos = ct.get_position()
        myTeam = ct.get_team()
        for u in ct.get_nearby_units():
            try:
                if ct.get_entity_type(u) != EntityType.BUILDER_BOT:
                    continue
                uPos = ct.get_position(u)
                mine = ct.get_team(u) == myTeam
                tag = "FRIENDLY" if mine else "ENEMY"
                # throw it back toward our own side, to any passable tile in range
                note("%s seen d2=%d" % (tag, myPos.distance_squared(uPos)))
                for d in CARDINALS:
                    target = uPos.add(d).add(d)
                    if not ct.is_in_vision(target):
                        continue
                    try:
                        ok = ct.can_launch(uPos, target)
                    except Exception as exc:
                        note("%s can_launch raised %s" % (tag, type(exc).__name__))
                        self.tries += 1
                        break
                    if not ok:
                        continue
                    self.tries += 1
                    try:
                        ct.launch(uPos, target)
                        note("%s LAUNCH OK d2=%d" % (tag, myPos.distance_squared(uPos)))
                    except Exception as exc:
                        note("%s launch raised %s: %s" % (tag, type(exc).__name__, exc))
                    return
                else:
                    if self.tries < 40:
                        self.tries += 1
                        note("%s in range d2=%d but can_launch False everywhere"
                             % (tag, myPos.distance_squared(uPos)))
            except Exception:
                pass
