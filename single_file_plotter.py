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


def run_gui_mode() -> None:
    """Tkinter tabanlı Pen Plotter Studio arayüzünü başlatır."""

    if tk is None:
        print(
            "Bu sistemde Tkinter modülü bulunamadı. Komut satırı moduna geçiliyor."
        )
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

    root.title("Pen Plotter Studio (Tek Dosya)")
    root.geometry("980x660")
    root.minsize(860, 620)
    root.deiconify()

    try:  # Varsayılan temayı modern bir temayla değiştirmeye çalış
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:  # pragma: no cover - tema hataları önemsiz
        pass

    main = ttk.Frame(root, padding=12)
    main.grid(column=0, row=0, sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    main.columnconfigure(0, weight=1)
    main.columnconfigure(1, weight=0)
    main.rowconfigure(0, weight=1)
    main.rowconfigure(1, weight=1)

    text_frame = ttk.LabelFrame(main, text="Metin")
    text_frame.grid(column=0, row=0, sticky="nsew")
    text_frame.columnconfigure(0, weight=1)
    text_frame.rowconfigure(0, weight=1)

    text_widget = tk.Text(text_frame, wrap="word", height=8, font=("Segoe UI", 11))
    text_widget.grid(column=0, row=0, sticky="nsew")
    text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
    text_scroll.grid(column=1, row=0, sticky="ns")
    text_widget.configure(yscrollcommand=text_scroll.set)
    text_widget.insert("1.0", "Pen Plotter Studio\nHoş geldiniz!")

    preview_frame = ttk.LabelFrame(main, text="Önizleme")
    preview_frame.grid(column=0, row=1, sticky="nsew", pady=(12, 0))
    preview_frame.columnconfigure(0, weight=1)
    preview_frame.rowconfigure(0, weight=1)

    CANVAS_WIDTH = 540
    CANVAS_HEIGHT = 360
    canvas = tk.Canvas(
        preview_frame,
        width=CANVAS_WIDTH,
        height=CANVAS_HEIGHT,
        background="#ffffff",
        highlightthickness=1,
        highlightbackground="#c7cad1",
    )
    canvas.grid(column=0, row=0, sticky="nsew")

    metrics_var = tk.StringVar(value="Font seçip önizleme oluşturun.")
    metrics_label = ttk.Label(preview_frame, textvariable=metrics_var, anchor="w")
    metrics_label.grid(column=0, row=1, sticky="ew", pady=(8, 0))

    controls = ttk.LabelFrame(main, text="Ayarlar")
    controls.grid(column=1, row=0, rowspan=2, sticky="ns", padx=(12, 0))
    for idx in range(4):
        controls.rowconfigure(idx, weight=0)
    controls.columnconfigure(0, weight=1)

    font_path_var = tk.StringVar(value="")

    font_frame = ttk.Frame(controls)
    font_frame.grid(column=0, row=0, sticky="ew", pady=(0, 12))
    font_frame.columnconfigure(0, weight=1)

    font_label_var = tk.StringVar(value="Seçilmedi")
    font_label = ttk.Label(font_frame, textvariable=font_label_var, width=32)
    font_label.grid(column=0, row=0, sticky="w")

    def select_font() -> None:
        if filedialog is None:
            return
        file_path = filedialog.askopenfilename(
            title="TrueType font seç",
            filetypes=[("TrueType Font", "*.ttf"), ("Tüm dosyalar", "*.*")],
        )
        if not file_path:
            return
        font_path_var.set(file_path)
        font_label_var.set(Path(file_path).name)
        refresh_preview(show_dialog=True)

    ttk.Button(font_frame, text="Font Seç (.ttf)", command=select_font).grid(
        column=0, row=1, sticky="ew", pady=(6, 0)
    )

    defaults = {
        "font_size": "14",
        "line_spacing": "1.3",
        "char_spacing": "0",
        "curve_tolerance": "0.1",
        "origin_x": "0",
        "origin_y": "0",
        "travel_height": "5",
        "drawing_height": "0",
        "travel_feed": "3000",
        "drawing_feed": "1200",
    }

    labels = {
        "font_size": "Yazı boyutu (mm)",
        "line_spacing": "Satır aralığı", 
        "char_spacing": "Harf arası (mm)",
        "curve_tolerance": "Eğri toleransı (mm)",
        "origin_x": "X ofseti (mm)",
        "origin_y": "Y ofseti (mm)",
        "travel_height": "Kalem yukarı Z (mm)",
        "drawing_height": "Kalem aşağı Z (mm)",
        "travel_feed": "Boşta hız (mm/dak)",
        "drawing_feed": "Çizim hızı (mm/dak)",
    }

    entry_vars: dict[str, tk.StringVar] = {}

    def add_labeled_entry(row: int, key: str) -> None:
        label = ttk.Label(controls, text=labels[key])
        label.grid(column=0, row=row, sticky="w")
        entry_var = tk.StringVar(value=defaults[key])
        entry = ttk.Entry(controls, textvariable=entry_var)
        entry.grid(column=0, row=row + 1, sticky="ew", pady=(0, 8))
        entry_vars[key] = entry_var

    row_index = 1
    for field_key in (
        "font_size",
        "line_spacing",
        "char_spacing",
        "curve_tolerance",
        "origin_x",
        "origin_y",
        "travel_height",
        "drawing_height",
        "travel_feed",
        "drawing_feed",
    ):
        add_labeled_entry(row_index, field_key)
        row_index += 2

    center_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        controls,
        text="Metni (0,0) etrafında ortala",
        variable=center_var,
    ).grid(column=0, row=row_index, sticky="w", pady=(4, 8))
    row_index += 1

    status_var = tk.StringVar(value="Hazır")

    state: dict[str, object] = {
        "paths": [],
        "settings": None,
        "metrics": None,
    }

    def parse_float(key: str) -> float:
        raw = entry_vars[key].get().strip()
        if not raw:
            raw = defaults[key]
        raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{labels[key]} için geçerli bir sayı girin.") from exc

    def compute_paths_settings() -> tuple[List[PathType], tuple[float, float, float, float, float], PlotterSettings]:
        font_path_str = font_path_var.get().strip()
        if not font_path_str:
            raise ValueError("Lütfen bir .ttf font dosyası seçin.")

        text_value = text_widget.get("1.0", "end-1c")
        if not text_value.strip():
            raise ValueError("Metin alanı boş olamaz.")

        font_path = Path(font_path_str)
        with SimpleFontLoader(font_path) as font_loader:
            paths = layout_text(
                text_value,
                font_loader,
                font_size=parse_float("font_size"),
                line_spacing=parse_float("line_spacing"),
                character_spacing=parse_float("char_spacing"),
                curve_tolerance=parse_float("curve_tolerance"),
            )

        if center_var.get():
            min_x, min_y, max_x, max_y, _ = measure_paths(paths)
            center_x = (min_x + max_x) / 2.0
            center_y = (min_y + max_y) / 2.0
            paths = translate_paths(paths, -center_x, -center_y)

        origin_x = parse_float("origin_x")
        origin_y = parse_float("origin_y")
        if origin_x or origin_y:
            paths = translate_paths(paths, origin_x, origin_y)

        metrics = measure_paths(paths)
        comment = f"Pen Plotter Studio GUI - {font_path.name}"[:80]
        settings = PlotterSettings(
            travel_height=parse_float("travel_height"),
            drawing_height=parse_float("drawing_height"),
            travel_feed_rate=parse_float("travel_feed"),
            drawing_feed_rate=parse_float("drawing_feed"),
            comment=comment,
        )
        return paths, metrics, settings

    def draw_preview(paths: List[PathType], metrics: tuple[float, float, float, float, float]) -> None:
        canvas.delete("all")
        min_x, min_y, max_x, max_y, total_length = metrics
        width = max_x - min_x
        height = max_y - min_y

        if not paths or (width == 0 and height == 0):
            canvas.create_text(
                CANVAS_WIDTH / 2,
                CANVAS_HEIGHT / 2,
                text="Önizleme için metin girin ve font seçin",
                fill="#6c6f7a",
            )
            metrics_var.set("Önizleme hazır değil.")
            return

        margin = 24
        scale_x = (CANVAS_WIDTH - margin * 2) / (width if width != 0 else 1)
        scale_y = (CANVAS_HEIGHT - margin * 2) / (height if height != 0 else 1)
        scale = min(scale_x, scale_y)
        if scale <= 0:
            scale = 1.0

        offset_x = margin - min_x * scale
        offset_y = margin - min_y * scale

        # Koordinatları Canvas sistemine çevirirken Y eksenini ters çeviriyoruz
        for path in paths:
            if len(path) < 2:
                continue
            coords: list[float] = []
            for x, y in path:
                draw_x = x * scale + offset_x
                draw_y = CANVAS_HEIGHT - (y * scale + offset_y)
                coords.extend((draw_x, draw_y))
            canvas.create_line(coords, fill="#1f77b4", width=2, smooth=False)

        bbox_left = min_x * scale + offset_x
        bbox_top = CANVAS_HEIGHT - (max_y * scale + offset_y)
        bbox_right = max_x * scale + offset_x
        bbox_bottom = CANVAS_HEIGHT - (min_y * scale + offset_y)
        canvas.create_rectangle(
            bbox_left,
            bbox_top,
            bbox_right,
            bbox_bottom,
            outline="#b9bdc6",
            dash=(4, 3),
        )

        metrics_var.set(
            "Genişlik: {:.2f} mm | Yükseklik: {:.2f} mm | Yol uzunluğu: {:.2f} mm".format(
                width,
                height,
                total_length,
            )
        )

    def refresh_preview(show_dialog: bool = False) -> None:
        try:
            paths, metrics, settings = compute_paths_settings()
        except Exception as exc:
            state["paths"] = []
            state["settings"] = None
            state["metrics"] = None
            canvas.delete("all")
            canvas.create_text(
                CANVAS_WIDTH / 2,
                CANVAS_HEIGHT / 2,
                text=str(exc),
                fill="#b94a48",
            )
            metrics_var.set("Önizleme hazırlanamadı.")
            status_var.set("Hata: {}".format(exc))
            if show_dialog and messagebox is not None:
                messagebox.showerror("Önizleme Hatası", str(exc))
            return

        state["paths"] = paths
        state["settings"] = settings
        state["metrics"] = metrics
        draw_preview(paths, metrics)
        status_var.set("Önizleme güncellendi.")

    def save_gcode() -> None:
        if filedialog is None:
            return
        if not state["paths"]:
            refresh_preview(show_dialog=True)
            if not state["paths"]:
                return
        settings_obj = state["settings"]
        if not isinstance(settings_obj, PlotterSettings):
            refresh_preview(show_dialog=True)
            settings_obj = state["settings"]
            if not isinstance(settings_obj, PlotterSettings):
                return
        file_path = filedialog.asksaveasfilename(
            title="G-code kaydet",
            defaultextension=".gcode",
            filetypes=[("G-code", "*.gcode"), ("Tüm dosyalar", "*.*")],
        )
        if not file_path:
            return
        gcode_lines = paths_to_gcode(state["paths"], settings_obj)
        Path(file_path).write_text("\n".join(gcode_lines) + "\n", encoding="utf-8")
        status_var.set(f"G-code kaydedildi: {file_path}")
        if messagebox is not None:
            messagebox.showinfo("G-code Kaydedildi", f"Dosya '{file_path}' olarak kaydedildi.")

    button_frame = ttk.Frame(controls)
    button_frame.grid(column=0, row=row_index + 1, sticky="ew", pady=(12, 0))
    button_frame.columnconfigure(0, weight=1)
    button_frame.columnconfigure(1, weight=1)

    ttk.Button(
        button_frame,
        text="Önizlemeyi Güncelle",
        command=lambda: refresh_preview(show_dialog=True),
    ).grid(column=0, row=0, sticky="ew", padx=(0, 6))

    ttk.Button(
        button_frame,
        text="G-code Kaydet",
        command=save_gcode,
    ).grid(column=1, row=0, sticky="ew")

    status_label = ttk.Label(main, textvariable=status_var, anchor="w")
    status_label.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(12, 0))

    # Hızlı klavye kısayolları
    root.bind("<Control-s>", lambda _event: save_gcode())
    root.bind("<Control-Return>", lambda _event: refresh_preview(show_dialog=True))

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
        "Boşta hız mm/dak (varsayılan 3000): ", default=3000.0
    )
    drawing_feed = _prompt_float(
        "Çizim hızı mm/dak (varsayılan 1200): ", default=1200.0
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
