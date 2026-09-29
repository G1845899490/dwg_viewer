from __future__ import annotations

from collections import defaultdict
from typing import Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
)

from ezdxf.addons.drawing.pyqt import (
    CorrespondingDXFEntity,
    CorrespondingDXFParentStack,
)
from ezdxf.entities import DXFEntity

GRID_DIVISIONS = 96


def top_level_entity(item) -> Optional[DXFEntity]:
    parents = item.data(CorrespondingDXFParentStack)
    if parents:
        return parents[0]
    return item.data(CorrespondingDXFEntity)


def item_scene_path(item) -> Optional[QPainterPath]:
    """Returns the geometry of a graphics item mapped to scene coordinates."""
    if isinstance(item, QGraphicsPixmapItem):
        rect = item.sceneBoundingRect()
        path = QPainterPath()
        path.addRect(rect)
        return path
    if isinstance(item, QGraphicsPathItem):
        path = item.path()
    elif isinstance(item, QGraphicsLineItem):
        line = item.line()
        path = QPainterPath()
        path.moveTo(line.p1())
        path.lineTo(line.p2())
    elif isinstance(item, QGraphicsPolygonItem):
        path = QPainterPath()
        path.addPolygon(item.polygon())
    else:
        path = item.shape()
    return item.sceneTransform().map(path)


def entity_handle(entity) -> str:
    try:
        return str(entity.dxf.get("handle", ""))
    except Exception:
        return ""


def _rects_intersect(a: QRectF, b: QRectF) -> bool:
    """Like QRectF.intersects() but also handles zero width/height rectangles
    (horizontal/vertical lines have a zero height/width bounding box)."""
    return not (
        a.right() < b.left()
        or a.left() > b.right()
        or a.bottom() < b.top()
        or a.top() > b.bottom()
    )


