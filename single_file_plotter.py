"""Standalone launcher for the pen plotter GUI.

Historically the project distributed a single Python file that bundled both the
GUI widgets and the application bootstrap.  The refactored package keeps the
same convenience script while delegating the heavy lifting to
:mod:`pen_plotter.gui`.
"""

from __future__ import annotations

from pen_plotter.gui import PlotterGUI


def main() -> None:
    app = PlotterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
