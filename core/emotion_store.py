# -*- coding: utf-8 -*-
"""
EmotionStore — v6.0 记忆情感持久化模块
======================================
将 EmotionEngine 的分析结果持久化到 helper 自己的 SQLite 数据库，
实现 AIRI memory-pgvector 的「情感标记」特性：每条记忆附带情感维度数据。

表结构：memory_emotions
- memory_id        TEXT   关联 livingmemory 主库 documents.id
- emotional_impact INTEGER -10 ~ +10（正面为正，负面为负）
- emotion_type     TEXT   细粒度情绪标签（happy/sad/angry/...）
- polarity         TEXT   极性（positive/negative/neutral）
- intensity        REAL   强度 0~1
- confidence       REAL   置信度 0~1
- speaker          TEXT   说话角色（user/ai）
- created_at       TEXT   ISO 时间戳

特性：
1. 幂等写入（同 memory_id 重复写会 UPSERT）
2. 趋势查询（最近 N 条 / 最近 N 天）
3. 情感热力图数据（按情绪类型分组统计）
4. 与 EmotionEngine.analyze() 结果格式直接对接
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class EmotionStore:
    """记忆情感持久化存储"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """创建表（幂等）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_emotions (
                    memory_id        TEXT PRIMARY KEY,
                    emotional_impact INTEGER NOT NULL DEFAULT 0,
                    emotion_type     TEXT NOT NULL DEFAULT 'neutral',
                    polarity         TEXT NOT NULL DEFAULT 'neutral',
                    intensity        REAL NOT NULL DEFAULT 0.0,
                    confidence       REAL NOT NULL DEFAULT 0.0,
                    speaker          TEXT NOT NULL DEFAULT 'user',
                    created_at       TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotions_type
                ON memory_emotions(emotion_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotions_impact
                ON memory_emotions(emotional_impact)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_emotions_created
                ON memory_emotions(created_at)
            """)
            conn.commit()
        logger.info(f"[EmotionStore] v6.0 情感存储已初始化: {self.db_path}")

    @staticmethod
    def _impact_from_analysis(analysis: dict) -> int:
        """将 EmotionEngine.analyze() 结果转换为 -10 ~ +10 的情感影响力分数。

        正面情绪 → 正分，负面 → 负分，中性 → 0。
        分数大小由 intensity × confidence 决定。
        """
        polarity = analysis.get("sentiment", "neutral")
        intensity = analysis.get("intensity", 0.0)
        confidence = analysis.get("confidence", 0.0)

        if polarity == "neutral":
            return 0

        # 基础分 1~10，由 intensity 决定
        base = max(1, round(intensity * 10))
        # 置信度低则衰减
        base = round(base * (0.5 + 0.5 * confidence))

        return base if polarity == "positive" else -base

    def store(self, memory_id: str, analysis: dict, speaker: str = "user") -> bool:
        """存储一条记忆的情感分析结果（UPSERT）。

        Args:
            memory_id: 主库 documents.id（字符串形式）
            analysis: EmotionEngine.analyze() 返回的 dict
            speaker: 说话角色
        Returns:
            True 表示成功
        """
        impact = self._impact_from_analysis(analysis)
        emotion_type = analysis.get("emotion", "neutral")
        polarity = analysis.get("sentiment", "neutral")
        intensity = analysis.get("intensity", 0.0)
        confidence = analysis.get("confidence", 0.0)
        now = datetime.now().isoformat()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO memory_emotions
                        (memory_id, emotional_impact, emotion_type, polarity,
                         intensity, confidence, speaker, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        emotional_impact=excluded.emotional_impact,
                        emotion_type=excluded.emotion_type,
                        polarity=excluded.polarity,
                        intensity=excluded.intensity,
                        confidence=excluded.confidence,
                        speaker=excluded.speaker,
                        created_at=excluded.created_at
                """, (str(memory_id), impact, emotion_type, polarity,
                      intensity, confidence, speaker, now))
                conn.commit()
            logger.debug(f"[EmotionStore] 存储 memory_id={memory_id} "
                        f"emotion={emotion_type}({polarity}) impact={impact}")
            return True
        except Exception as e:
            logger.warning(f"[EmotionStore] 存储失败 memory_id={memory_id}: {e}")
            return False

    def get_by_memory(self, memory_id: str) -> Optional[dict]:
        """查询单条记忆的情感数据"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM memory_emotions WHERE memory_id = ?",
                    (str(memory_id),)
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def get_recent(self, limit: int = 20) -> list[dict]:
        """获取最近 N 条情感记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM memory_emotions ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def get_trend(self, days: int = 7) -> dict:
        """获取最近 N 天的情感趋势统计

        Returns:
            {
                "total": 42,
                "avg_impact": 3.2,
                "dominant_emotion": "happy",
                "dominant_polarity": "positive",
                "distribution": {"happy": 15, "frustrated": 5, ...},
                "daily_avg": [{"date": "2026-08-11", "avg_impact": 4.1, "count": 8}, ...],
            }
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM memory_emotions WHERE created_at >= ? ORDER BY created_at DESC",
                    (cutoff,)
                ).fetchall()

                if not rows:
                    return {"total": 0, "avg_impact": 0, "dominant_emotion": "neutral",
                            "dominant_polarity": "neutral", "distribution": {}, "daily_avg": []}

                impacts = [r["emotional_impact"] for r in rows]
                distribution: dict[str, int] = {}
                polarities = {"positive": 0, "negative": 0, "neutral": 0}

                for r in rows:
                    etype = r["emotion_type"]
                    distribution[etype] = distribution.get(etype, 0) + 1
                    polarities[r["polarity"]] = polarities.get(r["polarity"], 0) + 1

                dominant_emotion = max(distribution, key=distribution.get)
                dominant_polarity = max(polarities, key=polarities.get)

                # 日均趋势
                daily: dict[str, list[int]] = {}
                for r in rows:
                    date = r["created_at"][:10]
                    daily.setdefault(date, []).append(r["emotional_impact"])
                daily_avg = [
                    {"date": d, "avg_impact": round(sum(v) / len(v), 1), "count": len(v)}
                    for d, v in sorted(daily.items())
                ]

                return {
                    "total": len(rows),
                    "avg_impact": round(sum(impacts) / len(impacts), 1),
                    "dominant_emotion": dominant_emotion,
                    "dominant_polarity": dominant_polarity,
                    "distribution": distribution,
                    "daily_avg": daily_avg,
                }
        except Exception as e:
            logger.warning(f"[EmotionStore] 趋势查询失败: {e}")
            return {"total": 0, "avg_impact": 0, "dominant_emotion": "neutral",
                    "dominant_polarity": "neutral", "distribution": {}, "daily_avg": []}

    def get_heatmap(self, limit: int = 100) -> dict:
        """获取情感热力图数据（按情绪类型分组）

        Returns:
            {"happy": 15, "frustrated": 5, "neutral": 20, ...}
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT emotion_type, COUNT(*) as cnt FROM memory_emotions "
                    "GROUP BY emotion_type ORDER BY cnt DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return {r[0]: r[1] for r in rows}
        except Exception:
            return {}
