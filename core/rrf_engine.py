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
