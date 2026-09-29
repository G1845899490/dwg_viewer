from __future__ import annotations

import os
import sys
from pathlib import Path

import ezdxf
from PySide6.QtCore import QSettings

ORG_NAME = "dwg_viewer"
APP_NAME = "DWG Viewer"

DEFAULT_ODA_CANDIDATES = (
    r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe",
    r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
)


def _settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


def bundled_oda_path() -> str:
    """ODA File Converter shipped inside the frozen application bundle.

    Works for PyInstaller onedir (``_internal/oda``), the legacy layout
    (``oda`` next to the exe) and onefile (``sys._MEIPASS``), regardless of
    where the bundle folder is copied to.
    """
    if not getattr(sys, "frozen", False):
        return ""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "oda" / "ODAFileConverter.exe")
    base = Path(sys.executable).resolve().parent
    candidates.append(base / "oda" / "ODAFileConverter.exe")
    candidates.append(base / "_internal" / "oda" / "ODAFileConverter.exe")
    candidates.append(base / "DWGViewer" / "oda" / "ODAFileConverter.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def autodetect_oda() -> str:
    for candidate in DEFAULT_ODA_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return ""


def get_oda_path() -> str:
    if get_use_bundled_oda():
        bundled = bundled_oda_path()
        if bundled:
            return bundled
    stored = _settings().value("oda/exec_path", "", type=str)
    if stored and Path(stored).is_file():
        return stored
    bundled = bundled_oda_path()
    if bundled:
        return bundled
    return autodetect_oda()


def get_use_bundled_oda() -> bool:
    return _settings().value("oda/use_bundled", True, type=bool)


def set_use_bundled_oda(use: bool) -> None:
    _settings().setValue("oda/use_bundled", bool(use))


def set_oda_path(path: str) -> None:
    _settings().setValue("oda/exec_path", path)
    apply_oda_path(path)


def apply_oda_path(path: str | None = None) -> str:
    resolved = path or get_oda_path()
    if resolved:
        ezdxf.options.set("odafc-addon", "win_exec_path", resolved)
    return resolved


def get_last_dir() -> str:
    stored = _settings().value("files/last_dir", "", type=str)
    if stored and Path(stored).is_dir():
        return stored
    return str(Path.home())


def set_last_dir(path: str) -> None:
    directory = Path(path)
    if directory.is_file():
        directory = directory.parent
    if directory.is_dir():
        _settings().setValue("files/last_dir", str(directory))


# ---------------------------------------------------------------- startup mode
STARTUP_NONE = "none"
STARTUP_DIALOG = "dialog"
STARTUP_LAST = "last"
STARTUP_FILES = "files"
STARTUP_FOLDER = "folder"

VALID_STARTUP_MODES = (
    STARTUP_NONE,
    STARTUP_DIALOG,
    STARTUP_LAST,
    STARTUP_FILES,
    STARTUP_FOLDER,
)


def _string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if item]


def get_startup_mode() -> str:
    mode = _settings().value("startup/mode", STARTUP_DIALOG, type=str)
    return mode if mode in VALID_STARTUP_MODES else STARTUP_DIALOG


def set_startup_mode(mode: str) -> None:
    _settings().setValue("startup/mode", mode)


def get_startup_files() -> list[str]:
    return _string_list(_settings().value("startup/files", []))


def set_startup_files(paths: list[str]) -> None:
    _settings().setValue("startup/files", list(paths))


def get_startup_folder() -> str:
    return _settings().value("startup/folder", "", type=str)


def set_startup_folder(path: str) -> None:
    _settings().setValue("startup/folder", path)


def get_last_session_files() -> list[str]:
    return _string_list(_settings().value("session/files", []))


def set_last_session_files(paths: list[str]) -> None:
    _settings().setValue("session/files", list(paths))


# ---------------------------------------------------------------- performance
def get_skip_audit() -> bool:
    return _settings().value("perf/skip_audit", False, type=bool)


def set_skip_audit(skip: bool) -> None:
    _settings().setValue("perf/skip_audit", bool(skip))


def get_oda_timeout() -> int:
    return _settings().value("perf/oda_timeout", 600, type=int)


def set_oda_timeout(seconds: int) -> None:
    _settings().setValue("perf/oda_timeout", int(seconds))


def get_hatch_timeout() -> float:
    return _settings().value("perf/hatch_timeout", 5.0, type=float)


