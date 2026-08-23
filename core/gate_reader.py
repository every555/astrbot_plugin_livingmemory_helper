# -*- coding: utf-8 -*-
"""安检门·GateReader —— helper 侧消费者（第5步 haruyuki_gate_scan 的核心逻辑）

设计依据：#1683 实现路线 / #1700 消费者定位。
- helper 对本体引擎库（v2_memory.db / livingmemory.db）保持只读纪律；
- gate.db 是安检门自己的库，裁决落盘（status/verdict/note/reviewed_at）
  不违反只读纪律——门的数据归门管。

职责：
- list_candidates：列候选区（status 过滤，metadata 解析，repeat_count 提升）
- verdict：省察时老婆裁决落盘（confirm=入库 / decline=驳回）
- stats：统计概览（含 flashbulb 预标计数）
"""
from __future__ import annotations

import json
import os
import sqlite3
import time


# ── 词表自学习 C 方案（2026-08-19 橘子批 Q1=D）──
_LEARN_STOP = {
    "老婆", "老公", "春雪", "小雪", "橘子", "明江", "宝宝", "宝贝", "游戏", "朋友",
    "时候", "今天", "明天", "后天", "现在", "事情", "东西", "地方", "问题", "样子",
    # 纯相对时间词：atom_classifier 日期通道已管，学了只会过度泛化
    "周一", "周二", "周三", "周四", "周五", "周六", "周日", "星期", "周末",
    "上午", "下午", "晚上", "早上", "中午", "夜里", "凌晨",
}


def _tokenize_nouns(text: str) -> list[str]:
    """jieba.posseg 抽名词+时间名词（flag 以 n/t 开头，≥2字，去停用词）。
    注：jieba 把"生日/纪念日"标成 t 类时间词，恰是咱家高价值词，必须收；
    纯相对时间（周三/周末）由停用词表挡住。jieba 缺失安静返回空。"""
    try:
        import jieba.posseg as pseg
    except Exception:
        return []
    try:
        return sorted({
            w for w, flag in pseg.lcut(text)
            if len(w) >= 2 and flag.startswith(("n", "t")) and w not in _LEARN_STOP
        })
    except Exception:
        return []


