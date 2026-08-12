# -*- coding: utf-8 -*-
"""
F2 - 错误学习系统 v4.0
参考 self-improvement skill 设计，新增：
- 学习分类（correction/insight/knowledge_gap/best_practice）
- 功能请求记录
- 优先级系统
- 状态管理
- 自我反思机制
- 学习确认流程
"""
import sqlite3
import os
from datetime import datetime
from astrbot.api import logger

# ── 关键词库 ──

CORRECTION_KEYWORDS = [
    "不对", "错了", "不是", "错啦", "错了哦", "不对哦",
    "不是这样的", "说错了", "搞错了", "你记错了",
    "其实应该是", "不要这样做", "换个方式",
]

INSIGHT_KEYWORDS = [
    "原来如此", "我明白了", "原来是因为", "恍然大悟",
    "学到了", "涨知识了", "原来是这样",
]

KNOWLEDGE_GAP_KEYWORDS = [
    "我不知道", "不了解", "没听说过", "这是什么",
    "怎么做的", "为什么", "能解释一下吗",
]

TOOL_ERROR_PATTERNS = [
    r"工具.*失败", r"调用.*失败", r"发送.*失败",
    r"Error", r"Traceback", r"exception",
    r"定时任务.*失败", r"提醒.*失败",
]

# ── 学习类型枚举 ──

class LearningType:
    CORRECTION = "correction"           # 用户纠正
    INSIGHT = "insight"                 # 洞察/发现
    KNOWLEDGE_GAP = "knowledge_gap"     # 知识差距
    BEST_PRACTICE = "best_practice"     # 最佳实践
    TOOL_ERROR = "tool_error"           # 工具错误
    FEATURE_REQUEST = "feature_request" # 功能请求

# ── 优先级枚举 ──

class Priority:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

# ── 状态枚举 ──

class Status:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    PROMOTED = "promoted"  # 已提升到长期记忆


