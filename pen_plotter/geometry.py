"""Shared geometry helpers for converting layout paths."""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

PathType = List[Tuple[float, float]]


def translate_paths(paths: Sequence[PathType], dx: float, dy: float) -> List[PathType]:
    """Translate every point in ``paths`` by ``dx`` and ``dy`` millimetres."""

    if dx == 0.0 and dy == 0.0:
        return [list(path) for path in paths]
    return [[(x + dx, y + dy) for x, y in path] for path in paths]


def measure_paths(paths: Iterable[PathType]) -> tuple[float, float, float, float, float]:
    """Return ``(min_x, min_y, max_x, max_y, total_length)`` for ``paths``."""

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    total_length = 0.0

    for path in paths:
        if not path:
            continue
        prev_x, prev_y = path[0]
        min_x = min(min_x, prev_x)
        min_y = min(min_y, prev_y)
        max_x = max(max_x, prev_x)
        max_y = max(max_y, prev_y)
        for x, y in path[1:]:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            total_length += ((x - prev_x) ** 2 + (y - prev_y) ** 2) ** 0.5
            prev_x, prev_y = x, y

    if min_x == float("inf"):
        return 0.0, 0.0, 0.0, 0.0, 0.0

    return min_x, min_y, max_x, max_y, total_length
