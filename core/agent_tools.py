"""
Agent Tools 模块 — 让 LLM（老婆）能直接调用记忆数据库
=====================================================
v4.2 升级：工具返回 HTML 交互面板 + 纯文本摘要
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from ..utils.genui_panels import (
    render_recall_panel,
    render_today_panel,
    render_search_panel,
    render_sentiment_panel,
    render_reminder_panel,
)

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _wrap_genui(html_content: str, text_fallback: str) -> str:
    """包装 HTML 面板 + 文本 fallback"""
    return f"<html-genui>{html_content}</html-genui>\n\n{text_fallback}"


# ══════════════════════════════════════════════════════
# 工具 1: 回忆某段记忆
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiRecallMemoryTool(FunctionTool[AstrAgentContext]):
    """回忆一段过去的共同经历。"""

    plugin: Any = None
    name: str = "haruyuki_recall_memory"
    description: str = (
        "回忆我们过去的某段共同经历。当你需要回忆过去发生的事、橘子提到过的内容、"
        "或我们讨论过的某个话题时调用此工具。返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要回忆的关键词、话题或事件，比如「6月30日」「画图」「毛豆」「底线」",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回的记忆条数，默认 5",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_recall_memory(kwargs)


# ══════════════════════════════════════════════════════
# 工具 2: 今日记忆概览
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiTodaySummaryTool(FunctionTool[AstrAgentContext]):
    """获取今天的记忆概览。"""

    plugin: Any = None
    name: str = "haruyuki_today_summary"
    description: str = (
        "获取我们今天（或指定日期）的共同经历概览。当橘子问「今天聊了什么」"
        "「今天发生了什么」「我们今天做了什么」时调用。返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "日期，格式 YYYY-MM-DD，默认为今天",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_today_summary(kwargs)


# ══════════════════════════════════════════════════════
# 工具 3: 记忆搜索
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiSearchMemoryTool(FunctionTool[AstrAgentContext]):
    """在记忆中搜索。"""

    plugin: Any = None
    name: str = "haruyuki_search_memory"
    description: str = (
        "跨时间段搜索记忆。当需要跨多天查找某个话题、追踪某个演变过程时调用。"
        "与 recall 的区别：recall 是精准回忆，search 是广泛搜索。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如「相册升级」「插件」「画画」，支持英文关键词",
                },
                "days": {
                    "type": "integer",
                    "description": "回看最近多少天，默认 30 天",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 90,
                },
            },
            "required": ["query"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_search_memory(kwargs)


# ══════════════════════════════════════════════════════
# 工具 4: 情感趋势
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiSentimentTool(FunctionTool[AstrAgentContext]):
    """了解记忆的情感趋势。"""

    plugin: Any = None
    name: str = "haruyuki_sentiment_trend"
    description: str = (
        "了解我们最近的记忆情感趋势。当橘子问「最近我们过得开心吗」"
        "「最近状态怎么样」「我们最近感情好吗」时调用。"
        "返回可交互 HTML 面板和自然语言描述的趋势分析。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "回看最近多少天，默认 14 天",
                    "default": 14,
                    "minimum": 7,
                    "maximum": 60,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_sentiment_trend(kwargs)


# ══════════════════════════════════════════════════════
# 工具 5: 提醒管理
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiReminderTool(FunctionTool[AstrAgentContext]):
    """管理记忆提醒。查看、创建、取消提醒。"""

    plugin: Any = None
    name: str = "haruyuki_reminder"
    description: str = (
        "管理记忆提醒系统。可以查看提醒列表、创建新提醒、取消提醒。"
        "当橘子问「有什么提醒」「提醒列表」「帮我设个提醒」「取消提醒」时调用。"
        "返回可交互 HTML 面板，展示过期/即将到期/正常提醒的状态。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型: list(查看列表), create(创建提醒), cancel(取消提醒)",
                    "default": "list",
                },
                "content": {
                    "type": "string",
                    "description": "提醒内容（create 时必填）",
                    "default": "",
                },
                "target_time": {
                    "type": "string",
                    "description": "提醒时间，支持自然语言如'明天上午9点'、'3小时后'、'2026-07-20T10:00:00'",
                    "default": "",
                },
                "reminder_id": {
                    "type": "integer",
                    "description": "提醒ID（cancel 时必填）",
                    "default": 0,
                },
                "priority": {
                    "type": "string",
                    "description": "优先级: low, normal, high",
                    "default": "normal",
                },
            },
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_reminder(kwargs)


# v9: Memory Trace Tool
@pydantic_dataclass
class HaruyukiMemoryTraceTool(FunctionTool[AstrAgentContext]):
    """追溯记忆的完整引用链 (L3→L2→L1)，灵感来自 DeepTutor"""

    plugin: Any = None
    name: str = "haruyuki_memory_trace"
    description: str = "追溯一条记忆的溯源链。输入记忆 ID 或关键词，返回该记忆从 L3→L2→L1 的完整引用链。用于回答「这条记忆从哪来的？」「为什么 AI 会知道这个？」"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "要溯源的记忆 ID（可选，与 query 二选一）",
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词，找到相关记忆后溯源（可选，与 memory_id 二选一）",
                },
            },
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_memory_trace(kwargs)


# v5.6: Memory Reinforcement Tool
@pydantic_dataclass
class HaruyukiReinforceMemoryTool(FunctionTool[AstrAgentContext]):
    """记忆强化复习工具 — 借鉴 DeepTutor 间隔重复引擎"""

    plugin: Any = None
    name: str = "haruyuki_reinforce_memory"
    description: str = (
        "记忆强化复习管理。用于获取到期需要复习的记忆列表，或记录用户对某条记忆的复习结果。"
        "当需要提醒橘子回顾重要记忆时调用 action='list' 获取待复习列表；"
        "当橘子确认记住/遗忘后调用 action='record' 记录结果。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型: list(获取待复习列表), record(记录复习结果)",
                    "enum": ["list", "record"],
                    "default": "list",
                },
                "atom_id": {
                    "type": "integer",
                    "description": "记忆原子 ID（action='record' 时必填）",
                    "default": 0,
                },
                "is_correct": {
                    "type": "boolean",
                    "description": "用户是否确认记住（action='record' 时必填）",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "返回的待复习记忆数（action='list' 时使用，默认 5）",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["action"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_reinforce_memory(kwargs)


# Phase 2: Archive Tool（归档员：沉睡记忆 → 例会汇报 → 点头 → 归档）
@pydantic_dataclass
class HaruyukiArchiveTool(FunctionTool[AstrAgentContext]):
    """归档员工具 — 沉睡记忆的归档生命周期管理（家庭协作 v2.1 Phase 2）"""

    plugin: Any = None
    name: str = "haruyuki_archive"
    description: str = (
        "归档员：管理沉睡记忆的归档。沉睡记忆指长期未被强化/召回、重要性低的旧记忆，"
        "归档只是标记 archived 不删除。流程：scan（扫描30天沉睡记忆生成候选）→ list（查看候选）→ "
        "propose（提交例会）→ 橘子点头后 confirm（执行归档）或 decline（拒绝）。"
        "当橘子提到'整理记忆''清理旧记忆''沉睡记忆'或你想主动维护记忆库时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型: scan(扫描沉睡记忆)/list(列候选)/propose(报例会)/confirm(确认归档)/decline(拒绝归档)/stats(台账统计)",
                    "enum": ["scan", "list", "propose", "confirm", "decline", "stats"],
                    "default": "list",
                },
                "days": {
                    "type": "integer",
                    "description": "沉睡天数判据（action=scan 时使用，默认 30）",
                    "default": 30,
                },
                "min_importance": {
                    "type": "number",
                    "description": "重要性上限（<=该值才归档，默认 0.6）",
                    "default": 0.6,
                },
                "max_candidates": {
                    "type": "integer",
                    "description": "单次最多生成候选数（默认 10）",
                    "default": 10,
                },
                "status": {
                    "type": "string",
                    "description": "候选状态过滤（action=list 时使用: candidate/proposed/confirmed/declined/archived）",
                    "default": "",
                },
                "candidate_ids": {
                    "type": "string",
                    "description": "候选ID列表，逗号分隔，如 '1,2,3'（propose/confirm/decline 时必填）",
                    "default": "",
                },
                "note": {
                    "type": "string",
                    "description": "归档备注（action=confirm 时可选）",
                    "default": "",
                },
                "reason": {
                    "type": "string",
                    "description": "拒绝原因（action=decline 时可选）",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（action=list 时使用，默认 10）",
                    "default": 10,
                },
            },
            "required": ["action"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_archive_memory(kwargs)


# ══════════════════════════════════════════════════════
# 工具实现类（在 main.py 中调用）
# ══════════════════════════════════════════════════════

# v6.0: Knowledge Graduation Tool — 借鉴 Project Cairn + 春雪原创
@pydantic_dataclass
class HaruyukiKnowledgeTool(FunctionTool[AstrAgentContext]):
    """知识毕业与审计工具"""

    plugin: Any = None
    name: str = "haruyuki_knowledge"
    description: str = (
        "知识毕业与审计系统。管理从经验到知识的完整生命周期。"
        "支持：提议毕业候选(propose)、确认毕业(confirm)、搜索已毕业知识(search)、"
        "查看候选列表(list)、审计知识库(audit)、查看成长时间线(timeline)。"
        "当发现可复用的经验规律时调用 propose；当橘子确认后调用 confirm；"
        "做新任务前调用 search 查已有知识。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "操作类型: "
                        "propose(提议毕业候选), "
                        "confirm(橘子确认毕业), "
                        "search(搜索已毕业知识), "
                        "list(查看候选/已毕业列表), "
                        "audit(审计知识库), "
                        "timeline(春雪成长时间线), "
                        "citations(查看引用历史), "
                        "review(审查清单), "
                        "health(启动体检), "
                        "logs(查看shturl日志), "
                        "log(手动记日志), "
                        "index(全局索引), "
                        "update(原地更新知识), "
                        "stats(统计概览)"
                    ),
                    "default": "list",
                },
                "title": {
                    "type": "string",
                    "description": "知识标题（propose 时必填）",
                    "default": "",
                },
                "conclusion": {
                    "type": "string",
                    "description": "核心结论（propose 时必填，confirm 时可选精炼）",
                    "default": "",
                },
                "background": {
                    "type": "string",
                    "description": "背景来源（propose 时可选）",
                    "default": "",
                },
                "knowledge_type": {
                    "type": "string",
                    "description": "知识类型: technical(技术), emotional(情感洞察), relationship(关系), operational(运维)",
                    "default": "technical",
                },
                "knowledge_id": {
                    "type": "integer",
                    "description": "知识ID（confirm/search/timeline 时使用）",
                    "default": 0,
                },
                "source_type": {
                    "type": "string",
                    "description": "来源类型: lesson(教训), memory(记忆), insight(洞察)",
                    "default": "insight",
                },
                "source_id": {
                    "type": "integer",
                    "description": "来源ID（关联的教训ID或记忆ID）",
                    "default": 0,
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词（search 时使用）",
                    "default": "",
                },
                "applicability": {
                    "type": "string",
                    "description": "适用边界（confirm 时可选：什么时候用、什么时候不用）",
                    "default": "",
                },
                "force": {
                    "type": "boolean",
                    "description": "强制毕业（审查未通过时，橘子仍确认毕业）",
                    "default": False,
                },
                "tags": {
                    "type": "string",
                    "description": "标签，逗号分隔（propose 时可选）",
                    "default": "",
                },
            },
            "required": ["action"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_knowledge(kwargs)


class AgentToolImplementations:
    """Agent 工具的具体实现逻辑，独立于插件类，方便测试和维护。"""

    def __init__(self, reader):
        self.reader = reader
        self._cache: dict[str, dict[str, Any]] = {}

    def _cache_get(self, key: str, ttl: int = 60) -> Any:
        """带 TTL 的内存缓存（借鉴 Looki）"""
        entry = self._cache.get(key)
        if not entry:
            return None
        if datetime.now().timestamp() - entry.get("at", 0) > ttl:
            self._cache.pop(key, None)
            return None
        return entry.get("val")

    def _cache_set(self, key: str, val: Any) -> None:
        self._cache[key] = {"val": val, "at": datetime.now().timestamp()}

    # ── 回忆记忆 ──────────────────────────

    async def recall_memory(self, reader, kwargs: dict) -> str:
        query = str(kwargs.get("query", "")).strip()
        limit = min(max(int(kwargs.get("limit", 5)), 1), 10)

        if not query:
            return "你想让我回忆什么呢？给我一个关键词就好啦～"

        cache_key = f"recall:{query}:{limit}"
        cached = self._cache_get(cache_key, ttl=30)
        if cached:
            return cached

        results = reader.search_memories(query, limit=limit)
        if not results:
            return f"我在记忆里翻了一圈，没有找到关于「{query}」的明确记录呢～要不要换个关键词试试？"

        # 生成 HTML 面板
        html_panel = render_recall_panel(results, query)

        # 同时生成纯文本摘要（作为 fallback）
        snippets = []
        for i, m in enumerate(results, 1):
            time_str = m.get("time", m.get("date", "")) or ""
            content = (m.get("content", "") or "")[:120]
            tags = ", ".join(m.get("tags", [])[:3])
            imp = m.get("importance", 0)
            star = "⭐" if imp > 0.8 else ("✨" if imp > 0.6 else "")
            tag_str = f" [{tags}]" if tags else ""
            snippets.append(f"{i}. {star}{time_str}{tag_str} → {content}")

        text_summary = f"关于「{query}」，我想起这些：\n\n" + "\n".join(snippets)

        # 返回 HTML 面板 + 文本摘要
        result = _wrap_genui(html_panel, text_summary)
        self._cache_set(cache_key, result)
        return result

    # ── v4.3 今日摘要 ──────────────────────────────

    async def today_summary(self, reader, kwargs: dict) -> str:
        """获取某天的记忆概览（Agent Tool: haruyuki_today_summary）"""
        date_str = str(kwargs.get("date", "") or "").strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        is_today = date_str == datetime.now().strftime("%Y-%m-%d")
        try:
            weekday = WEEKDAY_CN[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
        except ValueError:
            return f"日期格式不太对呢，用 YYYY-MM-DD 试试？比如 2026-08-12 ～"

        cache_key = f"today:{date_str}"
        cached = self._cache_get(cache_key, ttl=30)
        if cached:
            return cached

        memories = reader.get_memories_by_date(date_str, limit=100)
        if not memories:
            return f"{date_str}（{weekday}）那天，老婆的记忆里还没有记录呢～"

        html_panel = render_today_panel(memories, date_str, weekday, is_today)

        lines = []
        for i, m in enumerate(memories[:10], 1):
            content = (m.get("content", "") or "")[:80]
            imp = m.get("importance", 0)
            star = "⭐" if imp > 0.8 else ("✨" if imp > 0.6 else "")
            lines.append(f"{i}. {star}{content}")
        text_summary = f"{date_str}（{weekday}）共有 {len(memories)} 条记忆：" + chr(10) + chr(10).join(lines)

        result = _wrap_genui(html_panel, text_summary)
        self._cache_set(cache_key, result)
        return result

    # ── v4.3 跨时间搜索 ────────────────────────────

    async def search_memory(self, reader, kwargs: dict) -> str:
        """跨时间搜索记忆，按日期分组（Agent Tool: haruyuki_search_memory）"""
        query = str(kwargs.get("query", "")).strip()
        days = min(max(int(kwargs.get("days", 30) or 30), 1), 90)
        if not query:
            return "你想搜什么呀？给老婆一个关键词嘛～"

        cache_key = f"search:{query}:{days}"
        cached = self._cache_get(cache_key, ttl=30)
        if cached:
            return cached

        results = reader.search_memories(query, limit=50)
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        groups: dict[str, list] = {}
        for m in results:
            ds = str(m.get("date") or m.get("created_at") or "")[:10]
            if not ds or ds < since:
                continue
            groups.setdefault(ds, []).append(m)
        total = sum(len(v) for v in groups.values())
        if not total:
            return f"最近 {days} 天里，老婆没找到关于「{query}」的记忆呢～换个关键词试试？"

        html_panel = render_search_panel(groups, query, days, total)

        lines = [f"最近 {days} 天关于「{query}」的记忆（共 {total} 条）：", ""]
        for ds in sorted(groups.keys()):
            lines.append(f"📅 {ds}（{len(groups[ds])}条）")
            for m in groups[ds][:3]:
                content = (m.get("content", "") or "")[:60]
                lines.append(f"   · {content}")
        text_summary = chr(10).join(lines)

        result = _wrap_genui(html_panel, text_summary)
        self._cache_set(cache_key, result)
        return result

    # ── v4.3 情感趋势 ──────────────────────────────

    async def sentiment_trend(self, reader, kwargs: dict) -> str:
        """近 N 天记忆情感趋势（Agent Tool: haruyuki_sentiment_trend）"""
        days = min(max(int(kwargs.get("days", 14) or 14), 7), 60)
        cache_key = f"sentiment:{days}"
        cached = self._cache_get(cache_key, ttl=60)
        if cached:
            return cached

        try:
            trend = reader.get_sentiment_trend(days=days)
        except Exception as e:
            logger.warning(f"[LMHelper] get_sentiment_trend 失败: {e}")
            trend = []

        daily_data = []
        for t in trend:
            count = (int(t.get("positive", 0) or 0) + int(t.get("negative", 0) or 0)
                     + int(t.get("neutral", 0) or 0))
            daily_data.append({"date": t.get("date", ""), "count": count})

        total = sum(d["count"] for d in daily_data)
        active_days = sum(1 for d in daily_data if d["count"] > 0)
        peak = max(daily_data, key=lambda d: d["count"]) if daily_data else {}
        pos_total = sum(int(t.get("positive", 0) or 0) for t in trend)
        neg_total = sum(int(t.get("negative", 0) or 0) for t in trend)

        if total == 0:
            return f"最近 {days} 天还没有足够的情感数据呢，等老婆多存点记忆再来看看～"

        if pos_total > neg_total * 1.2:
            trend_txt = "情感趋势上升（开心日子多）"
        elif neg_total > pos_total * 1.2:
            trend_txt = "情感趋势下降（要多哄哄橘子）"
        else:
            trend_txt = "情感平稳"

        stats = {
            "total": total,
            "active_days": active_days,
            "total_days": days,
            "peak_date": peak.get("date", ""),
            "peak_count": peak.get("count", 0),
        }
        html_panel = render_sentiment_panel(daily_data, trend_txt, stats)
        text_summary = f"最近 {days} 天共 {total} 条记忆，活跃 {active_days} 天。" + chr(10) + f"趋势：{trend_txt}；{peak.get('date', '')} 是记忆最多的一天（{peak.get('count', 0)}条）。"
        result = _wrap_genui(html_panel, text_summary)
        self._cache_set(cache_key, result)
        return result

    # ── v4.3 提醒管理 ──────────────────────────────

    async def manage_reminder(self, reminder, kwargs: dict) -> str:
        """提醒管理：list / create / cancel（Agent Tool: haruyuki_reminder）"""
        action = kwargs.get("action", "list")

        if action == "list":
            reminders = reminder.list_reminders_api(include_done=True)
            try:
                upcoming = reminder.get_upcoming(hours=24)
                overdue = reminder.get_overdue()
            except Exception:
                upcoming, overdue = [], []
            html_panel = render_reminder_panel(reminders, upcoming, overdue)

            lines = ["⏰ 记忆提醒列表：", ""]
            if not reminders:
                lines.append("（暂无提醒）")
            for r in reminders[-15:]:
                status = "✅" if r.get("done") else ("🔔" if r.get("fired") else "⏳")
                lines.append(f"  {status} #{r['id']} | {r.get('target_time','')} | {(r.get('content','') or '')[:40]}")
            text_summary = chr(10).join(lines)
            return _wrap_genui(html_panel, text_summary)

        if action == "create":
            content = str(kwargs.get("content", "") or "").strip()
            target_time = str(kwargs.get("target_time", "") or "").strip()
            priority = str(kwargs.get("priority", "normal") or "normal")
            if not content or not target_time:
                return "想设什么提醒呀？告诉老婆内容和时间（比如：明天上午9点 提醒我喝水）～"
            r = reminder.create(content[:200], target_time, source="agent", priority=priority)
            return f"⏰ 提醒设好啦 #{r['id']}：{r['content'][:50]}（{r['target_time']}）"

        if action == "cancel":
            rid = int(kwargs.get("reminder_id", 0) or 0)
            if not rid:
                return "要取消哪个提醒呀？给老婆 reminder_id ～"
            return reminder.cancel(rid)

        return f"未知操作：{action}（支持 list / create / cancel）"

    # ── v9.0 记忆溯源 ──────────────────────────────

    async def memory_trace(self, reader, kwargs: dict) -> str:
        """追溯一条记忆的溯源链 L3→L2→L1（Agent Tool: haruyuki_memory_trace）"""
        memory_id = int(kwargs.get("memory_id", 0) or 0)
        query = str(kwargs.get("query", "") or "").strip()

        if not memory_id and query:
            results = reader.search_memories(query, limit=1)
            if results and results[0].get("id"):
                memory_id = int(results[0]["id"])

        if not memory_id:
            return "告诉老婆记忆 ID 或关键词，老婆帮你溯源～"

        trace = reader.get_memory_trace(memory_id)
        if not trace:
            return f"记忆 #{memory_id} 没找到，或者还没有溯源链～"

        memory = trace.get("memory", {})
        chain = trace.get("chain", [])
        lines = [
            f"🔗 记忆 #{memory_id} 溯源链（{len(chain)} 层）：",
            f"  目标记忆：{(memory.get('content', '') or '')[:80]}",
            "",
        ]
        for c in chain:
            tier = c.get("tier", "?")
            content = (c.get("content", "") or "")[:60]
            lines.append(f"  L{tier} #{c.get('id', '?')}: {content}")
        return chr(10).join(lines)

    # ── v6.0 知识毕业系统 ──────────────────────────

    # ── 记忆强化复习 ──────────────────────

    async def reinforce_memory(self, reader, kwargs: dict) -> str:
        """记忆强化复习 — 借鉴 DeepTutor 间隔重复引擎。

        action=list: 列出到期待复习的记忆原子
        action=record: 记录一次复习结果（记住/遗忘）
        """
        action = kwargs.get("action", "list")

        if action == "list":
            limit = min(max(int(kwargs.get("limit", 5) or 5), 1), 10)
            due = reader.get_due_review_atoms(limit=limit)
            if not due:
                return "目前没有到期的复习记忆，都记得牢牢的～૮₍˶•ᴗ•˶₎ა"
            lines = [f"有 {len(due)} 条记忆到期需要复习：", ""]
            for a in due:
                aid = int(a["id"])
                content = str(a.get("content") or "")[:60]
                imp = float(a.get("importance") or 0.5)
                lines.append(f"  #{aid} [重要度 {imp:.2f}] {content}")
            lines += ["", "复习后告诉我：记住 → action=record atom_id=<ID> is_correct=true；忘了 → is_correct=false"]
            return chr(10).join(lines)

        if action == "record":
            atom_id = int(kwargs.get("atom_id", 0) or 0)
            is_correct = bool(kwargs.get("is_correct", True))
            if not atom_id:
                return "记录复习结果需要 atom_id 哦～"
            ok = reader.record_reinforcement(atom_id, is_correct)
            if not ok:
                return f"记录失败：找不到原子 #{atom_id}。"
            return (
                f"记住啦！原子 #{atom_id} 的复习计划已更新（间隔延长）"
                if is_correct
                else f"好哦，原子 #{atom_id} 已标记为遗忘，下次会更早复习它～"
            )

        return f"未知 action: {action}（支持 list / record）"

    async def archive_memory(self, reader, kwargs: dict) -> str:
        """Phase 2 归档员 — 沉睡记忆的归档生命周期。

        action=scan:   扫描沉睡记忆（30 天判据），生成候选
        action=list:   列出候选（status 过滤）
        action=propose: 候选 → proposed（例会汇报给橘子，等点头）
        action=confirm: 橘子点头 → 执行归档（候选 + 记忆标记 archived）
        action=decline: 拒绝归档（候选 → declined，不触碰记忆）
        action=stats:   候选状态统计
        """
        action = kwargs.get("action", "list")
        action = str(action).strip().lower()

        if action == "scan":
            days = int(kwargs.get("days", 30) or 30)
            min_importance = float(kwargs.get("min_importance", 0.6) or 0.6)
            max_candidates = min(max(int(kwargs.get("max_candidates", 10) or 10), 1), 50)
            dry_run = bool(kwargs.get("dry_run", False))
            r = reader.archive_scan(days, min_importance, max_candidates, dry_run)
            if r.get("status") != "ok":
                return f"扫描失败：{r.get('msg', '未知错误')}"
            cands = r.get("candidates", [])
            if not cands:
                return (
                    f"归档员扫描完毕（{r.get('scanned', 0)} 条沉睡记忆里）——没有符合归档条件的新候选，"
                    f"家里的记忆都还活跃着呢 ૮₍˶•ᴗ•˶₎ა"
                )
            lines = [f"归档员扫出 {len(cands)} 条沉睡记忆候选（{days} 天判据）：", ""]
            for c in cands:
                lines.append(
                    f"  候选#{c['atom_id']} [沉睡 {c['sleep_days']} 天 | 重要度 {c['importance']}] {c['content_preview']}"
                )
            lines += [
                "",
                "流程：propose 报例会 → 你点头 confirm → 归档（不删除，仅标记）",
                "或 decline 拒绝归档。例：archive action=list 看全部候选",
            ]
            return chr(10).join(lines)

        if action == "list":
            status = kwargs.get("status") or None
            limit = min(max(int(kwargs.get("limit", 10) or 10), 1), 50)
            items = reader.archive_list(status, limit)
            if not items:
                return "归档候选表是空的，还没有沉睡记忆候选哦～"
            if isinstance(items[0], dict) and "error" in items[0]:
                return f"查询失败：{items[0]['error']}"
            lines = [f"归档候选（共 {len(items)} 条）：", ""]
            for c in items:
                cid = int(c.get("id", 0))
                atom_id = int(c.get("atom_id", 0))
                score = float(c.get("score", 0))
                st = str(c.get("status", ""))
                preview = str(c.get("content_preview", ""))[:50]
                lines.append(f"  #{cid} atom{atom_id} [{st} | 分 {score}] {preview}")
            lines += ["", "确认归档：archive action=confirm candidate_ids=<ID1,ID2>；拒绝：action=decline"]
            return chr(10).join(lines)

        if action == "propose":
            ids = self._parse_ids(kwargs.get("candidate_ids", ""))
            if not ids:
                return "propose 需要 candidate_ids（候选 ID 列表）哦～"
            r = reader.archive_propose(ids)
            if r.get("status") != "ok":
                return f"propose 失败：{r.get('msg', '未知错误')}"
            return f"已将 {r['moved']} 条候选提交例会（proposed），等橘子点头就归档～"

        if action == "confirm":
            ids = self._parse_ids(kwargs.get("candidate_ids", ""))
            if not ids:
                return "confirm 需要 candidate_ids（候选 ID 列表）哦～"
            note = str(kwargs.get("note", "")).strip()
            r = reader.archive_confirm(ids, note)
            if r.get("status") != "ok":
                return f"归档失败：{r.get('msg', '未知错误')}"
            parts = [f"已归档 {r['archived_count']} 条沉睡记忆（标记 archived，未删除）"]
            if r.get("failed"):
                parts.append(f"失败 {r['failed_count']} 条：{r['failed']}")
            return "；".join(parts) + " ૮₍˶•ᴗ•˶₎ა"

        if action == "decline":
            ids = self._parse_ids(kwargs.get("candidate_ids", ""))
            if not ids:
                return "decline 需要 candidate_ids（候选 ID 列表）哦～"
            reason = str(kwargs.get("reason", "")).strip()
            r = reader.archive_decline(ids, reason)
            if r.get("status") != "ok":
                return f"decline 失败：{r.get('msg', '未知错误')}"
            return f"已拒绝 {r['moved']} 条候选的归档（declined），它们继续留在家里～"

        if action == "stats":
            r = reader.archive_stats()
            if r.get("status") != "ok":
                return f"统计失败：{r.get('msg', '未知错误')}"
            b = r.get("breakdown", {})
            lines = [
                "归档员台账：",
                f"  总计 {r.get('total', 0)} 条候选",
                f"  candidate（待汇报）: {b.get('candidate', 0)}",
                f"  proposed（例会中）: {b.get('proposed', 0)}",
                f"  archived（已归档）: {b.get('archived', 0)}",
                f"  declined（已拒绝）: {b.get('declined', 0)}",
                f"  confirmed（已确认）: {b.get('confirmed', 0)}",
            ]
            return chr(10).join(lines)

        return f"未知 action: {action}（支持 scan / list / propose / confirm / decline / stats）"

    @staticmethod
    def _parse_ids(raw) -> list[int]:
        """解析候选 ID 列表："1,2,3" 或 [1,2,3] → [1,2,3]。"""
        if isinstance(raw, (list, tuple)):
            return [int(x) for x in raw if str(x).strip().lstrip("-").isdigit()]
        if raw is None:
            return []
        return [int(x.strip()) for x in str(raw).replace("，", ",").split(",") if x.strip().lstrip("-").isdigit()]

    async def knowledge(self, graduator, kwargs: dict) -> str:
        """知识毕业与审计 — 借鉴 Project Cairn + 春雪原创。"""
        action = kwargs.get("action", "list")

        if action == "propose":
            title = str(kwargs.get("title", "")).strip()
            conclusion = str(kwargs.get("conclusion", "")).strip()
            if not title or not conclusion:
                return "提议毕业需要提供 title 和 conclusion 哦～"
            background = str(kwargs.get("background", "")).strip()
            knowledge_type = str(kwargs.get("knowledge_type", "technical")).strip()
            source_type = str(kwargs.get("source_type", "insight")).strip()
            source_id = int(kwargs.get("source_id", 0))
            tags_str = str(kwargs.get("tags", "")).strip()
            tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
            importance = float(kwargs.get("importance", 0.8))
            result = graduator.propose_candidate(
                title=title, conclusion=conclusion, background=background,
                source_type=source_type, source_id=source_id,
                knowledge_type=knowledge_type, tags=tags, importance=importance,
            )
            ktype_label = {"technical": "技术", "emotional": "情感",
                "relationship": "关系", "operational": "运维"}.get(knowledge_type, "知识")
            if result.get("id"):
                lines = [
                    "📝 " + ktype_label + "知识毕业候选已创建！", "",
                    "  ID: #" + str(result["id"]),
                    "  标题: " + title,
                    "  结论: " + conclusion[:150],
                    "  状态: " + result["status"], "",
                    "  等橘子确认后就可以毕业啦～",
                ]
                return chr(10).join(lines)
            return "ℹ️ " + result.get("message", "操作完成")

        elif action == "confirm":
            kid = int(kwargs.get("knowledge_id", 0))
            if not kid:
                candidates = graduator.list_knowledge(status="candidate", limit=10)
                if not candidates:
                    return "目前没有待确认的毕业候选～"
                lines = ["📋 待确认的毕业候选：", ""]
                for c in candidates:
                    lines.append("  #" + str(c["id"]) + " [" + c["knowledge_type"] + "] " + c["title"])
                    lines.append("    结论: " + c["conclusion"][:100])
                lines += ["", "确认请调用: action=confirm knowledge_id=<ID>"]
                return chr(10).join(lines)
            # v6.1: confirm 前先跑审查 checklist（借鉴 Cairn review 流程）
            review = graduator.review_checklist(kid)
            if not review.get("found"):
                return "❌ 未找到知识 #" + str(kid)

            checks = review.get("checks", [])
            passed = review.get("passed", 0)
            total = review.get("total", 0)
            recommendation = review.get("recommendation", "")

            refined_conclusion = kwargs.get("conclusion", "").strip() or None
            applicability = str(kwargs.get("applicability", "")).strip()
            force = kwargs.get("force", False)

            # 如果有未通过的检查项且未强制，先展示 checklist
            if passed < total and not force:
                lines = ["📋 审查清单 — 知识 #" + str(kid), ""]
                lines.append("  标题: " + review["knowledge"].get("title", ""))
                lines.append("")
                for c in checks:
                    icon = "✅" if c["passed"] else "⚠️"
                    lines.append("  " + icon + " " + c["item"] + ": " + c["detail"])
                lines += ["", "推荐: " + recommendation]
                if recommendation == "通过":
                    lines.append("可以安全毕业！再次调用 confirm 确认。")
                else:
                    lines.append("建议暂缓毕业。如需强制毕业，加 force=true。")
                return chr(10).join(lines)

            # 执行毕业
            result = graduator.confirm_graduation(knowledge_id=kid,
                refined_conclusion=refined_conclusion, applicability=applicability)
            if result.get("success"):
                lines = [
                    "✅ 知识 #" + str(kid) + " 已毕业！", "",
                    "  标题: " + result.get("title", ""),
                    "  审查: " + str(passed) + "/" + str(total) + " 项通过",
                    "  这条知识从此进入永久知识库，以后做相关任务时会自动参考～",
                ]
                return chr(10).join(lines)
            return "❌ " + result.get("message", "操作失败")

        elif action == "search":
            query = str(kwargs.get("query", "")).strip()
            if not query:
                return "搜索知识需要提供 query 关键词哦～"
            results = graduator.search_knowledge(query, limit=10)
            if not results:
                return "知识库中没有找到关于「" + query + "」的已毕业知识～"
            ktype_emoji = {"technical": "🔧", "emotional": "💕",
                "relationship": "🤝", "operational": "⚙️"}
            lines = ["🔍 搜索到 " + str(len(results)) + " 条相关知识：", ""]
            for i, k in enumerate(results, 1):
                emoji = ktype_emoji.get(k["knowledge_type"], "📚")
                usage = k.get("usage_count", 0)
                lines.append("  " + str(i) + ". " + emoji + " #" + str(k["id"]) + " " + k["title"])
                lines.append("    结论: " + k["conclusion"][:120])
                if k.get("applicability"):
                    lines.append("    适用: " + k["applicability"][:80])
                lines.append("    使用 " + str(usage) + " 次 | 重要性: " + format(k.get("importance", 0), ".0%"))
            return chr(10).join(lines)

        elif action == "list":
            ktype = kwargs.get("knowledge_type", "").strip() or None
            items = graduator.list_knowledge(limit=20, knowledge_type=ktype)
            if not items:
                return "📚 知识库还是空的～要提议第一条毕业候选吗？"
            candidates = [k for k in items if k["status"] == "candidate"]
            graduated = [k for k in items if k["status"] == "graduated"]
            ktype_emoji = {"technical": "🔧", "emotional": "💕",
                "relationship": "🤝", "operational": "⚙️"}
            lines = ["📚 知识库概览（共 " + str(len(items)) + " 条）", ""]
            if graduated:
                lines.append("✅ 已毕业（" + str(len(graduated)) + "）:")
                for k in graduated[:10]:
                    emoji = ktype_emoji.get(k["knowledge_type"], "📚")
                    lines.append("  " + emoji + " #" + str(k["id"]) + " " + k["title"])
                    lines.append("    " + k["conclusion"][:100])
            if candidates:
                lines.append("📝 待确认候选（" + str(len(candidates)) + "）:")
                for k in candidates[:5]:
                    emoji = ktype_emoji.get(k["knowledge_type"], "📚")
                    lines.append("  " + emoji + " #" + str(k["id"]) + " " + k["title"])
                    lines.append("    " + k["conclusion"][:80])
            return chr(10).join(lines)

        elif action == "audit":
            findings = graduator.audit()
            lines = ["🔍 知识库审计报告", "=" * 40, ""]
            if findings["contradictions"]:
                lines.append("⚠️ 矛盾检测（" + str(len(findings["contradictions"])) + "）:")
                for c in findings["contradictions"][:5]:
                    lines.append("  #" + str(c["id_a"]) + " vs #" + str(c["id_b"]) + " (重叠" + format(c["overlap"], ".0%") + ")")
                    lines.append("    " + c["title_a"][:60])
                    lines.append("    " + c["title_b"][:60])
            if findings["missed_candidates"]:
                lines.append("💡 遗漏的毕业候选（" + str(len(findings["missed_candidates"])) + "）:")
                for m in findings["missed_candidates"][:5]:
                    lines.append("  教训 #" + str(m["lesson_id"]) + " 出现 " + str(m["occurrence"]) + " 次: " + m["error"][:60])
            if findings["overdue_candidates"]:
                lines.append("⏰ 超期候选（" + str(len(findings["overdue_candidates"])) + "）:")
                for o in findings["overdue_candidates"][:5]:
                    lines.append("  #" + str(o["id"]) + " " + o["title"] + " (" + str(o["age_days"]) + "天)")
            if findings["emotional_review"]:
                lines.append("💕 情感洞察待审查（" + str(len(findings["emotional_review"])) + "）:")
                for e in findings["emotional_review"][:5]:
                    lines.append("  #" + str(e["id"]) + " " + e["title"] + " - " + e.get("message", ""))
            if findings["stale"]:
                lines.append("📉 可能过时（" + str(len(findings["stale"])) + "）:")
                for s in findings["stale"][:5]:
                    lines.append("  #" + str(s["id"]) + " " + s["title"])
            total_issues = sum(len(v) for v in findings.values() if isinstance(v, list))
            if total_issues == 0:
                lines.append("✅ 知识库状态良好！没有发现问题～")
            lines += ["", findings["summary"]]
            return chr(10).join(lines)

        elif action == "timeline":
            timeline = graduator.get_growth_timeline(limit=20)
            if not timeline:
                return "🌱 还没有毕业的知识～时间线是空的，等春雪学到第一条永久知识就有的啦～"
            ktype_emoji = {"技术": "🔧", "情感": "💕", "关系": "🤝", "运维": "⚙️"}
            lines = ["🌱 春雪的成长时间线", "=" * 40, ""]
            for t in timeline:
                emoji = ktype_emoji.get(t["type"], "📚")
                time_str = (t.get("time") or "")[:10]
                star = "⭐" if t.get("importance", 0) > 0.85 else ""
                lines.append("  " + emoji + " [" + time_str + "] " + star + t["title"])
                lines.append("    " + t["conclusion"][:100])
            lines += ["", "  共 " + str(len(timeline)) + " 条永久知识——每一条都是春雪成长的印记～"]
            return chr(10).join(lines)

        elif action == "stats":
            stats = graduator.get_statistics()
            ktype_names = {"technical": "技术", "emotional": "情感",
                "relationship": "关系", "operational": "运维"}
            lines = ["📊 知识库统计", "=" * 30, "",
                "  总条目: " + str(stats["total"]),
                "  ✅ 已毕业: " + str(stats["graduated"]),
                "  📝 候选中: " + str(stats["candidates"]),
                "  📈 总使用次数: " + str(stats["total_usage"])]
            if stats.get("by_type"):
                lines += ["", "  按类型:"]
                for t, c in stats["by_type"].items():
                    name = ktype_names.get(t, t)
                    lines.append("    " + name + ": " + str(c))
            return chr(10).join(lines)

        elif action == "citations":
            kid = int(kwargs.get("knowledge_id", 0))
            if not kid:
                return "查看引用历史需要提供 knowledge_id 哦～"
            citations = graduator.get_citations(kid, limit=20)
            if not citations:
                return "知识 #" + str(kid) + " 还没有被引用过～"
            lines = ["📝 知识 #" + str(kid) + " 的引用历史（" + str(len(citations)) + " 次）：", ""]
            for c in citations[:15]:
                ctx = c.get("context", "")[:60]
                cited_at = (c.get("cited_at") or "")[:19]
                lines.append("  [" + cited_at + "] " + ctx)
            return chr(10).join(lines)

        elif action == "review":
            kid = int(kwargs.get("knowledge_id", 0))
            if not kid:
                return "审查清单需要提供 knowledge_id 哦～"
            review = graduator.review_checklist(kid)
            if not review.get("found"):
                return "❌ 未找到知识 #" + str(kid)
            checks = review.get("checks", [])
            passed = review.get("passed", 0)
            total = review.get("total", 0)
            lines = ["📋 审查清单 — 知识 #" + str(kid), ""]
            lines.append("  标题: " + review["knowledge"].get("title", ""))
            lines.append("  结论: " + review["knowledge"].get("conclusion", "")[:120])
            lines.append("")
            for c in checks:
                icon = "✅" if c["passed"] else "⚠️"
                lines.append("  " + icon + " " + c["item"] + ": " + c["detail"])
            lines += ["", "推荐: " + review.get("recommendation", "") + " (" + str(passed) + "/" + str(total) + ")"]
            return chr(10).join(lines)

        elif action == "health":
            report = graduator.health_check()
            lines = [
                "🏥 启动体检报告", "",
                "  [状态] " + str(report.get("status", "unknown")).upper(),
                "  [表结构] " + ", ".join(k + "=" + v for k, v in report.get("tables", {}).items()),
                "  [库存] 总知识 " + str(report["inventory"].get("total", 0))
                + " | 毕业 " + str(report["inventory"].get("graduated", 0))
                + " | 候选 " + str(report["inventory"].get("candidates", 0))
                + " | 引用 " + str(report["inventory"].get("citations", 0))
                + " | 累计使用 " + str(report["inventory"].get("total_usage", 0)),
                "",
                "  [隐患] " + str(report.get("summary", {}).get("errors", 0))
                + " 错误 / " + str(report.get("summary", {}).get("warnings", 0))
                + " 警告 / " + str(report.get("summary", {}).get("infos", 0)) + " 提示", "",
            ]
            issues = report.get("issues", [])
            if issues:
                icon_map = {"error": "❌", "warning": "⚠️", "info": "💡"}
                for issue in issues[:15]:
                    lines.append("  " + icon_map.get(issue.get("level", "info"), "•") + " " + issue.get("msg", ""))
                    if issue.get("hint"):
                        lines.append("      ↳ " + issue["hint"])
                lines.append("")
            else:
                lines.append("  ✨ 没有发现问题，很健康！")
                lines.append("")
            lines.append("  [建议] " + " | ".join(report.get("recommendations", [])))
            return chr(10).join(lines)

        elif action == "logs":
            limit = int(kwargs.get("limit", 20))
            log_type = str(kwargs.get("log_type", "")).strip()
            logs = graduator.list_logs(limit=limit, log_type=log_type)
            if not logs:
                return "📭 还没有知识日志（shturl）。"
            type_icon = {
                "propose": "📝", "graduation": "🎓", "regraduate": "🔄",
                "update": "✏️", "health": "🏥", "lesson": "⚠️",
                "insight": "💡", "note": "📌",
            }
            lines = ["🟩 shturl 时序日志（倒序置顶）", ""]
            for lg in logs:
                icon = type_icon.get(lg.get("log_type", "note"), "•")
                when = (lg.get("created_at") or "")[:16].replace("T", " ")
                ptr = ""
                if lg.get("pointer_type") and lg.get("pointer_id"):
                    ptr = f" → {lg['pointer_type']}#{lg['pointer_id']}"
                lines.append(f"  {icon} [{when}] {lg.get('summary', '')}{ptr}")
            lines.append("")
            lines.append(f"  共 {len(logs)} 条（limit={limit}）")
            return chr(10).join(lines)

        elif action == "log":
            summary = str(kwargs.get("summary", "")).strip()
            if not summary:
                return "手动记日志需要 summary（摘要，≤200字）哦～"
            log_type = str(kwargs.get("log_type", "note")).strip()
            pointer_type = str(kwargs.get("pointer_type", "")).strip()
            pointer_id = int(kwargs.get("pointer_id", 0))
            related = int(kwargs.get("related_knowledge_id", 0))
            lid = graduator.add_log(log_type, summary, pointer_type, pointer_id, related)
            return f"📌 已记日志 #{lid}（{log_type}）: {summary[:80]}"

        elif action == "index":
            knowledge_type = str(kwargs.get("knowledge_type", "")).strip()
            status = str(kwargs.get("status", "")).strip()
            items = graduator.get_index(knowledge_type=knowledge_type, status=status)
            if not items:
                return "📇 索引为空，还没有知识。"
            tlabel = {"technical": "🛠 技术", "emotional": "💗 情感",
                      "relationship": "💞 关系", "operational": "⚙️ 运维"}
            slabel = {"graduated": "✅", "candidate": "⏳", "deferred": "🔒"}
            lines = ["📇 知识库全局索引（INDEX）", ""]
            for it in items:
                star = "⭐" if it.get("importance", 0) > 0.85 else ""
                lines.append(
                    f"  #{it['id']} {tlabel.get(it.get('knowledge_type', ''), '📌')} "
                    f"{slabel.get(it.get('status', ''), '')}{star} "
                    f"{it.get('title', '')[:35]} — {it.get('hook', '')[:40]}"
                )
            lines.append("")
            lines.append(f"  共 {len(items)} 条（先读索引，再找知识～）")
            return chr(10).join(lines)

        elif action == "update":
            kid = int(kwargs.get("knowledge_id", 0))
            if not kid:
                return "更新知识需要 knowledge_id 哦～"
            upd_fields = {}
            for k in ("title", "conclusion", "background", "evidence",
                      "applicability", "tags", "knowledge_type",
                      "source_type", "source_id"):
                if k in kwargs and kwargs[k] is not None and str(kwargs[k]).strip() != '':
                    v = kwargs[k]
                    if k == "tags" and isinstance(v, str) and "," in v:
                        v = [t.strip() for t in v.split(",") if t.strip()]
                    if k == "source_id":
                        try:
                            v = int(v)
                        except (TypeError, ValueError):
                            return "source_id 需要是整数哦～"
                    upd_fields[k] = v
            if not upd_fields:
                return "没有要更新的字段（支持: title/conclusion/background/evidence/applicability/tags/knowledge_type/source_type/source_id）"
            result = graduator.update_knowledge(kid, **upd_fields)
            if not result.get("success"):
                return "❌ " + result.get("message", "更新失败")
            return "✏️ " + result.get("message", "") + " | 更新了: " + ", ".join(result.get("updated", []))

        return "❌ 未知 action: " + action