class SceneIndex:
    """Spatial index of rendered entity geometry in scene coordinates.

    Geometry is keyed by DXF handle, so both top level entities and entities
    nested in block references can be looked up. The top level handle of a
    block reference owns the union of all its rendered sub entity geometry.
    """

    def __init__(self) -> None:
        self._handle_paths: dict[str, list[QPainterPath]] = defaultdict(list)
        self._handle_bbox: dict[str, QRectF] = {}
        self._handle_filled: dict[str, bool] = {}
        self.top_order: list[str] = []
        self._top_set: set[str] = set()
        self._cell_size = 1.0
        self._grid: dict[tuple[int, int], set[str]] = defaultdict(set)
        self._stroke_cache: dict[tuple[str, int], QPainterPath] = {}

    def _add_path(self, handle: str, path: QPainterPath, filled: bool = False) -> None:
        self._handle_paths[handle].append(path)
        if filled:
            self._handle_filled[handle] = True

    def _mark_top(self, handle: str) -> None:
        if handle and handle not in self._top_set:
            self._top_set.add(handle)
            self.top_order.append(handle)

    def finalize(self) -> None:
        for handle, paths in self._handle_paths.items():
            rect: Optional[QRectF] = None
            for path in paths:
                bbox = path.boundingRect()
                rect = bbox if rect is None else rect.united(bbox)
            if rect is not None:
                self._handle_bbox[handle] = rect
        self._build_grid()

    def _build_grid(self) -> None:
        if not self._handle_bbox:
            return
        global_rect: Optional[QRectF] = None
        for rect in self._handle_bbox.values():
            global_rect = rect if global_rect is None else global_rect.united(rect)
        if global_rect is None:
            return
        span = max(global_rect.width(), global_rect.height(), 1e-6)
        self._cell_size = span / GRID_DIVISIONS
        self._origin = global_rect.topLeft()
        cell = self._cell_size
        for handle in self.top_order:
            rect = self._handle_bbox.get(handle)
            if rect is None:
                continue
            for gx, gy in self._cells(rect):
                self._grid[(gx, gy)].add(handle)

    def _cells(self, rect: QRectF):
        cell = self._cell_size
        ox, oy = self._origin.x(), self._origin.y()
        x0 = int((rect.left() - ox) // cell)
        x1 = int((rect.right() - ox) // cell)
        y0 = int((rect.top() - oy) // cell)
        y1 = int((rect.bottom() - oy) // cell)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                yield gx, gy

    def _query(self, rect: QRectF) -> set[str]:
        found: set[str] = set()
        for key in self._cells(rect):
            found |= self._grid.get(key, set())
        return found

    def paths_for_handle(self, handle: str) -> list[QPainterPath]:
        return self._handle_paths.get(handle, [])

    def bbox_for_handle(self, handle: str) -> Optional[QRectF]:
        return self._handle_bbox.get(handle)

    def count_in_rect(self, rect: QRectF) -> int:
        return len(self.handles_in_rect(rect))

    def handles_in_rect(self, rect: QRectF) -> list[str]:
        """Returns the top level handles of all entities whose geometry
        actually intersects the rectangle."""
        if not self._handle_bbox:
            return []
        candidates = self._query(rect)
        if not candidates:
            return []
        edges = (
            QLineF(rect.topLeft(), rect.topRight()),
            QLineF(rect.topRight(), rect.bottomRight()),
            QLineF(rect.bottomRight(), rect.bottomLeft()),
            QLineF(rect.bottomLeft(), rect.topLeft()),
        )
        center = rect.center()
        result: list[str] = []
        for handle in self.top_order:
            if handle not in candidates:
                continue
            bbox = self._handle_bbox.get(handle)
            if bbox is None or not _rects_intersect(bbox, rect):
                continue
            filled = self._handle_filled.get(handle, False)
            if self._handle_hits_rect(handle, rect, edges, center, filled):
                result.append(handle)
        return result

    def _handle_hits_rect(self, handle, rect, edges, center, filled) -> bool:
        for path in self._handle_paths.get(handle, ()):
            for polygon in path.toSubpathPolygons():
                points = polygon
                count = points.count()
                if count == 0:
                    continue
                for i in range(count):
                    if rect.contains(points.at(i)):
                        return True
                for i in range(count - 1):
                    segment = QLineF(points.at(i), points.at(i + 1))
                    for edge in edges:
                        if segment.intersects(edge)[0] == QLineF.BoundedIntersection:
                            return True
            if filled and path.contains(center):
                return True
        return False

    def _stroke(self, handle: str, tolerance: float) -> QPainterPath:
        key = (handle, int(tolerance * 1000))
        cached = self._stroke_cache.get(key)
        if cached is not None:
            return cached
        stroker = QPainterPathStroker()
        stroker.setWidth(max(tolerance * 2.0, 1e-6))
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        result = QPainterPath()
        for path in self.paths_for_handle(handle):
            result.addPath(stroker.createStroke(path))
        self._stroke_cache[key] = result
        return result

    def pick(self, point: QPointF, tolerance: float) -> list[str]:
        search = QRectF(
            point.x() - tolerance,
            point.y() - tolerance,
            tolerance * 2,
            tolerance * 2,
        )
        candidates = self._query(search)
        hits: list[str] = []
        for handle in self.top_order:
            if handle not in candidates:
                continue
            bbox = self._handle_bbox.get(handle)
            if bbox is None:
                continue
            if not bbox.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(point):
                continue
            if self._stroke(handle, tolerance).contains(point):
                hits.append(handle)
        return hits


def _item_is_filled(item) -> bool:
    getter = getattr(item, "brush", None)
    if getter is None:
        return False
    try:
        return getter().style() != Qt.NoBrush
    except Exception:
        return False


def build_scene_index(scene: QGraphicsScene) -> SceneIndex:
    index = SceneIndex()
    for item in scene.items(Qt.AscendingOrder):
        entity = item.data(CorrespondingDXFEntity)
        if entity is None:
            continue
        path = item_scene_path(item)
        if path is None:
            continue
        filled = _item_is_filled(item)

        parents = item.data(CorrespondingDXFParentStack) or ()
        direct = entity_handle(entity)
        # Register the geometry under the entity itself and under every
        # ancestor entity (nested block references). Otherwise entities in the
        # middle of a nesting chain would not be findable by their handle.
        handles: list[str] = []
        if direct:
            handles.append(direct)
        for ancestor in parents:
            handle = entity_handle(ancestor)
            if handle and handle not in handles:
                handles.append(handle)
        for handle in handles:
            index._add_path(handle, path, filled)

        top_handle = entity_handle(parents[0]) if parents else direct
        index._mark_top(top_handle)
    index.finalize()
    return index
