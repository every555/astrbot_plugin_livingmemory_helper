# -*- coding: utf-8 -*-
"""读取 LivingMemory 数据库的工具类 — v4.0.0 升级版：FTS5全文索引 + 毫秒时间戳对齐"""
import sqlite3
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from astrbot.api import logger

DEFAULT_DB_PATH = Path(
    "data/plugin_data/astrbot_plugin_livingmemory/livingmemory.db"
)

# AstrBot 插件实际以 data.plugins.<name> 加载（见 star_manager.py），
# 独立测试环境才用顶层包名。双路径兼容。
_LM_MODULE_PREFIXES = ("data.plugins.", "")


def _import_lm(module_path: str, names: str | list[str]):
    """双路径导入 livingmemory 子模块。

    Args:
        module_path: 如 "astrbot_plugin_livingmemory.core.events.event_bus"
        names: 要导入的名字（str 或 list）

    Returns:
        对应名字的对象（str 时返回单个对象，list 时返回对象列表）
    """
    is_single = isinstance(names, str)
    name_list = [names] if is_single else list(names)
    last_exc = None
    for prefix in _LM_MODULE_PREFIXES:
        try:
            mod = __import__(prefix + module_path, fromlist=name_list)
            objs = [getattr(mod, n) for n in name_list]
            return objs[0] if is_single else objs
        except (ImportError, AttributeError) as e:
            last_exc = e
    raise ImportError(f"无法导入 livingmemory 模块 {module_path}: {last_exc}")