class ErrorLearner:
    def __init__(self, reader, db_dir: str):
        self.reader = reader
        self.db_path = os.path.join(db_dir, "error_lessons.db")
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            # 主表：学习记录
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scene TEXT DEFAULT '',
                    error_content TEXT DEFAULT '',
                    user_correction TEXT DEFAULT '',
                    solution TEXT DEFAULT '',
                    tool_name TEXT DEFAULT '',
                    tags TEXT DEFAULT 'error_lesson',
                    
                    -- v3.0 新增字段
                    learning_type TEXT DEFAULT 'correction',
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    confidence REAL DEFAULT 0.5,
                    occurrence_count INTEGER DEFAULT 1,
                    last_seen_at TEXT,
                    
                    -- 原有字段
                    importance REAL DEFAULT 0.9,
                    fixed INTEGER DEFAULT 0,
                    fix_verified INTEGER DEFAULT 0,
                    recurrence_count INTEGER DEFAULT 0,
                    learned_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # 新增表：功能请求
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_content TEXT DEFAULT '',
                    user_context TEXT DEFAULT '',
                    priority TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            
            # v5.4: 补齐旧表缺失的列（CREATE TABLE IF NOT EXISTS 不会修改已有表）
            _migration_cols = {
                "occurrence_count": "INTEGER DEFAULT 1",
                "last_seen_at": "TEXT",
                "learning_type": "TEXT DEFAULT 'correction'",
                "priority": "TEXT DEFAULT 'medium'",
                "status": "TEXT DEFAULT 'pending'",
                "confidence": "REAL DEFAULT 0.5",
            }
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(error_lessons)").fetchall()}
            for col, typedef in _migration_cols.items():
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE error_lessons ADD COLUMN {col} {typedef}")
                    except Exception:
                        pass
            conn.commit()
            
            # 新增表：自我反思
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT DEFAULT '',
                    reflection TEXT DEFAULT '',
                    lesson TEXT DEFAULT '',
                    created_at TEXT
                )
            """)
            
            # v4.0 新增表：工作缓冲区（WAL协议核心）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS working_buffer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    message_type TEXT,
                    content TEXT,
                    summary TEXT,
                    created_at TEXT,
                    synced_to_long_term INTEGER DEFAULT 0
                )
            """)
            
            # v4.0 新增表：活动状态（SESSION-STATE）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    state_key TEXT,
                    state_value TEXT,
                    updated_at TEXT,
                    UNIQUE(session_id, state_key)
                )
            """)
            
            conn.commit()
        finally:
            conn.close()

    # ── 辅助：写入 LivingMemory 数据库 ──

    def _write_to_livingmemory(self, content: str, tags: list, importance: float = 0.9):
        """直接写入 LivingMemory 的 documents 表"""
        import json
        import uuid
        import time
        try:
            conn = self.reader._connect()
            doc_id = str(uuid.uuid4())
            now_ts = time.time()
            meta = json.dumps({
                "session_id": "livingmemory_helper",
                "persona_id": "春雪_helper",
                "importance": importance,
                "create_time": now_ts,
                "last_access_time": now_ts,
                "topics": tags,
                "key_facts": [content[:80]],
                "sentiment": "neutral",
                "interaction_type": "plugin",
                "canonical_summary": content,
                "persona_summary": content,
                "summary_schema_version": "v2",
                "summary_quality": "normal",
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO documents (doc_id, text, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                (doc_id, content, meta),
            )
            conn.commit()
            conn.close()
            logger.info(f"[ErrorLearner] 已写入 LivingMemory: {content[:40]}")
        except Exception as e:
            logger.error(f"[ErrorLearner] 写入 LivingMemory 失败: {e}")

    # ── 核心：添加学习记录 ──

    def add_lesson(
        self, scene="", error="", correction="",
        solution="", tool="", tags="error_lesson",
        learning_type=LearningType.CORRECTION,
        priority=Priority.MEDIUM,
        confidence=0.5
    ) -> int:
        """添加学习记录（v3.0 增强版）"""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            
            # 检查是否重复记录类似内容
            existing = self._find_similar(conn, error, correction)
            if existing:
                # 更新出现次数
                conn.execute(
                    "UPDATE error_lessons SET occurrence_count = occurrence_count + 1, "
                    "last_seen_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, existing["id"])
                )
                conn.commit()
                lesson_id = existing["id"]
                
                # 检查是否需要确认（3次以上）
                if existing["occurrence_count"] + 1 >= 3:
                    logger.info(f"[ErrorLearner] 重复出现3次，需要确认: {existing['id']}")
            else:
                # 新记录
                c = conn.execute(
                    "INSERT INTO error_lessons (scene, error_content, user_correction, "
                    "solution, tool_name, tags, learning_type, priority, status, confidence, "
                    "occurrence_count, learned_at, last_seen_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (scene, error, correction, solution, tool, tags,
                     learning_type, priority, Status.PENDING, confidence,
                     1, now, now, now),
                )
                conn.commit()
                lesson_id = c.lastrowid
        finally:
            conn.close()

        # 同步写入 LivingMemory（仅新记录）
        if not existing:
            content = f"[学习记录] 类型:{learning_type} | 场景:{scene} | "
            content += f"错误:{error[:80]} | 纠正:{correction[:80]} | 解决:{solution[:80]}"
            self._write_to_livingmemory(content, tags.split(",") if tags else ["learning"])

        # v2.1 A9：教训记录 → 发布 LESSON_ADDED（family_bus 订阅沉淀为知识候选）
        try:
            from .family_bus import publish_family_event

            content = f"类型:{learning_type} | 场景:{scene} | 错误:{error[:60]} | 纠正:{correction[:60]}"
            publish_family_event(
                "lesson_added",
                memory_id=int(lesson_id or 0),
                metadata={"content": content, "category": str(tags)},
            )
        except BaseException:
            pass

        return lesson_id

    def _find_similar(self, conn, error: str, correction: str) -> dict:
        """查找相似的已有记录"""
        if not error and not correction:
            return None
        
        keywords = []
        if error:
            keywords.extend([w for w in error[:30].split() if len(w) > 1])
        if correction:
            keywords.extend([w for w in correction[:30].split() if len(w) > 1])
        
        for kw in keywords[:3]:
            row = conn.execute(
                "SELECT * FROM error_lessons WHERE "
                "(error_content LIKE ? OR user_correction LIKE ?) "
                "ORDER BY learned_at DESC LIMIT 1",
                (f"%{kw}%", f"%{kw}%")
            ).fetchone()
            if row:
                return dict(row)
        return None

    # ── 功能请求 ──

    def add_feature_request(self, request: str, context: str = "") -> int:
        """记录用户的功能请求"""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            c = conn.execute(
                "INSERT INTO feature_requests (request_content, user_context, "
                "priority, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (request, context, Priority.MEDIUM, Status.PENDING, now, now),
            )
            conn.commit()
            request_id = c.lastrowid

            # 同步写入 LivingMemory
            content = f"[功能请求] 请求:{request[:100]} | 上下文:{context[:80]}"
            self._write_to_livingmemory(content, ["feature_request"], importance=0.8)
            
            return request_id
        finally:
            conn.close()

    def list_feature_requests(self, status=None, limit=20):
        """列出功能请求"""
        conn = self._connect()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM feature_requests WHERE status=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feature_requests ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── 自我反思 ──

    def self_reflect(self, context: str, reflection: str, lesson: str) -> int:
        """记录自我反思"""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            c = conn.execute(
                "INSERT INTO reflections (context, reflection, lesson, created_at) "
                "VALUES (?,?,?,?)",
                (context, reflection, lesson, now),
            )
            conn.commit()
            reflect_id = c.lastrowid

            # 同步写入 LivingMemory
            content = f"[自我反思] 场景:{context} | 反思:{reflection} | 教训:{lesson}"
            self._write_to_livingmemory(content, ["self_reflection"], importance=0.7)
            
            return reflect_id
        finally:
            conn.close()

    def list_reflections(self, limit=10):
        """列出最近的自我反思"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── 查询（增强版） ──

    def list_lessons(self, tag=None, learning_type=None, priority=None, limit=20):
        """列出学习记录（支持按类型和优先级筛选）"""
        conn = self._connect()
        try:
            query = "SELECT * FROM error_lessons WHERE 1=1"
            params = []
            
            if tag:
                query += " AND tags LIKE ?"
                params.append(f"%{tag}%")
            if learning_type:
                query += " AND learning_type = ?"
                params.append(learning_type)
            if priority:
                query += " AND priority = ?"
                params.append(priority)
            
            query += " ORDER BY learned_at DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            result = []
            for r in rows:
                d = dict(r)
                d["error"] = d.get("error_content", "")
                d["time"] = d.get("learned_at", "")
                d["created_at"] = d.get("learned_at", "")
                result.append(d)
            return result
        finally:
            conn.close()

    def get_lesson(self, lesson_id):
        """获取单条学习记录"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM error_lessons WHERE id=?",
                (lesson_id,),
            ).fetchone()
            if row:
                d = dict(row)
                d["error"] = d.get("error_content", "")
                d["time"] = d.get("learned_at", "")
                d["created_at"] = d.get("learned_at", "")
                return d
            return None
        finally:
            conn.close()

    def find_relevant(self, query: str, limit=3):
        """搜索相关教训（v4.2: 支持中文分词）"""
        conn = self._connect()
        try:
            # 英文按空格分词
            en_keywords = [w for w in query[:80].split() if len(w) > 1]
            # 中文 2-gram 分词：滑动窗口取连续2字
            import re as _re
            cn_chars = _re.findall(r'[\u4e00-\u9fff]+', query[:80])
            cn_keywords = []
            for seg in cn_chars:
                if len(seg) >= 2:
                    for i in range(len(seg) - 1):
                        gram = seg[i:i+2]
                        if gram not in cn_keywords:
                            cn_keywords.append(gram)
            # 合并关键词（中文2-gram + 英文单词），去重，取前12个
            all_keywords = cn_keywords + en_keywords
            seen_kw = set()
            keywords = []
            for kw in all_keywords:
                if kw not in seen_kw and len(kw) >= 2:
                    seen_kw.add(kw)
                    keywords.append(kw)
            keywords = keywords[:12]
            
            results = []
            for kw in keywords:
                rows = conn.execute(
                    "SELECT * FROM error_lessons WHERE "
                    "scene LIKE ? OR error_content LIKE ? OR solution LIKE ? "
                    "ORDER BY learned_at DESC LIMIT ?",
                    (f"%{kw}%", f"%{kw}%", f"%{kw}%", limit),
                ).fetchall()
                for r in rows:
                    results.append(dict(r))
        finally:
            conn.close()
        
        # 按（命中次数 × 重要性）综合排序
        from collections import Counter
        id_counts = Counter(r["id"] for r in results)
        seen = set()
        unique = []
        # 综合分数 = 命中次数 × (importance + 0.5)，高重要性教训优先浮现
        def sort_key(x):
            cnt = id_counts[x["id"]]
            imp = x.get("importance", 0.5) or 0.5
            score = cnt * (imp + 0.5)
            return (-score, x.get("learned_at", ""))
        for r in sorted(results, key=sort_key):
            if r["id"] not in seen:
                seen.add(r["id"])
                r["error"] = r.get("error_content", "")
                r["time"] = r.get("learned_at", "")
                r["created_at"] = r.get("learned_at", "")
                r["_match_count"] = id_counts[r["id"]]
                unique.append(r)
                if len(unique) >= limit:
                    break
        return unique

    def mark_fixed(self, lesson_id):
        """标记为已修正"""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE error_lessons SET fixed=1, status=?, updated_at=? WHERE id=?",
                (Status.RESOLVED, datetime.now().isoformat(), lesson_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_verified(self, lesson_id):
        """标记为验证通过"""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE error_lessons SET fix_verified=1, updated_at=? WHERE id=?",
                (datetime.now().isoformat(), lesson_id),
            )
            conn.commit()
        finally:
            conn.close()

    def promote_to_memory(self, lesson_id):
        """提升到长期记忆"""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE error_lessons SET status=?, importance=1.0, updated_at=? WHERE id=?",
                (Status.PROMOTED, datetime.now().isoformat(), lesson_id),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_lesson(self, lesson_id):
        """删除学习记录"""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM error_lessons WHERE id=?", (lesson_id,))
            conn.commit()
        finally:
            conn.close()

    # ── 自动检测（v3.0 增强版） ──

    def detect_correction(self, msg: str) -> bool:
        """检测用户纠正"""
        return any(kw in msg for kw in CORRECTION_KEYWORDS)

    def detect_insight(self, msg: str) -> bool:
        """检测用户洞察"""
        return any(kw in msg for kw in INSIGHT_KEYWORDS)

    def detect_knowledge_gap(self, msg: str) -> bool:
        """检测知识差距"""
        return any(kw in msg for kw in KNOWLEDGE_GAP_KEYWORDS)

    def detect_tool_error(self, response_text: str) -> bool:
        """检测工具错误"""
        import re
        for pat in TOOL_ERROR_PATTERNS:
            if re.search(pat, response_text):
                return True
        return "错误" in response_text or "失败" in response_text

    def auto_record_correction(self, user_msg: str, bot_prev: str = ""):
        """自动从用户纠正消息学习"""
        scene = "对话回复"
        if "画" in user_msg:
            scene = "画图操作"
        elif "任务" in user_msg or "提醒" in user_msg:
            scene = "定时任务"
        elif "代码" in user_msg:
            scene = "代码执行"
        
        # 判断优先级
        priority = Priority.MEDIUM
        if any(w in user_msg for w in ["总是", "每次", "一直", "老是"]):
            priority = Priority.HIGH
        
        self.add_lesson(
            scene=scene,
            error=bot_prev[:200] if bot_prev else "",
            correction=user_msg[:200],
            solution=f"用户纠正: {user_msg[:100]}。以后注意避免类似错误。",
            tags="error_lesson",
            learning_type=LearningType.CORRECTION,
            priority=priority,
            confidence=0.7,
        )

    def auto_record_tool_error(self, error_msg: str, tool_name=""):
        """自动记录工具调用错误"""
        self.add_lesson(
            scene="工具调用",
            error=error_msg[:200],
            correction="",
            solution=f"工具 {tool_name} 调用失败。检查参数并重试。",
            tool=tool_name,
            tags="error_lesson,tool_call",
            learning_type=LearningType.TOOL_ERROR,
            priority=Priority.HIGH,
            confidence=0.9,
        )

    def auto_record_feature_request(self, user_msg: str):
        """自动记录功能请求"""
        # 提取请求内容
        request = user_msg
        for prefix in ["能不能", "可以", "我想", "我希望", "能不能有", "有没有"]:
            if prefix in user_msg:
                request = user_msg.split(prefix)[-1]
                break
        
        self.add_feature_request(
            request=request[:200],
            context=user_msg[:200],
        )

    # ── 自动提醒 ──

    def get_reminder_for_context(self, context: str) -> str:
        """根据上下文返回相关教训提醒"""
        relevant = self.find_relevant(context, limit=2)
        if not relevant:
            return ""
        
        lines = ["💡 相关教训提醒："]
        for r in relevant:
            scene = r.get("scene", "")
            err = r.get("error_content", "")[:50]
            sol = r.get("solution", "")[:50]
            lines.append(f"· [{scene}] {err} → {sol}")
        
        return "\n".join(lines)

    # ── 统计和报告 ──

    def get_statistics(self):
        """获取统计数据"""
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM error_lessons").fetchone()[0]
            fixed = conn.execute(
                "SELECT COUNT(*) FROM error_lessons WHERE fixed=1"
            ).fetchone()[0]
            verified = conn.execute(
                "SELECT COUNT(*) FROM error_lessons WHERE fix_verified=1"
            ).fetchone()[0]
            recurring = conn.execute(
                "SELECT SUM(recurrence_count) FROM error_lessons"
            ).fetchone()[0] or 0
            
            # v3.0 新增统计 - 兼容旧版本数据库
            by_type = {}
            by_priority = {}
            try:
                for row in conn.execute(
                    "SELECT learning_type, COUNT(*) as cnt FROM error_lessons GROUP BY learning_type"
                ).fetchall():
                    by_type[row["learning_type"]] = row["cnt"]
                
                for row in conn.execute(
                    "SELECT priority, COUNT(*) as cnt FROM error_lessons GROUP BY priority"
                ).fetchall():
                    by_priority[row["priority"]] = row["cnt"]
            except Exception:
                # 旧版本数据库没有 learning_type/priority 列
                pass
            
            feature_requests = 0
            reflections = 0
            try:
                feature_requests = conn.execute("SELECT COUNT(*) FROM feature_requests").fetchone()[0]
                reflections = conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0]
            except Exception:
                pass
            
            return {
                "total": total,
                "fixed": fixed,
                "verified": verified,
                "recurrence": recurring,
                "by_type": by_type,
                "by_priority": by_priority,
                "feature_requests": feature_requests,
                "reflections": reflections,
            }
        finally:
            conn.close()

    def generate_report(self):
        """生成学习成长报告"""
        stats = self.get_statistics()
        lessons = self.list_lessons(limit=5)

        lines = [
            "📊 春雪学习成长报告 v4.0",
            "━" * 40,
            f" 📚 总共学到：{stats['total']} 条教训",
            f" ✅ 已纠正：{stats['fixed']} 条",
            f" 🎯 验证通过：{stats['verified']} 条",
            f" 🔄 再犯次数：{stats['recurrence']} 次",
            f" 📝 功能请求：{stats['feature_requests']} 条",
            f" 🪞 自我反思：{stats['reflections']} 条",
            "",
        ]
        
        # 按类型统计
        if stats["by_type"]:
            lines.append(" 📁 按类型：")
            type_names = {
                "correction": "纠正",
                "insight": "洞察",
                "knowledge_gap": "知识差距",
                "best_practice": "最佳实践",
                "tool_error": "工具错误",
            }
            for t, cnt in stats["by_type"].items():
                name = type_names.get(t, t)
                lines.append(f"  · {name}：{cnt} 条")
        
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════
    # v4.0 新增：WAL协议 & 工作缓冲区 & 心跳机制
    # ══════════════════════════════════════════════════════════════════════

    # ── WAL协议：预写日志 ──

    def wal_log(self, session_id: str, message_type: str, content: str, summary: str = ""):
        """
        WAL协议：先记录，再处理
        防止处理过程中崩溃导致数据丢失
        """
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO working_buffer (session_id, message_type, content, summary, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, message_type, content, summary, now),
            )
            conn.commit()
            logger.debug(f"[WAL] 已记录 {message_type}: {content[:30]}...")
        finally:
            conn.close()

    # ── 工作缓冲区管理 ──

    def get_working_buffer(self, session_id: str, limit: int = 50):
        """获取当前会话的工作缓冲区"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM working_buffer WHERE session_id=? "
                "AND synced_to_long_term=0 ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def clear_working_buffer(self, session_id: str):
        """清空指定会话的工作缓冲区"""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM working_buffer WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def sync_to_long_term(self, session_id: str):
        """将工作缓冲区的重要内容同步到长期记忆"""
        buffer = self.get_working_buffer(session_id, limit=20)
        if not buffer:
            return

        # 提取摘要内容
        summaries = []
        for item in buffer:
            if item.get("summary"):
                summaries.append(item["summary"])
            elif item.get("content"):
                summaries.append(item["content"][:100])

        if summaries:
            # 合并为一条长期记忆
            combined = f"[会话摘要] {session_id}: " + " | ".join(summaries[-5:])
            self._write_to_livingmemory(combined, ["session_summary"], importance=0.7)

            # 标记已同步
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE working_buffer SET synced_to_long_term=1 "
                    "WHERE session_id=?",
                    (session_id,),
                )
                conn.commit()
            finally:
                conn.close()

    # ── 活动状态管理（SESSION-STATE）──

    def get_session_state(self, session_id: str, key: str):
        """获取活动状态"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT state_value FROM session_state "
                "WHERE session_id=? AND state_key=?",
                (session_id, key),
            ).fetchone()
            return row["state_value"] if row else None
        finally:
            conn.close()

    def set_session_state(self, session_id: str, key: str, value: str):
        """设置活动状态"""
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO session_state "
                "(session_id, state_key, state_value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, key, value, now),
            )
            conn.commit()
        finally:
            conn.close()

    def clear_session_state(self, session_id: str):
        """清空指定会话的活动状态"""
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM session_state WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ── 心跳机制 ──

    def heartbeat_cleanup(self, max_age_days: int = 7):
        """心跳任务：清理过期的工作缓冲区"""
        conn = self._connect()
        try:
            # 清理超过指定天数的未同步记录
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
            
            # 先同步重要数据
            sessions = conn.execute(
                "SELECT DISTINCT session_id FROM working_buffer "
                "WHERE created_at < ? AND synced_to_long_term=0",
                (cutoff,),
            ).fetchall()
            
            for row in sessions:
                self.sync_to_long_term(row["session_id"])
            
            # 然后清理
            deleted = conn.execute(
                "DELETE FROM working_buffer WHERE created_at < ?",
                (cutoff,),
            ).rowcount
            conn.commit()
            
            logger.info(f"[Heartbeat] 清理了 {deleted} 条过期工作缓冲区记录")
            return deleted
        finally:
            conn.close()

    def memory_optimize(self):
        """心跳任务：优化记忆结构"""
        stats = self.get_statistics()
        optimizations = []
        
        # 优化1：清理重复记录
        conn = self._connect()
        try:
            # 查找重复的教训（相似内容）
            duplicates = conn.execute("""
                SELECT error_content, COUNT(*) as cnt 
                FROM error_lessons 
                GROUP BY error_content 
                HAVING cnt > 1
            """).fetchall()
            
            if duplicates:
                optimizations.append(f"发现 {len(duplicates)} 组重复记录")
        finally:
            conn.close()
        
        return optimizations

    def self_improvement_check(self):
        """心跳任务：自我改进检查清单"""
        checklist = []
        
        # 检查1：工作缓冲区使用情况
        conn = self._connect()
        try:
            buffer_count = conn.execute(
                "SELECT COUNT(*) FROM working_buffer WHERE synced_to_long_term=0"
            ).fetchone()[0]
            checklist.append(f"工作缓冲区未同步: {buffer_count} 条")
        finally:
            conn.close()
        
        # 检查2：学习记录统计
        stats = self.get_statistics()
        checklist.append(f"总学习记录: {stats['total']} 条")
        checklist.append(f"功能请求: {stats['feature_requests']} 条")
        checklist.append(f"自我反思: {stats['reflections']} 条")
        
        # 检查3：是否有待处理的功能请求
        pending = self.list_feature_requests(status="pending", limit=5)
        if pending:
            checklist.append(f"待处理功能请求: {len(pending)} 条")
        
        return checklist
