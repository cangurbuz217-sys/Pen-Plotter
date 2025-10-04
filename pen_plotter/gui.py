"""Reusable GUI components for the pen plotter application.

The original project shipped a sizeable :mod:`tkinter` user interface in a
single script.  The goal of this module is to expose the same interactive
widgets – hardware configuration, draggable drawing blocks and project
persistence – in a form that can be reused by both the packaged application
and the legacy single-file launcher.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


@dataclass
class HardwareSettings:
    """Configuration values that describe the connected plotter hardware."""

    bed_width: float = 210.0
    bed_height: float = 297.0
    pen_offset_x: float = 0.0
    pen_offset_y: float = 0.0
    pen_up_height: float = 5.0
    pen_down_height: float = 0.0
    travel_feedrate: float = 100.0
    draw_feedrate: float = 60.0
    z_feedrate: float = 30.0

    def to_dict(self) -> dict:
        """Return a serialisable mapping."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "HardwareSettings":
        """Create a :class:`HardwareSettings` instance from a mapping.

        ``data`` may be partial; any missing keys fall back to the defaults
        defined on the dataclass.  Invalid input raises :class:`ValueError`.
        """

        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValueError("Hardware settings must be provided as a mapping")

        fields = {field.name for field in cls.__dataclass_fields__.values()}
        filtered = {key: data[key] for key in data if key in fields}
        return cls(**filtered)


@dataclass
class PlotterProject:
    """Container for an entire plotter project."""

    settings: HardwareSettings = field(default_factory=HardwareSettings)
    blocks: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "settings": self.settings.to_dict(),
            "blocks": list(self.blocks),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PlotterProject":
        if not isinstance(data, dict):
            raise ValueError("Project data must be provided as a mapping")

        settings = HardwareSettings.from_dict(data.get("settings"))
        blocks = data.get("blocks", [])
        if not isinstance(blocks, list):
            raise ValueError("Project block data must be a list of strings")
        text_blocks = [str(block) for block in blocks]
        return cls(settings=settings, blocks=text_blocks)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "PlotterProject":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


