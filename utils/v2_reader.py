# -*- coding: utf-8 -*-
"""v2.0 数据只读访问器（家庭协作版）。

helper 插件通过本类查询 v2_memory.db（记忆生态系统 v2.0 数据）：
- memory_causality   因果证据链（双向遍历）
- memory_conflicts   三级冲突记录
- memory_profile     记忆画像
- memory_prophecies  记忆预言
- memory_expression_log  表达联动日志

同时直连主库 livingmemory.db 的 documents 表，用于「关键词 → memory_id」定位。
全部为只读连接（mode=ro），零写入、零耦合、不怕插件热重载。
"""
import json
import sqlite3
from typing import Any


class V2Reader:
    """只读访问 v2 数据。"""

    def __init__(self, main_db_path: str, v2_db_path: str):
        self.main_db_path = main_db_path.replace("\\", "/")
        self.v2_db_path = v2_db_path.replace("\\", "/")
        self._conn: sqlite3.Connection | None = None
        self._v2_conn: sqlite3.Connection | None = None

    # ─────────── 连接管理 ───────────

    def _main(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(f"file:{self.main_db_path}?mode=ro", uri=True)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _v2(self) -> sqlite3.Connection:
        if self._v2_conn is None:
            self._v2_conn = sqlite3.connect(f"file:{self.v2_db_path}?mode=ro", uri=True)
            self._v2_conn.row_factory = sqlite3.Row
        return self._v2_conn

    def close(self) -> None:
        for c in (self._conn, self._v2_conn):
            if c is not None:
                try:
                    c.close()
                except BaseException:
                    pass
        self._conn = self._v2_conn = None

    def _get_doc(self, doc_id: int) -> str:
        """取主库记忆内容（截断 200 字）。"""
        try:
            cur = self._main().execute(
                "SELECT text FROM documents WHERE id=?", (doc_id,)
            )
            row = cur.fetchone()
            if row:
                return (row["text"] or "")[:200]
        except BaseException:
            pass
        return ""

    # ─────────── 关键词 → memory_id ───────────

    def find_memory_id(self, keyword: str, limit: int = 5) -> list[dict]:
        """主库模糊查记忆。返回 [{id, text, created_at}]。"""
        try:
            cur = self._main().execute(
                "SELECT id, text, created_at FROM documents "
                "WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{keyword}%", limit),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    # ─────────── 画像 ───────────

    def get_profile(self, persona_id: str = "default", limit: int = 20) -> list[dict]:
        try:
            cur = self._v2().execute(
                "SELECT trait_key, trait_value, confidence, evidence_ids, updated_at "
                "FROM memory_profile WHERE persona_id=? ORDER BY confidence DESC LIMIT ?",
                (persona_id, limit),
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                try:
                    r["evidence_ids"] = json.loads(r.get("evidence_ids") or "[]")
                except (TypeError, ValueError):
                    r["evidence_ids"] = []
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    # ─────────── 冲突 ───────────

    def get_conflicts(self, status: str | None = None, limit: int = 20) -> list[dict]:
        sql = (
            "SELECT id, new_memory_id, old_memory_id, level, conflict_type, reason, "
            "confidence, status, created_at FROM memory_conflicts"
        )
        args: list[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        try:
            rows = [dict(r) for r in self._v2().execute(sql, args).fetchall()]
            for r in rows:
                r["new_content"] = self._get_doc(r.get("new_memory_id") or 0)
                r["old_content"] = self._get_doc(r.get("old_memory_id") or 0)
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    # ─────────── 预言 ───────────

    def get_prophecies(self, status: str | None = None, limit: int = 20) -> list[dict]:
        sql = (
            "SELECT id, content, base_memory_id, prophecy_type, ttl_days, created_at, "
            "expires_at, status, verified_at, verification, strength_before, strength_after "
            "FROM memory_prophecies"
        )
        args: list[Any] = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        try:
            rows = [dict(r) for r in self._v2().execute(sql, args).fetchall()]
            for r in rows:
                try:
                    r["verification"] = json.loads(r.get("verification") or "{}")
                except (TypeError, ValueError):
                    r["verification"] = {}
                if r.get("base_memory_id"):
                    r["base_content"] = self._get_doc(r["base_memory_id"])
                else:
                    r["base_content"] = ""
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    # ─────────── 家庭反馈日志（v2.1）───────────

    def get_feedback(self, limit: int = 30) -> list[dict]:
        """读取家庭反馈日志 feedback_log（只读）。"""
        try:
            rows = [
                dict(r)
                for r in self._v2()
                .execute(
                    "SELECT id, from_module, to_module, event_type, memory_id, "
                    "payload, created_at FROM feedback_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
                .fetchall()
            ]
            for r in rows:
                try:
                    r["payload"] = json.loads(r.get("payload") or "{}")
                except (TypeError, ValueError):
                    r["payload"] = {}
            return rows
        except Exception as e:  # noqa: BLE001
            return [{"error": str(e)}]

    def count_feedback(self) -> dict:
        """feedback_log 分组统计：总数 + 按事件类型计数。"""
        try:
            conn = self._v2()
            total = conn.execute("SELECT COUNT(*) AS c FROM feedback_log").fetchone()["c"]
            by_type = {
                r["event_type"]: r["c"]
                for r in conn.execute(
                    "SELECT event_type, COUNT(*) AS c FROM feedback_log "
                    "GROUP BY event_type ORDER BY c DESC"
                ).fetchall()
            }
            by_pair = {
                f"{r['from_module']}→{r['to_module']}": r["c"]
                for r in conn.execute(
                    "SELECT from_module, to_module, COUNT(*) AS c FROM feedback_log "
                    "GROUP BY from_module, to_module ORDER BY c DESC"
                ).fetchall()
            }
            return {"total": total, "by_type": by_type, "by_pair": by_pair}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "total": 0, "by_type": {}, "by_pair": {}}

    # ─────────── 因果链遍历 ───────────

    def trace_causal(
        self, memory_id: int, direction: str = "both", max_depth: int = 5
    ) -> dict:
        """按记忆 ID 双向遍历因果证据链。"""
        try:
            v2 = self._v2()
            cur = v2.execute(
                "SELECT id, memory_id, trigger_type, trigger_message, pre_cause_id, "
                "role, context_snapshot, created_at FROM memory_causality WHERE memory_id=?",
                (memory_id,),
            )
            node = cur.fetchone()
            if not node:
                return {"found": False, "memory_id": memory_id}
            node = dict(node)
            node["content"] = self._get_doc(memory_id)
            try:
                node["context_snapshot"] = json.loads(node.get("context_snapshot") or "{}")
            except (TypeError, ValueError):
                node["context_snapshot"] = {}

            causes: list[dict] = []
            effects: list[dict] = []

            # 前因链：沿 pre_cause_id 回溯
            pid = node.get("pre_cause_id")
            seen: set[int] = set()
            depth = 0
            while pid and depth < max_depth:
                if pid in seen:
                    break
                seen.add(pid)
                cur = v2.execute(
                    "SELECT id, memory_id, role, created_at FROM memory_causality WHERE id=?",
                    (pid,),
                )
                prow = cur.fetchone()
                if not prow:
                    break
                prow = dict(prow)
                prow["content"] = self._get_doc(prow["memory_id"])
                causes.append(prow)
                pid = prow.get("id")
                depth += 1

            # 后果：引用本节点作为前因的记录
            depth = 0
            cur = v2.execute(
                "SELECT memory_id FROM memory_causality WHERE pre_cause_id=?",
                (node["id"],),
            )
            for r in cur.fetchall():
                if depth >= max_depth:
                    break
                cur2 = v2.execute(
                    "SELECT id, memory_id, role, created_at FROM memory_causality WHERE memory_id=?",
                    (r["memory_id"],),
                )
                erow = cur2.fetchone()
                if erow:
                    erow = dict(erow)
                    erow["content"] = self._get_doc(erow["memory_id"])
                    effects.append(erow)
                depth += 1

            result: dict[str, Any] = {"found": True, "memory_id": memory_id, "node": node}
            if direction in ("cause", "both"):
                result["causes"] = causes
            if direction in ("effect", "both"):
                result["effects"] = effects
            return result
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "memory_id": memory_id}

    # ─────────── 表达风格 ───────────

    def get_expression_style(self, persona_id: str = "default") -> dict:
        try:
            cur = self._v2().execute(
                "SELECT style_version, style_snapshot, trait_drivers, updated_at "
                "FROM memory_expression_log WHERE persona_id=? "
                "ORDER BY style_version DESC LIMIT 1",
                (persona_id,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            r = dict(row)
            try:
                r["style_snapshot"] = json.loads(r.get("style_snapshot") or "{}")
            except (TypeError, ValueError):
                r["style_snapshot"] = {}
            try:
                r["trait_drivers"] = json.loads(r.get("trait_drivers") or "[]")
            except (TypeError, ValueError):
                r["trait_drivers"] = []
            return r
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
