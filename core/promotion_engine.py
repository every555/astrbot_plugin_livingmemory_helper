# -*- coding: utf-8 -*-
"""
召回驱动晋升引擎 v1.0 — 借鉴 OpenClaw short-term-promotion
==========================================================
被反复召回的记忆 → 候选 → 橘子审批 → 常驻核心记忆索引（封顶5条）。
硬门槛(Q2-B): access_count >= 5 且最近 7 天有访问（防僵尸热点）
评分(Q2-C): score = access_count * exp(-空闲天数/30)（时间衰减加权，新召回权重高）
审批(Q3): 家庭例会第二议题 + haruyuki_promote 工具兜底
扫描(Q4): 每日 daemon 后台扫 + 工具 scan 手动兜底
退位(Q5): 流动制 — 30 天无人召回 → retire_pending → 例会提醒 → 橘子点头才真退
存储: promotions.json（不写主库，reader 侧 override）
"""
import json
import math
import os
from datetime import datetime, timedelta

try:
    from astrbot.api import logger
except Exception:
    class logger:
        @staticmethod
        def info(msg):
            print("[INFO]", msg)

        @staticmethod
        def warning(msg):
            print("[WARN]", msg)

MIN_ACCESS = 5        # 硬门槛：累计召回次数
ACTIVE_DAYS = 7       # 硬门槛：最近 N 天内有访问
MAX_PROMOTED = 5      # 核心索引常驻席位上限
CANDIDATE_TOP = 10    # 单轮扫描新增候选上限
RETIRE_DAYS = 30     # 退位判据：N 天无人召回
DECAY_TAU = 30.0     # 时间衰减常数（天）


def _parse_ts(v):
    """兼容 SQLite datetime now（空格分隔）与 ISO（T 分隔）两种格式"""
    if not v:
        return None
    s = str(v).strip()
    if "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(s[:19])
    except Exception:
        return None


