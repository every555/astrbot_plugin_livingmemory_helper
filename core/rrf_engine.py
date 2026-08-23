# -*- coding: utf-8 -*-
"""
RRF (Reciprocal Rank Fusion) 纯算法模块 — v6.2

借鉴 TencentDB Agent Memory 的 Hybrid Path: Dual-Track RRF Fusion 设计。
本模块只提供 **纯算法**（不涉及 DB 连接），检索逻辑由 LivingMemoryReader 自身实现。

RRF 公式（标准论文常数 k=60）：
    RRF_score(item) = Σ 1/(k + rank + 1)  for each list containing item

核心优势：
- 多信号互补：FTS5 擅长精确匹配，LIKE 擅长中文子串，标签/元数据提供语义维度
- 无需归一化：不同检索方法的分数尺度不同，RRF 只用排名避免了归一化问题
- 自然去重：同一文档出现在多个列表中得分累加，天然提升高质量结果

参考: TencentCloud/TencentDB-Agent-Memory search-utils.ts rrfMerge<T>()
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ── RRF 核心算法 ──────────────────────────────────────────────────────

RRF_K = 60  # 论文标准常数


def rrf_merge(
    ranked_lists: List[List[Dict[str, Any]]],
    id_key: str = "id",
    k: int = RRF_K,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """RRF 融合多路检索结果（纯函数，无副作用）。

    Args:
        ranked_lists: 多路检索的排序列表（每路按相关性降序）
        id_key: 去重用的唯一标识字段名
        k: RRF 常数（默认 60，论文标准值）
        limit: 返回结果数上限

    Returns:
        融合排序后的列表，每项附加 _rrf_score / _source_count 字段
    """
    if not ranked_lists:
        return []
    if len(ranked_lists) == 1:
        return ranked_lists[0][:limit]

    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}
    source_counts: Dict[str, int] = {}

    for list_idx, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked):
            item_id = str(item.get(id_key, f"unk_{list_idx}_{rank}"))
            contribution = 1.0 / (k + rank + 1)
            scores[item_id] = scores.get(item_id, 0.0) + contribution
            if item_id not in items:
                items[item_id] = dict(item)
                source_counts[item_id] = 0
            source_counts[item_id] += 1

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

    result = []
    for item_id in sorted_ids[:limit]:
        item = items[item_id]
        item["_rrf_score"] = round(scores[item_id], 6)
        item["_source_count"] = source_counts[item_id]
        result.append(item)

    return result


# ── Token 估算工具 ────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """启发式 token 估算（中文/1.7 + 英文/4），无需 tiktoken。

    参考: TencentDB offload/fast-token-estimate.ts
    """
    if not text:
        return 0
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - cjk
    return int(cjk / 1.7 + other / 4)


# ── 上下文卸载管理器 ──────────────────────────────────────────────────
# 借鉴 TencentDB Agent Memory offload L3: Tiered Compression Cascade
#
# 三层压缩级联（按 token 占比升级）：
#   Mild (≥50%):       截断大块工具结果为摘要
#   Aggressive (≥85%): 删除最旧的非用户消息（保留最近 4 条）
#   Emergency (≥95%):  硬截断到 60% 以下

OFFLOAD_MILD_RATIO = 0.5
OFFLOAD_AGGRESSIVE_RATIO = 0.85
OFFLOAD_EMERGENCY_RATIO = 0.95
OFFLOAD_SCAN_RATIO = 0.7
TOOL_RESULT_SUMMARY_CHARS = 200


class ContextOffloadManager:
    """上下文卸载管理器 — 压缩长对话防止 context window 溢出。

    在 on_llm_request hook 中调用 maybe_compress() 检查并执行压缩。
    设计为只读检查 + 日志报告，不直接修改 AstrBot 的 req 对象（安全第一）。
    """

    def __init__(self, max_context_tokens: int = 120000):
        self.max_context_tokens = max_context_tokens

    def check(self, messages: List[Dict[str, Any]]) -> Tuple[str, int, int]:
        """检查对话是否需要压缩。

        Returns:
            (压缩级别, 当前 token 数, token 上限)
            级别: "none" / "mild" / "aggressive" / "emergency"
        """
        total = sum(
            estimate_tokens(
                msg.get("content", "")
                if isinstance(msg.get("content"), str)
                else str(msg.get("content", ""))
            )
            for msg in messages
        )
        ratio = total / self.max_context_tokens if self.max_context_tokens > 0 else 0

        if ratio >= OFFLOAD_EMERGENCY_RATIO:
            return "emergency", total, self.max_context_tokens
        elif ratio >= OFFLOAD_AGGRESSIVE_RATIO:
            return "aggressive", total, self.max_context_tokens
        elif ratio >= OFFLOAD_MILD_RATIO:
            return "mild", total, self.max_context_tokens
        return "none", total, self.max_context_tokens


# ── MMR 多样性重排（v6.8）─────────────────────────────────────────────
# 借鉴经典 MMR (Maximal Marginal Relevance, Carbonell & Goldstein 1998)
# TencentDB Agent Memory / Cyrene 均有同款：相关性 × 多样性 贪心选择。
#
# MMR(d) = lam * rel(d) - (1-lam) * max_{s in S} sim(d, s)
#   rel(d)   相关性：RRF/融合分 max 归一化（无 embedding，不依赖向量）
#   sim(d,s) 相似度：中文 trigram Jaccard（与 helper 自建 FTS5 trigram
#             索引同一套切法，零依赖纯文本；documents 表无向量列）
#   lam=0.7 默认：相关性 70% + 多样性 30%；lam=0 由调用方直接跳过（关闭）

DEF_MMR_LAMBDA = 0.7


def trigram_set(text: str) -> set:
    """文本 → 3-gram 集合（中文按字符，不足 3 字符退化为 whole-gram）"""
    t = (text or "").strip()
    if not t:
        return set()
    if len(t) < 3:
        return {t}
    return {t[i : i + 3] for i in range(len(t) - 2)}


def jaccard(a: set, b: set) -> float:
    """集合 Jaccard 相似度（空集对 → 0.0）"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def _rel_of(item: Dict[str, Any], rel_key: Optional[str]) -> float:
    """取相关性分：优先 rel_key，其次 _final（tier soft 模式），回落 _rrf_score"""
    if rel_key:
        return float(item.get(rel_key, 0.0) or 0.0)
    v = item.get("_final")
    if v is None:
        v = item.get("_rrf_score", 0.0)
    return float(v or 0.0)


