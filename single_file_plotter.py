#!/usr/bin/env python3
"""Tek dosyalık pen plotter G-code üreticisi.

Bu dosyayı bir yere (örneğin `plotter.py`) kaydedin ve aşağıdaki adımları
izleyin:

1. Python 3 yüklü olduğundan emin olun.
2. Terminalde bu dosyanın bulunduğu klasöre gelin.
3. Gerekli kütüphaneyi kurun: ``pip install fonttools``
4. Aşağıdaki gibi bir komutla G-code üretin:

   ``python plotter.py --text "Merhaba" --font "/tam/yol/font.ttf" --output ciktim.gcode``

Varsayılan ayarları değiştirmek için `python plotter.py --help` komutunu
çalıştırabilirsiniz.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from fontTools.misc import bezierTools
from fontTools.pens.basePen import BasePen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

Point = Tuple[float, float]
PathType = List[Point]
PathSequence = Sequence[Point]
_MAX_FLATTEN_DEPTH = 12


class SimpleFontLoader:
    """TrueType fontundan poligon yolları çıkarır."""

    def __init__(self, font_path: Path) -> None:
        self._font = TTFont(str(font_path))
        self._glyph_set = self._font.getGlyphSet()
        self._cmap = self._font.getBestCmap()
        head = self._font["head"]
        self.units_per_em = head.unitsPerEm
        hhea = self._font["hhea"]
        self.ascent = hhea.ascent
        self.descent = hhea.descent
        self._horizontal_metrics = self._font["hmtx"]

    def close(self) -> None:
        self._font.close()

    def __enter__(self) -> "SimpleFontLoader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def glyph_name_for_character(self, character: str) -> str | None:
        return self._cmap.get(ord(character))

    def glyph_paths(
        self,
        glyph_name: str,
        scale: float,
        offset: Tuple[float, float],
        curve_error_units: float,
    ) -> Tuple[float, List[PathType]]:
        glyph = self._glyph_set[glyph_name]
        advance_width, _ = self._horizontal_metrics[glyph_name]
        recording_pen = RecordingPen()
        transform = (scale, 0.0, 0.0, scale, offset[0], offset[1])
        polyline_pen = _PolylinePen(
            glyph_set=self._glyph_set,
            out_pen=TransformPen(recording_pen, transform),
            tolerance=max(curve_error_units, 1e-3),
        )
        glyph.draw(polyline_pen)
        return advance_width * scale, _recording_to_paths(recording_pen.value)


def layout_text(
    text: str,
    font_loader: SimpleFontLoader,
    font_size: float,
    line_spacing: float,
    character_spacing: float,
    curve_tolerance: float,
) -> List[PathType]:
    if font_size <= 0:
        raise ValueError("font_size pozitif olmalı")
    if line_spacing <= 0:
        raise ValueError("line_spacing pozitif olmalı")
    if curve_tolerance <= 0:
        raise ValueError("curve_tolerance pozitif olmalı")

    scale = font_size / font_loader.units_per_em
    curve_error_units = curve_tolerance / scale
    x_offset = 0.0
    y_offset = 0.0
    line_height = (font_loader.ascent - font_loader.descent) * scale * line_spacing

    paths: List[PathType] = []
    for line in text.splitlines():
        for character in line:
            glyph_name = font_loader.glyph_name_for_character(character)
            if glyph_name is None:
                x_offset += font_size * 0.5 + character_spacing
                continue
            advance, glyph_paths = font_loader.glyph_paths(
                glyph_name,
                scale=scale,
                offset=(x_offset, y_offset),
                curve_error_units=curve_error_units,
            )
            paths.extend(glyph_paths)
            x_offset += advance + character_spacing
        x_offset = 0.0
        y_offset -= line_height

    return paths


class _PolylinePen(BasePen):
    """Bézier eğrilerini çizgi segmentlerine çevirir."""

    def __init__(self, glyph_set, out_pen, tolerance: float) -> None:
        super().__init__(glyph_set)
        self._out_pen = out_pen
        self._tolerance = tolerance

    def _moveTo(self, p0: Point) -> None:  # noqa: N802
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
    p0: Point, p1: Point, p2: Point, tolerance: float
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
    p0: Point, p1: Point, p2: Point, p3: Point, tolerance: float
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


def _recording_to_paths(commands: Sequence[Tuple[str, Tuple[Point, ...]]]) -> List[PathType]:
    paths: List[PathType] = []
    current: PathType = []
    start_point: Point | None = None

    for command, points in commands:
        if command == "moveTo":
            if current:
                paths.append(current)
                current = []
            start_point = points[0]
            current.append(points[0])
        elif command == "lineTo":
            current.append(points[0])
        elif command == "closePath":
            if start_point is not None:
                current.append(start_point)
            if current:
                paths.append(current)
            current = []
            start_point = None
        elif command == "endPath":
            if current:
                paths.append(current)
            current = []
            start_point = None

    if current:
        paths.append(current)

    return [path for path in paths if len(path) > 1]


class PlotterSettings:
    def __init__(
        self,
        travel_height: float = 5.0,
        drawing_height: float = 0.0,
        travel_feed_rate: float = 3000.0,
        drawing_feed_rate: float = 1200.0,
        comment: str = "Generated by single_file_plotter",
    ) -> None:
        self.travel_height = travel_height
        self.drawing_height = drawing_height
        self.travel_feed_rate = travel_feed_rate
        self.drawing_feed_rate = drawing_feed_rate
        self.comment = comment


def paths_to_gcode(paths: Iterable[PathSequence], settings: PlotterSettings) -> List[str]:
    gcode: List[str] = []
    gcode.append(f"; {settings.comment}")
    gcode.append("G90 ; Absolute positioning")
    gcode.append("G21 ; Units in millimeters")
    gcode.append(f"G0 Z{settings.travel_height:.3f}")

    current_feed: float | None = None
    current_z = settings.travel_height
    pen_is_down = False

    for path in paths:
        path = list(path)
        if len(path) < 2:
            continue

        start = path[0]
        gcode.append(_format_move("G0", start, None))
        if current_z != settings.travel_height:
            gcode.append(f"G0 Z{settings.travel_height:.3f}")
            current_z = settings.travel_height
        if not pen_is_down:
            if current_z != settings.drawing_height:
                gcode.append(
                    _format_z_move(
                        "G1",
                        settings.drawing_height,
                        settings.travel_feed_rate,
                    )
                )
                current_feed = settings.travel_feed_rate
                current_z = settings.drawing_height
            pen_is_down = True

        for point in path[1:]:
            gcode.append(
                _format_move(
                    "G1",
                    point,
                    settings.drawing_feed_rate
                    if current_feed != settings.drawing_feed_rate
                    else None,
                )
            )
            current_feed = settings.drawing_feed_rate

        gcode.append(
            _format_z_move(
                "G1",
                settings.travel_height,
                settings.travel_feed_rate
                if current_feed != settings.travel_feed_rate
                else None,
            )
        )
        current_feed = settings.travel_feed_rate
        current_z = settings.travel_height
        pen_is_down = False

    gcode.append("M2 ; Program end")
    return gcode


def _format_move(command: str, point: Point, feed_rate: float | None) -> str:
    x, y = point
    if feed_rate is not None:
        return f"{command} X{x:.3f} Y{y:.3f} F{feed_rate:.2f}"
    return f"{command} X{x:.3f} Y{y:.3f}"


def _format_z_move(command: str, z: float, feed_rate: float | None) -> str:
    if feed_rate is not None:
        return f"{command} Z{z:.3f} F{feed_rate:.2f}"
    return f"{command} Z{z:.3f}"


def translate_paths(paths: List[PathType], dx: float, dy: float) -> List[PathType]:
    if dx == 0.0 and dy == 0.0:
        return paths
    return [[(x + dx, y + dy) for x, y in path] for path in paths]


def measure_paths(paths: Iterable[PathType]) -> tuple[float, float, float, float, float]:
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
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
            total_length += math.hypot(x - prev_x, y - prev_y)
            prev_x, prev_y = x, y

    if min_x is math.inf:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    return min_x, min_y, max_x, max_y, total_length


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Metni TrueType (.ttf) font kullanarak pen plotter/3B yazıcı için G-code'a dönüştürür."
        )
    )
    parser.add_argument(
        "--text",
        help="G-code'a dönüştürülecek metin. Birden çok satır için tırnak içinde \n kullanın.",
    )
    parser.add_argument(
        "--text-file",
        type=Path,
        help="Metni bir .txt dosyasından okumak için dosya yolu.",
    )
    parser.add_argument(
        "--font",
        required=True,
        type=Path,
        help="Kullanılacak .ttf font dosyasının yolu.",
    )
    parser.add_argument(
        "--font-size",
        type=float,
        default=12.0,
        help="Yazı boyutu (mm). Varsayılan 12 mm.",
    )
    parser.add_argument(
        "--line-spacing",
        type=float,
        default=1.3,
        help="Satırlar arası çarpan (varsayılan 1.3).",
    )
    parser.add_argument(
        "--char-spacing",
        type=float,
        default=0.0,
        help="Harfler arasına eklenecek ekstra boşluk (mm).",
    )
    parser.add_argument(
        "--curve-tolerance",
        type=float,
        default=0.1,
        help="Eğrileri düz çizgilere çevirirken izin verilen hata (mm).",
    )
    parser.add_argument(
        "--travel-height",
        type=float,
        default=5.0,
        help="Kalemin boştaki yüksekliği (mm).",
    )
    parser.add_argument(
        "--drawing-height",
        type=float,
        default=0.0,
        help="Kalemin çizim sırasındaki yüksekliği (mm).",
    )
    parser.add_argument(
        "--travel-feed",
        type=float,
        default=3000.0,
        help="Boşta hareket hızı (mm/dak).",
    )
    parser.add_argument(
        "--drawing-feed",
        type=float,
        default=1200.0,
        help="Çizim hızı (mm/dak).",
    )
    parser.add_argument(
        "--origin-x",
        type=float,
        default=0.0,
        help="Çıkış yolunu X ekseninde kaydır (mm).",
    )
    parser.add_argument(
        "--origin-y",
        type=float,
        default=0.0,
        help="Çıkış yolunu Y ekseninde kaydır (mm).",
    )
    parser.add_argument(
        "--center",
        action="store_true",
        help="Metni 0,0 etrafında ortala.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Çıkış dosyasını yazmadan önce boyut bilgisini göster.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output.gcode"),
        help="Kaydedilecek G-code dosyası (varsayılan output.gcode).",
    )
    return parser


def read_text_argument(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.text_file is not None:
        return args.text_file.read_text(encoding="utf-8")
    if args.text is not None:
        return args.text
    parser.error("Metin girmek için --text kullanın ya da --text-file ile dosya belirtin.")
    raise RuntimeError("unreachable")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    text = read_text_argument(args, parser)

    with SimpleFontLoader(args.font) as font_loader:
        paths = layout_text(
            text,
            font_loader,
            font_size=args.font_size,
            line_spacing=args.line_spacing,
            character_spacing=args.char_spacing,
            curve_tolerance=args.curve_tolerance,
        )

    if args.center:
        min_x, min_y, max_x, max_y, _ = measure_paths(paths)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        paths = translate_paths(paths, -center_x, -center_y)

    if args.origin_x != 0.0 or args.origin_y != 0.0:
        paths = translate_paths(paths, args.origin_x, args.origin_y)

    min_x, min_y, max_x, max_y, total_length = measure_paths(paths)

    if args.preview:
        print(
            "Boyut bilgisi:\n"
            f"- X aralığı: {min_x:.2f} mm — {max_x:.2f} mm\n"
            f"- Y aralığı: {min_y:.2f} mm — {max_y:.2f} mm\n"
            f"- Toplam çizim uzunluğu: {total_length:.2f} mm"
        )

    settings = PlotterSettings(
        travel_height=args.travel_height,
        drawing_height=args.drawing_height,
        travel_feed_rate=args.travel_feed,
        drawing_feed_rate=args.drawing_feed,
        comment="Generated by single_file_plotter",
    )

    gcode_lines = paths_to_gcode(paths, settings)
    args.output.write_text("\n".join(gcode_lines) + "\n", encoding="utf-8")
    print(f"G-code '{args.output}' dosyasına yazıldı.")


if __name__ == "__main__":
    main()
