import os
import sys
import threading
from typing import List, Optional, Tuple

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_model = None
_model_lock = threading.Lock()
_load_error: Optional[str] = None


def _resource_dir() -> str:
    """PyInstaller 打包后资源目录；源码运行时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _local_model_dir() -> Optional[str]:
    """若随包附带 models/ 目录，返回其路径作为 cache_dir。"""
    candidate = os.path.join(_resource_dir(), "models")
    return candidate if os.path.isdir(candidate) else None


def is_available() -> bool:
    global _load_error
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError as e:
        _load_error = str(e)
        return False


def get_load_error() -> Optional[str]:
    return _load_error


def is_ready() -> bool:
    return _model is not None


def _get_model():
    global _model, _load_error
    if _model is None:
        with _model_lock:
            if _model is None:
                from fastembed import TextEmbedding

                cache_dir = _local_model_dir()
                if cache_dir:
                    try:
                        _model = TextEmbedding(
                            model_name=MODEL_NAME,
                            cache_dir=cache_dir,
                            local_files_only=True,
                        )
                    except Exception as e:
                        _load_error = f"本地模型加载失败，回退在线下载：{e}"
                        _model = TextEmbedding(model_name=MODEL_NAME)
                else:
                    _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def warmup():
    """启动时后台预热，避免首次搜索卡顿。失败不抛出。"""
    try:
        _get_model()
    except Exception as e:
        global _load_error
        _load_error = str(e)


def rerank(
    query: str,
    candidates: List[Tuple[float, str]],
    top_n: int,
) -> List[Tuple[float, str, float]]:
    """
    对候选路径做语义重排。
    返回 [(rule_score, path, semantic_score)]，按 semantic_score 降序。
    """
    if not candidates:
        return []

    import numpy as np

    model = _get_model()
    texts = [c[1] for c in candidates]

    query_vec = next(iter(model.embed([QUERY_PREFIX + query])))
    doc_vecs = list(model.embed(texts))

    qv = np.asarray(query_vec, dtype=np.float32)
    dv = np.asarray(doc_vecs, dtype=np.float32)
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    dv = dv / (np.linalg.norm(dv, axis=1, keepdims=True) + 1e-9)
    sims = dv @ qv

    results = [
        (float(rule_score), path, float(sim))
        for (rule_score, path), sim in zip(candidates, sims)
    ]
    results.sort(key=lambda x: x[2], reverse=True)
    return results[:top_n]