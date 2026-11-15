from typing import List

from PySide6.QtCore import QThread, Signal

from . import semantic
from .matcher import PreparedPath, prepare_paths, top_k
from .scanner import scan_folders


class ScanWorker(QThread):
    progress = Signal(int)
    done = Signal(list)
    error = Signal(str)

    def __init__(self, roots):
        super().__init__()
        # 兼容单盘调用：传 str 也能工作
        self.roots = [roots] if isinstance(roots, str) else list(roots)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            # 多盘串行扫描但共用一个结果列表，进度按总量累计，
            # 这样界面进度条不会在每个盘切换时归零。
            paths = []
            for root in self.roots:
                if self._stop:
                    break

                def _on_progress(n, _paths=paths):
                    self.progress.emit(len(_paths))

                found = scan_folders(
                    root,
                    on_progress=_on_progress,
                    should_stop=lambda: self._stop,
                )
                paths.extend(found)
            self.done.emit(paths)
        except Exception as e:
            self.error.emit(str(e))


class PrepareWorker(QThread):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, paths: List[str]):
        super().__init__()
        self.paths = paths

    def run(self):
        prepared = prepare_paths(self.paths, on_progress=self.progress.emit)
        self.done.emit(prepared)


class WarmupWorker(QThread):
    done = Signal(bool, str)

    def run(self):
        try:
            semantic.warmup()
            ok = semantic.is_ready()
            self.done.emit(ok, "" if ok else (semantic.get_load_error() or "未知错误"))
        except Exception as e:
            self.done.emit(False, str(e))


class MatchWorker(QThread):
    done = Signal(int, list)  # (generation, results)

    def __init__(
        self,
        gen: int,
        query: str,
        prepared: List[PreparedPath],
        topn: int,
        use_semantic: bool = True,
        candidate_k: int = 300,
    ):
        super().__init__()
        self.gen = gen
        self.query = query
        self.prepared = prepared
        self.topn = topn
        self.use_semantic = use_semantic
        self.candidate_k = candidate_k

    def run(self):
        try:
            if self.use_semantic and semantic.is_available() and semantic.is_ready():
                # 候选池取比 TopN 更大的范围，交给语义分重排后再截断
                rules = top_k(self.prepared, self.query, max(self.topn, self.candidate_k))
                # 规则分为 0 表示连字面都不沾边，留着只会挤占语义重排的算力
                rules = [(s, p) for s, p in rules if s > 0]
                if not rules:
                    self.done.emit(self.gen, [])
                    return
                cands = [(s, p.raw) for s, p in rules]
                reranked = semantic.rerank(self.query, cands, self.topn)
                self.done.emit(self.gen, reranked)
            else:
                rules = top_k(self.prepared, self.query, self.topn)
                self.done.emit(self.gen, [(s, p.raw, None) for s, p in rules])
        except Exception:
            self.done.emit(self.gen, [])