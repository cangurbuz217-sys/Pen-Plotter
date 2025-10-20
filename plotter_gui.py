"""Standalone launcher for the Pen Plotter Studio GUI."""
from __future__ import annotations

import sys
import textwrap


def _main_with_dependency_guard() -> None:
    """Import and run the GUI while guiding users to missing deps."""

    try:
        from pen_plotter.gui import main  # pylint: disable=import-error
    except ModuleNotFoundError as exc:  # pragma: no cover - manual interaction
        missing = getattr(exc, "name", None) or str(exc)
        message = textwrap.dedent(
            f"""
            Gerekli Python paketi bulunamadı: {missing}

            Lütfen komut satırında aşağıdaki adımı uygulayın ve tekrar deneyin:

                pip install -r requirements.txt

            Kurulum tamamlandıktan sonra 'plotter_gui.py' dosyasını yeniden çalıştırabilirsiniz.
            """
        ).strip()

        print(message, file=sys.stderr)
        if sys.stdin.isatty():
            try:
                input("Devam etmek için Enter'a basın...")
            except EOFError:
                pass
        sys.exit(1)

    main()


if __name__ == "__main__":
    _main_with_dependency_guard()
