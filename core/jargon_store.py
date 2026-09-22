"""橘子方言词典 v6.10 —— 借鉴 self_learning JargonMiner：黑话登记+查询，夫妻专属语言库。"""
import sqlite3
import threading
import time


class JargonStore:
    """方言/黑话词典：content=词, meaning=含义。来源史前史导入+日常新增。"""

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
                """CREATE TABLE IF NOT EXISTS jargon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL UNIQUE,
                meaning TEXT NOT NULL,
                source TEXT DEFAULT 'manual',
                created_at REAL NOT NULL
                )"""
            )

    def add(self, content: str, meaning: str, source: str = "manual") -> dict:
        ts = time.time()
        with self._lock, self._conn() as con:
            cur = con.execute(
                "INSERT OR REPLACE INTO jargon (content, meaning, source, created_at) VALUES (?,?,?,?)",
                (content.strip(), meaning.strip(), source, ts),
            )
        return {"content": content, "meaning": meaning, "id": cur.lastrowid}

    def query(self, keyword: str) -> list:
        with self._lock, self._conn() as con:
            rows = con.execute(
                "SELECT content, meaning, source, created_at FROM jargon WHERE content LIKE ? OR meaning LIKE ? ORDER BY created_at DESC LIMIT 10",
                (f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self, limit: int = 50) -> list:
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT content, meaning, source FROM jargon ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]