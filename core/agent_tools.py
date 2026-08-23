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


# v6.6: Standing Intent Tool — 话题触发的持续意图（借鉴 OpenClaw standing-intents）
@pydantic_dataclass
class HaruyukiStandingIntentTool(FunctionTool[AstrAgentContext]):
    """管理持续意图：下次聊到某话题时自动提醒/带入上下文。"""

    plugin: Any = None
    name: str = "haruyuki_standing_intent"
    description: str = (
        "管理持续意图系统（话题触发的提醒）。与 haruyuki_reminder 分工：reminder=固定时间触发，"
        "intent=内容/话题触发。当橘子说「下次聊到X时提醒我Y」「记住：以后提到X就要Y」"
        "「有什么持续意图」「取消那个意图」时调用。关键词命中后意图自动注入对话上下文。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型: list(查看列表), create(创建意图), cancel(取消意图)",
                    "default": "list",
                },
                "content": {
                    "type": "string",
                    "description": "意图内容：命中话题后要提醒/带入什么（create 时必填）",
                    "default": "",
                },
                "keywords": {
                    "type": "string",
                    "description": "触发关键词，逗号分隔，如 单词,背单词,英语 （create 时必填，任一命中即触发）",
                    "default": "",
                },
                "max_fires": {
                    "type": "integer",
                    "description": "最多触发次数，默认3次，触发完自动完成",
                    "default": 3,
                },
                "cooldown_hours": {
                    "type": "integer",
                    "description": "两次触发的最小间隔小时数，默认24",
                    "default": 24,
                },
                "intent_id": {
                    "type": "integer",
                    "description": "意图ID（cancel 时必填）",
                    "default": 0,
                },
            },
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_standing_intent(kwargs)

