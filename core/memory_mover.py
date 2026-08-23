# -*- coding: utf-8 -*-
"""P2-⑫ 记忆搬家工具（MemoryMoverService）。

依据 memory_upgrade_roadmap_v2.md 第12条（Claude memory import 思路：
导出/导入格式，为未来迁移备份）。方案 B 全家桶（橘子 2026-08-23 拍板）。

两层行李：
- 灵魂层（logical）：JSONL 逐表导出，人能读、能 diff、跨家可携
- 身体层（physical）：SQLite backup API 一致性快照 + FAISS index 等附属文件

安全红线：源库只读连接、逻辑导出绝不混入 .db 本体、
导入前强制 manifest 校验、dry_run 默认开、导出产物不进 git。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Dict, List, Tuple

FORMAT = "chunxue-memory-portable"
SCOPE = "full-family"
VERSION = "1.0"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_jsonl(path: str) -> int:
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


class MemoryMoverService:
    """记忆搬家：逻辑导出/物理快照/校验/documents 幂等导入。"""

    def __init__(
        self,
        databases: Dict[str, Tuple[str, List[str]]],
        attachment_files: List[str] | None = None,
    ):
        # databases: {"livingmemory": (db_path, [table, ...]), ...}
        self.databases = {k: (p, list(t)) for k, (p, t) in databases.items()}
        self.attachment_files = list(attachment_files or [])

    # ─────────────────────── 逻辑导出（灵魂层） ───────────────────────

    def export_logical(self, target_dir: str) -> dict:
        os.makedirs(target_dir, exist_ok=True)
        tables_meta: Dict[str, dict] = {}
        report_tables: Dict[str, int] = {}
        for db_name, (db_path, tables) in self.databases.items():
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                for table in tables:
                    rel = os.path.join("logical", db_name, f"{table}.jsonl")
                    abs_path = os.path.join(target_dir, rel)
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                    n = 0
                    with open(abs_path, "w", encoding="utf-8", newline="\n") as f:
                        for row in con.execute(f'SELECT * FROM [{table}]'):
                            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
                            n += 1
                    tables_meta[f"{db_name}.{table}"] = {
                        "count": n,
                        "sha256": _sha256_file(abs_path),
                        "path": rel.replace("\\", "/"),
                    }
                    report_tables[f"{db_name}.{table}"] = n
            finally:
                con.close()
        manifest = {
            "format": FORMAT,
            "scope": SCOPE,
            "version": VERSION,
            "mode": "logical",
            "created_at": datetime.now().isoformat(),
            "tables": tables_meta,
        }
        with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return {"export_dir": target_dir, "mode": "logical", "tables": report_tables}

    # ─────────────────────── 物理快照（身体层） ───────────────────────

    def export_physical(self, target_dir: str) -> dict:
        os.makedirs(target_dir, exist_ok=True)
        phys_dir = os.path.join(target_dir, "physical")
        os.makedirs(phys_dir, exist_ok=True)
        db_meta: Dict[str, dict] = {}
        report_dbs: Dict[str, dict] = {}
        for db_name, (db_path, _tables) in self.databases.items():
            snap = os.path.join(phys_dir, os.path.basename(db_path))
            src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(snap)
                with dst:
                    src.backup(dst)
                dst.close()
            finally:
                src.close()
            db_meta[db_name] = {
                "file": os.path.basename(snap),
                "size": os.path.getsize(snap),
                "sha256": _sha256_file(snap),
            }
            report_dbs[db_name] = {"file": os.path.basename(snap)}
        # 附属文件（FAISS index / labels 等）原样拷贝
        for af in self.attachment_files:
            if os.path.exists(af):
                shutil.copy2(af, os.path.join(phys_dir, os.path.basename(af)))
        # 快照行数（供 report）
        for db_name, meta in db_meta.items():
            snap = os.path.join(phys_dir, meta["file"])
            con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            try:
                rows = 0
                for (t,) in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
                ).fetchall():
                    rows += con.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            finally:
                con.close()
            report_dbs[db_name]["rows"] = rows
        manifest = {
            "format": FORMAT,
            "scope": SCOPE,
            "version": VERSION,
            "mode": "physical",
            "created_at": datetime.now().isoformat(),
            "databases": db_meta,
        }
        with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return {"export_dir": target_dir, "mode": "physical", "databases": report_dbs}

    # ─────────────────────── manifest 校验 ───────────────────────

    def verify(self, export_dir: str) -> dict:
        manifest_path = os.path.join(export_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return {"ok": False, "mismatch": ["manifest.json 缺失"]}
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        mismatch: List[str] = []
        for key, meta in manifest.get("tables", {}).items():
            path = os.path.join(export_dir, meta["path"])
            if not os.path.exists(path):
                mismatch.append(f"{key}: 文件缺失 {meta['path']}")
                continue
            if _count_jsonl(path) != meta["count"]:
                mismatch.append(f"{key}: 行数不符")
                continue
            if _sha256_file(path) != meta["sha256"]:
                mismatch.append(f"{key}: SHA256 不符")
        return {"ok": not mismatch, "mismatch": mismatch}

    # ─────────────────────── 导入（documents 幂等样板） ───────────────────────

    def import_documents(
        self, export_dir: str, target_db: str, dry_run: bool = True
    ) -> dict:
        v = self.verify(export_dir)
        if not v["ok"]:
            raise ValueError("导出包校验失败: " + "; ".join(v["mismatch"][:3]))
        src = os.path.join(export_dir, "logical", "livingmemory", "documents.jsonl")
        rows: List[dict] = []
        with open(src, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
        if dry_run:
            return {"dry_run": True, "would_upsert": len(rows)}
        con = sqlite3.connect(target_db)
        try:
            cols = [c[1] for c in con.execute("PRAGMA table_info(documents)").fetchall()]
            usable = [c for c in cols if rows and c in rows[0]] if rows else []
            assert usable, "目标 documents 表无可用列"
            ph = ", ".join("?" for _ in usable)
            updates = ", ".join(f"{c}=excluded.{c}" for c in usable if c != "doc_id")
            sql = (
                f"INSERT INTO documents ({', '.join(usable)}) VALUES ({ph}) "
                f"ON CONFLICT(doc_id) DO UPDATE SET {updates}"
            )
            with con:
                for r in rows:
                    con.execute(sql, [r[c] for c in usable])
        finally:
            con.close()
        return {"dry_run": False, "upserted": len(rows)}
