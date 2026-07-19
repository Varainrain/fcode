from fcode import *
import random


class Defender:
    def __init__(self):
        self.defendPos = None
        self.destroyTurns = 0

    def defendInfrastructure(self, ct: Controller, teamCore, pf):
        myLoc = ct.get_position()
        if self.defendPos is None:
            for i in ct.get_nearby_buildings():
                if ct.get_team(i) == ct.get_team() and ct.get_hp(i) < ct.get_max_hp(i):
                    self.defendPos  = ct.get_position(i)
                    break
        if self.defendPos is not None:
            if myLoc.distance_squared(self.defendPos) > 2:
                pf.moveTo(ct, self.defendPos)
            self.placeLauncher(ct, self.defendPos)
            if ct.can_heal(self.defendPos):
                ct.heal(self.defendPos)

        if self.defendPos is not None:
            if ct.is_in_vision(self.defendPos):
                defendID = ct.get_tile_building_id(self.defendPos)
                if defendID is None:
                    self.defendPos = None
                elif ct.get_hp(defendID) == ct.get_max_hp(defendID):
                    self.defendPos = None
            else:
                self.defendPos = None

    def placeLauncher(self, ct: Controller, pos: Position):
        myLoc = ct.get_position()
        # launchers still yeet the siege's support builders, but 13 of them
        # was pure waste: cap how many we keep alive
        team = ct.get_team()
        launchers = 0
        for i in ct.get_nearby_buildings():
            if ct.get_team(i) == team and ct.get_entity_type(i) == EntityType.LAUNCHER:
                launchers += 1
                if ct.get_position(i).distance_squared(pos) <= 2:
                    return  # Launcher already built
        if launchers >= 2:
            return  # enough launchers alive, dont spam them
        topCands = []
        otherCands = []
        for k in ct.get_nearby_tiles(2):
            if k.distance_squared(pos) <= 2 and k.distance_squared(myLoc) <= 2:
                bid = ct.get_tile_building_id(k)
                if bid is None and ct.get_tile_env(k) != Environment.WALL:
                    topCands.append(k)
                elif bid is not None and ct.get_team(bid) == ct.get_team():
                    etype_k = ct.get_entity_type(bid)
                    if etype_k not in (EntityType.CONVEYOR, EntityType.HARVESTER, EntityType.SENTINEL):
                        otherCands.append(k)
        for a in topCands:
            if ct.can_build_launcher(a):
                if self.destroyTurns > 5:
                    self.destroyTurns = 0
                ct.build_launcher(a)
                return
        didDestroy = False
        for a in otherCands:
            if ct.can_destroy(a) and didDestroy == False:
                ct.destroy(a)
                didDestroy = True
            if ct.can_build_launcher(a):
                if self.destroyTurns > 5:
                    self.destroyTurns = 0
                ct.build_launcher(a)
                return
        return

    def picHealingLoc(self, ct: Controller, teamCore: Position, alwaysDefense: bool = False) -> Position | None:
        candidates = []
        for i in ct.get_nearby_tiles(16):
            if ct.get_tile_env(i) == Environment.EMPTY and i.distance_squared(teamCore) < ((ct.get_map_width() + ct.get_map_height() - 8) // 4):
                bid = ct.get_tile_building_id(i)
                if bid is None:
                    candidates.append(i)
                else:
                    entype = ct.get_entity_type(bid)
                    if (entype == EntityType.CONVEYOR or entype == EntityType.CORE):
                        candidates.append(i)

        if not candidates:
            return Position(teamCore.x + random.randint(-1, 2), teamCore.y + random.randint(-1, 2))

        buildingweights = []
        buildingpos = []
        for bid in ct.get_nearby_buildings():
            if ct.get_team(bid) == ct.get_team():
                entype = ct.get_entity_type(bid)
                if entype == EntityType.CONVEYOR:
                    buildingweights.append(25)
                    buildingpos.append(ct.get_position(bid))
                elif entype == EntityType.LAUNCHER:
                    buildingweights.append(5)
                    buildingpos.append(ct.get_position(bid))
                elif entype == EntityType.CORE:
                    buildingweights.append(100)
                    buildingpos.append(ct.get_position(bid))

        bestTile = None
        bestScore = -1

        for i in candidates:
            score = 0
            for j in range(len(buildingweights)):
                pose = buildingpos[j]
                weight = buildingweights[j]
                dist = i.distance_squared(pose)
                if dist < 50:
                    score += max(weight * (1 - 0.02 * dist), 0)

            if score > bestScore:
                bestTile = i
                bestScore = score
        if alwaysDefense == True:
            return Position(teamCore.x + random.randint(-1, 1), teamCore.y + random.randint(-1, 1))
        else:
            if bestTile is None:
                return Position(teamCore.x + random.randint(-1, 1), teamCore.y + random.randint(-1, 1))
            return Position(bestTile.x + random.randint(-1, 1), bestTile.y + random.randint(-1, 1))
