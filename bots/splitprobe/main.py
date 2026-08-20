"""Splitter probe: harvester -> conveyor -> SPLITTER -> conveyor -> core,
plus a second output branch off the splitter's side. Twin bot (splitprobe0)
builds the same chain with a plain conveyor instead. Compare delivered Ti.
"""
from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]


class Player:
    def __init__(self):
        self.spawned = False
        self.plan = None
        self.step = 0

    def run(self, ct: Controller) -> None:
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            if not self.spawned:
                for t in ct.get_nearby_tiles():
                    if ct.can_spawn(t):
                        ct.spawn_builder(t)
                        self.spawned = True
                        break
            return
        if et != EntityType.BUILDER_BOT:
            return

        my = ct.get_position()
        # find nearest ore, build harvester, then chain toward core with a
        # splitter as the SECOND link (facing along the chain toward core)
        if self.plan is None:
            core = None
            for b in ct.get_nearby_buildings():
                if ct.get_team(b) == ct.get_team() and ct.get_entity_type(b) == EntityType.CORE:
                    core = ct.get_position(b)
            ore = None
            best = 999
            for t in ct.get_nearby_tiles():
                if ct.get_tile_env(t) == Environment.ORE_TITANIUM:
                    d = my.distance_squared(t)
                    if d < best:
                        best, ore = d, t
            if ore is not None and core is not None:
                self.plan = (ore, core)
            else:
                # explore toward map centre until ore appears in vision
                c = Position(ct.get_map_width() // 2, ct.get_map_height() // 2)
                ct.move(self._step_toward(ct, my, c))
            return

        ore, core = self.plan
        # walk adjacent to ore first
        if self.step == 0:
            if my.distance_squared(ore) == 1:
                if ct.can_build_harvester(ore):
                    ct.build_harvester(ore)
                    self.step = 1
                return
            ct.move(self._step_toward(ct, my, ore))
            return
        # then lay: conveyor, SPLITTER, conveyor, conveyor... toward core
        # each link goes on the tile stepping from ore toward core
        chain_idx = self.step - 1
        prev = ore
        for _ in range(chain_idx):
            prev = self._toward(prev, core)
        target = self._toward(prev, core)
        if target.x == core.x and target.y == core.y:
            return  # chain reached core - done, idle
        face = self._dir_toward(target, core)
        if my.distance_squared(target) == 1:
            if chain_idx == 1:  # second link = THE SPLITTER
                if ct.can_build_splitter(target, face):
                    ct.build_splitter(target, face)
                    self.step += 1
            else:
                if ct.can_build_conveyor(target, face):
                    ct.build_conveyor(target, face)
                    self.step += 1
            return
        ct.move(self._step_toward(ct, my, target))

    def _toward(self, a: Position, b: Position) -> Position:
        dx = (b.x > a.x) - (b.x < a.x)
        dy = (b.y > a.y) - (b.y < a.y)
        if dx != 0:
            return Position(a.x + dx, a.y)
        return Position(a.x, a.y + dy)

    def _dir_toward(self, a: Position, b: Position) -> Direction:
        n = self._toward(a, b)
        for d in CARDINALS:
            dd = d.delta()
            if (a.x + dd[0], a.y + dd[1]) == (n.x, n.y):
                return d
        return Direction.NORTH

    def _step_toward(self, ct, a: Position, b: Position) -> Direction:
        best, bd = 999, Direction.CENTRE
        for d in CARDINALS:
            dd = d.delta()
            n = Position(a.x + dd[0], a.y + dd[1])
            if not ct.is_tile_passable(n):
                continue
            dist = n.distance_squared(b)
            if dist < best:
                best, bd = dist, d
        return bd