class PromotionEngine:
    """召回晋升：候选筛选/评分/审批/流动退位 — 纯逻辑，rows 由调用方喂入"""

    def __init__(self, data_dir: str):
        self.data_path = os.path.join(data_dir, "promotions.json")
        d = self._load()
        self.candidates = d.get("candidates", [])
        self.promoted = d.get("promoted", [])

    def _load(self) -> dict:
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"candidates": [], "promoted": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump({"candidates": self.candidates, "promoted": self.promoted}, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    @staticmethod
    def _score(access_count: int, idle_days: float) -> float:
        """时间衰减加权: 召回越多越热，越久没召回越冷"""
        return access_count * math.exp(-max(idle_days, 0.0) / DECAY_TAU)

    # ─────────── 候选扫描（Q2: B硬门槛 + C衰减评分）───────────

    def _occupied_doc_ids(self) -> set:
        c = {x["doc_id"] for x in self.candidates if x["status"] in ("pending", "approved")}
        p = {x["doc_id"] for x in self.promoted if x["status"] in ("active", "retire_pending")}
        return c | p

    def scan(self, rows) -> list:
        """rows: [{doc_id, text, access_count, last_accessed_at}] → 新增 pending 候选"""
        now = self._now()
        occupied = self._occupied_doc_ids()
        pool = []
        for r in rows:
            did = r.get("doc_id") or r.get("id")
            if not did or did in occupied:
                continue
            ac = int(r.get("access_count") or 0)
            if ac < MIN_ACCESS:
                continue
            ts = _parse_ts(r.get("last_accessed_at"))
            if ts is None or (now - ts) > timedelta(days=ACTIVE_DAYS):
                continue
            idle = max((now - ts).total_seconds() / 86400.0, 0.0)
            pool.append((self._score(ac, idle), did, r, idle))
        pool.sort(key=lambda x: x[0], reverse=True)
        new = []
        for score, did, r, idle in pool[:CANDIDATE_TOP]:
            cand = {
                "id": max([c["id"] for c in self.candidates], default=0) + 1 + len(new),
                "doc_id": did,
                "content": (r.get("text") or "").split(chr(10))[0][:80],
                "access_count": int(r.get("access_count") or 0),
                "score": round(score, 3),
                "last_accessed_at": str(r.get("last_accessed_at") or ""),
                "status": "pending",
                "proposed_at": now.isoformat(timespec="seconds"),
            }
            self.candidates.append(cand)
            new.append(cand)
        if new:
            self._save()
            logger.info("[Promotion] 扫描新增 " + str(len(new)) + " 个晋升候选")
        return new

    # ─────────── 审批（Q3: 例会 + 工具兜底）───────────

    def approve(self, candidate_id: int):
        active = [p for p in self.promoted if p["status"] in ("active", "retire_pending")]
        if len(active) >= MAX_PROMOTED:
            return None, "常驻席位已满（" + str(MAX_PROMOTED) + "条），先处理退位再晋升哦"
        for c in self.candidates:
            if c["id"] == candidate_id and c["status"] == "pending":
                c["status"] = "approved"
                c["approved_at"] = self._now().isoformat(timespec="seconds")
                entry = {
                    "doc_id": c["doc_id"],
                    "content": c["content"],
                    "status": "active",
                    "approved_at": c["approved_at"],
                    "last_accessed_at": c.get("last_accessed_at", ""),
                }
                self.promoted.append(entry)
                self._save()
                logger.info("[Promotion] 晋升 doc#" + str(c["doc_id"]) + " → 核心索引")
                return entry, ""
        return None, "未找到待审候选 #" + str(candidate_id)

    def reject(self, candidate_id: int):
        for c in self.candidates:
            if c["id"] == candidate_id and c["status"] == "pending":
                c["status"] = "rejected"
                c["rejected_at"] = self._now().isoformat(timespec="seconds")
                self._save()
                return c, ""
        return None, "未找到待审候选 #" + str(candidate_id)

    # ─────────── 流动退位（Q5: 30天无人召回 → 提醒 → 审批）───────────

    def check_retire(self, access_map: dict) -> list:
        """access_map: {doc_id: last_accessed_at} → 超30天 → retire_pending（不静默退）"""
        now = self._now()
        proposals = []
        for p in self.promoted:
            if p["status"] != "active":
                continue
            ts = _parse_ts(access_map.get(p["doc_id"]) or p.get("last_accessed_at"))
            if ts is None or (now - ts).days <= RETIRE_DAYS:
                continue
            p["status"] = "retire_pending"
            p["retire_proposed_at"] = now.isoformat(timespec="seconds")
            proposals.append(p)
        if proposals:
            self._save()
            logger.info("[Promotion] " + str(len(proposals)) + " 条常驻记忆待退位审批")
        return proposals

    def confirm_retire(self, doc_id) -> dict:
        for p in self.promoted:
            if p["doc_id"] == doc_id and p["status"] in ("retire_pending", "active"):
                p["status"] = "retired"
                p["retired_at"] = self._now().isoformat(timespec="seconds")
                self._save()
                return p
        return {}

    def keep(self, doc_id) -> dict:
        """橘子说这条不退 → 回 active，继续服役"""
        for p in self.promoted:
            if p["doc_id"] == doc_id and p["status"] == "retire_pending":
                p["status"] = "active"
                p.pop("retire_proposed_at", None)
                self._save()
                return p
        return {}

    # ─────────── 查询 ───────────

    def list_active_doc_ids(self) -> list:
        """核心索引合并用（retire_pending 尚未批准退，仍常驻）"""
        return [p["doc_id"] for p in self.promoted if p["status"] in ("active", "retire_pending")]

    def list_candidates(self, status: str = "pending") -> list:
        return [c for c in self.candidates if c["status"] == status]

    def meeting_brief(self) -> str:
        """例会第二议题文本：晋升候选审批 + 退位提醒"""
        lines = []
        pend = self.list_candidates("pending")
        if pend:
            lines.append("【第二议题 · 晋升候选 " + str(len(pend)) + " 条】（批准=常驻核心索引，席位 " + str(len(self.list_active_doc_ids())) + "/" + str(MAX_PROMOTED) + "）")
            for c in pend:
                lines.append("  #" + str(c["id"]) + " [召回" + str(c["access_count"]) + "次/评分" + str(c["score"]) + "] " + c["content"][:60])
        rp = [p for p in self.promoted if p["status"] == "retire_pending"]
        if rp:
            lines.append("【退位提醒 " + str(len(rp)) + " 条】（" + str(RETIRE_DAYS) + "天无人召回，批准退位还是保留？）")
            for p in rp:
                lines.append("  doc#" + str(p["doc_id"]) + " " + p["content"][:60] + "（回复 keep 保留 / retire 退位）")
        if not lines:
            lines.append("【第二议题 · 晋升】本期无待审候选，常驻席位 " + str(len(self.list_active_doc_ids())) + "/" + str(MAX_PROMOTED) + "。")
        return chr(10).join(lines)
