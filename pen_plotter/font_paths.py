"""Utilities to convert text strings into geometric paths using TrueType fonts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Sequence, Tuple

from fontTools.misc import bezierTools
from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

from .centerline import outlines_to_centerlines

Point = Tuple[float, float]
Path = List[Point]
_MAX_FLATTEN_DEPTH = 12


@dataclass
class GlyphPaths:
    """A collection of polyline paths for a single glyph."""

    advance_width: float
    paths: List[Path]


@dataclass
class LayoutSettings:
    """Text layout configuration."""

    font_size: float = 10.0
    line_spacing: float = 1.3
    character_spacing: float = 0.0
    curve_tolerance: float = 0.1
    stroke_mode: Literal["outline", "centerline"] = "centerline"


class FontLoader:
    """Loads glyph outlines from a TrueType font and converts them into polylines."""

    def __init__(self, font_path: str) -> None:
        self._font = TTFont(font_path)
        self._glyph_set = self._font.getGlyphSet()
        self._cmap = self._font.getBestCmap()
        head_table = self._font["head"]
        self.units_per_em = head_table.unitsPerEm
        hhea = self._font["hhea"]
        self.ascent = hhea.ascent
        self.descent = hhea.descent
        self._horizontal_metrics = self._font["hmtx"]
        self._outline_cache: dict[Tuple[str, float, float], GlyphPaths] = {}
        self._centerline_cache: dict[
            Tuple[str, float, float, float], List[Path]
        ] = {}

    def close(self) -> None:
        self._font.close()

    def __enter__(self) -> "FontLoader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def glyph_name_for_character(self, character: str) -> str | None:
        code_point = ord(character)
        return self._cmap.get(code_point)

    def glyph_paths(
        self,
        glyph_name: str,
        scale: float,
        offset: Tuple[float, float],
        curve_error_units: float,
    ) -> GlyphPaths:
        cache_key = (glyph_name, scale, curve_error_units)
        cached = self._outline_cache.get(cache_key)
        if cached is None:
            glyph = self._glyph_set[glyph_name]
            advance_width, _ = self._horizontal_metrics[glyph_name]
            recording_pen = RecordingPen()
            transform = (scale, 0.0, 0.0, scale, 0.0, 0.0)
            polyline_pen = _PolylinePen(
                glyph_set=self._glyph_set,
                out_pen=TransformPen(recording_pen, transform),
                tolerance=max(curve_error_units, 1e-3),
            )
            glyph.draw(polyline_pen)
            cached = GlyphPaths(
                advance_width=advance_width * scale,
                paths=_recording_to_paths(recording_pen.value),
            )
            self._outline_cache[cache_key] = cached

        if offset == (0.0, 0.0):
            translated_paths = [list(path) for path in cached.paths]
        else:
            translated_paths = [
                [(x + offset[0], y + offset[1]) for x, y in path]
                for path in cached.paths
            ]

        return GlyphPaths(advance_width=cached.advance_width, paths=translated_paths)

    def glyph_centerline_paths(
        self,
        glyph_name: str,
        scale: float,
        curve_error_units: float,
        tolerance_mm: float,
    ) -> List[Path]:
        cache_key = (glyph_name, scale, curve_error_units, tolerance_mm)
        cached = self._centerline_cache.get(cache_key)
        if cached is not None:
            return [list(path) for path in cached]

        outline = self.glyph_paths(
            glyph_name,
            scale=scale,
            offset=(0.0, 0.0),
            curve_error_units=curve_error_units,
        )
        centerlines = outlines_to_centerlines(outline.paths, tolerance_mm)
        self._centerline_cache[cache_key] = [list(path) for path in centerlines]
        return centerlines


def layout_text(
    text: str,
    font_loader: FontLoader,
    settings: LayoutSettings,
) -> List[Path]:
    """Converts ``text`` into a list of polyline paths."""

    if settings.font_size <= 0:
        raise ValueError("font_size must be positive")
    if settings.line_spacing <= 0:
        raise ValueError("line_spacing must be positive")
    if settings.curve_tolerance <= 0:
        raise ValueError("curve_tolerance must be positive")

    scale = settings.font_size / font_loader.units_per_em
    if scale == 0:
        raise ValueError("Invalid font configuration resulting in zero scale")
    curve_error_units = settings.curve_tolerance / scale
    x_offset = 0.0
    y_offset = 0.0
    line_height = (
        (font_loader.ascent - font_loader.descent)
        * scale
        * settings.line_spacing
    )
    all_paths: List[Path] = []

    for line in text.splitlines():
        for character in line:
            glyph_name = font_loader.glyph_name_for_character(character)
            if glyph_name is None:
                average_advance = settings.font_size * 0.5
                x_offset += average_advance + settings.character_spacing
                continue

            glyph_outline = font_loader.glyph_paths(
                glyph_name,
                scale=scale,
                offset=(0.0, 0.0),
                curve_error_units=curve_error_units,
            )

            if settings.stroke_mode == "centerline":
                base_paths = font_loader.glyph_centerline_paths(
                    glyph_name,
                    scale=scale,
                    curve_error_units=curve_error_units,
                    tolerance_mm=settings.curve_tolerance,
                )
            else:
                base_paths = glyph_outline.paths

            translated_paths = [
                [(x + x_offset, y + y_offset) for x, y in path]
                for path in base_paths
            ]

            all_paths.extend(translated_paths)
            x_offset += glyph_outline.advance_width + settings.character_spacing

        x_offset = 0.0
        y_offset -= line_height

    return all_paths


class _PolylinePen(BasePen):
    """Pen that approximates curves with line segments."""

    def __init__(self, glyph_set, out_pen, tolerance: float) -> None:
        super().__init__(glyph_set)
        self._out_pen = out_pen
        self._tolerance = tolerance

    def _moveTo(self, p0: Point) -> None:  # noqa: N802 (BasePen naming)
        self._out_pen.moveTo(p0)

    def _lineTo(self, p1: Point) -> None:  # noqa: N802
        self._out_pen.lineTo(p1)

    def _curveToOne(self, p1: Point, p2: Point, p3: Point) -> None:  # noqa: N802
        start = self._getCurrentPoint()
        for point in _flatten_cubic_segment(start, p1, p2, p3, self._tolerance):
            self._out_pen.lineTo(point)

    def _qCurveToOne(self, p1: Point, p2: Point) -> None:  # noqa: N802
        start = self._getCurrentPoint()
        for point in _flatten_quadratic_segment(start, p1, p2, self._tolerance):
            self._out_pen.lineTo(point)

    def _closePath(self) -> None:  # noqa: N802
        self._out_pen.closePath()

    def _endPath(self) -> None:  # noqa: N802
        self._out_pen.endPath()


def _flatten_quadratic_segment(
    p0: Point,
    p1: Point,
    p2: Point,
    tolerance: float,
) -> List[Point]:
    result: List[Point] = []
    _flatten_quadratic_recursive(p0, p1, p2, tolerance, result, 0)
    return result


def _flatten_quadratic_recursive(
    p0: Point,
    p1: Point,
    p2: Point,
    tolerance: float,
    result: List[Point],
    depth: int,
) -> None:
    if depth >= _MAX_FLATTEN_DEPTH or _distance_point_to_segment(p1, p0, p2) <= tolerance:
        result.append(p2)
        return
    left, right = bezierTools.splitQuadraticAtT(p0, p1, p2, 0.5)
    _flatten_quadratic_recursive(left[0], left[1], left[2], tolerance, result, depth + 1)
    _flatten_quadratic_recursive(right[0], right[1], right[2], tolerance, result, depth + 1)


def _flatten_cubic_segment(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    tolerance: float,
) -> List[Point]:
    result: List[Point] = []
    _flatten_cubic_recursive(p0, p1, p2, p3, tolerance, result, 0)
    return result


def _flatten_cubic_recursive(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    tolerance: float,
    result: List[Point],
    depth: int,
) -> None:
    if depth >= _MAX_FLATTEN_DEPTH or (
        _distance_point_to_segment(p1, p0, p3) <= tolerance
        and _distance_point_to_segment(p2, p0, p3) <= tolerance
    ):
        result.append(p3)
        return
    left, right = bezierTools.splitCubicAtT(p0, p1, p2, p3, 0.5)
    _flatten_cubic_recursive(left[0], left[1], left[2], left[3], tolerance, result, depth + 1)
    _flatten_cubic_recursive(right[0], right[1], right[2], right[3], tolerance, result, depth + 1)


def _distance_point_to_segment(point: Point, start: Point, end: Point) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx = x1 + t * dx
    cy = y1 + t * dy
    return math.hypot(px - cx, py - cy)


def _recording_to_paths(commands: Sequence[Tuple[str, Tuple[Point, ...]]]) -> List[Path]:
    paths: List[Path] = []
    current_path: Path = []
    start_point: Point | None = None

    for command, points in commands:
        if command == "moveTo":
            if current_path:
                paths.append(current_path)
                current_path = []
            start_point = points[0]
            current_path.append(points[0])
        elif command == "lineTo":
            current_path.append(points[0])
        elif command == "closePath":
            if start_point is not None:
                current_path.append(start_point)
            if current_path:
                paths.append(current_path)
            current_path = []
            start_point = None
        elif command == "endPath":
            if current_path:
                paths.append(current_path)
            current_path = []
            start_point = None

    if current_path:
        paths.append(current_path)

    return [path for path in paths if len(path) > 1]