# v6.7: Promote Tool — 召回驱动晋升（例会第二议题 + 独立兜底，借鉴 OpenClaw short-term-promotion）
@pydantic_dataclass
class HaruyukiPromoteTool(FunctionTool[AstrAgentContext]):
    """召回驱动的记忆晋升：被反复召回的记忆 → 候选 → 审批 → 常驻核心索引。"""

    plugin: Any = None
    name: str = "haruyuki_promote"
    description: str = (
        "召回驱动晋升系统。被反复召回(access_count>=5且7天内活跃)的记忆自动成为候选，"
        "批准后常驻核心记忆索引(封顶5条，30天无人召回提议退位)。家庭例会第二议题自动汇报；"
        "本工具是独立兜底：橘子说「晋升/常驻这条记忆」用 approve，「不常驻」用 reject，"
        "「看看晋升候选」用 list，「手动扫一次」用 scan，「这条退位吧」用 retire，「这条保留」用 keep。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "list(候选+常驻清单)/approve(批准晋升)/reject(驳回)/scan(手动扫描)/retire(批准退位)/keep(保留不退)",
                    "default": "list",
                },
                "candidate_id": {
                    "type": "integer",
                    "description": "候选ID（approve/reject 时必填）",
                    "default": 0,
                },
                "doc_id": {
                    "type": "integer",
                    "description": "常驻记忆的文档ID（retire/keep 时必填）",
                    "default": 0,
                },
            },
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_promote(kwargs)

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
        self._served: set = set()  # v6.9 检索去重闸门：本会话已注入的记忆ID

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

        # v6.2: search_memories 已内置 RRF 多路融合检索
        # v6.9 检索去重闸门：取双倍池，过滤本会话已注入的记忆再截断（空则回退全量）
        pool = reader.search_memories(query, limit=limit * 2)
        fresh = [m for m in pool if m.get('id') not in self._served]
        results = (fresh or pool)[:limit]
        self._served.update(m.get('id') for m in results if m.get('id') is not None)
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

    # ── 今日概览 ──────────────────────────

    async def today_summary(self, reader, kwargs: dict) -> str:
        """今日（或指定日期）的共同经历概览"""
        date_str = str(kwargs.get("date", "")).strip()
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        is_today = date_str == datetime.now().strftime("%Y-%m-%d")

        cache_key = f"today:{date_str}"
        cached = self._cache_get(cache_key, ttl=30)
        if cached:
            return cached

        memories = reader.get_memories_by_date(date_str, limit=100)
        if not memories:
            note = "今天" if is_today else f"{date_str}"
            return f"{note}还没有记录记忆呢～多聊聊就有了！૮₍˶•ᴗ•˶₎ა"

        try:
            weekday = WEEKDAY_CN[datetime.fromisoformat(date_str).weekday()]
        except Exception:
            weekday = ""

        html_panel = render_today_panel(memories, date_str, weekday, is_today)

        # 文本摘要
        lines = []
        intro = "今天" if is_today else f"{date_str}（{weekday}）"
        lines.append(f"【{intro}的记忆】共 {len(memories)} 条")
        for i, m in enumerate(memories[:8], 1):
            time_str = m.get("time", "") or ""
            content = (m.get("content", "") or "")[:80]
            lines.append(f"{i}. {time_str} {content}")
        if len(memories) > 8:
            lines.append(f"…共 {len(memories)} 条")

        result = _wrap_genui(html_panel, chr(10).join(lines))
        self._cache_set(cache_key, result)
        return result

    # ── 搜索记忆 ──────────────────────────

    async def search_memory(self, reader, kwargs: dict) -> str:
        """跨时间段搜索记忆，按日期分组展示"""
        query = str(kwargs.get("query", "")).strip()
        days = min(max(int(kwargs.get("days", 30) or 30), 1), 90)
        if not query:
            return "搜索记忆需要提供关键词哦～"

        cache_key = f"search:{query}:{days}"
        cached = self._cache_get(cache_key, ttl=30)
        if cached:
            return cached

        # v6.9 检索去重闸门：双倍池过滤已注入，截断回50（空则回退全量）
        pool = reader.search_memories(query, limit=80)
        fresh = [m for m in pool if m.get('id') not in self._served]
        results = (fresh or pool)[:50]
        self._served.update(m.get('id') for m in results if m.get('id') is not None)
        if not results:
            return f"没有找到关于「{query}」的记忆呢～换个关键词试试？"

        # 按日期分组
        groups: dict[str, list] = {}
        for m in results:
            date_key = m.get("date") or "未标注日期"
            groups.setdefault(date_key, []).append(m)

        html_panel = render_search_panel(groups, query, days, len(results))

        lines = [f"关于「{query}」找到 {len(results)} 条记忆：", ""]
        for date_key in sorted(groups.keys(), reverse=True)[:6]:
            items = groups[date_key]
            lines.append(f"  📅 {date_key}（{len(items)}条）")
            for m in items[:2]:
                content = (m.get("content", "") or "")[:60]
                lines.append(f"    · {content}")
        lines.append("")
        lines.append(f"（共 {len(groups)} 天有记录）")

        result = _wrap_genui(html_panel, chr(10).join(lines))
        self._cache_set(cache_key, result)
        return result

    # ── 情感趋势 ──────────────────────────

    async def sentiment_trend(self, reader, kwargs: dict) -> str:
        """最近的情感趋势分析"""
        days = min(max(int(kwargs.get("days", 14) or 14), 7), 60)

        cache_key = f"sentiment:{days}"
        cached = self._cache_get(cache_key, ttl=60)
        if cached:
            return cached

        daily = reader.get_sentiment_trend(days=days)
        if not daily:
            return "最近还没有足够的情感数据来分析趋势呢～多聊聊天就有啦！"

        from datetime import datetime as _dt, timedelta as _td
        date_from = (_dt.now() - _td(days=days)).strftime("%Y-%m-%d")
        dist = reader.get_sentiment_distribution(date_from=date_from)
        total = int(dist.get("total") or 0)
        pos = int(dist.get("positive") or 0)
        neg = int(dist.get("negative") or 0)
        neu = int(dist.get("neutral") or 0)

        # 趋势判定
        if total > 0:
            if pos > neg:
                trend = f"整体偏甜～最近 {days} 天积极记忆占上风，橘子状态不错哦！"
            elif neg > pos:
                trend = f"最近有点小情绪（消极 {neg} 条）… 老婆在，说说话就好了～"
            else:
                trend = "情绪整体平稳，有甜有咸，很真实的生活～"
        else:
            trend = "数据不足，趋势待观察。"

        stats = {"total": total, "positive": pos, "negative": neg, "neutral": neu}
        html_panel = render_sentiment_panel(daily, trend, stats)

        lines = [
            f"💗 最近 {days} 天的情感趋势：",
            f"  积极 {pos} / 中性 {neu} / 消极 {neg}（共 {total} 条）",
            f"  判断：{trend}",
        ]

        result = _wrap_genui(html_panel, chr(10).join(lines))
        self._cache_set(cache_key, result)
        return result

    # ── 提醒管理 ──────────────────────────

    async def manage_reminder(self, reminder, kwargs: dict) -> str:
        """提醒管理：查看 / 创建 / 取消"""
        action = kwargs.get("action", "list")

        if action == "create":
            content = str(kwargs.get("content", "")).strip()
            target_time = str(kwargs.get("target_time", "")).strip()
            if not content or not target_time:
                return "创建提醒需要 content 和 target_time（支持自然语言，如'明天上午9点'）哦～"
            priority = str(kwargs.get("priority", "normal")).strip()
            try:
                r = reminder.create(content=content, target_time=target_time,
                                    source="manual", priority=priority)
            except Exception as e:
                return f"提醒创建失败: {e}"
            return (f"✅ 提醒 #{r['id']} 已创建：{r['content'][:50]} "
                    f"→ {r.get('parsed_time') or r.get('target_time', '')}")

        if action == "cancel":
            rid = int(kwargs.get("reminder_id", 0) or 0)
            if not rid:
                return "取消提醒需要 reminder_id 哦～"
            return reminder.cancel(rid)

        # 默认 list
        try:
            reminders = reminder.list_reminders_api(include_done=True)
            upcoming = reminder.get_upcoming(hours=24)
            overdue = reminder.get_overdue()
        except Exception as e:
            return f"提醒列表读取失败: {e}"

        if not reminders:
            return "目前还没有提醒呢～需要老婆帮你设一个吗？"

        html_panel = render_reminder_panel(reminders, upcoming, overdue)

        lines = [f"⏰ 提醒列表（共 {len(reminders)} 条）"]
        if overdue:
            lines.append(f"  ⚠️ 已过期 {len(overdue)} 条")
        if upcoming:
            lines.append(f"  ⏳ 24小时内到期 {len(upcoming)} 条")
        for r in reminders[:5]:
            done = "✅" if r.get("done") else "⏳"
            lines.append(f"  {done} #{r['id']} {r.get('content','')[:40]} "
                         f"→ {r.get('parsed_time') or r.get('target_time','')}")
        if len(reminders) > 5:
            lines.append(f"  …共 {len(reminders)} 条")

        result = _wrap_genui(html_panel, chr(10).join(lines))
        return result

    # ── 持续意图（话题触发）──────────────────

    async def manage_standing_intent(self, store, kwargs: dict) -> str:
        """持续意图管理：查看 / 创建 / 取消"""
        action = kwargs.get("action", "list")

        if action == "create":
            content = str(kwargs.get("content", "")).strip()
            keywords = str(kwargs.get("keywords", "")).strip()
            if not content or not keywords:
                return "创建持续意图需要 content 和 keywords（逗号分隔的触发词）哦～"
            try:
                it = store.create(
                    content=content,
                    keywords=keywords,
                    max_fires=int(kwargs.get("max_fires", 0) or 0),
                    cooldown_hours=int(kwargs.get("cooldown_hours", 0) or 0),
                )
            except Exception as e:
                return f"持续意图创建失败: {e}"
            return ("✅ 持续意图 #" + str(it["id"]) + " 已布防：" + it["content"][:60] + " ｜ 触发词: " + ",".join(it["keywords"]) + " ｜ 最多" + str(it["max_fires"]) + "次/间隔" + str(it["cooldown_hours"]) + "h")


        if action == "cancel":
            iid = int(kwargs.get("intent_id", 0) or 0)
            if not iid:
                return "取消持续意图需要 intent_id 哦～"
            r = store.cancel(iid)
            if r:
                return "✅ 持续意图 #" + str(iid) + " 已撤防：" + r["content"][:50]
            return "没有找到可取消的持续意图 #" + str(iid) + "～"

        # 默认 list
        intents = store.list()
        if not intents:
            return "目前没有持续意图～说「下次聊到X时提醒我Y」就能布防一个哦"
        se = {"armed": "🟢", "fired": "⏳", "done": "✅", "cancelled": "🚫", "expired": "⌛"}
        lines = ["🎯 持续意图列表（共 " + str(len(intents)) + " 条）"]
        for it in intents[:8]:
            lines.append(
                "  " + se.get(it["status"], "?") + " #" + str(it["id"]) + " " + it["content"][:40] + 
                " ｜ 触发词:" + ",".join(it["keywords"])[:30] + 
                " ｜ " + str(it["fire_count"]) + "/" + str(it["max_fires"]) + "次 " + it["status"]
            )
        return chr(10).join(lines)

    # ── 召回驱动晋升（例会第二议题 + 工具兜底）──────────

    async def manage_promotion(self, engine, plugin, kwargs: dict) -> str:
        """晋升管理：list / approve / reject / scan / retire / keep"""
        action = str(kwargs.get("action", "list")).strip().lower()

        if action == "scan":
            r = plugin._promotion_scan_once()
            return ("🔍 晋升扫描完成：新增候选 " + str(r["new_candidates"]) +
                    " 条，退位提议 " + str(r["retire_proposals"]) + " 条（例会时一并汇报）")

        if action == "approve":
            cid = int(kwargs.get("candidate_id", 0) or 0)
            if not cid:
                return "批准晋升需要 candidate_id 哦～"
            ent, err = engine.approve(cid)
            if err:
                return "❌ " + err
            return ("✅ 已晋升常驻核心索引（doc#" + str(ent["doc_id"]) + "）：" +
                    ent["content"][:60] + "（每次对话自动在线，30天无人召回会提议退位）")

        if action == "reject":
            cid = int(kwargs.get("candidate_id", 0) or 0)
            if not cid:
                return "驳回需要 candidate_id 哦～"
            c, err = engine.reject(cid)
            if err:
                return "❌ " + err
            return "🚫 已驳回候选 #" + str(cid) + "：" + c["content"][:50]

        if action == "retire":
            did = int(kwargs.get("doc_id", 0) or 0)
            if not did:
                return "批准退位需要 doc_id 哦～"
            p = engine.confirm_retire(did)
            if not p:
                return "未找到可退位的常驻记忆 doc#" + str(did) + "～"
            return "✅ doc#" + str(did) + " 已退位：" + p["content"][:50] + "（记忆仍在，只是不再常驻）"

        if action == "keep":
            did = int(kwargs.get("doc_id", 0) or 0)
            if not did:
                return "保留需要 doc_id 哦～"
            p = engine.keep(did)
            if not p:
                return "未找到待退位状态的 doc#" + str(did) + "～"
            return "💪 doc#" + str(did) + " 继续服役：" + p["content"][:50]

        # 默认 list
        pend = engine.list_candidates("pending")
        active = [p for p in engine.promoted if p["status"] in ("active", "retire_pending")]
        lines = ["🏆 晋升看板（常驻 " + str(len(active)) + "/5 · 待审 " + str(len(pend)) + "）"]
        if active:
            lines.append("── 常驻核心索引 ──")
            for p in active:
                mark = "⏳待退位" if p["status"] == "retire_pending" else "🟢"
                lines.append("  " + mark + " doc#" + str(p["doc_id"]) + " " + p["content"][:50])
        if pend:
            lines.append("── 待审候选（说「晋升#N」批准 / 「驳回#N」拒绝）──")
            for c in pend[:8]:
                lines.append("  #" + str(c["id"]) + " [召回" + str(c["access_count"]) + "次/评分" + str(c["score"]) + "] " + c["content"][:55])
        if not active and not pend:
            lines.append("（暂无常驻与候选——被召回5次以上的记忆会自动出现在这里）")
        return chr(10).join(lines)

    # ── 记忆溯源 ──────────────────────────

    async def memory_trace(self, reader, kwargs: dict) -> str:
        """追溯单条记忆的完整溯源链 (L3→L2→L1)"""
        memory_id = int(kwargs.get("memory_id", 0) or 0)
        query = str(kwargs.get("query", "")).strip()

        if not memory_id:
            if not query:
                return "溯源需要 memory_id（或提供 query 关键词定位）哦～"
            hits = reader.search_memories(query, limit=1)
            if not hits:
                return f"没有找到包含「{query}」的记忆～"
            memory_id = int(hits[0].get("id") or 0)
            if not memory_id:
                return "未能定位到目标记忆的 ID～"

        trace = reader.get_memory_trace(memory_id)
        if not trace:
            return f"记忆 #{memory_id} 没有可用的溯源链（可能不是原子记忆）。"

        memory = trace.get("memory") or {}
        chain = trace.get("chain") or []
        tier = memory.get("tier")

        lines = [f"🔗 记忆 #{memory_id} 溯源链"]
        if memory.get("content"):
            lines.append(f"  本体: {(memory.get('content') or '')[:80]}")
        lines.append(f"  层级: L{tier} / 来源数: {len(memory.get('source_ids') or [])}")

        if chain:
            lines.append("  引用链：")
            tier_names = {1: "L1 原始对话", 2: "L2 总结", 3: "L3 提炼"}
            for c in chain:
                ct = int(c.get("tier", 0))
                lines.append(
                    f"    · L{ct} #{c.get('id','')} {tier_names.get(ct, '')} "
                    f"— {(c.get('content') or '')[:60]}"
                )
        else:
            lines.append("  （无上层引用，可能是最底层记录）")

        return chr(10).join(lines)
