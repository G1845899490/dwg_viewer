from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import ezdxf
from ezdxf import recover
from ezdxf.addons import odafc
from ezdxf.document import Drawing
from PySide6.QtCore import QObject, Signal

ODA_DXF_VERSION = "ACAD2018"
CACHE_KEEP = 30


class LoadCancelled(Exception):
    pass


def _cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "dwg_viewer" / "dxf_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(source: Path) -> Path:
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{ODA_DXF_VERSION}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.dxf"


def _prune_cache(keep: int = CACHE_KEEP) -> None:
    try:
        files = sorted(
            _cache_dir().glob("*.dxf"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for stale in files[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass



def _oda_executable() -> str:
    from dwg_viewer import config

    path = config.get_oda_path() or odafc.get_win_exec_path()
    if not path or not Path(path).is_file():
        raise FileNotFoundError(
            "未找到 ODA File Converter，请在“设置”中指定 ODAFileConverter.exe 路径。"
        )
    return path


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def _child_env() -> dict[str, str]:
    """Environment for the ODA process without our own Qt configuration.

    Variables such as QT_QPA_PLATFORM (e.g. "offscreen") would otherwise be
    inherited and break the Qt based ODA File Converter.
    """
    env = os.environ.copy()
    for key in (
        "QT_QPA_PLATFORM",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "QT_PLUGIN_PATH",
        "QT_DEBUG_PLUGINS",
    ):
        env.pop(key, None)
    return env


def convert_dwg_to_dxf(
    source: Path, target: Path, progress=None, should_cancel=None
) -> None:
    """Convert a DWG file to DXF using ODA File Converter.

    The converter is executed with its output redirected to a null device and
    the source copied into a dedicated folder under a space-free name. Version
    27.1 crashes when its stdout/stderr are connected to pipes and hangs when
    its filename filter argument contains spaces.
    """
    if progress:
        progress("正在转换 DWG（调用 ODA File Converter）...")
    executable = _oda_executable()
    from dwg_viewer import config

    timeout = max(30, config.get_oda_timeout())
    with tempfile.TemporaryDirectory(prefix="dwg_viewer_in_") as in_dir, tempfile.TemporaryDirectory(
        prefix="dwg_viewer_out_"
    ) as out_dir:
        shutil.copyfile(source, Path(in_dir) / "input.dwg")
        process = subprocess.Popen(
            [
                executable,
                in_dir,
                out_dir,
                ODA_DXF_VERSION,
                "DXF",
                "0",
                "0",
                "*.dwg",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=_hidden_startup_info(),
            env=_child_env(),
        )
        deadline = time.monotonic() + timeout
        while True:
            if should_cancel is not None and should_cancel():
                process.kill()
                process.wait()
                raise LoadCancelled()
            if process.poll() is not None:
                break
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise RuntimeError(
                    f"ODA File Converter 转换超时（超过 {timeout} 秒），已终止。"
                )
            time.sleep(0.1)
        returncode = process.returncode
        outputs = sorted(Path(out_dir).glob("*.dxf"))
        if not outputs:
            raise RuntimeError(
                f"ODA File Converter 未生成 DXF（退出码 {returncode}）。"
            )
        shutil.copyfile(outputs[0], target)


def load_dwg(path: str, progress=None, should_cancel=None) -> Drawing:
    source = Path(path)
    cache = _cache_path(source)
    if cache.is_file() and cache.stat().st_size > 0:
        try:
            if progress:
                progress("正在读取缓存 DXF ...")
            doc = ezdxf.readfile(str(cache))
            doc.filename = str(source)
            return doc
        except Exception:
            cache.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix="dwg_viewer_") as tmp_dir:
        target = Path(tmp_dir) / "input.dxf"
        convert_dwg_to_dxf(
            source, target, progress=progress, should_cancel=should_cancel
        )
        if should_cancel is not None and should_cancel():
            raise LoadCancelled()
        if progress:
            progress("正在解析 DXF ...")
        doc = ezdxf.readfile(str(target))
        doc.filename = str(source)
        try:
            shutil.copyfile(target, cache)
            _prune_cache()
        except OSError:
            pass
        return doc


def load_document(
    path: str, progress=None, audit: bool = True, should_cancel=None
) -> tuple[Drawing, list]:
    p = Path(path)
    if p.suffix.lower() == ".dwg":
        doc = load_dwg(path, progress=progress, should_cancel=should_cancel)
        if should_cancel is not None and should_cancel():
            raise LoadCancelled()
        errors = list(doc.audit().errors) if audit else []
        return doc, errors
    if should_cancel is not None and should_cancel():
        raise LoadCancelled()
    if progress:
        progress("正在读取 DXF ...")
    try:
        doc = ezdxf.readfile(path)
        return doc, list(doc.audit().errors) if audit else []
    except ezdxf.DXFError:
        doc, auditor = recover.readfile(path)
        return doc, list(auditor.errors)


def _block_size(name: str, blocks, cache: dict, depth: int = 0) -> int:
    if name in cache:
        return cache[name]
    if depth > 10:
        return 0
    try:
        block = blocks.get(name)
    except Exception:
        return 0
    if block is None:
        return 0
    cache[name] = 0  # recursion guard
    total = 0
    for entity in block:
        total += 1
        try:
            if entity.dxftype() == "INSERT":
                total += _block_size(entity.dxf.get("name", ""), blocks, cache, depth + 1)
        except Exception:
            pass
    cache[name] = total
    return total


def estimate_complexity(doc: Drawing) -> int:
    """Estimates the number of entities that will be drawn, including entities
    nested inside block references. A single INSERT of a huge block counts as
    one top level entity but explodes during rendering, so the plain modelspace
    length is not a sufficient guard.
    """
    try:
        blocks = doc.blocks
        cache: dict = {}
        total = 0
        for entity in doc.modelspace():
            total += 1
            try:
                if entity.dxftype() == "INSERT":
                    total += _block_size(entity.dxf.get("name", ""), blocks, cache)
            except Exception:
                pass
        return total
    except Exception:
        try:
            return len(doc.modelspace())
        except Exception:
            return 0


def _entity_metric(entity) -> tuple[str, int] | None:
    """Returns (description, size) for potentially heavy entities."""
    try:
        dxftype = entity.dxftype()
        if dxftype == "LWPOLYLINE":
            count = len(entity)
            return (f"顶点 {count}", count) if count >= 5000 else None
        if dxftype == "POLYLINE":
            count = len(entity.vertices)
            return (f"顶点 {count}", count) if count >= 5000 else None
        if dxftype == "SPLINE":
            count = len(entity.control_points) + len(entity.fit_points)
            return (f"控制点 {count}", count) if count >= 5000 else None
        if dxftype == "MESH":
            return ("3D 网格", 1)
        if dxftype in ("HATCH", "MPOLYGON"):
            try:
                pattern = getattr(entity, "pattern", None)
                if pattern is not None and len(pattern.lines) > 0:
                    scale = entity.dxf.get("pattern_scale", 1.0) or 1.0
                    if abs(scale) < 0.1:
                        return (f"图案填充 pattern_scale={scale:g}", 1000000)
            except Exception:
                pass
            return None
        if dxftype in ("ACAD_PROXY_ENTITY", "PROXY"):
            return ("代理图元", 1)
        if dxftype == "INSERT":
            return (f"块引用 {entity.dxf.get('name', '')}", 0)
    except Exception:
        return None
    return None


def analyze_document(doc: Drawing) -> str:
    from collections import Counter

    counts: Counter = Counter()
    heavy: list[tuple[str, str, str, int]] = []
    seen_blocks: set[str] = set()

    def scan(entities, scope: str, is_block: bool) -> None:
        for entity in entities:
            try:
                dxftype = entity.dxftype()
            except Exception:
                continue
            counts[dxftype] += 1
            metric = _entity_metric(entity)
            if metric is not None:
                desc, size = metric
                if size > 0 or desc == "代理图元" or desc == "3D 网格":
                    try:
                        handle = str(entity.dxf.get("handle", ""))
                    except Exception:
                        handle = ""
                    heavy.append((scope, dxftype, f"{desc} handle={handle}", size))
            if is_block and dxftype == "INSERT":
                pass

    try:
        scan(doc.modelspace(), "模型空间", False)
    except Exception:
        pass
    try:
        for block in doc.blocks:
            name = block.name
            if name.startswith("*"):
                continue  # layout blocks mirror model/paper space
            if name in seen_blocks:
                continue
            seen_blocks.add(name)
            scan(block, f"块[{name}]", True)
    except Exception:
        pass

    lines = [f"文件: {doc.filename}", "", "图元类型统计:"]
    for dxftype, number in counts.most_common():
        lines.append(f"  {dxftype}: {number}")
    lines.append("")
    lines.append("可能的重量级图元（前 20）:")
    heavy.sort(key=lambda item: item[3], reverse=True)
    for scope, dxftype, desc, _size in heavy[:20]:
        lines.append(f"  {scope} {dxftype}: {desc}")
    if not heavy:
        lines.append("  （未发现明显重型图元）")
    return "\n".join(lines)


def write_render_report(doc: Drawing) -> str:
    from dwg_viewer import config

    try:
        text = analyze_document(doc)
        path = config.log_dir() / "render_report.log"
        path.write_text(text, encoding="utf-8")
        return str(path)
    except Exception:
        return ""


class DocumentLoader(QObject):
    loaded = Signal(object, list, str, int)
    failed = Signal(str, str)
    progress = Signal(str)
    cancelled = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path
        self._cancel = threading.Event()

    @property
    def path(self) -> str:
        return self._path

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            from dwg_viewer import config

            doc, errors = load_document(
                self._path,
                progress=self.progress.emit,
                audit=not config.get_skip_audit(),
                should_cancel=self._cancel.is_set,
            )
            if self._cancel.is_set():
                raise LoadCancelled()
            try:
                count = estimate_complexity(doc)
            except Exception:
                count = 0
            if self._cancel.is_set():
                raise LoadCancelled()
            try:
                write_render_report(doc)
            except Exception:
                pass
            self.loaded.emit(doc, errors, self._path, count)
        except LoadCancelled:
            self.cancelled.emit(self._path)
        except Exception as exc:  # noqa: BLE001 - surface any loader error to the UI
            self.failed.emit(self._path, f"{type(exc).__name__}: {exc}")
