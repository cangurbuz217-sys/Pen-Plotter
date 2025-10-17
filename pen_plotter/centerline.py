"""Utilities to approximate single-stroke centerlines from filled outlines."""
from __future__ import annotations

import math
import heapq
from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

try:  # pragma: no cover - optional dependency
    import networkx as nx  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    nx = None  # type: ignore

try:  # pragma: no cover - optional dependency
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore

try:  # pragma: no cover - optional dependency
    from skimage.morphology import medial_axis as sk_medial_axis
except Exception:  # pragma: no cover - optional dependency
    sk_medial_axis = None  # type: ignore

Point = Tuple[float, float]
Path = List[Point]

_NEIGHBOURS = [
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
]

_PRIMARY_NEIGHBOURS = [
    (1, 0),
    (0, 1),
    (1, 1),
    (1, -1),
]


@dataclass
class _RasterContext:
    """Stores coordinate transforms between raster pixels and millimetres."""

    min_x: float
    max_y: float
    margin_mm: float
    px_per_mm: float
    height: int

    def to_mm(self, pixel: Tuple[int, int]) -> Point:
        x, y = pixel
        x_mm = (x + 0.5) / self.px_per_mm + self.min_x - self.margin_mm
        y_mm = self.max_y - self.margin_mm - (y + 0.5) / self.px_per_mm
        return x_mm, y_mm


def outlines_to_centerlines(paths: Sequence[Path], tolerance: float) -> List[Path]:
    """Convert closed outline paths into approximate centreline polylines."""

    closed_paths: List[Path] = []
    open_paths: List[Path] = []
    for path in paths:
        if len(path) < 2:
            continue
        if _is_closed(path):
            closed_paths.append(path)
        else:
            open_paths.append(list(path))

    if not closed_paths:
        return open_paths

    min_x, min_y, max_x, max_y = _bounds(closed_paths)
    if max_x - min_x <= 0.0 or max_y - min_y <= 0.0:
        return open_paths

    margin_mm = max(0.35, tolerance * 3.0)
    px_per_mm = min(32.0, max(10.0, 2.4 / max(tolerance, 1e-3)))

    width_mm = (max_x - min_x) + 2.0 * margin_mm
    height_mm = (max_y - min_y) + 2.0 * margin_mm
    width_px = max(int(math.ceil(width_mm * px_per_mm)), 8)
    height_px = max(int(math.ceil(height_mm * px_per_mm)), 8)

    raster = Image.new("1", (width_px, height_px), 0)
    draw = ImageDraw.Draw(raster)
    sorted_loops = sorted(closed_paths, key=lambda p: abs(_signed_area(p)), reverse=True)
    if not sorted_loops:
        return open_paths

    processed_loops: List[Sequence[Point]] = []

    for path in sorted_loops:
        if len(path) < 3:
            continue
        draw_points = [
            (
                (x - min_x + margin_mm) * px_per_mm,
                (max_y - y + margin_mm) * px_per_mm,
            )
            for x, y in path
        ]
        loop_area = _signed_area(path)
        if loop_area == 0.0:
            continue
        centroid = _polygon_centroid(path)
        winding_depth = sum(
            1 for other in processed_loops if _point_in_polygon(centroid, other)
        )
        fill_value = 1 if winding_depth % 2 == 0 else 0
        draw.polygon(draw_points, fill=fill_value)
        processed_loops.append(path)

    bitmap = np.array(raster, dtype=np.uint8)
    if not bitmap.any():
        return open_paths

    if sk_medial_axis is not None:
        skeleton_bool = sk_medial_axis(bitmap.astype(bool))
        if skeleton_bool.any():
            skeleton = skeleton_bool.astype(np.uint8)
            context = _RasterContext(
                min_x=min_x,
                max_y=max_y,
                margin_mm=margin_mm,
                px_per_mm=px_per_mm,
                height=height_px,
            )
            centerlines = _skeleton_to_paths(skeleton, context, tolerance)
            centerlines = _stitch_paths(centerlines, tolerance)
            centerlines = _smooth_paths(centerlines, tolerance)
            if centerlines:
                return open_paths + centerlines

    if cv2 is not None and hasattr(cv2, "ximgproc"):
        thinned = _opencv_thinning(bitmap)
    else:
        thinned = _zhang_suen_thinning(bitmap)
    if not thinned.any():
        return open_paths

    min_branch_length = max(4, int(round(px_per_mm * 0.75)))
    if min_branch_length >= 2:
        _prune_short_branches(thinned, min_branch_length)

    context = _RasterContext(
        min_x=min_x,
        max_y=max_y,
        margin_mm=margin_mm,
        px_per_mm=px_per_mm,
        height=height_px,
    )

    centerlines = _skeleton_to_paths(thinned, context, tolerance)
    centerlines = _stitch_paths(centerlines, tolerance)
    centerlines = _smooth_paths(centerlines, tolerance)
    if not centerlines:
        return open_paths

    return open_paths + centerlines


