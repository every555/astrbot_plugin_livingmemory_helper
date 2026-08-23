# -*- coding: utf-8 -*-
"""haruyuki_memory_replay 核心：failed 记忆补录引擎（2026-08-23 P2 前置）。

66 条 failed 记忆的提炼成果（content_preview + atoms）完整存活在
memory_write_ops.payload 里（documents_fts schema 坑时期，LLM 提炼成本
已付、写库炸在第一步）。本服务把它们零 LLM 成本重放回库：
清洗(测试排除/重复簇去重) → 反序列化 atoms → engine.add_memory 完整写库
(BM25+向量+graph)，metadata 携带 original_created_at 保原时间，
state.json 幂等防二跑，原 failed 记录不动（历史证据保全）。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from typing import Any

try:
    from astrbot.api import logger
except Exception:  # 单测环境
    class _L:
        info = print
        warning = print
        error = print
    logger = _L()


_TEST_PREVIEW_RE = re.compile(r"^\s*(test[\s:：,，]?memory|测试(记忆|记忆工具|工具|保存).{0,20}$)", re.I | re.S)
_PRINCIPLE_RE = re.compile(r"铁律|原则|底线|规矩|教训|约定")
_CLUSTER_WINDOW_S = 900  # 15 分钟内视为同事件窗口
_OVERLAP_THRESHOLD = 0.6


def _tokens(text: str) -> set[str]:
    """粗粒度词元：中文2字滑窗 + 英文单词，用于重复簇内容重叠判断。"""
    text = re.sub(r"\s+", "", text)
    cjk = [text[i:i + 2] for i in range(len(text) - 1) if re.match(r"[\u4e00-\u9fff]", text[i:i + 2])]
    en = re.findall(r"[a-zA-Z_]{3,}", text)
    return set(cjk) | set(w.lower() for w in en)


def _is_test_preview(pv: str) -> bool:
    pv = (pv or "").strip()
    if not pv:
        return True
    if len(pv) <= 30 and ("test" in pv.lower() or "测试" in pv):
        return True
    return bool(_TEST_PREVIEW_RE.search(pv))


class MemoryReplayService:
    """failed 记忆补录：清洗 → 反序列化 → 重放。引擎注入，纯逻辑可单测。"""

    def __init__(self, db_path: str, state_path: str, engine: Any = None):
        self.db_path = db_path
        self.state_path = state_path
        self.engine = engine

    # ── 幂等 state ──

    def _recover_from_db(self) -> set[int]:
        """库反查：已写入的 replay 标记（state 丢失时的兜底恢复）。"""
        done: set[int] = set()
        try:
            con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT metadata FROM documents WHERE metadata LIKE '%replay_of_op%'"
                ).fetchall()
                for (meta,) in rows:
                    try:
                        v = json.loads(meta).get("replay_of_op_id")
                        if v is not None:
                            done.add(int(v))
                    except Exception:
                        continue
            finally:
                con.close()
        except Exception:
            pass
        return done

    def _load_state(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
            ids = st.get("replayed_op_ids") or []
            st["replayed_op_ids"] = [int(x) for x in ids]
            return st
        except Exception:
            return {"replayed_op_ids": [], "updated": None}

    def _save_state(self, st: dict) -> None:
        st["updated"] = datetime.now().isoformat(timespec="seconds")
        tmp = self.state_path + ".tmp"
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    # ── 收集与清洗 ──

    def collect_failed_ops(self) -> list[dict]:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT id, op_type, status, step, payload, created_at"
                " FROM memory_write_ops WHERE status = ? AND op_type = ?"
                " ORDER BY created_at",
                ("failed", "add"),
            ).fetchall()
        finally:
            con.close()
        ops = []
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except Exception:
                payload = {}
            ops.append({
                "id": int(r["id"]),
                "step": r["step"],
                "created_at": float(r["created_at"] or 0),
                "payload": payload,
            })
        return ops

    def clean_candidates(self, ops: list[dict]):
        """返回 (keep, skip_report)。skip_report: {op_id: 原因}。"""
        keep: list[dict] = []
        skip: dict[int, str] = {}
        pending: list[dict] = []  # 无 atoms 的进入时间窗聚类
        for op in ops:
            pv = str(op["payload"].get("content_preview") or "")
            if _is_test_preview(pv):
                skip[op["id"]] = "test"
            elif _PRINCIPLE_RE.search(pv):
                keep.append(op)  # 原则/铁律/教训类：一条都不能丢
            elif op["payload"].get("atoms"):
                keep.append(op)
            else:
                pending.append(op)

        # 时间窗 + 内容重叠去重（同事件多次提交变体只留最长）
        pending.sort(key=lambda o: o["created_at"])
        cluster: list[dict] = []
        for op in pending:
            if cluster and op["created_at"] - cluster[-1]["created_at"] > _CLUSTER_WINDOW_S:
                self._dedup_cluster(cluster, keep, skip)
                cluster = []
            cluster.append(op)
        if cluster:
            self._dedup_cluster(cluster, keep, skip)
        keep.sort(key=lambda o: o["created_at"])
        return keep, skip

    @staticmethod
    def _dedup_cluster(cluster: list[dict], keep: list[dict], skip: dict) -> None:
        cluster.sort(key=lambda o: len(str(o["payload"].get("content_preview") or "")), reverse=True)
        kept_tokens: list[set[str]] = []
        kept_ops: list[dict] = []
        for op in cluster:
            tok = _tokens(str(op["payload"].get("content_preview") or ""))
            dup = False
            if not tok and kept_tokens:
                dup = True  # 空token(过短)且簇内已有保留记录 → 重复
            for kt in kept_tokens:
                if not tok or not kt:
                    continue
                inter = len(tok & kt)
                if inter / max(1, min(len(tok), len(kt))) >= _OVERLAP_THRESHOLD:
                    dup = True
                    break
            if dup:
                skip[op["id"]] = "dup_cluster"
            else:
                kept_tokens.append(tok)
                kept_ops.append(op)
        keep.extend(kept_ops)

    # ── 计划构建 ──

    def build_plan(self, op: dict) -> dict:
        p = op["payload"]
        content = str(p.get("content_preview") or "").strip()
        md = dict(p.get("metadata") or {})
        md["original_created_at"] = op["created_at"]
        md["replay_of_op_id"] = op["id"]
        md["replayed_at"] = time.time()
        md["replay_source"] = "haruyuki_memory_replay"
        return {
            "op_id": op["id"],
            "content": content,
            "session_id": p.get("session_id"),
            "persona_id": p.get("persona_id"),
            "importance": float(p.get("importance") or 0.5),
            "metadata": md,
            "atoms": self._deserialize_atoms(p.get("atoms") or []),
        }

    _atom_cls_cache = None

    @classmethod
    def _load_atom_cls(cls):
        """按文件路径直载 MemoryAtom（绕开本体插件包 __init__ 的宿主依赖链）。"""
        if cls._atom_cls_cache is not None:
            return cls._atom_cls_cache
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        target = os.path.join(
            os.path.dirname(os.path.dirname(here)),
            "astrbot_plugin_livingmemory", "core", "models", "memory_atom.py")
        spec = importlib.util.spec_from_file_location("_lm_replay_memory_atom", target)
        mod = importlib.util.module_from_spec(spec)
        import sys as _sys
        _sys.modules["_lm_replay_memory_atom"] = mod  # dataclass(slots=True) 需要在册模块
        spec.loader.exec_module(mod)
        cls._atom_cls_cache = (mod.AtomType, mod.MemoryAtom)
        return cls._atom_cls_cache

    @classmethod
    def _deserialize_atoms(cls, payloads: list) -> list:
        try:
            AtomType, MemoryAtom = cls._load_atom_cls()
        except Exception:
            logger.error("[MemoryReplay] MemoryAtom 导入失败，atoms 将以空重放")
            return []
        atoms = []
        for ap in payloads:
            if not isinstance(ap, dict):
                continue
            content = str(ap.get("content") or "").strip()
            if not content:
                continue
            try:
                at = AtomType(ap.get("atom_type") or "unknown")
            except ValueError:
                at = AtomType.UNKNOWN
            kw = dict(
                parent_memory_id=0,
                atom_type=at,
                content=content,
                entities=[str(e) for e in (ap.get("entities") or [])],
                importance=float(ap.get("importance") or 0.5),
                confidence=float(ap.get("confidence") or 0.7),
                created_at=float(ap.get("created_at") or time.time()),
                session_id=ap.get("session_id"),
                persona_id=ap.get("persona_id"),
            )
            atoms.append(MemoryAtom(**kw))
        return atoms

    # ── 执行 ──

    async def replay(self, dry_run: bool = True) -> dict:
        st = self._load_state()
        done_ids = set(st["replayed_op_ids"]) | self._recover_from_db()
        ops = self.collect_failed_ops()
        keep, skip = self.clean_candidates(ops)
        plans, skipped_done = [], []
        for op in keep:
            if op["id"] in done_ids:
                skipped_done.append(op["id"])
            else:
                plans.append(self.build_plan(op))
        report = {
            "dry_run": dry_run,
            "candidates_total": len(ops),
            "skipped_test": sum(1 for v in skip.values() if v == "test"),
            "skipped_dup": sum(1 for v in skip.values() if v == "dup_cluster"),
            "skipped_already": len(skipped_done),
            "planned": len(plans),
            "succeeded": 0,
            "failed": 0,
            "failed_detail": [],
            "preview": [
                {
                    "op_id": pl["op_id"],
                    "date": datetime.fromtimestamp(pl["metadata"]["original_created_at"]).strftime("%m-%d"),
                    "head": pl["content"][:40],
                    "atoms": len(pl["atoms"]),
                }
                for pl in plans[:8]
            ],
        }
        if dry_run or not plans:
            return report
        if self.engine is None:
            report["failed_detail"].append("engine is None")
            report["failed"] = len(plans)
            return report
        for pl in plans:
            try:
                await self.engine.add_memory(
                    pl["content"],
                    session_id=pl["session_id"],
                    persona_id=pl["persona_id"],
                    importance=pl["importance"],
                    metadata=pl["metadata"],
                    atoms=pl["atoms"],
                )
                report["succeeded"] += 1
                st["replayed_op_ids"].append(pl["op_id"])
                self._save_state(st)  # 即时存盘：断点续跑
            except Exception as e:
                report["failed"] += 1
                report["failed_detail"].append("op#" + str(pl["op_id"]) + ": " + str(e)[:120])
        self._save_state(st)
        return report
