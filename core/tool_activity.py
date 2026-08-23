# -*- coding: utf-8 -*-
"""P2-⑩ 工具日志桥（Tool Activity Bridge，MIRIX tool activity 本地化）。

错误-修复链自动进知识毕业流程：
    log_monitor 的未确认错误 × superpowers 的开发战报 → 匹配 → 知识毕业候选。

设计原则（与家庭反馈回路 A6/A8/A9 一脉相承）：
- 只提议、不裁决：生成的是 knowledge 候选，翻牌权永远在橘子。
- dry_run 默认开：先看预览，确认了才真 propose。
- 幂等：按错误 signature 去重（state.json 持久化），重启/重跑不重复提议。
- 降级：任何一步失败只计数告警，绝不炸调用方。
"""
import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger("tool_activity")

_TOKEN_RE = re.compile(r"[a-z_][a-z0-9_.]{3,}", re.I)

# 未确认错误够格线：出现次数 ≥2 或级别为 TRACEBACK/ERROR
_MIN_OCCURRENCE = 2
_HOT_LEVELS = {"traceback", "error"}


def _tokens(*texts: str) -> set:
    out = set()
    for t in texts:
        if not t:
            continue
        out.update(m.lower() for m in _TOKEN_RE.findall(str(t)))
    return out


class ToolActivityBridge:
    def __init__(self, log_errors_db: str, warstories_path: str,
                 graduator: Any = None, state_path: Optional[str] = None):
        self.log_errors_db = log_errors_db
        self.warstories_path = warstories_path
        self.graduator = graduator
        self.state_path = state_path
        self._processed: set = set(self._load_state())

    # ── state 持久化（防重启重复提议）──
    def _load_state(self) -> list:
        if not self.state_path or not os.path.exists(self.state_path):
            return []
        try:
            with open(self.state_path, encoding="utf-8") as f:
                return json.load(f).get("processed_signatures", [])
        except Exception:
            logger.warning("[ToolBridge] state.json 读取失败，按空处理", exc_info=True)
            return []

    def _save_state(self) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump({"processed_signatures": sorted(self._processed),
                           "updated": datetime.now().isoformat()}, f, ensure_ascii=False, indent=1)
        except Exception:
            logger.warning("[ToolBridge] state.json 写入失败", exc_info=True)

    # ── 数据读取 ──
    def _load_errors(self) -> list:
        rows = []
        try:
            con = sqlite3.connect(f"file:{self.log_errors_db}?mode=ro", uri=True)
            try:
                for r in con.execute(
                    "SELECT id, signature, occurrence, level, location, message "
                    "FROM log_errors WHERE acknowledged = 0"
                ):
                    occ, level = int(r[2] or 0), str(r[3] or "")
                    eligible = occ >= _MIN_OCCURRENCE or level.lower() in _HOT_LEVELS
                    rows.append({"error_id": r[0], "signature": str(r[1] or ""),
                                 "occurrence": occ, "level": level, "eligible": eligible,
                                 "location": str(r[4] or ""), "message": str(r[5] or "")})
            finally:
                con.close()
        except Exception:
            logger.warning("[ToolBridge] log_errors 读取失败", exc_info=True)
        return rows

    def _load_warstories(self) -> list:
        entries = []
        try:
            with open(self.warstories_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    meta = e.get("meta") or {}
                    kws = meta.get("keywords") or []
                    if isinstance(kws, str):
                        kws = [k.strip() for k in re.split(r"[,，]", kws) if k.strip()]
                    kw_set = {str(k).lower() for k in kws} | _tokens(meta.get("task", ""))
                    entries.append({"warstory_id": str(e.get("id") or meta.get("task", "?")),
                                    "task": str(meta.get("task", "")),
                                    "keywords": kw_set,
                                    "lessons": str(e.get("lessons", ""))[:120],
                                    "breakthrough": str(e.get("breakthrough", ""))[:80]})
        except FileNotFoundError:
            logger.info("[ToolBridge] warstories.jsonl 不存在（还没有战报）")
        except Exception:
            logger.warning("[ToolBridge] warstories 读取失败", exc_info=True)
        return entries  # 后写在前：最近的战报优先

    # ── 匹配 ──
    def _match(self, errors: list, stories: list) -> dict:
        matched, orphans = [], []
        for err in errors:
            if not err.get("eligible"):
                orphans.append(err)  # 不够毕业线：可见但不参与匹配/提议
                continue
            err_toks = _tokens(err["signature"], err["message"], err["location"])
            best, best_overlap = None, set()
            for st in stories:  # 最近的在前
                overlap = err_toks & st["keywords"]
                strong = any(len(t) >= 8 for t in overlap)
                if len(overlap) >= 2 or (len(overlap) == 1 and strong):
                    if len(overlap) > len(best_overlap):
                        best, best_overlap = st, overlap
            if best:
                matched.append({**err, "warstory_id": best["warstory_id"],
                                "warstory_task": best["task"],
                                "lessons_preview": best["lessons"],
                                "matched_terms": sorted(best_overlap)[:6]})
            else:
                orphans.append(err)
        return {"matched": matched, "orphans": orphans}

    def scan(self) -> dict:
        errors = self._load_errors()
        stories = self._load_warstories()
        r = self._match(errors, stories)
        r["errors_scanned"] = len(errors)
        r["warstories_loaded"] = len(stories)
        return r

    # ── 收割：matched → 知识候选 ──
    def harvest(self, dry_run: bool = True) -> dict:
        r = self.scan()
        out = {"proposed": 0, "skipped_dup": 0, "failed": 0,
               "preview": [], "orphans": r["orphans"], "dry_run": dry_run}
        for m in r["matched"]:
            sig = m["signature"]
            if sig in self._processed:
                out["skipped_dup"] += 1
                continue
            readable = (m["message"] or sig)[:50]
            title = f"[工具桥] {readable}（错误-修复链）"
            conclusion = (f"错误「{readable}」出现{m['occurrence']}次，已由战报「{m['warstory_task'][:30]}」修复。"
                          f"教训：{m['lessons_preview'] or '见战报 lessons'}。匹配词：{'/'.join(m['matched_terms'])}")
            if dry_run:
                out["preview"].append({"title": title, "conclusion": conclusion,
                                       "error_id": m["error_id"], "warstory_id": m["warstory_id"]})
                continue
            if self.graduator is None:
                out["failed"] += 1
                continue
            try:
                res = self.graduator.propose_candidate(
                    title=title, conclusion=conclusion,
                    background="P2-⑩ 工具日志桥：log_monitor错误×superpowers战报自动匹配（MIRIX tool activity）",
                    source_type="insight", source_id=0, knowledge_type="technical",
                    tags=["tool_log_bridge", "错误修复链"], importance=0.6)
                if res.get("status") == "rejected":
                    out["failed"] += 1
                    logger.warning(f"[ToolBridge] propose 被拒: {res.get('message')}")
                    continue
                out["proposed"] += 1
                self._processed.add(sig)
            except Exception:
                out["failed"] += 1
                logger.warning("[ToolBridge] propose 异常", exc_info=True)
        if not dry_run:
            self._save_state()
        return out
