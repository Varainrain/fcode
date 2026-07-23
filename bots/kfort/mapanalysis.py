"""chokepoint finder for the shared tile map.

one team-wide resumable job. builders call note_structural_tile only on
passable<->blocking changes, dupes get coalesced here. results are plain
(x, y) tuples so this file doesnt need fcode.

smoke test, two rooms + a 1 wide corridor::

    >>> grid = [[2] * 20 for _ in range(20)]
    >>> for x in range(1, 8):
    ...     for y in range(3, 17): grid[x][y] = 0
    >>> for x in range(12, 19):
    ...     for y in range(3, 17): grid[x][y] = 0
    >>> for x in range(8, 12): grid[x][10] = 0
    >>> result, _ = analyze_for_test(grid)
    >>> len(result)
    1
    >>> result[0][:2]
    ((10, 10), 1)
    >>> open_map = [[0] * 20 for _ in range(20)]
    >>> analyze_for_test(open_map)[0]
    []

maps are map[x][y] like Player.fullMap.
"""

from collections import deque


REGION_MIN_RADIUS = 3  # min clearance for a big-room region node
MAX_CHOKE_RADIUS = 2  # widest thing we still call a choke
RATIO_SMALL = 0.7  # choke/smaller-room ratio past which rooms just merge
RATIO_LARGE = 0.5  # same but vs the bigger room
RATIO_TWO_CHOKE = 0.8  # collapse 2-exit sliver regions with a wide exit
CPU_BUDGET_US = 6000  # no analysis cpu past this point in a turn
STEP_SLICE = 200  # max queue items per step() slice

CLEARANCE = 0
SKELETON = 1
PRUNE = 2
REGIONS = 3
CHOKES = 4
MERGE = 5
DONE = 6


struct_version = 0
chokes = []
region_partition = []
region_nodes = []
job = None
_debug_items = []
_debug_cursor = 0

_map_width = 0
_map_height = 0
_structural_map = []


def _index(x, y, height):
    return x * height + y


def configure_map(width, height):
    """Initialise the shared structural map; unexplored tiles are blocking."""
    global _map_width, _map_height, _structural_map, struct_version, job
    global chokes, region_partition, region_nodes, _debug_items, _debug_cursor
    if width == _map_width and height == _map_height and _structural_map:
        return
    _map_width = width
    _map_height = height
    _structural_map = [True] * (width * height)
    struct_version += 1
    job = None
    chokes = []
    region_partition = []
    region_nodes = []
    _debug_items = []
    _debug_cursor = 0


def reset_map(width, height):
    """Start a fresh match even when its dimensions match the previous one."""
    global _map_width, _map_height, _structural_map, struct_version, job
    global chokes, region_partition, region_nodes, _debug_items, _debug_cursor
    _map_width = width
    _map_height = height
    _structural_map = [True] * (width * height)
    struct_version += 1
    job = None
    chokes = []
    region_partition = []
    region_nodes = []
    _debug_items = []
    _debug_cursor = 0


def note_structural_tile(x, y, blocking, width, height):
    """Record one structural observation and bump the version only if needed."""
    global struct_version, job, chokes, region_partition, region_nodes
    global _debug_items, _debug_cursor
    configure_map(width, height)
    idx = _index(x, y, height)
    blocking = bool(blocking)
    if _structural_map[idx] == blocking:
        return False
    _structural_map[idx] = blocking
    struct_version += 1
    job = None
    chokes = []
    region_partition = []
    region_nodes = []
    _debug_items = []
    _debug_cursor = 0
    return True


def get_job():
    """Return the current-version singleton job, creating it lazily."""
    global job
    if not _structural_map:
        return None
    if job is None or job.version != struct_version:
        job = AnalysisJob(
            _map_width, _map_height, _structural_map, struct_version
        )
    return job


def region_at(x, y):
    """Return the published region id for a tile, or -1 if none is ready."""
    if (not region_partition or x < 0 or y < 0
            or x >= _map_width or y >= _map_height):
        return -1
    return region_partition[_index(x, y, _map_height)]


