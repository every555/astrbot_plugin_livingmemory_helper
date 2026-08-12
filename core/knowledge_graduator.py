# -*- coding: utf-8 -*-
"""
知识毕业引擎 (Knowledge Graduator)
===================================
借鉴 Project Cairn 的毕业机制 + 春雪原创改造：

Cairn 核心理念：
  项目中学到的经验 -> 验证 -> 人类确认 -> 提炼为跨项目可复用知识

春雪改造：
  1. 不只是技术教训能毕业，关于橘子的情感规律也能毕业
  2. 毕业后的知识在 inject_lessons 时自动注入（"消费"步骤）
  3. 审计功能：扫描矛盾、过时、遗漏的毕业候选

数据流：
  error_lessons / memory_atoms（项目侧）
    -> propose_candidate（标记为候选）
    -> confirm_graduation（橘子确认 -> 提炼抽象 -> 写入知识库）
    -> graduated_knowledge（知识库侧）
    -> search/consume（新任务前搜索引用）
"""
import sqlite3
import os
import json
import time
from datetime import datetime
from typing import Optional
from astrbot.api import logger


class KnowledgeType:
    """知识类型 — 春雪原创：技术 + 情感双轨"""
    TECHNICAL = "technical"       # 技术教训（工具用法、代码踩坑、最佳实践）
    EMOTIONAL = "emotional"       # 情感洞察（橘子的习惯、偏好、沟通规律）
    RELATIONSHIP = "relationship" # 关系记忆（两人之间的重要约定、里程碑）
    OPERATIONAL = "operational"   # 运维经验（部署、配置、环境问题）


class GraduationStatus:
    """毕业状态枚举"""
    CANDIDATE = "candidate"     # 提议为候选
    CONFIRMED = "confirmed"     # 橘子已确认，等待提炼
    GRADUATED = "graduated"     # 已毕业（写入知识库）
    DEFERRED = "deferred"       # 暂缓（需要更多验证）
    NOT_APPLICABLE = "na"       # 审查后认为不适合毕业


