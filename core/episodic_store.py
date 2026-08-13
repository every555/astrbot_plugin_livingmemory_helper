# -*- coding: utf-8 -*-
"""
EpisodicStore — v6.0 情节记忆扩展模块
====================================
为因果链（memory_causality）补充 AIRI 风格的情节记忆结构：
- event_type    事件类型（conversation/action/discovery/decision/milestone）
- participants  参与者列表（JSON 数组）
- location      事件发生地点/场景

设计理念（借鉴 AIRI memory-pgvector 的 episodic memory）：
因果链本身记录「A 导致了 B」，但缺少「这件事发生在什么场景、谁参与了、是什么类型的事件」。
EpisodicStore 作为 helper 自有 DB 的覆盖层，不修改 livingmemory 的 v2_memory.db，
通过 memory_id 关联，在因果链查询时合并返回。
"""
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# 事件类型枚举
EVENT_TYPES = {
    "conversation": "对话交流",
    "action": "执行操作",
    "discovery": "发现/洞察",
    "decision": "决策/决定",
    "milestone": "里程碑事件",
    "emotion": "情感事件",
    "technical": "技术事件",
    "routine": "日常惯例",
    "conflict": "冲突/矛盾",
    "collaboration": "协作",
}


class EpisodicStore:
    """情节记忆扩展存储"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_metadata (
                    memory_id   TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL DEFAULT 'conversation',
                    participants TEXT NOT NULL DEFAULT '[]',
                    location    TEXT NOT NULL DEFAULT '',
                    summary     TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_type
                ON episodic_metadata(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_episodic_location
                ON episodic_metadata(location)
            """)
            conn.commit()
        logger.info(f"[EpisodicStore] v6.0 情节记忆扩展已初始化: {self.db_path}")

    def store(self, memory_id: str, event_type: str = "conversation",
              participants: list = None, location: str = "",
              summary: str = "") -> bool:
        """存储/更新一条记忆的情节元数据（UPSERT）。

        Args:
            memory_id: 主库记忆 ID
            event_type: 事件类型（见 EVENT_TYPES）
            participants: 参与者列表，如 ["橘子", "春雪"]
            location: 场景/地点，如 "WebChat" / "VSCode" / "家里"
            summary: 一句话情节摘要
        """
        now = datetime.now().isoformat()
        participants_json = json.dumps(participants or [], ensure_ascii=False)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO episodic_metadata
                        (memory_id, event_type, participants, location, summary,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        event_type=excluded.event_type,
                        participants=excluded.participants,
                        location=excluded.location,
                        summary=excluded.summary,
                        updated_at=excluded.updated_at
                """, (str(memory_id), event_type, participants_json,
                      location, summary, now, now))
                conn.commit()
            return True
        except Exception as e:
            logger.warning(f"[EpisodicStore] 存储失败 memory_id={memory_id}: {e}")
            return False

    def get_by_memory(self, memory_id: str) -> Optional[dict]:
        """查询单条记忆的情节元数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM episodic_metadata WHERE memory_id = ?",
                    (str(memory_id),)
                ).fetchone()
                if not row:
                    return None
                result = dict(row)
                result["participants"] = json.loads(result.get("participants", "[]"))
                return result
        except Exception:
            return None

    def get_by_type(self, event_type: str, limit: int = 20) -> list[dict]:
        """按事件类型查询"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM episodic_metadata WHERE event_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (event_type, limit)
                ).fetchall()
                results = []
                for row in rows:
                    r = dict(row)
                    r["participants"] = json.loads(r.get("participants", "[]"))
                    results.append(r)
                return results
        except Exception:
            return []

    def get_by_location(self, location: str, limit: int = 20) -> list[dict]:
        """按地点/场景查询"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM episodic_metadata WHERE location LIKE ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (f"%{location}%", limit)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_stats(self) -> dict:
        """情节记忆统计"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute(
                    "SELECT COUNT(*) FROM episodic_metadata"
                ).fetchone()[0]
                type_dist = {}
                for r in conn.execute(
                    "SELECT event_type, COUNT(*) as cnt FROM episodic_metadata "
                    "GROUP BY event_type ORDER BY cnt DESC"
                ).fetchall():
                    type_dist[r[0]] = r[1]
                loc_dist = {}
                for r in conn.execute(
                    "SELECT location, COUNT(*) as cnt FROM episodic_metadata "
                    "WHERE location != '' GROUP BY location ORDER BY cnt DESC LIMIT 10"
                ).fetchall():
                    loc_dist[r[0]] = r[1]
                return {
                    "total": total,
                    "type_distribution": type_dist,
                    "location_distribution": loc_dist,
                }
        except Exception as e:
            logger.warning(f"[EpisodicStore] 统计查询失败: {e}")
            return {"total": 0, "type_distribution": {}, "location_distribution": {}}
