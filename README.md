# Pen-Plotter

This repository contains a reusable `tkinter` GUI for driving a pen plotter.
The interface can be launched either via the package entry point or the legacy
`single_file_plotter.py` script.  Both entry points now use the same
implementation so the hardware controls and project behaviour remain in sync.

## Running the GUI

```bash
python -m pen_plotter.gui  # launches the packaged application
# or
python single_file_plotter.py
```

The window exposes the following controls:

- **Hardware settings** – bed size, pen offsets, pen heights and feed rates.
- **Drawing blocks** – draggable text blocks that describe the drawing.
- **Project tools** – save/load project files and export generated G-code.

Projects are stored as JSON files that capture the hardware configuration and
block contents.  The same file can be loaded by either entry point.