def set_hatch_timeout(seconds: float) -> None:
    _settings().setValue("perf/hatch_timeout", float(seconds))


def get_ignore_proxy_graphics() -> bool:
    return _settings().value("perf/ignore_proxy", False, type=bool)


def set_ignore_proxy_graphics(ignore: bool) -> None:
    _settings().setValue("perf/ignore_proxy", bool(ignore))


def get_render_entity_limit() -> int:
    return _settings().value("perf/render_entity_limit", 200000, type=int)


def set_render_entity_limit(limit: int) -> None:
    _settings().setValue("perf/render_entity_limit", int(limit))


def get_render_item_limit() -> int:
    return _settings().value("perf/render_item_limit", 1500000, type=int)


def set_render_item_limit(limit: int) -> None:
    _settings().setValue("perf/render_item_limit", int(limit))


def get_render_timeout() -> int:
    return _settings().value("perf/render_timeout", 120, type=int)


def set_render_timeout(seconds: int) -> None:
    _settings().setValue("perf/render_timeout", int(seconds))


def get_block_expand_limit() -> int:
    return _settings().value("perf/block_expand_limit", 300000, type=int)


def set_block_expand_limit(limit: int) -> None:
    _settings().setValue("perf/block_expand_limit", int(limit))


def get_block_cache() -> bool:
    return _settings().value("perf/block_cache", True, type=bool)


def set_block_cache(value: bool) -> None:
    _settings().setValue("perf/block_cache", bool(value))


def get_ignore_entity_types() -> list[str]:
    raw = _settings().value("perf/ignore_types", "", type=str)
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def set_ignore_entity_types(types: list[str]) -> None:
    _settings().setValue("perf/ignore_types", ", ".join(types))


def get_max_hatch_segments() -> int:
    return _settings().value("perf/max_hatch_segments", 120000, type=int)


def set_max_hatch_segments(limit: int) -> None:
    _settings().setValue("perf/max_hatch_segments", int(limit))


# ------------------------------------------------------------- recent files
MAX_RECENT_FILES = 20


def get_recent_files() -> list[str]:
    return _string_list(_settings().value("files/recent", []))


def add_recent_file(path: str) -> None:
    path = str(Path(path))
    recent = get_recent_files()
    recent = [p for p in recent if p != path]
    recent.insert(0, path)
    _settings().setValue("files/recent", recent[:MAX_RECENT_FILES])


def clear_recent_files() -> None:
    _settings().setValue("files/recent", [])


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    directory = Path(base) / "dwg_viewer"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_window_geometry():
    return _settings().value("window/geometry", None)


def set_window_geometry(geometry) -> None:
    _settings().setValue("window/geometry", geometry)


def get_on_top() -> bool:
    return _settings().value("window/on_top", False, type=bool)


def set_on_top(value: bool) -> None:
    _settings().setValue("window/on_top", bool(value))


# ------------------------------------------------------------------ display
def get_display_background() -> str:
    value = _settings().value("display/background", "gray", type=str)
    return value if value in ("gray", "black", "white") else "gray"


def set_display_background(value: str) -> None:
    _settings().setValue("display/background", value)


def get_lineweight_scaling() -> float:
    return _settings().value("display/lineweight_scaling", 1.0, type=float)


def set_lineweight_scaling(value: float) -> None:
    clamped = max(0.1, min(20.0, float(value)))
    _settings().setValue("display/lineweight_scaling", round(clamped, 2))


def get_min_pen_width() -> float:
    return _settings().value("display/min_pen_width", 0.0, type=float)


def set_min_pen_width(value: float) -> None:
    clamped = max(0.0, min(50.0, float(value)))
    _settings().setValue("display/min_pen_width", round(clamped, 2))


def get_monochrome() -> bool:
    return _settings().value("display/monochrome", False, type=bool)


def set_monochrome(value: bool) -> None:
    _settings().setValue("display/monochrome", bool(value))


def get_fast_interaction() -> bool:
    return _settings().value("display/fast_interaction", True, type=bool)


def set_fast_interaction(value: bool) -> None:
    _settings().setValue("display/fast_interaction", bool(value))


def get_antialiasing() -> bool:
    return _settings().value("display/antialiasing", True, type=bool)


def set_antialiasing(value: bool) -> None:
    _settings().setValue("display/antialiasing", bool(value))

