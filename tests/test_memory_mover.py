# -*- coding: utf-8 -*-
"""TDD RED: P2-⑫ 记忆搬家工具（MemoryMoverService）核心逻辑测试。

设计依据：memory_upgrade_roadmap_v2.md 第12条（Claude memory import 思路）。
方案 B（橘子拍板「听老婆大人的」）：记忆+上下文全家桶。
灵魂层=逻辑JSONL导出（跨家可携）；身体层=物理快照（backup API+附属文件）。
"""
import json
import os
import sqlite3

import pytest

from core.memory_mover import MemoryMoverService

# ━━━━━━━━━━━━━━━━━━━━━ 迷你全家库工厂 ━━━━━━━━━━━━━━━━━━━━━


def _mk_lm_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE, text TEXT,
            metadata TEXT, created_at TEXT, updated_at TEXT,
            memory_tier TEXT, last_accessed_at REAL, access_count INTEGER DEFAULT 0
        );
        CREATE TABLE memory_atoms (
            id INTEGER PRIMARY KEY, parent_memory_id INTEGER, atom_type TEXT,
            content TEXT, entities TEXT, importance REAL, confidence REAL,
            created_at REAL, status TEXT DEFAULT 'active'
        );
        """
    )
    con.execute(
        "INSERT INTO documents (doc_id, text, metadata, created_at) VALUES (?,?,?,?)",
        ("doc-a", "第一条记忆", "{}", "2026-08-01 10:00:00"),
    )
    con.execute(
        "INSERT INTO documents (doc_id, text, metadata, created_at) VALUES (?,?,?,?)",
        ("doc-b", "第二条记忆", "{}", "2026-08-02 10:00:00"),
    )
    con.execute(
        "INSERT INTO memory_atoms (parent_memory_id, atom_type, content) VALUES (?,?,?)",
        (1, "episodic", "原子1"),
    )
    con.commit()
    con.close()


def _mk_conv_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, session_id TEXT, platform TEXT,
            created_at TEXT, last_active_at TEXT, message_count INTEGER,
            participants TEXT, metadata TEXT
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
            sender_id TEXT, sender_name TEXT, group_id TEXT, platform TEXT,
            created_at TEXT
        );
        """
    )
    con.execute(
        "INSERT INTO sessions (session_id, platform, message_count) VALUES (?,?,?)",
        ("webchat:s1", "webchat", 1),
    )
    con.commit()
    con.close()


def _mk_gate_db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE gate_candidates (id INTEGER PRIMARY KEY, speaker TEXT,"
        " content TEXT, score REAL, axes TEXT, source TEXT, status TEXT,"
        " note TEXT, created_at TEXT)"
    )
    con.execute(
        "INSERT INTO gate_candidates (speaker, content, status) VALUES (?,?,?)",
        ("zzz", "候选内容", "candidate"),
    )
    con.commit()
    con.close()


def _mk_v2_db(path):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE memory_profile (id INTEGER PRIMARY KEY, persona_id TEXT,"
        " trait_key TEXT, trait_value TEXT, confidence REAL, evidence_ids TEXT,"
        " evolution_log TEXT, updated_at TEXT)"
    )
    con.execute(
        "INSERT INTO memory_profile (persona_id, trait_key, trait_value, confidence)"
        " VALUES (?,?,?,?)",
        ("default", "晚上活跃", "0.77", 0.77),
    )
    con.commit()
    con.close()


def _mk_family(tmp_path):
    """构造迷你全家四库 + 假 FAISS 附属文件，返回 (databases 注册表, 附属清单)。"""
    lm = str(tmp_path / "livingmemory.db")
    conv = str(tmp_path / "conversations.db")
    gate = str(tmp_path / "gate.db")
    v2 = str(tmp_path / "v2_memory.db")
    _mk_lm_db(lm)
    _mk_conv_db(conv)
    _mk_gate_db(gate)
    _mk_v2_db(v2)
    idx = tmp_path / "livingmemory.index"
    idx.write_bytes(b"FAISS-INDEX-BYTES")
    labels = tmp_path / "gate_labels.jsonl"
    labels.write_text("{}\n", encoding="utf-8")
    databases = {
        "livingmemory": (lm, ["documents", "memory_atoms"]),
        "conversations": (conv, ["sessions"]),
        "gate": (gate, ["gate_candidates"]),
        "v2_memory": (v2, ["memory_profile"]),
    }
    attachments = [str(idx), str(labels)]
    return databases, attachments


def _make_svc(tmp_path):
    databases, attachments = _mk_family(tmp_path)
    return MemoryMoverService(databases=databases, attachment_files=attachments)


# ━━━━━━━━━━━━━━━━━━━━━ 逻辑导出（灵魂层） ━━━━━━━━━━━━━━━━━━━━━