class LivingMemoryReader:
    """v4.0.0 升级版 数据库读取层
    新增：
    - FTS5 全文虚拟索引（Porter分词加速检索）
    - SQLite TRIGGER 自动同步新记忆到索引
    - get_memory_count_since 毫秒时间戳对齐
    - 搜索先走 FTS5，降级到 LIKE 模糊匹配
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            root = os.getcwd()
            self.db_path = os.path.join(root, str(DEFAULT_DB_PATH))
        else:
            self.db_path = db_path
        self._init_fts5()

    def _connect(self):
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"LivingMemory 数据库未找到: {self.db_path}")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_fts5(self):
        """【v4.1→v5.7.1fix】初始化 FTS5 全文虚拟索引（不再抢占 AstrBot 核心的 documents_fts 表）

        重要修复：AstrBot 核心的 DocumentStorage 管理 documents_fts(contentless, search_text)，
        我们不能再 DROP 它重建为三列格式。改为检测到 AstrBot 管理的表时自动跳过，
        FTS 搜索降级为 LIKE 模糊匹配。
        """
        try:
            conn = self._connect()

            # 0. 检查 documents_fts 是否已被 AstrBot 核心管理（search_text 列）
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='documents_fts'"
            ).fetchone()

            if existing:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(documents_fts)").fetchall()]
                # AstrBot 核心用 search_text contentless 表 → 不要碰！
                if 'search_text' in cols:
                    logger.info("[LMHelper v6.0] documents_fts 由 AstrBot 核心管理，不抢占，FTS 搜索使用 LIKE 回退")
                    conn.close()
                    return
                # 旧版 livingmemory 三列格式 → 转为 LIKE 回退，不再维护自己的 FTS
                logger.info("[LMHelper v6.0] 检测到旧版三列 documents_fts，不再维护，FTS 搜索使用 LIKE 回退")
                conn.close()
                return

            # 表不存在 → 也不创建，让 AstrBot 核心管理
            logger.info("[LMHelper v6.0] documents_fts 未创建，交给 AstrBot 核心管理")
            conn.close()
        except Exception as e:
            logger.warning(f"[LMHelper v6.0] FTS5 初始化跳过（表可能已存在或无权限）: {e}")

    def _parse_meta(self, metadata_str: str) -> dict:
        if not metadata_str:
            return {}
        try:
            return json.loads(metadata_str)
        except Exception:
            return {}

    def get_memory_count(self) -> int:
        conn = self._connect()
        # 优先读 memory_atoms（持久化），fallback 到 documents
        try:
            count = conn.execute("SELECT COUNT(*) FROM memory_atoms WHERE status='active'").fetchone()[0]
        except Exception:
            count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()
        return count

    def get_memory_count_since(self, timestamp_ms: float) -> int:
        """【v4.0】统计自某个毫秒时间戳之后新增的记忆数"""
        try:
            seconds = timestamp_ms / 1000.0
            conn = self._connect()
            cursor = conn.cursor()
            # 从 memory_atoms 读（created_at 是 unix 秒时间戳）
            try:
                cursor.execute(
                    "SELECT COUNT(*) FROM memory_atoms WHERE created_at >= ? AND status='active'",
                    (seconds,)
                )
                count = cursor.fetchone()[0]
            except Exception:
                # fallback: documents 表（ISO 文本格式）
                dt_object = datetime.fromtimestamp(seconds)
                iso_text = dt_object.strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    "SELECT COUNT(*) FROM documents WHERE datetime(created_at) >= datetime(?)",
                    (iso_text,)
                )
                count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.error(f"[LMHelper] get_memory_count_since 异常: {e}")
            return 0

    def _atoms_to_result(self, rows) -> list:
        """把 memory_atoms 行转换为 WebUI 格式"""
        result = []
        for r in rows:
            d = dict(r)
            import json as _json
            meta = {}
            try:
                meta = _json.loads(d.get("metadata", "{}"))
            except Exception:
                pass
            # 转换时间戳为 ISO 格式
            ts = d.get("created_at")
            if ts and isinstance(ts, (int, float)):
                from datetime import datetime as _dt
                created_iso = _dt.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            else:
                created_iso = str(ts or "")
            result.append({
                "id": d.get("id"),
                "text": d.get("content", ""),
                "content": d.get("content", ""),
                "created_at": created_iso,
                "memory_tier": d.get("tier", 2),
                "metadata": d.get("metadata", "{}"),
                "importance": d.get("importance", 0.5),
                "atom_type": d.get("atom_type", ""),
                "session_id": d.get("session_id", ""),
                "status": d.get("status", ""),
            })
        return result

    def get_memory_by_id(self, memory_id: int) -> dict | None:
        """按 ID 获取单条记忆详情（memory_atoms 优先，fallback documents）。

        兼容两种 ID 来源：search_memories（FTS/LIKE）返回 documents.id，
        get_recent_memories / search_memories_by_tag 返回 memory_atoms.id。
        """
        if not memory_id:
            return None
        conn = self._connect()
        try:
            # 1. memory_atoms（最近记录 / 标签搜索的 ID 来源）
            row = conn.execute(
                "SELECT * FROM memory_atoms WHERE id = ? AND status='active'",
                (memory_id,),
            ).fetchone()
            if row:
                d = dict(row)
                import json as _json
                meta = {}
                try:
                    meta = _json.loads(d.get("metadata", "{}"))
                except Exception:
                    pass
                created_iso = ""
                ts = d.get("created_at")
                if ts and isinstance(ts, (int, float)):
                    from datetime import datetime as _dt
                    created_iso = _dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                entities = []
                try:
                    entities = _json.loads(d.get("entities", "[]"))
                except Exception:
                    pass
                return {
                    "id": d.get("id"),
                    "type": d.get("atom_type", "atom"),
                    "atom_type": d.get("atom_type", "atom"),
                    "content": d.get("content", ""),
                    "created_at": created_iso,
                    "memory_tier": d.get("tier", 2),
                    "metadata": d.get("metadata", "{}"),
                    "importance": d.get("importance", 0.5),
                    "confidence": d.get("confidence", 0.7),
                    "tags": entities if isinstance(entities, list) else [],
                    "status": d.get("status", "active"),
                    "session_id": d.get("session_id", ""),
                    "source": "atom",
                }
            # 2. documents（关键词 / FTS 搜索的 ID 来源）
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if row:
                d = dict(row)
                meta = self._parse_meta(d.get("metadata", ""))
                content = (
                    meta.get("canonical_summary", "")
                    or meta.get("persona_summary", "")
                    or d.get("text", "")
                )
                tags = meta.get("topics", [])
                if not isinstance(tags, list):
                    tags = []
                return {
                    "id": d.get("id"),
                    "doc_id": d.get("doc_id", ""),
                    "type": "document",
                    "atom_type": "document",
                    "content": content,
                    "full_text": d.get("text", ""),
                    "created_at": str(d.get("created_at", "")),
                    "memory_tier": d.get("memory_tier", 1),
                    "metadata": d.get("metadata", ""),
                    "importance": meta.get("importance", 0),
                    "confidence": meta.get("confidence", 0),
                    "tags": tags,
                    "status": "active",
                    "session_id": meta.get("session_id", ""),
                    "source": "document",
                }
        except Exception as e:
            logger.warning(f"[LMHelper] get_memory_by_id({memory_id}) error: {e}")
            return None
        finally:
            conn.close()
        return None

    def get_memories_by_date(self, date_str: str, limit: int = 100):
        """获取指定日期的记忆（从 memory_atoms 读取）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_atoms "
                "WHERE date(datetime(created_at, 'unixepoch')) = ? AND status='active' "
                "ORDER BY created_at DESC LIMIT ?",
                (date_str, limit),
            ).fetchall()
            result = self._atoms_to_result(rows)
        except Exception:
            # fallback: documents
            rows = conn.execute(
                "SELECT * FROM documents WHERE date(created_at) = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (date_str, limit),
            ).fetchall()
            result = [self._format_row(dict(r)) for r in rows]
        conn.close()
        return result

    def get_memories_by_date_range(
        self, start_date: str, end_date: str, limit: int = 200
    ):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_atoms "
                "WHERE date(datetime(created_at, 'unixepoch')) BETWEEN ? AND ? AND status='active' "
                "ORDER BY created_at DESC LIMIT ?",
                (start_date, end_date, limit),
            ).fetchall()
            result = self._atoms_to_result(rows)
        except Exception:
            rows = conn.execute(
                "SELECT * FROM documents WHERE date(created_at) BETWEEN ? AND ? "
                "ORDER BY created_at DESC LIMIT ?",
                (start_date, end_date, limit),
            ).fetchall()
            result = [self._format_row(dict(r)) for r in rows]
        conn.close()
        return result

    def get_recent_memories(self, limit: int = 100, offset: int = 0):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_atoms WHERE status='active' "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            result = self._atoms_to_result(rows)
        except Exception:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            result = [self._format_row(dict(r)) for r in rows]
        conn.close()
        return result

    def search_memories_by_tag(self, tag: str, limit: int = 50):
        """按标签搜索（通过 metadata JSON 中的 topics/标签）"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_atoms WHERE metadata LIKE ? AND status='active' "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{tag}%", limit),
            ).fetchall()
            result = self._atoms_to_result(rows)
        except Exception:
            rows = conn.execute(
                "SELECT * FROM documents WHERE metadata LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{tag}%", limit),
            ).fetchall()
            result = [self._format_row(dict(r)) for r in rows]
        conn.close()
        return result

    def _fts_column_exists(self, conn) -> bool:
        """检查 documents_fts 是否有 doc_id 列（livingmemory 可用的格式）"""
        try:
            cols = conn.execute("PRAGMA table_info(documents_fts)").fetchall()
            col_names = {r[1] for r in cols}
            return 'doc_id' in col_names
        except Exception:
            return False

    def _multi_strategy_search(self, query: str, limit: int):
        """【v6.2】多路检索 — 返回各路的原始排序列表，供 RRF 融合。

        FTS5 路径自动检测可用表：
        - livingmemory_memories_fts（LivingMemory 自己的 FTS5，优先）
        - documents_fts（可能被 AstrBot 核心管理，检测后再用）

        返回格式: [(strategy_name, [results]), ...]
        """
        conn = self._connect()
        lists = []

        # ── 路径 1: FTS5 BM25 ──
        fts_table = None
        fts_join_col = None

        # 1a. 优先检测 livingmemory_memories_fts（LivingMemory 自带的 FTS5）
        try:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='livingmemory_memories_fts'"
            ).fetchone()
            if exists:
                fts_table = "livingmemory_memories_fts"
                fts_join_col = "doc_id"
        except Exception:
            pass

        # 1b. 降级到 documents_fts（如果 AstrBot 核心没有占用）
        if not fts_table and self._fts_column_exists(conn):
            fts_table = "documents_fts"
            fts_join_col = "doc_id"

        if fts_table:
            try:
                # JOIN 条件：livingmemory_memories_fts.doc_id = documents.id（整数）
                # documents_fts 的 JOIN 不同，用 COALESCE
                if fts_table == "livingmemory_memories_fts":
                    join_clause = "f.doc_id = d.id"
                else:
                    join_clause = "f.doc_id = COALESCE(d.doc_id, d.id)"

                # 精确匹配
                rows = conn.execute(
                    f"""SELECT d.*, d.memory_tier as tier FROM documents d
                        INNER JOIN {fts_table} f ON ({join_clause})
                        WHERE {fts_table} MATCH ?
                        ORDER BY rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
                if not rows:
                    # 前缀匹配
                    tokens = query.replace('"', '').split()
                    prefix_q = f'"{query}"*' if len(tokens) == 1 else ' '.join(f'{t}*' for t in tokens)
                    rows = conn.execute(
                        f"""SELECT d.*, d.memory_tier as tier FROM documents d
                            INNER JOIN {fts_table} f ON ({join_clause})
                            WHERE {fts_table} MATCH ?
                            ORDER BY rank LIMIT ?""",
                        (prefix_q, limit),
                    ).fetchall()
                if rows:
                    lists.append(("fts", [self._format_row(dict(r)) for r in rows]))
                    logger.debug(f"[LMHelper v6.2] FTS5 ({fts_table}) 命中 {len(rows)} 条: '{query}'")
            except Exception as e:
                logger.debug(f"[LMHelper v6.2] FTS5 路失败 ({fts_table}): {e}")

        # ── 路径 2: LIKE 模糊（中文子串优势） ──
        try:
            rows = conn.execute(
                "SELECT *, memory_tier as tier FROM documents "
                "WHERE text LIKE ? OR metadata LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            if rows:
                lists.append(("like", [self._format_row(dict(r)) for r in rows]))
        except Exception:
            pass

        conn.close()
        return lists

    def search_memories(self, query: str, limit: int = 10):
        """【v6.2】RRF 多路融合检索 — 内化多路 + RRF 融合 + Tier 排序。

        升级路径：
        1. 多路并行检索（FTS5 BM25 + LIKE 模糊）
        2. RRF k=60 融合排序（借鉴 TencentDB search-utils.ts）
        3. 降级：RRF 无结果 → 单路 LIKE 兜底
        4. Tier 优先级二次排序 + 访问追踪
        """
        # ── v6.2: 多路检索 + RRF 融合 ──
        over_retrieve = limit * 3  # 过采样（TencentDB 标准 3x）
        strategy_lists = self._multi_strategy_search(query, over_retrieve)

        results = []
        if len(strategy_lists) > 1:
            # 多路 → RRF 融合
            from ..core.rrf_engine import rrf_merge
            ranked_lists = [results_list for _, results_list in strategy_lists]
            results = rrf_merge(ranked_lists, id_key="id", k=60, limit=over_retrieve)
            logger.debug(
                f"[LMHelper v6.2] RRF 融合 {[name for name, _ in strategy_lists]}: "
                f"{len(results)} 条"
            )
        elif len(strategy_lists) == 1:
            # 单路命中（另一路没结果）
            results = strategy_lists[0][1][:over_retrieve]
        else:
            # 全部失败 → LIKE 终极兜底
            conn = self._connect()
            rows = conn.execute(
                "SELECT *, memory_tier as tier FROM documents WHERE text LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{query}%", limit * 2),
            ).fetchall()
            conn.close()
            results = [self._format_row(dict(r)) for r in rows]

        if not results:
            return []

        # ── Tier 优先级二次排序：L0 > L1 > L2 > L3 ──
        tier_weight = {0: 1000, 1: 100, 2: 10, 3: 1}
        results.sort(
            key=lambda r: (
                tier_weight.get(r.get("tier", 3), 0),
                r.get("_rrf_score", 0),
            ),
            reverse=True,
        )
        results = results[:limit]

        # ── 访问追踪 ──
        if results:
            ids = [r["id"] for r in results if r.get("id")]
            if ids:
                conn = self._connect()
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE documents SET access_count = COALESCE(access_count, 0) + 1, "
                    f"last_accessed_at = datetime('now') WHERE id IN ({placeholders})",
                    ids
                )
                # v5.2: 强化对应的 memory_atoms — reinforcement_count++ + 延长TTL
                try:
                    now_ts = int(time.time())
                    conn.execute(
                        f"""UPDATE memory_atoms SET
                            reinforcement_count = COALESCE(reinforcement_count, 0) + 1,
                            last_reinforced_at = ?,
                            ttl_days = ttl_days * (1.0 + COALESCE(reinforcement_count, 0) * 0.1),
                            expires_at = expires_at + COALESCE(reinforcement_count, 0) * 86400.0,
                            status = 'active'
                            WHERE parent_memory_id IN ({placeholders}) AND status = 'active'""",
                        [now_ts] + ids
                    )
                    logger.debug(f"[LMHelper v6.2] 强化 {len(ids)} 条记忆的 atoms")
                except Exception as e:
                    logger.debug(f"[LMHelper v6.2] atom 强化跳过: {e}")
                conn.commit()
                conn.close()

        return results[:limit]

    def recompute_tiers(self) -> dict:
        """【v5.2】重算所有记忆的 tier — 强化感知 + 时间感知"""
        import json as _json
        from datetime import datetime as _dt

        conn = self._connect()
        now = _dt.now()
        rows = conn.execute(
            "SELECT d.id, d.metadata, d.created_at, d.memory_tier, "
            "COALESCE((SELECT MAX(a.reinforcement_count) FROM memory_atoms a WHERE a.parent_memory_id = d.id), 0) as max_rc "
            "FROM documents d"
        ).fetchall()

        stats = {"promoted": 0, "demoted": 0, "unchanged": 0}

        for r in rows:
            importance = 0.5
            try:
                if r["metadata"]:
                    meta = _json.loads(r["metadata"])
                    imp = meta.get("importance")
                    if imp is not None:
                        importance = float(imp)
            except Exception:
                pass

            age_days = 999
            if r["created_at"]:
                for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]:
                    try:
                        dt = _dt.strptime(str(r["created_at"]), fmt)
                        age_days = (now - dt).total_seconds() / 86400.0
                        break
                    except Exception:
                        continue

            rc = r["max_rc"] or 0  # 强化次数

            # v5.2: 强化感知 tier 计算
            # 强化次数高的记忆，降级更慢（时间窗口放宽）
            # rc=0: 标准窗口; rc>=3: 窗口翻倍; rc>=10: 永不降级到L3
            time_boost = 1.0 + min(rc * 0.3, 2.0)  # 最多3倍窗口

            if age_days < 0.25:
                new_tier = 0
            elif age_days <= 7 * time_boost and importance >= 0.5:
                new_tier = 1
            elif age_days <= 90 * time_boost and importance >= 0.5:
                new_tier = 2
            elif rc >= 10 and importance >= 0.7:
                new_tier = 2  # 高频高重要记忆永不归档
            else:
                new_tier = 3

            old_tier = r["memory_tier"] if r["memory_tier"] is not None else 1
            if new_tier < old_tier:
                stats["promoted"] += 1
            elif new_tier > old_tier:
                stats["demoted"] += 1
            else:
                stats["unchanged"] += 1

            conn.execute(
                "UPDATE documents SET memory_tier = ? WHERE id = ?",
                (new_tier, r["id"])
            )

        conn.commit()
        conn.close()
        logger.info(
            f"[LMHelper v6.0] Tier 重算完成: "
            f"↑{stats['promoted']} ↓{stats['demoted']} ={stats['unchanged']}"
        )
        return stats

    def get_tier_stats(self) -> dict:
        """【v5.1】获取分层统计"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT tier as memory_tier, COUNT(*) as c FROM memory_atoms WHERE status='active' GROUP BY tier ORDER BY tier"
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT memory_tier, COUNT(*) as c FROM documents GROUP BY memory_tier ORDER BY memory_tier"
            ).fetchall()
        conn.close()
        tier_names = {0: "L0_工作记忆", 1: "L1_活跃记忆", 2: "L2_情景记忆", 3: "L3_归档记忆"}
        return {tier_names.get(r["memory_tier"], f"未知_{r['memory_tier']}"): r["c"] for r in rows}
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (memory_id,)
        ).fetchone()
        conn.close()
        if row:
            return self._format_row(dict(row))
        return None

    def get_stats_for_date(self, date_str: str) -> dict:
        conn = self._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_atoms "
                "WHERE date(datetime(created_at, 'unixepoch')) = ? AND status='active'",
                (date_str,),
            ).fetchone()[0]
            hours = conn.execute(
                "SELECT strftime('%H', datetime(created_at, 'unixepoch')) as hour, COUNT(*) as cnt "
                "FROM memory_atoms WHERE date(datetime(created_at, 'unixepoch')) = ? AND status='active' "
                "GROUP BY hour ORDER BY hour",
                (date_str,),
            ).fetchall()
        except Exception:
            count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE date(created_at) = ?",
                (date_str,),
            ).fetchone()[0]
            hours = conn.execute(
                "SELECT strftime('%H', created_at) as hour, COUNT(*) as cnt "
                "FROM documents WHERE date(created_at) = ? "
                "GROUP BY hour ORDER BY hour",
                (date_str,),
            ).fetchall()
        hour_dist = {h["hour"]: h["cnt"] for h in hours} if hours else {}
        conn.close()
        return {"total": count, "hour_distribution": hour_dist}

    def get_all_tags(self) -> list:
        conn = self._connect()
        # 从 memory_atoms 读 metadata（包含 topics 标签）
        try:
            rows = conn.execute(
                "SELECT metadata FROM memory_atoms WHERE metadata IS NOT NULL AND status='active'"
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT metadata FROM documents WHERE metadata IS NOT NULL"
            ).fetchall()
        conn.close()
        tags = set()
        for r in rows:
            meta = self._parse_meta(r[0])
            topics = meta.get("topics", [])
            for t in topics:
                tags.add(t)
        return sorted(tags)

    def graph_enhanced_recall(self, doc_ids: list, limit: int = 3) -> list:
        """【v5.2】图增强召回 — 通过共享节点找到关联记忆
        给定 FTS 搜索命中的 doc_ids，通过 graph 找到共享节点的其他文档
        """
        if not doc_ids:
            return []
        
        conn = self._connect()
        results = []
        
        try:
            placeholders = ",".join("?" * len(doc_ids))
            
            # 1. 找这些文档的所有节点
            node_rows = conn.execute(
                f"""SELECT DISTINCT gen.node_id, gn.node_value, gn.node_type
                    FROM graph_entries ge
                    JOIN graph_entry_nodes gen ON gen.entry_id = ge.id
                    JOIN graph_nodes gn ON gn.id = gen.node_id
                    WHERE ge.source_memory_id IN ({placeholders})""",
                doc_ids
            ).fetchall()
            
            if not node_rows:
                conn.close()
                return []
            
            node_ids = [r["node_id"] for r in node_rows]
            node_placeholders = ",".join("?" * len(node_ids))
            
            # 2. 通过这些节点找到其他文档（按共享节点数排序）
            related = conn.execute(
                f"""SELECT ge.source_memory_id as id,
                           d.text, d.metadata, d.memory_tier,
                           d.created_at, d.access_count,
                           COUNT(DISTINCT gen.node_id) as shared_nodes
                    FROM graph_entry_nodes gen
                    JOIN graph_entries ge ON ge.id = gen.entry_id
                    LEFT JOIN documents d ON d.id = ge.source_memory_id
                    WHERE gen.node_id IN ({node_placeholders})
                    AND ge.source_memory_id IS NOT NULL
                    AND ge.source_memory_id NOT IN ({placeholders})
                    GROUP BY ge.source_memory_id
                    ORDER BY shared_nodes DESC, d.created_at DESC
                    LIMIT ?""",
                node_ids + doc_ids + [limit]
            ).fetchall()
            
            for r in related:
                results.append(dict(r))
            
            if results:
                logger.debug(f"[LMHelper v6.0] 图增强: {len(doc_ids)} docs → {len(results)} 关联记忆 (via {len(node_ids)} nodes)")
        except Exception as e:
            logger.debug(f"[LMHelper v6.0] 图增强失败: {e}")
        
        conn.close()
        return [self._format_row(r) for r in results]

    def track_decision(self, content: str, supersedes_id: str = None,
                       importance: float = 0.9, session_id: str = None,
                       persona_id: str = None) -> str:
        """【v5.2】追踪关键决策 — 带版本链，新决策标记旧决策为 superseded
        返回新决策的 atom_id
        """
        import json as _json
        import uuid

        conn = self._connect()
        decision_id = str(uuid.uuid4())[:8]
        now = time.time()

        # 如果有前序决策，标记为 superseded
        if supersedes_id:
            try:
                conn.execute(
                    """UPDATE memory_atoms SET status = 'superseded'
                       WHERE id = ? AND atom_type = 'decision'""",
                    (supersedes_id,)
                )
            except Exception:
                pass

        # 找一个最近的 document 作为 parent（决策不需要独立 document）
        parent = conn.execute(
            "SELECT id FROM documents ORDER BY id DESC LIMIT 1"
        ).fetchone()
        parent_id = parent["id"] if parent else None

        meta = _json.dumps({
            "decision_id": decision_id,
            "supersedes": supersedes_id,
            "status": "active"
        })

        conn.execute(
            """INSERT INTO memory_atoms
               (parent_memory_id, atom_type, content, importance, confidence,
                created_at, last_accessed_at, ttl_days, expires_at, status,
                reinforcement_count, decay_type, session_id, persona_id, metadata)
               VALUES (?, 'decision', ?, ?, 0.8, ?, ?, 999, ?, 'active', 0, 'linear', ?, ?, ?)""",
            (parent_id, content, importance, now, now, now + 999 * 86400,
             session_id, persona_id, meta)
        )
        conn.commit()
        atom_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        logger.info(f"[LMHelper v6.0] 决策追踪: #{atom_id} '{content[:50]}...' (supersedes={supersedes_id})")
        return atom_id

    def get_active_decisions(self, limit: int = 10) -> list:
        """【v5.2】获取所有活跃的决策（未被覆盖的）"""
        conn = self._connect()
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """SELECT id, content, importance, created_at, metadata
               FROM memory_atoms
               WHERE atom_type = 'decision' AND status = 'active'
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()

        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "content": r["content"],
                "importance": r["importance"],
                "created_at": r["created_at"],
                "metadata": r["metadata"]
            })
        conn.close()
        return results

    def _format_row(self, row: dict) -> dict:
        """标准化行数据"""
        meta = self._parse_meta(row.get("metadata", ""))
        created = row.get("created_at", "")
        if isinstance(created, str) and created:
            try:
                dt = datetime.fromisoformat(created)
                time_str = dt.strftime("%H:%M")
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                time_str = ""
                date_str = ""
        else:
            time_str = ""
            date_str = ""
        return {
            "id": row.get("id"),
            "doc_id": row.get("doc_id", ""),
            "content": meta.get("canonical_summary", "")
            or meta.get("persona_summary", "")
            or row.get("text", "")[:200],
            "full_text": row.get("text", ""),
            "created_at": created,
            "time": time_str,
            "date": date_str,
            "importance": meta.get("importance", 0),
            "tags": meta.get("topics", []),
            "key_facts": meta.get("key_facts", []),
            "sentiment": meta.get("sentiment", ""),
            "session_id": meta.get("session_id", ""),
            "interaction_type": meta.get("interaction_type", ""),
            "tier": row.get("memory_tier", 1),
            "access_count": row.get("access_count", 0),
        }

    # ======== graph / sentiment / archive / semantic ========

    def create_graph_node(self, node_type: str, label: str, properties: str = "{}"):
        """创建图谱节点"""
        import json
        conn = self._connect()
        try:
            props = json.loads(properties) if isinstance(properties, str) else (properties or {})
            cursor = conn.execute(
                "INSERT INTO graph_nodes (node_type, label, properties, weight, memory_count) VALUES (?, ?, ?, 0, 0)",
                (node_type, label, json.dumps(props, ensure_ascii=False))
            )
            conn.commit()
            return {"id": cursor.lastrowid, "node_type": node_type, "label": label, "properties": props}
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_graph_node_detail(self, node_id: int):
        """获取图谱节点详情（含关联边和邻居）"""
        conn = self._connect()
        try:
            node = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (node_id,)).fetchone()
            if not node:
                return None
            node = dict(node)
            # 获取关联边
            edges = conn.execute(
                "SELECT * FROM graph_edges WHERE source_node_id = ? OR target_node_id = ?",
                (node_id, node_id)
            ).fetchall()
            node["edges"] = [dict(e) for e in edges]
            # 获取邻居节点
            neighbor_ids = set()
            for e in node["edges"]:
                neighbor_ids.add(e["source_node_id"])
                neighbor_ids.add(e["target_node_id"])
            neighbor_ids.discard(node_id)
            if neighbor_ids:
                ph = ",".join("?" * len(neighbor_ids))
                neighbors = conn.execute(
                    f"SELECT id, node_type, node_value AS label FROM graph_nodes WHERE id IN ({ph})",
                    list(neighbor_ids)
                ).fetchall()
                node["neighbors"] = [dict(n) for n in neighbors]
            else:
                node["neighbors"] = []
            return node
        finally:
            conn.close()

    def get_relation_types(self):
        """获取所有关系类型（去重）"""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT relation_type FROM graph_edges WHERE relation_type IS NOT NULL").fetchall()
            return [r["relation_type"] for r in rows if r["relation_type"]]
        except Exception:
            return []
        finally:
            conn.close()

    def get_graph_nodes(self, limit=200, node_type=None):
        conn = self._connect()
        if node_type:
            rows = conn.execute("SELECT * FROM graph_nodes WHERE node_type = ? LIMIT ?", (node_type, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM graph_nodes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ═══════════════════ v5.6 Reinforcement Engine ═══════════════════

    def get_due_review_atoms(self, limit: int = 10) -> list[dict]:
        """获取到期复习的记忆原子（reinforcement_state.next_review_at 已过期）。

        Returns atoms with expired review timestamps, sorted by importance desc.
        Only active atoms with tier >= 2 (L2/L3).
        """
        now = time.time()
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT id, content, importance, reinforcement_state, reinforcement_count
            FROM memory_atoms
            WHERE status = 'active'
              AND tier >= 2
              AND reinforcement_state IS NOT NULL
              AND reinforcement_state != ''
            ORDER BY importance DESC
            LIMIT ?
            """,
            (limit * 2,),
        ).fetchall()
        conn.close()

        results = []
        for row in rows:
            state_str = row["reinforcement_state"]
            if not state_str:
                continue
            try:
                state = json.loads(state_str)
            except (json.JSONDecodeError, TypeError):
                continue
            next_review = float(state.get("next_review_at", 0))
            if next_review <= now:
                results.append(dict(row))
        return results[:limit]

    def record_reinforcement(self, atom_id: int, is_correct: bool) -> bool:
        """记录一次记忆强化复习结果。

        Args:
            atom_id: 记忆原子 ID
            is_correct: 用户是否确认记住

        Returns:
            bool: 成功返回 True
        """
        ReinforcementState = _import_lm(
            "astrbot_plugin_livingmemory.core.reinforcement.models", "ReinforcementState"
        )
        compute_memory_strength = _import_lm(
            "astrbot_plugin_livingmemory.core.reinforcement.memory_strength", "compute_memory_strength"
        )
        ReviewScheduler = _import_lm(
            "astrbot_plugin_livingmemory.core.reinforcement.scheduler", "ReviewScheduler"
        )

        now = time.time()
        conn = self._connect()

        # 获取当前状态和记忆数据
        row = conn.execute(
            "SELECT id, reinforcement_state, reinforcement_count, importance, confidence, atom_type, event_time FROM memory_atoms WHERE id = ?",
            (atom_id,),
        ).fetchone()

        if not row:
            conn.close()
            return False

        # 解析当前强化状态
        state = ReinforcementState.from_json(row["reinforcement_state"])
        if state.next_review_at <= 0:
            scheduler = ReviewScheduler()
            state = scheduler.get_initial_state()

        # 更新调度
        scheduler = ReviewScheduler()
        state = scheduler.schedule_next(state, is_correct)

        # 计算新强度
        history_len = max(1, state.consecutive_correct + state.consecutive_wrong)
        history = [True] * state.consecutive_correct + [False] * state.consecutive_wrong
        if len(history) < history_len:
            history = [True] * (history_len - len(history)) + history
        new_strength = compute_memory_strength(history)
        state.review_strength = new_strength

        # 更新数据库
        new_count = int(row["reinforcement_count"]) + 1
        importance = float(row["importance"])
        boost = 0.05 if is_correct else -0.02
        new_importance = max(0.01, min(1.0, importance + boost))

        confidence = float(row["confidence"])
        if is_correct:
            confidence = min(1.0, confidence * 0.7 + 0.3)
        else:
            confidence = max(0.1, confidence * 0.7)

        # 计算新 TTL
        AtomType, compute_ttl = _import_lm(
            "astrbot_plugin_livingmemory.core.models.memory_atom", ["AtomType", "compute_ttl"]
        )
        atom_type = AtomType(row["atom_type"]) if row["atom_type"] else AtomType.UNKNOWN
        event_time = float(row["event_time"]) if row["event_time"] else None
        new_ttl, decay = compute_ttl(atom_type, new_importance, new_count, event_time)
        new_expires = now + new_ttl * 86400.0

        conn.execute(
            """
            UPDATE memory_atoms
            SET reinforcement_count = ?, confidence = ?, importance = ?,
                ttl_days = ?, expires_at = ?, decay_type = ?,
                last_reinforced_at = ?, reinforcement_state = ?
            WHERE id = ?
            """,
            (
                new_count, confidence, new_importance,
                new_ttl, new_expires, decay.value if hasattr(decay, 'value') else str(decay),
                now, state.to_json(),
                atom_id,
            ),
        )
        conn.commit()
        conn.close()
        return True

    def init_reinforcement_state(self, atom_id: int) -> bool:
        """为一个原子初始化强化状态。

        Returns:
            bool: 成功返回 True
        """
        ReviewScheduler = _import_lm(
            "astrbot_plugin_livingmemory.core.reinforcement.scheduler", "ReviewScheduler"
        )

        scheduler = ReviewScheduler()
        state = scheduler.get_initial_state()
        state_json = state.to_json()

        conn = self._connect()
        conn.execute(
            "UPDATE memory_atoms SET reinforcement_state = ? WHERE id = ? AND (reinforcement_state IS NULL OR reinforcement_state = '')",
            (state_json, atom_id),
        )
        conn.commit()
        conn.close()
        return True

    # ── Phase 2 归档员（家庭协作 v2.1：沉睡记忆扫描 → 例会汇报 → 点头 → 归档）──

    def _get_archive_manager(self):
        """懒加载 + 缓存 ArchiveManager（双路径导入；v2 库与主库同目录推导）。"""
        if getattr(self, "_archive_mgr", None) is None:
            ArchiveManager = _import_lm(
                "astrbot_plugin_livingmemory.core.v2.archive_manager", "ArchiveManager"
            )
            v2_path = os.path.join(
                os.path.dirname(os.path.abspath(self.db_path)), "v2_memory.db"
            )
            self._archive_mgr = ArchiveManager(v2_path, self.db_path)
        return self._archive_mgr

    def archive_scan(self, days: int = 30, min_importance: float = 0.6,
                     max_candidates: int = 20, dry_run: bool = False) -> dict:
        """归档员：扫描沉睡记忆，生成候选（candidate）。"""
        try:
            return self._get_archive_manager().scan_sleeping_atoms(
                days, min_importance, max_candidates, dry_run
            )
        except Exception as e:
            logger.warning(f"[Archive] scan 失败: {e}")
            return {"status": "error", "msg": str(e), "new_candidates": 0, "candidates": []}

    def archive_list(self, status: str | None = None, limit: int = 20) -> list[dict]:
        """归档员：列出候选（可按状态过滤）。"""
        try:
            return self._get_archive_manager().list_candidates(status, limit)
        except Exception as e:
            logger.warning(f"[Archive] list 失败: {e}")
            return [{"error": str(e)}]

    def archive_propose(self, candidate_ids: list[int]) -> dict:
        """归档员：候选 → proposed（例会汇报给橘子等点头）。"""
        try:
            return self._get_archive_manager().propose(candidate_ids)
        except Exception as e:
            logger.warning(f"[Archive] propose 失败: {e}")
            return {"status": "error", "msg": str(e), "moved": 0}

    def archive_confirm(self, candidate_ids: list[int], note: str = "") -> dict:
        """归档员：橘子点头 → 执行归档（候选 archived + atoms.status='archived'）。"""
        try:
            return self._get_archive_manager().confirm(candidate_ids, note)
        except Exception as e:
            logger.warning(f"[Archive] confirm 失败: {e}")
            return {"status": "error", "msg": str(e), "archived_count": 0}

    def archive_decline(self, candidate_ids: list[int], reason: str = "") -> dict:
        """归档员：拒绝归档（候选 → declined，不触碰记忆）。"""
        try:
            return self._get_archive_manager().decline(candidate_ids, reason)
        except Exception as e:
            logger.warning(f"[Archive] decline 失败: {e}")
            return {"status": "error", "msg": str(e), "moved": 0}

    def archive_stats(self) -> dict:
        """归档员：候选状态统计。"""
        try:
            return self._get_archive_manager().stats()
        except Exception as e:
            logger.warning(f"[Archive] stats 失败: {e}")
            return {"status": "error", "msg": str(e)}

    # ── Phase 3: 家庭角色分工 ─────────────────────────────────────

    def _get_family_role_manager(self):
        """懒加载 + 缓存 FamilyRoleManager（双路径导入；v2 库与主库同目录推导）。"""
        if getattr(self, "_family_mgr", None) is None:
            FamilyRoleManager = _import_lm(
                "astrbot_plugin_livingmemory.core.v2.family_role_manager",
                "FamilyRoleManager",
            )
            v2_path = os.path.join(
                os.path.dirname(os.path.abspath(self.db_path)), "v2_memory.db"
            )
            self._family_mgr = FamilyRoleManager(v2_path, self.db_path)
        return self._family_mgr

    def family_roles_seed(self) -> dict:
        """角色分工：首次登记 22 位家人。"""
        try:
            return self._get_family_role_manager().ensure_seed()
        except Exception as e:
            logger.warning(f"[FamilyRole] seed 失败: {e}")
            return {"status": "error", "msg": str(e), "inserted": 0}

    def family_roles_list(self, active_only: bool = True) -> list[dict]:
        """角色分工：列出家人身份（含角色隐喻/职责/协作对象）。"""
        try:
            return self._get_family_role_manager().list_roles(active_only)
        except Exception as e:
            logger.warning(f"[FamilyRole] list 失败: {e}")
            return [{"error": str(e)}]

    def family_roles_tree(self) -> dict:
        """角色分工：家庭图谱（nodes + edges）。"""
        try:
            return self._get_family_role_manager().family_tree()
        except Exception as e:
            logger.warning(f"[FamilyRole] tree 失败: {e}")
            return {"nodes": [], "edges": [], "error": str(e)}

    def family_roles_stats(self) -> dict:
        """角色分工：台账统计。"""
        try:
            return self._get_family_role_manager().stats()
        except Exception as e:
            logger.warning(f"[FamilyRole] stats 失败: {e}")
            return {"status": "error", "msg": str(e)}

    def family_roles_register(self, member_name: str, tool_name: str, role: str,
                              duty: str = "", importance: float = 0.5,
                              cooperates_with: list[str] | None = None) -> dict:
        """角色分工：登记/更新一位家人。"""
        try:
            return self._get_family_role_manager().register_role(
                member_name, tool_name, role, duty, importance, cooperates_with
            )
        except Exception as e:
            logger.warning(f"[FamilyRole] register 失败: {e}")
            return {"status": "error", "msg": str(e)}

    # ── Phase 4: 家庭例会 ─────────────────────────────────────

    def _get_family_meeting_manager(self):
        """懒加载 + 缓存 FamilyMeetingManager（双路径导入；v2 库与主库同目录推导）。"""
        if getattr(self, "_meeting_mgr", None) is None:
            FamilyMeetingManager = _import_lm(
                "astrbot_plugin_livingmemory.core.v2.family_meeting_manager",
                "FamilyMeetingManager",
            )
            v2_path = os.path.join(
                os.path.dirname(os.path.abspath(self.db_path)), "v2_memory.db"
            )
            self._meeting_mgr = FamilyMeetingManager(v2_path, self.db_path)
        return self._meeting_mgr

    def family_meeting_generate(self, date_str: str | None = None) -> dict:
        """家庭例会：生成/更新指定日期日报（默认今天，同日覆盖）。"""
        try:
            return self._get_family_meeting_manager().generate_report(date_str)
        except Exception as e:
            logger.warning(f"[FamilyMeeting] generate 失败: {e}")
            return {"status": "error", "msg": str(e)}

    def family_meeting_get(self, date_str: str | None = None) -> dict | None:
        """家庭例会：查看某日日报（默认今天）。"""
        try:
            return self._get_family_meeting_manager().get_report(date_str)
        except Exception as e:
            logger.warning(f"[FamilyMeeting] get 失败: {e}")
            return {"status": "error", "msg": str(e)}

    def family_meeting_list(self, limit: int = 7) -> list[dict]:
        """家庭例会：列出最近日报。"""
        try:
            return self._get_family_meeting_manager().list_reports(limit)
        except Exception as e:
            logger.warning(f"[FamilyMeeting] list 失败: {e}")
            return [{"error": str(e)}]

    def family_meeting_stats(self) -> dict:
        """家庭例会：台账统计。"""
        try:
            return self._get_family_meeting_manager().stats()
        except Exception as e:
            logger.warning(f"[FamilyMeeting] stats 失败: {e}")
            return {"status": "error", "msg": str(e)}

    # ── v9: Three-Tier Memory Pyramid Queries ─────────────────────────

    def get_memory_pyramid(self, limit: int = 50) -> dict:
        """返回三层记忆金字塔数据

        Returns:
            dict: {"L1": [...], "L2": [...], "L3": [...]}
        """
        result = {"L1": [], "L2": [], "L3": []}
        try:
            conn = self._connect()

            # L3: tier=3, 跨会话合成记忆
            rows = conn.execute(
                """SELECT id, content, importance, source_ids, metadata,
                   created_at, session_id, atom_type
                FROM memory_atoms
                WHERE tier = 3 AND status = 'active'
                ORDER BY importance DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["source_ids"] = self._parse_json(d.get("source_ids", "[]"))
                d["metadata"] = self._parse_meta(d.get("metadata", "{}"))
                d["category"] = d["metadata"].get("category", "synthesis")
                result["L3"].append(d)

            # L2: tier=2, 会话摘要记忆 (展示所有 tier=2 活跃记忆)
            rows = conn.execute(
                """SELECT id, content, importance, source_ids, metadata,
                   created_at, session_id, atom_type
                FROM memory_atoms
                WHERE tier = 2 AND status = 'active'
                ORDER BY importance DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
            for r in rows:
                d = dict(r)
                d["source_ids"] = self._parse_json(d.get("source_ids", "[]"))
                d["metadata"] = self._parse_meta(d.get("metadata", "{}"))
                d["topics"] = d["metadata"].get("topics", [])
                d["emotion"] = d["metadata"].get("emotion", "neutral")
                result["L2"].append(d)

            # L1: 最近的消息事件 (从 conversations.db)
            try:
                conv_db = os.path.join(os.path.dirname(self.db_path), "conversations.db")
                if os.path.exists(conv_db):
                    conv_conn = sqlite3.connect(conv_db)
                    conv_conn.row_factory = sqlite3.Row
                    rows = conv_conn.execute(
                        "SELECT id, role, content, session_id, timestamp FROM messages ORDER BY id DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                    for r in rows:
                        result["L1"].append(dict(r))
                    conv_conn.close()
            except Exception as e:
                logger.debug(f"[LMReader] L1 messages 读取失败 (conversations.db): {e}")

            conn.close()
        except Exception as e:
            logger.warning(f"[LMReader] get_memory_pyramid error: {e}")

        return result

    def get_memory_trace(self, memory_id: int) -> dict | None:
        """溯源单条记忆的完整引用链 (L3→L2→L1 或 L2→L1)

        Returns:
            dict: {"memory": ..., "chain": [{"tier": 3, ...}, {"tier": 2, ...}, {"tier": 1, ...}]}
        """
        try:
            conn = self._connect()

            # 获取目标记忆
            row = conn.execute(
                "SELECT * FROM memory_atoms WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                conn.close()
                return None

            memory = dict(row)
            memory["source_ids"] = self._parse_json(memory.get("source_ids", "[]"))
            memory["metadata"] = self._parse_meta(memory.get("metadata", "{}"))
            tier = int(memory.get("tier", 2))

            chain = [{"tier": tier, "id": memory_id, "content": memory.get("content", ""),
                      "source_ids": memory["source_ids"]}]

            # 沿 source_ids 追溯
            visited = {memory_id}
            current_ids = list(memory["source_ids"])

            while current_ids:
                next_level_ids = []
                placeholders = ",".join("?" * len(current_ids))
                rows = conn.execute(
                    f"SELECT id, tier, content, source_ids, metadata, session_id FROM memory_atoms WHERE id IN ({placeholders})",
                    current_ids,
                ).fetchall()

                for r in rows:
                    rid = int(r["id"])
                    if rid in visited:
                        continue
                    visited.add(rid)

                    src_ids = self._parse_json(r["source_ids"] or "[]")
                    chain.append({
                        "tier": int(r["tier"]),
                        "id": rid,
                        "content": r["content"] or "",
                        "source_ids": src_ids,
                        "session_id": r["session_id"],
                    })
                    next_level_ids.extend(src_ids)

                # 如果下一级是 L1（消息），从 conversations.db 查
                if not rows and current_ids:
                    try:
                        conv_db = os.path.join(os.path.dirname(self.db_path), "conversations.db")
                        if os.path.exists(conv_db):
                            conv_conn = sqlite3.connect(conv_db)
                            conv_conn.row_factory = sqlite3.Row
                            msg_placeholders = ",".join("?" * len(current_ids))
                            msg_rows = conv_conn.execute(
                                f"SELECT id, role, content, session_id, timestamp FROM messages WHERE id IN ({msg_placeholders})",
                                current_ids,
                            ).fetchall()
                            for mr in msg_rows:
                                mid = int(mr["id"])
                                if mid in visited:
                                    continue
                                visited.add(mid)
                                chain.append({
                                    "tier": 1,
                                    "id": mid,
                                    "content": mr["content"] or "",
                                    "role": mr["role"],
                                    "session_id": mr["session_id"],
                                    "timestamp": mr["timestamp"],
                                })
                            conv_conn.close()
                    except Exception as e:
                        logger.debug(f"[LMReader] L1 trace 读取失败: {e}")

                current_ids = next_level_ids

            conn.close()
            return {"memory": memory, "chain": chain}
        except Exception as e:
            logger.warning(f"[LMReader] get_memory_trace error: {e}")
            return None

    @staticmethod
    def _parse_json(raw: str) -> list | dict:
        """安全解析 JSON 字符串"""
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def get_graph_edges(self, node_id=None, limit=500):
        conn = self._connect()
        if node_id:
            rows = conn.execute("SELECT * FROM graph_edges WHERE source_node_id = ? OR target_node_id = ? LIMIT ?", (node_id, node_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM graph_edges ORDER BY weight DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_graph_data(self, limit=100):
        """获取图谱数据，转换为 Graph2D 前端兼容格式

        对齐 livingmemory 原版 graph_store.get_graph_snapshot 的子图逻辑：
        从近期 graph_entries 出发，联表 graph_entry_nodes / graph_nodes 取出
        真正参与近期记忆的节点，再取这些节点之间、属于近期记忆的边，并计算
        真实的 degree / memory_count / entry_count / weight。避免直接
        ORDER BY id DESC 取到大量 weight=0 的孤立节点导致前端渲染空白。
        """
        limit = max(1, min(int(limit), 200))
        # 节点数上限沿用前端 limit；记忆/边/入口按比例放大
        limit_nodes = limit
        limit_memories = max(1, min(limit_nodes // 4, 24))
        limit_entries = max(12, min(limit_nodes * 2, 80))
        limit_edges = max(12, min(limit_nodes * 3, 120))

        conn = self._connect()
        try:
            # 1) 近期有图谱入口的记忆
            mem_rows = conn.execute(
                "SELECT source_memory_id, MAX(id) AS latest_entry_id "
                "FROM graph_entries GROUP BY source_memory_id "
                "ORDER BY latest_entry_id DESC LIMIT ?",
                (limit_memories,),
            ).fetchall()
            memory_ids = [int(r["source_memory_id"]) for r in mem_rows]
            if not memory_ids:
                return {"nodes": [], "edges": []}
            mem_ph = ",".join("?" * len(memory_ids))

            # 2) 这些记忆的近期入口
            entry_rows = conn.execute(
                f"SELECT id, source_memory_id FROM graph_entries "
                f"WHERE source_memory_id IN ({mem_ph}) "
                f"ORDER BY id DESC LIMIT ?",
                (*memory_ids, limit_entries),
            ).fetchall()
            entry_ids = [int(r["id"]) for r in entry_rows]
            if not entry_ids:
                return {"nodes": [], "edges": []}
            entry_ph = ",".join("?" * len(entry_ids))

            # 3) 入口关联的节点（只有出现在入口里的节点才是有意义的）
            node_rows = conn.execute(
                f"SELECT DISTINCT gn.id, gn.node_type, gn.node_value, "
                f"gn.canonical_value, gn.metadata "
                f"FROM graph_entry_nodes gen "
                f"JOIN graph_nodes gn ON gn.id = gen.node_id "
                f"WHERE gen.entry_id IN ({entry_ph}) "
                f"ORDER BY gn.id ASC",
                tuple(entry_ids),
            ).fetchall()
            if not node_rows:
                return {"nodes": [], "edges": []}
            node_ids = sorted({int(r["id"]) for r in node_rows})
            node_ph = ",".join("?" * len(node_ids))

            # 4) 这些节点之间、属于近期记忆的边
            edge_rows = conn.execute(
                f"SELECT id, source_node_id, target_node_id, relation_type, "
                f"source_memory_id, weight, confidence "
                f"FROM graph_edges "
                f"WHERE source_memory_id IN ({mem_ph}) "
                f"AND source_node_id IN ({node_ph}) "
                f"AND target_node_id IN ({node_ph}) "
                f"ORDER BY id DESC LIMIT ?",
                (*memory_ids, *node_ids, *node_ids, limit_edges),
            ).fetchall()

            # 5) 计算每个节点的 degree / memory_count / entry_count / weight
            degree = {}
            mem_sets = {nid: set() for nid in node_ids}
            entry_count = {nid: 0 for nid in node_ids}
            # 入口→节点映射（用于 entry_count / memory_count）
            entry_node_rows = conn.execute(
                f"SELECT entry_id, node_id FROM graph_entry_nodes "
                f"WHERE entry_id IN ({entry_ph})",
                tuple(entry_ids),
            ).fetchall()
            entry_mem = {int(r["id"]): int(r["source_memory_id"]) for r in entry_rows}
            for r in entry_node_rows:
                nid = int(r["node_id"])
                eid = int(r["entry_id"])
                if nid in entry_count:
                    entry_count[nid] += 1
                    mid = entry_mem.get(eid)
                    if mid:
                        mem_sets[nid].add(mid)
            for e in edge_rows:
                s = int(e["source_node_id"])
                t = int(e["target_node_id"])
                degree[s] = degree.get(s, 0) + 1
                degree[t] = degree.get(t, 0) + 1

            nodes = []
            for r in node_rows:
                nid = int(r["id"])
                m_count = len(mem_sets.get(nid, set()))
                e_count = entry_count.get(nid, 0)
                deg = degree.get(nid, 0)
                weight = round(e_count + m_count * 0.75 + deg * 0.35, 4)
                nodes.append({
                    "id": nid,
                    "type": r["node_type"] or "other",
                    "label": r["node_value"] or r["canonical_value"] or "Node",
                    "canonical_value": r["canonical_value"] or "",
                    "weight": weight,
                    "memory_count": m_count,
                    "degree": deg,
                    "entry_count": e_count,
                })

            # 6) 按 weight 降序截断节点数，丢弃被截断节点后孤立的边
            if len(nodes) > limit_nodes:
                nodes.sort(key=lambda x: (-x["weight"], -x["entry_count"], -x["degree"], x["label"]))
                nodes = nodes[:limit_nodes]
            allowed = {n["id"] for n in nodes}
            edges = []
            for e in edge_rows:
                s = int(e["source_node_id"])
                t = int(e["target_node_id"])
                if s in allowed and t in allowed:
                    edges.append({
                        "id": int(e["id"]),
                        "source": s,
                        "target": t,
                        "relation_type": e["relation_type"] or "related",
                        "memory_id": int(e["source_memory_id"] or 0),
                        "weight": float(e["weight"] or 1),
                        "confidence": float(e["confidence"] or 0.8),
                    })

            return {"nodes": nodes, "edges": edges}
        finally:
            conn.close()

    def get_sentiment_distribution(self, date_from=None, date_to=None):
        conn = self._connect()
        params = []
        where = ""
        if date_from:
            where += " AND date(created_at) >= ?"; params.append(date_from)
        if date_to:
            where += " AND date(created_at) <= ?"; params.append(date_to)
        rows = conn.execute(f"SELECT metadata FROM documents WHERE metadata IS NOT NULL{where}", params).fetchall()
        conn.close()
        pos = neg = neu = 0
        for r in rows:
            meta = self._parse_meta(r[0])
            s = meta.get("sentiment", "")
            if s == "positive": pos += 1
            elif s == "negative": neg += 1
            else: neu += 1
        return {"positive": pos, "negative": neg, "neutral": neu, "total": pos + neg + neu}

    def get_sentiment_trend(self, days=30):
        today = datetime.now()
        trend = []
        conn = self._connect()
        # 预查 documents 表的 sentiment 数据（按日期索引）
        doc_sentiment = {}  # {date_str: {positive, negative, neutral}}
        try:
            rows = conn.execute(
                "SELECT metadata, date(created_at) as ds FROM documents WHERE metadata IS NOT NULL AND metadata LIKE '%sentiment%'"
            ).fetchall()
            for r in rows:
                meta = self._parse_meta(r[0])
                s = meta.get("sentiment", "")
                ds = r[1] or ""
                if ds not in doc_sentiment:
                    doc_sentiment[ds] = {"positive": 0, "negative": 0, "neutral": 0}
                if s == "positive": doc_sentiment[ds]["positive"] += 1
                elif s == "negative": doc_sentiment[ds]["negative"] += 1
                else: doc_sentiment[ds]["neutral"] += 1
        except Exception:
            pass
        for i in range(days):
            d = today - timedelta(days=i)
            ds = d.strftime("%Y-%m-%d")
            pos = neg = neu = 0
            # 从 documents 索引中取
            if ds in doc_sentiment:
                pos = doc_sentiment[ds]["positive"]
                neg = doc_sentiment[ds]["negative"]
                neu = doc_sentiment[ds]["neutral"]
            # 也查 memory_atoms（可能有 sentiment 元数据）
            try:
                rows = conn.execute(
                    "SELECT metadata FROM memory_atoms WHERE date(datetime(created_at, 'unixepoch')) = ? AND status='active'",
                    (ds,),
                ).fetchall()
                for r in rows:
                    meta = self._parse_meta(r[0])
                    s = meta.get("sentiment", "")
                    if s == "positive": pos += 1
                    elif s == "negative": neg += 1
                    else: neu += 1
            except Exception:
                pass
            trend.append({"date": ds, "positive": pos, "negative": neg, "neutral": neu})
        conn.close()
        trend.reverse()
        return trend

    def _emotion_lexicon(self) -> tuple[dict, dict, set]:
        """懒加载情感词典，返回 (lexicon, polarity, negation_set)。失败时回退到空词典。"""
        try:
            from ..core.emotion_engine import EMOTION_LEXICON, EMOTION_POLARITY, NEGATION_WORDS
            return EMOTION_LEXICON, EMOTION_POLARITY, set(NEGATION_WORDS)
        except Exception as e:
            logger.debug(f"[LMHelper] 加载情感词典失败: {e}")
            return {}, {}, set()

    def _iter_memory_texts(self, conn, days: int = 30) -> list[dict]:
        """收集近 days 天内 documents + memory_atoms 的 (text, metadata, created_at)。
        统一返回 created_at 为 ISO 字符串。"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        out = []
        try:
            rows = conn.execute(
                "SELECT text, metadata, created_at FROM documents WHERE date(created_at) >= ?",
                (since,),
            ).fetchall()
            for r in rows:
                out.append({"text": r[0] or "", "metadata": self._parse_meta(r[1]),
                            "created_at": str(r[2] or "")})
        except Exception:
            pass
        try:
            rows = conn.execute(
                "SELECT content, metadata, created_at FROM memory_atoms "
                "WHERE status='active' AND created_at >= ?",
                (time.time() - days * 86400,),
            ).fetchall()
            for r in rows:
                ts = r[2] or 0
                try:
                    iso = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    iso = ""
                out.append({"text": r[0] or "", "metadata": self._parse_meta(r[1]),
                            "created_at": iso})
        except Exception:
            pass
        return out

    def get_emotion_word_stats(self, days: int = 30, limit: int = 25) -> dict:
        """统计近 days 天内高频情感词（词云数据）。
        返回 {words: [{word, count, polarity, emotion}], total_texts}"""
        lexicon, polarity, negations = self._emotion_lexicon()
        conn = self._connect()
        try:
            texts = self._iter_memory_texts(conn, days=days)
        finally:
            conn.close()
        counter = Counter()
        polarity_map = {}   # word -> polarity
        emotion_map = {}    # word -> emotion
        for item in texts:
            t = item["text"]
            if not t:
                continue
            for emotion, words in lexicon.items():
                p = polarity.get(emotion, "neutral")
                if p == "neutral":
                    continue  # 词云只展示正/负面情感词，过滤中性词
                for w in words:
                    if len(w) <= 1 or w in negations:
                        continue
                    if w in t:
                        n = t.count(w)
                        if n:
                            counter[w] += n
                            polarity_map.setdefault(w, p)
                            emotion_map.setdefault(w, emotion)
        words = [
            {"word": w, "count": c, "polarity": polarity_map.get(w, "neutral"),
             "emotion": emotion_map.get(w, "neutral")}
            for w, c in counter.most_common(limit)
        ]
        return {"words": words, "total_texts": len(texts)}

    def get_strong_sentiment_events(self, days: int = 14, limit: int = 20) -> dict:
        """挑出近 days 天内情感浓度高的记忆（时间线数据）。
        强度 = 命中情感词数（正负分别加权），返回按强度降序。"""
        lexicon, polarity, negations = self._emotion_lexicon()
        conn = self._connect()
        try:
            texts = self._iter_memory_texts(conn, days=days)
        finally:
            conn.close()
        events = []
        seen = set()
        for item in texts:
            t = item["text"]
            if not t:
                continue
            # 内容去重（documents 与 atoms 可能重复）
            key = t[:60]
            if key in seen:
                continue
            seen.add(key)
            pos_cnt = neg_cnt = 0
            matched = []
            for emotion, words in lexicon.items():
                for w in words:
                    if len(w) <= 1 or w in negations:
                        continue
                    if w in t:
                        n = t.count(w)
                        p = polarity.get(emotion, "neutral")
                        if p == "positive":
                            pos_cnt += n
                        elif p == "negative":
                            neg_cnt += n
                        matched.append({"word": w, "count": n, "polarity": p, "emotion": emotion})
            score = pos_cnt - neg_cnt
            if abs(score) < 2:
                continue  # 只保留情感浓度高的
            matched.sort(key=lambda x: x["count"], reverse=True)
            events.append({
                "time": item["created_at"],
                "content": t,  # 完整原文（弹窗查看用）
                "preview": (t[:120] + "…") if len(t) > 120 else t,  # 列表预览截断
                "sentiment": "positive" if score > 0 else "negative",
                "score": abs(score),
                "matched": matched[:8],
            })
        events.sort(key=lambda x: x["score"], reverse=True)
        return {"events": events[:limit], "total": len(events)}

    def get_archive_candidates(self, before_date=None, min_importance=0.0):
        conn = self._connect()
        try:
            if before_date:
                rows = conn.execute(
                    "SELECT * FROM memory_atoms WHERE date(datetime(created_at, 'unixepoch')) < ? AND status='active' ORDER BY created_at ASC LIMIT 200",
                    (before_date,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_atoms WHERE status='active' ORDER BY created_at ASC LIMIT 200"
                ).fetchall()
            result = self._atoms_to_result(rows)
        except Exception:
            if before_date:
                rows = conn.execute("SELECT * FROM documents WHERE date(created_at) < ? ORDER BY created_at ASC LIMIT 200", (before_date,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM documents ORDER BY created_at ASC LIMIT 200").fetchall()
            result = [self._format_row(dict(r)) for r in rows]
        conn.close()
        if min_importance > 0:
            result = [m for m in result if m.get("importance", 0) <= min_importance]
        return result

    def get_memory_count_by_date_range(self, start_date, end_date):
        conn = self._connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_atoms WHERE date(datetime(created_at, 'unixepoch')) BETWEEN ? AND ? AND status='active'",
                (start_date, end_date),
            ).fetchone()[0]
        except Exception:
            count = conn.execute("SELECT COUNT(*) FROM documents WHERE date(created_at) BETWEEN ? AND ?", (start_date, end_date)).fetchone()[0]
        conn.close()
        return count

    def semantic_search(self, query, limit=20):
        conn = self._connect()
        terms = [t.strip() for t in query.split() if t.strip()]
        if not terms:
            conn.close()
            return []
        conditions = []
        params = []
        for t in terms:
            conditions.append("(text LIKE ? OR metadata LIKE ?)")
            params.extend([f"%{t}%", f"%{t}%"])
        where = " OR ".join(conditions)
        rows = conn.execute(f"SELECT * FROM documents WHERE {where} ORDER BY created_at DESC LIMIT ?", params + [limit]).fetchall()
        conn.close()
        results = [self._format_row(dict(r)) for r in rows]
        def score_fn(mem):
            s = 0
            content = mem.get("content", "")
            full_text = mem.get("full_text", "")
            tags_str = " ".join(mem.get("tags", []))
            for t in terms:
                if t in content: s += 3
                if t in full_text: s += 2
                if t in tags_str: s += 4
            s += mem.get("importance", 0) * 2
            return -s
        results.sort(key=score_fn)
        return results

    # ======== P1-1: 智能归并 ========

    def _tokenize(self, text: str) -> set:
        """简易中文分词：按字符+空格切分，去停用词"""
        import re
        if not text:
            return set()
        # 提取中文字符序列 + 英文单词
        tokens = set()
        # 中文：按2-gram切分
        chinese = re.findall(r'[\u4e00-\u9fff]+', text)
        for seg in chinese:
            for i in range(len(seg)):
                tokens.add(seg[i])  # 单字
                if i + 1 < len(seg):
                    tokens.add(seg[i:i+2])  # 二元组
        # 英文：按单词
        english = re.findall(r'[a-zA-Z]+', text.lower())
        tokens.update(english)
        # 数字
        nums = re.findall(r'\d+', text)
        tokens.update(nums)
        return tokens

    def _jaccard_similarity(self, text_a: str, text_b: str) -> float:
        """Jaccard 相似度（基于 token 集合）"""
        tokens_a = self._tokenize(text_a)
        tokens_b = self._tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union) if union else 0.0

    def find_similar_pairs(self, threshold: float = 0.45, limit: int = 50) -> list:
        """查找相似记忆对，返回 [{id_a, id_b, content_a, content_b, similarity, tags_a, tags_b, time_a, time_b}, ...]"""
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, doc_id, text, metadata, created_at FROM documents "
            "WHERE text IS NOT NULL AND text != '' ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        conn.close()

        memories = []
        for r in rows:
            meta = self._parse_meta(r[3]) if r[3] else {}
            memories.append({
                "id": r[0], "doc_id": r[1], "text": r[2] or "",
                "content": meta.get("content", r[2] or ""),
                "importance": meta.get("importance", 0),
                "tags": meta.get("tags", []),
                "time": r[4] or "",
            })

        pairs = []
        n = len(memories)
        for i in range(min(n, 200)):  # 最多比较前200条
            for j in range(i + 1, min(n, 200)):
                sim = self._jaccard_similarity(memories[i]["content"], memories[j]["content"])
                if sim >= threshold:
                    pairs.append({
                        "id_a": memories[i]["id"],
                        "id_b": memories[j]["id"],
                        "content_a": memories[i]["content"][:100],
                        "content_b": memories[j]["content"][:100],
                        "importance_a": memories[i]["importance"],
                        "importance_b": memories[j]["importance"],
                        "tags_a": memories[i]["tags"],
                        "tags_b": memories[j]["tags"],
                        "time_a": memories[i]["time"],
                        "time_b": memories[j]["time"],
                        "similarity": round(sim, 3),
                    })

        pairs.sort(key=lambda x: -x["similarity"])
        return pairs[:limit]

    def merge_memories(self, primary_id: int, secondary_ids: list, merged_content: str = None) -> dict:
        """合并多条记忆到主记忆，删除次要记忆。
        返回 {success, merged_count, primary_id, merged_content}
        """
        conn = self._connect()
        try:
            # 获取主记忆
            primary = conn.execute("SELECT text, metadata FROM documents WHERE id = ?", (primary_id,)).fetchone()
            if not primary:
                return {"success": False, "msg": "主记忆不存在"}

            p_meta = self._parse_meta(primary[1]) if primary[1] else {}
            p_text = primary[0] or ""
            p_tags = set(p_meta.get("tags", []))

            # 收集次要记忆的内容和标签
            secondary_texts = []
            for sid in secondary_ids:
                row = conn.execute("SELECT text, metadata FROM documents WHERE id = ?", (sid,)).fetchone()
                if row:
                    secondary_texts.append(row[0] or "")
                    s_meta = self._parse_meta(row[1]) if row[1] else {}
                    p_tags.update(s_meta.get("tags", []))

            # 合并内容
            if merged_content:
                final_content = merged_content
            else:
                all_texts = [p_text] + secondary_texts
                final_content = " | ".join(t[:200] for t in all_texts if t.strip())

            # 合并重要度（取最高）
            for sid in secondary_ids:
                row = conn.execute("SELECT metadata FROM documents WHERE id = ?", (sid,)).fetchone()
                if row and row[0]:
                    s_meta = self._parse_meta(row[0])
                    s_imp = s_meta.get("importance", 0)
                    if s_imp > p_meta.get("importance", 0):
                        p_meta["importance"] = s_imp

            p_meta["tags"] = list(p_tags)
            p_meta["merged_from"] = secondary_ids
            p_meta["merged_at"] = datetime.now().isoformat()
            p_meta["content"] = final_content[:500]

            # 更新主记忆
            conn.execute(
                "UPDATE documents SET text = ?, metadata = ? WHERE id = ?",
                (final_content, json.dumps(p_meta, ensure_ascii=False), primary_id)
            )

            # 删除次要记忆
            deleted = 0
            for sid in secondary_ids:
                try:
                    conn.execute("DELETE FROM documents WHERE id = ?", (sid,))
                    deleted += 1
                except Exception:
                    pass

            conn.commit()
            return {
                "success": True,
                "primary_id": primary_id,
                "merged_count": deleted,
                "merged_content": final_content[:200],
                "tags": list(p_tags),
            }
        except Exception as e:
            conn.rollback()
            return {"success": False, "msg": str(e)}
        finally:
            conn.close()

    # ─────────────── P1-2: 报告生成 ───────────────

    def get_daily_report(self, date_str: str = None) -> dict:
        """生成某日的综合报告（不含 LLM 摘要，纯数据驱动）"""
        from datetime import datetime as dt, timedelta
        if not date_str:
            date_str = dt.now().strftime("%Y-%m-%d")

        conn = self._connect()
        today = dt.strptime(date_str, "%Y-%m-%d")
        yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
        last_week = (today - timedelta(days=7)).strftime("%Y-%m-%d")

        # 今日统计
        count_today = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE date(created_at)=?", (date_str,)
        ).fetchone()[0]

        # 昨日统计
        count_yesterday = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE date(created_at)=?", (yesterday,)
        ).fetchone()[0]

        # 本周累计
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        count_week = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE date(created_at)>=?", (week_start,)
        ).fetchone()[0]

        # 今日活跃时段
        hours = conn.execute(
            "SELECT strftime('%H',created_at) as h, COUNT(*) as c "
            "FROM documents WHERE date(created_at)=? GROUP BY h ORDER BY c DESC",
            (date_str,),
        ).fetchall()
        peak_hour = hours[0][0] if hours else None

        # 今日情感分布
        rows = conn.execute(
            "SELECT metadata FROM documents WHERE date(created_at)=? AND metadata IS NOT NULL",
            (date_str,),
        ).fetchall()
        pos = neg = neu = 0
        for r in rows:
            meta = self._parse_meta(r[0])
            s = meta.get("sentiment", "")
            if s == "positive": pos += 1
            elif s == "negative": neg += 1
            else: neu += 1

        # 今日标签 TOP 5
        tag_count = {}
        for r in rows:
            meta = self._parse_meta(r[0])
            for t in meta.get("topics", []):
                tag_count[t] = tag_count.get(t, 0) + 1
        top_tags = sorted(tag_count.items(), key=lambda x: -x[1])[:5]

        # 今日最近记忆（最多5条）
        recent = conn.execute(
            "SELECT text,metadata FROM documents WHERE date(created_at)=? "
            "ORDER BY created_at DESC LIMIT 5", (date_str,),
        ).fetchall()

        conn.close()

        # 情绪总结
        sentiment_label = "平静" if neu >= pos and neu >= neg else ("积极" if pos > neg else "低落")
        if count_today == 0:
            sentiment_label = "休息日"

        return {
            "date": date_str,
            "today_count": count_today,
            "yesterday_count": count_yesterday,
            "change": count_today - count_yesterday,
            "week_total": count_week,
            "peak_hour": f"{peak_hour}:00" if peak_hour else "无",
            "sentiment": {"positive": pos, "negative": neg, "neutral": neu, "label": sentiment_label},
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "recent_memories": [{"content": (r[0] or "")[:80], "metadata": self._parse_meta(r[1])} for r in recent],
        }

    def get_weekly_report(self) -> dict:
        """生成本周综合报告"""
        from datetime import datetime as dt, timedelta
        today = dt.now()
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")

        conn = self._connect()
        daily = []
        total = 0
        for i in range(7):
            d = dt.strptime(week_start, "%Y-%m-%d") + timedelta(days=i)
            ds = d.strftime("%Y-%m-%d")
            c = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE date(created_at)=?", (ds,)
            ).fetchone()[0]
            total += c
            # 情感
            rows = conn.execute(
                "SELECT metadata FROM documents WHERE date(created_at)=? AND metadata IS NOT NULL", (ds,)
            ).fetchall()
            pos = neg = neu = 0
            for r in rows:
                m = self._parse_meta(r[0])
                s = m.get("sentiment", "")
                if s == "positive": pos += 1
                elif s == "negative": neg += 1
                else: neu += 1
            daily.append({"date": ds, "count": c, "positive": pos, "negative": neg, "neutral": neu})

        # 本周标签 TOP 10
        rows = conn.execute(
            "SELECT metadata FROM documents WHERE date(created_at)>=? AND metadata IS NOT NULL", (week_start,)
        ).fetchall()
        tag_count = {}
        for r in rows:
            meta = self._parse_meta(r[0])
            for t in meta.get("topics", []):
                tag_count[t] = tag_count.get(t, 0) + 1
        top_tags = sorted(tag_count.items(), key=lambda x: -x[1])[:10]

        # 本周情感总计
        total_pos = sum(d["positive"] for d in daily)
        total_neg = sum(d["negative"] for d in daily)
        total_neu = sum(d["neutral"] for d in daily)
        sentiment_label = "平静" if total_neu >= total_pos and total_neu >= total_neg else ("积极" if total_pos > total_neg else "低落")
        if total == 0:
            sentiment_label = "休息周"

        conn.close()

        return {
            "week_start": week_start,
            "total": total,
            "daily": daily,
            "sentiment_summary": {"positive": total_pos, "negative": total_neg, "neutral": total_neu, "label": sentiment_label},
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
        }

    def get_memory_atoms(self, parent_id=None, limit=100):
        conn = self._connect()
        if parent_id:
            rows = conn.execute("SELECT * FROM memory_atoms WHERE parent_memory_id = ? ORDER BY created_at DESC LIMIT ?", (parent_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM memory_atoms ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