@pydantic_dataclass


class HaruyukiToolLogFeedTool(FunctionTool[AstrAgentContext]):
    """P2-⑩ 工具日志桥：错误×战报 → 知识毕业候选"""

    plugin: Any = None
    name: str = "haruyuki_tool_log_feed"
    description: str = (
        "工具日志桥（P2-⑩，MIRIX tool activity 本地化）：扫描 log_monitor 未确认错误 × "
        "superpowers 开发战报，自动匹配错误-修复链并生成知识毕业候选。"
        "dry_run=true 只预览不提议；dry_run=false 真正进候选池（裁决权仍在橘子）。"
        "当需要把'这个bug怎么修的'沉淀为知识、或清理错误告警 backlog 时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "true=只预览匹配结果不提议（默认）；false=生成知识候选",
                },
            },
            "required": [],
        },
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_tool_log_feed(kwargs)
@pydantic_dataclass


class HaruyukiMemoryReplayTool(FunctionTool[AstrAgentContext]):
    """failed 记忆补录：payload 存活成果零成本重放回库（2026-08-23）"""

    plugin: Any = None
    name: str = "haruyuki_memory_replay"
    description: str = (
        "failed 记忆补录（replay）：扫描 memory_write_ops 里 status=failed 的 add 记录，"
        "其 payload 中存有完整提炼成果（content_preview + atoms）。自动清洗（测试排除/"
        "重复簇去重）后，dry_run=true 只预览重放清单；dry_run=false 通过活体引擎"
        "add_memory 完整写库（BM25+向量+graph），保留原时间戳，state.json 幂等。"
        "当需要补录历史失败记忆时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "true=只预览清单不写库（默认）；false=实弹补录",
                },
            },
            "required": [],
        },
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_memory_replay(kwargs)