def mmr_rerank(
    items: List[Dict[str, Any]],
    limit: int = 10,
    lam: float = DEF_MMR_LAMBDA,
    text_key: str = "text",
    rel_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """MMR 贪心重排：从相关性排序池中选出「既相关又彼此不重复」的 top-N。

    Args:
        items: 已按相关性降序的候选池（通常为 limit x over_sample_ratio 条）
        limit: 最终保留条数
        lam: 相关性权重（0-1）；调用方应在 lam<=0 时直接跳过本函数（关闭）
        text_key: 用于多样性计算的文本字段
        rel_key: 相关性分字段；None=自动 _final/_rrf_score

    Returns:
        重排后的列表（len == min(len(items), limit)），各项附加 _mmr_score
    """
    if lam <= 0 or not items:
        return items[:limit]
    limit = max(1, min(limit, len(items)))

    rels = [_rel_of(it, rel_key) for it in items]
    r_max = max(rels)
    # max 归一化（相对最强候选的比例），非 min-max：池内垫底 ≠ 零相关，
    # min-max 会把池尾打成 0 分导致多样性罚分永远拉不平（v6.8 单测抓出）
    if r_max > 0:
        rel_norm = [r / r_max for r in rels]
    else:
        rel_norm = [0.5 for _ in rels]  # 全零分 → 相关性无信号，多样性主导

    grams = [trigram_set(str(it.get(text_key) or "")) for it in items]

    selected: List[int] = []
    selected_grams: List[set] = []
    remaining = list(range(len(items)))

    while len(selected) < limit and remaining:
        best_i, best_v = None, -1e18
        for i in remaining:
            max_sim = 0.0
            for sg in selected_grams:
                s = jaccard(grams[i], sg)
                if s > max_sim:
                    max_sim = s
            v = lam * rel_norm[i] - (1.0 - lam) * max_sim
            if v > best_v:
                best_v, best_i = v, i
        selected.append(best_i)
        selected_grams.append(grams[best_i])
        remaining.remove(best_i)

    result = [items[i] for i in selected]
    for rank, it in enumerate(result):
        it["_mmr_rank"] = rank
    return result
