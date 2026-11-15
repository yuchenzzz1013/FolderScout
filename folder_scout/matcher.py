import heapq
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from rapidfuzz import fuzz

SEP_RE = re.compile(r"[\s_\-\.~、，,]+")


def normalize_keep_sep(s: str) -> str:
    """分隔符统一为空格，小写，保留词边界。"""
    return SEP_RE.sub(" ", s.lower()).strip()


def normalize_strip_sep(s: str) -> str:
    """去掉所有分隔符，小写，用于连续子串匹配。"""
    return SEP_RE.sub("", s.lower())


def basename(path: str) -> str:
    p = path.rstrip("\\/")
    if not p:
        return path
    if len(p) == 2 and p[1] == ":":
        return p  # 盘符根目录
    return p.split("\\")[-1].split("/")[-1]


@dataclass
class PreparedPath:
    raw: str
    full_norm: str
    full_strip: str
    base_norm: str
    base_strip: str


@dataclass
class ParsedQuery:
    raw_units: List[str]
    unit_norms: List[str]
    unit_strips: List[str]


def prepare_paths(
    paths: List[str],
    on_progress: Optional[Callable[[int, int], None]] = None,
    progress_every: int = 20000,
) -> List[PreparedPath]:
    out: List[PreparedPath] = []
    total = len(paths)
    for i, p in enumerate(paths):
        b = basename(p)
        out.append(
            PreparedPath(
                raw=p,
                full_norm=normalize_keep_sep(p),
                full_strip=normalize_strip_sep(p),
                base_norm=normalize_keep_sep(b),
                base_strip=normalize_strip_sep(b),
            )
        )
        if on_progress and (i + 1) % progress_every == 0:
            on_progress(i + 1, total)
    if on_progress:
        on_progress(total, total)
    return out


def parse_query(query: str) -> ParsedQuery:
    units = query.strip().split()
    return ParsedQuery(
        raw_units=units,
        unit_norms=[normalize_keep_sep(u) for u in units],
        unit_strips=[normalize_strip_sep(u) for u in units],
    )


def score_prepared(prep: PreparedPath, q: ParsedQuery) -> float:
    """
    规则打分：归一化 + token AND + 去分隔符子串，双路取 max。
    - 先算 basename；若已很高，跳过完整路径，减少开销。
    """
    if not q.raw_units:
        return 0.0

    # basename 双路
    base_norm_score = min(fuzz.partial_ratio(u, prep.base_norm) for u in q.unit_norms)
    base_strip_score = min(fuzz.partial_ratio(u, prep.base_strip) for u in q.unit_strips)
    base_best = max(base_norm_score, base_strip_score)
    if base_best >= 80.0:
        return base_best

    # 完整路径双路
    full_norm_score = min(fuzz.partial_ratio(u, prep.full_norm) for u in q.unit_norms)
    full_strip_score = min(fuzz.partial_ratio(u, prep.full_strip) for u in q.unit_strips)
    full_best = max(full_norm_score, full_strip_score)

    return max(base_best, full_best)


def top_k(
    paths: List[PreparedPath],
    query: str,
    k: int,
) -> List[Tuple[float, PreparedPath]]:
    q = parse_query(query)
    if not q.raw_units or not paths:
        return []
    # heapq.nlargest 避免对百万条全排序，且不比较 PreparedPath
    scored = [(score_prepared(p, q), i) for i, p in enumerate(paths)]
    top = heapq.nlargest(k, scored, key=lambda x: x[0])
    return [(s, paths[i]) for s, i in top]