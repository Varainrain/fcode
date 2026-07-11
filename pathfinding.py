from fcode import *

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Pathfinder:
    def __init__(self):
        self.minDistToTarget = 2**10
        self.objectOnRight   = False
        self.currentObstacle = None
        self.currentTarget   = None
        self.canRotate       = True

    def reset(self):
        self.currentTarget   = None
        self.minDistToTarget = 2**10
        self.objectOnRight   = True
        self.currentObstacle = None
        self.canRotate       = True

    def canMove(self, c: Controller, pos: Position, direction: Direction) -> bool:
        dest = pos.add(direction)
        if (max(0, min(dest.x, c.get_map_width()-1))  != dest.x or
            max(0, min(dest.y, c.get_map_height()-1)) != dest.y):
            return False
        return c.can_move(direction)

    def _move(self, c: Controller, pos: Position, direction: Direction):
        if c.can_move(direction):
            c.move(direction)

    @staticmethod
    def _diagonalDist(a: Position, b: Position) -> int:
        return max(abs(a.x - b.x), abs(a.y - b.y))

    def _setInitialDirection(self, c: Controller):
        myLoc   = c.get_position()
        forward = myLoc.direction_to(self.currentTarget)
        left    = forward.rotate_left()
        right   = forward.rotate_right()

        for _ in range(8):
            if self.canMove(c, myLoc, left): break
            left = left.rotate_left()
        for _ in range(8):
            if self.canMove(c, myLoc, right): break
            right = right.rotate_right()

        leftDist  = self._diagonalDist(myLoc.add(left),  self.currentTarget)
        rightDist = self._diagonalDist(myLoc.add(right), self.currentTarget)

        self.objectOnRight   = leftDist < rightDist
        self.currentObstacle = (myLoc.add(left.rotate_right())
                                if self.objectOnRight
                                else myLoc.add(right.rotate_left()))

    def _followWall(self, c: Controller, myLoc: Position):
        direction = myLoc.direction_to(self.currentObstacle)
        w, h = c.get_map_width(), c.get_map_height()
        for _ in range(8):
            direction = (direction.rotate_left() if self.objectOnRight else direction.rotate_right())
            if self.canMove(c, myLoc, direction):
                self._move(c, myLoc, direction)
                return
            loc = myLoc.add(direction)
            if (loc.x < 0 or loc.y < 0 or loc.x >= w or loc.y >= h) and self.canRotate:
                self.objectOnRight = not self.objectOnRight
                self.canRotate     = False
            if not self.canMove(c, myLoc, direction):
                self.currentObstacle = loc

    def moveTo(self, c: Controller, target: Position):
        if self.currentTarget is None or self.currentTarget != target:
            self.reset()
            self.currentTarget = target

        myLoc = c.get_position()

        if not any(self.canMove(c, myLoc, d) for d in DIRECTIONS):
            return

        dist = self._diagonalDist(myLoc, target)
        if dist < self.minDistToTarget:
            self.reset()
            self.minDistToTarget = dist
        self.currentTarget = target

        if self.currentObstacle is None:
            forward = myLoc.direction_to(target)
            if self.canMove(c, myLoc, forward):
                self._move(c, myLoc, forward)
                return
            self._setInitialDirection(c)
        self._followWall(c, myLoc)
