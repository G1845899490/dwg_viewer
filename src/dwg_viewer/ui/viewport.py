from __future__ import annotations

import math
import time
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

from ezdxf import bbox as ezbbox
from ezdxf.addons.drawing.pyqt import _get_x_scale
from ezdxf.entities import DXFEntity

from dwg_viewer import config
from dwg_viewer.core.entity_info import entity_world_extents
from dwg_viewer.core.scene_index import SceneIndex, build_scene_index
from dwg_viewer.ui.scene_batcher import batch_scene

PICK_TOLERANCE_PX = 6.0
INTERACTION_RESTORE_MS = 120
HIGHLIGHT_COLOR = QColor(0, 220, 0, 235)


class CADView(QGraphicsView):
    entity_picked = Signal(object)
    cursor_moved = Signal(float, float)
    view_changed = Signal()
    box_selected = Signal(float, float, float, float, int, object)
    box_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFrameShape(QGraphicsView.NoFrame)
        hints = QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
        if config.get_antialiasing():
            hints |= QPainter.Antialiasing
        self.setRenderHints(hints)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setMouseTracking(True)
        self.setScene(QGraphicsScene())
        self.scale(1, -1)  # so that +y is up (drawing coordinates)

        self._document = None
        self._index: Optional[SceneIndex] = None
        self._panning = False
        self._pan_start = QPoint()
        self._pick_entities: list = []
        self._pick_index = 0
        self._selected_entity = None
        self._highlight_paths: list[QPainterPath] = []
        self._selection_bounds: Optional[QRectF] = None
        self._point_marker: Optional[QPointF] = None
        self._range_marker: Optional[QRectF] = None
        self._box_rect: Optional[QRectF] = None
        self._box_selecting = False
        self._box_start = QPointF()
        self._default_zoom = 1.0
        self._content_rect: Optional[QRectF] = None
        self._user_interacted = False
        self._world_extents_cache: dict = {}
        self._last_cursor_emit = 0.0
        self._interacting = False
        self._needs_fit = False
        self._interaction_timer = QTimer(self)
        self._interaction_timer.setSingleShot(True)
        self._interaction_timer.setInterval(INTERACTION_RESTORE_MS)
        self._interaction_timer.timeout.connect(self._end_interaction)

    # ------------------------------------------------------------------ model
    def set_document(self, document) -> None:
        self._document = document

    def reset_overlays(self) -> None:
        self._pick_entities = []
        self._pick_index = 0
        self._selected_entity = None
        self._highlight_paths = []
        self._selection_bounds = None
        self._point_marker = None
        self._range_marker = None
        self._box_rect = None
        self._box_selecting = False

    def _reset_caches(self) -> None:
        self._index = None
        self._world_extents_cache = {}

    def begin_loading(self) -> None:
        self.reset_overlays()
        self._reset_caches()
        self.scene().clear()
        self.viewport().update()

    def set_scene_and_fit(self, scene: QGraphicsScene) -> None:
        self._reset_caches()
        self._index = build_scene_index(scene)
        batched = batch_scene(scene)
        self.setScene(batched)
        rect = batched.sceneRect()
        if rect.isNull() or not rect.isValid():
            return
        self._content_rect = rect
        # A generous scene rect keeps the view scrollable so zooming can always
        # keep the cursor position fixed, even when the cursor is off content.
        margin_x = max(rect.width(), 1.0)
        margin_y = max(rect.height(), 1.0)
        batched.setSceneRect(
            rect.adjusted(-margin_x, -margin_y, margin_x, margin_y)
        )
        self.fit_to_scene()
        self.reset_overlays()
        self._needs_fit = not self.isVisible()
        self._user_interacted = False

    def fit_to_scene(self, *, user: bool = False) -> None:
        if user:
            self._user_interacted = True
        rect = self._content_rect or self.sceneRect()
        if rect.isNull() or not rect.isValid():
            return
        margin_x = rect.width() * 0.05
        margin_y = rect.height() * 0.05
        self.fitInView(
            rect.adjusted(-margin_x, -margin_y, margin_x, margin_y),
            Qt.KeepAspectRatio,
        )
        self._default_zoom = _get_x_scale(self.transform()) or 1.0

    # --------------------------------------------------------- interaction fx
    def _begin_interaction(self) -> None:
        if not self._interacting:
            self._interacting = True
            self.setRenderHint(QPainter.Antialiasing, False)
            self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self._interaction_timer.start()

    def _end_interaction(self) -> None:
        self._interacting = False
        self.setRenderHint(QPainter.Antialiasing, config.get_antialiasing())
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.viewport().update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if (self._needs_fit or not self._user_interacted) and not self.sceneRect().isNull():
            self._needs_fit = False
            self.fit_to_scene()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._user_interacted and not self.sceneRect().isNull():
            self.fit_to_scene()

    # -------------------------------------------------------------- pan / zoom
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self._panning = True
            self._user_interacted = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            self._begin_interaction()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            if self._box_rect is not None:
                self._box_rect = None
                self.box_cleared.emit()
                self.viewport().update()
            self._pick(event.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._box_selecting:
            current = self.mapToScene(event.pos())
            self._box_rect = self._rect_from_points(self._box_start, current)
            self.viewport().update()
            event.accept()
            return
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            self._begin_interaction()
            event.accept()
            return
        scene_pos = self.mapToScene(event.pos())
        now = time.monotonic()
        if now - self._last_cursor_emit >= 0.033:
            self._last_cursor_emit = now
            self.cursor_moved.emit(scene_pos.x(), scene_pos.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._box_selecting and event.button() == Qt.LeftButton:
            self._box_selecting = False
            self.unsetCursor()
            current = self.mapToScene(event.pos())
            rect = self._rect_from_points(self._box_start, current)
            self._box_rect = rect
            if rect.width() > 0 and rect.height() > 0:
                xmin, xmax = sorted((rect.left(), rect.right()))
                ymin, ymax = sorted((rect.top(), rect.bottom()))
                left, top, right, bottom = xmin, ymax, xmax, ymin
                handles = (
                    self._index.handles_in_rect(rect) if self._index else []
                )
                self.box_selected.emit(
                    left, top, right, bottom, len(handles), handles
                )
            self.viewport().update()
            event.accept()
            return
        if event.button() == Qt.RightButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._box_selecting = True
            self._box_start = self.mapToScene(event.pos())
            self._box_rect = None
            self.setCursor(Qt.CrossCursor)
            self.viewport().update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _rect_from_points(p1: QPointF, p2: QPointF) -> QRectF:
        xmin, xmax = sorted((p1.x(), p2.x()))
        ymin, ymax = sorted((p1.y(), p2.y()))
        return QRectF(xmin, ymin, xmax - xmin, ymax - ymin)

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120.0
        if notches == 0:
            event.accept()
            return
        self._begin_interaction()
        factor = 1.2 ** notches
        self._user_interacted = True
        view_pos = event.position().toPoint()
        anchor_scene = self.mapToScene(view_pos)
        self.scale(factor, factor)
        moved = self.mapFromScene(anchor_scene)
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        hbar.setValue(hbar.value() + (moved.x() - view_pos.x()))
        vbar.setValue(vbar.value() + (moved.y() - view_pos.y()))
        event.accept()

    # ---------------------------------------------------------------- picking
    def _resolve_handle(self, handle: str):
        if not handle or self._document is None:
            return None
        return self._document.entitydb.get(handle)

    @staticmethod
    def _handle_of(entity) -> str:
        try:
            return str(entity.dxf.get("handle", ""))
        except Exception:
            return ""

    def _pick(self, view_pos: QPoint) -> None:
        if self._index is None:
            return
        scene_pos = self.mapToScene(view_pos)
        scale = _get_x_scale(self.transform()) or 1.0
        tolerance = PICK_TOLERANCE_PX / scale
        handles = self._index.pick(scene_pos, tolerance)

        entities: list = []
        seen: set[int] = set()
        for handle in handles:
            entity = self._resolve_handle(handle)
            if entity is None or id(entity) in seen:
                continue
            seen.add(id(entity))
            entities.append(entity)

        if not entities:
            self._pick_entities = []
            self._pick_index = 0
            self._clear_selection()
            self._point_marker = None
            self._range_marker = None
            self.entity_picked.emit(None)
            self.viewport().update()
            return

        if entities == self._pick_entities:
            self._pick_index = (self._pick_index + 1) % len(entities)
        else:
            self._pick_entities = entities
            self._pick_index = 0
        self._point_marker = None
        self._range_marker = None
        self._set_selected(entities[self._pick_index])
        self.entity_picked.emit(self._selected_entity)
        self.viewport().update()

    def _clear_selection(self) -> None:
        self._selected_entity = None
        self._highlight_paths = []
        self._selection_bounds = None

    def _set_selected(self, entity) -> None:
        handle = self._handle_of(entity)
        paths: list[QPainterPath] = []
        if self._index is not None and handle:
            paths = list(self._index.paths_for_handle(handle))
        if not paths:
            rect = self._entity_extents_rect(entity)
            if rect is not None:
                fallback = QPainterPath()
                fallback.addRect(rect)
                paths = [fallback]
        self._selected_entity = entity
        self._highlight_paths = paths
        bounds = None
        if self._index is not None and handle:
            bounds = self._index.bbox_for_handle(handle)
        if bounds is None:
            bounds = self._union_bounds(paths)
        self._selection_bounds = bounds

    @staticmethod
    def _union_bounds(paths) -> Optional[QRectF]:
        result: Optional[QRectF] = None
        for path in paths:
            rect = path.boundingRect()
            result = rect if result is None else result.united(rect)
        return result

    def _entity_extents_rect(self, entity) -> Optional[QRectF]:
        handle = self._handle_of(entity)
        if handle and handle in self._world_extents_cache:
            extents = self._world_extents_cache[handle]
        else:
            try:
                extents = entity_world_extents(entity)
            except Exception:
                extents = None
            if handle:
                self._world_extents_cache[handle] = extents
        if extents is None:
            return None
        extmin, extmax = extents
        xmin, xmax = sorted((extmin.x, extmax.x))
        ymin, ymax = sorted((extmin.y, extmax.y))
        return QRectF(xmin, ymin, xmax - xmin, ymax - ymin)

    def select_entity(self, entity) -> bool:
        if entity is None:
            return False
        self._user_interacted = True
        self._set_selected(entity)
        if not self._highlight_paths:
            return False
        self._pick_entities = [entity]
        self._pick_index = 0
        self._point_marker = None
        self._range_marker = None
        if self._selection_bounds is not None:
            self._fit_rect(self._selection_bounds, min_view=True)
        self.entity_picked.emit(entity)
        self.viewport().update()
        return True

    # ------------------------------------------------------------------ locate
    def locate_point(self, x: float, y: float) -> None:
        self._user_interacted = True
        self._range_marker = None
        self._pick_entities = []
        self._pick_index = 0
        self._clear_selection()
        self._point_marker = QPointF(x, y)
        self.centerOn(x, y)
        self.view_changed.emit()
        self.viewport().update()

    def locate_bounds(self, left: float, top: float, right: float, bottom: float) -> None:
        self._user_interacted = True
        self._point_marker = None
        self._pick_entities = []
        self._pick_index = 0
        self._clear_selection()
        xmin, xmax = sorted((left, right))
        ymin, ymax = sorted((top, bottom))
        self._range_marker = QRectF(xmin, ymin, xmax - xmin, ymax - ymin)
        self._fit_rect(self._range_marker, min_view=False)
        self.view_changed.emit()
        self.viewport().update()

    def _fit_rect(self, rect: QRectF, *, min_view: bool) -> None:
        if not rect.isValid():
            return
        if rect.width() == 0 and rect.height() == 0:
            self.centerOn(rect.center())
            return
        margin = max(rect.width(), rect.height()) * 0.1
        target = rect.adjusted(-margin, -margin, margin, margin)
        self.fitInView(target, Qt.KeepAspectRatio)
        # Re-center on the target center. Do NOT clamp the zoom with scale():
        # with NoAnchor that scales about the viewport top-left and displaces
        # tiny entities (this was the cause of wrong ID locate positions).
        self.centerOn(rect.center())

    # --------------------------------------------------------------- painting
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)

        if self._highlight_paths:
            painter.save()
            if self._selection_bounds is not None:
                box_pen = QPen(QColor(0, 200, 0, 170))
                box_pen.setCosmetic(True)
                box_pen.setWidth(1)
                box_pen.setStyle(Qt.DashLine)
                painter.setPen(box_pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(self._selection_bounds)
            pen = QPen(HIGHLIGHT_COLOR)
            pen.setCosmetic(True)
            pen.setWidth(3)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for path in self._highlight_paths:
                painter.drawPath(path)
            painter.restore()

        if self._range_marker is not None:
            painter.save()
            pen = QPen(QColor(0, 160, 255, 230))
            pen.setCosmetic(True)
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(0, 160, 255, 40)))
            painter.drawRect(self._range_marker)
            painter.restore()

        if self._box_rect is not None:
            painter.save()
            pen = QPen(QColor(255, 140, 0, 235))
            pen.setCosmetic(True)
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(255, 140, 0, 40)))
            painter.drawRect(self._box_rect)
            painter.restore()

        if self._point_marker is not None:
            self._draw_point_marker(painter)

        self._draw_scale_bar(painter)

    def _draw_scale_bar(self, painter: QPainter) -> None:
        scale = _get_x_scale(self.transform())
        if scale <= 0:
            return
        viewport = self.viewport().rect()
        max_px = max(80.0, viewport.width() * 0.35)
        # Choose a power-of-ten unit such that the "10 unit" bar is about 100 px,
        # then clamp so the longest bar fits. This makes the reference always
        # visible and scales the numbers up/down (1,2,5,10 -> 100,200,500,1000...).
        target_unit = 100.0 / (10.0 * scale)
        try:
            exponent = math.floor(math.log10(target_unit))
        except (ValueError, OverflowError):
            exponent = 0
        unit = 10.0 ** exponent
        while 10.0 * unit * scale > max_px and unit > 1e-12:
            unit /= 10.0
        while unit * scale < 4.0 and unit < 1e12:
            unit *= 10.0
        values = [1.0 * unit, 2.0 * unit, 5.0 * unit, 10.0 * unit]

        metrics = painter.fontMetrics()
        bars = [(value, value * scale) for value in values if value * scale >= 1.0]
        if not bars:
            return

        spacing = 18
        pad = 8
        label_width = max(metrics.horizontalAdvance(f"{value:g}") for value, _ in bars)
        box_width = int(pad * 2 + max(length for _, length in bars) + 8 + label_width)
        box_height = int(pad * 2 + spacing * len(bars))
        left = 12
        top = viewport.height() - 12 - box_height

        painter.save()
        painter.setWorldMatrixEnabled(False)
        painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
        painter.setPen(QPen(QColor(120, 120, 120, 220), 1))
        painter.drawRoundedRect(left, top, box_width, box_height, 4, 4)

        painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
        y = top + pad + spacing // 2
        for value, length in bars:
            x0 = left + pad
            x1 = int(x0 + length)
            painter.drawLine(x0, int(y), x1, int(y))
            painter.drawLine(x0, int(y) - 4, x0, int(y) + 4)
            painter.drawLine(x1, int(y) - 4, x1, int(y) + 4)
            painter.drawText(x1 + 6, int(y) + 4, f"{value:g}")
            y += spacing
        painter.restore()

    def _draw_point_marker(self, painter: QPainter) -> None:
        view_point = self.mapFromScene(self._point_marker)
        painter.save()
        painter.setWorldMatrixEnabled(False)
        pen = QPen(QColor(255, 40, 40, 230))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        x, y = view_point.x(), view_point.y()
        painter.drawLine(int(x) - 14, int(y), int(x) + 14, int(y))
        painter.drawLine(int(x), int(y) - 14, int(x), int(y) + 14)
        painter.drawEllipse(view_point, 6, 6)
        painter.drawText(
            view_point + QPointF(12, -12),
            f"({self._point_marker.x():g}, {self._point_marker.y():g})",
        )
        painter.restore()
