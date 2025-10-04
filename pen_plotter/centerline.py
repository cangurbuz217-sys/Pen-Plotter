"""Utilities to approximate single-stroke centerlines from filled outlines."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

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
    px_per_mm = min(30.0, max(10.0, 2.5 / max(tolerance, 1e-3)))

    width_mm = (max_x - min_x) + 2.0 * margin_mm
    height_mm = (max_y - min_y) + 2.0 * margin_mm
    width_px = max(int(math.ceil(width_mm * px_per_mm)), 8)
    height_px = max(int(math.ceil(height_mm * px_per_mm)), 8)

    raster = Image.new("1", (width_px, height_px), 0)
    draw = ImageDraw.Draw(raster)
    sorted_loops = sorted(closed_paths, key=lambda p: abs(_signed_area(p)), reverse=True)
    if not sorted_loops:
        return open_paths

    reference_area = _signed_area(sorted_loops[0])
    reference_sign = 1.0 if reference_area >= 0.0 else -1.0

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
        fill_value = 1 if math.copysign(1.0, loop_area) == reference_sign else 0
        draw.polygon(draw_points, fill=fill_value)

    bitmap = np.array(raster, dtype=np.uint8)
    if not bitmap.any():
        return open_paths

    thinned = _zhang_suen_thinning(bitmap)
    if not thinned.any():
        return open_paths

    context = _RasterContext(
        min_x=min_x,
        max_y=max_y,
        margin_mm=margin_mm,
        px_per_mm=px_per_mm,
        height=height_px,
    )

    centerlines = _skeleton_to_paths(thinned, context, tolerance)
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


def _zhang_suen_thinning(image: np.ndarray) -> np.ndarray:
    skeleton = image.copy()
    skeleton[skeleton != 0] = 1
    changed = True
    rows, cols = skeleton.shape

    while changed:
        changed = False
        to_remove: List[Tuple[int, int]] = []
        for y in range(1, rows - 1):
            for x in range(1, cols - 1):
                if skeleton[y, x] == 0:
                    continue
                neighbours = _neighbour_values(skeleton, x, y)
                transitions = _transitions(neighbours)
                count = sum(neighbours)
                if not (2 <= count <= 6 and transitions == 1):
                    continue
                if neighbours[0] * neighbours[2] * neighbours[4] != 0:
                    continue
                if neighbours[2] * neighbours[4] * neighbours[6] != 0:
                    continue
                to_remove.append((x, y))
        if to_remove:
            for x, y in to_remove:
                skeleton[y, x] = 0
            changed = True

        to_remove = []
        for y in range(1, rows - 1):
            for x in range(1, cols - 1):
                if skeleton[y, x] == 0:
                    continue
                neighbours = _neighbour_values(skeleton, x, y)
                transitions = _transitions(neighbours)
                count = sum(neighbours)
                if not (2 <= count <= 6 and transitions == 1):
                    continue
                if neighbours[0] * neighbours[2] * neighbours[6] != 0:
                    continue
                if neighbours[0] * neighbours[4] * neighbours[6] != 0:
                    continue
                to_remove.append((x, y))
        if to_remove:
            for x, y in to_remove:
                skeleton[y, x] = 0
            changed = True

    return skeleton


def _neighbour_values(image: np.ndarray, x: int, y: int) -> List[int]:
    return [
        int(image[y - 1, x]),
        int(image[y - 1, x + 1]),
        int(image[y, x + 1]),
        int(image[y + 1, x + 1]),
        int(image[y + 1, x]),
        int(image[y + 1, x - 1]),
        int(image[y, x - 1]),
        int(image[y - 1, x - 1]),
    ]


def _transitions(neighbours: Sequence[int]) -> int:
    transitions = 0
    for i in range(len(neighbours)):
        if neighbours[i] == 0 and neighbours[(i + 1) % len(neighbours)] == 1:
            transitions += 1
    return transitions


def _skeleton_to_paths(
    skeleton: np.ndarray, context: _RasterContext, tolerance: float
) -> List[Path]:
    height, width = skeleton.shape
    node_neighbors: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for y in range(height):
        for x in range(width):
            if skeleton[y, x] == 0:
                continue
            neighbours: List[Tuple[int, int]] = []
            for dx, dy in _NEIGHBOURS:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and skeleton[ny, nx] != 0:
                    neighbours.append((nx, ny))
            if not neighbours:
                continue
            node_neighbors[(x, y)] = neighbours

    if not node_neighbors:
        return []

    visited_edges: set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    paths: List[Path] = []

    def as_edge(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return (a, b) if a <= b else (b, a)

    def record_path(pixel_points: List[Tuple[int, int]]) -> None:
        if len(pixel_points) < 2:
            return
        mm_points = [context.to_mm(pt) for pt in pixel_points]
        simplified = _simplify_path(mm_points, tolerance * 0.5)
        if _path_length(simplified) < max(0.2, tolerance):
            return
        paths.append(simplified)

    def walk(start: Tuple[int, int], next_node: Tuple[int, int]) -> None:
        pixel_path = [start]
        current = start
        previous = None
        while True:
            edge = as_edge(current, next_node)
            if edge in visited_edges:
                break
            visited_edges.add(edge)
            pixel_path.append(next_node)
            neighbours = [n for n in node_neighbors[next_node] if n != current]
            if len(neighbours) != 1:
                record_path(pixel_path)
                if neighbours:
                    for neighbour in neighbours:
                        if as_edge(next_node, neighbour) not in visited_edges:
                            walk(next_node, neighbour)
                return
            previous, current = current, next_node
            next_node = neighbours[0]

        record_path(pixel_path)

    endpoints = [
        node
        for node, neighbours in node_neighbors.items()
        if len(neighbours) == 1
    ]

    for node in endpoints:
        for neighbour in node_neighbors[node]:
            if as_edge(node, neighbour) not in visited_edges:
                walk(node, neighbour)

    for node, neighbours in node_neighbors.items():
        if len(neighbours) == 2:
            neighbour = neighbours[0]
            if as_edge(node, neighbour) not in visited_edges:
                walk(node, neighbour)

    return paths


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
