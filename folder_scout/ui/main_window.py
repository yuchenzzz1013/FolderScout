import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import semantic
from ..scanner import list_drives
from ..workers import MatchWorker, PrepareWorker, ScanWorker, WarmupWorker

DEFAULT_TOP_N = 5

STYLE = """
QMainWindow, QWidget#central { background: #ffffff; }

QFrame#card {
    background: #f7f8fa;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
}

QLabel#sectionTitle {
    color: #1f2328;
    font-weight: 600;
}

QLabel#hint { color: #6b7280; }

QLabel#status {
    color: #374151;
    background: #f3f4f6;
    border-radius: 6px;
    padding: 6px 10px;
}

QPushButton#driveChip {
    background: #ffffff;
    border: 1px solid #d8dce2;
    border-radius: 16px;
    padding: 7px 16px;
    font-weight: 600;
    color: #6b7280;
}
QPushButton#driveChip:hover { border-color: #93c5fd; }
QPushButton#driveChip:checked {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
}

QLineEdit#keyword {
    background: #ffffff;
    border: 1px solid #d8dce2;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 14px;
}
QLineEdit#keyword:focus { border: 1px solid #2563eb; }

QPushButton {
    background: #ffffff;
    border: 1px solid #d8dce2;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #f3f4f6; }
QPushButton:pressed { background: #e5e7eb; }
QPushButton:disabled { color: #9ca3af; background: #f9fafb; }

QPushButton#primary {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#primary:disabled { background: #bfdbfe; border-color: #bfdbfe; }

QSpinBox {
    background: #ffffff;
    border: 1px solid #d8dce2;
    border-radius: 6px;
    padding: 4px 6px;
}

QTableWidget#results {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}
QTableWidget#results::item { padding: 6px 8px; }
QTableWidget#results::item:selected { background: #dbeafe; color: #1e3a8a; }
QHeaderView::section {
    background: #f7f8fa;
    color: #6b7280;
    border: none;
    border-bottom: 1px solid #e3e6ea;
    padding: 7px 8px;
    font-weight: 600;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FolderScout - 文件夹关键词匹配")
        self.resize(940, 640)
        self.setStyleSheet(STYLE)

        self.prepared = []
        self._gen = 0
        self._scan_worker = None
        self._prepare_worker = None
        self._match_worker = None
        self._warmup_worker = None

        # 输入防抖：连续输入时只在停顿 300ms 后触发一次匹配
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self.start_match)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_scan_card())
        outer.addWidget(self._build_search_card())
        outer.addWidget(self._build_results(), 1)

        self._warmup_worker = WarmupWorker()
        self._warmup_worker.done.connect(self.on_warmup_done)
        self._warmup_worker.start()

    # ---------- 布局 ----------
    def _build_scan_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("扫描范围")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        hint = QLabel("点选可同时扫描多个磁盘")
        hint.setObjectName("hint")
        head.addWidget(hint)
        head.addStretch()
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(10)

        # 每个磁盘一个可勾选的切换按钮，点一下就选/取消，比 Ctrl 点列表直观
        self.drive_buttons = []
        drive_box = QHBoxLayout()
        drive_box.setSpacing(8)
        for d in list_drives():
            btn = QPushButton(d)
            btn.setCheckable(True)
            btn.setObjectName("driveChip")
            btn.setMinimumWidth(76)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            drive_box.addWidget(btn)
            self.drive_buttons.append(btn)
        if self.drive_buttons:
            self.drive_buttons[0].setChecked(True)
        drive_box.addStretch()
        body.addLayout(drive_box, 1)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        btns.addWidget(self.select_all_btn)
        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self.start_scan)
        btns.addWidget(self.scan_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)
        btns.addWidget(self.stop_btn)
        body.addLayout(btns)

        lay.addLayout(body)

        self.status_label = QLabel("正在加载语义模型...")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)
        return card

    def _build_search_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setObjectName("keyword")
        self.keyword_edit.setPlaceholderText(
            "输入关键词自动搜索，空格分隔多个词。例：xiao_lin 项目"
        )
        self.keyword_edit.setEnabled(False)
        self.keyword_edit.textChanged.connect(lambda _: self.debounce.start())
        row.addWidget(self.keyword_edit, 1)

        row.addWidget(QLabel("显示"))
        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(1, 500)
        self.topn_spin.setValue(DEFAULT_TOP_N)
        self.topn_spin.setSuffix(" 条")
        self.topn_spin.setFixedWidth(88)
        self.topn_spin.valueChanged.connect(lambda _: self.debounce.start())
        row.addWidget(self.topn_spin)
        lay.addLayout(row)

        opts = QHBoxLayout()
        opts.setSpacing(16)
        self.semantic_cb = QCheckBox("启用语义重排")
        self.semantic_cb.setChecked(True)
        if not semantic.is_available():
            self.semantic_cb.setChecked(False)
            self.semantic_cb.setEnabled(False)
            self.semantic_cb.setToolTip(f"fastembed 不可用：{semantic.get_load_error()}")
        self.semantic_cb.stateChanged.connect(lambda _: self.debounce.start())
        opts.addWidget(self.semantic_cb)

        tip = QLabel("双击结果可直接打开文件夹")
        tip.setObjectName("hint")
        opts.addStretch()
        opts.addWidget(tip)
        lay.addLayout(opts)
        return card

    def _build_results(self) -> QTableWidget:
        self.result_table = QTableWidget(0, 3)
        self.result_table.setObjectName("results")
        self.result_table.setHorizontalHeaderLabels(["路径", "规则分", "语义分"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setShowGrid(False)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.result_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.result_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.result_table.setAlternatingRowColors(False)
        self.result_table.itemDoubleClicked.connect(self.open_item)

        hdr = self.result_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.result_table.setColumnWidth(1, 80)
        self.result_table.setColumnWidth(2, 80)
        return self.result_table

    # ---------- 事件 ----------
    def on_warmup_done(self, ok, err):
        if ok:
            self.status_label.setText("语义模型就绪。选择磁盘后点击「开始扫描」")
        else:
            self.status_label.setText(f"语义模型加载失败，将仅用规则匹配：{err}")

    def selected_drives(self):
        return [b.text() for b in self.drive_buttons if b.isChecked()]

    def toggle_select_all(self):
        # 已全选则全部取消，否则全部选中
        all_on = all(b.isChecked() for b in self.drive_buttons)
        for b in self.drive_buttons:
            b.setChecked(not all_on)

    def start_scan(self):
        roots = self.selected_drives()
        if not roots:
            self.status_label.setText("请先选择至少一个磁盘")
            return
        self.prepared = []
        self.result_table.setRowCount(0)
        self.keyword_edit.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"正在扫描 {'、'.join(roots)} ...")

        self._scan_worker = ScanWorker(roots)
        self._scan_worker.progress.connect(self.on_scan_progress)
        self._scan_worker.done.connect(self.on_scan_done)
        self._scan_worker.error.connect(
            lambda e: self.status_label.setText(f"扫描出错：{e}")
        )
        self._scan_worker.start()

    def stop_scan(self):
        if self._scan_worker:
            self._scan_worker.stop()

    def on_scan_progress(self, n):
        self.status_label.setText(f"正在扫描... 已发现 {n} 个文件夹")

    def on_scan_done(self, paths):
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"扫描完成，共 {len(paths)} 个文件夹，正在预处理...")
        self._prepare_worker = PrepareWorker(paths)
        self._prepare_worker.progress.connect(self.on_prepare_progress)
        self._prepare_worker.done.connect(self.on_prepare_done)
        self._prepare_worker.start()

    def on_prepare_progress(self, cur, total):
        self.status_label.setText(f"预处理 {cur}/{total} ...")

    def on_prepare_done(self, prepared):
        self.prepared = prepared
        self.scan_btn.setEnabled(True)
        self.keyword_edit.setEnabled(True)
        self.keyword_edit.setFocus()
        self.status_label.setText(f"就绪，共 {len(prepared)} 个文件夹，输入关键词开始搜索")
        if self.keyword_edit.text().strip():
            self.start_match()

    # ---------- 匹配 ----------
    def start_match(self):
        if not self.prepared:
            return
        q = self.keyword_edit.text().strip()
        if not q:
            self.result_table.setRowCount(0)
            self.status_label.setText(f"就绪，共 {len(self.prepared)} 个文件夹，输入关键词开始搜索")
            return
        self._gen += 1
        gen = self._gen
        # 勾选语义重排、依赖齐全、且模型确实加载成功，才走语义路径
        use_sem = (
            self.semantic_cb.isChecked()
            and semantic.is_available()
            and semantic.is_ready()
        )
        self.status_label.setText(f"正在匹配「{q}」...")
        self._match_worker = MatchWorker(
            gen, q, self.prepared, self.topn_spin.value(), use_sem
        )
        self._match_worker.done.connect(self.on_match_done)
        self._match_worker.start()

    def on_match_done(self, gen, results):
        if gen != self._gen:
            return
        self.result_table.setRowCount(0)
        if not results:
            self.result_table.setRowCount(1)
            item = QTableWidgetItem("没有匹配到文件夹，换个关键词试试")
            item.setForeground(QColor("#6b7280"))
            self.result_table.setItem(0, 0, item)
            self.result_table.setItem(0, 1, QTableWidgetItem(""))
            self.result_table.setItem(0, 2, QTableWidgetItem(""))
            self.status_label.setText(
                f"没有匹配结果。共 {len(self.prepared)} 个文件夹"
            )
            return

        self.status_label.setText(
            f"找到 {len(results)} 个匹配文件夹，共扫描 {len(self.prepared)} 个"
        )

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.result_table.setRowCount(len(results))
        for r, (rule_score, path, sem_score) in enumerate(results):
            name_item = QTableWidgetItem(path)
            name_item.setData(Qt.UserRole, path)
            name_item.setToolTip(path)
            self.result_table.setItem(r, 0, name_item)

            rule_item = QTableWidgetItem(f"{rule_score:.0f}")
            rule_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            rule_item.setForeground(QColor("#6b7280"))
            self.result_table.setItem(r, 1, rule_item)

            if sem_score is None:
                sem_item = QTableWidgetItem("—")
                sem_item.setForeground(QColor("#9ca3af"))
            else:
                sem_item = QTableWidgetItem(f"{sem_score:.3f}")
                sem_item.setForeground(QColor("#1d4ed8"))
                sem_item.setFont(mono)
            sem_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.result_table.setItem(r, 2, sem_item)

    def open_item(self, item):
        row = item.row()
        path_item = self.result_table.item(row, 0)
        if not path_item:
            return
        path = path_item.data(Qt.UserRole)
        if path and os.path.isdir(path):
            os.startfile(path)
