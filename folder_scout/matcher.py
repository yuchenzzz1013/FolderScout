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

    多关键词采用「AND 召回 + 平均分排序」：
    - 只要有一个关键词在 basename 和完整路径里都完全没命中（得分为 0），
      说明这条路径与该查询无关，直接返回 0.0；
    - 否则返回各关键词得分的平均值。

    早期版本用 min() 取最小分，会让「folder scout 语义」这类查询在全路径
    精确匹配 folder 与 scout 的情况下依然得 0 分（因为“语义”不在路径里），
    配合相关性阈值会把本该展示的结果全部误杀。
    """
    if not q.raw_units:
        return 0.0

    def path_scores(attr_norm: str, attr_strip: str) -> List[int]:
        norm = getattr(prep, attr_norm)
        strip = getattr(prep, attr_strip)
        return [
            max(
                fuzz.partial_ratio(u_n, norm),
                fuzz.partial_ratio(u_s, strip),
            )
            for u_n, u_s in zip(q.unit_norms, q.unit_strips)
        ]

    # basename 优先；若已足够好则不必再算完整路径
    base_scores = path_scores("base_norm", "base_strip")
    if min(base_scores) > 0 and sum(base_scores) / len(base_scores) >= 80.0:
        return sum(base_scores) / len(base_scores)

    full_scores = path_scores("full_norm", "full_strip")
    # 逐关键词取 basename / 完整路径的较大值，再判断是否全部命中
    best = [max(b, f) for b, f in zip(base_scores, full_scores)]
    if min(best) <= 0:
        return 0.0
    return sum(best) / len(best)


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