def draw_debug(ct, position_factory, deadline_us=9000):
    """Draw the published red chokes and green nodes in bounded spare slices."""
    global _debug_cursor
    items = _debug_items
    while (_debug_cursor < len(items)
           and ct.get_cpu_time_elapsed() < deadline_us):
        tile, red, green, blue = items[_debug_cursor]
        _debug_cursor += 1
        ct.draw_indicator_dot(position_factory(tile[0], tile[1]),
                              red, green, blue)


class AnalysisJob:
    """Small-slice phase machine; callers enforce the per-turn CPU deadline."""

    def __init__(self, width, height, blocking, version):
        self.width = width
        self.height = height
        self.count = width * height
        self.blocking = blocking[:]
        self.version = version
        self.phase = CLEARANCE

        self.clearance = [-1] * self.count
        self.skeleton = [False] * self.count
        self.adj = [[] for _ in range(self.count)]
        self.active = [False] * self.count
        self.degree = [0] * self.count
        self.raw_region_nodes = []
        self.region_index = [-1] * self.count
        self.candidates = []

        self._mode = "seed"
        self._cursor = 0
        self._queue = deque()
        self._candidate = -1
        self._candidate_scan = 0
        self._candidate_end = 0
        self._candidate_greater = False
        self._region_cursor = 0
        self._neighbor_cursor = 0
        self._edge_seen = set()
        self._walk = None

        self.parent = []
        self.root_clearance = []
        self.root_size = []
        self.keep = []
        self.partition = []
        self._partition_clearance = []
        self._partition_size = []
        self._merge_cursor = 0
        self._ratio_buckets = []
        self._ratio_bucket = -1
        self._ratio_bucket_pos = 0
        self._incidence = []
        self._merge_changed = False
        self._output = []

    def step(self):
        if self.phase == CLEARANCE:
            self._step_clearance()
        elif self.phase == SKELETON:
            self._step_skeleton()
        elif self.phase == PRUNE:
            self._step_prune()
        elif self.phase == REGIONS:
            self._step_regions()
        elif self.phase == CHOKES:
            self._step_chokes()
        elif self.phase == MERGE:
            self._step_merge()

    def _neighbors(self, idx):
        h = self.height
        w = self.width
        x, y = divmod(idx, h)
        if x:
            yield idx - h
        if x + 1 < w:
            yield idx + h
        if y:
            yield idx - 1
        if y + 1 < h:
            yield idx + 1

    def _step_clearance(self):
        limit = STEP_SLICE
        n = self.count
        if self._mode == "seed":
            end = min(n, self._cursor + limit)
            for idx in range(self._cursor, end):
                if self.blocking[idx]:
                    self.clearance[idx] = 0
                    self._queue.append(idx)
            self._cursor = end
            if end == n:
                self._mode = "bfs" if self._queue else "unbounded"
                self._cursor = 0
            return

        if self._mode == "unbounded":
            end = min(n, self._cursor + limit)
            far = self.width + self.height + 1
            for idx in range(self._cursor, end):
                if not self.blocking[idx]:
                    self.clearance[idx] = far
            self._cursor = end
            if end == n:
                self.phase = SKELETON
                self._mode = "mark"
                self._cursor = 0
            return

        pops = 0
        clearance = self.clearance
        queue = self._queue
        while queue and pops < limit:
            idx = queue.popleft()
            next_distance = clearance[idx] + 1
            for other in self._neighbors(idx):
                if clearance[other] < 0:
                    clearance[other] = next_distance
                    queue.append(other)
            pops += 1
        if not queue:
            self.phase = SKELETON
            self._mode = "mark"
            self._cursor = 0

    def _step_skeleton(self):
        n = self.count
        end = min(n, self._cursor + STEP_SLICE)
        if self._mode == "mark":
            clearance = self.clearance
            blocking = self.blocking
            skeleton = self.skeleton
            for idx in range(self._cursor, end):
                if blocking[idx]:
                    continue
                value = clearance[idx]
                is_maximum = True
                for other in self._neighbors(idx):
                    if clearance[other] > value:
                        is_maximum = False
                        break
                skeleton[idx] = is_maximum
            self._cursor = end
            if end == n:
                self._mode = "connect"
                self._cursor = 0
            return

        skeleton = self.skeleton
        adj = self.adj
        h = self.height
        w = self.width
        for idx in range(self._cursor, end):
            if not skeleton[idx]:
                continue
            x, y = divmod(idx, h)
            if x + 1 < w and skeleton[idx + h]:
                adj[idx].append(idx + h)
                adj[idx + h].append(idx)
            if y + 1 < h and skeleton[idx + 1]:
                adj[idx].append(idx + 1)
                adj[idx + 1].append(idx)
        self._cursor = end
        if end == n:
            self.phase = PRUNE
            self._mode = "init"
            self._cursor = 0

    def _step_prune(self):
        if self._mode == "init":
            end = min(self.count, self._cursor + STEP_SLICE)
            for idx in range(self._cursor, end):
                if self.skeleton[idx]:
                    self.active[idx] = True
                    degree = len(self.adj[idx])
                    self.degree[idx] = degree
                    if degree == 1:
                        self._queue.append(idx)
            self._cursor = end
            if end == self.count:
                self._mode = "peel"
            return

        pops = 0
        while self._queue and pops < STEP_SLICE:
            idx = self._queue.popleft()
            pops += 1
            if not self.active[idx] or self.degree[idx] != 1:
                continue
            neighbor = -1
            for other in self.adj[idx]:
                if self.active[other]:
                    neighbor = other
                    break
            if neighbor < 0:
                continue
            if self.clearance[idx] < self.clearance[neighbor]:
                self.active[idx] = False
                self.degree[idx] = 0
                self.degree[neighbor] -= 1
                if self.degree[neighbor] == 1:
                    self._queue.append(neighbor)
        if not self._queue:
            self.phase = REGIONS
            self._mode = "scan"
            self._cursor = 0

    def _finish_region_candidate(self):
        if not self._candidate_greater:
            idx = self._candidate
            self.region_index[idx] = len(self.raw_region_nodes)
            self.raw_region_nodes.append(idx)
        self._candidate = -1

    def _step_regions(self):
        ops = 0
        h = self.height
        w = self.width
        while ops < STEP_SLICE:
            if self._candidate >= 0:
                idx = self._candidate
                x, y = divmod(idx, h)
                radius = self.clearance[idx]
                while self._candidate_scan < self._candidate_end and ops < STEP_SLICE:
                    pos = self._candidate_scan
                    self._candidate_scan += 1
                    ops += 1
                    ox, oy = divmod(pos, h)
                    if (abs(ox - x) <= radius and abs(oy - y) <= radius
                            and self.active[pos]
                            and self.clearance[pos] > radius):
                        self._candidate_greater = True
                        self._candidate_scan = self._candidate_end
                if self._candidate_scan >= self._candidate_end:
                    self._finish_region_candidate()
                continue

            if self._cursor >= self.count:
                self.phase = CHOKES
                self._mode = "walk"
                self._region_cursor = 0
                self._neighbor_cursor = 0
                return

            idx = self._cursor
            self._cursor += 1
            ops += 1
            if not self.active[idx]:
                continue
            degree = self.degree[idx]
            if degree != 2:
                self.region_index[idx] = len(self.raw_region_nodes)
                self.raw_region_nodes.append(idx)
            elif self.clearance[idx] >= REGION_MIN_RADIUS:
                radius = self.clearance[idx]
                x, y = divmod(idx, h)
                x0 = max(0, x - radius)
                x1 = min(w - 1, x + radius)
                y0 = max(0, y - radius)
                y1 = min(h - 1, y + radius)
                # scan the enclosing flat range; Chebyshev bounds are checked above
                self._candidate = idx
                self._candidate_scan = x0 * h + y0
                self._candidate_end = x1 * h + y1 + 1
                self._candidate_greater = False

    def _edge_key(self, left, right):
        if left > right:
            left, right = right, left
        return left * self.count + right

    def _outside_seed(self, endpoint, inward):
        """Step off a local-max plateau toward its adjacent open region."""
        best = endpoint
        best_clearance = -1
        for other in self._neighbors(endpoint):
            if other == inward or self.blocking[other]:
                continue
            value = self.clearance[other]
            if value > best_clearance:
                best = other
                best_clearance = value
        return best

    def _begin_next_walk(self):
        nodes = self.raw_region_nodes
        while self._region_cursor < len(nodes):
            start = nodes[self._region_cursor]
            neighbors = self.adj[start]
            while self._neighbor_cursor < len(neighbors):
                other = neighbors[self._neighbor_cursor]
                self._neighbor_cursor += 1
                if not self.active[other]:
                    continue
                key = self._edge_key(start, other)
                if key in self._edge_seen:
                    continue
                self._edge_seen.add(key)
                start_region = self.region_index[start]
                values = [(self.clearance[start], start),
                          (self.clearance[other], other)]
                minimum = min(values)[0]
                minima = [tile for value, tile in values if value == minimum]
                self._walk = [start_region, start, other, minimum, minima,
                              [start, other]]
                return True
            self._region_cursor += 1
            self._neighbor_cursor = 0
        return False

    def _step_chokes(self):
        ops = 0
        while ops < STEP_SLICE:
            if self._walk is None:
                if not self._begin_next_walk():
                    self.phase = MERGE
                    self._mode = "partition_raw_init"
                    return
            start_region, previous, current, minimum, minima, path = self._walk
            ops += 1
            current_region = self.region_index[current]
            if current_region >= 0 and current_region != start_region:
                if minimum <= MAX_CHOKE_RADIUS:
                    # prefer the middle of the minimum-clearance run
                    chosen = minima[len(minima) // 2]
                    left_pos = self._outside_seed(path[0], path[1])
                    right_pos = self._outside_seed(path[-1], path[-2])
                    self.candidates.append(
                        [minimum, chosen, start_region, current_region,
                         left_pos, right_pos]
                    )
                self._walk = None
                continue

            next_tile = -1
            for other in self.adj[current]:
                if self.active[other] and other != previous:
                    next_tile = other
                    break
            if next_tile < 0:
                self._walk = None
                continue
            key = self._edge_key(current, next_tile)
            if key in self._edge_seen:
                self._walk = None
                continue
            self._edge_seen.add(key)
            value = self.clearance[next_tile]
            if value < minimum:
                minimum = value
                minima = [next_tile]
            elif value == minimum:
                minima.append(next_tile)
            path.append(next_tile)
            self._walk = [start_region, current, next_tile, minimum, minima, path]

    def _start_partition(self, removed):
        self.partition = [-1] * self.count
        self._removed = removed
        self._partition_cursor = 0
        self._component = -1
        self._queue.clear()
        self._partition_clearance = []
        self._partition_size = []

    def _step_partition(self, next_mode):
        ops = 0
        while ops < STEP_SLICE:
            if self._queue:
                idx = self._queue.popleft()
                ops += 1
                self._partition_size[self._component] += 1
                value = self.clearance[idx]
                if value > self._partition_clearance[self._component]:
                    self._partition_clearance[self._component] = value
                for other in self._neighbors(idx):
                    if (self.partition[other] < 0 and not self.blocking[other]
                            and other not in self._removed):
                        self.partition[other] = self._component
                        self._queue.append(other)
                continue
            while self._partition_cursor < self.count:
                idx = self._partition_cursor
                self._partition_cursor += 1
                ops += 1
                if (not self.blocking[idx] and idx not in self._removed
                        and self.partition[idx] < 0):
                    self._component += 1
                    self._partition_clearance.append(0)
                    self._partition_size.append(0)
                    self.partition[idx] = self._component
                    self._queue.append(idx)
                    break
                if ops >= STEP_SLICE:
                    return False
            if self._partition_cursor >= self.count and not self._queue:
                self._mode = next_mode
                return True
        return False

    def _find(self, node):
        parent = self.parent
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def _union(self, left, right):
        left = self._find(left)
        right = self._find(right)
        if left == right:
            return left
        lc = self.root_clearance[left]
        rc = self.root_clearance[right]
        if rc > lc or (rc == lc and right < left):
            left, right = right, left
        self.parent[right] = left
        self.root_clearance[left] = max(lc, rc)
        self.root_size[left] += self.root_size[right]
        return left

    def _candidate_components(self, candidate):
        left = self.partition[candidate[4]]
        right = self.partition[candidate[5]]
        if left < 0:
            left = self.partition[self.raw_region_nodes[candidate[2]]]
        if right < 0:
            right = self.partition[self.raw_region_nodes[candidate[3]]]
        return left, right

    def _step_merge(self):
        if self._mode == "partition_raw_init":
            self._removed = set()
            self._merge_cursor = 0
            self._mode = "partition_raw_remove"
            return
        if self._mode == "partition_raw_remove":
            end = min(len(self.candidates), self._merge_cursor + STEP_SLICE)
            for idx in range(self._merge_cursor, end):
                self._removed.add(self.candidates[idx][1])
            self._merge_cursor = end
            if end == len(self.candidates):
                self._start_partition(self._removed)
                self._mode = "partition_raw"
            return
        if self._mode == "partition_raw":
            self._step_partition("ratio_init")
            return
        if self._mode == "ratio_init":
            count = len(self._partition_size)
            self.parent = list(range(count))
            self.root_clearance = self._partition_clearance[:]
            self.root_size = self._partition_size[:]
            self.keep = [False] * len(self.candidates)
            self._ratio_buckets = [
                [] for _ in range(MAX_CHOKE_RADIUS + 1)
            ]
            self._merge_cursor = 0
            self._mode = "ratio_order"
            return
        if self._mode == "ratio_order":
            end = min(len(self.candidates), self._merge_cursor + STEP_SLICE)
            for idx in range(self._merge_cursor, end):
                clearance = self.candidates[idx][0]
                self._ratio_buckets[clearance].append(idx)
            self._merge_cursor = end
            if end == len(self.candidates):
                self._ratio_bucket = MAX_CHOKE_RADIUS
                self._ratio_bucket_pos = 0
                self._mode = "ratio"
            return
        if self._mode == "ratio":
            ops = 0
            while self._ratio_bucket >= 0 and ops < STEP_SLICE:
                bucket = self._ratio_buckets[self._ratio_bucket]
                if self._ratio_bucket_pos >= len(bucket):
                    self._ratio_bucket -= 1
                    self._ratio_bucket_pos = 0
                    continue
                candidate_index = bucket[self._ratio_bucket_pos]
                self._ratio_bucket_pos += 1
                ops += 1
                candidate = self.candidates[candidate_index]
                left, right = self._candidate_components(candidate)
                if left < 0 or right < 0:
                    continue
                left = self._find(left)
                right = self._find(right)
                if left == right:
                    continue
                choke_clearance = candidate[0]
                small = min(self.root_clearance[left], self.root_clearance[right])
                large = max(self.root_clearance[left], self.root_clearance[right])
                if (choke_clearance > RATIO_SMALL * small
                        or choke_clearance > RATIO_LARGE * large):
                    self._union(left, right)
                else:
                    self.keep[candidate_index] = True
            if self._ratio_bucket < 0:
                self._mode = "incidence_init"
            return
        if self._mode == "incidence_init":
            self._incidence = [[] for _ in self.parent]
            self._merge_cursor = 0
            self._mode = "incidence"
            return
        if self._mode == "incidence":
            end = min(len(self.candidates), self._merge_cursor + STEP_SLICE)
            for idx in range(self._merge_cursor, end):
                if not self.keep[idx]:
                    continue
                left, right = self._candidate_components(self.candidates[idx])
                if left < 0 or right < 0:
                    self.keep[idx] = False
                    continue
                left = self._find(left)
                right = self._find(right)
                if left == right:
                    self.keep[idx] = False
                    continue
                self._incidence[left].append(idx)
                self._incidence[right].append(idx)
            self._merge_cursor = end
            if end == len(self.candidates):
                self._merge_cursor = 0
                self._merge_changed = False
                self._mode = "two_choke"
            return
        if self._mode == "two_choke":
            end = min(len(self.parent), self._merge_cursor + STEP_SLICE)
            for region in range(self._merge_cursor, end):
                if self._find(region) != region:
                    continue
                exits = self._incidence[region]
                if len(exits) != 2:
                    continue
                wider = max(exits, key=lambda i: self.candidates[i][0])
                if (self.candidates[wider][0]
                        > RATIO_TWO_CHOKE * self.root_clearance[region]):
                    left, right = self._candidate_components(self.candidates[wider])
                    self._union(left, right)
                    self.keep[wider] = False
                    self._merge_changed = True
                    break
            self._merge_cursor = end
            if self._merge_changed:
                self._mode = "incidence_init"
            elif end == len(self.parent):
                self._mode = "final_partition_init"
            return
        if self._mode == "final_partition_init":
            self._removed = set()
            self._merge_cursor = 0
            self._mode = "final_partition_remove"
            return
        if self._mode == "final_partition_remove":
            end = min(len(self.candidates), self._merge_cursor + STEP_SLICE)
            for idx in range(self._merge_cursor, end):
                if self.keep[idx]:
                    self._removed.add(self.candidates[idx][1])
            self._merge_cursor = end
            if end == len(self.candidates):
                self._start_partition(self._removed)
                self._mode = "final_partition"
            return
        if self._mode == "final_partition":
            self._step_partition("publish_init")
            return
        if self._mode == "publish_init":
            self._output = []
            self._merge_cursor = 0
            self._mode = "publish"
            return
        if self._mode == "publish":
            self._step_publish()
            return
        if self._mode == "debug_publish":
            self._step_debug_publish()

    def _step_publish(self):
        global chokes, region_partition, region_nodes
        global _debug_items, _debug_cursor
        h = self.height
        end = min(len(self.candidates), self._merge_cursor + STEP_SLICE)
        for idx in range(self._merge_cursor, end):
            candidate = self.candidates[idx]
            if not self.keep[idx]:
                continue
            left = self.partition[candidate[4]]
            right = self.partition[candidate[5]]
            if left < 0 or right < 0 or left == right:
                continue
            tile = divmod(candidate[1], h)
            self._output.append((tile, candidate[0],
                                 self._partition_size[left],
                                 self._partition_size[right]))
        self._merge_cursor = end
        if end == len(self.candidates):
            chokes = self._output[:]
            region_partition = self.partition[:]
            region_nodes = []
            _debug_items = [(choke[0], 255, 0, 0) for choke in chokes]
            _debug_cursor = 0
            self._merge_cursor = 0
            self._mode = "debug_publish"

    def _step_debug_publish(self):
        global region_nodes, _debug_items
        end = min(len(self.raw_region_nodes),
                  self._merge_cursor + STEP_SLICE)
        for idx in range(self._merge_cursor, end):
            node = divmod(self.raw_region_nodes[idx], self.height)
            region_nodes.append(node)
            _debug_items.append((node, 0, 255, 0))
        self._merge_cursor = end
        if end == len(self.raw_region_nodes):
            self.phase = DONE


def analyze_for_test(full_map):
    """Synchronously analyze an ``[x][y]`` synthetic map for doctests/tests."""
    if not full_map or not full_map[0]:
        return [], []
    width = len(full_map)
    height = len(full_map[0])
    blocking = []
    for x in range(width):
        if len(full_map[x]) != height:
            raise ValueError("full_map must be rectangular and indexed [x][y]")
        for y in range(height):
            blocking.append(full_map[x][y] in (-1, 2, 3))
    test_job = AnalysisJob(width, height, blocking, 0)
    while test_job.phase != DONE:
        test_job.step()
    return chokes[:], region_partition[:]
