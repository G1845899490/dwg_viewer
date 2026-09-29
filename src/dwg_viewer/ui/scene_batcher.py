from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
)

from dwg_viewer.core.scene_index import item_scene_path

MAX_POINTS_PER_BATCH = 40000


def _brush_of(item):
    getter = getattr(item, "brush", None)
    return getter() if getter is not None else None


def _mergeable(item) -> bool:
    if isinstance(item, QGraphicsPixmapItem):
        return False
    if not isinstance(
        item, (QGraphicsPathItem, QGraphicsLineItem, QGraphicsPolygonItem)
    ):
        return False
    if not item.transform().isIdentity():
        return False
    brush = _brush_of(item)
    if brush is not None:
        style = brush.style()
        if style not in (Qt.NoBrush, Qt.SolidPattern):
            return False
    return True


def _style_key(item):
    pen: QPen = item.pen()
    brush = _brush_of(item)
    brush_color = brush.color().rgba() if brush is not None else 0
    brush_style = brush.style() if brush is not None else Qt.NoBrush
    return (
        pen.color().rgba(),
        round(pen.widthF(), 3),
        pen.style(),
        pen.capStyle(),
        pen.joinStyle(),
        bool(pen.isCosmetic()),
        brush_color,
        brush_style,
        round(item.zValue(), 3),
    )


class _Batch:
    __slots__ = ("key", "path", "pen", "brush", "z", "points")

    def __init__(self, key, pen, brush, z):
        self.key = key
        self.path = QPainterPath()
        self.pen = pen
        self.brush = brush
        self.z = z
        self.points = 0

    def add(self, path: QPainterPath) -> None:
        self.path.addPath(path)
        self.points += path.elementCount()


def batch_scene(scene: QGraphicsScene) -> QGraphicsScene:
    """Merges runs of identically styled items into single path items.

    The original painting order is preserved. Items which cannot be merged
    safely (patterns, images, points, transformed items) are moved unchanged
    to the new scene.
    """
    merged = QGraphicsScene()
    merged.setSceneRect(scene.sceneRect())
    merged.setBackgroundBrush(scene.backgroundBrush())

    items = list(scene.items(Qt.AscendingOrder))
    current: Optional[_Batch] = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        item = QGraphicsPathItem(current.path)
        item.setPen(current.pen)
        item.setBrush(current.brush)
        item.setZValue(current.z)
        merged.addItem(item)
        current = None

    for item in items:
        if not _mergeable(item):
            flush()
            scene.removeItem(item)
            merged.addItem(item)
            continue
        key = _style_key(item)
        path = item_scene_path(item)
        if path is None:
            flush()
            scene.removeItem(item)
            merged.addItem(item)
            continue
        if (
            current is not None
            and current.key == key
            and current.points + path.elementCount() <= MAX_POINTS_PER_BATCH
        ):
            current.add(path)
        else:
            flush()
            current = _Batch(
                key, item.pen(), _brush_of(item) or QBrush(), item.zValue()
            )
            current.add(path)
    flush()
    return merged
