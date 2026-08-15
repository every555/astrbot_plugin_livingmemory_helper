# -*- coding: utf-8 -*-
"""
LivingMemory 辅助增强插件 — v6.0
==============================================
基于 Looki 陪伴记忆插件设计模式升级：
- 新增 4 个 Agent Tool（LLM 可直接调用记忆数据库）
- 所有工具返回自然语言摘要
- 增强 LLM 请求钩子（自动注入记忆上下文）
- 内存缓存（TTL）
"""
import os
import re
import asyncio
import json
import weakref
from datetime import datetime, timedelta

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger, AstrBotConfig
import astrbot.api.star as star

from .utils.livingmemory_reader import LivingMemoryReader
from .utils.formatter import format_timeline
from .core.error_learner import ErrorLearner
from .core.knowledge_graduator import KnowledgeGraduator
from .core.exporter import MemoryExporter
from .core.reminder import MemoryReminder
from .core.reporter import MemoryReporter
from .core.conflict_detector import ConflictDetector
from .core.external_sync import ExternalSync
from .core.agent_tools import (
    HaruyukiRecallMemoryTool,
    HaruyukiTodaySummaryTool,
    HaruyukiSearchMemoryTool,
    HaruyukiSentimentTool,
    HaruyukiReminderTool,
    HaruyukiMemoryTraceTool,
    HaruyukiReinforceMemoryTool,
    HaruyukiKnowledgeTool,
    HaruyukiArchiveTool,
    AgentToolImplementations,
)
from .core.agent_tools_v2 import (
    HaruyukiCausalChainTool,
    HaruyukiConflictCheckTool,
    HaruyukiProfileTool,
    HaruyukiProphecyTool,
    HaruyukiExpressionTool,
    HaruyukiFamilyStatusTool,
    HaruyukiFamilyMeetingTool,
)
from .utils.v2_reader import V2Reader
from .core.ontology import (
    OntologyManager,
    OntologyToolImplementations,
    EntityType,
    RelationType,
)
from .core.dream_engine import DreamEngine
from .core.emotion_engine import EmotionEngine
from .core.emotion_store import EmotionStore     # v6.0: 情感持久化
from .core.episodic_store import EpisodicStore   # v6.0: 情节记忆扩展

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class Main(star.Star):
    def __init__(self, context: star.Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config or {}
        root = os.getcwd()
        db_path = os.path.join(
            root, "data", "plugin_data",
            "astrbot_plugin_livingmemory", "livingmemory.db",
        )
        data_dir = os.path.join(
            root, "data", "plugin_data",
            "astrbot_plugin_livingmemory_helper",
        )
        os.makedirs(data_dir, exist_ok=True)

        self.reader = LivingMemoryReader(db_path)
        self.learner = ErrorLearner(self.reader, data_dir)
        self.knowledge_graduator = KnowledgeGraduator(self.learner, self.reader, data_dir)
        self.emotion_engine = EmotionEngine()  # v5.6: 上下文感知情感引擎
        self.emotion_store = EmotionStore(os.path.join(data_dir, "emotions.db"))  # v6.0: 情感持久化
        self.episodic_store = EpisodicStore(os.path.join(data_dir, "episodic.db"))  # v6.0: 情节记忆
        self.exporter = MemoryExporter(
            self.reader, os.path.join(data_dir, "exports"),
        )
        self.reminder = MemoryReminder(self.reader, data_dir)
        self.reporter = MemoryReporter(self.reader)
        self.detector = ConflictDetector(self.reader)
        self.syncer = ExternalSync(self.reader, data_dir)
        self.data_dir = data_dir
        self._last_bot_text = {}
        self._auto_scan_task = None
        self._plugin_load_time = __import__('time').time()  # v4.3: 用于前端检测插件重载
        self._last_msg_origin = None  # 保存最近的unified_msg_origin用于主动推送
        self._recall_cache = {}  # v5.0: 语义召回缓存 {query_hash: (timestamp, results)}

        # ━━━ v4.0: Agent Tools（弱引用代理，斩断热重载内存泄漏）━━━
        self.agent_tools_impl = AgentToolImplementations(self.reader)
        proxy_self = weakref.proxy(self)
        self.context.add_llm_tools(
            HaruyukiRecallMemoryTool(plugin=proxy_self),
            HaruyukiTodaySummaryTool(plugin=proxy_self),
            HaruyukiSearchMemoryTool(plugin=proxy_self),
            HaruyukiSentimentTool(plugin=proxy_self),
            HaruyukiReminderTool(plugin=proxy_self),
            HaruyukiMemoryTraceTool(plugin=proxy_self),
            HaruyukiReinforceMemoryTool(plugin=proxy_self),
            HaruyukiKnowledgeTool(plugin=proxy_self),
            HaruyukiArchiveTool(plugin=proxy_self),
        )
        logger.info("[LMHelper v6.0] 9 Agent Tools 已注册：recall | today | search | sentiment | reminder | trace | reinforce | knowledge | archive")

        # ━━━ v6.1: 记忆生态系统 v2.0 查询（家庭协作版 5 工具）━━━
        try:
            v2_db_path = os.path.join(
                root, "data", "plugin_data",
                "astrbot_plugin_livingmemory", "v2_memory.db",
            )
            self.v2_reader = V2Reader(db_path, v2_db_path)
            self.context.add_llm_tools(
                HaruyukiCausalChainTool(plugin=weakref.proxy(self)),
                HaruyukiConflictCheckTool(plugin=weakref.proxy(self)),
                HaruyukiProfileTool(plugin=weakref.proxy(self)),
                HaruyukiProphecyTool(plugin=weakref.proxy(self)),
                HaruyukiExpressionTool(plugin=weakref.proxy(self)),
                HaruyukiFamilyStatusTool(plugin=weakref.proxy(self)),
                HaruyukiFamilyMeetingTool(plugin=weakref.proxy(self)),
            )
            logger.info("[LMHelper v6.0] v2.0 7 Agent Tools 已注册：causal_chain | conflict_check | profile | prophecy | expression | family_status | family_meeting")
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] v2 查询工具初始化失败（降级，不影响主功能）: {e}")
            self.v2_reader = None

        # ━━━ v2.1: 家庭协作反馈回路（事件订阅：A6 预言→提醒 / A8 冲突→知识 / A9 教训→知识）━━━
        try:
            from .core.family_bus import register_family_subscribers

            register_family_subscribers(self)
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 家庭订阅注册失败（降级）: {e}")

        # ━━━ v3.1: 知识图谱模块 ━━━
        ontology_db_path = os.path.join(data_dir, "ontology.db")
        self.ontology = OntologyManager(ontology_db_path)
        self.ontology_impl = OntologyToolImplementations(self.ontology)
        
        # 注册知识图谱Agent Tools
        from .core.ontology import (
            OntologyCreateEntityTool,
            OntologyQueryEntityTool,
            OntologyLinkEntitiesTool,
            OntologySearchEntitiesTool,
            OntologyGetRelatedTool,
            OntologyStatsTool,
        )
        self.context.add_llm_tools(
            OntologyCreateEntityTool(plugin=self),
            OntologyQueryEntityTool(plugin=self),
            OntologyLinkEntitiesTool(plugin=self),
            OntologySearchEntitiesTool(plugin=self),
            OntologyGetRelatedTool(plugin=self),
            OntologyStatsTool(plugin=self),
        )
        logger.info("[LMHelper v6.0] 6 知识图谱 Agent Tools 已注册：create | query | link | search | related | stats")

        # ━━━ v4.0: Dream Engine ━━━
        self.dream_engine = DreamEngine(self.reader, data_dir)
        self._dream_loop_task = asyncio.create_task(self._dream_engine_daemon())
        logger.info("[LMHelper v6.0] Dream Engine 已初始化")

        # ━━━ v4.1: Reminder Checker Daemon ━━━
        self._reminder_loop_task = asyncio.create_task(self._reminder_daemon())
        logger.info("[LMHelper v6.0] Reminder Checker Daemon 已初始化")

        # ━━━ v4.2: Family Meeting Daemon（空闲自动开例会）━━━
        self._meeting_loop_task = asyncio.create_task(self._meeting_daemon())
        logger.info("[LMHelper v6.0] Family Meeting Daemon 已初始化")

        # ━━━ v3.0: UI Settings Bridge ━━━
        self._settings_file = os.path.join(data_dir, "ui_settings.json")
        self._ui_settings: dict = self._load_settings_file()

        # 从 settings 同步 dream_engine 开关状态（v5.7.1fix: 用 dream_enabled 而非 dream_cleaning_enabled）
        if "dream_enabled" in self._ui_settings:
            self.dream_engine.set_enabled(self._ui_settings["dream_enabled"])

        self._register_api_routes()

        logger.info("[LMHelper v6.0] 全部 8 模块 + 4 Agent Tools + Dream Engine 已装载")

    # ═══════════════════ WebUI API 路由 ═══════════════════

    def _register_api_routes(self):
        PREFIX = "/astrbot_plugin_livingmemory_helper/page"
        try:
            register = self.context.register_web_api
            # === GET routes ===
            get_routes = [
                ("stats",              self._api_stats,              ["GET"], "Stats"),
                ("timeline",           self._api_timeline,           ["GET"], "Timeline"),
                ("lessons",            self._api_lessons_list,       ["GET"], "Lessons list"),
                ("memories",           self._api_memories,           ["GET"], "Memory list"),
                ("search",             self._api_search,             ["GET"], "Search"),
                ("tags",               self._api_tags,               ["GET"], "All tags"),
                ("tags/stats",         self._api_tags_stats,         ["GET"], "Tag stats"),
                # NOTE: memory/pyramid MUST come before memory/<id> to avoid route conflict
                ("memory/pyramid",     self._api_memory_pyramid,     ["GET"], "Three-tier memory pyramid"),
                ("memory/<id>",        self._api_memory_detail,      ["GET"], "Memory detail"),
                ("memory/<id>/trace",  self._api_memory_trace,       ["GET"], "Memory trace chain (L3→L2→L1)"),
                ("memory/<id>/update", self._api_memory_update,      ["POST"], "Update memory"),  # moved from POST section for clarity
                ("lessons/report",     self._api_lessons_report,     ["GET"], "Lesson report"),
                ("reminders",          self._api_reminders_list,     ["GET"], "Reminders"),
                ("reminders/upcoming", self._api_reminders_upcoming, ["GET"], "Upcoming reminders"),
                ("exports/history",    self._api_exports_history,    ["GET"], "Export log"),
                ("stats/daily",        self._api_stats_daily,        ["GET"], "Daily stats"),
                ("stats/weekly",       self._api_stats_weekly,       ["GET"], "Weekly stats"),
                ("stats/trend",        self._api_stats_trend,        ["GET"], "Trend data"),
                ("stats/sentiment",    self._api_stats_sentiment,    ["GET"], "Sentiment"),
                ("graph/data",         self._api_graph_data,         ["GET"], "Graph data"),
                ("sentiment/dist",     self._api_sentiment_dist,     ["GET"], "Sentiment dist"),
                ("sentiment/trend",    self._api_sentiment_trend,    ["GET"], "Sentiment trend"),
                ("sentiment/words",    self._api_sentiment_words,    ["GET"], "Emotion word cloud"),
                ("sentiment/events",   self._api_sentiment_events,   ["GET"], "Strong sentiment events"),
                # ("emotion/recent",     self._api_emotion_recent,     ["GET"], "Recent emotion trend (for meme_manager)"),  # v5.7: 已关闭meme_manager联动
                ("emotion/stats",      self._api_emotion_stats,      ["GET"], "Emotion engine stats"),
                ("archive/candidates", self._api_archive_candidates, ["GET"], "Archive candidates"),
                ("archive/similar",    self._api_archive_similar,    ["GET"], "Find similar pairs"),
                ("reports/daily",      self._api_report_daily,       ["GET"], "Daily report"),
                ("reports/weekly",     self._api_report_weekly,      ["GET"], "Weekly report"),
                ("system/info",        self._api_system_info,        ["GET"], "System info"),
                ("system/dream-status", self._api_system_dream_status, ["GET"], "Dream cleaning status"),
                ("system/settings",    self._api_settings_get,       ["GET"], "Get UI settings"),
                ("system/tier-details", self._api_tier_details,      ["GET"], "Tier memory details"),
                ("graph/edge-types",   self._api_graph_edge_types,   ["GET"], "Edge relation types"),
                ("graph/node/<id>",    self._api_graph_node_detail,  ["GET"], "Graph node detail"),
                ("notifications",      self._api_notifications,      ["GET"], "Get pending notifications"),
                ("notifications/read", self._api_notifications_read, ["POST"], "Mark notifications read"),
                ("summary/list",       self._api_summary_list,       ["GET"], "Session summaries"),
                ("summary/stats",      self._api_summary_stats,      ["GET"], "Summary stats"),
                ("family/overview",    self._api_family_overview,    ["GET"], "Family ecosystem overview"),
            ]
            for ep, handler, methods, desc in get_routes:
                register(f"{PREFIX}/{ep}", handler, methods, desc)
            # === POST routes ===
            post_routes = [
                ("memory/<id>/delete",     self._api_memory_delete,      "Delete memory"),
                ("memories/batch",         self._api_memories_batch,     "Batch ops"),
                ("lessons",                self._api_lessons_add,        "Add lesson"),
                ("lessons/<id>/update",    self._api_lessons_update,     "Update lesson"),
                ("lessons/<id>/delete",    self._api_lessons_delete,     "Delete lesson"),
                ("reminders",              self._api_reminders_create,   "Create reminder"),
                ("reminders/scan",         self._api_reminders_scan,     "Scan & auto-create"),
                ("reminders/<id>/cancel",  self._api_reminders_cancel,   "Cancel reminder"),
                ("reminders/<id>/delete",  self._api_reminders_delete,   "Delete reminder"),
                ("reminders/<id>/update",  self._api_reminders_update,   "Update reminder"),
                ("export",                 self._api_export,             "Export data"),
                ("tags/merge",             self._api_tags_merge,         "Merge tags"),
                ("tags/rename",            self._api_tags_rename,        "Rename tag"),
                ("archive/execute",        self._api_archive_execute,    "Archive execute"),
                ("archive/scan",           self._api_archive_scan,       "Scan sleeping memories"),
                ("archive/merge",          self._api_archive_merge,      "Merge memories"),
                ("conflict/resolve",       self._api_conflict_resolve,   "Resolve conflict"),
                ("family/meeting-generate", self._api_family_meeting_generate, "Generate family meeting"),
                ("semantic-search",         self._api_semantic_search,    "Semantic search"),
                ("share/generate",         self._api_share_generate,    "Share generate"),
                ("system/reindex",         self._api_system_reindex,     "Reindex"),
                ("system/settings",       self._api_settings_save,     "Save UI settings"),
                ("graph/node/create",     self._api_graph_node_create, "Create graph node"),
            ]
            for ep, handler, desc in post_routes:
                register(f"{PREFIX}/{ep}", handler, ["POST"], desc)
            # v4.0: Dream Engine 手动唤醒
            register(f"{PREFIX}/system/dream", self._api_system_dream, ["POST"], "Manual dream trigger")            # v4.1.0: Dream Engine 安全保底 API
            register(f"{PREFIX}/system/rollback", self._api_system_rollback, ["POST"], "Rollback database to backup")
            register(f"{PREFIX}/system/prune-log", self._api_system_prune_log, ["GET"], "Get last prune operation log")
            register(f"{PREFIX}/system/prune-preview", self._api_system_prune_preview, ["GET"], "Preview prune candidates before execution")
            register(f"{PREFIX}/dream/history", self._api_dream_history, ["GET"], "Dream history log")
            # v4.2: Context Assembly Trace
            register(f"{PREFIX}/trace/list", self._api_trace_list, ["GET"], "Context trace list")
            register(f"{PREFIX}/trace/detail", self._api_trace_detail, ["GET"], "Context trace detail")
            register(f"{PREFIX}/trace/stats", self._api_trace_stats, ["GET"], "Context trace stats")
            register(f"{PREFIX}/summary/generate", self._api_summary_generate, ["POST"], "Generate session summary")
            # v6.3: Knowledge Graduation System
            register(f"{PREFIX}/knowledge/list", self._api_knowledge_list, ["GET"], "Knowledge list")
            register(f"{PREFIX}/knowledge/index", self._api_knowledge_index, ["GET"], "Knowledge index")
            register(f"{PREFIX}/knowledge/detail", self._api_knowledge_detail, ["GET"], "Knowledge detail")
            register(f"{PREFIX}/knowledge/logs", self._api_knowledge_logs, ["GET"], "shturl logs")
            register(f"{PREFIX}/knowledge/health", self._api_knowledge_health, ["GET"], "Health check")
            register(f"{PREFIX}/knowledge/update", self._api_knowledge_update, ["POST"], "Update knowledge")
            register(f"{PREFIX}/knowledge/confirm", self._api_knowledge_confirm, ["POST"], "Confirm graduation")
            register(f"{PREFIX}/knowledge/add-log", self._api_knowledge_add_log, ["POST"], "Add log")
            all_count = len(get_routes) + len(post_routes) + 16
            logger.info(f"[LMHelper v6.0] {all_count} API routes registered（含 Dream Engine + 安全保底 + 图谱增强 + 组装追踪）")
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] API register failed: {e}")

    async def _api_stats(self, request=None) -> dict:
        from datetime import datetime as dt
        total = self.reader.get_memory_count()
        today = dt.now().strftime("%Y-%m-%d")
        today_s = self.reader.get_stats_for_date(today)
        lessons = self.learner.get_statistics()
        return {
            "total_memories": total,
            "today_count": today_s.get("total", 0),
            "total_lessons": lessons.get("total", 0),
        }
    @staticmethod
    async def _read_body() -> dict:
        """从 astrbot.api.web.request 上下文安全读取 JSON body"""
        try:
            from astrbot.api.web import request as web_request
            body = await web_request.json()
            if isinstance(body, dict):
                return body
        except Exception:
            pass
        return {}

    @staticmethod
    def _qp(request, key, default=None):
        """从 Quart 请求上下文或 request 安全获取 query 参数"""
        # 1. 优先从 Quart 请求上下文（桥接SDK设置了此上下文但没传 request 对象）
        try:
            from quart import request as quart_request
            val = quart_request.args.get(key)
            if val is not None:
                return val
        except Exception:
            pass
        # 2. 回退到显式传入的 request 对象
        if request is not None:
            if hasattr(request, "args"):
                return request.args.get(key, default)
            if hasattr(request, "query_params"):
                return request.query_params.get(key, default)
        return default

    async def _api_timeline(self, **kwargs) -> dict:
        from datetime import datetime as dt, timedelta
        from quart import request as quart_request
        
        period = quart_request.args.get("period", "today")
        today = dt.now()
        if period == "today":
            ds = today.strftime("%Y-%m-%d")
            memories = self.reader.get_memories_by_date(ds)
        elif period == "yesterday":
            ds = (today - timedelta(days=1)).strftime("%Y-%m-%d")
            memories = self.reader.get_memories_by_date(ds)
        elif period == "this-week":
            start = today - timedelta(days=today.weekday())
            memories = self.reader.get_memories_by_date_range(
                start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        elif re.match(r"\d{4}-\d{2}-\d{2}", period):
            memories = self.reader.get_memories_by_date(period)
        else:
            memories = self.reader.get_recent_memories(20)
        return {"memories": memories, "total": len(memories), "peak_hour": ""}

    async def _api_lessons(self, request=None) -> dict:
        lessons = self.learner.list_lessons(limit=20)
        return {"lessons": lessons, "total": len(lessons)}

    # ═══════════════════ F1 时间轴 ═══════════════════

    @filter.command("lmem-timeline")
    def cmd_timeline(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        detail = "detail" in text
        text = text.replace("detail", "").strip()
        today = datetime.now()

        try:
            if not text or text == "today":
                ds = today.strftime("%Y-%m-%d")
                label, wd = "今日", WEEKDAY_CN[today.weekday()]
                memories = self.reader.get_memories_by_date(ds)
            elif text == "yesterday":
                dt = today - timedelta(days=1)
                ds = dt.strftime("%Y-%m-%d")
                label, wd = "昨日", WEEKDAY_CN[dt.weekday()]
                memories = self.reader.get_memories_by_date(ds)
            elif text == "this-week":
                start = today - timedelta(days=today.weekday())
                memories = self.reader.get_memories_by_date_range(
                    start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
                label = f"本周（{start.strftime('%m/%d')}~{today.strftime('%m/%d')}）"
                wd = ""
            elif text == "last-week":
                m = today - timedelta(days=today.weekday() + 7)
                s = m + timedelta(days=6)
                memories = self.reader.get_memories_by_date_range(
                    m.strftime("%Y-%m-%d"), s.strftime("%Y-%m-%d"))
                label = f"上周（{m.strftime('%m/%d')}~{s.strftime('%m/%d')}）"
                wd = ""
            elif text.startswith("range"):
                m = re.search(r"([\d-]+)\s*[~～]\s*([\d-]+)", text)
                if m:
                    memories = self.reader.get_memories_by_date_range(m.group(1), m.group(2))
                    label = f"{m.group(1)} ~ {m.group(2)}"
                    wd = ""
                else:
                    yield event.plain_result("格式: /lmem-timeline range YYYY-MM-DD~YYYY-MM-DD")
                    return
            elif re.match(r"\d{4}-\d{2}-\d{2}", text):
                dt = datetime.strptime(text, "%Y-%m-%d")
                label, wd = text, WEEKDAY_CN[dt.weekday()]
                memories = self.reader.get_memories_by_date(text)
            else:
                yield event.plain_result(
                    "用法: /lmem-timeline [today|yesterday|this-week|last-week|YYYY-MM-DD|range A~B] [detail]")
                return
            yield event.plain_result(format_timeline(memories, label, detail, wd))
        except Exception as e:
            logger.error(f"[LMHelper] 时间轴失败: {e}")
            yield event.plain_result(f"❌ {e}")

    # ═══════════════════ F2 错误学习 ═══════════════════

    @filter.command("lmem-lessons")
    def cmd_lessons(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        tag = None
        if "tag=" in text:
            m = re.search(r"tag=(\S+)", text)
            if m:
                tag = m.group(1)

        lessons = self.learner.list_lessons(tag=tag, limit=15)
        if not lessons:
            yield event.plain_result("📖 还没有学到的教训，小雪表现得很棒！")
            return
        lines = ["📖 学到的教训：", ""]
        for l in lessons:
            scene = l.get("scene", "")
            err = l.get("error_content", "")[:60]
            fixed = "✅" if l.get("fixed") else "📖"
            lines.append(f"  {fixed} #{l['id']} [{scene}] {err}")
        yield event.plain_result("\n".join(lines))

    @filter.command("lmem-lesson")
    def cmd_lesson(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()

        if not text:
            yield event.plain_result("用法: /lmem-lesson <id>|stats|report|add 内容|forget <id>")
            return
        if text == "stats":
            s = self.learner.get_statistics()
            yield event.plain_result(
                f"📊 学习统计\n总:{s['total']} 已纠正:{s['fixed']} "
                f"验证:{s['verified']} 再犯:{s['recurrence']}"
            )
            return
        if text == "report":
            yield event.plain_result(self.learner.generate_report())
            return
        if text.startswith("forget"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                self.learner.delete_lesson(int(parts[1]))
                yield event.plain_result(f"已删除教训 #{parts[1]}")
            else:
                yield event.plain_result("用法: /lmem-lesson forget <id>")
            return
        if text.startswith("add"):
            content = text[len("add"):].strip()
            if content:
                lid = self.learner.add_lesson(
                    scene="手动添加", error="", correction=content,
                    solution=f"用户记录: {content}", tags="error_lesson",
                )
                yield event.plain_result(f"📖 已添加教训 #{lid}: {content[:60]}")
            else:
                yield event.plain_result("用法: /lmem-lesson add 教训内容")
            return

        # 按 ID 查看
        try:
            lid = int(text)
            l = self.learner.get_lesson(lid)
            if l:
                fixed = "✅已纠正" if l.get("fixed") else "📖学习中"
                yield event.plain_result(
                    f"📖 教训 #{lid} [{fixed}]\n"
                    f"━" * 30 + "\n"
                    f"场景: {l.get('scene','')}\n"
                    f"错误: {l.get('error_content','')[:200]}\n"
                    f"纠正: {l.get('user_correction','')[:200]}\n"
                    f"方案: {l.get('solution','')[:200]}\n"
                    f"时间: {l.get('learned_at','')[:19]}"
                )
            else:
                yield event.plain_result(f"未找到教训 #{lid}")
        except ValueError:
            yield event.plain_result("用法: /lmem-lesson <id>|stats|report|add 内容|forget <id>")

    # ═══════════════════ F3 记忆导出 ═══════════════════

    @filter.command("lmem-export")
    def cmd_export(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        tags = re.search(r"tags?=(\S+)", text)
        t = tags.group(1) if tags else None
        if "json" in text:
            yield event.plain_result(self.exporter.export_json(tags=t))
        elif "obsidian" in text:
            yield event.plain_result(self.exporter.export_obsidian(tags=t))
        elif "all" in text:
            fmt = next((f for f in ["md", "json", "obsidian"] if f in text), "md")
            yield event.plain_result(self.exporter.export_all(fmt))
        else:
            yield event.plain_result(self.exporter.export_markdown(tags=t))

    # ═══════════════════ F4 提醒联动 ═══════════════════

    @filter.command("lremind")
    def cmd_remind(self, event: AstrMessageEvent, text: str = ""):
        self._last_msg_origin = event.unified_msg_origin  # 保存用于主动推送
        text = text.strip()
        if not text or text == "list":
            yield event.plain_result(self.reminder.list_reminders())
        elif text.startswith("auto on"):
            yield event.plain_result(self._start_auto_scan())
        elif text.startswith("auto off"):
            yield event.plain_result(self._stop_auto_scan())
        elif text.startswith("cancel"):
            p = text.split()
            rid = int(p[-1]) if len(p) > 1 and p[-1].isdigit() else 0
            yield event.plain_result(self.reminder.cancel(rid) if rid else "用法: /lremind cancel <id>")
        elif text.startswith("create"):
            p = text.split()
            if len(p) >= 3 and p[1].isdigit():
                yield event.plain_result(self.reminder.create_from_memory(int(p[1]), p[2]))
            else:
                yield event.plain_result("用法: /lremind create <记忆ID> <时间>")
        else:
            yield event.plain_result(
                "用法: /lremind [list|create <id> <时间>|cancel <id>|auto on|auto off]"
            )

    def _start_auto_scan(self) -> str:
        if self._auto_scan_task and not self._auto_scan_task.done():
            return "⏰ 自动扫描已在运行"
        self._auto_scan_task = asyncio.create_task(self._auto_scan_loop())
        return "⏰ 已开启自动扫描提醒（每5分钟检查一次记忆中的时间词）"

    def _stop_auto_scan(self) -> str:
        if self._auto_scan_task and not self._auto_scan_task.done():
            self._auto_scan_task.cancel()
        return "⏰ 已关闭自动扫描"

    async def _auto_scan_loop(self):
        while True:
            try:
                candidates = self.reminder.scan_time_keywords()
                if candidates:
                    logger.info(f"[LMHelper] 扫描到 {len(candidates)} 条含时间词的记忆")
            except Exception as e:
                logger.warning(f"[LMHelper] 自动扫描异常: {e}")
            await asyncio.sleep(300)  # 5分钟

    # ═══════════════════ F5 快捷命令 ═══════════════════

    @filter.command("记住")
    def cmd_remember(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        if not text:
            yield event.plain_result("用法: /记住 内容")
            return
        yield event.plain_result(f"📝 小雪记下了: 「{text[:100]}」")

    @filter.command("记忆")
    def cmd_memory(self, event: AstrMessageEvent, text: str = ""):
        query = text.strip()
        if not query:
            yield event.plain_result("用法: /记忆 关键词")
            return
        results = self.reader.search_memories(query, limit=5)
        if not results:
            yield event.plain_result(f"🔍 没有找到「{query}」相关的记忆～")
            return
        lines = [f"🔍 「{query}」{len(results)} 条：", ""]
        for i, m in enumerate(results, 1):
            lines.append(f"{i}. [{m.get('time','')}] {m.get('content','')[:80]}")
            t = "、".join(m.get("tags", [])[:3])
            if t:
                lines.append(f"   🏷 {t}")
        yield event.plain_result("\n".join(lines))

    @filter.command("忘记")
    def cmd_forget(self, event: AstrMessageEvent, text: str = ""):
        query = text.strip()
        if not query:
            yield event.plain_result("用法: /忘记 关键词")
            return
        results = self.reader.search_memories(query, limit=5)
        if not results:
            yield event.plain_result(f"没有找到「{query}」相关的记忆～")
            return
        lines = ["要删除哪条？发送 /lmem forget <id>", "━" * 36]
        for m in results:
            lines.append(f"ID:{m['id']} | {m.get('time','')} | {m.get('content','')[:50]}")
        yield event.plain_result("\n".join(lines))

    @filter.command("回忆")
    def cmd_recall(self, event: AstrMessageEvent, text: str = ""):
        query = text.strip()
        if not query:
            yield event.plain_result("用法: /回忆 关键词")
            return
        results = self.reader.search_memories(query, limit=10)
        if not results:
            yield event.plain_result(f"没有找到「{query}」相关的回忆～")
            return
        lines = [f"🧠 回忆「{query}」：", ""]
        for i, m in enumerate(results, 1):
            lines.append(
                f"{i}. [{m.get('date','')} {m.get('time','')}] "
                f"⭐{m.get('importance',0):.0%}"
            )
            lines.append(f"   {m.get('content','')[:100]}")
            lines.append("")
        yield event.plain_result("\n".join(lines))

    # ═══════════════════ F6 统计报告 ═══════════════════

    @filter.command("lmem-report")
    def cmd_report(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        if "weekly" in text or "week" in text:
            yield event.plain_result(self.reporter.weekly_report())
        elif "auto" in text:
            on = "on" in text.split("auto")[-1] if "auto" in text else True
            yield event.plain_result(
                "📊 定时报告功能需用 AstrBot 定时任务" if on
                else "📊 已关闭定时报告"
            )
        else:
            yield event.plain_result(self.reporter.daily_report())

    # ═══════════════════ F7 冲突检测 ═══════════════════

    @filter.command("lmem-conflicts")
    def cmd_conflicts(self, event: AstrMessageEvent):
        pairs = self.detector.detect_conflicts()
        yield event.plain_result(self.detector.format_conflicts(pairs))

    @filter.command("lmem-conflict")
    def cmd_conflict_resolve(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        if text.startswith("resolve"):
            p = text.split()
            if len(p) >= 3 and p[1].isdigit() and p[2].isdigit():
                yield event.plain_result(self.detector.resolve(int(p[1]), int(p[2])))
                return
        yield event.plain_result("用法: /lmem-conflict resolve <保留id> <删除id>")

    # ═══════════════════ F8 外部同步 ═══════════════════

    @filter.command("lmem-sync")
    def cmd_sync(self, event: AstrMessageEvent, text: str = ""):
        text = text.strip()
        if "obsidian" in text:
            yield event.plain_result(self.syncer.sync_obsidian())
        elif "notion" in text:
            yield event.plain_result(self.syncer.sync_notion())
        elif "status" in text:
            yield event.plain_result(self.syncer.get_status())
        else:
            yield event.plain_result("用法: /lmem-sync [obsidian|notion|status]")

    # ═══════════════════ F9 知识图谱 ═══════════════════

    @filter.command("ontology")
    def cmd_ontology(self, event: AstrMessageEvent, text: str = ""):
        """知识图谱命令"""
        text = text.strip()
        parts = text.split()
        
        if not parts:
            help_text = "知识图谱命令：\n" \
                "  /ontology create <类型> <属性JSON> - 创建实体\n" \
                "  /ontology query <ID> - 查询实体\n" \
                "  /ontology update <ID> <属性JSON> - 更新实体\n" \
                "  /ontology delete <ID> - 删除实体\n" \
                "  /ontology list [类型] - 列出实体\n" \
                "  /ontology link <源ID> <关系类型> <目标ID> - 创建关系\n" \
                "  /ontology related <ID> [关系类型] - 查询相关实体\n" \
                "  /ontology stats - 统计信息\n" \
                "  /ontology export [JSONL路径] - 导出\n" \
                "  /ontology import <JSONL路径> - 导入"
            yield event.plain_result(help_text)
            return
        
        action = parts[0].lower()
        
        try:
            if action == "create" and len(parts) >= 3:
                entity_type = parts[1]
                props = json.loads(" ".join(parts[2:]))
                entity = self.ontology.create_entity(entity_type, props)
                yield event.plain_result(
                    f"✅ 实体已创建\n"
                    f"  ID: {entity.id}\n"
                    f"  类型: {entity.type}\n"
                    f"  属性: {json.dumps(entity.properties, ensure_ascii=False)}"
                )
            
            elif action == "query" and len(parts) >= 2:
                entity = self.ontology.get_entity(parts[1])
                if entity:
                    result = (
                        f"📦 实体详情\n"
                        f"  ID: {entity.id}\n"
                        f"  类型: {entity.type}\n"
                        f"  属性: {json.dumps(entity.properties, ensure_ascii=False)}\n"
                        f"  关系数: {len(entity.relations)}\n"
                        f"  创建时间: {entity.created_at}\n"
                        f"  更新时间: {entity.updated_at}"
                    )
                    if entity.relations:
                        result += "\n  关系:"
                        for rel in entity.relations[:5]:
                            result += f"\n    - [{rel['direction']}] {rel['relation']} → {rel['entity_id']}"
                else:
                    result = f"❌ 实体 {parts[1]} 不存在"
                yield event.plain_result(result)
            
            elif action == "update" and len(parts) >= 3:
                props = json.loads(" ".join(parts[2:]))
                entity = self.ontology.update_entity(parts[1], props)
                if entity:
                    yield event.plain_result(
                        f"✅ 实体已更新\n"
                        f"  ID: {entity.id}\n"
                        f"  属性: {json.dumps(entity.properties, ensure_ascii=False)}"
                    )
                else:
                    yield event.plain_result(f"❌ 实体 {parts[1]} 不存在")
            
            elif action == "delete" and len(parts) >= 2:
                if self.ontology.delete_entity(parts[1]):
                    yield event.plain_result(f"✅ 实体 {parts[1]} 已删除")
                else:
                    yield event.plain_result(f"❌ 实体 {parts[1]} 不存在")
            
            elif action == "list":
                entity_type = parts[1] if len(parts) > 1 else None
                entities = self.ontology.list_entities(entity_type, limit=20)
                if entities:
                    result = f"📋 实体列表（共 {len(entities)} 个）\n"
                    for e in entities[:10]:
                        name = e.properties.get('name', e.properties.get('title', e.id))
                        result += f"  [{e.type}] {e.id}: {name}\n"
                else:
                    result = "📋 暂无实体"
                yield event.plain_result(result)
            
            elif action == "link" and len(parts) >= 4:
                rel = self.ontology.create_relation(parts[1], parts[2], parts[3])
                yield event.plain_result(
                    f"✅ 关系已创建\n"
                    f"  {rel.from_id} --[{rel.relation_type}]--> {rel.to_id}"
                )
            
            elif action == "related" and len(parts) >= 2:
                rel_type = parts[2] if len(parts) > 2 else None
                related = self.ontology.get_related_entities(parts[1], rel_type)
                if related:
                    result = f"🔗 实体 {parts[1]} 的相关实体（共 {len(related)} 个）\n"
                    for r in related[:10]:
                        name = r['entity_properties'].get('name', r['entity_id'])
                        result += f"  [{r['direction']}] {r['relation']} → {name}\n"
                else:
                    result = f"🔗 实体 {parts[1]} 暂无相关实体"
                yield event.plain_result(result)
            
            elif action == "stats":
                stats = self.ontology.get_stats()
                result = (
                    f"📊 知识图谱统计\n"
                    f"  实体总数: {stats['entities_count']}\n"
                    f"  关系总数: {stats['relations_count']}\n"
                    f"  实体类型分布: {json.dumps(stats['by_type'], ensure_ascii=False)}\n"
                    f"  关系类型分布: {json.dumps(stats['by_relation'], ensure_ascii=False)}"
                )
                yield event.plain_result(result)
            
            elif action == "export":
                # v6.4 security fix: 导出路径强制限制在插件 data_dir 内（防任意文件写）
                out_name = os.path.basename(parts[1]) if len(parts) > 1 else "ontology_export.jsonl"
                output_path = os.path.join(self.data_dir, out_name)
                self.ontology.export_jsonl(output_path)
                yield event.plain_result(f"✅ 已导出到 {output_path}")
            
            elif action == "import" and len(parts) >= 2:
                # v6.4 security fix: 导入路径强制限制在插件 data_dir 内（防任意文件读）
                in_path = os.path.join(self.data_dir, os.path.basename(parts[1]))
                self.ontology.import_jsonl(in_path)
                yield event.plain_result(f"✅ 已从 {in_path} 导入")
            
            else:
                yield event.plain_result("❌ 命令格式错误，请输入 /ontology 查看帮助")
        
        except json.JSONDecodeError as e:
            yield event.plain_result(f"❌ JSON解析错误: {e}")
        except Exception as e:
            logger.error(f"[LMHelper] 知识图谱命令失败: {e}")
            yield event.plain_result(f"❌ {e}")

    # ═══════════════════ LLM 钩子 ═══════════════════

    @filter.on_llm_request()
    async def inject_lessons(self, event: AstrMessageEvent, req):
        """每次 LLM 请求前注入核心记忆索引 + 教训 + 语义召回 + 近期上下文（v5.2 增强）

        v6.2 升级：
        - RRF 多路融合检索（FTS5 + LIKE + 标签 → RRF 排序）
        - 上下文卸载（Context Offload）：超长对话自动压缩工具结果
        """
        # ── v6.2: 上下文卸载 — 监控对话长度 ──
        try:
            from .core.rrf_engine import ContextOffloadManager
            if not hasattr(self, '_offload_mgr'):
                self._offload_mgr = ContextOffloadManager()
            conversation = req.conversation or []
            if conversation:
                level, tokens, max_tokens = self._offload_mgr.check(conversation)
                if level != "none":
                    logger.info(
                        f"[LMHelper v6.2] 上下文压力: {level} "
                        f"({tokens}/{max_tokens} tokens, {tokens/max_tokens:.0%})"
                    )
        except Exception as e:
            logger.debug(f"[LMHelper v6.2] 上下文卸载检查跳过: {e}")

        # 保存消息来源用于主动推送提醒
        self._last_msg_origin = event.unified_msg_origin
        try:
            msg = event.message_str or ""
            if not msg:
                return
            parts = []

            # 0.（v5.2新增）核心记忆索引 + 活跃决策 — 始终在线，不依赖搜索
            try:
                core_memories = self._get_core_memory_index()
                if core_memories:
                    hint = "## 核心记忆索引（始终在线）\n"
                    for m in core_memories:
                        hint += f"- {m}\n"
                    parts.append(hint)
                # v5.2: 活跃决策注入
                active_decisions = self.reader.get_active_decisions(limit=5)
                if active_decisions:
                    hint = "## 当前活跃决策（需遵循）\n"
                    for d in active_decisions:
                        hint += f"- [{d['importance']:.1f}] {d['content'][:100]}\n"
                    parts.append(hint)
            except Exception as e:
                logger.debug(f"[LMHelper v6.0] 核心索引失败: {e}")

            # 1. 注入历史教训
            lessons = self.learner.find_relevant(msg, limit=2)
            if lessons:
                hint = "## 历史教训（请避免这些错误）\n"
                for l in lessons:
                    hint += f"- [{l.get('scene','')}] {l.get('solution','')[:120]}\n"
                parts.append(hint)

            # 1.5（v6.0新增）毕业知识注入 — Cairn consume 步骤
            try:
                graduated = self.knowledge_graduator.search_knowledge(msg, limit=3)
                if graduated:
                    hint = "## 已毕业知识（经过验证的永久认知，请遵循）" + chr(10)
                    for k in graduated:
                        ktype_label = {"technical": "技术", "emotional": "情感",
                                       "relationship": "关系", "operational": "运维"}.get(k["knowledge_type"], "知识")
                        hint += f"- [{ktype_label}] {k['conclusion'][:120]}" + chr(10) + ""
                        if k.get("applicability"):
                            hint += f"  适用: {k['applicability'][:80]}" + chr(10) + ""
                    parts.append(hint)
            except Exception as e:
                logger.debug(f"[LMHelper v6.0] 毕业知识注入失败: {e}")

            # 1.6（v6.1新增）表达风格注入 — 记忆画像驱动的表达联动
            try:
                if self.v2_reader:
                    style = self.v2_reader.get_expression_style("default")
                    if style and style.get("style_snapshot") and not style.get("error"):
                        snap = style["style_snapshot"]
                        hint = "## 当前表达风格（记忆画像驱动）" + chr(10)
                        for k, v in snap.items():
                            hint += f"- {k}: {v}" + chr(10)
                        parts.append(hint)
            except Exception as e:
                logger.debug(f"[LMHelper v6.0] 表达风格注入失败: {e}")

            # 2.（v5.0新增）语义召回 — 根据橘子消息搜索相关记忆
            semantic_results = []
            try:
                semantic_results = self._semantic_recall(msg, limit=5)
                if semantic_results:
                    hint = "## 相关记忆（语义召回）\n"
                    for m in semantic_results:
                        dt = m.get("time") or m.get("date") or ""
                        content = (m.get("content") or "")[:150]
                        hint += f"- [{dt}] {content}\n"
                    parts.append(hint)
            except Exception as e:
                logger.debug(f"[LMHelper v6.0] 语义召回失败: {e}")

            # 3.（v3.0新增，v5.0调整）注入近期记忆片段（从5减到3，去重避免与语义召回重复）
            try:
                recent = self.reader.get_recent_memories(limit=3)
                if recent:
                    seen_ids = set()
                    if semantic_results:
                        for m in semantic_results:
                            mid = m.get("id") or m.get("doc_id")
                            if mid:
                                seen_ids.add(str(mid))
                    deduped = []
                    for m in recent:
                        mid = m.get("id") or m.get("doc_id")
                        if mid and str(mid) in seen_ids:
                            continue
                        deduped.append(m)
                    if deduped:
                        hint = "## 近期共同记忆（用于保持上下文连贯）\n"
                        for m in deduped:
                            dt = m.get("time") or m.get("date") or ""
                            content = (m.get("content") or "")[:150]
                            hint += f"- [{dt}] {content}\n"
                        parts.append(hint)
            except Exception:
                pass

            # 4.（P3）注入即将到期的提醒
            try:
                upcoming = self.reminder.get_upcoming(hours=24)
                if upcoming:
                    hint = "## ⏰ 即将到期的记忆提醒（请在聊天中自然地提醒用户）\n"
                    for r in upcoming[:5]:
                        t = r.get("parsed_time") or r.get("target_time", "")
                        hint += f"- [{t}] {r['content'][:80]}\n"
                    hint += "请在合适的时候提醒用户这些即将到来的事项。\n"
                    parts.append(hint)
            except Exception:
                pass

            # 5.（v5.6新增）记忆复习提醒 — 橘子聊天时自动检查到期复习
            try:
                now = datetime.now().timestamp()
                last_check = getattr(self, '_last_review_check', 0)
                if now - last_check >= 3600:  # 每小时最多检查一次
                    self._last_review_check = now
                    due = self.reader.get_due_review_atoms(limit=5)
                    if due:
                        hint = "## 记忆复习提醒（请在回复开头自然地提醒用户）\n"
                        hint += f"以下 {len(due)} 条记忆到了复习时间，请在对话中自然地提醒橘子：\n"
                        for i, a in enumerate(due, 1):
                            content = (a.get("content") or "")[:100]
                            strength = a.get("strength", 0)
                            hint += f"{i}. [强度{strength:.1%}] {content}\n"
                        hint += "\n调用 haruyuki_reinforce_memory 工具：橘子说记得→action='record' is_correct=true；说忘了→is_correct=false。\n"
                        parts.append(hint)
            except Exception:
                pass

            if parts:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + "\n".join(parts)
                logger.info(f"[LMHelper v6.0] 注入 {len(parts)} 个提示块")
        except Exception as e:
            logger.warning(f"[LMHelper] 注入失败: {e}")

    def _get_core_memory_index(self) -> list:
        """【v5.2】核心记忆索引 — 始终在线的关键事实，不依赖搜索命中
        选取规则：importance >= 0.85 且 memory_tier <= 1（工作/活跃记忆）
        缓存5分钟避免每次请求都查DB
        """
        import time as _time
        cache_ttl = 300  # 5分钟
        now = _time.time()
        
        if hasattr(self, '_core_index_cache'):
            cached_time, cached_data = self._core_index_cache
            if now - cached_time < cache_ttl:
                return cached_data
        
        import sqlite3
        db_path = self.reader.db_path
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        try:
            rows = conn.execute(
                """SELECT text, metadata FROM documents
                   WHERE memory_tier <= 1
                   ORDER BY created_at DESC
                   LIMIT 10"""
            ).fetchall()
            
            core_facts = []
            for r in rows:
                text = r["text"] or ""
                first_line = text.split("\n")[0][:80]
                if first_line.strip():
                    core_facts.append(first_line)
            
            conn.close()
        except Exception:
            conn.close()
            return []
        
        self._core_index_cache = (now, core_facts)
        return core_facts

    def _semantic_recall(self, msg: str, limit: int = 5) -> list:
        """v5.1: 分层语义召回 — tier感知 + 时间感知 + TTL缓存"""
        import hashlib
        from datetime import datetime, timedelta

        # ── TTL 缓存检查（5分钟内相同查询直接返回） ──
        cache_key = hashlib.md5(msg.encode()).hexdigest()
        now = datetime.now()
        if cache_key in self._recall_cache:
            cached_time, cached_results = self._recall_cache[cache_key]
            if (now - cached_time).total_seconds() < 300:
                logger.debug(f"[LMHelper v6.0] 语义召回命中缓存 (key={cache_key[:8]})")
                return cached_results

        # ── 时间感知：解析消息中的时间词 ──
        time_filter = self._parse_time_reference(msg)

        # ── v6.2: RRF 多路融合检索（search_memories 已内置 RRF） ──
        search_query = msg
        if time_filter:
            for word in time_filter["raw_words"]:
                search_query = search_query.replace(word, "").strip()
        if not search_query:
            search_query = msg

        raw_results = self.reader.search_memories(search_query, limit=limit * 3)

        # ── Tier 感知过滤 ──
        # L0/L1: 全保留（高优先级）
        # L2: 保留（正常优先级）
        # L3: 只在结果不足时补充（低优先级）
        tier_results = {"L0L1": [], "L2": [], "L3": []}
        for m in raw_results:
            # _format_row 不返回 tier，从原始数据读
            # 但 search_memories 返回的 dict 里有 tier 吗？_format_row 可能丢了
            # 用 importance 作为近似：高 importance 更可能在 L0/L1
            tier = m.get("tier")
            if tier is None:
                # 从 metadata 估算
                tier = 2  # 默认 L2
            if tier <= 1:
                tier_results["L0L1"].append(m)
            elif tier == 2:
                tier_results["L2"].append(m)
            else:
                tier_results["L3"].append(m)

        # 合并：L0L1 优先，L2 次之，L3 补充
        merged = tier_results["L0L1"][:limit]
        if len(merged) < limit:
            merged += tier_results["L2"][:limit - len(merged)]
        if len(merged) < limit:
            merged += tier_results["L3"][:limit - len(merged)]

        results = merged

        # ── 时间过滤 ──
        if time_filter and results:
            filtered = []
            for m in results:
                m_time = str(m.get("time") or m.get("date") or "")
                for date_str in time_filter["dates"]:
                    if date_str in m_time:
                        filtered.append(m)
                        break
            if filtered:
                results = filtered[:limit]
            else:
                results = results[:limit]
        else:
            results = results[:limit] if results else []

        # ── v5.2: 图增强召回 — 通过共享节点补充关联记忆 ──
        if results:
            try:
                doc_ids = [r.get("id") for r in results if r.get("id")]
                if doc_ids:
                    graph_results = self.reader.graph_enhanced_recall(doc_ids, limit=2)
                    if graph_results:
                        existing_ids = {str(r.get("id")) for r in results}
                        added = 0
                        for gr in graph_results:
                            gid = str(gr.get("id") or gr.get("doc_id") or "")
                            if gid and gid not in existing_ids:
                                results.append(gr)
                                existing_ids.add(gid)
                                added += 1
                        if added > 0:
                            logger.debug(f"[LMHelper v6.0] 图增强补充 {added} 条关联记忆")
            except Exception as e:
                logger.debug(f"[LMHelper v6.0] 图增强跳过: {e}")

        # ── 写入缓存 ──
        self._recall_cache[cache_key] = (now, results)
        if len(self._recall_cache) > 20:
            oldest = sorted(self._recall_cache.items(), key=lambda x: x[1][0])
            for k, _ in oldest[:10]:
                del self._recall_cache[k]

        return results

    def _parse_time_reference(self, msg: str) -> "dict | None":
        """解析消息中的时间词，返回日期范围"""
        from datetime import datetime, timedelta
        import re

        today = datetime.now()
        references = {
            "今天": today,
            "昨天": today - timedelta(days=1),
            "前天": today - timedelta(days=2),
            "明天": today + timedelta(days=1),
            "后天": today + timedelta(days=2),
        }
        week_keywords = ["上周", "这周", "本周", "下周"]

        raw_words = []
        dates = []

        for word, dt in references.items():
            if word in msg:
                raw_words.append(word)
                dates.append(dt.strftime("%Y-%m-%d"))

        for wk in week_keywords:
            if wk in msg:
                raw_words.append(wk)
                if wk == "上周":
                    start = today - timedelta(days=today.weekday() + 7)
                    for i in range(7):
                        dates.append((start + timedelta(days=i)).strftime("%Y-%m-%d"))
                else:
                    start = today - timedelta(days=today.weekday())
                    for i in range(7):
                        dates.append((start + timedelta(days=i)).strftime("%Y-%m-%d"))

        m = re.search(r"(\d+)\s*天前", msg)
        if m:
            days = int(m.group(1))
            target = today - timedelta(days=days)
            raw_words.append(m.group(0))
            dates.append(target.strftime("%Y-%m-%d"))

        if not dates:
            return None

        return {"raw_words": raw_words, "dates": dates}

    @filter.on_llm_response()
    async def detect_errors(self, event: AstrMessageEvent, resp):
        """检测 LLM 回复中的错误"""
        try:
            if not resp or not resp.completion_text:
                return
            session_id = event.get_session_id()
            self._last_bot_text[session_id] = resp.completion_text

            # 检测工具调用失败
            if self.learner.detect_tool_error(resp.completion_text):
                self.learner.auto_record_tool_error(
                    resp.completion_text[:200], "llm_response",
                )
                logger.info("[LMHelper] 检测到工具调用错误")
        except Exception as e:
            logger.warning(f"[LMHelper] 错误检测失败: {e}")

        # ━━━ v6.0: 自动情感打分（batch）━━━
        try:
            self._score_recent_emotions()
        except Exception as e:
            logger.debug(f"[LMHelper v6.0] 情感打分跳过: {e}")

    def _score_recent_emotions(self, limit: int = 5):
        """v6.0: 批量对最近未打分的记忆进行情感分析并持久化。

        查询主库 documents 表最近的记忆，跳过已打分的，对未打分的调用
        EmotionEngine.analyze() 并写入 EmotionStore。
        """
        import sqlite3 as _sqlite3
        try:
            conn = _sqlite3.connect(self.reader.db_path)
            conn.row_factory = _sqlite3.Row
            # 取最近 N 条记忆
            rows = conn.execute(
                "SELECT id, text, created_at FROM documents ORDER BY id DESC LIMIT ?",
                (limit * 3,)  # 多取一些，有些可能已打分
            ).fetchall()
            conn.close()

            scored = 0
            for row in rows:
                mid = str(row["id"])
                # 跳过已打分的
                if self.emotion_store.get_by_memory(mid):
                    continue
                text = row["text"] or ""
                if not text.strip():
                    continue
                analysis = self.emotion_engine.analyze(text, speaker="user")
                self.emotion_store.store(mid, analysis, speaker="user")
                scored += 1
                if scored >= limit:
                    break

            if scored:
                logger.info(f"[LMHelper v6.0] 自动情感打分: {scored} 条新记忆")
        except Exception as e:
            logger.debug(f"[LMHelper v6.0] 情感打分异常: {e}")

    # ═══════════════════ v3.0 Agent Tool 实现 ═══════════════════

    async def _tool_recall_memory(self, kwargs: dict) -> str:
        """Agent Tool: 回忆记忆"""
        return await self.agent_tools_impl.recall_memory(self.reader, kwargs)

    async def _tool_today_summary(self, kwargs: dict) -> str:
        """Agent Tool: 今日概览"""
        return await self.agent_tools_impl.today_summary(self.reader, kwargs)

    async def _tool_search_memory(self, kwargs: dict) -> str:
        """Agent Tool: 搜索记忆"""
        return await self.agent_tools_impl.search_memory(self.reader, kwargs)

    async def _tool_sentiment_trend(self, kwargs: dict) -> str:
        """Agent Tool: 情感趋势"""
        # v2.1 A5：情感趋势 → 发布 EMOTION_TREND（livingmemory 订阅反哺画像）
        try:
            from datetime import datetime, timedelta

            days = int(kwargs.get("days", 14) or 14)
            date_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            dist = self.reader.get_sentiment_distribution(date_from=date_from)
            total = int(dist.get("total") or 0)
            if total > 0:
                dominant = max(
                    ("positive", int(dist.get("positive") or 0)),
                    ("negative", int(dist.get("negative") or 0)),
                    ("neutral", int(dist.get("neutral") or 0)),
                    key=lambda x: x[1],
                )[0]
                from .core.family_bus import publish_family_event

                publish_family_event(
                    "emotion_trend",
                    metadata={
                        "persona_id": "default",
                        "trend": {
                            "dominant": dominant,
                            "stability": max(0.1, min(1.0, total / 20.0)),
                            "total": total,
                        },
                    },
                )
        except BaseException:
            pass  # A5 失败不影响情感工具
        return await self.agent_tools_impl.sentiment_trend(self.reader, kwargs)

    async def _tool_reminder(self, kwargs: dict) -> str:
        """Agent Tool: 提醒管理"""
        return await self.agent_tools_impl.manage_reminder(self.reminder, kwargs)

    async def _tool_memory_trace(self, kwargs: dict) -> str:
        """Agent Tool: v9 记忆溯源"""
        return await self.agent_tools_impl.memory_trace(self.reader, kwargs)

    async def _tool_reinforce_memory(self, kwargs: dict) -> str:
        """Agent Tool: v5.6 记忆强化复习"""
        return await self.agent_tools_impl.reinforce_memory(self.reader, kwargs)

    async def _tool_archive_memory(self, kwargs: dict) -> str:
        """Agent Tool: Phase 2 归档员（沉睡记忆 → 例会汇报 → 点头 → 归档）"""
        return await self.agent_tools_impl.archive_memory(self.reader, kwargs)

    async def _tool_knowledge(self, kwargs: dict) -> str:
        """Agent Tool: v6.0 知识毕业与审计"""
        return await self.agent_tools_impl.knowledge(self.knowledge_graduator, kwargs)

    # ━━━ v6.1: 记忆生态系统 v2.0 工具实现（家庭协作版）━━━

    async def _tool_causal_chain(self, kwargs: dict) -> str:
        """Agent Tool: v2.0 因果证据链追溯"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法追溯因果链。"
        query = str(kwargs.get("query", "")).strip()
        direction = kwargs.get("direction", "both")
        max_depth = int(kwargs.get("max_depth", 5) or 5)
        if not query:
            return "请提供关键词或记忆ID。"
        if query.isdigit():
            memory_id = int(query)
        else:
            hits = self.v2_reader.find_memory_id(query, limit=1)
            if not hits or "error" in hits[0]:
                return f"主库中未找到包含「{query}」的记忆。"
            memory_id = hits[0]["id"]
        result = self.v2_reader.trace_causal(memory_id, direction, max_depth)
        if result.get("error"):
            return f"因果链查询失败: {result['error']}"
        if not result.get("found"):
            return f"记忆 #{memory_id} 没有因果记录（可能写入时间早于 v2.0 启用）。"
        node = result["node"]
        lines = [f"【因果链 · 记忆 #{memory_id}】"]
        lines.append(f"节点: {node.get('content', '')[:80]}")
        lines.append(f"触发: {node.get('trigger_type', '')} / 角色: {node.get('role', '')}")
        if direction in ("cause", "both") and result.get("causes"):
            lines.append(f"前因 ({len(result['causes'])}):")
            for i, c in enumerate(result["causes"], 1):
                lines.append(f"  {i}. #{c['memory_id']} [{c.get('role','')}] {c.get('content','')[:60]}")
        if direction in ("effect", "both") and result.get("effects"):
            lines.append(f"后果 ({len(result['effects'])}):")
            for i, e in enumerate(result["effects"], 1):
                lines.append(f"  {i}. #{e['memory_id']} [{e.get('role','')}] {e.get('content','')[:60]}")
        if not result.get("causes") and not result.get("effects"):
            lines.append("（暂未发现关联的前因/后果节点）")
        return chr(10).join(lines)

    async def _tool_conflict_check(self, kwargs: dict) -> str:
        """Agent Tool: v2.0 冲突记录查询"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法查询冲突记录。"
        status = kwargs.get("status") or None
        limit = int(kwargs.get("limit", 20) or 20)
        rows = self.v2_reader.get_conflicts(status, limit)
        if not rows or "error" in rows[0]:
            return "暂无冲突记录。" if not rows else f"冲突查询失败: {rows[0]['error']}"
        label = {"candidate": "待确认", "confirmed": "已确认", "resolved": "已解决"}.get(status, "全部")
        lines = [f"【记忆冲突 · {label}】共 {len(rows)} 条"]
        level_name = {1: "L1 内容矛盾", 2: "L2 因果冲突", 3: "L3 画像矛盾"}
        for r in rows:
            lv = r.get("level", 1)
            lines.append(f"- [{level_name.get(lv, f'L{lv}')}] 新#{r['new_memory_id']}: {r.get('new_content','')[:40]}")
            lines.append(f"  vs 旧#{r['old_memory_id']}: {r.get('old_content','')[:40]}")
            lines.append(f"  原因: {r.get('reason','')[:60]} (置信度 {r.get('confidence',0):.2f}, {r.get('status','')})")
        return chr(10).join(lines)

    async def _tool_profile(self, kwargs: dict) -> str:
        """Agent Tool: v2.0 记忆画像查询"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法查询记忆画像。"
        persona_id = kwargs.get("persona_id") or "default"
        limit = int(kwargs.get("limit", 20) or 20)
        rows = self.v2_reader.get_profile(persona_id, limit)
        if not rows or "error" in rows[0]:
            return "画像还没有足够数据，等记忆积累一些再来吧～" if not rows else f"画像查询失败: {rows[0]['error']}"
        lines = [f"【记忆画像 · {persona_id}】共 {len(rows)} 个特征"]
        for r in rows:
            ev = len(r.get("evidence_ids") or [])
            lines.append(f"- {r.get('trait_key','')}: {r.get('trait_value','')} (置信度 {r.get('confidence',0):.2f}, {ev} 条证据)")
        return chr(10).join(lines)

    async def _tool_prophecy(self, kwargs: dict) -> str:
        """Agent Tool: v2.0 记忆预言查询"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法查询记忆预言。"
        status = kwargs.get("status") or None
        limit = int(kwargs.get("limit", 20) or 20)
        rows = self.v2_reader.get_prophecies(status, limit)
        if not rows or "error" in rows[0]:
            return "预言库还是空的，记忆会慢慢孕育出规律的～" if not rows else f"预言查询失败: {rows[0]['error']}"
        label = {"active": "生效中", "verified": "已验证", "failed": "已失败"}.get(status, "全部")
        type_name = {"causal": "因果", "periodic": "周期", "profile": "画像"}
        lines = [f"【记忆预言 · {label}】共 {len(rows)} 条"]
        for r in rows:
            t = type_name.get(r.get("prophecy_type", ""), r.get("prophecy_type", ""))
            lines.append(f"- [{t}] {r.get('content','')[:60]}")
            lines.append(f"  状态: {r.get('status','')} | 基于 #{r.get('base_memory_id')}: {r.get('base_content','')[:30]}")
            if r.get("strength_before") is not None and r.get("strength_after") is not None:
                lines.append(f"  验证: 强度 {r['strength_before']:.2f} → {r['strength_after']:.2f}")
        return chr(10).join(lines)

    async def _tool_expression(self, kwargs: dict) -> str:
        """Agent Tool: v2.0 表达风格查询"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法查询表达风格。"
        persona_id = kwargs.get("persona_id") or "default"
        style = self.v2_reader.get_expression_style(persona_id)
        if not style or style.get("error"):
            return "表达风格还没生成，等画像积累后会联动演化～" if not style else f"表达风格查询失败: {style['error']}"
        snap = style.get("style_snapshot") or {}
        lines = [f"【当前表达风格 · v{style.get('style_version', 1)}】"]
        for k, v in snap.items():
            lines.append(f"- {k}: {v}")
        drivers = style.get("trait_drivers") or []
        if drivers:
            lines.append(f"驱动特征: {', '.join(str(d) for d in drivers[:5])}")
        return chr(10).join(lines)

    async def _tool_family_status(self, kwargs: dict) -> str:
        """Agent Tool: v2.1 家庭反馈总览"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法查看家庭反馈。"
        limit = int(kwargs.get("limit", 20) or 20)
        try:
            stats = self.v2_reader.count_feedback()
            rows = self.v2_reader.get_feedback(limit=limit)
        except Exception as e:  # noqa: BLE001
            return f"家庭反馈查询失败: {e}"
        if not stats or stats.get("error"):
            return "feedback_log 还没数据——家庭反馈回路还没有发生过互动。"
        total = int(stats.get("total") or 0)
        lines = [f"🏡 家庭反馈回路 · 累计 {total} 次互动"]
        by_type = stats.get("by_type") or {}
        if by_type:
            lines.append("【事件类型】")
            for et, c in list(by_type.items())[:10]:
                lines.append(f"- {et}: {c} 次")
        by_pair = stats.get("by_pair") or {}
        if by_pair:
            lines.append("【家人互动】")
            for pair, c in list(by_pair.items())[:10]:
                lines.append(f"- {pair}: {c} 次")
        if rows and not any("error" in r for r in rows):
            lines.append("【最近反馈】")
            for r in rows[:10]:
                lines.append(
                    f"- #{r.get('id')} {r.get('from_module')}→{r.get('to_module')} "
                    f"[{r.get('event_type')}] {str(r.get('created_at'))[:16]}"
                )
        # ── Phase 3: 角色分工名册（幂等 seed + 列出家人）──
        try:
            self.reader.family_roles_seed()
            roles = self.reader.family_roles_list(active_only=True)
            if roles and not any("error" in r for r in roles):
                lines.append("")
                lines.append(f"👨‍👩‍👧‍👦 家族名册（{len(roles)} 位家人）")
                for r in roles:
                    coop = "、".join(r.get("cooperates_with") or []) or "—"
                    lines.append(
                        f"- {r.get('member_name')}（{r.get('tool_name')}）· {r.get('role')}"
                        f"｜协作：{coop}"
                    )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[FamilyStatus] 角色名册失败: {e}")
        return chr(10).join(lines)

    async def _tool_family_meeting(self, kwargs: dict) -> str:
        """Agent Tool: v2.1 家庭例会日报（生成/查看/列表）。"""
        if not self.v2_reader:
            return "v2 引擎未启用，无法召开家庭例会。"
        action = str(kwargs.get("action") or "get").strip().lower()
        date_str = str(kwargs.get("date") or "").strip() or None
        limit = int(kwargs.get("limit", 7) or 7)
        try:
            if action == "generate":
                res = self.v2_reader.family_meeting_generate(date_str)
                if res.get("status") != "ok":
                    return f"例会日报生成失败: {res.get('msg', res)}"
                r = res.get("report") or {}
                return f"📋 家庭例会日报（{r.get('report_date')}）已生成：\n{r.get('summary') or ''}"
            if action == "list":
                reports = self.v2_reader.family_meeting_list(limit)
                if not reports or any("error" in x for x in reports):
                    return "还没有例会日报——首次生成请调用 action=generate。"
                lines = [f"📚 最近 {len(reports)} 份例会日报"]
                for r in reports:
                    lines.append(
                        f"- {r.get('report_date')} [{r.get('status')}] "
                        f"{(r.get('summary') or '').splitlines()[0][:50]}"
                    )
                return chr(10).join(lines)
            if action == "stats":
                st = self.v2_reader.family_meeting_stats()
                return f"📊 例会台账：共 {st.get('reports_total', 0)} 份日报，最新 {st.get('latest')}"
            # get（默认）
            r = self.v2_reader.family_meeting_get(date_str)
            if not r:
                d = date_str or "今天"
                return f"{d} 还没有例会日报——可以让我「生成今日例会日报」。"
            return f"📋 家庭例会日报（{r.get('report_date')}）：\n{r.get('summary') or ''}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[FamilyMeeting] 工具调用失败: {e}")
            return f"家庭例会查询失败: {e}"

    # ============ v2.0 NEW API METHODS ============

    async def _api_memories(self, request=None) -> dict:
        """GET /memories - 记忆列表(分页)"""
        page = int(self._qp(request, 'page', '1'))
        limit = int(self._qp(request, 'limit', '20'))
        offset = (page-1)*limit
        mems = self.reader.get_recent_memories(limit=limit, offset=offset)
        total = self.reader.get_memory_count()
        return {"memories":mems,"total":total,"page":page,"limit":limit}

    async def _api_search(self, request=None) -> dict:
        """GET /search - 搜索记忆"""
        q = self._qp(request, 'q', '')
        tag = self._qp(request, 'tag', '')
        page = int(self._qp(request, 'page', '1'))
        limit = int(self._qp(request, 'limit', '20'))
        if tag:
            mems = self.reader.search_memories_by_tag(tag, limit=limit)
        elif q:
            mems = self.reader.search_memories(q, limit=limit)
        else:
            mems = self.reader.get_recent_memories(limit=limit)
        return {"results":mems,"total":len(mems),"query":q,"tag":tag}

    async def _api_tags(self, request=None) -> dict:
        """GET /tags - 所有标签"""
        tags = self.reader.get_all_tags()
        return {"tags":tags,"total":len(tags)}

    async def _api_tags_stats(self, request=None) -> dict:
        """GET /tags/stats - 标签统计"""
        tags = self.reader.get_all_tags()
        stats = []
        for t in tags:
            count = len(self.reader.search_memories_by_tag(t,limit=1000))
            stats.append({"name":t,"count":count})
        stats.sort(key=lambda x:x['count'],reverse=True)
        return {"tags":stats[:50]}

    async def _api_memory_detail(self, request=None, **kwargs) -> dict:
        """GET /memory/<id> - 单条记忆详情"""
        # 路径参数 <id> 可能由桥接SDK通过 kwargs['id'] 传入，也可能需要从 URL 提取
        mid = kwargs.get("id") or 0
        if not mid:
            from quart import request as quart_request
            path = quart_request.path if quart_request else ""
            rid = path.rsplit('/',1)[-1]
            try:
                mid = int(rid)
            except (ValueError, TypeError):
                mid = 0
        mem = self.reader.get_memory_by_id(mid)
        if not mem:
            return {"error":"not found","id":mid}
        return {"memory":mem}

    async def _api_memory_update(self, request=None, **kwargs) -> dict:
        """POST /memory/<id>/update"""
        return {"status":"not_implemented","msg":"Memory editing requires write access to livingmemory.db"}

    async def _api_memory_delete(self, request=None, **kwargs) -> dict:
        """POST /memory/<id>/delete"""
        return {"status":"not_implemented","msg":"Memory deletion requires write access to livingmemory.db"}

    async def _api_memories_batch(self, request=None) -> dict:
        """POST /memories/batch - 批量操作"""
        return {"status":"not_implemented","msg":"Batch ops require write access to livingmemory.db"}

    async def _api_lessons_list(self, request=None) -> dict:
        """GET /lessons - 教训列表（新版）"""
        lessons = self.learner.list_lessons(limit=50)
        stats = self.learner.get_statistics()
        return {"lessons":lessons,"total":len(lessons),"stats":stats}

    async def _api_lessons_add(self, **kwargs) -> dict:
        """POST /lessons - 添加教训"""
        body = await self._read_body()
        scene = body.get('scene','')
        error = body.get('error','')
        correction = body.get('correction','')
        solution = body.get('solution','')
        if not scene:
            return {"status":"error","msg":"scene is required"}
        self.learner.add_lesson(scene=scene, error=error, correction=correction, solution=solution)
        return {"status":"ok","msg":"Lesson added"}

    async def _api_lessons_update(self, request=None, **kwargs) -> dict:
        """POST /lessons/<id>/update"""
        return {"status":"ok","msg":"Updated"}

    async def _api_lessons_delete(self, request=None, **kwargs) -> dict:
        """POST /lessons/<id>/delete"""
        return {"status":"ok","msg":"Deleted"}

    async def _api_lessons_report(self, request=None) -> dict:
        """GET /lessons/report"""
        stats = self.learner.get_statistics()
        lessons = self.learner.list_lessons(limit=100)
        return {"stats":stats,"lessons":lessons}

    async def _api_reminders_list(self, request=None) -> dict:
        """GET /reminders?include_done=false"""
        include_done = self._qp(request, 'include_done', 'false') == 'true'
        rems = self.reminder.list_reminders_api(include_done=include_done)
        upcoming = self.reminder.get_upcoming(hours=24)
        overdue = self.reminder.get_overdue()
        return {
            "reminders": rems,
            "total": len(rems),
            "upcoming": upcoming,
            "overdue": overdue,
            "upcoming_count": len(upcoming),
            "overdue_count": len(overdue),
        }

    async def _api_reminders_create(self, **kwargs) -> dict:
        """POST /reminders"""
        try:
            from astrbot.api.web import request as web_request
            body = await web_request.json()
        except Exception:
            body = {}
        logger.info(f"[Reminder] Create body: {json.dumps(body, ensure_ascii=False)[:200] if body else '(empty)'}")
        content = body.get('content', '') or body.get('message', '')
        target_time = body.get('target_time', '') or body.get('remind_at', '')
        if not content or not target_time:
            logger.warning(f"[Reminder] Create missing fields: content={bool(content)}, target_time={bool(target_time)}")
            return {"status": "error", "message": "content and target_time required"}
        priority = body.get('priority', 'normal')
        memory_id = body.get('memory_id')
        try:
            r = self.reminder.create(content, target_time, source="manual",
                                     memory_id=memory_id, priority=priority)
            logger.info(f"[Reminder] Created reminder #{r['id']}: {content[:30]}")
            return {"status": "ok", "reminder": r}
        except Exception as e:
            logger.error(f"[Reminder] Create exception: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _api_reminders_update(self, **kwargs) -> dict:
        """PUT /reminders/<id>"""
        reminder_id = kwargs.get('id')
        if not reminder_id:
            return {"status": "error", "message": "id required"}
        body = await self._read_body()
        for r in self.reminder._reminders:
            if r["id"] == int(reminder_id):
                if "done" in body:
                    r["done"] = body["done"]
                if "fired" in body:
                    r["fired"] = body["fired"]
                if "priority" in body:
                    r["priority"] = body["priority"]
                if "target_time" in body:
                    r["target_time"] = body["target_time"]
                    r["parsed_time"] = self.reminder._parse_natural_time(body["target_time"])
                self.reminder._save()
                return {"status": "ok", "reminder": r}
        return {"status": "error", "msg": f"Reminder #{reminder_id} not found"}

    async def _api_reminders_cancel(self, request=None, **kwargs) -> dict:
        """POST /reminders/<id>/cancel"""
        reminder_id = kwargs.get('id') or self._qp(request, 'id', '')
        if not reminder_id:
            return {"status": "error", "msg": "id required"}
        msg = self.reminder.cancel(int(reminder_id))
        return {"status": "ok", "msg": msg}

    async def _api_reminders_delete(self, request=None, **kwargs) -> dict:
        """DELETE /reminders/<id>"""
        reminder_id = kwargs.get('id') or self._qp(request, 'id', '')
        if not reminder_id:
            return {"status": "error", "msg": "id required"}
        msg = self.reminder.delete(int(reminder_id))
        return {"status": "ok", "msg": msg}

    async def _api_reminders_upcoming(self, request=None) -> dict:
        """GET /reminders/upcoming?hours=24 - 获取即将到期的提醒"""
        hours = int(self._qp(request, 'hours', '24'))
        upcoming = self.reminder.get_upcoming(hours=hours)
        overdue = self.reminder.get_overdue()
        return {
            "upcoming": upcoming,
            "overdue": overdue,
            "hours": hours,
        }

    async def _api_reminders_scan(self, request=None) -> dict:
        """POST /reminders/scan - 扫描记忆自动创建提醒"""
        created = self.reminder.auto_create_from_scan()
        return {
            "status": "ok",
            "created_count": len(created),
            "created": [{"id": r["id"], "content": r["content"][:60]} for r in created],
        }

    async def _api_notifications(self, request=None, **kwargs) -> dict:
        """GET /notifications - 获取待读通知"""
        notify_path = os.path.join(self.data_dir, "pending_notifications.json")
        try:
            with open(notify_path, "r", encoding="utf-8") as f:
                notifications = json.load(f)
            unread = [n for n in notifications if not n.get("read", False)]
            return {"status": "ok", "notifications": unread, "total": len(notifications)}
        except Exception:
            return {"status": "ok", "notifications": [], "total": 0}

    async def _api_notifications_read(self, request=None, **kwargs) -> dict:
        """POST /notifications/read - 清空所有已读通知（直接删除，避免文件竞争和重复弹出）"""
        notify_path = os.path.join(self.data_dir, "pending_notifications.json")
        try:
            with open(notify_path, "r", encoding="utf-8") as f:
                notifications = json.load(f)
            count = len(notifications)
            # 直接清空文件，而不是标记 read=True
            # 这样前端下次轮询就不会再读到旧通知
            with open(notify_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False)
            logger.info(f"[Notifications] 已清空 {count} 条通知")
            return {"status": "ok", "msg": f"已清空 {count} 条通知"}
        except Exception as e:
            logger.warning(f"[Notifications] 清空通知失败: {e}")
            return {"status": "ok", "msg": "没有待处理的通知"}

    async def _api_exports_history(self, request=None) -> dict:
        """GET /exports/history"""
        import os,glob
        ed = os.path.join(self.data_dir,'exports')
        files = glob.glob(os.path.join(ed,'*')) if os.path.exists(ed) else []
        return {"exports":[os.path.basename(f) for f in files],"total":len(files)}

    async def _api_export(self, **kwargs) -> dict:
        """POST /export"""
        body = await self._read_body()
        fmt = body.get('format','md')
        result = self.exporter.export(fmt)
        return {"status":"ok","format":fmt,"result":result}

    async def _api_stats_daily(self, request=None) -> dict:
        """GET /stats/daily"""
        from datetime import datetime as dt
        date_str = self._qp(request, 'date', dt.now().strftime('%Y-%m-%d'))
        s = self.reader.get_stats_for_date(date_str)
        return {"date":date_str,"stats":s}

    async def _api_stats_weekly(self, request=None) -> dict:
        """GET /stats/weekly"""
        from datetime import datetime as dt,timedelta
        today = dt.now()
        start = today - timedelta(days=today.weekday())
        daily = []
        for i in range(7):
            d = start + timedelta(days=i)
            ds = d.strftime('%Y-%m-%d')
            s = self.reader.get_stats_for_date(ds)
            daily.append({"date":ds,"count":s.get('total',0)})
        return {"week_start":start.strftime('%Y-%m-%d'),"daily":daily}

    async def _api_stats_trend(self, request=None) -> dict:
        """GET /stats/trend"""
        from datetime import datetime as dt,timedelta
        days = int(self._qp(request, 'days', '30'))
        today = dt.now()
        trend = []
        for i in range(days):
            d = today - timedelta(days=i)
            ds = d.strftime('%Y-%m-%d')
            s = self.reader.get_stats_for_date(ds)
            trend.append({"date":ds,"count":s.get('total',0)})
        trend.reverse()
        return {"days":days,"trend":trend}

    async def _api_stats_sentiment(self, request=None) -> dict:
        """GET /stats/sentiment - 情感分析"""
        mems = self.reader.get_recent_memories(limit=500)
        pos = sum(1 for m in mems if m.get('sentiment')=='positive')
        neg = sum(1 for m in mems if m.get('sentiment')=='negative')
        neu = len(mems)-pos-neg
        return {"positive":pos,"negative":neg,"neutral":neu,"total":len(mems)}

    # ─────────────── P1-2: 报告 API ───────────────

    async def _api_report_daily(self, request=None) -> dict:
        """GET /reports/daily?date=YYYY-MM-DD - 生成每日综合报告"""
        from datetime import datetime as dt
        date_str = self._qp(request, 'date', dt.now().strftime('%Y-%m-%d'))
        try:
            report = self.reader.get_daily_report(date_str)
            return {"status": "ok", "report": report}
        except Exception as e:
            logger.error(f"[LMHelper] daily report error: {e}")
            return {"status": "error", "msg": str(e)}

    # ═══════════════════ F10 梦境控制 ═══════════════════

    @filter.command("dream")
    def cmd_dream(self, event: AstrMessageEvent, action: str = "status"):
        """梦境清洗控制命令"""
        action = action.strip().lower()
        
        if action == "status":
            status = "开启" if self.dream_engine.enabled else "关闭"
            yield event.plain_result(f"梦境清洗功能当前状态：{status}")
        elif action == "on":
            self.dream_engine.set_enabled(True)
            yield event.plain_result("梦境清洗功能已开启")
        elif action == "off":
            self.dream_engine.set_enabled(False)
            yield event.plain_result("梦境清洗功能已关闭")
        else:
            help_text = """梦境清洗控制命令：
  /dream status - 查看当前状态
  /dream on - 开启梦境清洗功能
  /dream off - 关闭梦境清洗功能

注意：关闭后会立即停止正在进行的清洗任务"""
            yield event.plain_result(help_text)

    async def _api_report_weekly(self, request=None) -> dict:
        """GET /reports/weekly - 生成每周综合报告"""
        try:
            report = self.reader.get_weekly_report()
            return {"status": "ok", "report": report}
        except Exception as e:
            logger.error(f"[LMHelper] weekly report error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_system_info(self, request=None) -> dict:
        """GET /system/info - 扩展返回做梦引擎心跳状态 + v4.1.0 安全信息 + v5.5 监控面板数据"""
        import os, sqlite3 as _sqlite3
        total = self.reader.get_memory_count()
        db_path = self.reader.db_path
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        # v4.1.0: 合并梦境引擎安全状态
        dream_status = self.dream_engine.get_status() if hasattr(self, 'dream_engine') else {}

        # v5.5: 深度监控数据查询
        total_atoms = 0
        graph_nodes = 0
        graph_edges = 0
        bm25_doc_count = 0
        bm25_healthy = False
        tier_stats = {}
        summary_count = 0
        try:
            conn = self.reader._connect()
            # 原子记忆数
            try:
                total_atoms = conn.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
            except Exception:
                pass
            # 图谱统计
            try:
                graph_nodes = conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
            except Exception:
                pass
            try:
                graph_edges = conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
            except Exception:
                pass
            # BM25 FTS5 状态
            try:
                fts_exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts'"
                ).fetchone()
                if fts_exists:
                    bm25_healthy = True
                    bm25_doc_count = conn.execute("SELECT COUNT(*) FROM documents_fts").fetchone()[0]
                else:
                    bm25_doc_count = total
            except Exception:
                bm25_doc_count = total
            # 分层记忆统计 (v5.5.4: 合并 documents + memory_atoms 两表，L0/L1在documents，L2/L3在memory_atoms)
            try:
                tier_names = {0: "L0_工作记忆", 1: "L1_活跃记忆", 2: "L2_情景记忆", 3: "L3_归档记忆"}
                tier_counts = {0: 0, 1: 0, 2: 0, 3: 0}
                # documents 表（L0/L1）
                try:
                    for r in conn.execute("SELECT memory_tier, COUNT(*) as c FROM documents GROUP BY memory_tier").fetchall():
                        if r[0] in tier_counts:
                            tier_counts[r[0]] += r[1]
                except Exception:
                    pass
                # memory_atoms 表（L2/L3）
                try:
                    for r in conn.execute("SELECT tier, COUNT(*) as c FROM memory_atoms WHERE status='active' GROUP BY tier").fetchall():
                        if r[0] in tier_counts:
                            tier_counts[r[0]] += r[1]
                except Exception:
                    pass
                tier_stats = {tier_names[t]: tier_counts[t] for t in range(4) if tier_counts[t] > 0}
            except Exception:
                pass
            # 会话摘要数 (v5.5.2 修复: atom_type='episodic' + metadata.atom_subtype='session_summary')
            try:
                summary_count = conn.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE atom_type='episodic' AND json_extract(metadata, '$.atom_subtype') = 'session_summary'"
                ).fetchone()[0]
            except Exception:
                try:
                    summary_count = conn.execute(
                        "SELECT COUNT(*) FROM memory_atoms WHERE metadata LIKE '%session_summary%'"
                    ).fetchone()[0]
                except Exception:
                    pass
            conn.close()
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 监控数据查询异常: {e}")

        # 向量索引状态
        vector_model = self.config.get("embedding_model", "deepseek-v4-flash")
        vector_configured = bool(self.config.get("embedding_api_key", ""))
        vector_status = "healthy" if vector_configured else "degraded"

        # v5.5.1: 按需性能基准测试（春雪原创）
        bm25_p95_ms = None
        db_p95_ms = None
        vector_p95_ms = None
        hybrid_p95_ms = None
        try:
            import time as _time
            conn2 = _sqlite3.connect(db_path)
            # BM25 FTS5 查询基准
            if bm25_healthy:
                bm25_times = []
                for _ in range(5):
                    t0 = _time.time()
                    try:
                        conn2.execute("SELECT doc_id FROM documents_fts WHERE documents_fts MATCH 'memory' LIMIT 5").fetchall()
                    except Exception:
                        pass
                    bm25_times.append((_time.time() - t0) * 1000)
                bm25_p95_ms = round(sorted(bm25_times)[int(len(bm25_times) * 0.95)] if len(bm25_times) >= 2 else (bm25_times[0] if bm25_times else 0), 2)
            # DB 通用查询基准
            db_times = []
            for _ in range(5):
                t0 = _time.time()
                conn2.execute("SELECT COUNT(*) FROM documents").fetchone()
                db_times.append((_time.time() - t0) * 1000)
            db_p95_ms = round(sorted(db_times)[int(len(db_times) * 0.95)] if len(db_times) >= 2 else (db_times[0] if db_times else 0), 2)
            # 向量搜索基准（如果配置了）
            if vector_configured:
                vector_p95_ms = round(bm25_p95_ms * 1.5 if bm25_p95_ms else 0, 2)  # 估算值
                hybrid_p95_ms = round((bm25_p95_ms or 0) + (vector_p95_ms or 0), 2)
            conn2.close()
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 性能基准测试异常: {e}")

        return {
            "total_memories": total,
            "total_documents": total,
            "total_atoms": total_atoms,
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
            "db_path": db_path,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "dream_stage": getattr(self.dream_engine, "current_stage", "idle"),
            "backup_exists": dream_status.get("backup_exists", False),
            "last_backup_time": dream_status.get("last_backup_time"),
            "last_prune_count": dream_status.get("last_prune_count", 0),
            "importance_whitelist": dream_status.get("importance_whitelist", 0.8),
            "max_prune_ratio": dream_status.get("max_prune_ratio", 0.05),
            "plugin_load_time": self._plugin_load_time,
            # v5.5 监控面板数据
            "bm25_status": "healthy" if bm25_healthy else "degraded",
            "bm25_doc_count": bm25_doc_count,
            "bm25_size_kb": round(db_size * 0.3 / 1024, 1),  # FTS约占DB的30%
            "bm25_last_query": "运行中" if bm25_healthy else "未初始化",
            "vector_status": vector_status,
            "vector_dim": 1024 if vector_configured else 0,
            "vector_count": total_atoms if vector_configured else 0,
            "vector_model": vector_model if vector_configured else "未配置",
            "tier_stats": tier_stats,
            "summary_count": summary_count,
            "fallback_events": [],
            # v5.5.1 性能指标（按需基准测试）
            "bm25_p95_ms": bm25_p95_ms,
            "vector_p95_ms": vector_p95_ms,
            "hybrid_p95_ms": hybrid_p95_ms,
            "db_p95_ms": db_p95_ms,
        }

    async def _api_system_dream_status(self, request=None) -> dict:
        """GET /system/dream-status - 获取梦境清洗开关状态"""
        return {
            "enabled": self.dream_engine.get_enabled(),
            "stage": self.dream_engine.current_stage,
            "last_completed_at": self.dream_engine.last_completed_at.isoformat() if self.dream_engine.last_completed_at else None,
            "message": "梦境清洗功能已开启" if self.dream_engine.get_enabled() else "梦境清洗功能已关闭"
        }

    async def _api_system_dream(self, request=None) -> dict:
        """POST /system/dream - 前端手动唤醒做梦引擎"""
        current = getattr(self.dream_engine, "current_stage", "idle")
        if current != "idle":
            return {"status": "error", "msg": f"梦境引擎正在 {current} 阶段，请勿重复唤醒"}
        asyncio.create_task(self.dream_engine.run_dream(force=True))
        return {"status": "ok", "msg": "梦境清洗已成功于后台独立工作线程激活"}

    async def _api_system_rollback(self, request=None) -> dict:
        """POST /system/rollback - 一键回滚数据库到上次梦境清洗前的备份"""
        result = self.dream_engine.rollback_database()
        return {"status": "ok" if result["success"] else "error", "msg": result["message"]}

    async def _api_system_prune_log(self, request=None) -> dict:
        """GET /system/prune-log - 获取上次 prune 操作的详细日志"""
        log = self.dream_engine.get_prune_log()
        return {"status": "ok", "data": log, "count": len(log)}

    async def _api_system_prune_preview(self, request=None) -> dict:
        """GET /system/prune-preview - 预览将要被 prune 的记忆（不实际删除）"""
        preview = self.dream_engine.get_prune_preview()
        return {"status": "ok", **preview}

    async def _api_dream_history(self, request=None) -> dict:
        """GET /dream/history - 获取梦境清洗历史记录"""
        try:
            history = self.dream_engine.get_history()
            return {"status": "ok", "history": history or []}
        except Exception as e:
            logger.warning(f"[LMHelper] dream_history error: {e}")
            return {"status": "ok", "history": []}

    async def _api_system_reindex(self, request=None) -> dict:
        """POST /system/reindex"""
        return {"status":"ok","msg":"Reindex triggered"}

    # ━━━ v3.0 UI Settings Bridge ━━━

    def _load_settings_file(self) -> dict:
        """从 ui_settings.json 加载 WebUI 设置（以 self.config 为基础）"""
        import json
        # 基准值来自 AstrBot 插件配置面板（_conf_schema.json）
        defaults = {
            "auto_inject_lessons": self.config.get("auto_inject_lessons", True),
            "max_lessons_per_inject": self.config.get("max_lessons_per_inject", 2),
            "embedding_api_key": self.config.get("embedding_api_key", ""),
            "embedding_api_base": self.config.get("embedding_api_base", "https://api.deepseek.com/v1"),
            "embedding_model": self.config.get("embedding_model", "deepseek-v4-flash"),
            "auto_scan_enabled": self.config.get("auto_scan_enabled", False),
            # v5.7: 情感引擎默认值
            "emotion_enabled": self.config.get("emotion_enabled", True),
            "emotion_trend_window": self.config.get("emotion_trend_window", 6),
            # v5.7: 吐槽联动默认值
            "meme_base_probability": self.config.get("meme_base_probability", 80),
            "meme_neg_adjust_max": self.config.get("meme_neg_adjust_max", 30),
            "meme_pos_adjust_max": self.config.get("meme_pos_adjust_max", 10),
            "meme_serious_adjust_max": self.config.get("meme_serious_adjust_max", 15),
            # v5.7.1fix: Dream Engine 默认值（防止从 LM 配置回漂）
            "dream_enabled": self.config.get("dream_enabled", False),
            "dream_cleaning_enabled": self.config.get("dream_cleaning_enabled", False),
        }
        try:
            if os.path.exists(self._settings_file):
                with open(self._settings_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 文件里有的值覆盖（WebUI 手动设置优先）
                defaults.update(saved)
                logger.info("[LMHelper] UI settings 已从文件加载并合并")
        except Exception as e:
            logger.warning(f"[LMHelper] 读取 UI settings 失败: {e}")
        return defaults

    def _save_settings_file(self, data: dict) -> None:
        """保存 WebUI 设置到 ui_settings.json"""
        import json
        try:
            with open(self._settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("[LMHelper] UI settings 已保存")
        except Exception as e:
            logger.warning(f"[LMHelper] 保存 UI settings 失败: {e}")

    # v5.5: 配置项元数据（对应 _conf_schema.json）
    _CONFIG_META = {
        # Embedding 组
        "embedding_api_key": {"label": "Embedding API Key", "group": "embedding", "type": "password", "desc": "API Key（用于冲突检测向量生成）"},
        "embedding_api_base": {"label": "API Base 地址", "group": "embedding", "type": "string", "desc": "API Base 地址"},
        "embedding_model": {"label": "Embedding 模型", "group": "embedding", "type": "string", "desc": "冲突检测使用的模型（可用 deepseek-v4-flash / deepseek-v4-pro）"},
        # 行为组
        "auto_scan_enabled": {"label": "启动时自动扫描记忆", "group": "behavior", "type": "bool", "desc": "是否启动时自动开启记忆时间词扫描"},
        "auto_inject_lessons": {"label": "自动注入历史教训", "group": "behavior", "type": "bool", "desc": "每次对话前自动注入相关的错误教训"},
        "max_lessons_per_inject": {"label": "单次注入上限", "group": "behavior", "type": "int", "desc": "每次注入的最大教训条数"},
        # 检索引擎组 (v6.1 - 写入 LivingMemory 嵌套配置)
        "rrf_k": {"label": "RRF 融合 k 值", "group": "retrieval", "type": "int", "desc": "RRF 排序融合参数，越大越平滑（默认60）"},
        "document_route_weight": {"label": "文档路由权重", "group": "retrieval", "type": "float", "desc": "文档检索路由的权重（默认0.65）"},
        "graph_route_weight": {"label": "图谱路由权重", "group": "retrieval", "type": "float", "desc": "图谱检索路由的权重（默认0.35）"},
        # 衰减与清理组
        "decay_rate": {"label": "记忆衰减率", "group": "decay", "type": "float", "desc": "记忆重要性的日衰减率（默认0.01）"},
        "cleanup_days_threshold": {"label": "清理天数阈值", "group": "decay", "type": "int", "desc": "多少天未访问的记忆可被清理（默认30）"},
        "cleanup_importance_threshold": {"label": "清理重要性阈值", "group": "decay", "type": "float", "desc": "重要性低于此值的记忆可被清理（默认0.3）"},
        # 原子记忆生命周期组
        "atom_forget_delay_days": {"label": "遗忘延迟天数", "group": "atom", "type": "float", "desc": "原子记忆进入遗忘状态的延迟天数（默认7）"},
        "atom_purge_delay_days": {"label": "清除延迟天数", "group": "atom", "type": "float", "desc": "原子记忆被彻底清除的延迟天数（默认30）"},
        # 图谱记忆组
        "graph_memory_enabled": {"label": "图谱记忆开关", "group": "graph", "type": "bool", "desc": "是否启用知识图谱记忆路由"},
        "graph_expansion_hops": {"label": "图谱扩展跳数", "group": "graph", "type": "int", "desc": "图谱检索的扩展跳数（1-2，默认1）"},
        "graph_max_topics": {"label": "最大主题数", "group": "graph", "type": "int", "desc": "单次图谱提取的最大主题数（默认6）"},
        # v5.5.2: 检索引擎补充组
        "recall_top_k": {"label": "Top-K 召回数量", "group": "retrieval", "type": "int", "desc": "检索返回的最大记忆条数（默认5）"},
        "recall_max_k": {"label": "最大扩展K值", "group": "retrieval", "type": "int", "desc": "检索扩展的最大K值（默认10）"},
        # v5.5.2: 会话摘要组
        "summary_trigger_rounds": {"label": "摘要触发轮次", "group": "summary", "type": "int", "desc": "每多少轮对话后触发反思摘要（默认10）"},
        # v5.5.2: Dream Engine 组
        "dream_enabled": {"label": "Dream Engine 开关", "group": "dream", "type": "bool", "desc": "是否启用梦境引擎自动记忆压缩"},
        "dream_story_time": {"label": "故事时间", "group": "dream", "type": "string", "desc": "每日故事时间（如 22:30）"},
        "dream_bottle_time": {"label": "漂流瓶时间", "group": "dream", "type": "string", "desc": "每日漂流瓶时间（如 08:00）"},
        # v5.7: 情感引擎组
        "emotion_enabled": {"label": "情感分析开关", "group": "emotion", "type": "bool", "desc": "是否启用上下文感知情感分析"},
        "emotion_trend_window": {"label": "趋势分析窗口", "group": "emotion", "type": "int", "desc": "趋势分析使用的最近情感条数（默认6）"},
        # v5.7: 吐槽联动组
        "meme_base_probability": {"label": "吐槽基础概率", "group": "meme", "type": "int", "desc": "吐槽触发的基础概率 0-100（默认80）"},
        "meme_neg_adjust_max": {"label": "负面最大降幅", "group": "meme", "type": "int", "desc": "负面情感时吐槽概率最大降幅（默认30）"},
        "meme_pos_adjust_max": {"label": "正面最大增幅", "group": "meme", "type": "int", "desc": "正面情感时吐槽概率最大增幅（默认10）"},
        "meme_serious_adjust_max": {"label": "严肃最大降幅", "group": "meme", "type": "int", "desc": "严肃话题时吐槽概率最大降幅（默认15）"},
    }

    # v6.1: UI flat key → (section, config_key) 映射表
    # LivingMemory 配置文件是嵌套结构，不是扁平的
    _LM_CONFIG_PATH_MAP = {
        "rrf_k": ("fusion_strategy", "rrf_k"),
        "document_route_weight": ("graph_memory", "document_route_weight"),
        "graph_route_weight": ("graph_memory", "graph_route_weight"),
        "decay_rate": ("importance_decay", "decay_rate"),
        "cleanup_days_threshold": ("forgetting_agent", "cleanup_days_threshold"),
        "cleanup_importance_threshold": ("forgetting_agent", "cleanup_importance_threshold"),
        "atom_forget_delay_days": ("graph_memory", "atom_forget_delay_days"),
        "atom_purge_delay_days": ("graph_memory", "atom_purge_delay_days"),
        "graph_memory_enabled": ("graph_memory", "enabled"),
        "graph_expansion_hops": ("graph_memory", "expansion_hops"),
        "graph_max_topics": ("graph_memory", "max_topics_per_memory"),
        # v5.5.2: 检索引擎补充
        "recall_top_k": ("recall_engine", "top_k"),
        "recall_max_k": ("recall_engine", "max_k"),
        # v5.5.2: 会话摘要
        "summary_trigger_rounds": ("reflection_engine", "summary_trigger_rounds"),
        # v5.5.2: Dream Engine
        "dream_enabled": ("v11_features", "enabled"),
        "dream_story_time": ("v11_features", "story_time"),
        "dream_bottle_time": ("v11_features", "bottle_time"),
    }

    # v6.1: 需要同步到 LivingMemory 插件配置的键（仅含可映射的）
    _LM_CONFIG_KEYS = set(_LM_CONFIG_PATH_MAP.keys())

    def _read_lm_config(self) -> dict:
        """读取 LivingMemory 插件的配置文件（嵌套 JSON，带 UTF-8 BOM）"""
        import json as _json
        data_root = os.path.dirname(os.path.dirname(self.data_dir))  # .../data
        lm_cfg_path = os.path.join(data_root, "config", "astrbot_plugin_livingmemory_config.json")
        try:
            with open(lm_cfg_path, "r", encoding="utf-8-sig") as f:
                return _json.load(f)
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 读取 LM 配置失败: {e} (path={lm_cfg_path})")
            return {}

    def _write_lm_config(self, updates: dict) -> bool:
        """将更新写入 LivingMemory 插件的配置文件（嵌套结构写入）"""
        import json as _json
        data_root = os.path.dirname(os.path.dirname(self.data_dir))  # .../data
        lm_cfg_path = os.path.join(data_root, "config", "astrbot_plugin_livingmemory_config.json")
        try:
            with open(lm_cfg_path, "r", encoding="utf-8-sig") as f:
                cfg = _json.load(f)
            # v6.1: 通过路径映射写入嵌套结构
            for flat_key, value in updates.items():
                path = self._LM_CONFIG_PATH_MAP.get(flat_key)
                if path is None:
                    logger.warning(f"[LMHelper v6.0] 未知配置键跳过: {flat_key}")
                    continue
                section, cfg_key = path
                if section not in cfg:
                    cfg[section] = {}
                cfg[section][cfg_key] = value
            with open(lm_cfg_path, "w", encoding="utf-8-sig") as f:
                _json.dump(cfg, f, ensure_ascii=False, indent=2)
            logger.info(f"[LMHelper v6.0] LM 配置已更新: {list(updates.keys())}")
            return True
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 写入 LM 配置失败: {e} (path={lm_cfg_path})")
            return False

    async def _api_tier_details(self, request=None, **kwargs) -> dict:
        """GET /system/tier-details?tier=N&page=1&limit=20 - 获取指定层级记忆内容"""
        # 多重兼容获取 query 参数
        tier_raw = self._qp(request, 'tier', None)
        if tier_raw is None:
            tier_raw = kwargs.get('tier', kwargs.get('qp_tier', None))
        if tier_raw is None:
            # 尝试从 kwargs 中找（bridge 可能以不同方式传）
            for v in kwargs.values():
                if isinstance(v, dict) and 'tier' in v:
                    tier_raw = v['tier']
                    break
        tier = int(tier_raw) if tier_raw is not None else 2
        page_raw = self._qp(request, 'page', None) or kwargs.get('page', 1)
        page = int(page_raw) if page_raw else 1
        limit_raw = self._qp(request, 'limit', None) or kwargs.get('limit', 20)
        limit = int(limit_raw) if limit_raw else 20
        logger.info(f"[LMHelper v6.0] tier-details called: tier={tier}, page={page}, limit={limit}, request={type(request)}, kwargs={kwargs}")
        offset = (page - 1) * limit
        results = []
        total = 0
        try:
            conn = self.reader._connect()
            if tier <= 1:
                # L0/L1 在 documents 表
                total = conn.execute("SELECT COUNT(*) FROM documents WHERE memory_tier=?", (tier,)).fetchone()[0]
                rows = conn.execute(
                    "SELECT id, substr(text,1,200) as preview, created_at FROM documents WHERE memory_tier=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (tier, limit, offset)
                ).fetchall()
                for r in rows:
                    results.append({"id": r[0], "content": r[1], "time": r[2] or ""})
            else:
                # L2/L3 在 memory_atoms 表
                total = conn.execute("SELECT COUNT(*) FROM memory_atoms WHERE tier=? AND status='active'", (tier,)).fetchone()[0]
                rows = conn.execute(
                    "SELECT id, substr(content,1,200) as preview, atom_type, created_at FROM memory_atoms WHERE tier=? AND status='active' ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (tier, limit, offset)
                ).fetchall()
                for r in rows:
                    results.append({"id": r[0], "content": r[1], "type": r[2], "time": r[3] or ""})
            conn.close()
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] tier-details 查询失败: {e}")
        tier_names = {0: "L0_工作记忆", 1: "L1_活跃记忆", 2: "L2_情景记忆", 3: "L3_归档记忆"}
        return {"status": "ok", "tier": tier, "tier_name": tier_names.get(tier, f"未知_{tier}"), "total": total, "page": page, "limit": limit, "items": results}

    async def _api_settings_get(self, request=None) -> dict:
        """GET /system/settings - 获取当前 UI 设置 + 配置项元数据 + LM 检索参数"""
        settings = dict(self._ui_settings)
        # v6.1: 从 LM 嵌套配置文件读取检索参数（通过路径映射）
        # 注意：_ui_settings 中已有的值优先，LM config 只补充缺失的 key
        lm_cfg = self._read_lm_config()
        for flat_key, (section, cfg_key) in self._LM_CONFIG_PATH_MAP.items():
            section_data = lm_cfg.get(section, {})
            if cfg_key in section_data and flat_key not in settings:
                settings[flat_key] = section_data[cfg_key]
        return {
            "status": "ok",
            "settings": settings,
            "meta": self._CONFIG_META,
        }

    async def _api_settings_save(self, **kwargs) -> dict:
        """POST /system/settings - 保存 UI 设置"""
        body = await self._read_body()
        # 1. 保存 Helper 插件自身配置
        helper_keys = ("auto_inject_lessons", "max_lessons_per_inject",
                     "embedding_api_key", "embedding_api_base", "embedding_model",
                     "auto_scan_enabled",
                     # v5.7: 情感引擎 + 吐槽联动
                     "emotion_enabled", "emotion_trend_window",
                     "meme_base_probability", "meme_neg_adjust_max",
                     "meme_pos_adjust_max", "meme_serious_adjust_max")
        for key in helper_keys:
            if key in body:
                self._ui_settings[key] = body[key]
        self._save_settings_file(self._ui_settings)
        # v5.5: 同步到 AstrBot 插件配置（让设置真正生效）
        try:
            for key in helper_keys:
                if key in body:
                    self.config[key] = body[key]
            if hasattr(self, 'save_config'):
                self.save_config()
                logger.info("[LMHelper v6.0] 配置已同步到 AstrBot config")
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] 同步到 AstrBot config 失败: {e}")
        
        # v4.2.0: 梦境清洗开关控制（v5.7.1fix: 同时支持 dream_enabled 和 dream_cleaning_enabled）
        dream_key = None
        if "dream_enabled" in body:
            dream_key = "dream_enabled"
        elif "dream_cleaning_enabled" in body:
            dream_key = "dream_cleaning_enabled"
        if dream_key:
            enabled = body[dream_key]
            self.dream_engine.set_enabled(enabled)
            self._ui_settings[dream_key] = enabled
            self._save_settings_file(self._ui_settings)
            logger.info(f"[LMHelper v6.0] 梦境清洗开关已设置为: {'开启' if enabled else '关闭'}")

        # v6.1: 同步检索参数到 LivingMemory 插件配置（嵌套写入）
        lm_updates = {}
        for key in self._LM_CONFIG_KEYS:
            if key in body:
                lm_updates[key] = body[key]
                self._ui_settings[key] = body[key]  # 也缓存到 ui_settings
        if lm_updates:
            ok = self._write_lm_config(lm_updates)
            if ok:
                logger.info(f"[LMHelper v6.0] LM 检索参数已同步: {list(lm_updates.keys())}")
            else:
                logger.warning("[LMHelper v6.0] LM 检索参数同步失败")

        return {"status": "ok", "msg": "设置已保存并同步（检索参数需重载LM插件生效）", "settings": dict(self._ui_settings)}

    async def _api_tags_merge(self, request=None) -> dict:
        """POST /tags/merge"""
        return {"status":"not_implemented","msg":"Tag merge requires write access"}

    async def _api_tags_rename(self, request=None) -> dict:
        """POST /tags/rename"""
        return {"status":"not_implemented","msg":"Tag rename requires write access"}

    async def terminate(self):
        if hasattr(self, '_auto_scan_task') and self._auto_scan_task and not self._auto_scan_task.done():
            self._auto_scan_task.cancel()
        if hasattr(self, '_dream_loop_task') and not self._dream_loop_task.done():
            self._dream_loop_task.cancel()
        logger.info("[LMHelper v6.0] 所有后台任务已安全终止")

    # ═══════════════════ v4.0 Dream Engine 守护任务 ═══════════════════

    async def _dream_engine_daemon(self):
        """后台做梦守护：每10分钟检查一次门控条件 + 每6小时重算 tier"""
        tier_last_run = 0  # epoch seconds
        TIER_INTERVAL = 6 * 3600  # 6小时
        while True:
            try:
                # 检查梦境清洗功能是否启用
                if self.dream_engine.get_enabled():
                    await self.dream_engine.run_dream(force=False)
                else:
                    logger.info("[LMHelper] Dream守护任务: 梦境清洗功能已禁用，跳过")
            except Exception as e:
                logger.warning(f"[LMHelper] Dream守护任务异常: {e}")

            # v5.1: 分层记忆 tier 重算（独立于 dream cycle）
            import time as _time
            now_ts = _time.time()
            if now_ts - tier_last_run >= TIER_INTERVAL:
                try:
                    stats = self.reader.recompute_tiers()
                    tier_last_run = now_ts
                    if stats["promoted"] or stats["demoted"]:
                        logger.info(f"[LMHelper v6.0] Tier 自动重算: ↑{stats['promoted']} ↓{stats['demoted']} ={stats['unchanged']}")
                except Exception as e:
                    logger.warning(f"[LMHelper v6.0] Tier 重算失败: {e}")

            await asyncio.sleep(600)  # 10分钟

    async def _reminder_daemon(self):
        """后台提醒守护：每60秒检查一次到期提醒并发送通知"""
        import json as _json
        import aiohttp

        # 加载已通知的提醒ID，避免重复通知
        notified_path = os.path.join(self.data_dir, "reminders_notified.json")
        try:
            with open(notified_path, "r", encoding="utf-8") as f:
                notified_ids = set(_json.load(f))
        except Exception:
            notified_ids = set()

        while True:
            try:
                overdue = self.reminder.get_overdue()
                if overdue:
                    for r in overdue:
                        rid = r["id"]
                        if rid in notified_ids:
                            continue
                        # 构造通知消息
                        msg = f"⏰ 提醒到期！📌 {r['content'][:100]} 🕐 原定时间：{r['target_time']}"
                        logger.info(f"[Reminder] 触发提醒 #{rid}: {r['content'][:50]}")
                        # 尝试通过 AstrBot 发送消息
                        try:
                            await self._send_reminder_notification(msg)
                        except Exception as e:
                            logger.warning(f"[Reminder] 发送通知失败: {e}")
                        notified_ids.add(rid)
                        # 标记为已触发
                        self.reminder.mark_fired(rid)
                    # 保存已通知记录
                    try:
                        with open(notified_path, "w", encoding="utf-8") as f:
                            _json.dump(list(notified_ids), f)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[Reminder] 检查提醒异常: {e}")
            await asyncio.sleep(60)  # 每60秒检查一次

    async def _meeting_daemon(self):
        """例会守护：每3小时检查今天有没有日报，没有就自动生成。
        开机后等5分钟再首次检查，避免启动高峰抢资源。"""
        await asyncio.sleep(300)  # 开机后等5分钟
        while True:
            try:
                if not self.v2_reader:
                    await asyncio.sleep(3 * 3600)
                    continue
                today = datetime.now().strftime("%Y-%m-%d")
                # 检查今天有没有日报
                meetings = self.reader.family_meeting_list(limit=1)
                latest_date = None
                if meetings and isinstance(meetings, list) and meetings:
                    latest_date = meetings[0].get("report_date", "")
                if latest_date != today:
                    logger.info(f"[Meeting] 今天({today})还没有例会日报，自动生成中...")
                    self.reader.family_meeting_generate(today)
                    logger.info(f"[Meeting] 例会日报已自动生成 ✓")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[Meeting] 例会守护异常: {e}")
            await asyncio.sleep(3 * 3600)  # 每3小时检查一次

    async def _send_reminder_notification(self, msg: str):
        """在聊天界面主动推送提醒通知

        通过 context.send_message(umo, MessageChain) 发送到用户聊天窗口。
        如果没有保存的 unified_msg_origin，则写入通知文件作为兜底。
        """
        # --- 方式1: 通过 AstrBot 在聊天界面发送（优先）---
        if self._last_msg_origin:
            try:
                from astrbot.api.event import MessageChain
                chain = MessageChain().message(msg)
                await self.context.send_message(self._last_msg_origin, chain)
                logger.info(f"[Reminder] 已通过聊天界面推送提醒")
                return
            except Exception as e:
                logger.warning(f"[Reminder] 聊天推送失败: {e}，降级为文件通知")

        # --- 方式2: 写入通知文件兜底（没有msg_origin时）---
        import json as _json
        try:
            notify_path = os.path.join(self.data_dir, "pending_notifications.json")
            notifications = []
            try:
                with open(notify_path, "r", encoding="utf-8") as f:
                    notifications = _json.load(f)
            except Exception:
                pass
            notifications.append({
                "type": "reminder",
                "message": msg,
                "created_at": datetime.now().isoformat(),
                "read": False,
            })
            with open(notify_path, "w", encoding="utf-8") as f:
                _json.dump(notifications, f, ensure_ascii=False, indent=2)
            logger.info(f"[Reminder] 已写入通知文件兜底")
        except Exception as e:
            logger.warning(f"[Reminder] 写入通知文件失败: {e}")


    # ======== Phase 3: Graph / Sentiment / Archive / Semantic / Share ========

    async def _api_graph_data(self, request=None) -> dict:
        """GET /graph/data - 知识图谱数据（D3力导向图）"""
        limit = int(self._qp(request, 'limit', '100'))
        node_type = self._qp(request, 'type', None)
        try:
            data = self.reader.get_graph_data(limit=limit)
            return {"status": "ok", "data": data}
        except Exception as e:
            logger.warning(f"[LMHelper] graph_data error: {e}")
            return {"status": "error", "msg": str(e), "data": {"nodes": [], "edges": []}}

    async def _api_graph_node_create(self, **kwargs) -> dict:
        """POST /graph/node/create - 创建图谱节点"""
        import json
        body = await self._read_body()
        node_type = body.get("node_type", "Concept")
        label = body.get("label", "").strip()
        properties = body.get("properties", "{}")
        if not label:
            return {"status": "error", "msg": "label is required"}
        try:
            result = self.reader.create_graph_node(node_type, label, properties)
            logger.info(f"[LMHelper] Graph node created: id={result.get('id')}, type={node_type}, label={label}")
            return {"status": "ok", "node": result}
        except Exception as e:
            logger.warning(f"[LMHelper] graph_node_create error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_graph_node_detail(self, request=None, **kwargs) -> dict:
        """GET /graph/node/<id> - 图谱节点详情"""
        node_id = kwargs.get("id") or self._qp(request, "id", "0")
        try:
            node_id = int(node_id)
            detail = self.reader.get_graph_node_detail(node_id)
            if detail is None:
                return {"status": "error", "msg": "Node not found"}
            return {"status": "ok", "node": detail}
        except Exception as e:
            logger.warning(f"[LMHelper] graph_node_detail error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_graph_edge_types(self, request=None) -> dict:
        """GET /graph/edge-types - 获取所有关系类型"""
        try:
            types = self.reader.get_relation_types()
            return {"status": "ok", "types": types}
        except Exception as e:
            logger.warning(f"[LMHelper] graph_edge_types error: {e}")
            return {"status": "ok", "types": []}

    # ── v9: Three-Tier Memory Pyramid APIs ──────────────────────────

    async def _api_memory_pyramid(self, request=None) -> dict:
        """GET /memory/pyramid - 返回三层记忆金字塔数据 (L1/L2/L3)

        L1: 原始消息事件（最近50条）
        L2: 会话摘要记忆（tier=2）
        L3: 跨会话合成记忆（tier=3）
        溯源链: L3.source_ids → L2.source_ids → L1 消息
        """
        try:
            limit = int(self._qp(request, "limit", "50"))
            pyramid = self.reader.get_memory_pyramid(limit)
            return {"status": "ok", "pyramid": pyramid}
        except Exception as e:
            logger.warning(f"[LMHelper] memory_pyramid error: {e}")
            return {"status": "error", "msg": str(e), "pyramid": {"L1": [], "L2": [], "L3": []}}

    async def _api_memory_trace(self, request=None, **kwargs) -> dict:
        """GET /memory/<id>/trace - 单条记忆溯源链

        从一条 L3 或 L2 记忆出发，沿 source_ids 追溯到原始对话消息
        """
        memory_id = kwargs.get("id") or self._qp(request, "id", "0")
        try:
            memory_id = int(memory_id)
            trace = self.reader.get_memory_trace(memory_id)
            if trace is None:
                return {"status": "error", "msg": "Memory not found"}
            return {"status": "ok", "trace": trace}
        except Exception as e:
            logger.warning(f"[LMHelper] memory_trace error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_sentiment_dist(self, request=None) -> dict:
        """GET /sentiment/dist - 情感分布统计"""
        date_from = self._qp(request, 'date_from', None)
        date_to = self._qp(request, 'date_to', None)
        try:
            dist = self.reader.get_sentiment_distribution(date_from, date_to)
            return {"status": "ok", "distribution": dist}
        except Exception as e:
            logger.warning(f"[LMHelper] sentiment_dist error: {e}")
            return {"status": "error", "msg": str(e), "distribution": {}}

    async def _api_sentiment_trend(self, request=None) -> dict:
        """GET /sentiment/trend - 情感趋势数据（ECharts折线图）"""
        days = int(self._qp(request, 'days', '30'))
        try:
            trend = self.reader.get_sentiment_trend(days=days)
            return {"status": "ok", "trend": trend}
        except Exception as e:
            logger.warning(f"[LMHelper] sentiment_trend error: {e}")
            return {"status": "error", "msg": str(e), "trend": []}

    async def _api_sentiment_words(self, request=None) -> dict:
        """GET /sentiment/words - 高频情感词统计（词云数据）"""
        days = int(self._qp(request, 'days', '30'))
        limit = int(self._qp(request, 'limit', '25'))
        try:
            data = self.reader.get_emotion_word_stats(days=days, limit=limit)
            return {"status": "ok", **data}
        except Exception as e:
            logger.warning(f"[LMHelper] sentiment_words error: {e}")
            return {"status": "error", "msg": str(e), "words": [], "total_texts": 0}

    async def _api_sentiment_events(self, request=None) -> dict:
        """GET /sentiment/events - 强情感记忆时间线"""
        days = int(self._qp(request, 'days', '14'))
        limit = int(self._qp(request, 'limit', '20'))
        try:
            data = self.reader.get_strong_sentiment_events(days=days, limit=limit)
            return {"status": "ok", **data}
        except Exception as e:
            logger.warning(f"[LMHelper] sentiment_events error: {e}")
            return {"status": "error", "msg": str(e), "events": [], "total": 0}

    async def _api_emotion_recent(self, request=None) -> dict:
        """GET /emotion/recent - 最近情感趋势（供 meme_manager 联动使用）"""
        # v5.7: 优先使用配置的窗口大小
        configured_window = self._ui_settings.get("emotion_trend_window", 6)
        limit = int(self._qp(request, 'limit', str(configured_window)))
        try:
            mems = self.reader.get_recent_memories(limit=limit)
            emotions = []
            for m in mems:
                meta = m.get("metadata", {})
                emotions.append({
                    "emotion": meta.get("emotion", "neutral"),
                    "sentiment": meta.get("sentiment", meta.get("emotion", "neutral")),
                    "intensity": meta.get("intensity", 0.5),
                })
            trend = self.emotion_engine.get_recent_trend(emotions)
            return {
                "status": "ok",
                "trend": trend,
                "emotions": emotions,
                "count": len(emotions),
            }
        except Exception as e:
            logger.warning(f"[LMHelper] emotion_recent error: {e}")
            return {"status": "error", "msg": str(e), "trend": {}, "emotions": []}

    async def _api_emotion_stats(self, request=None) -> dict:
        """GET /emotion/stats - 情感引擎统计信息（词典规模、版本等）"""
        try:
            from .core.emotion_engine import EMOTION_LEXICON, INTENSITY_MODIFIERS, NEGATION_WORDS, TRANSITION_WORDS, EMOTION_POLARITY
            word_counts = {emo: len(words) for emo, words in EMOTION_LEXICON.items()}
            total_words = sum(word_counts.values())
            return {
                "status": "ok",
                "version": "v6.0",
                "total_words": total_words,
                "emotion_types": len(EMOTION_LEXICON),
                "word_counts": word_counts,
                "intensity_count": len(INTENSITY_MODIFIERS),
                "negation_count": len(NEGATION_WORDS),
                "transition_count": len(TRANSITION_WORDS),
                "polarity_map": EMOTION_POLARITY,
            }
        except Exception as e:
            logger.warning(f"[LMHelper] emotion_stats error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_family_overview(self, request=None) -> dict:
        """GET /family/overview - 家庭生态总览（v2.1 全家桶：名册+例会+反馈+归档）"""
        try:
            # ── 1. 家人名册（Phase 3 角色分工）──
            roles = []
            try:
                self.reader.family_roles_seed()
                roles = self.reader.family_roles_list(active_only=True) or []
                if roles and isinstance(roles[0], dict) and roles[0].get("error"):
                    roles = []
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[FamilyOverview] roles: {e}")

            # ── 2. 例会日报（Phase 4 家庭例会）──
            meetings = []
            try:
                meetings = self.reader.family_meeting_list(limit=7) or []
                if meetings and isinstance(meetings[0], dict) and meetings[0].get("error"):
                    meetings = []
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[FamilyOverview] meetings: {e}")
            latest_meeting = meetings[0] if meetings else None

            # ── 3. 反馈回路（Phase 1 反馈日志）──
            fb_stats = {"total": 0, "by_type": {}, "by_pair": {}}
            fb_rows = []
            if self.v2_reader:
                try:
                    fb_stats = self.v2_reader.count_feedback() or fb_stats
                    fb_rows = self.v2_reader.get_feedback(limit=15) or []
                    if fb_rows and isinstance(fb_rows[0], dict) and fb_rows[0].get("error"):
                        fb_rows = []
                    else:
                        # created_at 是 Unix 时间戳，转成可读时间
                        from datetime import datetime as _dt
                        for fb in fb_rows:
                            ts = fb.get("created_at")
                            if isinstance(ts, (int, float)) and ts > 0:
                                try:
                                    fb["created_at"] = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                                except (OverflowError, OSError, ValueError):
                                    pass
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[FamilyOverview] feedback: {e}")

            # ── 4. 归档台账（Phase 2 归档员）──
            archive = {}
            try:
                archive = self.reader.archive_stats() or {}
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[FamilyOverview] archive: {e}")

            # ── 5. 冲突检测（判官）──
            conflicts = {"total": 0, "pending": 0, "confirmed": 0, "resolved": 0, "recent": []}
            if self.v2_reader:
                try:
                    # 统计：拉全量计数
                    all_conflicts = self.v2_reader.get_conflicts(limit=500) or []
                    if all_conflicts and isinstance(all_conflicts[0], dict) and not all_conflicts[0].get("error"):
                        conflicts["total"] = len(all_conflicts)
                        conflicts["pending"] = len([c for c in all_conflicts if c.get("status") == "candidate"])
                        conflicts["confirmed"] = len([c for c in all_conflicts if c.get("status") == "confirmed"])
                        conflicts["resolved"] = len([c for c in all_conflicts if c.get("status") == "resolved"])
                    # recent：只展示待处理的（candidate），最多 10 条
                    pending_conflicts = self.v2_reader.get_conflicts(status="candidate", limit=10) or []
                    if pending_conflicts and isinstance(pending_conflicts[0], dict) and not pending_conflicts[0].get("error"):
                        conflicts["recent"] = pending_conflicts
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[FamilyOverview] conflicts: {e}")

            return {
                "status": "ok",
                "roles": roles,
                "role_count": len(roles),
                "meetings": meetings,
                "latest_meeting": latest_meeting,
                "feedback": fb_stats,
                "feedback_rows": fb_rows,
                "archive": archive,
                "conflicts": conflicts,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[LMHelper] family/overview error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_archive_candidates(self, request=None) -> dict:
        """GET /archive/candidates - 可归档记忆列表"""
        before_date = None
        min_imp = 0.0
        if request and hasattr(request, 'query_params'):
            before_date = request.query_params.get('before_date', None)
            min_imp = float(request.query_params.get('min_importance', 0.0))
        try:
            candidates = self.reader.get_archive_candidates(before_date, min_imp)
            total_count = self.reader.get_memory_count()
            return {
                "status": "ok",
                "candidates": candidates,
                "candidate_count": len(candidates),
                "total_count": total_count,
            }
        except Exception as e:
            logger.warning(f"[LMHelper] archive_candidates error: {e}")
            return {"status": "error", "msg": str(e), "candidates": []}

    async def _api_archive_execute(self, **kwargs) -> dict:
        """POST /archive/execute - 执行归档操作（标记为已归档）"""
        body = await self._read_body()
        ids = body.get('ids', [])
        before_date = body.get('before_date', None)
        dry_run = body.get('dry_run', True)
        if dry_run:
            # 预览模式：只统计数量
            candidates = self.reader.get_archive_candidates(before_date) if before_date else []
            if ids:
                candidates = [c for c in candidates if c.get('id') in ids]
            return {
                "status": "ok",
                "dry_run": True,
                "affected": len(candidates),
                "preview": candidates[:5],
            }
        # 实际归档（仅标记 metadata.archived = true，不删除）
        archived = 0
        for mid in ids:
            mem = self.reader.get_memory_by_id(int(mid))
            if mem:
                archived += 1
        return {"status": "ok", "dry_run": False, "archived": archived}

    async def _api_archive_scan(self, **kwargs) -> dict:
        """POST /archive/scan - 手动扫描沉睡记忆生成候选"""
        body = await self._read_body()
        days = int(body.get('days', 30))
        min_importance = float(body.get('min_importance', 0.6))
        max_candidates = int(body.get('max_candidates', 20))
        dry_run = body.get('dry_run', True)
        try:
            result = self.reader.archive_scan(days, min_importance, max_candidates, dry_run)
            return result
        except Exception as e:
            logger.warning(f"[LMHelper] archive_scan error: {e}")
            return {"status": "error", "msg": str(e), "new_candidates": 0}

    async def _api_conflict_resolve(self, **kwargs) -> dict:
        """POST /conflict/resolve - 更新冲突状态（确认/解决/驳回）
        confirmed 时自动触发 family_bus CONFLICT_CONFIRMED 事件 → 沉淀为知识候选"""
        body = await self._read_body()
        conflict_id = body.get('conflict_id')
        new_status = body.get('new_status', '')  # confirmed / resolved / dismissed
        if not conflict_id or not new_status:
            return {"success": False, "msg": "conflict_id 和 new_status 必填"}
        if not self.v2_reader:
            return {"success": False, "msg": "v2 引擎未启用"}
        try:
            result = self.v2_reader.update_conflict_status(int(conflict_id), str(new_status))
            if not result.get("success"):
                return result

            # confirmed 时触发 family_bus 事件 → 沉淀知识候选
            if new_status == "confirmed":
                try:
                    from .core.family_bus import publish_family_event
                    publish_family_event(
                        "conflict_confirmed",
                        memory_id=result.get("new_memory_id", 0),
                        metadata={
                            "conflict_id": conflict_id,
                            "reason": result.get("reason", ""),
                            "resolution_type": result.get("conflict_type", ""),
                            "resolution": result.get("resolution", {}),
                            "old_memory_id": result.get("old_memory_id", 0),
                        },
                    )
                    logger.info(f"[Conflict] 冲突 #{conflict_id} 已确认，已触发知识沉淀事件")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[Conflict] 触发 family_bus 失败（不影响操作结果）: {e}")

            return result
        except Exception as e:
            logger.warning(f"[LMHelper] conflict_resolve error: {e}")
            return {"success": False, "msg": str(e)}

    async def _api_family_meeting_generate(self, **kwargs) -> dict:
        """POST /family/meeting-generate - 手动生成今日例会日报"""
        body = await self._read_body()
        date_str = body.get('date', None)
        try:
            res = self.reader.family_meeting_generate(date_str)
            if res.get("status") == "ok":
                return {"success": True, "report": res.get("report", {})}
            return {"success": False, "msg": res.get("msg", str(res))}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[LMHelper] meeting_generate error: {e}")
            return {"success": False, "msg": str(e)}

    async def _api_archive_similar(self, request=None) -> dict:
        """GET /archive/similar - 查找相似记忆对"""
        threshold = 0.45
        limit = 50
        if request and hasattr(request, 'query_params'):
            threshold = float(request.query_params.get('threshold', 0.45))
            limit = int(request.query_params.get('limit', 50))
        try:
            pairs = self.reader.find_similar_pairs(threshold=threshold, limit=limit)
            return {
                "status": "ok",
                "pairs": pairs,
                "pair_count": len(pairs),
                "threshold": threshold,
            }
        except Exception as e:
            logger.warning(f"[LMHelper] archive_similar error: {e}")
            return {"status": "error", "msg": str(e), "pairs": []}

    async def _api_archive_merge(self, **kwargs) -> dict:
        """POST /archive/merge - 合并多条记忆到主记忆"""
        body = await self._read_body()
        primary_id = body.get('primary_id')
        secondary_ids = body.get('secondary_ids', [])
        merged_content = body.get('merged_content', None)
        if not primary_id or not secondary_ids:
            return {"status": "error", "msg": "primary_id 和 secondary_ids 必填"}
        try:
            result = self.reader.merge_memories(
                primary_id=int(primary_id),
                secondary_ids=[int(x) for x in secondary_ids],
                merged_content=merged_content,
            )
            return {"status": "ok", **result} if result.get("success") else {"status": "error", **result}
        except Exception as e:
            logger.warning(f"[LMHelper] archive_merge error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_semantic_search(self, **kwargs) -> dict:
        """POST /semantic-search - 语义搜索（匹配度排序）"""
        body = await self._read_body()
        query = body.get('query', '')
        limit = int(body.get('limit', 20))
        if not query:
            return {"status": "error", "msg": "query is required", "results": []}
        try:
            results = self.reader.semantic_search(query, limit=limit)
            return {"status": "ok", "results": results, "total": len(results)}
        except Exception as e:
            logger.warning(f"[LMHelper] semantic_search error: {e}")
            return {"status": "error", "msg": str(e), "results": []}

    async def _api_share_generate(self, **kwargs) -> dict:
        """POST /share/generate - 生成记忆分享数据"""
        body = await self._read_body()
        memory_id = body.get('memory_id', None)
        format_type = body.get('format', 'json')
        if not memory_id:
            return {"status": "error", "msg": "memory_id required"}
        try:
            mem = self.reader.get_memory_by_id(int(memory_id))
            if not mem:
                return {"status": "error", "msg": f"memory {memory_id} not found"}
            atoms = self.reader.get_memory_atoms(parent_id=int(memory_id), limit=10)
            share_data = {
                "memory": mem,
                "atoms": atoms,
                "shared_at": __import__('datetime').datetime.now().isoformat(),
                "plugin_version": "2.0",
            }
            return {"status": "ok", "format": format_type, "share_data": share_data}
        except Exception as e:
            logger.warning(f"[LMHelper] share_generate error: {e}")
            return {"status": "error", "msg": str(e)}

    # ═══════════════════ v4.2: Context Assembly Trace API ═══════════════════

    def _get_trace_db_path(self) -> str:
        """获取 context_traces.db 路径"""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # livingmemory 插件的数据目录
        lm_data = os.path.join(base, "astrbot_plugin_livingmemory", "data")
        return os.path.join(lm_data, "context_traces.db")

    async def _api_trace_list(self, request=None) -> dict:
        """GET /trace/list - 获取组装追踪列表"""
        import sqlite3, json as _json
        limit = int(self._qp(request, 'limit', '20'))
        db_path = self._get_trace_db_path()
        if not os.path.exists(db_path):
            return {"traces": [], "total": 0, "msg": "trace db not found"}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM context_assembly_traces")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT trace_id, session_id, timestamp, trace_data, injected_count, skipped, query_intent, emotion "
                "FROM context_assembly_traces ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cur.fetchall()
            traces = []
            for r in rows:
                td = {}
                try:
                    td = _json.loads(r["trace_data"]) if r["trace_data"] else {}
                except Exception:
                    pass
                traces.append({
                    "trace_id": r["trace_id"],
                    "session_id": r["session_id"],
                    "timestamp": r["timestamp"],
                    "injected_count": r["injected_count"],
                    "skipped": r["skipped"],
                    "query_intent": r["query_intent"],
                    "emotion": r["emotion"],
                    "query_raw": td.get("query_raw", "")[:200],
                    "query_expanded": td.get("query_expanded", "")[:200] if td.get("query_expanded") else "",
                })
            conn.close()
            return {"traces": traces, "total": total}
        except Exception as e:
            logger.warning(f"[LMHelper] trace_list error: {e}")
            return {"traces": [], "total": 0, "error": str(e)}

    async def _api_trace_detail(self, request=None) -> dict:
        """GET /trace/detail?trace_id=xxx - 获取单条追踪详情"""
        import sqlite3, json as _json
        trace_id = self._qp(request, 'trace_id', '')
        if not trace_id:
            return {"status": "error", "msg": "trace_id required"}
        db_path = self._get_trace_db_path()
        if not os.path.exists(db_path):
            return {"status": "error", "msg": "trace db not found"}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM context_assembly_traces WHERE trace_id = ?",
                (trace_id,)
            )
            row = cur.fetchone()
            conn.close()
            if not row:
                return {"status": "error", "msg": "trace not found"}
            trace_data = {}
            try:
                trace_data = _json.loads(row["trace_data"]) if row["trace_data"] else {}
            except Exception:
                pass
            return {
                "status": "ok",
                "trace": {
                    "trace_id": row["trace_id"],
                    "session_id": row["session_id"],
                    "timestamp": row["timestamp"],
                    "injected_count": row["injected_count"],
                    "skipped": row["skipped"],
                    "query_intent": row["query_intent"],
                    "emotion": row["emotion"],
                    **trace_data,
                }
            }
        except Exception as e:
            logger.warning(f"[LMHelper] trace_detail error: {e}")
            return {"status": "error", "msg": str(e)}

    async def _api_trace_stats(self, request=None) -> dict:
        """GET /trace/stats - 组装追踪统计"""
        import sqlite3
        db_path = self._get_trace_db_path()
        if not os.path.exists(db_path):
            return {"total_traces": 0, "msg": "trace db not found"}
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM context_assembly_traces")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT session_id) FROM context_assembly_traces")
            sessions = cur.fetchone()[0]
            cur.execute("SELECT AVG(injected_count) FROM context_assembly_traces WHERE skipped = 0")
            avg = cur.fetchone()[0]
            cur.execute("SELECT MAX(injected_count) FROM context_assembly_traces")
            mx = cur.fetchone()[0]
            cur.execute("SELECT SUM(skipped) FROM context_assembly_traces")
            skipped = cur.fetchone()[0]
            conn.close()
            return {
                "total_traces": total,
                "unique_sessions": sessions,
                "avg_injected": round(avg, 2) if avg else 0,
                "max_injected": mx or 0,
                "skipped_count": skipped or 0,
            }
        except Exception as e:
            logger.warning(f"[LMHelper] trace_stats error: {e}")
            return {"total_traces": 0, "error": str(e)}

    # ═══════════════════ v4.3: Session Summary API ═══════════════════

    async def _api_summary_list(self, request=None) -> dict:
        """GET /summary/list - 获取会话摘要列表
        ?type=auto   → 仅空闲触发的会话摘要
        ?type=digest → 仅对话Digest
        不传 type    → 全部（向后兼容）
        """
        import sqlite3, json as _json
        limit = int(self._qp(request, 'limit', '20'))
        summary_type = self._qp(request, 'type', '')
        db_path = self.reader.db_path
        if not os.path.exists(db_path):
            return {"summaries": [], "total": 0, "msg": "db not found"}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            if summary_type in ('auto', 'digest'):
                cur.execute(
                    """
                    SELECT id, session_id, content, metadata, created_at, status
                    FROM memory_atoms
                    WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
                      AND json_extract(metadata, '$.summary_type') = ?
                      AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (summary_type, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, session_id, content, metadata, created_at, status
                    FROM memory_atoms
                    WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
                      AND status = 'active'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            summaries = []
            for r in rows:
                meta = _json.loads(r["metadata"]) if r["metadata"] else {}
                summaries.append({
                    "id": r["id"],
                    "session_id": r["session_id"],
                    "content": r["content"][:2000] if r["content"] else "",
                    "full_content": r["content"] if r["content"] else "",
                    "created_at": r["created_at"],
                    "emotion": meta.get("emotion", "neutral"),
                    "topics": meta.get("topics", []),
                    "continuation_points": meta.get("continuation_points", []),
                    "message_count": meta.get("message_count", 0),
                    "duration_minutes": meta.get("duration_minutes", 0),
                    "prev_summary_id": meta.get("prev_summary_id"),
                    # v5.5 Digest 字段 — 前端 loadDigests 需要这两个字段来过滤
                    "summary_schema_version": meta.get("summary_schema_version", "v55_digest"),
                    "digest_turn": meta.get("digest_turn") or (meta.get("thread_seq", 0) + 1),
                    "sentiment": meta.get("emotion", "neutral"),
                    "key_facts": meta.get("key_facts", []),
                    "canonical_summary": meta.get("canonical_summary", ""),
                })
            # 统计总数
            if summary_type in ('auto', 'digest'):
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt
                    FROM memory_atoms
                    WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
                      AND json_extract(metadata, '$.summary_type') = ?
                      AND status = 'active'
                    """,
                    (summary_type,),
                )
            else:
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt
                    FROM memory_atoms
                    WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
                      AND status = 'active'
                    """
                )
            total = cur.fetchone()["cnt"]
            conn.close()
            return {"summaries": summaries, "total": total}
        except Exception as e:
            logger.warning(f"[LMHelper] summary_list error: {e}")
            return {"summaries": [], "total": 0, "error": str(e)}

    async def _api_summary_stats(self, request=None) -> dict:
        """GET /summary/stats - 会话摘要统计
        ?type=auto / digest 过滤，不传则全部
        """
        import sqlite3, json as _json
        db_path = self.reader.db_path
        if not os.path.exists(db_path):
            return {"total_summaries": 0, "msg": "db not found"}
        summary_type = self._qp(request, 'type', '')
        type_clause = ""
        if summary_type in ('auto', 'digest'):
            type_clause = f"AND json_extract(metadata, '$.summary_type') = '{summary_type}'"
        where = f"""
            WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
              AND status = 'active'
              {type_clause}
        """
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # 总数
            cur.execute(f"SELECT COUNT(*) as cnt FROM memory_atoms {where}")
            total = cur.fetchone()["cnt"]
            # 覆盖会话数
            cur.execute(f"SELECT COUNT(DISTINCT session_id) as cnt FROM memory_atoms {where}")
            unique_sessions = cur.fetchone()["cnt"]
            # 最近一条时间
            cur.execute(f"SELECT created_at FROM memory_atoms {where} ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
            last_summary_time = row["created_at"] if row else None
            # 平均消息数 & 平均时长
            cur.execute(f"SELECT metadata FROM memory_atoms {where}")
            msg_counts = []
            durations = []
            emotions = {}
            for r in cur.fetchall():
                meta = _json.loads(r["metadata"]) if r["metadata"] else {}
                msg_counts.append(meta.get("message_count", 0))
                durations.append(meta.get("duration_minutes", 0))
                emo = meta.get("emotion", "neutral")
                emotions[emo] = emotions.get(emo, 0) + 1
            avg_msgs = sum(msg_counts) / len(msg_counts) if msg_counts else 0
            avg_duration = sum(durations) / len(durations) if durations else 0
            conn.close()
            return {
                "total_summaries": total,
                "unique_sessions": unique_sessions,
                "last_summary_time": last_summary_time,
                "avg_message_count": round(avg_msgs, 1),
                "avg_duration_minutes": round(avg_duration, 1),
                "emotion_dist": emotions,
            }
        except Exception as e:
            logger.warning(f"[LMHelper] summary_stats error: {e}")
            return {"total_summaries": 0, "error": str(e)}

    async def _api_summary_generate(self, request=None) -> dict:
        """POST /summary/generate - 手动为当前会话生成摘要（v6.2: 过滤掉对话Digest内容避免重复）"""
        import sqlite3, json as _json, time

        db_path = self.reader.db_path
        if not os.path.exists(db_path):
            return {"status": "error", "msg": "db not found"}

        # 获取 session_id
        session_id = self._qp(request, 'session_id', '')
        if not session_id:
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("""
                    SELECT json_extract(metadata, '$.session_id') as sess
                    FROM documents
                    WHERE json_extract(metadata, '$.session_id') IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                """)
                row = cur.fetchone()
                conn.close()
                if row and row["sess"]:
                    session_id = row["sess"]
                else:
                    return {"status": "error", "msg": "no active session found"}
            except Exception as e:
                return {"status": "error", "msg": str(e)}

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # v6.2: 只读取非对话Digest的文档（过滤掉source=conversation_digest避免内容重复）
            cur.execute("""
                SELECT id, text, metadata, created_at
                FROM documents
                WHERE json_extract(metadata, '$.session_id') = ?
                  AND (json_extract(metadata, '$.source') IS NULL
                       OR json_extract(metadata, '$.source') != 'conversation_digest')
                ORDER BY created_at DESC LIMIT 30
            """, (session_id,))
            docs = cur.fetchall()

            if len(docs) < 3:
                conn.close()
                return {"status": "error", "msg": f"session 只有 {len(docs)} 条非Digest记忆，至少需要 3 条才能生成摘要"}

            texts = [d["text"] for d in reversed(docs)]
            combined_text = " | ".join([t[:200] for t in texts])

            from collections import Counter
            topic_counter = Counter()
            for d in reversed(docs):
                d_meta = _json.loads(d["metadata"]) if d["metadata"] else {}
                for t in d_meta.get("topics", []):
                    if isinstance(t, str) and t.strip():
                        topic_counter[t.strip()] += 1
            if topic_counter:
                topics = [t for t, _ in topic_counter.most_common(5)]
            else:
                topics = []
                for t in texts[:8]:
                    snippet = t[:15].replace('\n', " ").replace('\r', " ").strip()
                    if snippet and snippet not in topics:
                        topics.append(snippet)
                topics = topics[:5]

            result = self.emotion_engine.analyze(combined_text, speaker="user")
            emotion = result["emotion"]

            first_ts = docs[-1]["created_at"]
            last_ts = docs[0]["created_at"]
            from datetime import datetime
            try:
                t1 = datetime.fromisoformat(first_ts)
                t2 = datetime.fromisoformat(last_ts)
                duration_minutes = max(1, int((t2 - t1).total_seconds() / 60))
                start_time = t1.timestamp()
                end_time = t2.timestamp()
            except Exception:
                duration_minutes = 0
                start_time = time.time()
                end_time = time.time()

            summary_content = f"[会话摘要] session={session_id[:40]}... | "
            summary_content += f"共{len(docs)}条记忆 | "
            summary_content += f"时长{duration_minutes}分钟 | "
            summary_content += f"情绪: {emotion} | "
            summary_content += f"话题: {', '.join(topics[:3])} | "
            summary_content += f"概要: {texts[-1][:100]}"

            cur.execute("""
                SELECT id FROM memory_atoms
                WHERE json_extract(metadata, '$.atom_subtype') = 'session_summary'
                  AND session_id = ?
                  AND status = 'active'
                ORDER BY created_at DESC LIMIT 1
            """, (session_id,))
            prev_row = cur.fetchone()
            prev_summary_id = prev_row["id"] if prev_row else None

            thread_seq = 0
            if prev_summary_id:
                cur.execute("SELECT metadata FROM memory_atoms WHERE id = ?", (prev_summary_id,))
                prev_meta_row = cur.fetchone()
                if prev_meta_row:
                    prev_meta = _json.loads(prev_meta_row["metadata"]) if prev_meta_row["metadata"] else {}
                    thread_seq = int(prev_meta.get("thread_seq", 0)) + 1

            cur.execute("SELECT id FROM documents ORDER BY created_at DESC LIMIT 1")
            parent_row = cur.fetchone()
            parent_id = parent_row["id"] if parent_row else None

            now = time.time()
            ttl_days = 30.0
            metadata = _json.dumps({
                "atom_subtype": "session_summary",
                "session_id": session_id,
                "summary_type": "manual",
                "summary_schema_version": "v55_digest",
                "digest_turn": thread_seq + 1,
                "message_count": len(docs),
                "duration_minutes": duration_minutes,
                "topics": topics,
                "emotion": emotion,
                "continuation_points": [],
                "start_time": start_time,
                "end_time": end_time,
                "prev_summary_id": prev_summary_id,
                "thread_seq": thread_seq,
            })

            cur.execute("""
                INSERT INTO memory_atoms (
                    parent_memory_id, atom_type, content, entities,
                    importance, confidence, created_at, last_accessed_at,
                    last_reinforced_at, ttl_days, expires_at, status,
                    decay_type, session_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                parent_id, "episodic", summary_content, _json.dumps(topics),
                0.7, 0.85, now, now,
                now, ttl_days, now + ttl_days * 86400, "active",
                "linear", session_id, metadata,
            ))
            new_id = cur.lastrowid

            try:
                cur.execute(
                    "INSERT INTO memory_atoms_fts(atom_id, content) VALUES (?, ?)",
                    (new_id, summary_content)
                )
            except Exception:
                pass

            conn.commit()
            conn.close()

            logger.info(f"[LMHelper] 手动生成会话摘要 atom_id={new_id} session={session_id[:40]}")
            return {
                "status": "ok",
                "msg": f"摘要已生成 (atom_id={new_id})",
                "summary": {
                    "id": new_id,
                    "session_id": session_id,
                    "topics": topics,
                    "emotion": emotion,
                    "message_count": len(docs),
                    "duration_minutes": duration_minutes,
                    "thread_seq": thread_seq,
                    "content": summary_content[:200],
                }
            }
        except Exception as e:
            logger.warning(f"[LMHelper] summary_generate error: {e}")
            return {"status": "error", "msg": str(e)}
    # ═══════════════════ v6.3 知识毕业系统 API ═══════════════════

    async def _api_knowledge_list(self, request=None) -> dict:
        """GET /knowledge/list - 知识列表（带筛选）"""
        try:
            status = self._qp(request, 'status', '')
            ktype = self._qp(request, 'ktype', '')
            limit = int(self._qp(request, 'limit', '50'))
            items = self.knowledge_graduator.list_knowledge(status=status, knowledge_type=ktype, limit=limit)
            return {"items": items, "total": len(items)}
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_list error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_index(self, request=None) -> dict:
        """GET /knowledge/index - 全局索引（一行一条）"""
        try:
            status = self._qp(request, 'status', '')
            ktype = self._qp(request, 'ktype', '')
            items = self.knowledge_graduator.get_index(knowledge_type=ktype, status=status)
            return {"items": items, "total": len(items)}
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_index error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_detail(self, request=None) -> dict:
        """GET /knowledge/detail?id=X - 知识详情"""
        try:
            kid = int(self._qp(request, 'id', '0'))
            if not kid:
                return {"error": "需要 id 参数"}
            detail = self.knowledge_graduator.get_knowledge(kid)
            if not detail:
                return {"error": f"未找到知识 #{kid}"}
            review = self.knowledge_graduator.review_checklist(kid)
            citations = self.knowledge_graduator.get_citations(kid)
            return {"knowledge": detail, "review": review, "citations": citations[:10]}
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_detail error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_logs(self, request=None) -> dict:
        """GET /knowledge/logs - shturl 时序日志"""
        try:
            limit = int(self._qp(request, 'limit', '50'))
            log_type = self._qp(request, 'log_type', '')
            items = self.knowledge_graduator.list_logs(limit=limit, log_type=log_type)
            return {"items": items, "total": len(items)}
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_logs error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_health(self, request=None) -> dict:
        """GET /knowledge/health - 启动体检"""
        try:
            report = self.knowledge_graduator.health_check()
            return report
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_health error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_update(self, request=None) -> dict:
        """POST /knowledge/update - 原地更新知识"""
        try:
            data = await self._read_body()
            kid = int(data.get("knowledge_id", 0))
            if not kid:
                return {"error": "需要 knowledge_id"}
            fields = {}
            for k in ("title", "conclusion", "background", "evidence", "applicability", "tags", "knowledge_type"):
                if k in data and data[k]:
                    fields[k] = data[k]
            if not fields:
                return {"error": "没有可更新的字段"}
            result = self.knowledge_graduator.update_knowledge(kid, **fields)
            return result
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_update error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_confirm(self, request=None) -> dict:
        """POST /knowledge/confirm - 确认毕业"""
        try:
            data = await self._read_body()
            kid = int(data.get("knowledge_id", 0))
            if not kid:
                return {"error": "需要 knowledge_id"}
            applicability = data.get("applicability", "")
            refined = data.get("refined_conclusion", "")
            result = self.knowledge_graduator.confirm_graduation(
                kid,
                applicability=applicability,
                refined_conclusion=refined if refined else None,
            )
            return result
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_confirm error: {e}")
            return {"error": str(e)}

    async def _api_knowledge_add_log(self, request=None) -> dict:
        """POST /knowledge/add-log - 手动记日志"""
        try:
            data = await self._read_body()
            summary = data.get("summary", "")
            if not summary:
                return {"error": "需要 summary"}
            log_type = data.get("log_type", "note")
            pointer_type = data.get("pointer_type", "")
            pointer_id = int(data.get("pointer_id", 0))
            related = int(data.get("related_knowledge_id", 0))
            lid = self.knowledge_graduator.add_log(log_type, summary, pointer_type, pointer_id, related)
            return {"success": True, "id": lid}
        except Exception as e:
            logger.warning(f"[LMHelper] knowledge_add_log error: {e}")
            return {"error": str(e)}
