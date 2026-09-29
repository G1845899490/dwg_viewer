from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from dwg_viewer import config
from dwg_viewer.ui.main_window import MainWindow

CAD_SUFFIXES = (".dwg", ".dxf")


def _existing(paths) -> list[str]:
    return [str(path) for path in paths if Path(path).is_file()]


def _startup_open(window: MainWindow) -> None:
    mode = config.get_startup_mode()
    if mode == config.STARTUP_DIALOG:
        window.open_startup()
    elif mode == config.STARTUP_LAST:
        paths = _existing(config.get_last_session_files())
        if paths:
            window.open_files(paths)
        else:
            window.open_startup()
    elif mode == config.STARTUP_FILES:
        window.open_files(_existing(config.get_startup_files()))
    elif mode == config.STARTUP_FOLDER:
        folder = Path(config.get_startup_folder())
        if folder.is_dir():
            paths = sorted(
                str(p)
                for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in CAD_SUFFIXES
            )
            window.open_files(paths)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("DWG Viewer")
    app.setOrganizationName("dwg_viewer")

    config.apply_oda_path()

    window = MainWindow()
    window.show()

    if len(argv) > 1:
        window.open_files(argv[1:])
    else:
        QTimer.singleShot(0, lambda: _startup_open(window))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
