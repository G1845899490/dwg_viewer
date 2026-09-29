from __future__ import annotations

import time

from PySide6.QtGui import QBrush, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
)

from ezdxf.render import hatching
from ezdxf.addons.drawing.config import ProxyGraphicPolicy
from ezdxf.addons.drawing.frontend import Frontend, _draw_viewports
from ezdxf.addons.drawing.gfxproxy import DXFGraphicProxy
from ezdxf.addons.drawing.pyqt import PyQtBackend, _matrix_to_qtransform
from ezdxf.entities import DXFGraphic, Insert, Viewport

DEFAULT_MAX_HATCH_SEGMENTS = 120000

_MISSING = object()


class RenderCancelled(Exception):
    pass


class RenderAborted(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LimitedFrontend(Frontend):
    """Frontend with a global pattern hatch budget and a per-entity yield hook.

    - A pattern HATCH with a very small pattern scale (or a block referenced
      many times) can generate millions of tiny line segments; the global
      budget keeps rendering bounded.
    - ``yield_hook`` is called for every entity, including entities nested in
      block references, so the UI can stay responsive and cancel a long
      render. The hook may raise :class:`RenderCancelled` or
      :class:`RenderAborted`.
    """

    max_hatch_segments = DEFAULT_MAX_HATCH_SEGMENTS
    truncated_hatches: list[str]
    yield_hook = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.truncated_hatches = []
        self._hatch_segments_used = 0
        self.yield_hook = None
        self.ignore_types: set[str] = set()
        self.nested_entity_limit = 0
        self._nested_count = 0
        self.expand_truncated = False
        self.use_block_cache = True
        self._block_cache: dict = {}
        self._building_blocks: set[str] = set()

    # ------------------------------------------------------- block caching
    def draw_composite_entity(self, entity, properties) -> None:
        """Render block references reusing a per-block geometry cache."""
        if not self.use_block_cache or not isinstance(entity, Insert):
            return super().draw_composite_entity(entity, properties)
        name = str(entity.dxf.get("name", ""))
        if not name:
            return super().draw_composite_entity(entity, properties)
        if name in self._building_blocks:
            # Self- or mutual-recursive block reference: stop here to avoid
            # infinite expansion (stack overflow).
            return

        cache = self._block_cache.get(name, _MISSING)
        if cache is _MISSING:
            self._building_blocks.add(name)
            try:
                cache = self._build_block_cache(entity)
            except Exception:
                cache = None
            finally:
                self._building_blocks.discard(name)
            self._block_cache[name] = cache

        if not cache:
            return super().draw_composite_entity(entity, properties)

        backend = self.pipeline.backend
        instances = entity.multi_insert() if entity.mcount > 1 else (entity,)
        try:
            for instance in instances:
                try:
                    matrix = instance.matrix44()
                except Exception:
                    super().draw_composite_entity(instance, properties)
                    continue
                transform = _matrix_to_qtransform(matrix)
                for path, pen, brush, z_value in cache:
                    item = QGraphicsPathItem(path)
                    item.setPen(pen)
                    item.setBrush(brush)
                    item.setZValue(z_value)
                    item.setTransform(transform)
                    backend._add_item(item, "")
                # per-instance attributes are not part of the block definition
                self.draw_entities(instance.attribs)
        except Exception:
            # never let a caching problem break rendering
            return super().draw_composite_entity(entity, properties)

    def _build_block_cache(self, insert: Insert):
        doc = getattr(insert, "doc", None)
        block = doc.blocks.get(insert.dxf.get("name", "")) if doc else None
        if block is None:
            return None

        scene = QGraphicsScene()
        backend = PyQtBackend(scene)
        sub = LimitedFrontend(
            ctx=self.ctx,
            out=backend,
            config=self.config,
            bbox_cache=getattr(self, "bbox_cache", None),
        )
        sub.use_block_cache = self.use_block_cache
        sub._block_cache = self._block_cache
        sub._building_blocks = self._building_blocks
        sub.ignore_types = set(self.ignore_types)
        sub.nested_entity_limit = self.nested_entity_limit
        sub.max_hatch_segments = self.max_hatch_segments
        sub.yield_hook = self.yield_hook
        try:
            # ATTDEF entities are placeholders; the real per-instance values
            # are drawn from the INSERT's ATTRIB entities. ``virtual_entities``
            # excludes them too, so the cache must as well.
            entities = [e for e in block if e.dxftype() != "ATTDEF"]
            sub.draw_entities(entities)
        finally:
            backend.finalize()

        primitives = []
        for item in scene.items():
            if isinstance(item, QGraphicsPixmapItem):
                return None  # raster images cannot be cached as vector paths
            if isinstance(item, QGraphicsPathItem):
                path = item.path()
                pen = item.pen()
                brush = item.brush()
            elif isinstance(item, QGraphicsLineItem):
                line = item.line()
                path = QPainterPath()
                path.moveTo(line.p1())
                path.lineTo(line.p2())
                pen = item.pen()
                brush = QBrush()
            elif isinstance(item, QGraphicsPolygonItem):
                path = QPainterPath()
                path.addPolygon(item.polygon())
                pen = item.pen()
                brush = item.brush()
            else:
                return None  # unsupported item (e.g. cosmetic POINT)
            # bake nested transforms into the block-local path
            path = item.transform().map(path)
            primitives.append((path, pen, brush, item.zValue()))
        return self._merge_primitives(primitives)

    @staticmethod
    def _pen_key(pen: QPen, brush: QBrush, z_value: float):
        return (
            pen.color().rgba(),
            round(pen.widthF(), 3),
            pen.style(),
            pen.capStyle(),
            pen.joinStyle(),
            bool(pen.isCosmetic()),
            brush.color().rgba(),
            brush.style(),
            round(z_value, 3),
        )

    def _merge_primitives(self, primitives):
        merged = []
        current = None
        current_key = None
        for path, pen, brush, z_value in primitives:
            key = self._pen_key(pen, brush, z_value)
            if current is not None and key == current_key:
                current[0].addPath(path)
            else:
                current = [QPainterPath(path), pen, brush, z_value]
                current_key = key
                merged.append(current)
        return [tuple(entry) for entry in merged]

    def draw_entities(self, entities, *, filter_func=None) -> None:
        if filter_func is not None:
            entities = filter(filter_func, entities)
        viewports: list[Viewport] = []
        hook = self.yield_hook
        for entity in entities:
            if hook is not None:
                hook()
            try:
                dxftype = entity.dxftype().upper()
            except Exception:
                dxftype = ""
            if self.ignore_types and dxftype in self.ignore_types:
                self.skip_entity(entity, "ignored by user setting")
                continue
            if (
                self.nested_entity_limit > 0
                and self._nested_count >= self.nested_entity_limit
            ):
                self.expand_truncated = True
                continue
            self._nested_count += 1
            if isinstance(entity, Viewport):
                viewports.append(entity)
                continue
            if not isinstance(entity, DXFGraphic):
                if self.config.proxy_graphic_policy != ProxyGraphicPolicy.IGNORE:
                    entity = DXFGraphicProxy(entity)
                else:
                    self.skip_entity(entity, "Cannot parse DXF entity")
                    continue
            properties = self.ctx.resolve_all(entity)
            self.exec_property_override(entity, properties)
            if properties.is_visible:
                self.draw_entity(entity, properties)
            else:
                self.skip_entity(entity, "invisible")
        _draw_viewports(self, viewports)

    def draw_hatch_pattern(self, polygon, paths, properties) -> None:
        if polygon.pattern is None or len(polygon.pattern.lines) == 0:
            return
        handle = ""
        try:
            handle = str(polygon.dxf.get("handle", "") or "")
        except Exception:
            pass
        if not handle:
            try:
                handle = str(self.pipeline.current_entity_handle() or "")
            except Exception:
                handle = ""

        remaining = self.max_hatch_segments - self._hatch_segments_used
        if remaining <= 0:
            self.truncated_hatches.append(handle or "?")
            return

        ocs = polygon.ocs()
        elevation = polygon.dxf.elevation.z
        properties.linetype_pattern = tuple()
        lines: list = []

        t0 = time.perf_counter()
        max_time = self.config.hatching_timeout

        def timeout() -> bool:
            return (time.perf_counter() - t0) > max_time

        limit = remaining
        truncated = False
        for baseline in hatching.pattern_baselines(
            polygon,
            min_hatch_line_distance=self.config.min_hatch_line_distance,
            jiggle_origin=True,
        ):
            for line in hatching.hatch_paths(baseline, paths, timeout):
                line_pattern = baseline.pattern_renderer(line.distance)
                for start, end in line_pattern.render(line.start, line.end):
                    if ocs.transform:
                        start, end = (
                            ocs.to_wcs((start.x, start.y, elevation)),
                            ocs.to_wcs((end.x, end.y, elevation)),
                        )
                    lines.append((start, end))
                    if len(lines) >= limit:
                        truncated = True
                        break
                if truncated:
                    break
            if truncated:
                break
        self._hatch_segments_used += len(lines)
        if truncated:
            self.truncated_hatches.append(handle or "?")
        self.pipeline.draw_solid_lines(lines, properties)
