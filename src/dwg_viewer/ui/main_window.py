from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dwg_viewer.config import (
    add_recent_file,
    clear_recent_files,
    get_last_dir,
    get_oda_path,
    get_recent_files,
    get_render_entity_limit,
    get_on_top,
    get_window_geometry,
    log_dir,
    set_last_dir,
    set_last_session_files,
    set_on_top,
    set_window_geometry,
)
from dwg_viewer.core.coordinate import (
    ParseError,
    parse_bounds,
    parse_id,
    parse_point,
    parse_points,
)
from dwg_viewer.core.document import DocumentLoader
from dwg_viewer.ui.document_view import DocumentView
from dwg_viewer.ui.box_window import BoxStatsWindow
from dwg_viewer.ui.entity_panel import EntityDataWindow, InsertDataWindow
from dwg_viewer.ui.floating import FloatingToolWindow
from dwg_viewer.ui.settings_dialog import SettingsDialog

FILE_FILTER = "CAD 图纸 (*.dwg *.DWG *.dxf *.DXF)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DWG Viewer")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self._threads: set[QThread] = set()
        self._loaders: set[DocumentLoader] = set()
        self._pending = 0
        self._loading_names: list[str] = []
        self._stage_text = ""
        self._load_queue: list[str] = []
        self._active_loads = 0
        self._max_concurrent_loads = 1
        self._render_queue: list[DocumentView] = []
        self._rendering = False
        self._rendering_view: DocumentView | None = None
        self._render_dialog = None
        self.connect_points_enabled = False

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        tab_bar = self.tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._tab_context_menu)
        self.setCentralWidget(self.tabs)

        self._build_actions()
        self._build_toolbar()
        self._build_locate_window()
        self._build_entity_window()
        self._build_box_window()

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.coord_label = QLabel("坐标: -")
        self.coord_label.setAlignment(Qt.AlignCenter)
        self.coord_label.setMinimumWidth(220)
        self.status.addPermanentWidget(self.coord_label, 1)

        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        self.status.addPermanentWidget(self.progress_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(180)
        self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)

        self.status.showMessage(f"ODA File Converter: {get_oda_path() or '未配置'}")

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        geometry = get_window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)

        self.on_top_action.blockSignals(True)
        self.on_top_action.setChecked(get_on_top())
        self.on_top_action.blockSignals(False)
        if get_on_top():
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

    # ------------------------------------------------------------------ setup
    def _build_actions(self) -> None:
        self.open_action = QAction("打开(&O)...", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.triggered.connect(self._open_dialog)

        self.close_action = QAction("关闭当前标签(&W)", self)
        self.close_action.setShortcut(QKeySequence.Close)
        self.close_action.triggered.connect(
            lambda: self._close_tab(self.tabs.currentIndex())
        )

        self.quit_action = QAction("退出(&Q)", self)
        self.quit_action.setShortcut(QKeySequence.Quit)
        self.quit_action.triggered.connect(self.close)

        self.fit_action = QAction("显示全图(&F)", self)
        self.fit_action.setShortcut("Home")
        self.fit_action.triggered.connect(self._fit_current)

        self.render_action = QAction("渲染当前标签(&R)", self)
        self.render_action.triggered.connect(self._render_current)

        self.stop_action = QAction("停止打开(&T)", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self._stop_opening)

        self.entity_action = QAction("图元数据(&D)", self)
        self.entity_action.setCheckable(True)
        self.entity_action.toggled.connect(self._toggle_entity_panel)

        self.insert_action = QAction("Insert数据(&I)", self)
        self.insert_action.setCheckable(True)
        self.insert_action.setEnabled(False)
        self.insert_action.toggled.connect(self._toggle_insert_panel)

        self.locate_action = QAction("定位(&L)", self)
        self.locate_action.setCheckable(True)
        self.locate_action.toggled.connect(self._toggle_locate_window)

        self.on_top_action = QAction("置顶(&P)", self)
        self.on_top_action.setCheckable(True)
        self.on_top_action.toggled.connect(self._toggle_on_top)

        self.settings_action = QAction("设置(&S)...", self)
        self.settings_action.triggered.connect(self._open_settings)

        self.log_action = QAction("打开日志文件夹(&G)", self)
        self.log_action.triggered.connect(self._open_log_folder)

        menu = self.menuBar()
        file_menu = menu.addMenu("文件(&F)")
        file_menu.addAction(self.open_action)
        self.recent_menu = QMenu("打开历史(&H)", self)
        file_menu.addMenu(self.recent_menu)
        file_menu.addAction(self.close_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        self._rebuild_recent_menu()

        view_menu = menu.addMenu("视图(&V)")
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.render_action)
        view_menu.addAction(self.locate_action)
        view_menu.addAction(self.entity_action)
        view_menu.addAction(self.insert_action)
        view_menu.addAction(self.on_top_action)

        menu.addAction(self.settings_action)
        menu.addAction(self.log_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.toolbar = toolbar
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.stop_action)
        self.history_button = QToolButton()
        self.history_button.setText("打开历史")
        self.history_button.setMenu(self.recent_menu)
        self.history_button.setPopupMode(QToolButton.InstantPopup)
        toolbar.addWidget(self.history_button)
        toolbar.addAction(self.fit_action)
        toolbar.addSeparator()
        toolbar.addAction(self.locate_action)
        toolbar.addAction(self.entity_action)
        toolbar.addAction(self.insert_action)
        toolbar.addAction(self.on_top_action)

    def _build_locate_window(self) -> None:
        self.locate_window = FloatingToolWindow("定位", self)
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()

        self.point_edit = QLineEdit()
        self.point_edit.setPlaceholderText("例如: 100, 200")
        self.point_edit.returnPressed.connect(self._locate_point)
        form.addRow("点 (x, y):", self._with_button(self.point_edit, self._locate_point))

        self.bounds_edit = QLineEdit()
        self.bounds_edit.setPlaceholderText("例如: 0, 100, 200, 0   或   (0,0)(200,100)")
        self.bounds_edit.returnPressed.connect(self._locate_bounds)
        form.addRow(
            "范围:", self._with_button(self.bounds_edit, self._locate_bounds)
        )

        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("图元 Handle，例如: 2F")
        self.id_edit.returnPressed.connect(self._locate_id)
        form.addRow("ID (Handle):", self._with_button(self.id_edit, self._locate_id))

        self.points_edit = QPlainTextEdit()
        self.points_edit.setPlaceholderText("x1, y1, x2, y2, x3, y3 ...（可换行、可无空格）")
        self.points_edit.setFixedHeight(70)
        points_wrapper = QWidget()
        points_row = QHBoxLayout(points_wrapper)
        points_row.setContentsMargins(0, 0, 0, 0)
        points_row.addWidget(self.points_edit, 1)
        points_buttons = QVBoxLayout()
        points_buttons.setSpacing(3)
        locate_points_button = QPushButton("定位")
        locate_points_button.clicked.connect(self._locate_point_list)
        points_buttons.addWidget(locate_points_button)
        self.connect_button = QPushButton("连线")
        self.connect_button.setCheckable(True)
        self.connect_button.setToolTip("把定位的点按顺序用直线连接")
        self.connect_button.toggled.connect(self._toggle_connect_points)
        points_buttons.addWidget(self.connect_button)
        points_row.addLayout(points_buttons)
        form.addRow("点列表:", points_wrapper)

        outer.addLayout(form)
        self.locate_status = QLabel("")
        self.locate_status.setStyleSheet("color: #205080;")
        outer.addWidget(self.locate_status)
        outer.addStretch(0)

        self.locate_window.set_content(container)
        self.locate_window.resize(460, 300)
        self.locate_window.closed.connect(self._on_locate_window_closed)

    def _with_button(self, line_edit: QLineEdit, callback) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit)
        button = QPushButton("定位")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return wrapper

    def _build_entity_window(self) -> None:
        self.entity_window = EntityDataWindow(self)
        self.entity_panel = self.entity_window.panel
        self.entity_window.closed.connect(self._on_entity_window_closed)
        self.entity_window.hide()

        self.insert_window = InsertDataWindow(self)
        self.insert_window.closed.connect(self._on_insert_window_closed)
        self.insert_window.hide()

    def _build_box_window(self) -> None:
        self.box_window = BoxStatsWindow(self)
        self.box_window.entity_activated.connect(self._on_box_entity_activated)
        self.box_window.hide()

    def _on_box_selected(self, left, top, right, bottom, count, handles) -> None:
        text = f"{left:g}, {top:g}, {right:g}, {bottom:g}"
        QGuiApplication.clipboard().setText(text)
        entries = []
        view = self._current_view()
        if view is not None and view.doc is not None:
            for handle in handles:
                entity = view.doc.entitydb.get(handle)
                if entity is not None:
                    entries.append((str(handle), entity.dxftype()))
        self.box_window.set_box(left, top, right, bottom, count, entries)
        self._place_floating(self.box_window, prefer="right")
        self.box_window.show()
        self.box_window.raise_()
        self.box_window.activateWindow()
        self.status.showMessage(
            f"框选范围内约 {count} 个图元，坐标已复制到剪贴板：{text}", 10000
        )

    def _on_box_entity_activated(self, handle: str) -> None:
        view = self._current_view()
        if view is None:
            return
        ok, message = view.select_by_handle(handle)
        self.status.showMessage(message, 5000)

    def _on_box_cleared(self) -> None:
        self.box_window.hide()

    # ------------------------------------------------------------------- tabs
    def _current_view(self) -> DocumentView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, DocumentView) else None

    def _add_document_view(
        self, view: DocumentView, path: str, *, render: bool = True
    ) -> None:
        index = self.tabs.addTab(view, Path(path).name)
        self.tabs.setTabToolTip(index, path)
        if self.tabs.count() == 1:
            self.tabs.setCurrentIndex(index)
        if render:
            self._render_queue.append(view)
            self._pump_render()

    def _close_tab(self, index: int) -> None:
        if index < 0:
            return
        widget = self.tabs.widget(index)
        if widget is self._rendering_view:
            self.status.showMessage("该标签正在渲染，请先取消或等待完成。", 5000)
            return
        if widget in self._render_queue:
            self._render_queue.remove(widget)
        self.tabs.removeTab(index)
        widget.deleteLater()

    def _tab_context_menu(self, pos) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        menu.addAction("关闭本标签页", lambda: self._close_tab(index))
        menu.addAction("关闭所有标签页", self._close_all_tabs)
        menu.addAction("关闭右边的所有标签页", lambda: self._close_tabs_right(index))
        menu.addAction("关闭左边的所有标签页", lambda: self._close_tabs_left(index))
        menu.exec(tab_bar.mapToGlobal(pos))

    def _close_all_tabs(self) -> None:
        for index in range(self.tabs.count() - 1, -1, -1):
            self._close_tab(index)

    def _close_tabs_right(self, index: int) -> None:
        for i in range(self.tabs.count() - 1, index, -1):
            self._close_tab(i)

    def _close_tabs_left(self, index: int) -> None:
        for i in range(index - 1, -1, -1):
            self._close_tab(i)

    def _on_tab_changed(self, index: int) -> None:
        view = self._current_view()
        self.coord_label.setText("坐标: -")
        if view and view.path:
            self.setWindowTitle(f"{Path(view.path).name} - DWG Viewer")
        else:
            self.setWindowTitle("DWG Viewer")
        if view is not None:
            view.set_connect_points(self.connect_points_enabled)
        self._pump_render()
        self._sync_entity_window()

    def _pump_render(self) -> None:
        if self._rendering or not self._render_queue:
            return
        self._rendering = True
        view = self._render_queue.pop(0)
        self._rendering_view = view
        self._update_stop_action()
        QTimer.singleShot(0, lambda v=view: self._render_queued(v))

    def _render_with_progress(self, view: DocumentView) -> bool:
        name = Path(view.path).name if view.path else ""
        total = view.document_entity_count()
        dialog = QProgressDialog(
            f"{name}\n正在渲染，请稍候...", "取消", 0, max(total, 1), self
        )
        dialog.setWindowTitle("渲染")
        # Non-modal: the user may keep working (switch tabs, pan other
        # drawings) while this drawing is being rendered.
        dialog.setWindowModality(Qt.NonModal)
        dialog.setWindowFlag(Qt.Tool, True)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        self._rendering_view = view
        self._render_dialog = dialog
        self._stage_text = f"{name} · 正在渲染 ..."
        self._update_progress()
        QApplication.processEvents()

        def on_progress(current: int, maximum: int) -> None:
            dialog.setMaximum(max(maximum, 1))
            dialog.setValue(current)

        try:
            return view.ensure_rendered(
                should_cancel=dialog.wasCanceled, on_progress=on_progress
            )
        finally:
            self._rendering_view = None
            self._render_dialog = None
            dialog.close()
            dialog.deleteLater()

    def _render_queued(self, view: DocumentView) -> None:
        name = Path(view.path).name if view.path else ""
        try:
            if not view.is_rendered:
                rendered = self._render_with_progress(view)
            else:
                rendered = True
        except Exception as exc:  # noqa: BLE001 - never let a render error crash the app
            rendered = False
            self.status.showMessage(f"{name} · 渲染出错：{exc}", 10000)
        finally:
            self._rendering = False
            if view.is_rendered:
                self.status.showMessage(f"{name} · 渲染完成。", 3000)
            elif rendered is False:
                reason = view.render_abort_reason or "已取消"
                self.status.showMessage(f"{name} · {reason}。", 10000)
            self._stage_text = ""
            self._update_progress()
            self._update_stop_action()
            self._sync_entity_window()
            self._pump_render()

    def _render_current(self) -> None:
        view = self._current_view()
        if view is None or view.is_rendered:
            return
        if self._rendering:
            self.status.showMessage("已有图纸正在渲染，请稍候。", 5000)
            return
        self._render_with_progress(view)
        if view.is_rendered:
            view.view.fit_to_scene()
            self.status.showMessage("渲染完成。", 3000)
        else:
            reason = view.render_abort_reason or "已取消"
            self.status.showMessage(f"{reason}。", 8000)
        self._stage_text = ""
        self._update_progress()

    def _fit_current(self) -> None:
        view = self._current_view()
        if view is None:
            return
        if not view.is_rendered:
            if self._rendering:
                self.status.showMessage("已有图纸正在渲染，请稍候。", 5000)
                return
            self._render_with_progress(view)
        if view.is_rendered:
            view.view.fit_to_scene(user=True)

    # ----------------------------------------------------------------- opening
    def _open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "打开图纸", get_last_dir(), FILE_FILTER
        )
        if paths:
            set_last_dir(paths[0])
            self.open_files(paths)

    def open_startup(self) -> None:
        if self.tabs.count() == 0:
            self._open_dialog()

    def open_files(self, paths) -> None:
        for path in paths:
            if Path(path).is_file():
                set_last_dir(path)
                add_recent_file(path)
                self._load_path(str(path))
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = [p for p in get_recent_files() if Path(p).is_file()]
        if not files:
            empty = self.recent_menu.addAction("（暂无历史记录）")
            empty.setEnabled(False)
            return
        for path in files:
            action = self.recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(
                lambda checked=False, p=path: self.open_files([p])
            )
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("清空历史记录", self._clear_recent)

    def _clear_recent(self) -> None:
        clear_recent_files()
        self._rebuild_recent_menu()

    def _load_path(self, path: str) -> None:
        self._pending += 1
        self._loading_names.append(Path(path).name)
        self._load_queue.append(path)
        self._update_progress()
        self._update_stop_action()
        self._pump_queue()

    def _pump_queue(self) -> None:
        while self._load_queue and self._active_loads < self._max_concurrent_loads:
            self._start_loader(self._load_queue.pop(0))

    def _start_loader(self, path: str) -> None:
        self._active_loads += 1
        name = Path(path).name
        self._stage_text = f"{name} · 正在打开 ..."
        self._update_progress()
        thread = QThread(self)
        loader = DocumentLoader(path)
        loader.moveToThread(thread)
        thread.started.connect(loader.run)
        loader.progress.connect(lambda msg, n=name: self._on_loader_progress(n, msg))
        loader.loaded.connect(self._on_loaded)
        loader.failed.connect(self._on_load_failed)
        loader.cancelled.connect(self._on_load_cancelled)
        loader.loaded.connect(thread.quit)
        loader.failed.connect(thread.quit)
        loader.cancelled.connect(thread.quit)
        thread.finished.connect(lambda: self._cleanup_loader(thread, loader))
        self._threads.add(thread)
        self._loaders.add(loader)
        thread.start()

    def _on_loader_progress(self, name: str, message: str) -> None:
        self._stage_text = f"{name} · {message}"
        self._update_progress()

    def _update_progress(self) -> None:
        if self._stage_text:
            self.progress_label.setText(self._stage_text)
            self.progress_label.setVisible(True)
            self.progress.setVisible(True)
            return
        if self._loading_names:
            name = self._loading_names[0]
            extra = (
                f"（还有 {len(self._loading_names) - 1} 个）"
                if len(self._loading_names) > 1
                else ""
            )
            self.progress_label.setText(f"正在打开 {name}{extra}")
            self.progress_label.setVisible(True)
            self.progress.setVisible(True)
        else:
            self.progress_label.setText("")
            self.progress_label.setVisible(False)
            self.progress.setVisible(False)

    def _cleanup_loader(self, thread: QThread, loader: DocumentLoader) -> None:
        self._threads.discard(thread)
        self._loaders.discard(loader)
        loader.deleteLater()
        thread.deleteLater()
        self._active_loads = max(0, self._active_loads - 1)
        self._pending = max(0, self._pending - 1)
        if Path(loader.path).name in self._loading_names:
            self._loading_names.remove(Path(loader.path).name)
        self._update_progress()
        self._update_stop_action()
        self._pump_queue()

    def _on_loaded(self, doc, errors, path: str, count: int) -> None:
        view = DocumentView()
        view.selection_changed.connect(self._on_selection_changed)
        view.status_message.connect(self.status.showMessage)
        view.coordinate_changed.connect(self._update_coord)
        view.box_selected.connect(self._on_box_selected)
        view.box_cleared.connect(self._on_box_cleared)
        view.set_document(doc, path)
        view.set_entity_count(count)

        limit = get_render_entity_limit()
        render = True
        if limit > 0 and count > limit:
            reply = QMessageBox.question(
                self,
                "图元数量过大",
                f"“{Path(path).name}” 包含约 {count} 个图元。\n"
                "渲染可能需要很长时间甚至卡死。\n\n是否现在渲染？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            render = reply == QMessageBox.Yes
            if not render:
                view.set_skipped(
                    f"图元过多（约 {count} 个），已跳过渲染。\n"
                    "可执行菜单「视图 → 渲染当前标签」再渲染。"
                )

        self._add_document_view(view, path, render=render)
        if not render:
            self.status.showMessage(
                f"{Path(path).name} · 已打开（未渲染，图元过多）。", 10000
            )

    def _on_load_failed(self, path: str, message: str) -> None:
        self.status.showMessage(f"打开失败: {Path(path).name}", 8000)
        QMessageBox.critical(
            self, "打开失败", f"无法打开 {path}\n\n{message}"
        )

    def _on_load_cancelled(self, path: str) -> None:
        self.status.showMessage(f"{Path(path).name} · 已取消打开。", 5000)

    def _stop_opening(self) -> None:
        stopped = 0
        if self._load_queue:
            stopped += len(self._load_queue)
            self._load_queue.clear()
        for loader in list(self._loaders):
            loader.cancel()
            stopped += 1
        if self._render_queue:
            stopped += len(self._render_queue)
            self._render_queue.clear()
        if self._render_dialog is not None:
            self._render_dialog.cancel()
            stopped += 1
        self._loading_names.clear()
        # only still-running loaders remain pending; they will decrement on cleanup
        self._pending = len(self._loaders)
        self._stage_text = ""
        self._update_progress()
        self._update_stop_action()
        self.status.showMessage(f"已停止打开任务（{stopped} 项）。", 6000)

    def _update_stop_action(self) -> None:
        busy = bool(
            self._load_queue
            or self._loaders
            or self._render_queue
            or self._rendering
        )
        self.stop_action.setEnabled(busy)

    def _update_coord(self, x: float, y: float) -> None:
        self.coord_label.setText(f"坐标: {x:.4f}, {y:.4f}")

    # ------------------------------------------------------------------ locate
    def _locate_point(self) -> None:
        view = self._current_view()
        if view is None:
            self.status.showMessage("没有打开的图纸。", 5000)
            return
        text = self.point_edit.text()
        try:
            x, y = parse_point(text)
            view.locate_point(x, y)
            message = f"已定位到点 ({x:g}, {y:g})"
            self.status.showMessage(message, 5000)
            self.locate_status.setText(message)
            return
        except ParseError:
            pass
        # perhaps a point list was pasted into the single point box
        try:
            points = parse_points(text)
        except ParseError as exc:
            self.status.showMessage(str(exc), 5000)
            self.locate_status.setText(str(exc))
            return
        view.locate_points(points)
        message = f"已定位 {len(points)} 个点。"
        self.status.showMessage(message, 5000)
        self.locate_status.setText(message)

    def _locate_point_list(self) -> None:
        view = self._current_view()
        if view is None:
            self.status.showMessage("没有打开的图纸。", 5000)
            return
        text = self.points_edit.toPlainText()
        try:
            points = parse_points(text)
        except ParseError as exc:
            self.status.showMessage(f"点列表解析失败：{exc}", 8000)
            return
        except Exception as exc:  # noqa: BLE001
            self.status.showMessage(f"点列表解析异常：{exc}", 8000)
            return
        try:
            view.locate_points(points)
        except Exception as exc:  # noqa: BLE001
            self.status.showMessage(f"定位异常：{exc}", 8000)
            return
        message = f"已定位 {len(points)} 个点。"
        self.status.showMessage(message, 8000)
        self.locate_status.setText(message)

    def _toggle_connect_points(self, checked: bool) -> None:
        self.connect_points_enabled = checked
        view = self._current_view()
        if view is not None:
            view.set_connect_points(checked)

    def _locate_bounds(self) -> None:
        view = self._current_view()
        if view is None:
            self.status.showMessage("没有打开的图纸。", 5000)
            return
        try:
            left, top, right, bottom = parse_bounds(self.bounds_edit.text())
        except ParseError as exc:
            self.status.showMessage(str(exc), 5000)
            return
        view.locate_bounds(left, top, right, bottom)
        self.status.showMessage(
            f"已定位到范围 ({left:g}, {top:g}, {right:g}, {bottom:g})", 5000
        )

    def _locate_id(self) -> None:
        view = self._current_view()
        if view is None:
            self.status.showMessage("没有打开的图纸。", 5000)
            return
        raw = self.id_edit.text().strip()
        if not raw:
            self.status.showMessage("请输入 Handle。", 5000)
            return
        tokens = parse_id(raw)
        if not tokens:
            self.status.showMessage("未能从输入中识别出 Handle。", 5000)
            return
        ok = False
        message = ""
        for token in tokens:
            ok, message = view.select_by_handle(token)
            if ok:
                break
        if ok:
            self.status.showMessage(message, 5000)
            self._on_selection_changed(view.selected_entity)
        else:
            tried = ", ".join(tokens[:5])
            self.status.showMessage(
                f"未找到匹配的图元（已尝试：{tried}）", 6000
            )

    # ---------------------------------------------------------------- selection
    def _on_selection_changed(self, entity) -> None:
        if entity is None:
            self.status.showMessage("已取消选择。", 3000)
            self._hide_entity_window()
        else:
            self.status.showMessage(f"已选中 {entity.dxftype()}", 5000)
            self._show_entity_window()
        self._update_insert_action(entity)

    def _sync_entity_window(self) -> None:
        view = self._current_view()
        entity = view.selected_entity if view is not None else None
        if entity is not None:
            self._show_entity_window()
        else:
            self._hide_entity_window()
        self._update_insert_action(entity)

    def _is_insert(self, entity) -> bool:
        return entity is not None and entity.dxftype() == "INSERT"

    def _update_insert_action(self, entity) -> None:
        is_insert = self._is_insert(entity)
        self.insert_action.setEnabled(is_insert)
        if not is_insert:
            self.insert_action.blockSignals(True)
            self.insert_action.setChecked(False)
            self.insert_action.blockSignals(False)
            self.insert_window.hide()

    def _refresh_entity_panel(self) -> None:
        if not self.entity_window.isVisible():
            return
        view = self._current_view()
        entity = view.selected_entity if view else None
        if entity is None:
            self.entity_window.clear()
        else:
            self.entity_window.set_entity(entity)

    def _refresh_insert_panel(self) -> None:
        view = self._current_view()
        entity = view.selected_entity if view else None
        if self._is_insert(entity):
            self.insert_window.set_insert(entity)

    def _set_entity_action(self, checked: bool) -> None:
        self.entity_action.blockSignals(True)
        self.entity_action.setChecked(checked)
        self.entity_action.blockSignals(False)

    def _show_entity_window(self) -> None:
        if not self.entity_window.isVisible():
            self._place_floating(self.entity_window, prefer="right")
            self.entity_window.show()
            self.entity_window.raise_()
            self.entity_window.activateWindow()
        self._set_entity_action(True)
        self._refresh_entity_panel()

    def _hide_entity_window(self) -> None:
        self.entity_window.hide()
        self._set_entity_action(False)

    def _toggle_entity_panel(self, checked: bool) -> None:
        if checked:
            self._show_entity_window()
        else:
            self._hide_entity_window()

    def _toggle_insert_panel(self, checked: bool) -> None:
        if checked:
            self._place_floating(self.insert_window, prefer="right")
            self.insert_window.show()
            self.insert_window.raise_()
            self.insert_window.activateWindow()
            self._refresh_insert_panel()
        else:
            self.insert_window.hide()

    def _place_floating(self, window, prefer: str = "right") -> None:
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = window.width()
        height = window.height()
        frame = self.frameGeometry()
        if prefer == "left":
            x = frame.left() - width - 8
            if x < available.left():
                x = available.left() + 8
        else:
            x = frame.right() + 8
            if x + width > available.right():
                x = max(available.left(), available.right() - width - 8)
        top_offset = 24
        try:
            top_offset += self.menuBar().height() + self.toolbar.height() + 60
        except Exception:
            top_offset = 160
        y = min(
            max(available.top() + 8, frame.top() + top_offset),
            max(available.top() + 8, available.bottom() - height - 8),
        )
        window.move(x, y)

    def _on_entity_window_closed(self) -> None:
        self._set_entity_action(False)

    def _on_insert_window_closed(self) -> None:
        self.insert_action.blockSignals(True)
        self.insert_action.setChecked(False)
        self.insert_action.blockSignals(False)

    def _toggle_locate_window(self, checked: bool) -> None:
        if checked:
            self._place_floating(self.locate_window, prefer="left")
            self.locate_window.show()
            self.locate_window.raise_()
            self.locate_window.activateWindow()
        else:
            self.locate_window.hide()

    def _on_locate_window_closed(self) -> None:
        self.locate_action.blockSignals(True)
        self.locate_action.setChecked(False)
        self.locate_action.blockSignals(False)

    # ----------------------------------------------------------------- settings
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.status.showMessage(f"ODA File Converter: {get_oda_path()}", 5000)
            self._rerender_open_tabs()

    def _rerender_open_tabs(self) -> None:
        targets = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, DocumentView) and widget.is_rendered:
                targets.append(widget)
        if not targets:
            return
        self._stage_text = "正在按新的显示设置重新渲染 ..."
        self._update_progress()
        for widget in targets:
            widget.apply_render_settings()
            widget._rendered = False
            try:
                self._render_with_progress(widget)
            except Exception as exc:  # noqa: BLE001
                self.status.showMessage(f"重新渲染出错：{exc}", 8000)
        self._stage_text = ""
        self._update_progress()
        self.status.showMessage(
            f"已按新的显示设置重新渲染 {len(targets)} 个标签。", 5000
        )

    def _toggle_on_top(self, checked: bool) -> None:
        set_on_top(checked)
        maximized = self.isMaximized()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()
        if maximized:
            self.showMaximized()
        else:
            self.raise_()
        self.status.showMessage("已置顶。" if checked else "已取消置顶。", 3000)

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir())))

    def closeEvent(self, event) -> None:
        paths = []
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, DocumentView) and widget.path:
                paths.append(widget.path)
        set_last_session_files(paths)
        set_window_geometry(self.saveGeometry())
        super().closeEvent(event)

    # -------------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event) -> None:
        if self._has_cad_urls(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if self._has_cad_urls(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in (".dwg", ".dxf")
        ]
        if paths:
            self.open_files(paths)
            event.acceptProposedAction()

    @staticmethod
    def _has_cad_urls(event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in (".dwg", ".dxf")
            for url in event.mimeData().urls()
        )

    @staticmethod
    def _cad_paths(event) -> list[str]:
        return [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in (".dwg", ".dxf")
        ]

    def eventFilter(self, obj, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.DragEnter, QEvent.DragMove):
            if self._has_cad_urls(event):
                event.acceptProposedAction()
                return True
        elif event_type == QEvent.Drop:
            if self._has_cad_urls(event):
                paths = self._cad_paths(event)
                if paths:
                    self.open_files(paths)
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)
