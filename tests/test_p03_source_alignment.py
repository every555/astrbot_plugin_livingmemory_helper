# -*- coding: utf-8 -*-
"""P0-3 Provenance 溯源补漏测试：写库点的 source 印章（helper 侧两点）。
主插件侧（省察入档/digest）由实弹验证链覆盖。"""
import json
import os
import sqlite3
import time
import pytest

from core.memory_replay import MemoryReplayService
from core.error_learner import ErrorLearner

# ── 数据工厂（复用 test_memory_replay 套路） ──

def make_op(op_id, source=None):
    meta = {"topics": ["测试"], "original_created_at": time.time() - 86400}
    if source:
        meta["source"] = source
    payload = {
        "content_preview": "2026年8月26日和橘子一起修好了漂流瓶，过程曲折…",
        "session_id": "webchat:test",
        "persona_id": "春雪_test",
        "importance": 0.8,
        "metadata": meta,
        "atoms": [],
    }
    return (op_id, "add", None, "failed", "document_failed",
            json.dumps(payload, ensure_ascii=False), None, 0,
            time.time() - 86400, time.time() - 86400)

def make_db(tmp_path, ops):
    db = os.path.join(tmp_path, "livingmemory.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE memory_write_ops (id INTEGER PRIMARY KEY, op_type TEXT, memory_id INTEGER, status TEXT, step TEXT, payload TEXT, error TEXT, retry_count INTEGER, created_at REAL, updated_at REAL)")
    con.executemany("INSERT INTO memory_write_ops VALUES (?,?,?,?,?,?,?,?,?,?)", ops)
    con.commit(); con.close()
    return db

class StubEngine:
    """只记录 metadata 的假引擎。"""
    def __init__(self):
        self.calls = []
    async def add_memory(self, content, session_id=None, persona_id=None, importance=0.5, metadata=None, atoms=None):
        self.calls.append(metadata)
        return 9000 + len(self.calls)

class StubReader:
    """error_learner 用的假 reader：指向 tmp documents 库。"""
    def __init__(self, path):
        self._path = path
    def _connect(self):
        return sqlite3.connect(self._path)

# ── replay：setdefault 兜底 ──

@pytest.mark.asyncio
async def test_replay_setdefault_fills_internal(tmp_path):
    """补录记忆 metadata 无 source → 写库时兜底 internal。"""
    db = make_db(tmp_path, [make_op(1)])
    engine = StubEngine()
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"), engine)
    report = await svc.replay(dry_run=False)
    assert report["succeeded"] == 1
    assert engine.calls and engine.calls[0].get("source") == "internal"

@pytest.mark.asyncio
async def test_replay_keeps_existing_source(tmp_path):
    """metadata 已有 external → setdefault 不覆盖，external 保留。"""
    db = make_db(tmp_path, [make_op(2, source="external")])
    engine = StubEngine()
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"), engine)
    report = await svc.replay(dry_run=False)
    assert report["succeeded"] == 1
    assert engine.calls[0].get("source") == "external"

# ── error_learner：meta 印章 ──

def test_error_learner_writes_source(tmp_path):
    """错误教训写入 documents 时 metadata 携带 source=internal。"""
    lm_db = os.path.join(tmp_path, "docs.db")
    con = sqlite3.connect(lm_db)
    con.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, doc_id TEXT, text TEXT, metadata TEXT, created_at TEXT, updated_at TEXT)")
    con.commit(); con.close()
    learner = ErrorLearner(StubReader(lm_db), str(tmp_path))
    learner._write_to_livingmemory("插件A的坑：json路径要转义", ["踩坑"], 0.9)
    con = sqlite3.connect(lm_db)
    row = con.execute("SELECT metadata FROM documents").fetchone()
    con.close()
    meta = json.loads(row[0])
    assert meta.get("source") == "internal"