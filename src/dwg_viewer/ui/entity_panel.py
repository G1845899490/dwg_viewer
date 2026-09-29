from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeySequence,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dwg_viewer.core.entity_info import (
    collect_codes,
    entity_full_dump,
    entity_sections,
    group_code_help,
    insert_full_dump,
    insert_internal_entities,
    insert_sections,
)
from dwg_viewer.ui.floating import FloatingToolWindow

MAX_ENTITY_LIST_ROWS = 2000


class _DataTree(QTreeWidget):
    def __init__(self, parent=None, headers=("名称", "值")):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(list(headers))
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setColumnWidth(0, 180)
        self.setTextElideMode(Qt.ElideNone)
        self.setStyleSheet(
            "QTreeView::item:hover { background-color: #eaf6ff; color: #000000; }"
            "QTreeView::item:selected { background-color: #cfe8ff; color: #000000; }"
            "QTreeView::item:selected:!active { background-color: #dceeff; color: #000000; }"
        )

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> None:
        model = self.selectionModel()
        if model is None:
            return
        lines: list[str] = []
        for item in self.selectedItems():
            cells: list[str] = []
            for column in range(self.columnCount()):
                if model.isSelected(self.indexFromItem(item, column)):
                    cells.append(item.text(column))
            if cells:
                lines.append("\t".join(cells))
        if lines:
            QGuiApplication.clipboard().setText("\n".join(lines))


