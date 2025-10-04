#!/usr/bin/env python3
"""Tek dosyalık pen plotter G-code üreticisi ve grafik arayüzü.

Kurulum (Windows için önerilen adımlar):

1. Bu dosyanın tamamını örneğin ``C:\\Users\\cangu\\Desktop\\plotter.py``
   konumuna kaydedin.
2. ``pip install fonttools`` komutuyla gerekli bağımlılığı yükleyin.
3. Dosyayı çift tıklayarak ya da ``python plotter.py`` komutuyla çalıştırın.
4. Açılan "Pen Plotter Studio" penceresinden metni yazın, ``.ttf`` fontu
   seçin, kalem/Z ayarlarını girin ve G-code çıktısını kaydedin.

Komut satırı tercih edenler için aynı dosya ``--help`` parametresiyle
çağrıldığında klasik CLI modu da kullanılabilir.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

try:  # Tkinter her sistemde hazır olmayabilir
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - GUI dışı ortamlarda
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

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
        travel_feed_rate: float = 50.0,
        drawing_feed_rate: float = 20.0,
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
            gcode.append(_format_z_move("G0", settings.travel_height, None))
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
                "G0",
                settings.travel_height,
                settings.travel_feed_rate
                if current_feed != settings.travel_feed_rate
                else None,
            )
        )
        current_feed = settings.travel_feed_rate
        current_z = settings.travel_height
        pen_is_down = False

    gcode.append(_format_z_move("G0", settings.travel_height, None))
    gcode.append("M2 ; Program end")
    return gcode


def _format_move(command: str, point: Point, feed_rate: float | None) -> str:
    x, y = point
    if feed_rate is not None:
        feed_mm_min = feed_rate * 60.0
        return f"{command} X{x:.3f} Y{y:.3f} F{feed_mm_min:.2f}"
    return f"{command} X{x:.3f} Y{y:.3f}"


def _format_z_move(command: str, z: float, feed_rate: float | None) -> str:
    if feed_rate is not None:
        feed_mm_min = feed_rate * 60.0
        return f"{command} Z{z:.3f} F{feed_mm_min:.2f}"
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
        default=50.0,
        help="Boşta hareket hızı (mm/sn).",
    )
    parser.add_argument(
        "--drawing-feed",
        type=float,
        default=20.0,
        help="Çizim hızı (mm/sn).",
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
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        run_gui_mode()
        return

    parser = build_parser()
    args = parser.parse_args(argv)
    text = read_text_argument(args, parser)
    generate_and_save_gcode(text, args)


def generate_and_save_gcode(text: str, args: argparse.Namespace) -> None:
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



if tk is not None:

    class _GUITextBlock:
        def __init__(
            self,
            app: "_PenPlotterStudio",
            uid: int,
            initial_text: str,
        ) -> None:
            self.app = app
            self.uid = uid
            self.frame = ttk.Frame(app.blocks_container, padding=(8, 8))
            self.header_var = tk.StringVar(value="")
            self.position_var = tk.StringVar(value="Pozisyon: X=0.0 mm | Y=0.0 mm")
            header = ttk.Frame(self.frame)
            header.pack(fill="x", pady=(0, 6))
            ttk.Label(
                header,
                textvariable=self.header_var,
                font=("TkDefaultFont", 10, "bold"),
            ).pack(side="left")
            ttk.Label(header, textvariable=self.position_var).pack(side="left", padx=(8, 0))
            ttk.Button(
                header,
                text="✕",
                width=3,
                command=lambda: app.remove_block(self),
            ).pack(side="right")

            controls = ttk.Frame(self.frame)
            controls.pack(fill="x", pady=(0, 6))
            controls.columnconfigure(0, weight=1)
            controls.columnconfigure(1, weight=1)
            controls.columnconfigure(2, weight=1)

            self.font_size_var = tk.StringVar(value="14")
            self.line_spacing_var = tk.StringVar(value="1.3")
            self.char_spacing_var = tk.StringVar(value="0")

            ttk.Label(controls, text="Boyut (mm)").grid(column=0, row=0, sticky="w")
            ttk.Entry(controls, textvariable=self.font_size_var, width=8).grid(
                column=0,
                row=1,
                sticky="ew",
                padx=(0, 6),
            )

            ttk.Label(controls, text="Satır aralığı").grid(column=1, row=0, sticky="w")
            ttk.Entry(controls, textvariable=self.line_spacing_var, width=8).grid(
                column=1,
                row=1,
                sticky="ew",
                padx=(0, 6),
            )

            ttk.Label(controls, text="Harf boşluğu (mm)").grid(column=2, row=0, sticky="w")
            ttk.Entry(controls, textvariable=self.char_spacing_var, width=8).grid(
                column=2,
                row=1,
                sticky="ew",
            )

            self.text_widget = tk.Text(self.frame, height=4, wrap="word")
            self.text_widget.pack(fill="both", expand=True)
            if initial_text:
                self.text_widget.insert("1.0", initial_text)
            self.text_widget.edit_modified(False)
            self.text_widget.bind("<<Modified>>", self._on_text_modified)

            for variable in (
                self.font_size_var,
                self.line_spacing_var,
                self.char_spacing_var,
            ):
                variable.trace_add("write", lambda *_: app.schedule_preview())

            self.translation_x = 10.0
            self.translation_y = 10.0
            self.local_bounds: tuple[float, float, float, float] | None = None
            self.current_bounds: tuple[float, float, float, float] | None = None
            self.color = "#1f77b4"

        def _on_text_modified(self, _event: tk.Event) -> None:
            if self.text_widget.edit_modified():
                self.text_widget.edit_modified(False)
                self.app.schedule_preview()

        def set_display_index(self, index: int, color: str) -> None:
            self.header_var.set(f"Metin Bloğu {index}")
            self.color = color

        def update_position_label(self) -> None:
            self.position_var.set(
                f"Pozisyon: X={self.translation_x:.1f} mm | Y={self.translation_y:.1f} mm"
            )

        def destroy(self) -> None:
            self.frame.destroy()


    class _PenPlotterStudio:
        CANVAS_BG = "#f6f7fb"
        BLOCK_COLORS = [
            "#1f77b4",
            "#d62728",
            "#2ca02c",
            "#9467bd",
            "#ff7f0e",
            "#17becf",
        ]

        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            root.title("Pen Plotter Studio")
            root.minsize(980, 660)

            self.hardware_defaults = {
                "bed_x": "235",
                "bed_y": "235",
                "pen_offset_x": "0",
                "pen_offset_y": "0",
                "pen_up": "5",
                "pen_down": "0",
                "travel_feed": "50",
                "drawing_feed": "20",
            }
            self.hardware_defaults_float = {
                key: float(value) for key, value in self.hardware_defaults.items()
            }
            self.hardware_labels = {
                "bed_x": "Bed X (mm)",
                "bed_y": "Bed Y (mm)",
                "pen_offset_x": "Pen offset X (mm)",
                "pen_offset_y": "Pen offset Y (mm)",
                "pen_up": "Kalem yukarı (mm)",
                "pen_down": "Kalem aşağı (mm)",
                "travel_feed": "Boşta hız (mm/sn)",
                "drawing_feed": "Çizim hızı (mm/sn)",
            }

            self.hardware_vars = {
                key: tk.StringVar(value=value) for key, value in self.hardware_defaults.items()
            }
            self.curve_tolerance_var = tk.StringVar(value="0.1")
            self.font_path_var = tk.StringVar(value="")

            self.status_var = tk.StringVar(value="Hazır")
            self.metrics_var = tk.StringVar(value="Önizleme bekleniyor.")

            self.blocks: list[_GUITextBlock] = []
            self.block_uid_counter = 1
            self.block_bounds_mm: dict[int, tuple[float, float, float, float]] = {}
            self.preview_paths: List[PathType] = []
            self.preview_settings: PlotterSettings | None = None
            self.preview_metrics: tuple[float, float, float, float, float] | None = None
            self.preview_pen_offset = (0.0, 0.0)
            self.current_bed_size = (
                self.hardware_defaults_float["bed_x"],
                self.hardware_defaults_float["bed_y"],
            )
            self.canvas_transform = (1.0, 24.0, 24.0)
            self.drag_block: _GUITextBlock | None = None
            self.drag_offset = (0.0, 0.0)
            self._preview_pending = False

            self.canvas_width = 640
            self.canvas_height = 540

            self._build_ui()
            self.add_block("Pen Plotter Studio'ya hoş geldiniz!")
            self.schedule_preview()

        def _build_ui(self) -> None:
            main = ttk.Frame(self.root, padding=16)
            main.grid(column=0, row=0, sticky="nsew")
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)
            main.columnconfigure(0, weight=0)
            main.columnconfigure(1, weight=1)
            main.rowconfigure(0, weight=1)
            main.rowconfigure(1, weight=0)

            controls = ttk.Frame(main)
            controls.grid(column=0, row=0, sticky="nsw", padx=(0, 16))
            controls.columnconfigure(0, weight=1)
            controls.rowconfigure(2, weight=1)

            ttk.Label(
                controls,
                text="Pen Plotter Studio",
                font=("TkDefaultFont", 16, "bold"),
            ).grid(column=0, row=0, sticky="w", pady=(0, 12))

            hardware_frame = ttk.LabelFrame(controls, text="Hardware setup")
            hardware_frame.grid(column=0, row=1, sticky="ew", pady=(0, 12))
            for i in range(4):
                hardware_frame.columnconfigure(i, weight=1)

            self._add_hardware_entry(hardware_frame, "bed_x", 0, 0)
            self._add_hardware_entry(hardware_frame, "bed_y", 0, 1)
            self._add_hardware_entry(hardware_frame, "pen_offset_x", 1, 0)
            self._add_hardware_entry(hardware_frame, "pen_offset_y", 1, 1)
            self._add_hardware_entry(hardware_frame, "pen_up", 2, 0)
            self._add_hardware_entry(hardware_frame, "pen_down", 2, 1)
            self._add_hardware_entry(hardware_frame, "travel_feed", 3, 0)
            self._add_hardware_entry(hardware_frame, "drawing_feed", 3, 1)

            ttk.Label(hardware_frame, text="Eğri toleransı (mm)").grid(
                column=0,
                row=4,
                sticky="w",
                pady=(8, 0),
            )
            ttk.Entry(hardware_frame, textvariable=self.curve_tolerance_var, width=8).grid(
                column=0,
                row=5,
                sticky="ew",
                pady=(0, 8),
            )
            self.curve_tolerance_var.trace_add("write", lambda *_: self.schedule_preview())

            font_frame = ttk.LabelFrame(controls, text="Your text")
            font_frame.grid(column=0, row=2, sticky="nsew")
            font_frame.columnconfigure(0, weight=1)
            font_frame.rowconfigure(2, weight=1)

            ttk.Button(font_frame, text="TTF font seç", command=self.choose_font).grid(
                column=0,
                row=0,
                sticky="ew",
                pady=(4, 6),
            )
            ttk.Label(font_frame, textvariable=self.font_path_var, wraplength=240, justify="left").grid(
                column=0,
                row=1,
                sticky="w",
                pady=(0, 8),
            )

            blocks_panel = ttk.Frame(font_frame)
            blocks_panel.grid(column=0, row=2, sticky="nsew")
            blocks_panel.columnconfigure(0, weight=1)
            blocks_panel.rowconfigure(1, weight=1)

            ttk.Button(
                blocks_panel,
                text="Metin bloğu ekle",
                command=self.add_block,
            ).grid(column=0, row=0, sticky="ew", pady=(0, 8))

            self.blocks_container = ttk.Frame(blocks_panel)
            self.blocks_container.grid(column=0, row=1, sticky="nsew")
            self.blocks_container.columnconfigure(0, weight=1)

            preview_frame = ttk.Frame(main)
            preview_frame.grid(column=1, row=0, sticky="nsew")
            preview_frame.columnconfigure(0, weight=1)
            preview_frame.rowconfigure(0, weight=1)

            self.canvas = tk.Canvas(
                preview_frame,
                background=self.CANVAS_BG,
                highlightthickness=0,
            )
            self.canvas.grid(column=0, row=0, sticky="nsew")
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
            self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

            ttk.Label(preview_frame, textvariable=self.metrics_var, anchor="center").grid(
                column=0,
                row=1,
                sticky="ew",
                pady=(12, 0),
            )

            footer = ttk.Frame(main)
            footer.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(12, 0))
            footer.columnconfigure(0, weight=1)
            footer.columnconfigure(1, weight=0)
            footer.columnconfigure(2, weight=0)

            ttk.Label(footer, textvariable=self.status_var, anchor="w").grid(
                column=0,
                row=0,
                sticky="w",
            )
            ttk.Button(footer, text="Önizlemeyi güncelle", command=self.force_refresh).grid(
                column=1,
                row=0,
                padx=(12, 6),
            )
            ttk.Button(footer, text="G-code kaydet", command=self.save_gcode).grid(
                column=2,
                row=0,
            )

            self.root.bind("<Control-s>", lambda _event: self.save_gcode())
            self.root.bind("<Control-Return>", lambda _event: self.force_refresh())

        def _add_hardware_entry(self, parent: ttk.Frame, key: str, row: int, column: int) -> None:
            ttk.Label(parent, text=self.hardware_labels[key]).grid(
                column=column,
                row=row * 2,
                sticky="w",
                pady=(4 if row else 0, 0),
                padx=(0, 8),
            )
            ttk.Entry(parent, textvariable=self.hardware_vars[key], width=10).grid(
                column=column,
                row=row * 2 + 1,
                sticky="ew",
                padx=(0, 8),
                pady=(0, 4),
            )
            self.hardware_vars[key].trace_add("write", lambda *_: self.schedule_preview())

        def choose_font(self) -> None:
            if filedialog is None:
                return
            file_path = filedialog.askopenfilename(
                title="TTF font seç",
                filetypes=[("TrueType Font", "*.ttf"), ("Tüm dosyalar", "*.*")],
            )
            if file_path:
                self.font_path_var.set(file_path)
                self.status_var.set(f"Seçilen font: {Path(file_path).name}")
                self.schedule_preview()

        def add_block(self, initial_text: str = "") -> None:
            uid = self.block_uid_counter
            self.block_uid_counter += 1
            block = _GUITextBlock(self, uid, initial_text)
            bed_y = self._safe_float(self.hardware_vars["bed_y"], 235.0)
            offset = 25.0 * len(self.blocks)
            block.translation_x = 10.0
            block.translation_y = max(10.0, bed_y - 40.0 - offset)
            block.update_position_label()
            block.frame.grid(column=0, row=len(self.blocks), sticky="ew", pady=(0, 12))
            self.blocks.append(block)
            self.update_block_headers()
            self.schedule_preview()

        def remove_block(self, block: _GUITextBlock) -> None:
            if block in self.blocks:
                self.blocks.remove(block)
                block.destroy()
                self.update_block_headers()
                self.schedule_preview()

        def update_block_headers(self) -> None:
            for index, block in enumerate(self.blocks, start=1):
                color = self.BLOCK_COLORS[(index - 1) % len(self.BLOCK_COLORS)]
                block.set_display_index(index, color)
                block.frame.grid_configure(row=index - 1)
                block.update_position_label()

        def _safe_float(self, var: tk.StringVar, fallback: float) -> float:
            raw = var.get().strip().replace(",", ".")
            if not raw:
                return fallback
            try:
                return float(raw)
            except ValueError:
                return fallback

        def schedule_preview(self) -> None:
            if self._preview_pending:
                return
            self._preview_pending = True
            self.root.after(75, self._run_scheduled_preview)

        def _run_scheduled_preview(self) -> None:
            self._preview_pending = False
            self.refresh_preview()

        def force_refresh(self) -> None:
            self.refresh_preview(show_dialog=True)

        def _parse_float(
            self,
            var: tk.StringVar,
            label: str,
            *,
            default: float | None = None,
            min_value: float | None = None,
        ) -> float:
            raw = var.get().strip()
            if not raw and default is not None:
                raw = str(default)
                var.set(raw)
            raw = raw.replace(",", ".")
            try:
                value = float(raw)
            except ValueError as exc:
                raise ValueError(f"{label} için geçerli bir sayı girin.") from exc
            if min_value is not None and value <= min_value:
                if min_value == 0.0:
                    raise ValueError(f"{label} 0'dan büyük olmalı.")
                raise ValueError(f"{label} {min_value} değerinden büyük olmalı.")
            return value

        def refresh_preview(self, show_dialog: bool = False) -> None:
            try:
                font_path_str = self.font_path_var.get().strip()
                if not font_path_str:
                    raise ValueError("Lütfen bir .ttf font dosyası seçin.")
                font_path = Path(font_path_str)

                bed_x = self._parse_float(
                    self.hardware_vars["bed_x"],
                    self.hardware_labels["bed_x"],
                    default=self.hardware_defaults_float["bed_x"],
                    min_value=0.0,
                )
                bed_y = self._parse_float(
                    self.hardware_vars["bed_y"],
                    self.hardware_labels["bed_y"],
                    default=self.hardware_defaults_float["bed_y"],
                    min_value=0.0,
                )
                curve_tolerance = self._parse_float(
                    self.curve_tolerance_var,
                    "Eğri toleransı (mm)",
                    default=0.1,
                    min_value=0.0,
                )
                travel_feed = self._parse_float(
                    self.hardware_vars["travel_feed"],
                    self.hardware_labels["travel_feed"],
                    default=self.hardware_defaults_float["travel_feed"],
                    min_value=0.0,
                )
                drawing_feed = self._parse_float(
                    self.hardware_vars["drawing_feed"],
                    self.hardware_labels["drawing_feed"],
                    default=self.hardware_defaults_float["drawing_feed"],
                    min_value=0.0,
                )
                pen_up = self._parse_float(
                    self.hardware_vars["pen_up"],
                    self.hardware_labels["pen_up"],
                    default=self.hardware_defaults_float["pen_up"],
                )
                pen_down = self._parse_float(
                    self.hardware_vars["pen_down"],
                    self.hardware_labels["pen_down"],
                    default=self.hardware_defaults_float["pen_down"],
                )
                pen_offset_x = self._parse_float(
                    self.hardware_vars["pen_offset_x"],
                    self.hardware_labels["pen_offset_x"],
                    default=self.hardware_defaults_float["pen_offset_x"],
                )
                pen_offset_y = self._parse_float(
                    self.hardware_vars["pen_offset_y"],
                    self.hardware_labels["pen_offset_y"],
                    default=self.hardware_defaults_float["pen_offset_y"],
                )

                self.current_bed_size = (bed_x, bed_y)
                self.preview_pen_offset = (pen_offset_x, pen_offset_y)

                block_results: list[tuple[_GUITextBlock, List[PathType], tuple[float, float, float, float]]] = []
                all_paths: List[PathType] = []
                total_length = 0.0

                with SimpleFontLoader(font_path) as font_loader:
                    for block in self.blocks:
                        text = block.text_widget.get("1.0", "end-1c")
                        if not text.strip():
                            block.local_bounds = None
                            block.current_bounds = None
                            continue
                        font_size = self._parse_float(
                            block.font_size_var,
                            "Boyut (mm)",
                            default=14.0,
                            min_value=0.0,
                        )
                        line_spacing = self._parse_float(
                            block.line_spacing_var,
                            "Satır aralığı",
                            default=1.3,
                            min_value=0.0,
                        )
                        char_spacing = self._parse_float(
                            block.char_spacing_var,
                            "Harf boşluğu (mm)",
                            default=0.0,
                        )

                        raw_paths = layout_text(
                            text,
                            font_loader,
                            font_size=font_size,
                            line_spacing=line_spacing,
                            character_spacing=char_spacing,
                            curve_tolerance=curve_tolerance,
                        )
                        raw_bounds = measure_paths(raw_paths)
                        block.local_bounds = raw_bounds[:4]

                        min_tx = -block.local_bounds[0] if block.local_bounds else block.translation_x
                        max_tx = bed_x - block.local_bounds[2] if block.local_bounds else block.translation_x
                        min_ty = -block.local_bounds[1] if block.local_bounds else block.translation_y
                        max_ty = bed_y - block.local_bounds[3] if block.local_bounds else block.translation_y
                        if block.local_bounds:
                            if min_tx <= max_tx:
                                block.translation_x = min(max(block.translation_x, min_tx), max_tx)
                            if min_ty <= max_ty:
                                block.translation_y = min(max(block.translation_y, min_ty), max_ty)

                        translated_paths = translate_paths(
                            raw_paths,
                            block.translation_x,
                            block.translation_y,
                        )
                        translated_bounds = measure_paths(translated_paths)
                        if translated_bounds[4] == 0.0:
                            block.current_bounds = None
                            continue
                        block.current_bounds = translated_bounds[:4]
                        block.update_position_label()

                        block_results.append((block, translated_paths, translated_bounds[:4]))
                        all_paths.extend(translated_paths)
                        total_length += translated_bounds[4]

                if not all_paths:
                    raise ValueError("En az bir metin bloğu dolu olmalıdır.")

                combined_metrics = measure_paths(all_paths)
                comment = f"Pen Plotter Studio - {font_path.name}"[:80]
                settings = PlotterSettings(
                    travel_height=pen_up,
                    drawing_height=pen_down,
                    travel_feed_rate=travel_feed,
                    drawing_feed_rate=drawing_feed,
                    comment=comment,
                )

                self.preview_paths = all_paths
                self.preview_settings = settings
                self.preview_metrics = combined_metrics

                self._draw_preview(bed_x, bed_y, block_results)
                width = combined_metrics[2] - combined_metrics[0]
                height = combined_metrics[3] - combined_metrics[1]
                self.metrics_var.set(
                    "Genişlik: {:.2f} mm | Yükseklik: {:.2f} mm | Yol uzunluğu: {:.2f} mm".format(
                        width,
                        height,
                        total_length,
                    )
                )
                self.status_var.set("Önizleme güncellendi.")
            except Exception as exc:
                self.preview_paths = []
                self.preview_settings = None
                self.preview_metrics = None
                self.block_bounds_mm.clear()
                self.canvas.delete("all")
                self.canvas.create_text(
                    self.canvas_width / 2,
                    self.canvas_height / 2,
                    text=str(exc),
                    fill="#b94a48",
                )
                self.metrics_var.set("Önizleme hazırlanamadı.")
                self.status_var.set(f"Hata: {exc}")
                if show_dialog and messagebox is not None:
                    messagebox.showerror("Önizleme hatası", str(exc))

        def _draw_preview(
            self,
            bed_x: float,
            bed_y: float,
            block_results: list[tuple[_GUITextBlock, List[PathType], tuple[float, float, float, float]]],
        ) -> None:
            canvas = self.canvas
            canvas.delete("all")
            width = self.canvas_width
            height = self.canvas_height

            margin = 36.0
            if bed_x <= 0 or bed_y <= 0:
                canvas.create_text(
                    width / 2,
                    height / 2,
                    text="Bed boyutlarını pozitif girin.",
                    fill="#b94a48",
                )
                return

            scale_x = (width - margin * 2) / bed_x if bed_x > 0 else 1.0
            scale_y = (height - margin * 2) / bed_y if bed_y > 0 else 1.0
            scale = max(min(scale_x, scale_y), 1e-3)
            offset_x = (width - bed_x * scale) / 2.0
            offset_y = (height - bed_y * scale) / 2.0
            self.canvas_transform = (scale, offset_x, offset_y)

            x0 = offset_x
            x1 = offset_x + bed_x * scale
            y0 = height - offset_y
            y1 = height - (offset_y + bed_y * scale)

            canvas.create_rectangle(x0, y1, x1, y0, outline="#8892a0", fill="#ffffff")

            grid_step = 10.0
            if bed_x > 0 and bed_y > 0:
                num_x = int(bed_x // grid_step) + 1
                num_y = int(bed_y // grid_step) + 1
                for i in range(num_x + 1):
                    x_mm = min(i * grid_step, bed_x)
                    x = offset_x + x_mm * scale
                    canvas.create_line(x, y0, x, y1, fill="#e2e6ef")
                for j in range(num_y + 1):
                    y_mm = min(j * grid_step, bed_y)
                    y = height - (offset_y + y_mm * scale)
                    canvas.create_line(x0, y, x1, y, fill="#e2e6ef")

            self.block_bounds_mm.clear()
            for block, paths, bounds in block_results:
                color = block.color
                path_color = "#000000"
                for path in paths:
                    if len(path) < 2:
                        continue
                    coords: list[float] = []
                    for x_mm, y_mm in path:
                        x = offset_x + x_mm * scale
                        y = height - (offset_y + y_mm * scale)
                        coords.extend((x, y))
                    canvas.create_line(coords, fill=path_color, width=2)

                min_x, min_y, max_x, max_y = bounds
                x_left = offset_x + min_x * scale
                x_right = offset_x + max_x * scale
                y_top = height - (offset_y + max_y * scale)
                y_bottom = height - (offset_y + min_y * scale)
                canvas.create_rectangle(
                    x_left,
                    y_top,
                    x_right,
                    y_bottom,
                    outline=color,
                    dash=(4, 3),
                )
                canvas.create_text(
                    x_left + 6,
                    y_top + 14,
                    text=block.header_var.get(),
                    fill=color,
                    anchor="w",
                    font=("TkDefaultFont", 9, "bold"),
                )
                self.block_bounds_mm[block.uid] = bounds

        def save_gcode(self) -> None:
            if filedialog is None:
                return
            if not self.preview_paths or self.preview_settings is None:
                self.force_refresh()
                if not self.preview_paths or self.preview_settings is None:
                    return
            file_path = filedialog.asksaveasfilename(
                title="G-code kaydet",
                defaultextension=".gcode",
                filetypes=[("G-code", "*.gcode"), ("Tüm dosyalar", "*.*")],
            )
            if not file_path:
                return
            pen_offset_x, pen_offset_y = self.preview_pen_offset
            paths_for_output = (
                translate_paths(self.preview_paths, pen_offset_x, pen_offset_y)
                if pen_offset_x or pen_offset_y
                else list(self.preview_paths)
            )
            gcode_lines = paths_to_gcode(paths_for_output, self.preview_settings)
            Path(file_path).write_text("\n".join(gcode_lines) + "\n", encoding="utf-8")
            self.status_var.set(f"G-code kaydedildi: {file_path}")
            if messagebox is not None:
                messagebox.showinfo("G-code kaydedildi", f"Dosya '{file_path}' olarak kaydedildi.")

        def _on_canvas_configure(self, event: tk.Event) -> None:
            self.canvas_width = max(event.width, 200)
            self.canvas_height = max(event.height, 200)
            self.schedule_preview()

        def _canvas_to_mm(self, x: float, y: float) -> tuple[float, float]:
            scale, offset_x, offset_y = self.canvas_transform
            if scale <= 0:
                return 0.0, 0.0
            mm_x = (x - offset_x) / scale
            mm_y = ((self.canvas_height - y) - offset_y) / scale
            return mm_x, mm_y

        def _on_canvas_press(self, event: tk.Event) -> None:
            if not self.block_bounds_mm:
                return
            mm_x, mm_y = self._canvas_to_mm(event.x, event.y)
            for block in reversed(self.blocks):
                bounds = self.block_bounds_mm.get(block.uid)
                if bounds and bounds[0] <= mm_x <= bounds[2] and bounds[1] <= mm_y <= bounds[3]:
                    self.drag_block = block
                    self.drag_offset = (mm_x - block.translation_x, mm_y - block.translation_y)
                    self.status_var.set(f"{block.header_var.get()} sürükleniyor...")
                    break

        def _on_canvas_drag(self, event: tk.Event) -> None:
            block = self.drag_block
            if block is None:
                return
            mm_x, mm_y = self._canvas_to_mm(event.x, event.y)
            new_tx = mm_x - self.drag_offset[0]
            new_ty = mm_y - self.drag_offset[1]
            bed_x, bed_y = self.current_bed_size
            if block.local_bounds:
                min_tx = -block.local_bounds[0]
                max_tx = bed_x - block.local_bounds[2]
                min_ty = -block.local_bounds[1]
                max_ty = bed_y - block.local_bounds[3]
                if min_tx <= max_tx:
                    new_tx = min(max(new_tx, min_tx), max_tx)
                if min_ty <= max_ty:
                    new_ty = min(max(new_ty, min_ty), max_ty)
            block.translation_x = new_tx
            block.translation_y = new_ty
            block.update_position_label()
            self.schedule_preview()

        def _on_canvas_release(self, _event: tk.Event) -> None:
            if self.drag_block is not None:
                self.status_var.set("Konum güncellendi.")
            self.drag_block = None


    def run_gui_mode() -> None:
        """Tkinter tabanlı Pen Plotter Studio arayüzünü başlatır."""
        if tk is None:
            print("Bu sistemde Tkinter modülü bulunamadı. Komut satırı moduna geçiliyor.")
            run_interactive_mode()
            return

        root = tk.Tk()
        root.withdraw()

        try:
            _ensure_fonttools_installed()
        except ModuleNotFoundError:
            error_message = (
                "fonttools paketi bulunamadı. Komut satırında `pip install fonttools` "
                "komutunu çalıştırıp tekrar deneyin."
            )
            if messagebox is not None:
                messagebox.showerror("Bağımlılık Eksik", error_message)
            else:
                print(error_message)
            root.destroy()
            return

        try:
            style = ttk.Style()
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass

        app = _PenPlotterStudio(root)
        root.deiconify()
        root.mainloop()

def run_interactive_mode() -> None:
    print(
        "\nBu araç komut satırına alışık olmayan kullanıcılar için basitleştirilmiş bir mod sunar."
    )
    print(
        "Adımlar:\n"
        "1) Bu pencereyi açık tutun.\n"
        "2) Sorulan bilgileri doldurun.\n"
        "3) FontTools kurulu değilse otomatik uyarı alacaksınız."
    )

    text = input("\nYazılacak metni girin: ")
    while not text.strip():
        print("Metin boş olamaz. Lütfen tekrar deneyin.")
        text = input("Yazılacak metni girin: ")

    font_path = _prompt_for_existing_path("TTF font dosyasının tam yolu: ")

    output_path_input = input(
        "Çıkış G-code dosya adı (varsayılan output.gcode): "
    ).strip()
    output_path = Path(output_path_input) if output_path_input else Path("output.gcode")

    font_size = _prompt_float("Yazı boyutu mm (varsayılan 12): ", default=12.0)
    line_spacing = _prompt_float(
        "Satır aralığı çarpanı (varsayılan 1.3): ", default=1.3
    )
    char_spacing = _prompt_float(
        "Harfler arası ekstra boşluk mm (varsayılan 0): ", default=0.0
    )
    curve_tolerance = _prompt_float(
        "Eğri doğrultma toleransı mm (varsayılan 0.1): ", default=0.1
    )
    travel_height = _prompt_float(
        "Kalemin boşta yüksekliği mm (varsayılan 5): ", default=5.0
    )
    drawing_height = _prompt_float(
        "Kalemin çizimde yüksekliği mm (varsayılan 0): ", default=0.0
    )
    travel_feed = _prompt_float(
        "Boşta hız mm/sn (varsayılan 50): ", default=50.0
    )
    drawing_feed = _prompt_float(
        "Çizim hızı mm/sn (varsayılan 20): ", default=20.0
    )
    center = _prompt_yes_no("Metni (0,0) etrafında ortalamak ister misiniz? (E/h): ")
    preview = _prompt_yes_no("Boyut bilgisini görmek ister misiniz? (E/h): ")

    args = argparse.Namespace(
        text=text,
        text_file=None,
        font=font_path,
        font_size=font_size,
        line_spacing=line_spacing,
        char_spacing=char_spacing,
        curve_tolerance=curve_tolerance,
        travel_height=travel_height,
        drawing_height=drawing_height,
        travel_feed=travel_feed,
        drawing_feed=drawing_feed,
        origin_x=0.0,
        origin_y=0.0,
        center=center,
        preview=preview,
        output=output_path,
    )

    try:
        _ensure_fonttools_installed()
        generate_and_save_gcode(text, args)
        print("\nİşlem tamamlandı!")
    except Exception as exc:  # pragma: no cover - interaktif hata raporu
        print(f"\nBir hata oluştu: {exc}")
    finally:
        input("\nPencereyi kapatmak için Enter'a basın...")


def _prompt_for_existing_path(prompt: str) -> Path:
    while True:
        value = input(prompt).strip().strip('"')
        if not value:
            print("Dosya yolu boş olamaz. Lütfen tam .ttf yolunu yazın.")
            continue
        path = Path(value).expanduser()
        if path.exists():
            return path
        print("Dosya bulunamadı. Yolun doğru olduğundan emin olun ve tekrar deneyin.")


def _prompt_float(prompt: str, default: float) -> float:
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"Geçersiz sayı. Varsayılan değer {default} kullanılacak.")
        return default


def _prompt_yes_no(prompt: str) -> bool:
    raw = input(prompt).strip().lower()
    return raw in {"e", "evet", "y"}


def _ensure_fonttools_installed() -> None:
    try:
        import fontTools  # noqa: F401
    except ModuleNotFoundError:
        print(
            "\nfonttools paketini kurmanız gerekiyor. Aşağıdaki komutu çalıştırın:\n"
            "pip install fonttools"
        )
        raise


if __name__ == "__main__":
    main()
