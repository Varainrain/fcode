"""A simple economy bot: spawn a few builders, mine nearby ore, wander a bit.

Each unit gets its own Player instance; run() is called once per round.
"""

import random
from fcode import Controller, Direction, EntityType, Environment, Position

DIRS = [d for d in Direction if d != Direction.CENTRE]
CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

MAX_BUILDERS = 6


class Player:
    def __init__(self):
        self.spawned = 0

    def run(self, ct: Controller) -> None:
        et = ct.get_entity_type()
        if et == EntityType.CORE:
            self._core(ct)
        elif et == EntityType.BUILDER_BOT:
            self._builder(ct)

    def _core(self, ct: Controller) -> None:
        if self.spawned >= MAX_BUILDERS:
            return
        pos = ct.get_position()
        dirs = list(DIRS)
        random.shuffle(dirs)
        for d in dirs:
            sp = pos.add(d)
            if ct.can_spawn(sp):
                ct.spawn_builder(sp)
                self.spawned += 1
                return

    def _builder(self, ct: Controller) -> None:
        pos = ct.get_position()

        # 1. Build a harvester on any adjacent ore tile.
        if ct.get_action_cooldown() == 0:
            for d in Direction:
                p = pos.add(d)
                if ct.can_build_harvester(p):
                    ct.build_harvester(p)
                    break

        # 2. Occasionally drop a conveyor in a random cardinal direction.
        if ct.get_action_cooldown() == 0 and random.random() < 0.3:
            d = random.choice(CARDINALS)
            if ct.can_build_conveyor(pos, d):
                ct.build_conveyor(pos, d)

        # 3. Wander in a random direction.
        if ct.get_move_cooldown() == 0:
            random.shuffle(DIRS)
            for d in DIRS:
                if ct.can_move(d):
                    ct.move(d)
                    break
# LAUNCHER_OFFSETS = [(2, 2), (2, -1), (-1, 2), (-1, 1)]
# import random
# from fcode import Controller, Direction, EntityType, Environment, Position

# DIRS = [d for d in Direction if d != Direction.CENTRE]
# CARDINALS = [Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST]

# MAX_BUILDERS = 6


# class Player:
#     def __init__(self):
#         self.spawned = 0
#         self.corePos = None

#     def run(self, ct: Controller) -> None:
#         et = ct.get_entity_type()
#         if et == EntityType.CORE:
#             self._core(ct)
#         elif et == EntityType.BUILDER_BOT:
#             self._builder(ct)

#     def _core(self, ct: Controller) -> None:
#         if self.spawned >= MAX_BUILDERS:
#             return
#         pos = ct.get_position()
#         dirs = list(DIRS)
#         random.shuffle(dirs)
#         for d in dirs:
#             sp = pos.add(d)
#             if ct.can_spawn(sp):
#                 ct.spawn_builder(sp)
#                 self.spawned += 1
#                 return

#     def _builder(self, ct: Controller) -> None:
#         if self.corePos is None:
#             for i in ct.get_nearby_buildings():
#                 if ct.get_entity_type(i) == EntityType.CORE and ct.get_team(i) == ct.get_team():
#                     self.corePos = ct.get_position(i)
#         pos = ct.get_position()

#         if ct.get_action_cooldown() == 0:
#             for d in Direction:
#                 p = pos.add(d)
#                 if ct.can_build_harvester(p):
#                     ct.build_harvester(p)
#                     break

#         if ct.get_action_cooldown() == 0 and random.random() < 0.3:
#             if self.corePos is not None:
#                 possibleConveyors = []
#                 for i in CARDINALS:
#                     end = pos.add(i)
#                     if ct.can_build_conveyor(pos, i):
#                         possibleConveyors.append(i)
#                 possibleConveyors.sort(key=lambda c: self.corePos.distance_squared(pos.add(c)))
#                 for i in possibleConveyors:
#                     if ct.can_build_conveyor(pos, i):
#                         ct.build_conveyor(pos, i)
                
#             else:
#                 d = random.choice(CARDINALS)
#                 if ct.can_build_conveyor(pos, d):
#                     ct.build_conveyor(pos, d)

#         if ct.get_move_cooldown() == 0:
#             random.shuffle(DIRS)
#             for d in DIRS:
#                 if ct.can_move(d):
#                     ct.move(d)
#                     break
#         w =  ct.get_map_width()
#         h = ct.get_map_height()
#         for dx, dy in LAUNCHER_OFFSETS:
#             pos = Position(self.corePos.x + dx, self.corePos.y + dy)
#             if 0 <= pos.x < w and 0 <= pos.y < h:
#                 if ct.get_tile_env(pos) != Environment.WALL:
#                     ct.draw_indicator_dot(pos, 255, 255, 255)