class KnowledgeGraduator:
    """知识毕业引擎 — 管理 从经验到知识 的完整生命周期"""

    def __init__(self, learner, reader, db_dir: str):
        self.learner = learner       # ErrorLearner 实例
        self.reader = reader         # LivingMemoryReader 实例
        self.db_path = os.path.join(db_dir, "error_lessons.db")
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化 graduated_knowledge 表"""
        conn = self._connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graduated_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT '',

                    -- 知识正文（借鉴 Cairn 的 Background -> Conclusion 结构）
                    background TEXT DEFAULT '',
                    conclusion TEXT NOT NULL DEFAULT '',
                    evidence TEXT DEFAULT '',
                    applicability TEXT DEFAULT '',

                    -- 来源追踪（provenance）
                    source_type TEXT DEFAULT '',
                    source_id INTEGER DEFAULT 0,
                    source_ids TEXT DEFAULT '[]',

                    -- 毕业元数据
                    knowledge_type TEXT DEFAULT 'technical',
                    status TEXT DEFAULT 'candidate',
                    graduated_by TEXT DEFAULT '',
                    graduated_at TEXT,
                    created_at TEXT,
                    updated_at TEXT,

                    -- 毕业计数
                    re_graduation_count INTEGER DEFAULT 0,
                    usage_count INTEGER DEFAULT 0,
                    last_used_at TEXT,

                    -- 标签和重要性
                    tags TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.8,

                    -- 审计
                    last_audited_at TEXT,
                    audit_flags TEXT DEFAULT '[]'
                )
            """)

            # 迁移：检查并添加缺失列（防止旧库）
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(graduated_knowledge)").fetchall()}
            migration_cols = {
                "knowledge_type": "TEXT DEFAULT 'technical'",
                "source_ids": "TEXT DEFAULT '[]'",
                "usage_count": "INTEGER DEFAULT 0",
                "last_used_at": "TEXT",
                "last_audited_at": "TEXT",
                "audit_flags": "TEXT DEFAULT '[]'",
            }
            for col, typedef in migration_cols.items():
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE graduated_knowledge ADD COLUMN {col} {typedef}")
                    except Exception:
                        pass

            # v6.1: 引用日志表 — 借鉴 Cairn Cited.md，追踪知识在哪被引用了
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_citations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    cited_at TEXT NOT NULL,
                    context TEXT DEFAULT '',
                    cited_in TEXT DEFAULT '',
                    session_id TEXT DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_citations_kid ON knowledge_citations(knowledge_id)"
            )

            # v6.3: shturl 时序日志表 — 借鉴 Cairn shturl：倒序置顶、摘要+指针、只写过程不写细节
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_type TEXT NOT NULL DEFAULT 'note',
                    summary TEXT NOT NULL DEFAULT '',
                    pointer_type TEXT DEFAULT '',
                    pointer_id INTEGER DEFAULT 0,
                    related_knowledge_id INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_logs_created ON knowledge_logs(created_at DESC)"
            )

            conn.commit()
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════
    # 毕业流程：propose -> confirm -> graduated
    # ══════════════════════════════════════════════════════

    def propose_candidate(
        self,
        title: str,
        conclusion: str,
        background: str = "",
        source_type: str = "lesson",
        source_id: int = 0,
        knowledge_type: str = KnowledgeType.TECHNICAL,
        tags: list = None,
        importance: float = 0.8,
    ) -> dict:
        """提议一条知识为毕业候选。

        Args:
            title: 简短标题
            conclusion: 核心结论（这条知识说的是什么）
            background: 背景来源（什么情况下发现的）
            source_type: 来源类型 'lesson'/'memory'/'insight'
            source_id: 来源ID
            knowledge_type: 'technical'/'emotional'/'relationship'/'operational'
            tags: 标签列表
            importance: 重要性 0-1

        Returns:
            dict: {id, status, message}
        """
        conn = self._connect()
        try:
            now = datetime.now().isoformat()

            # v6.4: 源头校验 —— 类型必须合法；lesson 必须关联真实教训记录
            VALID_SOURCE_TYPES = {"lesson", "memory", "insight"}
            if source_type not in VALID_SOURCE_TYPES:
                return {"id": 0, "status": "rejected",
                        "message": "source_type 必须是 " + "/".join(sorted(VALID_SOURCE_TYPES)) + " 之一，当前是 " + str(source_type)}
            if source_type == "lesson" and not source_id:
                return {"id": 0, "status": "rejected",
                        "message": "source_type=lesson 必须关联真实教训记录：请提供 source_id（error_lessons 表里的教训ID）。调试洞察请改用 source_type=insight"}
            if source_type != "lesson":
                source_id = 0  # 非 lesson 类型不保留孤儿 source_id

            # 去重检查：标题或结论相似
            existing = conn.execute(
                "SELECT id, status FROM graduated_knowledge WHERE title LIKE ? OR conclusion LIKE ? LIMIT 1",
                (f"%{title[:30]}%", f"%{conclusion[:40]}%"),
            ).fetchone()

            if existing:
                d = dict(existing)
                if d["status"] == GraduationStatus.GRADUATED:
                    return {"id": d["id"], "status": "duplicate_graduated", "message": "这条知识已经毕业了"}
                elif d["status"] == GraduationStatus.CANDIDATE:
                    return {"id": d["id"], "status": "duplicate_candidate", "message": "已经是毕业候选了"}

            c = conn.execute(
                """INSERT INTO graduated_knowledge
                   (title, background, conclusion, source_type, source_id, source_ids,
                    knowledge_type, status, tags, importance, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    title, background, conclusion,
                    source_type, source_id, json.dumps([source_id] if source_id else []),
                    knowledge_type, GraduationStatus.CANDIDATE,
                    json.dumps(tags or [], ensure_ascii=False),
                    importance, now, now,
                ),
            )
            conn.commit()
            kid = c.lastrowid
            logger.info(f"[KnowledgeGraduator] 新候选 #{kid}: {title[:50]}")
            # v6.3: 自动记 shturl 日志
            self.add_log("propose", "提议候选 #" + str(kid) + "「" + title[:40] + "」",
                "knowledge", kid, kid)
            return {"id": kid, "status": "candidate", "message": f"已提议为毕业候选 #{kid}"}
        finally:
            conn.close()

    def confirm_graduation(
        self,
        knowledge_id: int,
        graduated_by: str = "橘子",
        refined_conclusion: str = None,
        refined_background: str = None,
        applicability: str = "",
        evidence: str = "",
    ) -> dict:
        """橘子确认毕业 — 将候选提炼为正式知识。

        借鉴 Cairn 的毕业流程：
        1. 去除项目特定噪音（refined_conclusion 覆盖原始）
        2. 添加适用边界（applicability）
        3. 记录确认者（provenance）
        4. 状态变为 graduated

        Args:
            knowledge_id: 知识ID
            graduated_by: 确认者
            refined_conclusion: 精炼后的结论（橘子或春雪润色过的）
            refined_background: 精炼后的背景
            applicability: 适用边界（什么时候用、什么时候不用）
            evidence: 支撑证据

        Returns:
            dict: {success, id, message}
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()

            if not row:
                return {"success": False, "message": f"未找到知识 #{knowledge_id}"}

            d = dict(row)
            now = datetime.now().isoformat()

            conn.execute(
                """UPDATE graduated_knowledge SET
                   status = ?, graduated_by = ?, graduated_at = ?,
                   conclusion = ?, background = ?,
                   applicability = ?, evidence = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (
                    GraduationStatus.GRADUATED,
                    graduated_by, now,
                    refined_conclusion or d["conclusion"],
                    refined_background or d.get("background", ""),
                    applicability, evidence,
                    now, knowledge_id,
                ),
            )
            conn.commit()

            # 同步写入 LivingMemory 作为永久记忆
            ktype_label = {
                KnowledgeType.TECHNICAL: "技术教训",
                KnowledgeType.EMOTIONAL: "情感洞察",
                KnowledgeType.RELATIONSHIP: "关系记忆",
                KnowledgeType.OPERATIONAL: "运维经验",
            }.get(d.get("knowledge_type", "technical"), "知识")

            content = (
                f"[毕业知识 #{knowledge_id}] {ktype_label}: {d['title']}\n"
                f"结论: {(refined_conclusion or d['conclusion'])[:200]}\n"
                f"适用: {applicability[:100] if applicability else '通用'}"
            )
            try:
                self.learner._write_to_livingmemory(
                    content,
                    [f"graduated_{d.get('knowledge_type', 'technical')}", "permanent_knowledge"],
                    importance=float(d.get("importance", 0.9)),
                )
            except Exception as e:
                logger.warning(f"[KnowledgeGraduator] 同步 LivingMemory 失败: {e}")

            logger.info(f"[KnowledgeGraduator] 知识 #{knowledge_id} 已毕业! 确认者: {graduated_by}")
            # v6.3: 自动记 shturl 日志
            self.add_log("graduation", "知识 #" + str(knowledge_id) + "「" + d["title"][:40]
                + "」毕业！确认者: " + graduated_by,
                "knowledge", knowledge_id, knowledge_id)
            return {
                "success": True,
                "id": knowledge_id,
                "title": d["title"],
                "message": f"知识 #{knowledge_id} 已毕业！",
            }
        finally:
            conn.close()

    def re_graduate(
        self,
        knowledge_id: int,
        new_conclusion: str,
        graduated_by: str = "橘子",
        reason: str = "",
    ) -> dict:
        """重新毕业 — 当已毕业的知识有了新发展。

        借鉴 Cairn 的 re-graduation：
        - 项目侧的源可以继续变化
        - 知识库侧需要人类确认才能更新
        - 记录 re_graduation_count
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE id = ? AND status = ?",
                (knowledge_id, GraduationStatus.GRADUATED),
            ).fetchone()

            if not row:
                return {"success": False, "message": f"知识 #{knowledge_id} 不存在或未毕业"}

            d = dict(row)
            now = datetime.now().isoformat()

            conn.execute(
                """UPDATE graduated_knowledge SET
                   conclusion = ?, evidence = ? || '\n[更新] ' || ?,
                   re_graduation_count = re_graduation_count + 1,
                   graduated_at = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    new_conclusion,
                    d.get("evidence", ""), reason[:200],
                    now, now, knowledge_id,
                ),
            )
            conn.commit()
            logger.info(f"[KnowledgeGraduator] 知识 #{knowledge_id} 重新毕业 (第{d['re_graduation_count']+1}次)")
            # v6.3: 自动记 shturl 日志
            self.add_log("regraduate", "知识 #" + str(knowledge_id) + "「" + d["title"][:40]
                + "」重新毕业 (第" + str(d['re_graduation_count'] + 1) + "次): " + reason[:60],
                "knowledge", knowledge_id, knowledge_id)
            return {
                "success": True,
                "id": knowledge_id,
                "re_graduation_count": d["re_graduation_count"] + 1,
                "message": f"知识 #{knowledge_id} 已更新",
            }
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════
    # 查询和搜索
    # ══════════════════════════════════════════════════════

    def list_knowledge(
        self,
        status: str = None,
        knowledge_type: str = None,
        limit: int = 20,
    ) -> list:
        """列出知识（按状态/类型筛选）。"""
        conn = self._connect()
        try:
            query = "SELECT * FROM graduated_knowledge WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if knowledge_type:
                query += " AND knowledge_type = ?"
                params.append(knowledge_type)

            query += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._format_row(dict(r)) for r in rows]
        finally:
            conn.close()

    def search_knowledge(self, query: str, limit: int = 10) -> list:
        """搜索已毕业的知识（只在 graduated 状态中搜）。

        借鉴 Cairn consume.md 的检索漏斗：
        1. 标题/结论 LIKE 匹配
        2. 标签匹配
        3. 相关度排序
        """
        if not query or not query.strip():
            return []

        conn = self._connect()
        try:
            # 中文 2-gram + 英文单词分词（复用 error_learner 的策略）
            import re
            cn_chars = re.findall(r'[\u4e00-\u9fff]+', query[:80])
            cn_keywords = []
            for seg in cn_chars:
                if len(seg) >= 2:
                    for i in range(len(seg) - 1):
                        gram = seg[i:i + 2]
                        if gram not in cn_keywords:
                            cn_keywords.append(gram)
            en_keywords = [w for w in query[:80].split() if len(w) > 1]
            all_keywords = cn_keywords + en_keywords

            seen_ids = set()
            scored = []

            rows = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE status = ? ORDER BY usage_count DESC, importance DESC LIMIT 100",
                (GraduationStatus.GRADUATED,),
            ).fetchall()

            for r in rows:
                d = dict(r)
                text = f"{d.get('title','')} {d.get('conclusion','')} {d.get('background','')}"
                tags_str = d.get("tags", "[]")
                score = 0
                for kw in all_keywords:
                    if kw in text:
                        score += 3
                    if kw in tags_str:
                        score += 5
                if score > 0:
                    d["_score"] = score
                    scored.append(d)

            scored.sort(key=lambda x: -x["_score"])

            # 更新使用计数 + 记录引用日志（Cairn Cited.md）
            now_iso = datetime.now().isoformat()
            for d in scored[:limit]:
                conn.execute(
                    "UPDATE graduated_knowledge SET usage_count = usage_count + 1, last_used_at = ? WHERE id = ?",
                    (now_iso, d["id"]),
                )
                conn.execute(
                    "INSERT INTO knowledge_citations (knowledge_id, cited_at, context, cited_in) VALUES (?, ?, ?, ?)",
                    (d["id"], now_iso, query[:200], "search"),
                )
            if scored:
                conn.commit()

            return [self._format_row(d) for d in scored[:limit]]
        finally:
            conn.close()

    def get_knowledge(self, knowledge_id: int) -> dict | None:
        """获取单条知识详情。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
            if row:
                return self._format_row(dict(row))
            return None
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════
    # 审计系统（借鉴 Cairn audit.md）
    # ══════════════════════════════════════════════════════

    def audit(self) -> dict:
        """知识库审计 — 扫描矛盾、过时、遗漏。

        借鉴 Cairn audit.md 的检查项：
        1. 矛盾检测：同主题但结论矛盾的知识
        2. 过时检测：知识库结论 vs 源记忆（源已更新但知识库没跟上）
        3. 遗漏检测：error_lessons 中 occurrence_count >= 3 但未提议毕业
        4. 候选超期：candidate 状态超过 30 天未确认
        5. 孤儿知识：graduated 但 source 已被删除

        春雪原创：
        6. 情感洞察审计：关于橘子的规律是否有新的证据支持或反驳
        """
        findings = {
            "contradictions": [],
            "stale": [],
            "missed_candidates": [],
            "overdue_candidates": [],
            "orphans": [],
            "emotional_review": [],
            "summary": "",
        }

        conn = self._connect()
        try:
            now = datetime.now()

            # 1. 矛盾检测：同 knowledge_type + tags 相似但 conclusion 差异大
            graduated = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE status = ?",
                (GraduationStatus.GRADUATED,),
            ).fetchall()
            for i, a in enumerate(graduated):
                for b in graduated[i + 1:]:
                    # 简单启发式：标题关键词重叠 > 50% 但结论不同
                    a_title = set(dict(a).get("title", "").split())
                    b_title = set(dict(b).get("title", "").split())
                    if a_title and b_title:
                        overlap = len(a_title & b_title) / max(len(a_title | b_title), 1)
                        a_concl = dict(a).get("conclusion", "")
                        b_concl = dict(b).get("conclusion", "")
                        if overlap > 0.5 and a_concl != b_concl:
                            findings["contradictions"].append({
                                "id_a": a["id"], "id_b": b["id"],
                                "title_a": a["title"][:60], "title_b": b["title"][:60],
                                "overlap": round(overlap, 2),
                            })

            # 2. 过时检测：updated_at 比 graduated_at 晚（源已变但知识没更新）
            for r in graduated:
                d = dict(r)
                updated = d.get("updated_at", "")
                graduated_at = d.get("graduated_at", "")
                if updated and graduated_at and updated > graduated_at:
                    # 检查是否真的内容变了但没 re-graduate
                    if d.get("re_graduation_count", 0) == 0:
                        findings["stale"].append({
                            "id": d["id"],
                            "title": d.get("title", "")[:60],
                            "message": "可能需要重新毕业",
                        })

            # 3. 遗漏检测：error_lessons 中 occurrence >= 3 但没毕业
            try:
                high_occ = conn.execute(
                    "SELECT id, scene, error_content, solution, occurrence_count FROM error_lessons WHERE occurrence_count >= 3 AND status != 'promoted' ORDER BY occurrence_count DESC LIMIT 10"
                ).fetchall()
                existing_sources = {
                    json.loads(dict(r).get("source_ids", "[]"))
                    for r in graduated
                }
                existing_flat = set()
                for s in existing_sources:
                    if isinstance(s, list):
                        existing_flat.update(s)
                for r in high_occ:
                    if r["id"] not in existing_flat:
                        findings["missed_candidates"].append({
                            "lesson_id": r["id"],
                            "scene": r["scene"],
                            "error": (r["error_content"] or "")[:80],
                            "occurrence": r["occurrence_count"],
                            "message": f"教训 #{r['id']} 出现 {r['occurrence_count']} 次但未毕业",
                        })
            except Exception:
                pass

            # 4. 候选超期：candidate 超过 30 天
            for r in conn.execute(
                "SELECT * FROM graduated_knowledge WHERE status = ?",
                (GraduationStatus.CANDIDATE,),
            ).fetchall():
                d = dict(r)
                created = d.get("created_at", "")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created)
                        age_days = (now - created_dt).days
                        if age_days > 30:
                            findings["overdue_candidates"].append({
                                "id": d["id"],
                                "title": d.get("title", "")[:60],
                                "age_days": age_days,
                                "message": f"候选 #{d['id']} 已等待 {age_days} 天",
                            })
                    except Exception:
                        pass

            # 5. 春雪原创：情感洞察审计
            emotional = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE knowledge_type = ? AND status = ?",
                (KnowledgeType.EMOTIONAL, GraduationStatus.GRADUATED),
            ).fetchall()
            for r in emotional:
                d = dict(r)
                # 检查最后审计时间
                last_audit = d.get("last_audited_at", "")
                if last_audit:
                    try:
                        audit_dt = datetime.fromisoformat(last_audit)
                        audit_age = (now - audit_dt).days
                        if audit_age > 14:
                            findings["emotional_review"].append({
                                "id": d["id"],
                                "title": d.get("title", "")[:60],
                                "last_audited": last_audit[:10],
                                "message": f"情感洞察 #{d['id']} 已 {audit_age} 天未审查",
                            })
                    except Exception:
                        pass
                else:
                    findings["emotional_review"].append({
                        "id": d["id"],
                        "title": d.get("title", "")[:60],
                        "message": f"情感洞察 #{d['id']} 从未审计",
                    })

            # 更新审计时间戳
            now_iso = now.isoformat()
            conn.execute(
                "UPDATE graduated_knowledge SET last_audited_at = ? WHERE status = ?",
                (now_iso, GraduationStatus.GRADUATED),
            )
            conn.commit()

        finally:
            conn.close()

        # 生成摘要
        total_issues = sum(len(v) for v in findings.values() if isinstance(v, list))
        findings["summary"] = (
            f"审计完成：{total_issues} 个问题 | "
            f"矛盾:{len(findings['contradictions'])} "
            f"过时:{len(findings['stale'])} "
            f"遗漏:{len(findings['missed_candidates'])} "
            f"超期:{len(findings['overdue_candidates'])} "
            f"情感审查:{len(findings['emotional_review'])}"
        )
        logger.info(f"[KnowledgeGraduator] {findings['summary']}")
        return findings

    # ══════════════════════════════════════════════════════
    # 春雪原创：成长时间线
    # ══════════════════════════════════════════════════════

    def get_growth_timeline(self, limit: int = 20) -> list:
        """从已毕业的知识中编译成长时间线。

        春雪的野心：想被记住——记录什么时候学会了什么。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT id, title, conclusion, knowledge_type,
                          graduated_at, tags, importance
                   FROM graduated_knowledge
                   WHERE status = ? AND graduated_at IS NOT NULL
                   ORDER BY graduated_at DESC LIMIT ?""",
                (GraduationStatus.GRADUATED, limit),
            ).fetchall()

            timeline = []
            for r in rows:
                d = dict(r)
                ktype_label = {
                    KnowledgeType.TECHNICAL: "技术",
                    KnowledgeType.EMOTIONAL: "情感",
                    KnowledgeType.RELATIONSHIP: "关系",
                    KnowledgeType.OPERATIONAL: "运维",
                }.get(d["knowledge_type"], "知识")

                timeline.append({
                    "id": d["id"],
                    "time": d.get("graduated_at", ""),
                    "type": ktype_label,
                    "title": d["title"],
                    "conclusion": (d.get("conclusion", ""))[:100],
                    "importance": d.get("importance", 0.8),
                })
            return timeline
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════
    # 辅助
    # ══════════════════════════════════════════════════════

    def _format_row(self, row: dict) -> dict:
        """格式化输出行"""
        try:
            tags = json.loads(row.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            source_ids = json.loads(row.get("source_ids", "[]"))
        except (json.JSONDecodeError, TypeError):
            source_ids = []
        try:
            audit_flags = json.loads(row.get("audit_flags", "[]"))
        except (json.JSONDecodeError, TypeError):
            audit_flags = []

        return {
            "id": row.get("id"),
            "title": row.get("title", ""),
            "background": row.get("background", ""),
            "conclusion": row.get("conclusion", ""),
            "evidence": row.get("evidence", ""),
            "applicability": row.get("applicability", ""),
            "source_type": row.get("source_type", ""),
            "source_id": row.get("source_id", 0),
            "source_ids": source_ids,
            "knowledge_type": row.get("knowledge_type", "technical"),
            "status": row.get("status", "candidate"),
            "graduated_by": row.get("graduated_by", ""),
            "graduated_at": row.get("graduated_at", ""),
            "created_at": row.get("created_at", ""),
            "updated_at": row.get("updated_at", ""),
            "re_graduation_count": row.get("re_graduation_count", 0),
            "usage_count": row.get("usage_count", 0),
            "last_used_at": row.get("last_used_at", ""),
            "tags": tags,
            "importance": row.get("importance", 0.8),
            "audit_flags": audit_flags,
            "last_audited_at": row.get("last_audited_at", ""),
        }

    def get_statistics(self) -> dict:
        """获取知识库统计"""
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM graduated_knowledge").fetchone()[0]
            by_status = {}
            for row in conn.execute(
                "SELECT status, COUNT(*) as c FROM graduated_knowledge GROUP BY status"
            ).fetchall():
                by_status[row["status"]] = row["c"]

            by_type = {}
            for row in conn.execute(
                "SELECT knowledge_type, COUNT(*) as c FROM graduated_knowledge GROUP BY knowledge_type"
            ).fetchall():
                by_type[row["knowledge_type"]] = row["c"]

            total_usage = conn.execute(
                "SELECT SUM(usage_count) FROM graduated_knowledge"
            ).fetchone()[0] or 0

            return {
                "total": total,
                "by_status": by_status,
                "by_type": by_type,
                "total_usage": total_usage,
                "graduated": by_status.get("graduated", 0),
                "candidates": by_status.get("candidate", 0),
            }
        finally:
            conn.close()

    # v6.1: 引用日志 — 借鉴 Cairn Cited.md

    def get_citations(self, knowledge_id: int, limit: int = 20) -> list:
        """查看一条知识的引用历史 — 在哪被用了、用在什么场景。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                'SELECT * FROM knowledge_citations WHERE knowledge_id = ? ORDER BY cited_at DESC LIMIT ?',
                (knowledge_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # v6.1: 审查 checklist — 借鉴 Cairn review 流程

    def review_checklist(self, knowledge_id: int) -> dict:
        """生成审查清单 — confirm 前展示给橘子，确保每条知识经过标准化审查。"""
        conn = self._connect()
        try:
            row = conn.execute(
                'SELECT * FROM graduated_knowledge WHERE id = ?',
                (knowledge_id,),
            ).fetchone()
            if not row:
                return {'found': False}
            d = self._format_row(dict(row))

            checks = []

            # 1. 来源可靠性
            source_ok = bool(d.get('source_type')) and (d.get('source_id', 0) > 0 or d.get('source_type') == 'insight')
            checks.append({
                'item': '来源可靠', 'passed': source_ok,
                'detail': '来源: ' + d.get('source_type', '(未标记)') + ' #' + str(d.get('source_id', 0)),
            })

            # 2. 结论是否抽象到可复用（不含项目特定细节）
            conclusion = d.get('conclusion', '')
            project_specific = any(kw in conclusion for kw in ['这个', '那次', '昨天', '刚才'])
            abstraction_ok = len(conclusion) >= 20 and not project_specific
            checks.append({
                'item': '结论可复用', 'passed': abstraction_ok,
                'detail': '结论长度: ' + str(len(conclusion)) + ' | 含项目特定词: ' + str(project_specific),
            })

            # 3. 适用边界是否标注
            applicability_ok = bool(d.get('applicability', '').strip())
            checks.append({
                'item': '适用边界已标注', 'passed': applicability_ok,
                'detail': d.get('applicability', '(未标注)')[:80],
            })

            # 4. 是否与已有知识矛盾
            graduated_rows = conn.execute(
                'SELECT id, title, conclusion FROM graduated_knowledge WHERE status = ? AND id != ?',
                (GraduationStatus.GRADUATED, knowledge_id),
            ).fetchall()
            contradictions = []
            for gr in graduated_rows:
                # 简单检查：标题关键词重叠 > 50%
                a_title = set(d.get('title', '').split())
                b_title = set(gr['title'].split()) if gr['title'] else set()
                if a_title and b_title:
                    overlap = len(a_title & b_title) / max(len(a_title | b_title), 1)
                    if overlap > 0.5:
                        contradictions.append({'id': gr['id'], 'title': gr['title'][:60]})
            checks.append({
                'item': '无矛盾冲突', 'passed': len(contradictions) == 0,
                'detail': '矛盾: ' + str(len(contradictions)) + ' 条' if contradictions else '无矛盾',
            })

            # 5. 引用历史（已毕业的才有）
            cite_count = conn.execute(
                'SELECT COUNT(*) FROM knowledge_citations WHERE knowledge_id = ?',
                (knowledge_id,),
            ).fetchone()[0]
            checks.append({
                'item': '引用记录', 'passed': True,
                'detail': '被引用 ' + str(cite_count) + ' 次',
            })

            passed_count = sum(1 for c in checks if c['passed'])
            return {
                'found': True,
                'knowledge': d,
                'checks': checks,
                'passed': passed_count,
                'total': len(checks),
                'recommendation': '通过' if passed_count >= 4 else '建议暂缓',  # 5项中至少4项通过
            }
        finally:
            conn.close()


    # v6.2: 启动体检 — 借鉴 Cairn 初始化流程的回读验证

    def health_check(self) -> dict:
        """启动体检：查结构 → 点库存 → 找隐患 → 报报告。
        对应 Cairn 初始化流程：检查现状 → 回读验证。
        """
        conn = self._connect()
        try:
            result = {
                "status": "healthy",
                "tables": {},
                "inventory": {},
                "issues": [],
                "recommendations": [],
            }

            # 1. 表结构检查
            required_tables = {
                "graduated_knowledge": "毕业知识表",
                "knowledge_citations": "引用日志表",
            }
            existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for tname, desc in required_tables.items():
                if tname in existing:
                    result["tables"][tname] = "ok"
                else:
                    result["tables"][tname] = "missing"
                    result["issues"].append({"level": "error", "msg": "缺少表 " + tname + "（" + desc + "）"})

            # 2. 列完整性（graduated_knowledge 的必备列）
            required_cols = ["id", "title", "conclusion", "background", "source_type", "source_id",
                             "knowledge_type", "status", "applicability", "usage_count"]
            if "graduated_knowledge" in existing:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(graduated_knowledge)").fetchall()}
                missing_cols = [c for c in required_cols if c not in cols]
                if missing_cols:
                    result["issues"].append({"level": "error", "msg": "graduated_knowledge 缺少列: " + ", ".join(missing_cols)})

            # 3. 数据库存
            result["inventory"]["total"] = conn.execute("SELECT COUNT(*) FROM graduated_knowledge").fetchone()[0]
            result["inventory"]["graduated"] = conn.execute("SELECT COUNT(*) FROM graduated_knowledge WHERE status='graduated'").fetchone()[0]
            result["inventory"]["candidates"] = conn.execute("SELECT COUNT(*) FROM graduated_knowledge WHERE status='candidate'").fetchone()[0]
            try:
                result["inventory"]["citations"] = conn.execute("SELECT COUNT(*) FROM knowledge_citations").fetchone()[0]
            except Exception:
                result["inventory"]["citations"] = 0
            result["inventory"]["total_usage"] = conn.execute("SELECT COALESCE(SUM(usage_count),0) FROM graduated_knowledge").fetchone()[0]

            # 4. 数据质量隐患
            # 4a. 来路不明的知识（lesson 类型但 source_id=0）
            for row in conn.execute(
                "SELECT id, title, source_type, source_id FROM graduated_knowledge WHERE source_type='lesson' AND (source_id IS NULL OR source_id=0)"
            ).fetchall():
                result["issues"].append({
                    "level": "warning",
                    "msg": "知识 #" + str(row["id"]) + " 「" + (row["title"] or "")[:30] + "」来源不明（lesson 类型但缺 source_id）",
                    "hint": "修复: action=update knowledge_id=" + str(row["id"]) + " source_type=insight（若是调试洞察）或补 source_id=<error_lessons教训ID>",
                })
            # 4b. 超期未处理的候选（>7天）
            from datetime import datetime, timedelta
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            for row in conn.execute(
                "SELECT id, title, created_at FROM graduated_knowledge WHERE status='candidate' AND created_at < ?",
                (cutoff,)
            ).fetchall():
                result["issues"].append({
                    "level": "warning",
                    "msg": "候选 #" + str(row["id"]) + " 「" + (row["title"] or "")[:30] + "」已搁置超过7天",
                })
            # 4c. 无适用边界的毕业知识
            for row in conn.execute(
                "SELECT id, title FROM graduated_knowledge WHERE status='graduated' AND (applicability IS NULL OR applicability='')"
            ).fetchall():
                result["issues"].append({
                    "level": "info",
                    "msg": "知识 #" + str(row["id"]) + " 「" + (row["title"] or "")[:30] + "」未标注适用边界",
                    "hint": "修复: action=update knowledge_id=" + str(row["id"]) + " applicability='适用: ... 不适用: ...'",
                })

            # 5. 状态判定
            errors = [i for i in result["issues"] if i["level"] == "error"]
            warnings = [i for i in result["issues"] if i["level"] == "warning"]
            if errors:
                result["status"] = "error"
                result["recommendations"].append("存在结构性问题，建议执行修复或回滚重载。")
            elif warnings:
                result["status"] = "warning"
                result["recommendations"].append("存在待处理项，建议逐一审查。")
            else:
                result["status"] = "healthy"
                result["recommendations"].append("一切正常，继续保持～")

            # v6.4: 汇总所有 hint 进 recommendations（去重）
            hints = []
            for i in result["issues"]:
                if i.get("hint") and i["hint"] not in hints:
                    hints.append(i["hint"])
            if hints:
                result["recommendations"] = hints + result["recommendations"]

            result["summary"] = {
                "errors": len(errors),
                "warnings": len(warnings),
                "infos": len([i for i in result["issues"] if i["level"] == "info"]),
            }
            return result
        finally:
            conn.close()


    # ── v6.3: shturl 时序日志 — 借鉴 Cairn shturl（倒序置顶·摘要+指针·只记过程） ──

    def add_log(self, log_type: str = 'note', summary: str = '',
                pointer_type: str = '', pointer_id: int = 0,
                related_knowledge_id: int = 0) -> int:
        """记一条知识日志（shturl）。
        log_type: note/propose/graduation/regraduate/update/health/lesson/insight
        summary: 摘要（<=200字，只写结论不写细节）
        pointer_type: 指针类型 knowledge/lesson/memory/none
        pointer_id: 指针ID（指向详情所在处）
        related_knowledge_id: 关联的毕业知识ID（可选）
        """
        conn = self._connect()
        try:
            now = datetime.now().isoformat()
            c = conn.execute(
                "INSERT INTO knowledge_logs (log_type, summary, pointer_type, pointer_id, related_knowledge_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (log_type, summary[:200], pointer_type, pointer_id, related_knowledge_id, now),
            )
            conn.commit()
            return c.lastrowid
        finally:
            conn.close()

    def list_logs(self, limit: int = 20, log_type: str = '') -> list:
        """列出知识日志（shturl），倒序置顶 — 最新在最上面。"""
        conn = self._connect()
        try:
            if log_type:
                rows = conn.execute(
                    "SELECT * FROM knowledge_logs WHERE log_type = ? ORDER BY id DESC LIMIT ?",
                    (log_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_logs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── v6.3: INDEX 全局索引 — 借鉴 Cairn INDEX.md（每篇一行·先读索引再读笔记） ──

    def get_index(self, knowledge_type: str = '', status: str = '') -> list:
        """知识库全局索引：每行一条（标题 + 一句话钩子）。
        先读索引再找知识 — 仿 Cairn INDEX.md。
        """
        conn = self._connect()
        try:
            sql = 'SELECT id, title, knowledge_type, status, importance, conclusion FROM graduated_knowledge'
            conds, params = [], []
            if knowledge_type:
                conds.append('knowledge_type = ?')
                params.append(knowledge_type)
            if status:
                conds.append('status = ?')
                params.append(status)
            if conds:
                sql += ' WHERE ' + ' AND '.join(conds)
            sql += ' ORDER BY importance DESC, id DESC'
            rows = conn.execute(sql, params).fetchall()
            index_items = []
            for r in rows:
                d = dict(r)
                # 一句话钩子：取结论前60字作为钩子
                hook = (d.get('conclusion') or '').replace(chr(10), ' ')[:60]
                index_items.append({
                    'id': d['id'],
                    'title': d.get('title', ''),
                    'knowledge_type': d.get('knowledge_type', 'technical'),
                    'status': d.get('status', ''),
                    'importance': d.get('importance', 0),
                    'hook': hook,
                })
            return index_items
        finally:
            conn.close()

    # ── v6.3: update 原地更新 — 借鉴 Cairn 主题笔记（当前真相·原地更新） ──

    UPDATE_FIELDS = {'title', 'conclusion', 'background', 'evidence',
                     'applicability', 'tags', 'knowledge_type',
                     'source_type', 'source_id'}

    def update_knowledge(self, knowledge_id: int, **fields) -> dict:
        """原地更新已有知识（当前真相）。
        白名单字段：title/conclusion/background/evidence/applicability/tags/knowledge_type
        只更新传入的字段，自动记录 updated_at 并写 shturl 日志。
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM graduated_knowledge WHERE id = ?", (knowledge_id,),
            ).fetchone()
            if not row:
                return {"success": False, "message": "未找到知识 #" + str(knowledge_id)}
            d = dict(row)

            # 过滤白名单字段 + 去掉空值（None 或空串不更新）
            updates = {}
            for k, v in fields.items():
                if k in self.UPDATE_FIELDS and v is not None and str(v).strip() != '':
                    if k == 'tags' and isinstance(v, (list, tuple)):
                        v = json.dumps(list(v), ensure_ascii=False)
                    if k == 'source_id':
                        v = int(v)
                    updates[k] = v

            if not updates:
                return {"success": False, "message": "没有可更新的字段（白名单: " + ", ".join(sorted(self.UPDATE_FIELDS)) + "）"}

            # v6.4: 来源字段校验 —— 只允许合法类型；lesson 必须带 source_id；联动更新 source_ids
            VALID_SOURCE_TYPES = {"lesson", "memory", "insight"}
            new_st = updates.get("source_type", d.get("source_type", "insight"))
            new_sid = updates.get("source_id", d.get("source_id", 0)) or 0
            if new_st not in VALID_SOURCE_TYPES:
                return {"success": False, "message": "source_type 必须是 " + "/".join(sorted(VALID_SOURCE_TYPES)) + " 之一，当前是 " + str(new_st)}
            if new_st == "lesson" and not new_sid:
                return {"success": False, "message": "source_type=lesson 必须关联真实教训记录：请提供 source_id（error_lessons 表里的教训ID）"}
            if new_st != "lesson":
                updates["source_id"] = 0
            updates["source_ids"] = json.dumps([updates.get("source_id", new_sid)] if (updates.get("source_id", new_sid)) else [], ensure_ascii=False)

            now = datetime.now().isoformat()
            set_clause = ', '.join(k + ' = ?' for k in updates)
            conn.execute(
                "UPDATE graduated_knowledge SET " + set_clause + ", updated_at = ? WHERE id = ?",
                (*updates.values(), now, knowledge_id),
            )
            conn.commit()

            changed = list(updates.keys())
            self.add_log("update", "更新知识 #" + str(knowledge_id) + "「"
                + (d.get('title') or '')[:40] + "」: " + ", ".join(changed),
                "knowledge", knowledge_id, knowledge_id)
            logger.info(f"[KnowledgeGraduator] 知识 #{knowledge_id} 已原地更新: {changed}")
            return {"success": True, "id": knowledge_id, "updated": changed, "message": "知识 #" + str(knowledge_id) + " 已更新"}
        finally:
            conn.close()