def _is_closed(path: Sequence[Point]) -> bool:
    return math.isclose(path[0][0], path[-1][0], abs_tol=1e-6) and math.isclose(
        path[0][1], path[-1][1], abs_tol=1e-6
    )


def _bounds(paths: Iterable[Sequence[Point]]) -> Tuple[float, float, float, float]:
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    for path in paths:
        for x, y in path:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    return min_x, min_y, max_x, max_y


def _signed_area(path: Sequence[Point]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        area += (x1 * y2) - (x2 * y1)
    return area * 0.5


def _polygon_centroid(path: Sequence[Point]) -> Point:
    if not path:
        return (0.0, 0.0)

    twice_area = 0.0
    cx = 0.0
    cy = 0.0

    points = list(path)
    if points[0] != points[-1]:
        points.append(points[0])

    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        cross = (x0 * y1) - (x1 * y0)
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    if abs(twice_area) < 1e-9:
        avg_x = sum(x for x, _ in path) / len(path)
        avg_y = sum(y for _, y in path) / len(path)
        return avg_x, avg_y

    area = twice_area * 0.5
    return (cx / (3.0 * twice_area), cy / (3.0 * twice_area)) if area != 0 else (
        sum(x for x, _ in path) / len(path),
        sum(y for _, y in path) / len(path),
    )


def _point_on_segment(point: Point, a: Point, b: Point) -> bool:
    (px, py) = point
    (ax, ay) = a
    (bx, by) = b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-9:
        return False
    dot = (px - ax) * (px - bx) + (py - ay) * (py - by)
    return dot <= 1e-9


def _point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    if not polygon:
        return False

    x, y = point
    inside = False
    points = list(polygon)
    if points[0] != points[-1]:
        points.append(points[0])

    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if _point_on_segment(point, (x0, y0), (x1, y1)):
            return True
        intersects = ((y0 > y) != (y1 > y)) and (
            x < (x1 - x0) * (y - y0) / (y1 - y0 + 1e-12) + x0
        )
        if intersects:
            inside = not inside

    return inside


def _zhang_suen_thinning(image: np.ndarray) -> np.ndarray:
    """Vectorised Zhang-Suen thinning for a binary bitmap."""

    skeleton = (image > 0).astype(np.uint8)
    if skeleton.size == 0:
        return skeleton

    padded = np.pad(skeleton, 1, mode="constant", constant_values=0)

    def subiteration(data: np.ndarray, iteration: int) -> bool:
        center = data[1:-1, 1:-1]
        if not center.any():
            return False

        p2 = data[:-2, 1:-1]
        p3 = data[:-2, 2:]
        p4 = data[1:-1, 2:]
        p5 = data[2:, 2:]
        p6 = data[2:, 1:-1]
        p7 = data[2:, :-2]
        p8 = data[1:-1, :-2]
        p9 = data[:-2, :-2]

        neighbour_sum = (
            p2
            + p3
            + p4
            + p5
            + p6
            + p7
            + p8
            + p9
        )

        stacked = np.stack((p2, p3, p4, p5, p6, p7, p8, p9, p2))
        transitions = ((stacked[:-1] == 0) & (stacked[1:] == 1)).sum(axis=0)

        condition = (
            (center == 1)
            & (neighbour_sum >= 2)
            & (neighbour_sum <= 6)
            & (transitions == 1)
        )

        if iteration == 0:
            condition &= (p2 * p4 * p6 == 0)
            condition &= (p4 * p6 * p8 == 0)
        else:
            condition &= (p2 * p4 * p8 == 0)
            condition &= (p2 * p6 * p8 == 0)

        if not condition.any():
            return False

        center[condition] = 0
        return True

    changed = True
    while changed:
        changed = False
        if subiteration(padded, 0):
            changed = True
        if subiteration(padded, 1):
            changed = True

    return padded[1:-1, 1:-1]


def _opencv_thinning(image: np.ndarray) -> np.ndarray:
    """Use OpenCV's accelerated thinning when available."""

    binary = (image > 0).astype(np.uint8) * 255
    thinned = cv2.ximgproc.thinning(  # type: ignore[attr-defined]
        binary, thinningType=cv2.ximgproc.THINNING_ZHANGSUEN  # type: ignore[attr-defined]
    )
    return (thinned > 0).astype(np.uint8)
def _prune_short_branches(skeleton: np.ndarray, min_length: int) -> None:
    """Remove tiny spurs from a skeleton in-place."""

    height, width = skeleton.shape
    changed = True

    while changed:
        changed = False
        endpoints: List[Tuple[int, int]] = []
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                if skeleton[y, x] == 0:
                    continue
                neighbours = [
                    (x + dx, y + dy)
                    for dx, dy in _NEIGHBOURS
                    if 0 <= x + dx < width
                    and 0 <= y + dy < height
                    and skeleton[y + dy, x + dx] != 0
                ]
                if len(neighbours) == 1:
                    endpoints.append((x, y))

        if not endpoints:
            return

        for start in endpoints:
            x, y = start
            path: List[Tuple[int, int]] = []
            previous: Tuple[int, int] | None = None

            for _ in range(min_length):
                path.append((x, y))
                neighbours = [
                    (x + dx, y + dy)
                    for dx, dy in _NEIGHBOURS
                    if 0 <= x + dx < width
                    and 0 <= y + dy < height
                    and skeleton[y + dy, x + dx] != 0
                ]
                if previous is not None and previous in neighbours:
                    neighbours.remove(previous)
                if not neighbours:
                    break
                if len(neighbours) > 1:
                    break
                previous = (x, y)
                x, y = neighbours[0]
            else:
                # Loop completed without breaking meaning spur is long enough.
                continue

            if len(path) <= min_length:
                for px, py in path:
                    if skeleton[py, px] != 0:
                        skeleton[py, px] = 0
                        changed = True


def _skeleton_to_paths(
    skeleton: np.ndarray, context: _RasterContext, tolerance: float
) -> List[Path]:
    height, width = skeleton.shape
    visited: set[Tuple[int, int]] = set()
    component_paths: List[Path] = []

    for y in range(height):
        for x in range(width):
            if skeleton[y, x] == 0 or (x, y) in visited:
                continue

            queue: deque[Tuple[int, int]] = deque([(x, y)])
            visited.add((x, y))
            component: List[Tuple[int, int]] = []

            while queue:
                px, py = queue.popleft()
                component.append((px, py))
                for dx, dy in _NEIGHBOURS:
                    nx, ny = px + dx, py + dy
                    if (
                        0 <= nx < width
                        and 0 <= ny < height
                        and skeleton[ny, nx] != 0
                        and (nx, ny) not in visited
                    ):
                        visited.add((nx, ny))
                        queue.append((nx, ny))

            path = _component_to_path(component, context, tolerance)
            if len(path) >= 2:
                component_paths.append(path)

    return component_paths


def _component_to_path(
    component: Sequence[Tuple[int, int]],
    context: _RasterContext,
    tolerance: float,
) -> Path:
    if len(component) < 2:
        return _component_fallback_loop(component, context, tolerance)

    graph, weights = _build_component_graph(component)
    if not graph:
        return _component_fallback_loop(component, context, tolerance)

    odd_nodes = [
        node
        for node, neighbours in graph.items()
        if sum(neighbours.values()) % 2 == 1
    ]

    _, augmentation_paths = _pair_odd_nodes(graph, weights, odd_nodes)
    for path in augmentation_paths:
        for a, b in zip(path, path[1:]):
            graph[a][b] = graph[a].get(b, 0) + 1
            graph[b][a] = graph[b].get(a, 0) + 1

    start_node: Tuple[int, int]
    if odd_nodes:
        start_node = odd_nodes[0]
    else:
        start_node = next(iter(graph.keys()))

    pixel_path = _eulerian_path(graph, start_node)
    if len(pixel_path) < 2:
        return []

    mm_points = [context.to_mm(pt) for pt in pixel_path]
    simplified = _simplify_path(mm_points, tolerance * 0.5)
    if len(simplified) < 2:
        return _component_fallback_loop(component, context, tolerance)

    resampled = _resample_path(simplified, max(tolerance * 0.5, 0.25))
    if len(resampled) < 2:
        return simplified if len(simplified) >= 2 else _component_fallback_loop(
            component, context, tolerance
        )

    return resampled


def _component_fallback_loop(
    component: Sequence[Tuple[int, int]],
    context: _RasterContext,
    tolerance: float,
) -> Path:
    if not component:
        return []

    mm_points = [context.to_mm(pixel) for pixel in component]
    min_x = min(point[0] for point in mm_points)
    max_x = max(point[0] for point in mm_points)
    min_y = min(point[1] for point in mm_points)
    max_y = max(point[1] for point in mm_points)

    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5

    width = max_x - min_x
    height = max_y - min_y
    radius = max(width, height, 1.0 / context.px_per_mm) * 0.5
    radius = max(radius, tolerance * 0.75, 0.15)

    circumference = 2.0 * math.pi * radius
    step = max(tolerance * 0.5, 0.3)
    segments = max(8, int(math.ceil(circumference / step)))

    loop: Path = []
    for i in range(segments):
        angle = (2.0 * math.pi * i) / segments
        loop.append((center_x + radius * math.cos(angle), center_y + radius * math.sin(angle)))
    loop.append(loop[0])
    return loop


def _build_component_graph(
    component: Sequence[Tuple[int, int]]
) -> Tuple[
    Dict[Tuple[int, int], Dict[Tuple[int, int], int]],
    Dict[Tuple[Tuple[int, int], Tuple[int, int]], float],
]:
    component_set = set(component)
    if len(component_set) < 2:
        return {}, {}

    graph: Dict[Tuple[int, int], Dict[Tuple[int, int], int]] = {
        node: {} for node in component_set
    }
    weights: Dict[Tuple[Tuple[int, int], Tuple[int, int]], float] = {}

    for x, y in component_set:
        for dx, dy in _PRIMARY_NEIGHBOURS:
            nx, ny = x + dx, y + dy
            neighbour = (nx, ny)
            if neighbour not in component_set:
                continue
            weight = math.hypot(dx, dy)
            graph[(x, y)][neighbour] = graph[(x, y)].get(neighbour, 0) + 1
            graph[neighbour][(x, y)] = graph[neighbour].get((x, y), 0) + 1
            weights[((x, y), neighbour)] = weight
            weights[(neighbour, (x, y))] = weight

    graph = {node: neighbours for node, neighbours in graph.items() if neighbours}
    return graph, weights


def _pair_odd_nodes(
    graph: Dict[Tuple[int, int], Dict[Tuple[int, int], int]],
    weights: Dict[Tuple[Tuple[int, int], Tuple[int, int]], float],
    odd_nodes: Sequence[Tuple[int, int]],
) -> Tuple[float, List[List[Tuple[int, int]]]]:
    if len(odd_nodes) < 2:
        return 0.0, []

    pair_dist: Dict[Tuple[Tuple[int, int], Tuple[int, int]], float] = {}
    pair_paths: Dict[Tuple[Tuple[int, int], Tuple[int, int]], List[Tuple[int, int]]] = {}

    for node in odd_nodes:
        distances, previous = _dijkstra(graph, weights, node)
        for other in odd_nodes:
            if other == node or other not in distances:
                continue
            path = _reconstruct_path(previous, other, node)
            if len(path) < 2:
                continue
            pair_dist[(node, other)] = distances[other]
            pair_dist[(other, node)] = distances[other]
            pair_paths[(node, other)] = path
            pair_paths[(other, node)] = list(reversed(path))

    if not pair_dist:
        return 0.0, []

    used: Dict[Tuple[int, int], bool] = {node: False for node in odd_nodes}
    chosen_paths: List[List[Tuple[int, int]]] = []
    total_cost = 0.0

    if nx is not None:
        graph_match = nx.Graph()
        for node in odd_nodes:
            graph_match.add_node(node)
        for (node_a, node_b), cost in pair_dist.items():
            if node_a == node_b:
                continue
            if graph_match.has_edge(node_a, node_b):
                continue
            graph_match.add_edge(node_a, node_b, weight=cost)
        matching = nx.algorithms.matching.min_weight_matching(
            graph_match, weight="weight"
        )
        if len(matching) * 2 == len(odd_nodes):
            for node_a, node_b in matching:
                if (node_a, node_b) not in pair_paths and (
                    node_b, node_a
                ) in pair_paths:
                    node_a, node_b = node_b, node_a
                if (node_a, node_b) in pair_paths:
                    chosen_paths.append(pair_paths[(node_a, node_b)])
                    total_cost += pair_dist[(node_a, node_b)]
            if chosen_paths:
                return total_cost, chosen_paths

    # Greedy fallback if networkx is unavailable
    edges = sorted(
        (
            (cost, node_a, node_b)
            for (node_a, node_b), cost in pair_dist.items()
            if node_a < node_b
        ),
        key=lambda item: item[0],
    )
    for cost, node_a, node_b in edges:
        if used[node_a] or used[node_b]:
            continue
        used[node_a] = True
        used[node_b] = True
        chosen_paths.append(pair_paths[(node_a, node_b)])
        total_cost += cost

    return total_cost, chosen_paths


def _dijkstra(
    graph: Dict[Tuple[int, int], Dict[Tuple[int, int], int]],
    weights: Dict[Tuple[Tuple[int, int], Tuple[int, int]], float],
    start: Tuple[int, int],
) -> Tuple[Dict[Tuple[int, int], float], Dict[Tuple[int, int], Tuple[int, int]]]:
    distances: Dict[Tuple[int, int], float] = {start: 0.0}
    previous: Dict[Tuple[int, int], Tuple[int, int]] = {}
    heap: List[Tuple[float, Tuple[int, int]]] = [(0.0, start)]

    while heap:
        dist, node = heapq.heappop(heap)
        if dist > distances.get(node, math.inf):
            continue
        for neighbour, count in graph.get(node, {}).items():
            if count <= 0:
                continue
            weight = weights.get((node, neighbour))
            if weight is None:
                continue
            new_dist = dist + weight
            if new_dist + 1e-12 < distances.get(neighbour, math.inf):
                distances[neighbour] = new_dist
                previous[neighbour] = node
                heapq.heappush(heap, (new_dist, neighbour))

    return distances, previous


def _reconstruct_path(
    previous: Dict[Tuple[int, int], Tuple[int, int]],
    target: Tuple[int, int],
    start: Tuple[int, int],
) -> List[Tuple[int, int]]:
    if target not in previous and target != start:
        return []
    node = target
    path: List[Tuple[int, int]] = [node]
    while node != start:
        node = previous.get(node)
        if node is None:
            return []
        path.append(node)
    path.reverse()
    return path


def _eulerian_path(
    graph: Dict[Tuple[int, int], Dict[Tuple[int, int], int]],
    start: Tuple[int, int],
) -> List[Tuple[int, int]]:
    if start not in graph:
        return []

    adjacency: Dict[Tuple[int, int], Dict[Tuple[int, int], int]] = {
        node: dict(neighbours) for node, neighbours in graph.items()
    }

    stack: List[Tuple[int, int]] = [start]
    circuit: List[Tuple[int, int]] = []

    while stack:
        node = stack[-1]
        neighbours = adjacency.get(node)
        if neighbours:
            next_node = next(iter(neighbours))
            remaining = neighbours[next_node]
            if remaining <= 1:
                neighbours.pop(next_node, None)
            else:
                neighbours[next_node] = remaining - 1

            reverse_neighbours = adjacency.get(next_node)
            if reverse_neighbours is not None:
                reverse_remaining = reverse_neighbours.get(node, 0)
                if reverse_remaining <= 1:
                    reverse_neighbours.pop(node, None)
                else:
                    reverse_neighbours[node] = reverse_remaining - 1

            stack.append(next_node)
        else:
            circuit.append(stack.pop())

    circuit.reverse()
    return circuit


def _stitch_paths(paths: List[Path], tolerance: float) -> List[Path]:
    """Merge adjacent polyline fragments into longer strokes."""

    if not paths:
        return []

    join_tolerance = max(tolerance * 3.0, 0.3)
    scale = 1.0 / join_tolerance

    def key(point: Point) -> Tuple[int, int]:
        return (int(round(point[0] * scale)), int(round(point[1] * scale)))

    from collections import defaultdict

    endpoint_map: Dict[Tuple[int, int], List[Tuple[int, bool]]] = defaultdict(list)
    start_keys: List[Tuple[int, int] | None] = []
    end_keys: List[Tuple[int, int] | None] = []

    for index, path in enumerate(paths):
        if len(path) < 2:
            start_keys.append(None)
            end_keys.append(None)
            continue
        start = key(path[0])
        end = key(path[-1])
        start_keys.append(start)
        end_keys.append(end)
        endpoint_map[start].append((index, False))
        endpoint_map[end].append((index, True))

    used = [False] * len(paths)
    stitched: List[Path] = []

    def remove_from_map(node_key: Tuple[int, int], entry: Tuple[int, bool]) -> None:
        entries = endpoint_map.get(node_key)
        if not entries:
            return
        try:
            entries.remove(entry)
        except ValueError:
            return
        if not entries:
            endpoint_map.pop(node_key, None)

    def mark_used(idx: int) -> None:
        used[idx] = True
        start = start_keys[idx]
        end = end_keys[idx]
        if start is not None:
            remove_from_map(start, (idx, False))
        if end is not None:
            remove_from_map(end, (idx, True))

    def pick_candidate(node_key: Tuple[int, int]) -> Tuple[int, bool] | None:
        options = [entry for entry in endpoint_map.get(node_key, []) if not used[entry[0]]]
        if not options:
            return None
        return max(options, key=lambda entry: len(paths[entry[0]]))

    for idx, path in enumerate(paths):
        if used[idx] or len(path) < 2:
            continue
        current = list(path)
        mark_used(idx)
        start_key = start_keys[idx]
        end_key = end_keys[idx]

        while start_key is not None:
            candidate = pick_candidate(start_key)
            if candidate is None:
                break
            next_idx, from_end = candidate
            mark_used(next_idx)
            next_path = paths[next_idx]
            if from_end:
                segment = next_path[:-1]
                other_key = start_keys[next_idx]
            else:
                segment = list(reversed(next_path[1:]))
                other_key = end_keys[next_idx]
            if segment:
                current = segment + current
            start_key = other_key

        while end_key is not None:
            candidate = pick_candidate(end_key)
            if candidate is None:
                break
            next_idx, from_end = candidate
            mark_used(next_idx)
            next_path = paths[next_idx]
            if from_end:
                segment = list(reversed(next_path[:-1]))
                other_key = start_keys[next_idx]
            else:
                segment = next_path[1:]
                other_key = end_keys[next_idx]
            if segment:
                current.extend(segment)
            end_key = other_key

        stitched.append(current)

    return stitched


def _smooth_paths(paths: List[Path], tolerance: float) -> List[Path]:
    if not paths:
        return []

    smoothed: List[Path] = []
    simplify_tolerance = max(tolerance * 0.5, 1e-3)
    dedupe_epsilon = max(tolerance * 0.2, 1e-3)

    for path in paths:
        if len(path) < 2:
            continue
        points = list(path)
        iterations = 2
        for _ in range(iterations):
            if len(points) < 3:
                break
            refined: List[Point] = [points[0]]
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                qx = 0.75 * x0 + 0.25 * x1
                qy = 0.75 * y0 + 0.25 * y1
                rx = 0.25 * x0 + 0.75 * x1
                ry = 0.25 * y0 + 0.75 * y1
                refined.append((qx, qy))
                refined.append((rx, ry))
            refined.append(points[-1])
            points = refined

        simplified = _simplify_path(points, simplify_tolerance)
        if len(simplified) < 2:
            continue

        deduped: Path = [simplified[0]]
        for pt in simplified[1:]:
            if _distance_sq(deduped[-1], pt) <= dedupe_epsilon ** 2:
                deduped[-1] = (
                    0.5 * (deduped[-1][0] + pt[0]),
                    0.5 * (deduped[-1][1] + pt[1]),
                )
            else:
                deduped.append(pt)

        if len(deduped) < 2:
            continue

        spacing = max(tolerance * 0.75, 0.4)
        resampled = _resample_path(deduped, spacing)
        if len(resampled) >= 2:
            smoothed.append(resampled)

    return smoothed


def _path_length(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    length = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length += math.hypot(x2 - x1, y2 - y1)
    return length


def _simplify_path(points: Sequence[Point], tolerance: float) -> Path:
    if len(points) < 3 or tolerance <= 0.0:
        return list(points)

    first, last = points[0], points[-1]
    max_distance = 0.0
    index = -1
    for i in range(1, len(points) - 1):
        distance = _point_line_distance(points[i], first, last)
        if distance > max_distance:
            max_distance = distance
            index = i

    if max_distance > tolerance and index != -1:
        left = _simplify_path(points[: index + 1], tolerance)
        right = _simplify_path(points[index:], tolerance)
        return left[:-1] + right
    return [first, last]


def _distance_sq(a: Point, b: Point) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _resample_path(points: Sequence[Point], spacing: float) -> Path:
    if spacing <= 0.0 or len(points) < 2:
        return list(points)

    result: Path = [points[0]]
    distance_since_last = 0.0

    for start, end in zip(points, points[1:]):
        seg_len = math.hypot(end[0] - start[0], end[1] - start[1])
        if seg_len == 0.0:
            continue
        direction = ((end[0] - start[0]) / seg_len, (end[1] - start[1]) / seg_len)
        travelled = 0.0

        while distance_since_last + seg_len - travelled >= spacing - 1e-9:
            step = spacing - distance_since_last
            if step <= 1e-9:
                distance_since_last = 0.0
                continue
            travelled += step
            point = (
                start[0] + direction[0] * travelled,
                start[1] + direction[1] * travelled,
            )
            if _distance_sq(result[-1], point) > 1e-9:
                result.append(point)
            distance_since_last = 0.0

        distance_since_last += seg_len - travelled

    if _distance_sq(result[-1], points[-1]) > 1e-9:
        result.append(points[-1])

    return result


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(x0 - x1, y0 - y1)
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(x0 - proj_x, y0 - proj_y)
