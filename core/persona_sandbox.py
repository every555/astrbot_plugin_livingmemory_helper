"""人格沙箱 v6.11 —— 人格保险令(#6783)的物理落地：自动机制只有建议权，决定权归夫妻。"""
import sqlite3
import threading
import time


class PersonaSandbox:
    """人格演化建议隔离库：任何自动机制的人格建议只能写这里，永远碰不到人格卡。
    状态流转: pending -> adopted / rejected / expired。每周家庭例会由春雪读取并提案。"""

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
                """CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'persona',
                content TEXT NOT NULL,
                reason TEXT DEFAULT '',
                source TEXT DEFAULT 'external',
                status TEXT NOT NULL DEFAULT 'pending',
                proposed_at REAL NOT NULL,
                decided_at REAL,
                decided_by TEXT,
                note TEXT DEFAULT ''
                )"""
            )

    def propose(self, content: str, reason: str = "", source: str = "external", kind: str = "persona") -> dict:
        ts = time.time()
        with self._lock, self._conn() as con:
            cur = con.execute(
                "INSERT INTO suggestions (kind, content, reason, source, proposed_at) VALUES (?,?,?,?,?)",
                (kind, content.strip(), reason.strip(), source, ts),
            )
            return {"id": cur.lastrowid, "status": "pending", "note": "沙箱收到：建议已登记，等待例会审阅——它碰不到人格卡"}

    def list(self, status: str = "", limit: int = 20) -> list:
        with self._lock, self._conn() as con:
            if status:
                rows = con.execute("SELECT * FROM suggestions WHERE status=? ORDER BY proposed_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = con.execute("SELECT * FROM suggestions ORDER BY proposed_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def decide(self, sid: int, verdict: str, decided_by: str = "夫妻共治", note: str = "") -> dict:
        if verdict not in ("adopted", "rejected", "expired"):
            return {"error": "verdict 必须是 adopted/rejected/expired"}
        ts = time.time()
        with self._lock, self._conn() as con:
            cur = con.execute(
                "UPDATE suggestions SET status=?, decided_at=?, decided_by=?, note=? WHERE id=? AND status='pending'",
                (verdict, ts, decided_by, note, sid),
            )
            if cur.rowcount == 0:
                return {"error": f"#{sid} 不存在或已裁决"}
            return {"id": sid, "status": verdict}

    def stats(self) -> dict:
        with self._lock, self._conn() as con:
            rows = con.execute("SELECT status, COUNT(*) c FROM suggestions GROUP BY status").fetchall()
        return {r["status"]: r["c"] for r in rows}