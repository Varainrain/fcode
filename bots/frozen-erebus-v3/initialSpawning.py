
import itertools
from fcode import Controller, Direction, EntityType, Environment, Position

CARDINALS = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]

directionMoves = [
    Position(-6, -6), Position(-2, -6), Position(-6, -2), Position(0, -6), # tL
    Position(6, -6), Position(2, -6), Position(6, -2), Position(6, 0), # tR
    Position(6, 6), Position(2, 6), Position(6, 2), Position(0, 6), # bR
    Position(-6, 6), Position(-2, 6), Position(-6, 2), Position(-6, 0) # bL
]
anglePerDir = [
    135, 108, 162, 90,
    45, 72, 18, 0,
    315, 288, 342, 270,
    225, 252, 198, 180
]
spawnPoints = [
    Position(-1, -1), Position(0, -1), Position(-1, 0), Position(0, -1), # tL
    Position(1, -1), Position(0, -1), Position(1, 0), Position(1, 0), # tR
    Position(1, 1), Position(0, 1), Position(1, 0), Position(0, 1), # bR
    Position(-1, 1), Position(0, 1), Position(-1, 0), Position(-1, 0) # bL
]


class initialSpawn:
    def getCardPath(self, ct: Controller, start: Position, target: Position):
        dX = target.x - start.x
        dY = target.y - start.y
        ewDir = Direction.EAST if dX > 0 else Direction.WEST
        nsDir = Direction.NORTH if dY < 0 else Direction.SOUTH 
        dX, dY = abs(dX), abs(dY)

        if dX == 0:
            return [nsDir] * dY
        if dY == 0:
            return [ewDir] * dX

        if dY > dX:
            primaryDir, secondaryDir = nsDir, ewDir
            primaryCount, secondaryCount = dY, dX
        else:
            primaryDir, secondaryDir = ewDir, nsDir
            primaryCount, secondaryCount = dX, dY

        numInPattern = primaryCount // secondaryCount
        patternBlock = [primaryDir] * numInPattern + [secondaryDir]

        path = patternBlock * secondaryCount
        path += [primaryDir] * (primaryCount - numInPattern * secondaryCount)
        return path

    def pickBestRays(self, ct: Controller, rayScores, coreCorners):
        if len(rayScores) < 5:
            angles = []
            for ray in rayScores:
                angles.append(ray[1])
            for i in rayScores:
                index = anglePerDir.index(i[1])
                start = Position(coreCorners[index // 4].x + spawnPoints[index].x, coreCorners[index // 4].y + spawnPoints[index].y)
                target = Position(start.x + directionMoves[index].x, start.y + directionMoves[index].y)
                ct.draw_indicator_line(start, target, 50, 70, 180)
            return angles
        bestScore = 0
        bestAngles = []
        for thisFive in itertools.combinations(rayScores, 5):
            curScore = 0
            angles = []
            for ray in thisFive:
                curScore += ray[0]
                angles.append(ray[1])
            angles.sort()
            product = 1
            for i in range(len(angles)-1):
                product = product * (angles[i+1]-angles[i])/30
            product = product * (360 - angles[-1] + angles[0])/30
            curScore += product 
            if curScore > bestScore:
                bestScore = curScore
                bestAngles = angles
        for i in bestAngles:
            index = anglePerDir.index(i)
            start = Position(coreCorners[index // 4].x + spawnPoints[index].x, coreCorners[index // 4].y + spawnPoints[index].y)
            target = Position(start.x + directionMoves[index].x, start.y + directionMoves[index].y)
            ct.draw_indicator_line(start, target, 50, 70, 180)
        return bestAngles
    def setBestFive (self, ct: Controller):
        myLoc = ct.get_position()
        tL = myLoc
        tR = myLoc.add(Direction.EAST)
        bL = myLoc.add(Direction.SOUTH)
        bR = myLoc.add(Direction.SOUTH).add(Direction.EAST)
        coreCorners = [tL, tR, bR, bL]
        mapW = ct.get_map_width()
        mapH = ct.get_map_height()
        rayScores = []
        for i in range(16):
            rayPath = self.getCardPath(ct, spawnPoints[i], directionMoves[i])
            start = Position(coreCorners[i // 4].x + spawnPoints[i].x, coreCorners[i // 4].y + spawnPoints[i].y)
            rayScore = 0
            for j in rayPath:
                start = start.add(j)
                if 0 <= start.x < mapW and 0 <= start.y < mapH:
                    ct.draw_indicator_dot(start, 255, 255, 255)
                    if ct.is_in_vision(start):
                        env = ct.get_tile_env(start)
                        if env == Environment.ORE_TITANIUM:
                            rayScore += 16
                        elif env == Environment.EMPTY:
                            rayScore += 1
                        else:
                            break
                    else:
                        break
                else:
                    break
            if rayScore > 3: # super short paths are not worth exploring
                rayScores.append([rayScore, anglePerDir[i]])
        return self.pickBestRays(ct, rayScores, coreCorners)
