from typing import List

from PySide6.QtCore import QThread, Signal

from . import semantic
from .matcher import PreparedPath, prepare_paths, top_k
from .scanner import scan_folders


class ScanWorker(QThread):
    progress = Signal(int)
    done = Signal(list)
    error = Signal(str)

    def __init__(self, root: str):
        super().__init__()
        self.root = root
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            paths = scan_folders(
                self.root,
                on_progress=self.progress.emit,
                should_stop=lambda: self._stop,
            )
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
            k = max(self.topn, self.candidate_k) if self.use_semantic else self.topn
            rules = top_k(self.prepared, self.query, k)

            if self.use_semantic and semantic.is_available() and rules:
                cands = [(s, p.raw) for s, p in rules]
                reranked = semantic.rerank(self.query, cands, self.topn)
                self.done.emit(self.gen, reranked)
            else:
                self.done.emit(self.gen, [(s, p.raw, None) for s, p in rules[: self.topn]])
        except Exception:
            self.done.emit(self.gen, [])