class _FullTextEdit(QPlainTextEdit):
    match_index_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._query = ""
        self._case_sensitive = False
        self._match_positions: list[int] = []
        self._current_index = -1

    def _find_flags(self):
        if self._case_sensitive:
            return QTextDocument.FindCaseSensitively
        return QTextDocument.FindFlags()

    def set_search(self, text: str, case_sensitive: bool = False) -> int:
        self._query = text or ""
        self._case_sensitive = case_sensitive
        self._match_positions = []
        self._current_index = -1
        selections: list[QTextEdit.ExtraSelection] = []
        if self._query:
            document = self.document()
            cursor = QTextCursor(document)
            flags = self._find_flags()
            fmt = QTextCharFormat()
            fmt.setBackground(QColor("#fff176"))
            while True:
                found = document.find(self._query, cursor, flags)
                if found.isNull():
                    break
                self._match_positions.append(found.selectionStart())
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format = fmt
                selections.append(selection)
                cursor = found
        self.setExtraSelections(selections)
        self.match_index_changed.emit(0, len(self._match_positions))
        return len(self._match_positions)

    def _goto(self, index: int) -> None:
        total = len(self._match_positions)
        if total == 0:
            return
        index %= total
        position = self._match_positions[index]
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        cursor.setPosition(position + len(self._query), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()
        self._current_index = index
        self.match_index_changed.emit(index + 1, total)

    def next_match(self) -> None:
        total = len(self._match_positions)
        if total == 0:
            return
        start = self._current_index + 1 if self._current_index >= 0 else 0
        self._goto(start)

    def prev_match(self) -> None:
        total = len(self._match_positions)
        if total == 0:
            return
        start = self._current_index - 1 if self._current_index >= 0 else total - 1
        self._goto(start)


class DataPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Vertical)
        self.tree = _DataTree(self)
        self.splitter.addWidget(self.tree)

        self.tabs = QTabWidget(self)

        # ---- tab 1: all group codes (with search) ----
        full_tab = QWidget()
        full_layout = QVBoxLayout(full_tab)
        full_layout.setContentsMargins(4, 4, 4, 4)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索："))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入要查找的组码或文本，回车跳到下一个")
        self.full_text = _FullTextEdit(self)
        self.full_text.match_index_changed.connect(self._on_match_index)
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.returnPressed.connect(self.full_text.next_match)
        search_row.addWidget(self.search_edit, 1)
        self.case_check = QCheckBox("区分大小写")
        self.case_check.toggled.connect(self._on_search_changed)
        search_row.addWidget(self.case_check)
        self.prev_button = QPushButton("上一个")
        self.prev_button.clicked.connect(self.full_text.prev_match)
        search_row.addWidget(self.prev_button)
        self.next_button = QPushButton("下一个")
        self.next_button.clicked.connect(self.full_text.next_match)
        search_row.addWidget(self.next_button)
        self.match_label = QLabel("")
        search_row.addWidget(self.match_label)
        full_layout.addLayout(search_row)
        full_layout.addWidget(self.full_text)
        self.tabs.addTab(full_tab, "全部组码")

        # ---- tab 2: group code meanings ----
        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)
        help_layout.setContentsMargins(4, 4, 4, 4)
        self.help_tree = _DataTree(self, headers=("组码", "含义"))
        help_layout.addWidget(self.help_tree)
        self.tabs.addTab(help_tab, "组码说明")

        self.splitter.addWidget(self.tabs)
        self.splitter.setSizes([340, 260])
        layout.addWidget(self.splitter)

    # ------------------------------------------------------------- content
    def set_sections(self, sections) -> None:
        self.tree.clear()
        for title, pairs in sections:
            self.add_section(title, pairs)

    def add_section(
        self, title: str, pairs, *, expanded: bool = True, spanned: bool = True
    ) -> QTreeWidgetItem:
        section = QTreeWidgetItem([title, ""])
        if spanned:
            section.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(section)
        for key, value in pairs:
            QTreeWidgetItem(section, [str(key), str(value)])
        section.setExpanded(expanded)
        return section

    def add_entity_list(self, title: str, entities) -> None:
        section = QTreeWidgetItem([f"{title} ({len(entities)})", ""])
        section.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(section)
        for entity in entities[:MAX_ENTITY_LIST_ROWS]:
            QTreeWidgetItem(
                section, [entity.dxftype(), str(entity.dxf.get("handle", ""))]
            )
        if len(entities) > MAX_ENTITY_LIST_ROWS:
            QTreeWidgetItem(
                section,
                ["...", f"省略 {len(entities) - MAX_ENTITY_LIST_ROWS} 个图元"],
            )
        section.setExpanded(False)

    def set_full_text(self, text: str) -> None:
        self.full_text.setPlainText(text)
        self.search_edit.clear()
        self._rebuild_code_help(text)

    def _rebuild_code_help(self, text: str) -> None:
        self.help_tree.clear()
        codes = collect_codes(text)
        if not codes:
            return
        root = QTreeWidgetItem([f"组码说明（共 {len(codes)} 个不同组码）", ""])
        root.setFirstColumnSpanned(True)
        self.help_tree.addTopLevelItem(root)
        for code, meaning in group_code_help(codes):
            QTreeWidgetItem(root, [code, meaning])
        root.setExpanded(True)

    def clear(self) -> None:
        self.tree.clear()
        self.full_text.clear()
        self.help_tree.clear()
        self.search_edit.clear()
        self.match_label.setText("")

    # -------------------------------------------------------------- search
    def _on_search_changed(self) -> None:
        self.full_text.set_search(
            self.search_edit.text(), self.case_check.isChecked()
        )

    def _on_match_index(self, current: int, total: int) -> None:
        if total == 0:
            self.match_label.setText("")
        elif current == 0:
            self.match_label.setText(f"共 {total} 个")
        else:
            self.match_label.setText(f"{current}/{total}")


class EntityDataWindow(FloatingToolWindow):
    def __init__(self, parent=None):
        super().__init__("图元数据", parent)
        self.resize(600, 700)
        self.panel = DataPanel(self)
        self.set_content(self.panel)

    def set_entity(self, entity) -> None:
        self.panel.set_sections(entity_sections(entity))
        self.panel.set_full_text(entity_full_dump(entity))

    def clear(self) -> None:
        self.panel.clear()


class InsertDataWindow(FloatingToolWindow):
    def __init__(self, parent=None):
        super().__init__("Insert数据", parent)
        self.resize(600, 700)
        self.panel = DataPanel(self)
        self.set_content(self.panel)

    def set_insert(self, insert) -> None:
        self.panel.set_sections(insert_sections(insert))
        self.panel.add_entity_list("内部图元", insert_internal_entities(insert))
        self.panel.set_full_text(insert_full_dump(insert))

    def clear(self) -> None:
        self.panel.clear()


# Backwards compatible alias
EntityPanelWindow = EntityDataWindow
