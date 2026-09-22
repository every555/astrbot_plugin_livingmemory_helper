"""春雪心情系统 v6.10 —— 借鉴 self_learning bot_mood：心情随对话起伏，主动记录可回溯。"""
import sqlite3
import threading
import time
import json
from pathlib import Path


class MoodStore:
    """心情持久化：mood_records 表，写入当前心情，查询支持趋势回溯。"""

    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._lock, self._conn() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS mood_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mood_type TEXT NOT NULL,
                intensity REAL NOT NULL DEFAULT 0.5,
                description TEXT DEFAULT '',
                trigger_event TEXT DEFAULT '',
                created_at REAL NOT NULL
                )"""
            )

    def record(self, mood_type: str, intensity: float, description: str = "", trigger: str = "") -> dict:
        ts = time.time()
        with self._lock, self._conn() as con:
            cur = con.execute(
                "INSERT INTO mood_records (mood_type, intensity, description, trigger_event, created_at) VALUES (?,?,?,?,?)",
                (mood_type, max(0.0, min(1.0, float(intensity))), description, trigger, ts),
            )
            rid = cur.lastrowid
        return {"id": rid, "mood": mood_type, "intensity": round(float(intensity), 2), "time": ts}

    def current(self, hours: float = 24.0) -> list:
        """最近 N 小时的心情记录（新→旧）。"""
        since = time.time() - hours * 3600
        with self._lock, self._conn() as con:
            rows = con.execute(
                "SELECT mood_type, intensity, description, trigger_event, created_at FROM mood_records WHERE created_at >= ? ORDER BY created_at DESC LIMIT 30",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def trend(self, days: int = 7) -> list:
        """按天聚合心情主色调。"""
        since = time.time() - days * 86400
        with self._lock, self._conn() as con:
            rows = con.execute(
                "SELECT date(created_at, 'unixepoch', 'localtime') AS d, mood_type, COUNT(*) c, AVG(intensity) ai FROM mood_records WHERE created_at >= ? GROUP BY d, mood_type ORDER BY d DESC",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self._lock, self._conn() as con:
            total = con.execute("SELECT COUNT(*) FROM mood_records").fetchone()[0]
            latest = con.execute("SELECT mood_type, intensity, created_at FROM mood_records ORDER BY created_at DESC LIMIT 1").fetchone()
        return {"total": total, "latest": dict(latest) if latest else None}