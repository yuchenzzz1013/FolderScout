import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import semantic
from ..scanner import list_drives
from ..workers import MatchWorker, PrepareWorker, ScanWorker, WarmupWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FolderScout - 文件夹关键词匹配")
        self.resize(900, 640)

        self.prepared = []
        self._gen = 0
        self._scan_worker = None
        self._prepare_worker = None
        self._match_worker = None
        self._warmup_worker = None

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(300)
        self.debounce.timeout.connect(self.start_match)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("选择磁盘："))
        self.drive_box = QComboBox()
        self.drive_box.addItems(list_drives())
        row1.addWidget(self.drive_box)
        self.scan_btn = QPushButton("开始扫描")
        self.scan_btn.clicked.connect(self.start_scan)
        row1.addWidget(self.scan_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)
        row1.addWidget(self.stop_btn)
        layout.addLayout(row1)

        self.status_label = QLabel("正在加载语义模型...")
        layout.addWidget(self.status_label)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("关键词："))
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("支持多关键词，空格分隔。例：xiao_lin 项目")
        self.keyword_edit.setEnabled(False)
        self.keyword_edit.textChanged.connect(lambda _: self.debounce.start())
        row2.addWidget(self.keyword_edit)
        row2.addWidget(QLabel("TopN："))
        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(1, 500)
        self.topn_spin.setValue(30)
        self.topn_spin.valueChanged.connect(lambda _: self.debounce.start())
        row2.addWidget(self.topn_spin)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.semantic_cb = QCheckBox("启用语义重排")
        self.semantic_cb.setChecked(True)  # 默认开启
        if not semantic.is_available():
            self.semantic_cb.setChecked(False)
            self.semantic_cb.setEnabled(False)
            self.semantic_cb.setToolTip(
                f"fastembed 不可用：{semantic.get_load_error()}"
            )
        self.semantic_cb.stateChanged.connect(lambda _: self.debounce.start())
        row3.addWidget(self.semantic_cb)
        row3.addStretch()
        layout.addLayout(row3)

        self.result_list = QListWidget()
        self.result_list.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.result_list)

        # 启动后台预热
        self._warmup_worker = WarmupWorker()
        self._warmup_worker.done.connect(self.on_warmup_done)
        self._warmup_worker.start()

    def on_warmup_done(self, ok, err):
        if ok:
            self.status_label.setText("语义模型就绪。请选择磁盘并点击“开始扫描”")
        else:
            self.status_label.setText(f"语义模型加载失败（将仅用规则匹配）：{err}")

    # ---------- 扫描 ----------
    def start_scan(self):
        root = self.drive_box.currentText()
        if not root:
            return
        self.prepared = []
        self.result_list.clear()
        self.keyword_edit.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"正在扫描 {root} ...")

        self._scan_worker = ScanWorker(root)
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
        self.status_label.setText(
            f"扫描完成，共 {len(paths)} 个文件夹，正在预处理..."
        )
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
        self.status_label.setText(
            f"就绪，共 {len(prepared)} 个文件夹，请输入关键词"
        )
        if self.keyword_edit.text().strip():
            self.start_match()

    # ---------- 匹配 ----------
    def start_match(self):
        if not self.prepared:
            return
        q = self.keyword_edit.text().strip()
        if not q:
            self.result_list.clear()
            return
        self._gen += 1
        gen = self._gen
        use_sem = self.semantic_cb.isChecked() and semantic.is_available()
        self._match_worker = MatchWorker(
            gen, q, self.prepared, self.topn_spin.value(), use_sem
        )
        self._match_worker.done.connect(self.on_match_done)
        self._match_worker.start()

    def on_match_done(self, gen, results):
        if gen != self._gen:
            return
        self.result_list.clear()
        for rule_score, path, sem_score in results:
            if sem_score is not None:
                text = f"规则 {rule_score:5.1f} | 语义 {sem_score:.3f}  {path}"
            else:
                text = f"规则 {rule_score:5.1f}  {path}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            self.result_list.addItem(item)

    def open_item(self, item):
        path = item.data(Qt.UserRole)
        if path and os.path.isdir(path):
            os.startfile(path)