class DraggableTextBlock(ttk.Frame):
    """A block of text that can be reordered via drag-and-drop."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "",
        on_change: Optional[Callable[["DraggableTextBlock"], None]] = None,
        on_delete: Optional[Callable[["DraggableTextBlock"], None]] = None,
        request_reorder: Optional[Callable[["DraggableTextBlock", int], None]] = None,
    ) -> None:
        super().__init__(master, padding=4, relief="ridge", borderwidth=2)

        self._on_change = on_change
        self._on_delete = on_delete
        self._request_reorder = request_reorder

        self._dragging = False

        header = ttk.Frame(self)
        header.pack(fill="x")

        drag_handle = ttk.Label(header, text="↕", width=2, anchor="center")
        drag_handle.pack(side="left")
        drag_handle.bind("<ButtonPress-1>", self._start_drag, add="+")
        drag_handle.bind("<B1-Motion>", self._during_drag, add="+")
        drag_handle.bind("<ButtonRelease-1>", self._end_drag, add="+")
        self._drag_handle = drag_handle

        title = ttk.Label(header, text="Block", font=("TkDefaultFont", 10, "bold"))
        title.pack(side="left", padx=(4, 0))
        self._title_label = title

        delete_button = ttk.Button(
            header,
            text="Delete",
            command=lambda: self._on_delete_clicked(),
            width=7,
        )
        delete_button.pack(side="right")

        self._text = tk.Text(self, height=4, wrap="word")
        self._text.pack(fill="both", expand=True, pady=(4, 0))
        self._text.insert("1.0", text)
        self._text.bind("<<Modified>>", self._handle_modified)

    def _on_delete_clicked(self) -> None:
        if self._on_delete:
            self._on_delete(self)

    def _handle_modified(self, event: tk.Event) -> None:
        # ``Text`` widgets keep the modified flag set until explicitly cleared.
        self._text.edit_modified(False)
        if self._on_change:
            self._on_change(self)

    def _start_drag(self, event: tk.Event) -> None:
        self._dragging = True
        self.configure(style="DraggedBlock.TFrame")
        self.after(0, self.lift)

    def _during_drag(self, event: tk.Event) -> None:
        if not self._dragging or not self._request_reorder:
            return
        y_root = self.winfo_rooty() + event.y
        self._request_reorder(self, y_root)

    def _end_drag(self, event: tk.Event) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.configure(style="TFrame")
        if self._request_reorder:
            y_root = self.winfo_rooty() + event.y
            self._request_reorder(self, y_root)

    def get_text(self) -> str:
        return self._text.get("1.0", "end-1c")

    def set_text(self, text: str) -> None:
        self._text.delete("1.0", "end")
        self._text.insert("1.0", text)

    def set_index(self, index: int) -> None:
        self._title_label.configure(text=f"Block {index}")


def generate_gcode(settings: HardwareSettings, blocks: Iterable[str]) -> str:
    """Generate a simple G-code program for the provided blocks.

    The implementation deliberately mirrors the behaviour of the legacy
    single-file tool: it emits comments for each text block alongside the
    machine configuration so that users have a consistent preview regardless of
    the entry point.
    """

    gcode_lines = [
        "; Pen Plotter project",
        f"; Bed size: {settings.bed_width} x {settings.bed_height} mm",
        f"; Pen offset: X{settings.pen_offset_x} Y{settings.pen_offset_y}",
        "G21 ; Set units to millimetres",
        "G90 ; Use absolute positioning",
        f"G0 Z{settings.pen_up_height:.2f} F{settings.z_feedrate * 60:.0f}",
    ]

    for index, text in enumerate(blocks, start=1):
        cleaned = text.strip() or "(empty)"
        gcode_lines.append(f"; Block {index}")
        for line in cleaned.splitlines() or [cleaned]:
            gcode_lines.append(f";   {line}")

    gcode_lines.extend(
        [
            f"; Pen down height: {settings.pen_down_height}",
            f"; Travel feedrate: {settings.travel_feedrate} mm/s",
            f"; Draw feedrate: {settings.draw_feedrate} mm/s",
            "M2",
        ]
    )

    return "\n".join(gcode_lines) + "\n"


class PlotterGUI(tk.Tk):
    """The main application window for the pen plotter GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Pen Plotter GUI")
        self.geometry("1100x680")

        self.project = PlotterProject()
        self.blocks: List[DraggableTextBlock] = []

        self._settings_vars: dict[str, tk.StringVar] = {}

        self._build_styles()
        self._build_layout()
        self._load_project_into_ui(self.project)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("DraggedBlock.TFrame", relief="solid", borderwidth=3)

    def _build_layout(self) -> None:
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True, padx=12, pady=12)

        root.columnconfigure(1, weight=1)
        root.columnconfigure(2, weight=1)
        root.rowconfigure(0, weight=1)

        self._build_settings_panel(root)
        self._build_block_panel(root)
        self._build_preview_panel(root)

        buttons = ttk.Frame(root)
        buttons.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky="ew")
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        buttons.columnconfigure(2, weight=1)

        ttk.Button(buttons, text="Load project", command=self._load_project_dialog).grid(
            row=0, column=0, padx=4, sticky="ew"
        )
        ttk.Button(buttons, text="Save project", command=self._save_project_dialog).grid(
            row=0, column=1, padx=4, sticky="ew"
        )
        ttk.Button(buttons, text="Export G-code", command=self._export_gcode_dialog).grid(
            row=0, column=2, padx=4, sticky="ew"
        )

    def _build_settings_panel(self, root: ttk.Frame) -> None:
        panel = ttk.LabelFrame(root, text="Hardware settings")
        panel.grid(row=0, column=0, sticky="nswe", padx=(0, 12))
        for index in range(6):
            panel.rowconfigure(index, weight=1)
        panel.columnconfigure(1, weight=1)

        self._settings_vars = {
            "bed_width": tk.StringVar(value="210.0"),
            "bed_height": tk.StringVar(value="297.0"),
            "pen_offset_x": tk.StringVar(value="0.0"),
            "pen_offset_y": tk.StringVar(value="0.0"),
            "pen_up_height": tk.StringVar(value="5.0"),
            "pen_down_height": tk.StringVar(value="0.0"),
            "travel_feedrate": tk.StringVar(value="100.0"),
            "draw_feedrate": tk.StringVar(value="60.0"),
            "z_feedrate": tk.StringVar(value="30.0"),
        }

        def _add_row(row: int, label: str, key: str) -> None:
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(panel, textvariable=self._settings_vars[key], width=8)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            entry.bind("<FocusOut>", lambda _e: self._update_gcode())

        _add_row(0, "Bed width (mm)", "bed_width")
        _add_row(1, "Bed height (mm)", "bed_height")
        _add_row(2, "Pen offset X (mm)", "pen_offset_x")
        _add_row(3, "Pen offset Y (mm)", "pen_offset_y")
        _add_row(4, "Pen up height (mm)", "pen_up_height")
        _add_row(5, "Pen down height (mm)", "pen_down_height")
        _add_row(6, "Travel feedrate (mm/s)", "travel_feedrate")
        _add_row(7, "Draw feedrate (mm/s)", "draw_feedrate")
        _add_row(8, "Z feedrate (mm/s)", "z_feedrate")

    def _build_block_panel(self, root: ttk.Frame) -> None:
        panel = ttk.LabelFrame(root, text="Drawing blocks")
        panel.grid(row=0, column=1, sticky="nswe")
        panel.rowconfigure(1, weight=1)
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, text="Add text instructions for the pen plotter.").grid(
            row=0, column=0, sticky="w", padx=4, pady=(4, 2)
        )

        self._block_container = ttk.Frame(panel)
        self._block_container.grid(row=1, column=0, sticky="nswe", padx=4, pady=4)
        self._block_container.columnconfigure(0, weight=1)

        add_button = ttk.Button(panel, text="Add text block", command=lambda: self._add_block())
        add_button.grid(row=2, column=0, sticky="ew", padx=4, pady=(0, 4))

    def _build_preview_panel(self, root: ttk.Frame) -> None:
        panel = ttk.LabelFrame(root, text="G-code preview")
        panel.grid(row=0, column=2, sticky="nswe", padx=(12, 0))
        panel.rowconfigure(0, weight=1)
        panel.columnconfigure(0, weight=1)

        self._gcode_preview = tk.Text(panel, wrap="none")
        self._gcode_preview.grid(row=0, column=0, sticky="nswe")

        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=self._gcode_preview.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._gcode_preview.configure(yscrollcommand=scrollbar.set)

    # ------------------------------------------------------------------
    # Block management
    # ------------------------------------------------------------------
    def _add_block(self, text: str = "") -> None:
        block = DraggableTextBlock(
            self._block_container,
            text=text,
            on_change=lambda _b: self._update_gcode(),
            on_delete=self._remove_block,
            request_reorder=self._request_block_reorder,
        )
        block.grid(column=0, sticky="ew", pady=4)
        self.blocks.append(block)
        self._update_block_numbers()
        self._update_gcode()

    def _remove_block(self, block: DraggableTextBlock) -> None:
        if block in self.blocks:
            self.blocks.remove(block)
            block.destroy()
            self._update_block_numbers()
            self._update_gcode()

    def _request_block_reorder(self, block: DraggableTextBlock, y_root: int) -> None:
        if block not in self.blocks:
            return

        other_blocks = [b for b in self.blocks if b is not block]
        target_index = len(other_blocks)
        for index, sibling in enumerate(other_blocks):
            midpoint = sibling.winfo_rooty() + sibling.winfo_height() / 2
            if y_root < midpoint:
                target_index = index
                break

        new_order = list(other_blocks)
        new_order.insert(target_index, block)

        if new_order == self.blocks:
            return

        self.blocks = new_order

        for widget in self.blocks:
            widget.grid_forget()
        for widget in self.blocks:
            widget.grid(column=0, sticky="ew", pady=4)

        self._update_block_numbers()
        self._update_gcode()

    def _update_block_numbers(self) -> None:
        for index, block in enumerate(self.blocks, start=1):
            block.set_index(index)

    # ------------------------------------------------------------------
    # Project persistence
    # ------------------------------------------------------------------
    def _collect_settings(self) -> HardwareSettings:
        def parse_float(value: str, fallback: float) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return fallback

        current = self.project.settings
        values = {
            key: parse_float(self._settings_vars[key].get(), getattr(current, key))
            for key in self._settings_vars
        }
        return HardwareSettings(**values)

    def _collect_project(self) -> PlotterProject:
        settings = self._collect_settings()
        blocks = [block.get_text() for block in self.blocks]
        return PlotterProject(settings=settings, blocks=blocks)

    def _load_project_into_ui(self, project: PlotterProject) -> None:
        self.project = project

        for key, var in self._settings_vars.items():
            var.set(str(getattr(project.settings, key)))

        for block in list(self.blocks):
            block.destroy()
        self.blocks.clear()

        for text in project.blocks or [""]:
            self._add_block(text)

        self._update_gcode()

    def _load_project_dialog(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open project",
            defaultextension=".json",
            filetypes=[("Plotter project", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            project = PlotterProject.load(Path(filename))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror("Load failed", f"Could not load project: {exc}")
            return
        self._load_project_into_ui(project)

    def _save_project_dialog(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".json",
            filetypes=[("Plotter project", "*.json"), ("All files", "*.*")],
        )
        if not filename:
            return
        project = self._collect_project()
        try:
            project.save(Path(filename))
        except OSError as exc:
            messagebox.showerror("Save failed", f"Could not save project: {exc}")

    def _export_gcode_dialog(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Export G-code",
            defaultextension=".gcode",
            filetypes=[("G-code", "*.gcode"), ("All files", "*.*")],
        )
        if not filename:
            return
        project = self._collect_project()
        try:
            Path(filename).write_text(
                generate_gcode(project.settings, project.blocks), encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror("Export failed", f"Could not write file: {exc}")

    # ------------------------------------------------------------------
    # Derived data updates
    # ------------------------------------------------------------------
    def _update_gcode(self) -> None:
        project = self._collect_project()
        gcode = generate_gcode(project.settings, project.blocks)
        self._gcode_preview.configure(state="normal")
        self._gcode_preview.delete("1.0", "end")
        self._gcode_preview.insert("1.0", gcode)
        self._gcode_preview.configure(state="disabled")


__all__ = [
    "HardwareSettings",
    "PlotterProject",
    "PlotterGUI",
    "DraggableTextBlock",
    "generate_gcode",
]


def main() -> None:
    """Launch the GUI directly when executed as a module."""

    app = PlotterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
