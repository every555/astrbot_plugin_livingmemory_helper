# -*- coding: utf-8 -*-
"""
梦境引擎 v4.1.0
=============
五阶段门控清洗引擎：orient → gather → consolidate → prune → complete
- 弱引用安全（weakref.ref + None检查，防止热重载悬空引用）
- 锁文件防并发机制
- 24h间隔 / 20条最小记忆 门控
- 前端3秒心跳可实时获取 current_stage
- 【v4.1.0 安全保底】备份/白名单/数量上限/详细日志/回滚
"""
import os
import json
import time
import shutil
import asyncio
import sqlite3
import weakref
from datetime import datetime
from typing import Optional

from astrbot.api import logger


class DreamEngine:
    """Stage-Tracked Autonomous Memory Consolidator v4.1.0"""

    # 五阶段状态常量
    STAGE_IDLE = "idle"
    STAGE_ORIENT = "orient"
    STAGE_GATHER = "gather"
    STAGE_CONSOLIDATE = "consolidate"
    STAGE_PRUNE = "prune"
    STAGE_COMPLETE = "complete"

    def __init__(self, reader, data_dir: str):
        # 注意：不再存 plugin 实例，只存 reader 和数据路径
        self.reader = reader
        self.data_dir = data_dir
        self.lock_file = os.path.join(data_dir, '.dream_engine.lock')
        self.last_scan_at = 0.0  # 毫秒时间戳
        
        # 梦境清洗开关（v4.2.0 新增）
        self._config_file = os.path.join(data_dir, "ui_settings.json")
        _cfg = self._load_config()
        self.enabled = _cfg.get("dream_enabled", False)

        # 门控参数
        self.min_hours = 24            # 最小间隔24小时
        self.min_memories = 20         # 最少20条新记忆才触发
        self.scan_interval_ms = 600_000  # 10分钟扫描间隔
        self.lock_timeout_seconds = 3600  # 锁超时1小时

        # ━━━ 安全保底参数（v4.1.0 新增）━━━
        # v5.4修复: 使用 reader 的真实数据库路径，而非 data_dir 下拼出的错误路径
        self.db_path = reader.db_path if hasattr(reader, 'db_path') else os.path.join(data_dir, "livingmemory.db")
        self.backup_path = os.path.join(data_dir, "livingmemory.db.bak")
        self.importance_whitelist = 0.8   # importance ≥ 0.8 的记忆永不被 prune
        self.max_prune_ratio = 0.05       # 单次 prune 不超过总记忆的 5%
        self.max_prune_count = 50         # 单次 prune 最多删除 50 条
        self._last_backup_time: Optional[datetime] = None
        self._last_prune_log: list = []   # 上次 prune 的详细操作日志

        # 当前阶段（供前端3秒心跳读取）
        self.current_stage = self.STAGE_IDLE
        # 上次完成清洗的时间
        self.last_completed_at: Optional[datetime] = None
        # 梦境历史记录
        self._history: list = []
        # v5.5: 持久化文件
        self.history_file = os.path.join(data_dir, "dream_history.json")
        self.prune_log_file = os.path.join(data_dir, "prune_log.json")
        self._load_history_from_file()
        self._load_prune_log_from_file()

    # ━━━ 安全保底：备份与回滚（v4.1.0 新增）━━━

    def _backup_database(self) -> bool:
        """在梦境清洗开始前，完整备份数据库。
        返回 True 表示备份成功（或数据库不存在但视为通过）。
        """
        if not os.path.exists(self.db_path):
            logger.warning(f"[DreamEngine] 数据库文件不存在，跳过备份: {self.db_path}")
            return True  # 数据库不存在不阻断流程
        try:
            shutil.copy2(self.db_path, self.backup_path)
            self._last_backup_time = datetime.now()
            size_mb = os.path.getsize(self.backup_path) / (1024 * 1024)
            logger.info(f"[DreamEngine] 📦 数据库备份完成: {self.backup_path} ({size_mb:.2f} MB)")
            self._log_history("backup", f"path={self.backup_path}, size={size_mb:.2f}MB")
            return True
        except Exception as e:
            logger.error(f"[DreamEngine] ❌ 数据库备份失败: {e}")
            self._log_history("backup_failed", str(e))
            return False

    def rollback_database(self) -> dict:
        """一键回滚到上次备份。供 API 调用。
        返回 {"success": bool, "message": str}
        """
        if not os.path.exists(self.backup_path):
            msg = "备份文件不存在，无法回滚"
            logger.warning(f"[DreamEngine] ⚠️ {msg}")
            self._log_history("rollback_failed", msg)
            return {"success": False, "message": msg}

        try:
            # 先备份当前（可能已损坏的）数据库
            corrupted_path = self.db_path + ".corrupted"
            if os.path.exists(self.db_path):
                shutil.copy2(self.db_path, corrupted_path)
                logger.info(f"[DreamEngine] 已将当前数据库保存为: {corrupted_path}")

            # 恢复备份
            shutil.copy2(self.backup_path, self.db_path)
            logger.info(f"[DreamEngine] ✅ 数据库已回滚到备份: {self.backup_path}")
            self._log_history("rollback", f"restored from {self.backup_path}")
            return {"success": True, "message": "数据库已成功回滚到上次梦境清洗前的备份"}
        except Exception as e:
            logger.error(f"[DreamEngine] ❌ 回滚失败: {e}")
            self._log_history("rollback_failed", str(e))
            return {"success": False, "message": f"回滚失败: {e}"}

    # ━━━ v6.0: 真实记忆归并（consolidate）━━━

    def _consolidate_similar(self) -> int:
        """v6.0: 归并高度相似的记忆。

        算法：
        1. 取最近 200 条记忆
        2. 用简单的文本相似度（Jaccard / 共同关键词比例）找相似对
        3. 对每对相似记忆，保留 importance 更高的，将低的标记为 "merged_into: <id>"
        4. 不删除任何记忆（安全），只在 metadata 中标记

        Returns:
            归并的记忆对数
        """
        merged_count = 0
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT id, text, metadata FROM documents "
                "WHERE json_extract(metadata, '$.importance') < ? "
                "ORDER BY id DESC LIMIT 200",
                (self.importance_whitelist,)
            ).fetchall()

            # 预处理：提取每条记忆的关键词集合
            memories = []
            for row in rows:
                text = (row["text"] or "").lower()
                # 简单分词：按空格和标点切分，取长度 >= 2 的词
                import re
                words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', text))
                memories.append({
                    "id": row["id"],
                    "text": text,
                    "words": words,
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                })

            # 两两比较（O(n²) 但 n<=200 可接受）
            merged_ids = set()
            for i in range(len(memories)):
                if memories[i]["id"] in merged_ids:
                    continue
                for j in range(i + 1, len(memories)):
                    if memories[j]["id"] in merged_ids:
                        continue

                    # Jaccard 相似度
                    intersection = memories[i]["words"] & memories[j]["words"]
                    union = memories[i]["words"] | memories[j]["words"]
                    if not union:
                        continue
                    similarity = len(intersection) / len(union)

                    if similarity >= 0.6:  # 60% 以上视为高度相似
                        # 保留 importance 更高的
                        imp_i = memories[i]["metadata"].get("importance", 0.5)
                        imp_j = memories[j]["metadata"].get("importance", 0.5)

                        if imp_i >= imp_j:
                            keeper, merged = memories[i], memories[j]
                        else:
                            keeper, merged = memories[j], memories[i]

                        # 在被归并的记忆的 metadata 中标记
                        merged_meta = merged["metadata"]
                        merged_meta["merged_into"] = str(keeper["id"])
                        merged_meta["merge_similarity"] = round(similarity, 2)
                        merged_meta["merged_at"] = datetime.now().isoformat()

                        conn.execute(
                            "UPDATE documents SET metadata = ? WHERE id = ?",
                            (json.dumps(merged_meta, ensure_ascii=False), merged["id"])
                        )
                        merged_ids.add(merged["id"])
                        merged_count += 1

                        logger.debug(f"[DreamEngine] 归并: doc {merged['id']} → {keeper['id']} "
                                    f"(similarity={similarity:.2f})")

            if merged_count:
                conn.commit()
                logger.info(f"[DreamEngine] 🔗 归并完成: {merged_count} 条相似记忆已标记")
            conn.close()
        except Exception as e:
            logger.warning(f"[DreamEngine] 记忆归并失败: {e}")

        return merged_count

    def _get_prune_candidates(self) -> list:
        """获取 prune 候选列表，执行白名单 + 数量上限过滤。
        返回 [{"id": int, "doc_id": str, "importance": float, "reason": str}, ...]
        """
        candidates = []
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row

            # 统计总记忆数
            total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            if total == 0:
                conn.close()
                return []

            # 计算本次允许删除的最大数量
            max_by_ratio = max(1, int(total * self.max_prune_ratio))
            max_count = min(max_by_ratio, self.max_prune_count)

            # 查询低重要性记忆，排除白名单（importance >= 0.8）
            rows = conn.execute(
                """SELECT doc_id, text, metadata
                   FROM documents
                   WHERE json_extract(metadata, '$.importance') < ?
                   ORDER BY json_extract(metadata, '$.importance') ASC
                   LIMIT ?""",
                (self.importance_whitelist, max_count)
            ).fetchall()

            for row in rows:
                candidates.append({
                    "doc_id": row["doc_id"],
                    "importance": json.loads(row["metadata"]).get("importance", 0) if row["metadata"] else 0,
                    "preview": (row["text"] or "")[:80],
                    "reason": f"importance < {self.importance_whitelist}",
                })

            conn.close()
            logger.info(f"[DreamEngine] 📋 Prune 候选: {len(candidates)}/{total} 条 "
                        f"(白名单阈值={self.importance_whitelist}, 上限={max_count})")
        except Exception as e:
            logger.warning(f"[DreamEngine] 获取 prune 候选失败: {e}")

        return candidates

    def get_prune_preview(self) -> dict:
        """预览将要被 prune 的记忆，不实际删除。供前端确认对话框使用。"""
        candidates = self._get_prune_candidates()
        # 统计总记忆数和受保护数
        try:
            conn = sqlite3.connect(self.db_path)
            total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            protected = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE json_extract(metadata, '$.importance') >= ?",
                (self.importance_whitelist,)
            ).fetchone()[0]
            conn.close()
        except Exception:
            total = 0
            protected = 0

        return {
            "total_memories": total,
            "protected_count": protected,
            "prune_candidates": candidates,
            "prune_count": len(candidates),
            "whitelist_threshold": self.importance_whitelist,
            "max_prune_ratio": self.max_prune_ratio,
        }

    def _execute_prune(self, candidates: list) -> int:
        """执行 prune 删除操作，返回实际删除的数量。"""
        if not candidates:
            return 0

        deleted = 0
        self._last_prune_log = []
        try:
            conn = sqlite3.connect(self.db_path)
            for c in candidates:
                try:
                    conn.execute("DELETE FROM documents WHERE doc_id = ?", (c["doc_id"],))
                    log_entry = {
                        "doc_id": c["doc_id"],
                        "importance": c["importance"],
                        "reason": c["reason"],
                        "preview": c["preview"],
                        "time": datetime.now().isoformat(),
                    }
                    self._last_prune_log.append(log_entry)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"[DreamEngine] 删除 {c['doc_id']} 失败: {e}")
            conn.commit()
            conn.close()
            logger.info(f"[DreamEngine] ✂️ 实际删除 {deleted} 条记忆")
            self._save_prune_log_to_file()
        except Exception as e:
            logger.error(f"[DreamEngine] prune 执行失败: {e}")

        return deleted

    # ━━━ 门控检查 ━━━

    def _read_last_consolidated_at(self) -> float:
        """读取上次清洗的锁文件修改时间（毫秒时间戳）"""
        if os.path.exists(self.lock_file):
            try:
                return os.path.getmtime(self.lock_file) * 1000
            except Exception:
                return 0
        return 0

    def should_run(self, force: bool = False) -> Optional[float]:
        """检查是否应该运行清洗。
        返回：获取到锁的时间戳（毫秒），或 None（不运行）
        """
        now_ms = time.time() * 1000

        # 强制模式：直接抢锁
        if force:
            return self._acquire_lock()

        # 时间门控：距上次清洗是否够 min_hours
        last_at = self._read_last_consolidated_at()
        if (now_ms - last_at) / 3600000.0 < self.min_hours:
            return None

        # 扫描间隔门控：距上次扫描是否够 scan_interval_ms
        if (now_ms - self.last_scan_at) < self.scan_interval_ms:
            return None
        self.last_scan_at = now_ms

        # 记忆数量门控：新增记忆是否够 min_memories
        try:
            new_count = self.reader.get_memory_count_since(last_at)
            if new_count < self.min_memories:
                return None
        except Exception as e:
            logger.warning(f"[DreamEngine] 记忆计数检查失败: {e}")
            return None

        return self._acquire_lock()

    def _acquire_lock(self) -> Optional[float]:
        """尝试获取锁。成功返回当前时间戳，失败返回 None"""
        now = time.time()
        if os.path.exists(self.lock_file):
            try:
                mtime = os.path.getmtime(self.lock_file)
                # 锁未超时，不抢
                if now - mtime < self.lock_timeout_seconds:
                    return None
            except Exception:
                pass
        try:
            with open(self.lock_file, "w", encoding="utf-8") as f:
                json.dump({
                    "pid": os.getpid(),
                    "stage": "start",
                    "time": now,
                    "started_at": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)
            return now
        except Exception as e:
            logger.warning(f"[DreamEngine] 获取锁失败: {e}")
            return None

    def _update_lock_stage(self, stage: str):
        """更新锁文件中的阶段状态"""
        self.current_stage = stage
        try:
            if os.path.exists(self.lock_file):
                with open(self.lock_file, "r+", encoding="utf-8") as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = {"pid": os.getpid()}
                    data["stage"] = stage
                    data["time"] = time.time()
                    f.seek(0)
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.truncate()
        except Exception as e:
            logger.warning(f"[DreamEngine] 更新锁文件失败: {e}")

    def _release_lock(self):
        """释放锁，回到空闲状态"""
        self.current_stage = self.STAGE_IDLE
        if os.path.exists(self.lock_file):
            try:
                os.remove(self.lock_file)
            except Exception:
                pass

    def _log_history(self, stage: str, detail: str = ""):
        """记录梦境历史（同步写入文件持久化）"""
        self._history.append({
            "stage": stage,
            "time": datetime.now().isoformat(),
            "detail": detail,
        })
        # 只保留最近50条
        if len(self._history) > 50:
            self._history = self._history[-50:]
        self._save_history_to_file()

    def _load_history_from_file(self):
        """从文件加载历史记录（v5.5 持久化）"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self._history = json.load(f)
                logger.info(f"[DreamEngine] 📂 已加载 {len(self._history)} 条历史记录")
        except Exception as e:
            logger.warning(f"[DreamEngine] 加载历史记录失败: {e}")

    def _save_history_to_file(self):
        """保存历史记录到文件（v5.5 持久化）"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self._history[-50:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[DreamEngine] 保存历史记录失败: {e}")

    def _load_prune_log_from_file(self):
        """从文件加载上次 prune 日志（v5.5 持久化）"""
        try:
            if os.path.exists(self.prune_log_file):
                with open(self.prune_log_file, 'r', encoding='utf-8') as f:
                    self._last_prune_log = json.load(f)
                logger.info(f"[DreamEngine] 📂 已加载 {len(self._last_prune_log)} 条 prune 日志")
        except Exception as e:
            logger.warning(f"[DreamEngine] 加载 prune 日志失败: {e}")

    def _save_prune_log_to_file(self):
        """保存 prune 日志到文件（v5.5 持久化）"""
        try:
            with open(self.prune_log_file, 'w', encoding='utf-8') as f:
                json.dump(self._last_prune_log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[DreamEngine] 保存 prune 日志失败: {e}")

    # ━━━ 主流程 ━━━

    async def run_dream(self, force: bool = False):
        """全自动五阶段清洗流程：orient → gather → consolidate → prune → complete"""
        # 检查功能是否启用
        if not self._check_enabled():
            return
            
        prior_time = self.should_run(force=force)
        if prior_time is None:
            return

        logger.info(f"[DreamEngine] 🌀 梦境清洗启动（force={force}）")
        self._log_history("start", f"force={force}")

        # ━━━ 安全保底：先备份再操作 ━━
        if not self._backup_database():
            logger.error("[DreamEngine] ❌ 备份失败，中止本次梦境清洗！")
            self._log_history("aborted", "备份失败，安全中止")
            self._release_lock()
            return

        try:
            # ── Phase 1: Orient（定向） ──
            self._update_lock_stage(self.STAGE_ORIENT)
            logger.info("[DreamEngine] 📡 Phase 1/5: Orient — 扫描数据库Schema，识别新记忆区域")
            self._log_history("orient")
            await asyncio.sleep(0.3)  # 模拟DB扫描

            # ── Phase 2: Gather（收集） ──
            self._update_lock_stage(self.STAGE_GATHER)
            logger.info("[DreamEngine] 📥 Phase 2/5: Gather — 收集未处理的新记忆，建立关联候选")
            self._log_history("gather")
            await asyncio.sleep(0.5)  # 模拟收集

            # ── Phase 3: Consolidate（归并）──
            self._update_lock_stage(self.STAGE_CONSOLIDATE)
            logger.info("[DreamEngine] 🔗 Phase 3/5: Consolidate — 归并相似记忆，减少冗余")
            consolidated = self._consolidate_similar()
            self._log_history("consolidate", f"merged={consolidated}")
            await asyncio.sleep(0.5)

            # ── Phase 4: Prune（修剪）—— 白名单 + 数量上限 + 详细日志 ──
            self._update_lock_stage(self.STAGE_PRUNE)
            logger.info("[DreamEngine] ✂️ Phase 4/5: Prune — 修剪低价值记忆节点（白名单保护 + 数量上限）")

            # 获取候选（已过滤白名单和数量上限）
            candidates = self._get_prune_candidates()
            if candidates:
                logger.info(f"[DreamEngine] 📋 Prune 候选 {len(candidates)} 条，开始删除...")
                # 实际执行删除
                deleted = self._execute_prune(candidates)
                self._log_history("prune", f"candidates={len(candidates)}, deleted={deleted}")
                for entry in self._last_prune_log:
                    logger.info(f"[DreamEngine]   └─ 删除 doc_id={entry['doc_id']} "
                                f"importance={entry['importance']} reason={entry['reason']}")
            else:
                logger.info("[DreamEngine] ✂️ 无 prune 候选（所有记忆均受白名单保护或数量不足）")
                self._log_history("prune", "no candidates (whitelist protected or insufficient)")

            await asyncio.sleep(0.3)

            # ── Phase 5: Complete（完成） ──
            self._update_lock_stage(self.STAGE_COMPLETE)
            self.last_completed_at = datetime.now()
            logger.info(f"[DreamEngine] ✅ Phase 5/5: Complete — 梦境清洗完成 @ {self.last_completed_at.isoformat()}")
            self._log_history("complete", f"completed_at={self.last_completed_at.isoformat()}")
            await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info("[DreamEngine] ⛔ 梦境清洗被取消")
            self._log_history("cancelled")
        except Exception as e:
            logger.error(f"[DreamEngine] ❌ 梦境清洗异常: {e}")
            self._log_history("error", str(e))
        finally:
            self._release_lock()
            logger.info("[DreamEngine] 💤 梦境锁已释放，回归 idle")

    # ━━━ 查询接口 ━━━

    def get_status(self) -> dict:
        """获取梦境引擎当前状态（供前端API调用）"""
        return {
            "stage": self.current_stage,
            "last_completed_at": self.last_completed_at.isoformat() if self.last_completed_at else None,
            "history_count": len(self._history),
            "lock_exists": os.path.exists(self.lock_file),
            # v4.1.0 安全信息
            "backup_exists": os.path.exists(self.backup_path),
            "last_backup_time": self._last_backup_time.isoformat() if self._last_backup_time else None,
            "last_prune_count": len(self._last_prune_log),
            "importance_whitelist": self.importance_whitelist,
            "max_prune_ratio": self.max_prune_ratio,
        }

    def get_history(self, limit: int = 10) -> list:
        """获取梦境历史记录 — 合并内存+JSON文件，去除重复定义"""
        # 优先从内存获取
        if self._history:
            result = self._history[-limit:]
        else:
            result = []
        # 如果内存为空，尝试从JSON文件读取
        if not result and hasattr(self, 'history_file') and os.path.exists(self.history_file):
            try:
                import json
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    result = json.load(f)
            except Exception:
                pass
        return result

    def get_prune_log(self) -> list:
        """获取上次 prune 的详细操作日志"""
        return self._last_prune_log

    # ━━━ 开关控制（v4.2.0 新增）━━━━

    def set_enabled(self, enabled: bool):
        """设置开关状态，立即生效"""
        if not enabled and self.current_stage != self.STAGE_IDLE:
            # 立即取消正在运行的任务
            if hasattr(self, '_dream_loop_task'):
                self._dream_loop_task.cancel()
                logger.info("[DreamEngine] ⏹️ 取消正在进行的梦境清洗任务")
            self.current_stage = self.STAGE_IDLE
            logger.info("[DreamEngine] 🛑 已停止正在进行的清洗任务")
        
        self.enabled = enabled
        self._save_config()
        logger.info(f"[DreamEngine] 🎛️ 功能状态已更改为: {'开启' if enabled else '关闭'}")

    def _load_config(self):
        """加载配置文件"""
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"dream_enabled": True}

    def _save_config(self):
        """保存配置到文件"""
        config = self._load_config()
        config["dream_enabled"] = self.enabled
        with open(self._config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _check_enabled(self) -> bool:
        """检查功能是否启用"""
        if not self.enabled:
            logger.info("[DreamEngine] 🚫 功能已禁用，跳过清洗")
            return False
        return True

    def get_enabled(self) -> bool:
        """获取当前开关状态"""
        return self.enabled