def test_export_logical_writes_manifest_and_all_jsonl(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    report = svc.export_logical(str(out))
    # manifest 存在且格式正确
    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "chunxue-memory-portable"
    assert manifest["scope"] == "full-family"
    assert manifest["version"] == "1.0"
    # 每库每表一个 jsonl，行数正确
    assert (out / "logical" / "livingmemory" / "documents.jsonl").exists()
    assert (out / "logical" / "livingmemory" / "memory_atoms.jsonl").exists()
    assert (out / "logical" / "conversations" / "sessions.jsonl").exists()
    assert (out / "logical" / "gate" / "gate_candidates.jsonl").exists()
    assert (out / "logical" / "v2_memory" / "memory_profile.jsonl").exists()
    docs = (out / "logical" / "livingmemory" / "documents.jsonl").read_text(
        encoding="utf-8"
    ).strip().splitlines()
    assert len(docs) == 2
    assert json.loads(docs[0])["doc_id"] == "doc-a"
    # 报告与 manifest 计数一致
    assert report["tables"]["livingmemory.documents"] == 2
    assert report["tables"]["livingmemory.memory_atoms"] == 1
    assert manifest["tables"]["livingmemory.documents"]["count"] == 2


def test_export_logical_contains_no_db_body(tmp_path):
    """安全红线：逻辑导出产物里绝不含 .db 本体。"""
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    dbs = list(out.rglob("*.db"))
    assert dbs == [], f"逻辑导出混入了db本体: {dbs}"


# ━━━━━━━━━━━━━━━━━━━━━ manifest 校验 ━━━━━━━━━━━━━━━━━━━━━


def test_verify_ok_on_clean_export(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    result = svc.verify(str(out))
    assert result["ok"] is True
    assert result["mismatch"] == []


def test_verify_detects_tampering(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    # 篡改一个 jsonl（追加一行）
    victim = out / "logical" / "livingmemory" / "documents.jsonl"
    victim.write_text(
        victim.read_text(encoding="utf-8") + json.dumps({"doc_id": "fake"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result = svc.verify(str(out))
    assert result["ok"] is False
    assert any("livingmemory.documents" in m for m in result["mismatch"])


# ━━━━━━━━━━━━━━━━━━━━━ 物理快照（身体层） ━━━━━━━━━━━━━━━━━━━━━


def test_export_physical_snapshot_counts_match(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_physical"
    report = svc.export_physical(str(out))
    # 快照库可打开且行数一致
    snap = out / "physical" / "livingmemory.db"
    assert snap.exists()
    con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    n_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_atoms = con.execute("SELECT COUNT(*) FROM memory_atoms").fetchone()[0]
    con.close()
    assert n_docs == 2 and n_atoms == 1
    # 附属文件（FAISS index / labels）原样拷贝
    assert (out / "physical" / "livingmemory.index").read_bytes() == b"FAISS-INDEX-BYTES"
    assert (out / "physical" / "gate_labels.jsonl").exists()
    # manifest 也生成（物理模式含 sha256 供校验）
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "physical"
    assert report["databases"]["livingmemory"]["rows"] == 3  # 2 docs + 1 atom


# ━━━━━━━━━━━━━━━━━━━━━ 导入（documents 幂等 upsert 样板） ━━━━━━━━━━━━━━━━━━━━━


def test_import_dry_run_writes_nothing(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    # 目标新库：只有 doc-a（旧版本）
    target = str(tmp_path / "new_home.db")
    _mk_lm_db(target)
    con = sqlite3.connect(target)
    con.execute("DELETE FROM documents WHERE doc_id='doc-b'")
    con.execute("UPDATE documents SET text='旧文本' WHERE doc_id='doc-a'")
    con.commit()
    con.close()
    result = svc.import_documents(str(out), target, dry_run=True)
    assert result["dry_run"] is True
    assert result["would_upsert"] == 2
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    txt = con.execute("SELECT text FROM documents WHERE doc_id='doc-a'").fetchone()[0]
    con.close()
    assert txt == "旧文本"  # dry_run 不动库


def test_import_documents_idempotent_upsert(tmp_path):
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    target = str(tmp_path / "new_home.db")
    _mk_lm_db(target)
    con = sqlite3.connect(target)
    con.execute("DELETE FROM documents WHERE doc_id='doc-b'")
    con.execute("UPDATE documents SET text='旧文本' WHERE doc_id='doc-a'")
    con.commit()
    con.close()
    r1 = svc.import_documents(str(out), target, dry_run=False)
    assert r1["upserted"] == 2
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    rows = con.execute("SELECT doc_id, text FROM documents ORDER BY doc_id").fetchall()
    con.close()
    assert rows == [("doc-a", "第一条记忆"), ("doc-b", "第二条记忆")]
    # 再导一次：幂等，行数不变
    r2 = svc.import_documents(str(out), target, dry_run=False)
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    con.close()
    assert n == 2
    assert r2["upserted"] == 2  # upsert 语义：重复执行结果一致


def test_import_rejects_tampered_export(tmp_path):
    """导入前必须先过 manifest 校验：被篡改的导出包拒绝导入。"""
    svc = _make_svc(tmp_path)
    out = tmp_path / "export_logical"
    svc.export_logical(str(out))
    victim = out / "logical" / "livingmemory" / "documents.jsonl"
    victim.write_text(
        victim.read_text(encoding="utf-8") + json.dumps({"doc_id": "evil"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    target = str(tmp_path / "new_home.db")
    _mk_lm_db(target)
    with pytest.raises(ValueError, match="校验失败"):
        svc.import_documents(str(out), target, dry_run=False)