class GateReader:
    """读/裁决 安检门候选区（gate.db）。库不存在=门还没跑过，安静返回空。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ─────────── 内部：按需连接 ───────────

    def _get_conn(self) -> sqlite3.Connection | None:
        if self._conn is not None:
            return self._conn
        if not os.path.exists(self.db_path):
            return None  # 门还没开业（gate.db 由本体侧首次过秤时创建）
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        self._conn = conn
        return conn

    # ─────────── 查询 ───────────

    def list_candidates(self, status: str | None = None, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM gate_candidates WHERE status=? ORDER BY score DESC, id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gate_candidates ORDER BY score DESC, id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._fmt(r) for r in rows]
        except sqlite3.Error:
            return []  # 表还没建（极端：库在表不在）

    # ─────────── 裁决落盘（省察时老婆亲自调用） ───────────

    def audit_log(self, tail: int = 30) -> str:
        """省察考勤（2026-08-20 橘子"给审查系统装个日志功能"）。

        读省察审计日志 reflection_audit.log 尾部（与 gate.db 同目录，
        由本体 reflection_scheduler 写）。18:21 省察卡死无人知晓的案底，
        以后橘子问考勤 action=audit 一查便知。"""
        path = os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "reflection_audit.log"
        )
        if not os.path.exists(path):
            return ("【省察考勤】还没有审计记录（reflection_audit.log 未生成）——"
                    "本体插件重载生效后，首次省察事件自动建账。")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            shown = [l.rstrip() for l in lines[-max(1, int(tail)):]]
            return "【省察考勤·最近事件】" + chr(10) + chr(10).join(shown)
        except Exception as e:
            return f"【省察考勤】读取失败: {e}"

    def mark_memorized(self, texts) -> int:
        """豁免登记直通：老婆 memorize 完把原句喂给门（橘子10:04抓的缺口）。"""
        conn = self._get_conn()
        if conn is None:
            return 0

        if isinstance(texts, str):
            texts = [texts]
        import json as _json
        import time as _time

        def _bigrams(t: str) -> list[str]:
            import re as _re
            s = _re.sub(r"\s+", "", t)
            return [s[i:i + 2] for i in range(len(s) - 1)] if len(s) >= 2 else ([s] if s else [])

        n = 0
        for text in texts:
            t = (text or "").strip()
            if not t:
                continue
            conn.execute(
                "INSERT INTO memorized_fp (content, bigrams, created_at) VALUES (?, ?, ?)",
                (t, _json.dumps(sorted(_bigrams(t)), ensure_ascii=False), _time.time()),
            )
            n += 1
        conn.commit()
        return n

    def verdict(self, cid: int, action: str, verdict_word: str = "", note: str = "") -> bool:
        """裁决一条候选。

        action: 'confirm'（入档）/ 'decline'（驳回）
        verdict_word: 裁决词（升级/合并/驳回/加工…#1696 十词表由省察时老婆选用）
        note: 备注理由（冷启动期=门的训练食物）
        confirm 成功后顺手喂词表自学习（C 方案：名词记频，失败不影响裁决）。
        """
        if action not in ("confirm", "decline"):
            return False
        conn = self._get_conn()
        if conn is None:
            return False
        status = "confirmed" if action == "confirm" else "declined"
        try:
            row = conn.execute(
                "SELECT content, speaker FROM gate_candidates WHERE id=?", (cid,)
            ).fetchone()
            cur = conn.execute(
                "UPDATE gate_candidates SET status=?, verdict=?, note=?, reviewed_at=? WHERE id=?",
                (status, verdict_word, note, time.time(), cid),
            )
            conn.commit()
            done = cur.rowcount > 0
            if done and action == "confirm" and row is not None:
                self._learn_nouns(conn, row["content"] or "", row["speaker"] or "")
            return done
        except sqlite3.Error:
            return False

    def _learn_nouns(self, conn: sqlite3.Connection, text: str, speaker: str) -> None:
        """confirm 反馈 → 名词记频（gate.db learned_nouns 表）。
        count>=2 毕业；本体重载后并入 +0.3 高权级。任何异常安静吞掉。"""
        try:
            words = _tokenize_nouns(text)
            if not words:
                return
            now = time.time()
            conn.execute(
                """CREATE TABLE IF NOT EXISTS learned_nouns (
                    word TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 1,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    last_speaker TEXT DEFAULT '', sample TEXT DEFAULT '')"""
            )
            for w in words:
                conn.execute(
                    """INSERT INTO learned_nouns (word, count, first_seen, last_seen, last_speaker, sample)
                       VALUES (?, 1, ?, ?, ?, ?)
                       ON CONFLICT(word) DO UPDATE SET count=count+1, last_seen=?, last_speaker=?, sample=?""",
                    (w, now, now, speaker, text[:60], now, speaker, text[:60]),
                )
            conn.commit()
        except Exception:
            pass

    def learned_report(self, limit: int = 10) -> list[dict]:
        """学习词频报告：count>=2 = 毕业（重载本体后并入高权级生效）。"""
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT word, count, last_speaker, sample FROM learned_nouns "
                "ORDER BY count DESC, last_seen DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "word": r["word"], "count": r["count"],
                    "graduated": r["count"] >= 2,
                    "last_speaker": r["last_speaker"], "sample": r["sample"],
                }
                for r in rows
            ]
        except sqlite3.Error:
            return []

    # ─────────── 统计 ───────────

    def stats(self) -> dict:
        conn = self._get_conn()
        empty = {"total": 0, "candidate": 0, "confirmed": 0, "declined": 0, "flashbulb_flagged": 0}
        if conn is None:
            return empty
        try:
            out = dict(empty)
            out["total"] = conn.execute("SELECT COUNT(*) FROM gate_candidates").fetchone()[0]
            for st in ("candidate", "confirmed", "declined"):
                out[st] = conn.execute(
                    "SELECT COUNT(*) FROM gate_candidates WHERE status=?", (st,)
                ).fetchone()[0]
            out["flashbulb_flagged"] = conn.execute(
                "SELECT COUNT(*) FROM gate_candidates WHERE verdict='升级' AND status='candidate'"
            ).fetchone()[0]
            return out
        except sqlite3.Error:
            return empty

    # ─────────── 工具 ───────────

    @staticmethod
    def _fmt(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["axes"] = json.loads(d.get("axes") or "{}")
        meta = json.loads(d.get("metadata") or "{}")
        d["metadata"] = meta
        d["repeat_count"] = int(meta.get("repeat_count", 1))
        return d

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
