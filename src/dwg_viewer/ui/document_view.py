from __future__ import annotations

import time
from typing import Optional

import ezdxf
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsScene,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ezdxf import bbox, reorder
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import (
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
    ProxyGraphicPolicy,
)
from ezdxf.addons.drawing.frontend import _draw_viewports
from ezdxf.addons.drawing.gfxproxy import DXFGraphicProxy
from ezdxf.addons.drawing.pyqt import PyQtBackend
from ezdxf.document import Drawing
from ezdxf.entities import DXFEntity, DXFGraphic, Viewport

from dwg_viewer import config
from dwg_viewer.core.fonts_cjk import install_cjk_fallback
from dwg_viewer.core.limited_frontend import (
    LimitedFrontend,
    RenderAborted,
    RenderCancelled,
)
from dwg_viewer.ui.viewport import CADView

SLOW_ENTITY_SECONDS = 2.0


class _CountingBackend(PyQtBackend):
    """PyQtBackend which counts created graphics items and can enforce a
    minimum on-screen line width (only thin lines get thickened)."""

    def __init__(self, scene=None):
        super().__init__(scene)
        self.item_count = 0
        self.min_pen_width_px = 0.0

    def _add_item(self, item, entity_handle) -> None:
        self.item_count += 1
        super()._add_item(item, entity_handle)

    def _get_pen(self, properties):
        pen = super()._get_pen(properties)
        width = pen.widthF()
        if self.min_pen_width_px > 0.0 and width < self.min_pen_width_px:
            width = self.min_pen_width_px
        # Quantize the on-screen width to 0.25 px steps: keeps the number of
        # distinct pen styles small so the batching step can merge more items.
        width = round(width * 4.0) / 4.0
        if width != pen.widthF():
            pen.setWidthF(width)
        return pen


