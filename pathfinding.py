from fcode import *

DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Pathfinder:
    def __init__(self):
        self.minDistToTarget = 2**10
        self.objectOnRight   = True
        self.currentObstacle = None
        self.currentTarget   = None
        self.canRotate       = True
        self.visitedStates   = set()

    def reset(self):
        self.currentTarget   = None
        self.minDistToTarget = 2**10
        self.objectOnRight   = True
        self.currentObstacle = None
        self.canRotate       = True
        self.visitedStates   = set()

    def isInBounds(self, c: Controller, pos: Position) -> bool:
        W = c.get_map_width() - 1
        H = c.get_map_height() - 1
        return pos.x == max(0, min(W, pos.x)) and pos.y == max(0, min(H, pos.y))

    def canMove(self, c: Controller, direction: Direction) -> bool:
        dest = c.get_position().add(direction)
        if not self.isInBounds(c, dest):
            return False
        return c.can_move(direction)

    def _move(self, c: Controller, direction: Direction):
        if c.can_move(direction):
            c.move(direction)

    @staticmethod
    def _diagonalDist(a: Position, b: Position) -> int:
        return max(abs(a.x - b.x), abs(a.y - b.y))

    def _isKnownPassable(self, c: Controller, pos: Position) -> bool:
        # Only trust this if we currently have vision on the tile -- otherwise we can't
        # tell whether the remembered obstacle has actually cleared.
        if not self.isInBounds(c, pos) or not c.is_in_vision(pos):
            return False
        if c.get_tile_env(pos) == Environment.WALL:
            return False
        return c.get_tile_building_id(pos) is None

    def _setInitialDirection(self, c: Controller):
        myLoc   = c.get_position()
        forward = myLoc.direction_to(self.currentTarget)
        left    = forward.rotate_left()
        right   = forward.rotate_right()

        for _ in range(8):
            if self.canMove(c, left): break
            left = left.rotate_left()
        for _ in range(8):
            if self.canMove(c, right): break
            right = right.rotate_right()

        leftLoc  = myLoc.add(left)
        rightLoc = myLoc.add(right)
        leftDist  = self._diagonalDist(leftLoc,  self.currentTarget)
        rightDist = self._diagonalDist(rightLoc, self.currentTarget)

        if leftDist < rightDist:
            self.objectOnRight = True
        elif rightDist < leftDist:
            self.objectOnRight = False
        else:
            # Tie on Chebyshev distance -- break it with actual distance from the bot.
            self.objectOnRight = myLoc.distance_squared(leftLoc) < myLoc.distance_squared(rightLoc)

        self.currentObstacle = (myLoc.add(left.rotate_right())
                                if self.objectOnRight
                                else myLoc.add(right.rotate_left()))

    def _followWall(self, c: Controller, myLoc: Position, canRotate: bool = None):
        if canRotate is None:
            canRotate = self.canRotate
        direction = myLoc.direction_to(self.currentObstacle)
        for _ in range(8):
            direction = (direction.rotate_left() if self.objectOnRight else direction.rotate_right())
            if self.canMove(c, direction):
                self._move(c, direction)
                return
            loc = myLoc.add(direction)
            if not self.isInBounds(c, loc):
                if canRotate:
                    # Hit the map edge -- flip which side we're hugging and restart the
                    # sweep from scratch (rather than continuing this loop with a direction
                    # that points off the map), locking further flips until the next reset.
                    self.objectOnRight = not self.objectOnRight
                    self.canRotate = False
                    self._followWall(c, myLoc, canRotate=False)
                    return
                continue
            if not self.canMove(c, direction):
                self.currentObstacle = loc

    def _state(self, c: Controller, target: Position):
        myLoc = c.get_position()
        ref = self.currentObstacle if self.currentObstacle is not None else target
        direction = myLoc.direction_to(ref)
        return (myLoc.x, myLoc.y, direction, self.objectOnRight)

    def moveTo(self, c: Controller, target: Position):
        if self.currentTarget is None or self.currentTarget != target:
            self.reset()
            self.currentTarget = target

        if not any(self.canMove(c, d) for d in DIRECTIONS):
            return

        myLoc = c.get_position()

        dist = self._diagonalDist(myLoc, target)
        if dist < self.minDistToTarget:
            self.reset()
            self.minDistToTarget = dist

        # If the obstacle we're routing around has turned out to be passable (vision
        # updated, a unit moved off it, etc.), stop treating it as blocking and retry
        # a direct line instead of continuing to wall-follow around nothing.
        if self.currentObstacle is not None and self._isKnownPassable(c, self.currentObstacle):
            self.reset()
            self.minDistToTarget = dist

        # Cycle detection: if we've already been in this exact (position, facing-toward-
        # obstacle-or-target, which-side-we're-hugging) state on this trip, the wall-follow
        # sweep is looping around an obstacle it can't escape -- force a reset instead of
        # repeating the same loop forever.
        state = self._state(c, target)
        if state in self.visitedStates:
            self.reset()
            self.minDistToTarget = dist
        else:
            self.visitedStates.add(state)

        self.currentTarget = target

        if self.currentObstacle is None:
            forward = myLoc.direction_to(target)
            if self.canMove(c, forward):
                self._move(c, forward)
                return
            self._setInitialDirection(c)
        self._followWall(c, myLoc)
