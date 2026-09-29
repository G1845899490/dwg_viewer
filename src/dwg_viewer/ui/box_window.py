from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QTreeWidgetItem, QVBoxLayout, QWidget

from dwg_viewer.ui.entity_panel import _DataTree
from dwg_viewer.ui.floating import FloatingToolWindow

MAX_ROWS = 5000


class BoxStatsWindow(FloatingToolWindow):
    entity_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__("框选统计", parent)
        self.resize(560, 660)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self.splitter = QSplitter(Qt.Vertical)
        self.stats = _DataTree(self, headers=("项目", "值"))
        self.stats.setColumnWidth(0, 300)
        self.splitter.addWidget(self.stats)

        self.tree = _DataTree(self, headers=("图元", "Handle"))
        self.tree.setColumnWidth(0, 240)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.splitter.addWidget(self.tree)
        self.splitter.setSizes([160, 460])
        layout.addWidget(self.splitter)
        self.set_content(container)

    def set_box(self, left, top, right, bottom, count, entries) -> None:
        width = abs(right - left)
        height = abs(top - bottom)
        diagonal = math.hypot(width, height)

        self.stats.clear()
        root = QTreeWidgetItem(["框选统计", ""])
        root.setFirstColumnSpanned(True)
        self.stats.addTopLevelItem(root)
        for key, value in (
            ("图元数量", str(count)),
            ("[left, top, right, bottom]", f"{left:g}, {top:g}, {right:g}, {bottom:g}"),
            ("宽度 (X)", f"{width:g}"),
            ("高度 (Y)", f"{height:g}"),
            ("对角线长度", f"{diagonal:g}"),
        ):
            QTreeWidgetItem(root, [key, value])
        root.setExpanded(True)
        self.stats.resizeColumnToContents(0)
        self.stats.setColumnWidth(0, self.stats.columnWidth(0) + 60)
        self.stats.resizeColumnToContents(1)

        self.tree.clear()
        if not entries:
            empty = QTreeWidgetItem(["（框内无图元）", ""])
            empty.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(empty)
            return

        all_root = QTreeWidgetItem([f"全部 ({len(entries)})", ""])
        all_root.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(all_root)
        for handle, dxftype in entries[:MAX_ROWS]:
            self._add_entity_item(all_root, handle, dxftype)
        if len(entries) > MAX_ROWS:
            QTreeWidgetItem(all_root, ["...", f"省略 {len(entries) - MAX_ROWS} 个"])

        groups: dict[str, list[str]] = {}
        for handle, dxftype in entries:
            groups.setdefault(dxftype, []).append(handle)
        for dxftype in sorted(groups):
            handles = groups[dxftype]
            node = QTreeWidgetItem([f"{dxftype} ({len(handles)})", ""])
            node.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(node)
            for handle in handles[:MAX_ROWS]:
                self._add_entity_item(node, handle, dxftype)
        all_root.setExpanded(True)

    def _add_entity_item(self, parent, handle, dxftype) -> None:
        item = QTreeWidgetItem([dxftype, str(handle)])
        item.setData(0, Qt.UserRole, str(handle))
        item.setToolTip(0, "点击可定位到该图元")
        parent.addChild(item)

    def _on_item_clicked(self, item, column) -> None:
        handle = item.data(0, Qt.UserRole)
        if handle:
            self.entity_activated.emit(str(handle))

    def clear(self) -> None:
        self.stats.clear()
        self.tree.clear()
