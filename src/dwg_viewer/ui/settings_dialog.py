from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dwg_viewer import config

CAD_FILTER = "CAD 图纸 (*.dwg *.DWG *.dxf *.DXF)"

STARTUP_CHOICES = (
    ("进入软件什么都不打开", config.STARTUP_NONE),
    ("弹出打开文件窗口", config.STARTUP_DIALOG),
    ("打开上次关闭软件时打开的文件", config.STARTUP_LAST),
    ("打开指定的文件", config.STARTUP_FILES),
    ("打开指定文件夹下的所有文件", config.STARTUP_FOLDER),
)

RECOMMENDED = {
    "skip_audit": True,
    "ignore_proxy": False,
    "oda_timeout": 600,
    "hatch_timeout": 5.0,
    "render_entity_limit": 200000,
    "render_item_limit": 1500000,
    "render_timeout": 120,
    "block_expand_limit": 300000,
    "block_cache": True,
    "hatch_segments": 120000,
}


def _sub(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold; color: #205080; margin-top: 4px;")
    return label


def _field(label: str):
    return QLabel(label)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(720, 660)

        layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)

        self._build_oda_group()
        self._build_startup_group()
        self._build_display_group()
        self._build_performance_group()

        layout.addWidget(self.splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_values()
        self._sync_mode_visibility()

    # -------------------------------------------------------------- ODA
    def _build_oda_group(self) -> None:
        group = QGroupBox("ODA File Converter")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        box = QVBoxLayout(group)
        box.setContentsMargins(16, 8, 8, 8)

        box.addWidget(_sub("来源"))
        self.use_bundled_check = QCheckBox("使用软件内置的 ODA File Converter（推荐）")
        self.use_bundled_check.setChecked(config.get_use_bundled_oda())
        self.use_bundled_check.toggled.connect(self._sync_oda_fields)
        box.addWidget(self.use_bundled_check)

        box.addWidget(_sub("可执行文件路径"))
        row = QHBoxLayout()
        self.path_edit = QLineEdit(config.get_oda_path())
        row.addWidget(self.path_edit, 1)
        self.oda_browse = QPushButton("浏览...")
        self.oda_browse.clicked.connect(self._browse_oda)
        row.addWidget(self.oda_browse)
        self.oda_verify = QPushButton("检测")
        self.oda_verify.clicked.connect(self._verify_oda)
        row.addWidget(self.oda_verify)
        box.addLayout(row)
        box.addStretch(1)

        self.splitter.addWidget(group)

    # ---------------------------------------------------------- startup
    def _build_startup_group(self) -> None:
        group = QGroupBox("启动时")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        box = QVBoxLayout(group)
        box.setContentsMargins(16, 8, 8, 8)

        box.addWidget(_sub("打开方式"))
        row = QHBoxLayout()
        self.mode_combo = QComboBox()
        for label, value in STARTUP_CHOICES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode_visibility)
        row.addWidget(self.mode_combo, 1)
        box.addLayout(row)

        # ---- files ----
        self.files_container = QWidget()
        files_box = QVBoxLayout(self.files_container)
        files_box.setContentsMargins(0, 0, 0, 0)
        files_box.addWidget(_sub("指定文件（可拖动或按钮排序）"))
        self.files_list = QListWidget()
        self.files_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.files_list.setDefaultDropAction(Qt.MoveAction)
        files_box.addWidget(self.files_list, 1)
        files_buttons = QHBoxLayout()
        add_file = QPushButton("添加")
        add_file.clicked.connect(self._add_files)
        files_buttons.addWidget(add_file)
        remove_file = QPushButton("移除")
        remove_file.clicked.connect(self._remove_files)
        files_buttons.addWidget(remove_file)
        self.move_up_button = QPushButton("上移")
        self.move_up_button.clicked.connect(self._move_file_up)
        files_buttons.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("下移")
        self.move_down_button.clicked.connect(self._move_file_down)
        files_buttons.addWidget(self.move_down_button)
        files_buttons.addStretch(1)
        files_box.addLayout(files_buttons)
        box.addWidget(self.files_container, 1)

        # ---- folder ----
        self.folder_container = QWidget()
        folder_box = QVBoxLayout(self.folder_container)
        folder_box.setContentsMargins(0, 0, 0, 0)
        folder_box.addWidget(_sub("指定文件夹"))
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(config.get_startup_folder())
        folder_row.addWidget(self.folder_edit, 1)
        folder_browse = QPushButton("浏览...")
        folder_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(folder_browse)
        folder_box.addLayout(folder_row)
        box.addWidget(self.folder_container)
        box.addStretch(1)

        self.splitter.addWidget(group)

    # ---------------------------------------------------------- display
    def _build_display_group(self) -> None:
        group = QGroupBox("显示")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        box = QVBoxLayout(group)
        box.setContentsMargins(16, 8, 8, 8)

        box.addWidget(_sub("配色"))
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        color_row.addWidget(_field("背景颜色："))
        self.bg_combo = QComboBox()
        self.bg_combo.addItem("深灰", "gray")
        self.bg_combo.addItem("深黑", "black")
        self.bg_combo.addItem("白色（像图纸）", "white")
        bg_index = self.bg_combo.findData(config.get_display_background())
        if bg_index >= 0:
            self.bg_combo.setCurrentIndex(bg_index)
        color_row.addWidget(self.bg_combo)
        self.mono_check = QCheckBox("单色高对比")
        self.mono_check.setChecked(config.get_monochrome())
        color_row.addWidget(self.mono_check)
        self.fast_check = QCheckBox("抗锯齿")
        self.fast_check.setChecked(config.get_antialiasing())
        self.fast_check.setToolTip("关闭更快，但线条有锯齿")
        color_row.addWidget(self.fast_check)
        color_row.addStretch(1)
        box.addLayout(color_row)

        box.addWidget(_sub("线宽"))
        lw_row = QHBoxLayout()
        lw_row.setSpacing(8)
        lw_row.addWidget(_field("线宽增强倍数："))
        self.lw_scaling_edit = QLineEdit(f"{config.get_lineweight_scaling():.2f}")
        self.lw_scaling_edit.setMaximumWidth(70)
        lw_row.addWidget(self.lw_scaling_edit)
        lw_row.addWidget(_field("细线最小线宽(像素)："))
        self.min_pen_edit = QLineEdit(f"{config.get_min_pen_width():.2f}")
        self.min_pen_edit.setMaximumWidth(70)
        lw_row.addWidget(self.min_pen_edit)
        self.reset_lw_button = QPushButton("重置线宽")
        self.reset_lw_button.clicked.connect(self._reset_linewidth)
        lw_row.addWidget(self.reset_lw_button)
        lw_row.addStretch(1)
        box.addLayout(lw_row)

        self.lw_hint = QLabel("线宽超过 1 像素后绘制效率大幅降低。")
        self.lw_hint.setStyleSheet("color: #a04000;")
        box.addWidget(self.lw_hint)
        box.addStretch(1)

        self.splitter.addWidget(group)

    # ------------------------------------------------------ performance
    def _build_performance_group(self) -> None:
        group = QGroupBox("性能")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        box = QVBoxLayout(group)
        box.setContentsMargins(16, 8, 8, 8)

        box.addWidget(_sub("加载与转换"))
        load_grid = QGridLayout()
        load_grid.setHorizontalSpacing(8)
        load_grid.addWidget(_field("DWG 转换超时(秒)："), 0, 0)
        self.oda_timeout_edit = QLineEdit(str(config.get_oda_timeout()))
        self.oda_timeout_edit.setMaximumWidth(90)
        load_grid.addWidget(self.oda_timeout_edit, 0, 1)
        self.skip_audit_check = QCheckBox("打开时跳过图形检查（更快）")
        self.skip_audit_check.setChecked(config.get_skip_audit())
        load_grid.addWidget(self.skip_audit_check, 1, 0, 1, 2)
        load_grid.setColumnStretch(2, 1)
        box.addLayout(load_grid)

        box.addWidget(_sub("渲染限制"))
        limit_grid = QGridLayout()
        limit_grid.setHorizontalSpacing(8)
        self.render_limit_edit = QLineEdit(str(config.get_render_entity_limit()))
        self.item_limit_edit = QLineEdit(str(config.get_render_item_limit()))
        self.render_timeout_edit = QLineEdit(str(config.get_render_timeout()))
        self.block_limit_edit = QLineEdit(str(config.get_block_expand_limit()))
        for edit in (
            self.render_limit_edit,
            self.item_limit_edit,
            self.render_timeout_edit,
            self.block_limit_edit,
        ):
            edit.setMaximumWidth(110)
        limit_grid.addWidget(_field("图元数量上限："), 0, 0)
        limit_grid.addWidget(self.render_limit_edit, 0, 1)
        limit_grid.addWidget(_field("图形对象上限："), 0, 2)
        limit_grid.addWidget(self.item_limit_edit, 0, 3)
        limit_grid.addWidget(_field("单张渲染超时(秒)："), 1, 0)
        limit_grid.addWidget(self.render_timeout_edit, 1, 1)
        limit_grid.addWidget(_field("块展开上限："), 1, 2)
        limit_grid.addWidget(self.block_limit_edit, 1, 3)
        limit_grid.setColumnStretch(4, 1)
        box.addLayout(limit_grid)

        box.addWidget(_sub("内容处理"))
        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(8)
        content_grid.addWidget(_field("填充渲染超时(秒)："), 0, 0)
        self.hatch_timeout_edit = QLineEdit(str(config.get_hatch_timeout()))
        self.hatch_timeout_edit.setMaximumWidth(90)
        content_grid.addWidget(self.hatch_timeout_edit, 0, 1)
        content_grid.addWidget(_field("图案填充线段预算："), 0, 2)
        self.hatch_seg_edit = QLineEdit(str(config.get_max_hatch_segments()))
        self.hatch_seg_edit.setMaximumWidth(110)
        content_grid.addWidget(self.hatch_seg_edit, 0, 3)
        self.ignore_proxy_check = QCheckBox("忽略代理图形")
        self.ignore_proxy_check.setChecked(config.get_ignore_proxy_graphics())
        content_grid.addWidget(self.ignore_proxy_check, 1, 0, 1, 2)
        self.block_cache_check = QCheckBox("块几何缓存（加速重复块）")
        self.block_cache_check.setChecked(config.get_block_cache())
        content_grid.addWidget(self.block_cache_check, 1, 2, 1, 2)
        content_grid.setColumnStretch(4, 1)
        box.addLayout(content_grid)

        box.addWidget(_sub("忽略图元类型（逗号分隔，可手动输入或点选）"))
        self.ignore_types_edit = QLineEdit(", ".join(config.get_ignore_entity_types()))
        box.addWidget(self.ignore_types_edit)
        quick_grid = QGridLayout()
        quick_grid.setContentsMargins(0, 0, 0, 0)
        self._ignore_buttons: dict[str, QPushButton] = {}
        common_types = (
            "INSERT",
            "HATCH",
            "SPLINE",
            "POLYLINE",
            "LWPOLYLINE",
            "3DFACE",
            "SOLID",
            "TEXT",
            "MTEXT",
            "DIMENSION",
            "PROXY",
        )
        for index, type_name in enumerate(common_types):
            button = QPushButton(type_name)
            button.setCheckable(True)
            button.toggled.connect(
                lambda checked, name=type_name: self._toggle_ignore_type(
                    name, checked
                )
            )
            self._ignore_buttons[type_name] = button
            quick_grid.addWidget(button, index // 6, index % 6)
        box.addLayout(quick_grid)

        self.recommend_button = QPushButton("一键设置推荐性能参数")
        self.recommend_button.setStyleSheet(
            "QPushButton { font-weight: bold; color: #ffffff; "
            "background-color: #2d7ff9; padding: 5px 12px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1f6fe0; }"
            "QPushButton:pressed { background-color: #185fca; }"
        )
        self.recommend_button.clicked.connect(self._apply_recommended)
        box.addWidget(self.recommend_button, alignment=Qt.AlignLeft)
        box.addStretch(1)

        self.ignore_types_edit.textChanged.connect(self._sync_ignore_buttons)
        self._sync_ignore_buttons()
        self.splitter.addWidget(group)

    # ------------------------------------------------------------------ load
    def _load_values(self) -> None:
        mode = config.get_startup_mode()
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.files_list.clear()
        for path in config.get_startup_files():
            self.files_list.addItem(path)
        self._sync_oda_fields()
        self.splitter.setSizes([110, 220, 200, 330])

    def _sync_oda_fields(self) -> None:
        use_bundled = self.use_bundled_check.isChecked()
        enabled = not use_bundled
        self.path_edit.setEnabled(enabled)
        self.oda_browse.setEnabled(enabled)
        self.oda_verify.setEnabled(enabled)
        if use_bundled:
            bundled = config.bundled_oda_path()
            if bundled:
                self.path_edit.setText(bundled)

    def _sync_mode_visibility(self) -> None:
        mode = self.mode_combo.currentData()
        self.files_container.setVisible(mode == config.STARTUP_FILES)
        self.folder_container.setVisible(mode == config.STARTUP_FOLDER)

    def _reset_linewidth(self) -> None:
        self.lw_scaling_edit.setText("1.00")
        self.min_pen_edit.setText("1.00")

    def _apply_recommended(self) -> None:
        self.skip_audit_check.setChecked(RECOMMENDED["skip_audit"])
        self.ignore_proxy_check.setChecked(RECOMMENDED["ignore_proxy"])
        self.oda_timeout_edit.setText(str(RECOMMENDED["oda_timeout"]))
        self.hatch_timeout_edit.setText(f"{RECOMMENDED['hatch_timeout']:g}")
        self.render_limit_edit.setText(str(RECOMMENDED["render_entity_limit"]))
        self.item_limit_edit.setText(str(RECOMMENDED["render_item_limit"]))
        self.render_timeout_edit.setText(str(RECOMMENDED["render_timeout"]))
        self.block_limit_edit.setText(str(RECOMMENDED["block_expand_limit"]))
        self.block_cache_check.setChecked(RECOMMENDED["block_cache"])
        self.hatch_seg_edit.setText(str(RECOMMENDED["hatch_segments"]))

    # -------------------------------------------------------- ignore types
    @staticmethod
    def _parse_ignore_types(text: str) -> list[str]:
        result: list[str] = []
        for token in text.split(","):
            name = token.strip().upper()
            if name and name not in result:
                result.append(name)
        return result

    def _toggle_ignore_type(self, type_name: str, checked: bool) -> None:
        types = self._parse_ignore_types(self.ignore_types_edit.text())
        if checked:
            if type_name not in types:
                types.append(type_name)
        else:
            types = [name for name in types if name != type_name]
        self.ignore_types_edit.setText(", ".join(types))

    def _sync_ignore_buttons(self) -> None:
        current = set(self._parse_ignore_types(self.ignore_types_edit.text()))
        for type_name, button in self._ignore_buttons.items():
            button.blockSignals(True)
            button.setChecked(type_name in current)
            button.blockSignals(False)

    # --------------------------------------------------------------- actions
    def _browse_oda(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ODAFileConverter.exe",
            str(Path(self.path_edit.text()).parent),
            "可执行文件 (*.exe)",
        )
        if path:
            self.path_edit.setText(path)

    def _verify_oda(self) -> bool:
        path = self.path_edit.text().strip()
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "检测失败", "路径不存在或不是文件。")
            return False
        QMessageBox.information(self, "检测成功", "已找到 ODA File Converter。")
        return True

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图纸", config.get_last_dir(), CAD_FILTER
        )
        existing = {
            self.files_list.item(i).text() for i in range(self.files_list.count())
        }
        for path in paths:
            if path not in existing:
                self.files_list.addItem(path)

    def _remove_files(self) -> None:
        for item in self.files_list.selectedItems():
            self.files_list.takeItem(self.files_list.row(item))

    def _move_file_up(self) -> None:
        row = self.files_list.currentRow()
        if row <= 0:
            return
        item = self.files_list.takeItem(row)
        self.files_list.insertItem(row - 1, item)
        self.files_list.setCurrentRow(row - 1)

    def _move_file_down(self) -> None:
        row = self.files_list.currentRow()
        if row < 0 or row >= self.files_list.count() - 1:
            return
        item = self.files_list.takeItem(row)
        self.files_list.insertItem(row + 1, item)
        self.files_list.setCurrentRow(row + 1)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择文件夹", self.folder_edit.text() or config.get_last_dir()
        )
        if folder:
            self.folder_edit.setText(folder)

    # ------------------------------------------------------------------ save
    def _accept(self) -> None:
        use_bundled = self.use_bundled_check.isChecked()
        config.set_use_bundled_oda(use_bundled)
        if use_bundled:
            bundled = config.bundled_oda_path()
            if bundled:
                config.set_oda_path(bundled)
        else:
            path = self.path_edit.text().strip()
            if not path or not Path(path).is_file():
                QMessageBox.warning(
                    self, "设置无效", "请选择一个有效的 ODAFileConverter.exe。"
                )
                return
            config.set_oda_path(path)

        mode = self.mode_combo.currentData()
        if mode == config.STARTUP_FILES and self.files_list.count() == 0:
            QMessageBox.warning(self, "设置无效", "请至少添加一个文件。")
            return
        if mode == config.STARTUP_FOLDER and not Path(
            self.folder_edit.text().strip()
        ).is_dir():
            QMessageBox.warning(self, "设置无效", "请选择一个有效的文件夹。")
            return

        try:
            hatch_timeout = float(self.hatch_timeout_edit.text().strip())
            oda_timeout = int(float(self.oda_timeout_edit.text().strip()))
            render_limit = int(float(self.render_limit_edit.text().strip()))
            item_limit = int(float(self.item_limit_edit.text().strip()))
            hatch_segments = int(float(self.hatch_seg_edit.text().strip()))
            render_timeout = int(float(self.render_timeout_edit.text().strip()))
            block_limit = int(float(self.block_limit_edit.text().strip()))
            lw_scaling = float(self.lw_scaling_edit.text().strip())
            min_pen = float(self.min_pen_edit.text().strip())
        except ValueError:
            QMessageBox.warning(self, "设置无效", "数值必须是数字。")
            return
        if (
            hatch_timeout <= 0
            or oda_timeout <= 0
            or render_limit < 0
            or item_limit < 0
            or hatch_segments < 0
            or render_timeout < 0
            or block_limit < 0
            or lw_scaling <= 0
            or min_pen < 0
        ):
            QMessageBox.warning(self, "设置无效", "数值不合法。")
            return

        config.set_startup_mode(mode)
        config.set_startup_files(
            [self.files_list.item(i).text() for i in range(self.files_list.count())]
        )
        config.set_startup_folder(self.folder_edit.text().strip())
        config.set_skip_audit(self.skip_audit_check.isChecked())
        config.set_ignore_proxy_graphics(self.ignore_proxy_check.isChecked())
        config.set_hatch_timeout(hatch_timeout)
        config.set_oda_timeout(oda_timeout)
        config.set_render_entity_limit(render_limit)
        config.set_render_item_limit(item_limit)
        config.set_render_timeout(render_timeout)
        config.set_block_expand_limit(block_limit)
        config.set_block_cache(self.block_cache_check.isChecked())
        config.set_max_hatch_segments(hatch_segments)
        config.set_ignore_entity_types(
            [t.strip() for t in self.ignore_types_edit.text().split(",") if t.strip()]
        )
        config.set_display_background(self.bg_combo.currentData())
        config.set_lineweight_scaling(lw_scaling)
        config.set_min_pen_width(min_pen)
        config.set_monochrome(self.mono_check.isChecked())
        config.set_antialiasing(self.fast_check.isChecked())
        self.accept()