class DocumentView(QWidget):
    selection_changed = Signal(object)
    status_message = Signal(str)
    coordinate_changed = Signal(float, float)
    box_selected = Signal(float, float, float, float, int, object)
    box_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = CADView(self)
        layout.addWidget(self.view)
        self.placeholder = QLabel(self)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setVisible(False)
        layout.addWidget(self.placeholder)

        self._doc: Optional[Drawing] = None
        self._path: Optional[str] = None
        self._render_context: Optional[RenderContext] = None
        self._backend = PyQtBackend()
        self._bbox_cache = bbox.Cache()
        self._config = Configuration()
        self._selected_entity: Optional[DXFEntity] = None
        self._rendered = False
        self._entity_count = 0
        self._render_abort_reason = ""

        self.view.entity_picked.connect(self._on_entity_picked)
        self.view.cursor_moved.connect(self.coordinate_changed)
        self.view.box_selected.connect(self.box_selected)
        self.view.box_cleared.connect(self.box_cleared)
    # ------------------------------------------------------------------ model
    @property
    def doc(self) -> Optional[Drawing]:
        return self._doc

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def selected_entity(self) -> Optional[DXFEntity]:
        return self._selected_entity

    @property
    def is_rendered(self) -> bool:
        return self._rendered

    def set_document(self, doc: Drawing, path: Optional[str] = None) -> None:
        self._doc = doc
        self._path = path
        self.view.set_document(doc)
        self._render_context = RenderContext(doc)
        self._bbox_cache = bbox.Cache()
        self._selected_entity = None
        self._rendered = False

    def ensure_rendered(self, should_cancel=None, on_progress=None) -> bool:
        if self._rendered or self._doc is None:
            return True
        self.placeholder.setVisible(False)
        self._render_abort_reason = ""
        ok = self._draw(should_cancel=should_cancel, on_progress=on_progress)
        if ok:
            self._rendered = True
        else:
            self.view.begin_loading()
        return ok

    @property
    def render_abort_reason(self) -> str:
        return self._render_abort_reason

    def set_entity_count(self, count: int) -> None:
        self._entity_count = max(0, int(count))

    def document_entity_count(self) -> int:
        if self._entity_count:
            return self._entity_count
        if self._doc is None:
            return 0
        try:
            return len(self._doc.modelspace())
        except Exception:
            return 0

    def rerender(self, should_cancel=None, on_progress=None) -> bool:
        if self._doc is None:
            return False
        self._rendered = False
        return self.ensure_rendered(
            should_cancel=should_cancel, on_progress=on_progress
        )

    def apply_render_settings(self) -> None:
        from PySide6.QtGui import QPainter

        self.view.setRenderHint(QPainter.Antialiasing, config.get_antialiasing())

    def set_skipped(self, message: str) -> None:
        self.placeholder.setText(message)
        self.placeholder.setVisible(True)

    def _draw(self, should_cancel=None, on_progress=None) -> bool:
        if self._doc is None:
            return False
        install_cjk_fallback()
        background = config.get_display_background()
        if background == "black":
            background_policy = BackgroundPolicy.BLACK
            custom_bg = "#000000FF"
        elif background == "white":
            background_policy = BackgroundPolicy.WHITE
            custom_bg = "#FFFFFFFF"
        else:
            background_policy = BackgroundPolicy.CUSTOM
            custom_bg = "#212830FF"
        if config.get_monochrome():
            color_policy = (
                ColorPolicy.MONOCHROME_LIGHT_BG
                if background == "white"
                else ColorPolicy.MONOCHROME_DARK_BG
            )
        else:
            color_policy = ColorPolicy.COLOR
        self._config = Configuration(
            hatching_timeout=max(1.0, config.get_hatch_timeout()),
            proxy_graphic_policy=(
                ProxyGraphicPolicy.IGNORE
                if config.get_ignore_proxy_graphics()
                else ProxyGraphicPolicy.SHOW
            ),
            background_policy=background_policy,
            custom_bg_color=custom_bg,
            color_policy=color_policy,
            lineweight_scaling=max(0.1, config.get_lineweight_scaling()),
        )
        ignore_types = set(config.get_ignore_entity_types())
        item_limit = config.get_render_item_limit()
        render_timeout = config.get_render_timeout()
        start_time = time.perf_counter()

        self.view.begin_loading()
        scene = QGraphicsScene()
        self._backend = _CountingBackend(scene)
        self._backend.min_pen_width_px = max(0.0, config.get_min_pen_width())
        layout = self._doc.modelspace()
        self._render_context.set_current_layout(layout)

        frontend = LimitedFrontend(
            ctx=self._render_context,
            out=self._backend,
            config=self._config,
            bbox_cache=self._bbox_cache,
        )
        frontend.max_hatch_segments = max(1000, config.get_max_hatch_segments())
        frontend.ignore_types = set(ignore_types)
        frontend.nested_entity_limit = max(0, config.get_block_expand_limit())
        frontend.use_block_cache = config.get_block_cache()
        frontend.set_background(
            self._render_context.current_layout_properties.background_color
        )
        frontend.parent_stack = []

        handle_mapping = list(layout.get_redraw_order())
        if handle_mapping:
            entities = reorder.ascending(layout, handle_mapping)
        else:
            entities = iter(layout)
        total = len(handle_mapping) if handle_mapping else self.document_entity_count()

        slow_entities: list[tuple[str, str, float]] = []
        viewports: list[Viewport] = []
        last_yield = time.perf_counter()
        last_heartbeat = 0.0
        progress_state = {"index": 0}

        def yield_hook() -> None:
            nonlocal last_yield
            now = time.perf_counter()
            if now - last_yield < 0.05:
                return
            last_yield = now
            if should_cancel is not None and should_cancel():
                raise RenderCancelled()
            if render_timeout > 0 and (now - start_time) > render_timeout:
                raise RenderAborted(
                    f"渲染超时（超过 {render_timeout} 秒），已中止。"
                    "可尝试：设置里“忽略图元类型”填 HATCH、SPLINE、3DFACE、PROXY 等，"
                    "或调低“图案填充线段总预算 / 渲染图形对象上限”。"
                )
            if on_progress is not None:
                index = progress_state["index"]
                on_progress(index, max(total, index + 1))
            QApplication.processEvents()
            if item_limit > 0 and self._backend.item_count > item_limit:
                raise RenderAborted(
                    f"图形对象过多（超过 {item_limit}），已中止渲染"
                )

        frontend.yield_hook = yield_hook

        try:
            for index, entity in enumerate(entities):
                progress_state["index"] = index
                now = time.perf_counter()
                if now - last_heartbeat >= 0.2:
                    self._write_heartbeat(entity, index, total)
                    last_heartbeat = now
                yield_hook()

                if isinstance(entity, Viewport):
                    viewports.append(entity)
                    continue
                if not isinstance(entity, DXFGraphic):
                    if self._config.proxy_graphic_policy != ProxyGraphicPolicy.IGNORE:
                        entity = DXFGraphicProxy(entity)
                    else:
                        frontend.skip_entity(entity, "Cannot parse DXF entity")
                        continue
                if ignore_types and entity.dxftype().upper() in ignore_types:
                    frontend.skip_entity(entity, "ignored by user setting")
                    continue

                start = time.perf_counter()
                properties = self._render_context.resolve_all(entity)
                frontend.exec_property_override(entity, properties)
                if properties.is_visible:
                    frontend.draw_entity(entity, properties)
                else:
                    frontend.skip_entity(entity, "invisible")
                elapsed = time.perf_counter() - start
                if elapsed >= SLOW_ENTITY_SECONDS:
                    try:
                        dxftype = entity.dxftype()
                        handle = str(entity.dxf.get("handle", ""))
                        slow_entities.append((dxftype, handle, elapsed))
                        self._append_slow_entity(dxftype, handle, elapsed)
                    except Exception:
                        pass
        except RenderCancelled:
            self._backend.finalize()
            self._render_abort_reason = "已取消"
            return False
        except RenderAborted as exc:
            self._backend.finalize()
            self._render_abort_reason = exc.reason
            return False
        finally:
            frontend.yield_hook = None
        del slow_entities

        _draw_viewports(frontend, viewports)
        self._backend.finalize()
        if getattr(frontend, "truncated_hatches", None):
            handles = [h for h in frontend.truncated_hatches if h and h != "?"]
            summary = ", ".join(handles[:50]) if handles else "多个"
            self._append_note(
                f"截断的图案填充数量: {len(frontend.truncated_hatches)} handle: {summary}"
            )
        if getattr(frontend, "expand_truncated", False):
            self._append_note(
                f"块展开达到上限 {frontend.nested_entity_limit} 个虚拟图元，已停止继续展开。"
            )
            self.status_message.emit(
                "块展开量达到上限，部分块内容未渲染（可在设置中调高“块展开上限”）。"
            )
        self._write_heartbeat(None, total, total)
        self.view.set_scene_and_fit(scene)
        return True

    def _write_heartbeat(self, entity, index: int, total: int) -> None:
        try:
            path = config.log_dir() / "render_heartbeat.txt"
            if entity is None:
                path.write_text("渲染完成\n", encoding="utf-8")
                return
            dxftype = entity.dxftype()
            handle = ""
            if isinstance(entity, DXFGraphic):
                handle = str(entity.dxf.get("handle", ""))
            path.write_text(
                f"{self._path}\n进度: {index}/{total}\n当前图元: {dxftype} handle={handle}\n",
                encoding="utf-8",
            )
        except Exception:
            pass

    def _append_slow_entity(self, dxftype: str, handle: str, elapsed: float) -> None:
        try:
            path = config.log_dir() / "render_slow.log"
            with open(path, "a", encoding="utf-8") as fp:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                fp.write(
                    f"[{stamp}] {self._path} {dxftype} handle={handle} {elapsed:.2f}s\n"
                )
        except OSError:
            pass

    def _append_note(self, note: str) -> None:
        try:
            path = config.log_dir() / "render_slow.log"
            with open(path, "a", encoding="utf-8") as fp:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                fp.write(f"[{stamp}] {self._path} {note}\n")
        except OSError:
            pass

    # -------------------------------------------------------------- selection
    def _on_entity_picked(self, entity) -> None:
        self._selected_entity = entity
        self.selection_changed.emit(entity)

    # ---------------------------------------------------------------- locate
    def locate_point(self, x: float, y: float) -> None:
        self.view.locate_point(x, y)

    def locate_bounds(self, left: float, top: float, right: float, bottom: float) -> None:
        self.view.locate_bounds(left, top, right, bottom)

    def select_by_handle(self, handle: str) -> tuple[bool, str]:
        if self._doc is None:
            return False, "没有打开的图纸。"
        raw = handle.strip()
        if raw.lower().startswith("0x"):
            raw = raw[2:]
        if not raw:
            return False, "请输入 Handle。"
        candidates = {raw, raw.upper()}
        try:
            candidates.add(format(int(raw, 16), "X"))
        except ValueError:
            pass
        entity = None
        for candidate in candidates:
            entity = self._doc.entitydb.get(candidate)
            if entity is not None:
                break
        if entity is None:
            return False, f"未找到 Handle 为 {raw} 的图元。"
        if not self.view.select_entity(entity):
            return False, "图元存在但没有可显示的图形。"
        self._selected_entity = entity
        return True, f"已选中 {entity.dxftype()} (Handle {raw})"
