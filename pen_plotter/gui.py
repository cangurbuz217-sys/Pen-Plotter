"""Tkinter-based desktop interface for the pen plotter toolchain."""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # pragma: no cover - import guard for headless environments
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - Tk is optional during tests
    tk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]

from .font_paths import FontLoader, LayoutSettings, layout_text
from .gcode import PlotterSettings, paths_to_gcode
from .geometry import measure_paths, translate_paths

PathType = List[Tuple[float, float]]


if tk is None:  # pragma: no cover - gracefully handle missing Tk

    class PenPlotterStudio:  # type: ignore[empty-body]
        """Placeholder exported when Tkinter is unavailable."""

        def __init__(self, *_args, **_kwargs) -> None:  # noqa: D401 - runtime guard
            raise RuntimeError(
                "Tkinter bu ortamda mevcut değil. GUI yalnızca Tk destekli sistemlerde çalışır."
            )

    def main() -> None:  # type: ignore[empty-body]
        raise RuntimeError(
            "Tkinter bu ortamda mevcut değil. GUI yalnızca Tk destekli sistemlerde çalışır."
        )

    __all__ = ["PenPlotterStudio", "main"]

else:

    class _GUITextBlock:
        """A draggable, self-contained text block with its own formatting."""

        def __init__(
            self,
            app: "PenPlotterStudio",
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
            self.text_widget.insert("1.0", initial_text)
            self.text_widget.bind("<<Modified>>", self._on_text_modified)
            self.text_widget.edit_modified(False)

            self.translation_x = 0.0
            self.translation_y = 0.0
            self.rotation_deg = 0.0
            self.local_bounds: Optional[Tuple[float, float, float, float]] = None
            self.current_bounds: Optional[Tuple[float, float, float, float]] = None
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
                (
                    "Pozisyon: X={:.1f} mm | Y={:.1f} mm | A={:.1f}°".format(
                        self.translation_x,
                        self.translation_y,
                        self.rotation_deg,
                    )
                )
            )

        def destroy(self) -> None:
            self.frame.destroy()

    class _GUIShape:
        """Configurable geometric shape that can be positioned and rotated."""

        SHAPE_TITLES = {
            "rectangle": "Dikdörtgen",
            "line": "Çizgi",
            "arrow": "Yön oku",
        }

        PARAM_CONFIGS = {
            "rectangle": [
                ("Genişlik (mm)", "width", "40"),
                ("Yükseklik (mm)", "height", "20"),
            ],
            "line": [
                ("Uzunluk (mm)", "length", "40"),
            ],
            "arrow": [
                ("Uzunluk (mm)", "length", "50"),
                ("Ok başı (mm)", "head", "12"),
            ],
        }

        def __init__(self, app: "PenPlotterStudio", uid: int, shape_type: str) -> None:
            if shape_type not in self.PARAM_CONFIGS:
                raise ValueError(f"Desteklenmeyen şekil: {shape_type}")
            self.app = app
            self.uid = uid
            self.shape_type = shape_type
            self.frame = ttk.Frame(app.shapes_container, padding=(8, 8))
            self.header_var = tk.StringVar(value="")
            self.position_var = tk.StringVar(
                value="Pozisyon: X=0.0 mm | Y=0.0 mm | A=0.0°"
            )

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
                command=lambda: app.remove_shape(self),
            ).pack(side="right")

            controls = ttk.Frame(self.frame)
            controls.pack(fill="x")
            controls.columnconfigure(0, weight=1)
            controls.columnconfigure(1, weight=1)

            self.param_vars: Dict[str, tk.StringVar] = {}
            self.param_labels: Dict[str, str] = {}
            self.param_defaults: Dict[str, float] = {}
            for column, (label_text, key, default) in enumerate(
                self.PARAM_CONFIGS[shape_type]
            ):
                ttk.Label(controls, text=label_text).grid(
                    column=column,
                    row=0,
                    sticky="w",
                    padx=(0, 8),
                )
                var = tk.StringVar(value=default)
                entry = ttk.Entry(controls, textvariable=var, width=8)
                entry.grid(column=column, row=1, sticky="ew", padx=(0, 8))
                entry.bind("<KeyRelease>", lambda _event: app.schedule_preview())
                self.param_vars[key] = var
                self.param_labels[key] = label_text
                try:
                    self.param_defaults[key] = float(default)
                except ValueError:
                    self.param_defaults[key] = 0.0

            self.translation_x = 0.0
            self.translation_y = 0.0
            self.rotation_deg = 0.0
            self.local_bounds: Optional[Tuple[float, float, float, float]] = None
            self.color = "#1f77b4"

        def set_display_index(self, index: int, color: str) -> None:
            title = self.SHAPE_TITLES.get(self.shape_type, self.shape_type.title())
            self.header_var.set(f"{title} {index}")
            self.color = color

        def update_position_label(self) -> None:
            self.position_var.set(
                (
                    "Pozisyon: X={:.1f} mm | Y={:.1f} mm | A={:.1f}°".format(
                        self.translation_x,
                        self.translation_y,
                        self.rotation_deg,
                    )
                )
            )

        def destroy(self) -> None:
            self.frame.destroy()

    @dataclass
    class _BlockRequest:
        uid: int
        text: str
        font_size: float
        line_spacing: float
        char_spacing: float
        translation: Tuple[float, float]
        rotation: float

    @dataclass
    class _ShapeRequest:
        uid: int
        shape_type: str
        params: Dict[str, float]
        translation: Tuple[float, float]
        rotation: float

    @dataclass
    class _BlockPreviewData:
        uid: int
        paths: List[PathType]
        bounds: Tuple[float, float, float, float]
        local_bounds: Optional[Tuple[float, float, float, float]]
        outside: bool
        length: float
        rotation: float
        center: Tuple[float, float]
        handle_point: Tuple[float, float]

    @dataclass
    class _ShapePreviewData:
        uid: int
        shape_type: str
        paths: List[PathType]
        bounds: Tuple[float, float, float, float]
        local_bounds: Tuple[float, float, float, float]
        outside: bool
        length: float
        rotation: float
        center: Tuple[float, float]
        handle_point: Tuple[float, float]

    @dataclass
    class _PreviewInputs:
        font_path: str
        bed_x: float
        bed_y: float
        pen_offset_x: float
        pen_offset_y: float
        approach_height: float
        pen_up: float
        pen_down: float
        travel_feed: float
        drawing_feed: float
        curve_tolerance: float
        blocks: List[_BlockRequest]
        shapes: List["_ShapeRequest"]

    @dataclass
    class _PreviewComputation:
        inputs: _PreviewInputs
        block_results: List[_BlockPreviewData]
        shape_results: List[_ShapePreviewData]
        all_paths: List[PathType]
        metrics: Tuple[float, float, float, float, float]
        total_length: float
        settings: PlotterSettings
        font_name: str

    class PenPlotterStudio:
        """Full-featured Pen Plotter Studio interface."""

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
                "approach_height": "10",
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
                "approach_height": "İlk yaklaşma (mm)",
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
            self.warning_var = tk.StringVar(value="")

            self.blocks: List[_GUITextBlock] = []
            self.shapes: List[_GUIShape] = []
            self.block_uid_counter = 1
            self.shape_uid_counter = 1
            self.item_bounds_mm: Dict[object, Tuple[float, float, float, float]] = {}
            self.item_centers_mm: Dict[object, Tuple[float, float]] = {}
            self.item_handles_mm: Dict[object, Tuple[float, float]] = {}
            self.render_stack: List[object] = []
            self.preview_paths: List[PathType] = []
            self.preview_settings: Optional[PlotterSettings] = None
            self.preview_metrics: Optional[Tuple[float, float, float, float, float]] = None
            self.preview_pen_offset = (0.0, 0.0)
            self.current_bed_size = (
                self.hardware_defaults_float["bed_x"],
                self.hardware_defaults_float["bed_y"],
            )
            self.canvas_transform = (1.0, 24.0, 24.0)
            self.drag_item: Optional[object] = None
            self.drag_offset = (0.0, 0.0)
            self.rotate_item: Optional[object] = None
            self.rotate_reference_angle = 0.0
            self.rotate_center = (0.0, 0.0)
            self._preview_pending = False
            self._preview_timer: Optional[str] = None
            self._preview_thread_running = False
            self._preview_job_counter = 0
            self._active_preview_id = 0
            self._force_show_dialog = False

            self.last_project_path: Optional[Path] = None

            self.canvas_width = 640
            self.canvas_height = 540

            self._build_ui()
            self.add_block("Pen Plotter Studio'ya hoş geldiniz!")
            self.schedule_preview()

        # ------------------------------------------------------------------ UI --
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
            self._add_hardware_entry(hardware_frame, "approach_height", 2, 0)
            self._add_hardware_entry(hardware_frame, "pen_up", 2, 1)
            self._add_hardware_entry(hardware_frame, "pen_down", 2, 2)
            self._add_hardware_entry(hardware_frame, "travel_feed", 3, 0)
            self._add_hardware_entry(hardware_frame, "drawing_feed", 3, 1)

            tolerance_row = 8
            ttk.Label(hardware_frame, text="Eğri toleransı (mm)").grid(
                column=0,
                row=tolerance_row,
                columnspan=2,
                sticky="w",
                pady=(8, 0),
            )
            ttk.Entry(hardware_frame, textvariable=self.curve_tolerance_var, width=8).grid(
                column=0,
                row=tolerance_row + 1,
                columnspan=2,
                sticky="ew",
                pady=(0, 8),
            )

            self.curve_tolerance_var.trace_add("write", lambda *_: self.schedule_preview())

            font_frame = ttk.LabelFrame(controls, text="Your text")
            font_frame.grid(column=0, row=2, sticky="nsew")
            font_frame.columnconfigure(0, weight=1)
            font_frame.rowconfigure(2, weight=1)
            font_frame.rowconfigure(3, weight=1)

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

            shapes_frame = ttk.LabelFrame(font_frame, text="Şekiller")
            shapes_frame.grid(column=0, row=3, sticky="nsew", pady=(12, 0))
            shapes_frame.columnconfigure(0, weight=1)
            shapes_frame.rowconfigure(1, weight=1)

            shapes_buttons = ttk.Frame(shapes_frame)
            shapes_buttons.grid(column=0, row=0, sticky="ew", pady=(4, 6))
            for idx in range(3):
                shapes_buttons.columnconfigure(idx, weight=1)
            ttk.Button(
                shapes_buttons,
                text="Dikdörtgen ekle",
                command=lambda: self.add_shape("rectangle"),
            ).grid(column=0, row=0, sticky="ew", padx=(0, 4))
            ttk.Button(
                shapes_buttons,
                text="Çizgi ekle",
                command=lambda: self.add_shape("line"),
            ).grid(column=1, row=0, sticky="ew", padx=2)
            ttk.Button(
                shapes_buttons,
                text="Yön oku ekle",
                command=lambda: self.add_shape("arrow"),
            ).grid(column=2, row=0, sticky="ew", padx=(4, 0))

            self.shapes_container = ttk.Frame(shapes_frame)
            self.shapes_container.grid(column=0, row=1, sticky="nsew")
            self.shapes_container.columnconfigure(0, weight=1)

            preview_frame = ttk.Frame(main)
            preview_frame.grid(column=1, row=0, sticky="nsew")
            preview_frame.columnconfigure(0, weight=1)
            preview_frame.rowconfigure(1, weight=1)

            ttk.Label(
                preview_frame,
                textvariable=self.warning_var,
                foreground="#d9534f",
                anchor="center",
                justify="center",
                font=("TkDefaultFont", 10, "bold"),
            ).grid(column=0, row=0, sticky="ew", pady=(0, 4))

            self.canvas = tk.Canvas(
                preview_frame,
                background=self.CANVAS_BG,
                highlightthickness=0,
            )
            self.canvas.grid(column=0, row=1, sticky="nsew")
            self.canvas.bind("<Configure>", self._on_canvas_configure)
            self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
            self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)

            ttk.Label(preview_frame, textvariable=self.metrics_var, anchor="center").grid(
                column=0,
                row=2,
                sticky="ew",
                pady=(12, 0),
            )

            footer = ttk.Frame(main)
            footer.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(12, 0))
            footer.columnconfigure(0, weight=1)
            footer.columnconfigure(1, weight=0)
            footer.columnconfigure(2, weight=0)
            footer.columnconfigure(3, weight=0)
            footer.columnconfigure(4, weight=0)

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
            ttk.Button(footer, text="Projeyi aç", command=self.load_project).grid(
                column=2,
                row=0,
                padx=(0, 6),
            )
            ttk.Button(footer, text="Projeyi kaydet", command=self.save_project).grid(
                column=3,
                row=0,
                padx=(0, 6),
            )
            ttk.Button(footer, text="G-code kaydet", command=self.save_gcode).grid(
                column=4,
                row=0,
            )

            self.root.bind("<Control-s>", lambda _event: self.save_gcode())
            self.root.bind("<Control-Shift-s>", lambda _event: self.save_project())
            self.root.bind("<Control-o>", lambda _event: self.load_project())
            self.root.bind("<Control-Return>", lambda _event: self.force_refresh())

        def _add_hardware_entry(self, parent: ttk.Frame, key: str, row: int, column: int) -> None:
            ttk.Label(parent, text=self.hardware_labels[key]).grid(
                column=column,
                row=row * 2,
                sticky="w",
                pady=(4 if row else 0, 0),
                padx=(0, 8),
            )
            entry = ttk.Entry(parent, textvariable=self.hardware_vars[key], width=10)
            entry.grid(column=column, row=row * 2 + 1, sticky="ew", padx=(0, 8), pady=(0, 4))
            entry.bind("<KeyRelease>", lambda _event: self.schedule_preview())

        # ---------------------------------------------------------- Block mgmt --
        def add_block(self, initial_text: str = "") -> None:
            block = _GUITextBlock(self, self.block_uid_counter, initial_text)
            self.block_uid_counter += 1
            block.frame.grid(column=0, row=len(self.blocks), sticky="ew", pady=(0, 12))
            self.blocks.append(block)
            self.update_block_headers()
            self.schedule_preview()

        def remove_block(self, block: _GUITextBlock) -> None:
            if block not in self.blocks:
                return
            self.blocks.remove(block)
            block.destroy()
            for index, other in enumerate(self.blocks):
                other.frame.grid_configure(row=index)
            self.update_block_headers()
            self.schedule_preview()

        def update_block_headers(self) -> None:
            for index, block in enumerate(self.blocks, start=1):
                color = self.BLOCK_COLORS[(index - 1) % len(self.BLOCK_COLORS)]
                block.set_display_index(index, color)

        def add_shape(self, shape_type: str) -> None:
            shape = _GUIShape(self, self.shape_uid_counter, shape_type)
            self.shape_uid_counter += 1
            shape.frame.grid(column=0, row=len(self.shapes), sticky="ew", pady=(0, 12))
            self.shapes.append(shape)
            self.update_shape_headers()
            self.schedule_preview()

        def remove_shape(self, shape: _GUIShape) -> None:
            if shape not in self.shapes:
                return
            self.shapes.remove(shape)
            shape.destroy()
            for index, other in enumerate(self.shapes):
                other.frame.grid_configure(row=index)
            self.update_shape_headers()
            self.schedule_preview()

        def update_shape_headers(self) -> None:
            for index, shape in enumerate(self.shapes, start=1):
                color = self.BLOCK_COLORS[(index - 1) % len(self.BLOCK_COLORS)]
                shape.set_display_index(index, color)

        # ---------------------------------------------------------- Utilities --
        def choose_font(self) -> None:
            if filedialog is None:
                return
            initial_dir = Path.home() / "Desktop"
            file_path = filedialog.askopenfilename(
                title="TrueType font seç",
                filetypes=[
                    ("TrueType / OpenType", "*.ttf *.otf"),
                    ("Tüm dosyalar", "*.*"),
                ],
                initialdir=initial_dir if initial_dir.exists() else None,
            )
            if not file_path:
                return
            self.font_path_var.set(file_path)
            self.status_var.set(f"Seçilen font: {Path(file_path).name}")
            self.schedule_preview()

        def schedule_preview(self) -> None:
            self._preview_pending = True
            if self._preview_timer is None:
                self._preview_timer = self.root.after(150, self._on_preview_timer)

        def _on_preview_timer(self) -> None:
            self._preview_timer = None
            self._start_preview()

        def force_refresh(self, show_dialog: bool = False) -> None:
            if self._preview_timer is not None:
                self.root.after_cancel(self._preview_timer)
                self._preview_timer = None
            self._preview_pending = True
            self._start_preview(show_dialog=show_dialog)

        def _start_preview(self, show_dialog: bool = False) -> None:
            if self._preview_thread_running:
                self._force_show_dialog = self._force_show_dialog or show_dialog
                return
            if not self._preview_pending and not show_dialog:
                return
            try:
                inputs = self._collect_preview_inputs()
            except Exception as exc:
                self._preview_pending = False
                self._display_preview_error(exc, show_dialog or self._force_show_dialog)
                self._force_show_dialog = False
                return
            self._preview_pending = False
            dialog_flag = show_dialog or self._force_show_dialog
            self._force_show_dialog = False
            self._preview_thread_running = True
            self._preview_job_counter += 1
            job_id = self._preview_job_counter
            self._active_preview_id = job_id
            self.warning_var.set("")
            self.status_var.set("Önizleme hazırlanıyor...")
            self._show_loading_canvas()
            thread = threading.Thread(
                target=self._preview_worker,
                args=(job_id, inputs, dialog_flag),
                daemon=True,
            )
            thread.start()

        def _collect_preview_inputs(self) -> _PreviewInputs:
            font_path_str = self.font_path_var.get().strip()
            if not font_path_str:
                raise ValueError("Lütfen önizleme için bir font seçin.")
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
            approach_height = self._parse_float(
                self.hardware_vars["approach_height"],
                self.hardware_labels["approach_height"],
                default=self.hardware_defaults_float["approach_height"],
            )
            curve_tolerance = self._parse_float(
                self.curve_tolerance_var,
                "Eğri toleransı (mm)",
                default=0.1,
                min_value=1e-3,
            )

            block_requests: List[_BlockRequest] = []
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

                block_requests.append(
                    _BlockRequest(
                        uid=block.uid,
                        text=text,
                        font_size=font_size,
                        line_spacing=line_spacing,
                        char_spacing=char_spacing,
                        translation=(block.translation_x, block.translation_y),
                        rotation=block.rotation_deg,
                    )
                )

            shape_requests: List[_ShapeRequest] = []
            for shape in self.shapes:
                params: Dict[str, float] = {}
                for key, var in shape.param_vars.items():
                    default = shape.param_defaults.get(key, 0.0)
                    params[key] = self._parse_float(
                        var,
                        shape.param_labels.get(key, key),
                        default=default,
                        min_value=0.0,
                    )
                shape_requests.append(
                    _ShapeRequest(
                        uid=shape.uid,
                        shape_type=shape.shape_type,
                        params=params,
                        translation=(shape.translation_x, shape.translation_y),
                        rotation=shape.rotation_deg,
                    )
                )

            if not block_requests and not shape_requests:
                raise ValueError("En az bir metin bloğu veya şekil olmalıdır.")

            return _PreviewInputs(
                font_path=font_path_str,
                bed_x=bed_x,
                bed_y=bed_y,
                pen_offset_x=pen_offset_x,
                pen_offset_y=pen_offset_y,
                approach_height=approach_height,
                pen_up=pen_up,
                pen_down=pen_down,
                travel_feed=travel_feed,
                drawing_feed=drawing_feed,
                curve_tolerance=curve_tolerance,
                blocks=block_requests,
                shapes=shape_requests,
            )

        def _preview_worker(
            self, job_id: int, inputs: _PreviewInputs, show_dialog: bool
        ) -> None:
            try:
                block_results: List[_BlockPreviewData] = []
                shape_results: List[_ShapePreviewData] = []
                all_paths: List[PathType] = []
                total_length = 0.0

                def _rotate_paths(
                    paths: List[PathType], angle_deg: float, pivot: Tuple[float, float]
                ) -> List[PathType]:
                    if not paths or abs(angle_deg) < 1e-6:
                        return [list(path) for path in paths]
                    px, py = pivot
                    angle_rad = math.radians(angle_deg)
                    cos_a = math.cos(angle_rad)
                    sin_a = math.sin(angle_rad)
                    rotated: List[PathType] = []
                    for path in paths:
                        new_path: PathType = []
                        for x, y in path:
                            dx = x - px
                            dy = y - py
                            rx = px + dx * cos_a - dy * sin_a
                            ry = py + dx * sin_a + dy * cos_a
                            new_path.append((rx, ry))
                        rotated.append(new_path)
                    return rotated

                def _handle_point(
                    center: Tuple[float, float],
                    local_bounds: Optional[Tuple[float, float, float, float]],
                    rotation_deg: float,
                ) -> Tuple[float, float]:
                    cx, cy = center
                    if local_bounds is None:
                        reach = 12.0
                    else:
                        width = local_bounds[2] - local_bounds[0]
                        height = local_bounds[3] - local_bounds[1]
                        reach = max(width, height) * 0.5 + 8.0
                        reach = max(reach, 12.0)
                    angle_rad = math.radians(rotation_deg)
                    dx = -math.sin(angle_rad)
                    dy = math.cos(angle_rad)
                    return (cx + dx * reach, cy + dy * reach)

                with FontLoader(inputs.font_path) as font_loader:
                    for request in inputs.blocks:
                        layout_settings = LayoutSettings(
                            font_size=request.font_size,
                            line_spacing=request.line_spacing,
                            character_spacing=request.char_spacing,
                            curve_tolerance=inputs.curve_tolerance,
                            stroke_mode="centerline",
                        )
                        raw_paths = layout_text(request.text, font_loader, layout_settings)
                        if not raw_paths:
                            continue
                        local_bounds = measure_paths(raw_paths)[:4]
                        cx = (local_bounds[0] + local_bounds[2]) * 0.5
                        cy = (local_bounds[1] + local_bounds[3]) * 0.5
                        rotated_paths = _rotate_paths(raw_paths, request.rotation, (cx, cy))
                        transformed_paths = translate_paths(
                            rotated_paths,
                            request.translation[0],
                            request.translation[1],
                        )
                        translated_metrics = measure_paths(transformed_paths)
                        length = translated_metrics[4]
                        if length == 0.0:
                            continue
                        bounds_rect = translated_metrics[:4]
                        outside = (
                            bounds_rect[0] < -1e-3
                            or bounds_rect[1] < -1e-3
                            or bounds_rect[2] > inputs.bed_x + 1e-3
                            or bounds_rect[3] > inputs.bed_y + 1e-3
                        )
                        center_world = (cx + request.translation[0], cy + request.translation[1])
                        handle_point = _handle_point(center_world, local_bounds, request.rotation)
                        block_results.append(
                            _BlockPreviewData(
                                uid=request.uid,
                                paths=transformed_paths,
                                bounds=bounds_rect,
                                local_bounds=local_bounds,
                                outside=outside,
                                length=length,
                                rotation=request.rotation,
                                center=center_world,
                                handle_point=handle_point,
                            )
                        )
                        all_paths.extend(transformed_paths)
                        total_length += length

                for shape_request in inputs.shapes:
                    base_paths, local_bounds = self._shape_paths(shape_request)
                    if not base_paths:
                        continue
                    cx = (local_bounds[0] + local_bounds[2]) * 0.5
                    cy = (local_bounds[1] + local_bounds[3]) * 0.5
                    rotated_paths = _rotate_paths(base_paths, shape_request.rotation, (cx, cy))
                    transformed_paths = translate_paths(
                        rotated_paths,
                        shape_request.translation[0],
                        shape_request.translation[1],
                    )
                    metrics = measure_paths(transformed_paths)
                    length = metrics[4]
                    if length == 0.0:
                        continue
                    bounds_rect = metrics[:4]
                    outside = (
                        bounds_rect[0] < -1e-3
                        or bounds_rect[1] < -1e-3
                        or bounds_rect[2] > inputs.bed_x + 1e-3
                        or bounds_rect[3] > inputs.bed_y + 1e-3
                    )
                    center_world = (
                        cx + shape_request.translation[0],
                        cy + shape_request.translation[1],
                    )
                    handle_point = _handle_point(
                        center_world, local_bounds, shape_request.rotation
                    )
                    shape_results.append(
                        _ShapePreviewData(
                            uid=shape_request.uid,
                            shape_type=shape_request.shape_type,
                            paths=transformed_paths,
                            bounds=bounds_rect,
                            local_bounds=local_bounds,
                            outside=outside,
                            length=length,
                            rotation=shape_request.rotation,
                            center=center_world,
                            handle_point=handle_point,
                        )
                    )
                    all_paths.extend(transformed_paths)
                    total_length += length

                if not all_paths:
                    raise ValueError("En az bir öğe önizleme için kullanılabilir olmalıdır.")

                combined_metrics = measure_paths(all_paths)
                comment = f"Pen Plotter Studio - {Path(inputs.font_path).name}"[:80]
                settings = PlotterSettings(
                    approach_height=inputs.approach_height,
                    travel_height=inputs.pen_up,
                    drawing_height=inputs.pen_down,
                    travel_feed_rate=inputs.travel_feed,
                    drawing_feed_rate=inputs.drawing_feed,
                    comment=comment,
                )
                preview = _PreviewComputation(
                    inputs=inputs,
                    block_results=block_results,
                    shape_results=shape_results,
                    all_paths=all_paths,
                    metrics=combined_metrics,
                    total_length=total_length,
                    settings=settings,
                    font_name=Path(inputs.font_path).name,
                )
                self.root.after(
                    0,
                    lambda: self._apply_preview_result(job_id, preview, show_dialog),
                )
            except Exception as exc:
                self.root.after(
                    0,
                    lambda: self._apply_preview_error(job_id, exc, show_dialog),
                )

        def _apply_preview_result(
            self, job_id: int, data: _PreviewComputation, show_dialog: bool
        ) -> None:
            if job_id != self._active_preview_id:
                return
            self._preview_thread_running = False

            inputs = data.inputs
            self.preview_paths = data.all_paths
            self.preview_settings = data.settings
            self.preview_metrics = data.metrics
            self.preview_pen_offset = (inputs.pen_offset_x, inputs.pen_offset_y)
            self.current_bed_size = (inputs.bed_x, inputs.bed_y)

            self.item_bounds_mm.clear()
            self.item_centers_mm.clear()
            self.item_handles_mm.clear()
            render_items: List[
                Tuple[object, List[PathType], Tuple[float, float, float, float], bool]
            ] = []
            outside_labels: List[str] = []

            block_map = {block.uid: block for block in self.blocks}
            seen_blocks: set[int] = set()
            for block_data in data.block_results:
                block = block_map.get(block_data.uid)
                if block is None:
                    continue
                seen_blocks.add(block.uid)
                block.local_bounds = block_data.local_bounds
                block.current_bounds = block_data.bounds
                block.rotation_deg = block_data.rotation
                block.update_position_label()
                self.item_bounds_mm[block] = block_data.bounds
                self.item_centers_mm[block] = block_data.center
                self.item_handles_mm[block] = block_data.handle_point
                render_items.append(
                    (block, block_data.paths, block_data.bounds, block_data.outside)
                )
                if block_data.outside:
                    outside_labels.append(block.header_var.get())

            for block in self.blocks:
                if block.uid not in seen_blocks:
                    block.local_bounds = None
                    block.current_bounds = None
                    self.item_bounds_mm.pop(block, None)
                    self.item_centers_mm.pop(block, None)
                    self.item_handles_mm.pop(block, None)

            shape_map = {shape.uid: shape for shape in self.shapes}
            seen_shapes: set[int] = set()
            for shape_data in data.shape_results:
                shape = shape_map.get(shape_data.uid)
                if shape is None:
                    continue
                seen_shapes.add(shape.uid)
                shape.local_bounds = shape_data.local_bounds
                shape.rotation_deg = shape_data.rotation
                shape.update_position_label()
                self.item_bounds_mm[shape] = shape_data.bounds
                self.item_centers_mm[shape] = shape_data.center
                self.item_handles_mm[shape] = shape_data.handle_point
                render_items.append(
                    (shape, shape_data.paths, shape_data.bounds, shape_data.outside)
                )
                if shape_data.outside:
                    outside_labels.append(shape.header_var.get())

            for shape in self.shapes:
                if shape.uid not in seen_shapes:
                    shape.local_bounds = None
                    self.item_bounds_mm.pop(shape, None)
                    self.item_centers_mm.pop(shape, None)
                    self.item_handles_mm.pop(shape, None)

            self.render_stack = [item for item, _, _, _ in render_items]

            self._draw_preview(inputs.bed_x, inputs.bed_y, render_items)
            width = data.metrics[2] - data.metrics[0]
            height = data.metrics[3] - data.metrics[1]
            self.metrics_var.set(
                "Genişlik: {:.2f} mm | Yükseklik: {:.2f} mm | Yol uzunluğu: {:.2f} mm".format(
                    width,
                    height,
                    data.total_length,
                )
            )
            if outside_labels:
                names = ", ".join(outside_labels)
                if len(outside_labels) == 1:
                    warning_text = f"Uyarı: {names} çalışma alanının dışında."
                else:
                    warning_text = (
                        f"Uyarı: Öğeler çalışma alanının dışında: {names}"
                    )
                self.warning_var.set(warning_text)
                self.status_var.set(warning_text)
            else:
                self.warning_var.set("")
                self.status_var.set(f"Önizleme güncellendi ({data.font_name}).")

            if self._preview_pending:
                self.root.after(50, self._start_preview)

        def _apply_preview_error(
            self, job_id: int, exc: Exception, show_dialog: bool
        ) -> None:
            if job_id != self._active_preview_id:
                return
            self._preview_thread_running = False
            self._display_preview_error(exc, show_dialog)
            if self._preview_pending:
                self.root.after(150, self._start_preview)

        def _display_preview_error(self, exc: Exception, show_dialog: bool) -> None:
            self.preview_paths = []
            self.preview_settings = None
            self.preview_metrics = None
            self.item_bounds_mm.clear()
            self.item_centers_mm.clear()
            self.item_handles_mm.clear()
            self.render_stack.clear()
            self.canvas.delete("all")
            self.canvas.create_text(
                self.canvas_width / 2,
                self.canvas_height / 2,
                text=str(exc),
                fill="#b94a48",
            )
            self.metrics_var.set("Önizleme hazırlanamadı.")
            self.status_var.set(f"Hata: {exc}")
            self.warning_var.set("")
            if show_dialog and messagebox is not None:
                messagebox.showerror("Önizleme hatası", str(exc))

        def _show_loading_canvas(self) -> None:
            self.canvas.delete("all")
            self.canvas.create_rectangle(
                0,
                0,
                self.canvas_width,
                self.canvas_height,
                fill=self.CANVAS_BG,
                outline="",
            )
            self.canvas.create_text(
                self.canvas_width / 2,
                self.canvas_height / 2,
                text="Önizleme hazırlanıyor...",
                fill="#4a5568",
                font=("TkDefaultFont", 11, "bold"),
            )

        def _draw_preview(
            self,
            bed_x: float,
            bed_y: float,
            items: List[
                Tuple[object, List[PathType], Tuple[float, float, float, float], bool]
            ],
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

            canvas.create_rectangle(0, 0, width, height, fill=self.CANVAS_BG, outline="")

            shade_color = "#d9deeb"
            canvas.create_rectangle(0, 0, width, y1, fill=shade_color, outline="")
            canvas.create_rectangle(0, y0, width, height, fill=shade_color, outline="")
            canvas.create_rectangle(0, y1, x0, y0, fill=shade_color, outline="")
            canvas.create_rectangle(x1, y1, width, y0, fill=shade_color, outline="")

            canvas.create_rectangle(
                x0,
                y1,
                x1,
                y0,
                outline="#42526b",
                width=3,
                fill="#ffffff",
            )

            canvas.create_text(
                x0 + 8,
                y0 - 6,
                text="(0,0)",
                fill="#42526b",
                anchor="sw",
                font=("TkDefaultFont", 9, "bold"),
            )
            canvas.create_text(
                x1 - 8,
                y1 + 10,
                text=f"X: 0 → {bed_x:.1f} mm\nY: 0 → {bed_y:.1f} mm",
                fill="#42526b",
                anchor="ne",
                font=("TkDefaultFont", 9, "bold"),
            )
            canvas.create_text(
                (x0 + x1) / 2,
                y0 + 18,
                text=f"X sınırı: 0 ↔ {bed_x:.1f} mm",
                fill="#4a5568",
                anchor="n",
                font=("TkDefaultFont", 9),
            )
            canvas.create_text(
                x0 - 12,
                (y0 + y1) / 2,
                text=f"Y sınırı\n0 ↕ {bed_y:.1f} mm",
                fill="#4a5568",
                anchor="e",
                font=("TkDefaultFont", 9),
                justify="right",
            )

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

            pen_offset_x, pen_offset_y = self.preview_pen_offset
            if 0.0 <= pen_offset_x <= bed_x:
                x_line = offset_x + pen_offset_x * scale
                canvas.create_line(x_line, y0, x_line, y1, fill="#f4a259", dash=(4, 4))
            if 0.0 <= pen_offset_y <= bed_y:
                y_line = height - (offset_y + pen_offset_y * scale)
                canvas.create_line(x0, y_line, x1, y_line, fill="#f4a259", dash=(4, 4))

            for item, paths, bounds, outside in items:
                color = getattr(item, "color", "#000000")
                for path in paths:
                    if len(path) < 2:
                        continue
                    coords: List[float] = []
                    for x_mm, y_mm in path:
                        x = offset_x + x_mm * scale
                        y = height - (offset_y + y_mm * scale)
                        coords.extend((x, y))
                    canvas.create_line(coords, fill="#000000", width=2)

                min_x, min_y, max_x, max_y = bounds
                x_left = offset_x + min_x * scale
                x_right = offset_x + max_x * scale
                y_top = height - (offset_y + max_y * scale)
                y_bottom = height - (offset_y + min_y * scale)
                outline_color = "#d9534f" if outside else color
                dash_pattern = (6, 3) if outside else (4, 3)
                canvas.create_rectangle(
                    x_left,
                    y_top,
                    x_right,
                    y_bottom,
                    outline=outline_color,
                    dash=dash_pattern,
                    width=2 if outside else 1,
                )
                header_var = getattr(item, "header_var", None)
                label_text = header_var.get() if header_var is not None else ""
                if label_text:
                    canvas.create_text(
                        x_left + 6,
                        y_top + 14,
                        text=label_text,
                        fill=outline_color,
                        anchor="w",
                        font=("TkDefaultFont", 9, "bold"),
                    )

                center_mm = self.item_centers_mm.get(item)
                handle_mm = self.item_handles_mm.get(item)
                if center_mm and handle_mm:
                    cx = offset_x + center_mm[0] * scale
                    cy = height - (offset_y + center_mm[1] * scale)
                    hx = offset_x + handle_mm[0] * scale
                    hy = height - (offset_y + handle_mm[1] * scale)
                    canvas.create_line(cx, cy, hx, hy, fill=outline_color, dash=(3, 2))
                    canvas.create_oval(
                        hx - 6,
                        hy - 6,
                        hx + 6,
                        hy + 6,
                        outline=outline_color,
                        fill="#ffffff",
                        width=2,
                    )

        def save_project(self) -> None:
            if filedialog is None:
                return
            try:
                project_state = self._collect_project_state()
            except ValueError as exc:
                self.status_var.set(f"Projeyi kaydedemedi: {exc}")
                if messagebox is not None:
                    messagebox.showerror("Kaydetme hatası", str(exc))
                return

            initialfile = (
                self.last_project_path.name
                if self.last_project_path is not None
                else "pen_plotter_project.json"
            )
            file_path = filedialog.asksaveasfilename(
                title="Projeyi kaydet",
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("Tüm dosyalar", "*.*")],
                initialfile=initialfile,
            )
            if not file_path:
                return

            try:
                Path(file_path).write_text(
                    json.dumps(project_state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                self.status_var.set(f"Kaydedilemedi: {exc}")
                if messagebox is not None:
                    messagebox.showerror("Kaydetme hatası", str(exc))
                return

            self.last_project_path = Path(file_path)
            self.status_var.set(f"Proje kaydedildi: {file_path}")

        def load_project(self) -> None:
            if filedialog is None:
                return
            file_path = filedialog.askopenfilename(
                title="Projeyi aç",
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("Tüm dosyalar", "*.*")],
            )
            if not file_path:
                return

            try:
                payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
            except OSError as exc:
                self.status_var.set(f"Dosya okunamadı: {exc}")
                if messagebox is not None:
                    messagebox.showerror("Dosya okunamadı", str(exc))
                return
            except json.JSONDecodeError as exc:
                self.status_var.set(f"JSON ayrıştırılamadı: {exc}")
                if messagebox is not None:
                    messagebox.showerror("JSON hatası", str(exc))
                return

            self.last_project_path = Path(file_path)
            previous_pending = self._preview_pending
            self._preview_pending = True

            for block in list(self.blocks):
                self.remove_block(block)

            for shape in list(self.shapes):
                self.remove_shape(shape)

            for key, var in self.hardware_vars.items():
                value = payload.get("hardware", {}).get(key)
                if isinstance(value, (int, float)):
                    var.set(self._fmt(float(value)))
                elif isinstance(value, str):
                    var.set(value)
                else:
                    var.set(self.hardware_defaults[key])

            curve_tol = payload.get("curve_tolerance")
            if isinstance(curve_tol, (int, float)):
                self.curve_tolerance_var.set(self._fmt(float(curve_tol)))
            elif isinstance(curve_tol, str):
                self.curve_tolerance_var.set(curve_tol)
            else:
                self.curve_tolerance_var.set("0.1")

            font_path = payload.get("font_path")
            if isinstance(font_path, str):
                self.font_path_var.set(font_path)
            else:
                self.font_path_var.set("")

            blocks_payload = payload.get("blocks")
            if isinstance(blocks_payload, list) and blocks_payload:
                for entry in blocks_payload:
                    if not isinstance(entry, dict):
                        continue
                    text = str(entry.get("text", ""))
                    self.add_block(text)
                    block = self.blocks[-1]
                    font_size = entry.get("font_size")
                    if isinstance(font_size, (int, float)):
                        block.font_size_var.set(self._fmt(float(font_size)))
                    elif isinstance(font_size, str):
                        block.font_size_var.set(font_size)
                    line_spacing = entry.get("line_spacing")
                    if isinstance(line_spacing, (int, float)):
                        block.line_spacing_var.set(self._fmt(float(line_spacing)))
                    elif isinstance(line_spacing, str):
                        block.line_spacing_var.set(line_spacing)
                    char_spacing = entry.get("character_spacing")
                    if isinstance(char_spacing, (int, float)):
                        block.char_spacing_var.set(self._fmt(float(char_spacing)))
                    elif isinstance(char_spacing, str):
                        block.char_spacing_var.set(char_spacing)
                    translation = entry.get("translation")
                    if (
                        isinstance(translation, (list, tuple))
                        and len(translation) == 2
                    ):
                        try:
                            block.translation_x = float(translation[0])
                            block.translation_y = float(translation[1])
                        except (TypeError, ValueError):
                            pass
                    rotation = entry.get("rotation")
                    if isinstance(rotation, (int, float)):
                        block.rotation_deg = float(rotation)
                    elif isinstance(rotation, str):
                        try:
                            block.rotation_deg = float(rotation)
                        except ValueError:
                            pass
                    block.update_position_label()
            else:
                self.add_block()

            shapes_payload = payload.get("shapes")
            if isinstance(shapes_payload, list) and shapes_payload:
                for entry in shapes_payload:
                    if not isinstance(entry, dict):
                        continue
                    shape_type = entry.get("type")
                    if not isinstance(shape_type, str):
                        continue
                    try:
                        self.add_shape(shape_type)
                    except ValueError:
                        continue
                    shape = self.shapes[-1]
                    params = entry.get("params", {})
                    if isinstance(params, dict):
                        for key, value in params.items():
                            var = shape.param_vars.get(key)
                            if var is None:
                                continue
                            if isinstance(value, (int, float)):
                                var.set(self._fmt(float(value)))
                            elif isinstance(value, str):
                                var.set(value)
                    translation = entry.get("translation")
                    if (
                        isinstance(translation, (list, tuple))
                        and len(translation) == 2
                    ):
                        try:
                            shape.translation_x = float(translation[0])
                            shape.translation_y = float(translation[1])
                        except (TypeError, ValueError):
                            pass
                    rotation = entry.get("rotation")
                    if isinstance(rotation, (int, float)):
                        shape.rotation_deg = float(rotation)
                    elif isinstance(rotation, str):
                        try:
                            shape.rotation_deg = float(rotation)
                        except ValueError:
                            pass
                    shape.update_position_label()

            self._preview_pending = previous_pending
            self.update_block_headers()
            self.update_shape_headers()
            self.schedule_preview()
            self.status_var.set(f"Proje yüklendi: {file_path}")

        def save_gcode(self) -> None:
            if filedialog is None:
                return
            if not self.preview_paths or self.preview_settings is None:
                self.force_refresh(show_dialog=True)
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
            paths_for_output: List[PathType]
            if pen_offset_x or pen_offset_y:
                paths_for_output = translate_paths(
                    self.preview_paths, pen_offset_x, pen_offset_y
                )
            else:
                paths_for_output = [list(path) for path in self.preview_paths]
            gcode_lines = paths_to_gcode(paths_for_output, self.preview_settings)
            Path(file_path).write_text("\n".join(gcode_lines) + "\n", encoding="utf-8")
            self.status_var.set(f"G-code kaydedildi: {file_path}")
            if messagebox is not None:
                messagebox.showinfo("G-code kaydedildi", f"Dosya '{file_path}' olarak kaydedildi.")

        # ------------------------------------------------------- Canvas events --
        def _on_canvas_configure(self, event: tk.Event) -> None:
            self.canvas_width = max(event.width, 200)
            self.canvas_height = max(event.height, 200)
            self.schedule_preview()

        def _canvas_to_mm(self, x: float, y: float) -> Tuple[float, float]:
            scale, offset_x, offset_y = self.canvas_transform
            if scale <= 0:
                return 0.0, 0.0
            mm_x = (x - offset_x) / scale
            mm_y = ((self.canvas_height - y) - offset_y) / scale
            return mm_x, mm_y

        def _on_canvas_press(self, event: tk.Event) -> None:
            if not self.item_bounds_mm:
                return
            mm_x, mm_y = self._canvas_to_mm(event.x, event.y)

            for item in reversed(self.render_stack):
                handle = self.item_handles_mm.get(item)
                center = self.item_centers_mm.get(item)
                if handle and center:
                    distance = math.hypot(mm_x - handle[0], mm_y - handle[1])
                    if distance <= 8.0:
                        self.rotate_item = item
                        vector = (handle[0] - center[0], handle[1] - center[1])
                        base_angle = math.degrees(math.atan2(vector[1], vector[0]))
                        current_rotation = getattr(item, "rotation_deg", 0.0)
                        self.rotate_reference_angle = base_angle - current_rotation
                        self.rotate_center = center
                        header_var = getattr(item, "header_var", None)
                        label_text = header_var.get() if header_var is not None else "Öğe"
                        self.status_var.set(f"{label_text} döndürülüyor...")
                        return

            for item in reversed(self.render_stack):
                bounds = self.item_bounds_mm.get(item)
                if (
                    bounds
                    and bounds[0] - 1e-3 <= mm_x <= bounds[2] + 1e-3
                    and bounds[1] - 1e-3 <= mm_y <= bounds[3] + 1e-3
                ):
                    self.drag_item = item
                    tx = getattr(item, "translation_x", 0.0)
                    ty = getattr(item, "translation_y", 0.0)
                    self.drag_offset = (mm_x - tx, mm_y - ty)
                    header_var = getattr(item, "header_var", None)
                    label_text = header_var.get() if header_var is not None else "Öğe"
                    self.status_var.set(f"{label_text} sürükleniyor...")
                    return

        def _on_canvas_drag(self, event: tk.Event) -> None:
            mm_x, mm_y = self._canvas_to_mm(event.x, event.y)
            if self.rotate_item is not None:
                center_x, center_y = self.rotate_center
                vx = mm_x - center_x
                vy = mm_y - center_y
                if math.hypot(vx, vy) < 1e-3:
                    return
                angle = math.degrees(math.atan2(vy, vx))
                new_rotation = angle - self.rotate_reference_angle
                setattr(self.rotate_item, "rotation_deg", new_rotation)
                update_method = getattr(self.rotate_item, "update_position_label", None)
                if callable(update_method):
                    update_method()
                self.schedule_preview()
                return

            item = self.drag_item
            if item is None:
                return
            mm_x, mm_y = self._canvas_to_mm(event.x, event.y)
            new_tx = mm_x - self.drag_offset[0]
            new_ty = mm_y - self.drag_offset[1]
            setattr(item, "translation_x", new_tx)
            setattr(item, "translation_y", new_ty)
            update_method = getattr(item, "update_position_label", None)
            if callable(update_method):
                update_method()
            self.schedule_preview()

        def _on_canvas_release(self, _event: tk.Event) -> None:
            if self.rotate_item is not None:
                header_var = getattr(self.rotate_item, "header_var", None)
                label_text = header_var.get() if header_var is not None else "Öğe"
                self.status_var.set(f"{label_text} rotasyonu güncellendi.")
            elif self.drag_item is not None:
                header_var = getattr(self.drag_item, "header_var", None)
                label_text = header_var.get() if header_var is not None else "Öğe"
                self.status_var.set(f"{label_text} konumu güncellendi.")
            self.drag_item = None
            self.rotate_item = None

        # ------------------------------------------------------------ Helpers --
        def _shape_paths(
            self, request: _ShapeRequest
        ) -> Tuple[List[PathType], Tuple[float, float, float, float]]:
            params = request.params
            shape_type = request.shape_type
            if shape_type == "rectangle":
                width = max(params.get("width", 0.0), 0.0)
                height = max(params.get("height", 0.0), 0.0)
                half_w = width * 0.5
                half_h = height * 0.5
                path = [
                    (-half_w, -half_h),
                    (half_w, -half_h),
                    (half_w, half_h),
                    (-half_w, half_h),
                    (-half_w, -half_h),
                ]
                local_bounds = (-half_w, -half_h, half_w, half_h)
                return [path], local_bounds
            if shape_type == "line":
                length = max(params.get("length", 0.0), 0.0)
                half = length * 0.5
                path = [(-half, 0.0), (half, 0.0)]
                local_bounds = (-half, -0.1, half, 0.1)
                return [path], local_bounds
            if shape_type == "arrow":
                length = max(params.get("length", 0.0), 0.0)
                head = max(params.get("head", length * 0.25), 0.0)
                half = length * 0.5
                head = min(head, max(length * 0.49, 0.0))
                shaft_end = half - head
                shaft_end = max(shaft_end, -half)
                head_width = max(head * 0.6, head * 0.2, 0.1)
                path = [
                    (-half, 0.0),
                    (shaft_end, 0.0),
                    (shaft_end, head_width),
                    (half, 0.0),
                    (shaft_end, -head_width),
                    (shaft_end, 0.0),
                ]
                local_bounds = (
                    -half,
                    -max(head_width, 0.1),
                    half,
                    max(head_width, 0.1),
                )
                return [path], local_bounds
            return [], (0.0, 0.0, 0.0, 0.0)

        def _parse_float(
            self,
            var: tk.StringVar,
            label: str,
            *,
            default: float,
            min_value: Optional[float] = None,
        ) -> float:
            value_str = var.get().strip()
            if not value_str:
                var.set(self._fmt(default))
                return default
            try:
                value = float(value_str)
            except ValueError as exc:  # pragma: no cover - validated via UI
                raise ValueError(f"'{label}' alanı için geçersiz değer: {value_str}") from exc
            if min_value is not None and value < min_value:
                raise ValueError(f"'{label}' alanı en az {min_value} olmalıdır.")
            return value

        def _fmt(self, value: float) -> str:
            return f"{value:.3f}".rstrip("0").rstrip(".")

        def _collect_project_state(self) -> dict:
            if not self.blocks and not self.shapes:
                raise ValueError("En az bir metin bloğu veya şekil olmalı.")
            font_path = self.font_path_var.get().strip()
            if not font_path:
                raise ValueError("Projeyi kaydetmeden önce bir font seçin.")
            blocks_payload = []
            for block in self.blocks:
                text = block.text_widget.get("1.0", "end-1c")
                blocks_payload.append(
                    {
                        "text": text,
                        "font_size": block.font_size_var.get(),
                        "line_spacing": block.line_spacing_var.get(),
                        "character_spacing": block.char_spacing_var.get(),
                        "translation": [block.translation_x, block.translation_y],
                        "rotation": block.rotation_deg,
                    }
                )
            shapes_payload = []
            for shape in self.shapes:
                shape_entry = {
                    "type": shape.shape_type,
                    "params": {key: var.get() for key, var in shape.param_vars.items()},
                    "translation": [shape.translation_x, shape.translation_y],
                    "rotation": shape.rotation_deg,
                }
                shapes_payload.append(shape_entry)
            return {
                "font_path": font_path,
                "curve_tolerance": self.curve_tolerance_var.get(),
                "hardware": {
                    key: var.get() for key, var in self.hardware_vars.items()
                },
                "blocks": blocks_payload,
                "shapes": shapes_payload,
            }

    PlotterGUI = PenPlotterStudio

    def main() -> None:  # pragma: no cover - launches interactive UI
        if tk is None:
            raise RuntimeError(
                "Tkinter bu ortamda mevcut değil. GUI yalnızca Tk destekli sistemlerde çalışır."
            )
        root = tk.Tk()
        PenPlotterStudio(root)
        root.mainloop()

    __all__ = ["PenPlotterStudio", "PlotterGUI", "main"]
