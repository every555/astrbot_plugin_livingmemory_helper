# -*- coding: utf-8 -*-
"""TDD RED: haruyuki_memory_replay 核心逻辑测试（P2-⑫ 前置：failed 记忆补录）。"""
import json
import os
import sqlite3
import time
import pytest

from core.memory_replay import MemoryReplayService

# ── 测试数据工厂 ──────────────────────────────────────────

def make_atom(content="原子内容", atom_type="episodic", importance=0.6):
    return {
        "parent_memory_id": 0,
        "atom_type": atom_type,
        "content": content,
        "entities": ["橘子"],
        "importance": importance,
        "confidence": 0.7,
        "created_at": 1753142400.0,
    }

def make_op(op_id, preview="记忆内容" * 20, atoms=None, status="failed",
            step="document_failed", created=None, session="webchat:test"):
    p = {
        "content_preview": preview,
        "session_id": session,
        "persona_id": "春雪_test",
        "importance": 0.8,
        "metadata": {"topics": ["测试"]},
        "atoms": atoms if atoms is not None else [],
    }
    return (op_id, "add", None, status, step, json.dumps(p, ensure_ascii=False),
            None, 0, created or (time.time() - 86400), time.time() - 86400)

def make_db(tmp_path, ops):
    db = os.path.join(tmp_path, "livingmemory.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE memory_write_ops (id INTEGER PRIMARY KEY, op_type TEXT, memory_id INTEGER, status TEXT, step TEXT, payload TEXT, error TEXT, retry_count INTEGER, created_at REAL, updated_at REAL)")
    con.executemany("INSERT INTO memory_write_ops VALUES (?,?,?,?,?,?,?,?,?,?)", ops)
    con.commit(); con.close()
    return db

class StubEngine:
    """只记录调用不真写的假引擎。"""
    def __init__(self):
        self.calls = []
    async def add_memory(self, content, session_id=None, persona_id=None, importance=0.5, metadata=None, atoms=None):
        self.calls.append({"content": content, "session_id": session_id, "persona_id": persona_id, "importance": importance, "metadata": metadata, "atoms": atoms})
        return 9000 + len(self.calls)

# ── 用例 ──────────────────────────────────────────────────

def test_collect_failed(tmp_path):
    """只收 failed 的 add 记录，completed 不收。"""
    db = make_db(tmp_path, [make_op(1, status="failed"), make_op(2, status="completed")])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    ops = svc.collect_failed_ops()
    assert [o["id"] for o in ops] == [1]

def test_clean_excludes_tests(tmp_path):
    """测试记录排除：preview 含 test/测试 memory save 特征。"""
    db = make_db(tmp_path, [
        make_op(1, preview="test memory save"),
        make_op(2, preview="测试记忆工具是否正常工作"),
        make_op(3, preview="2026年7月20日，和橘子修好了bug，过程曲折…"),
    ])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    keep, skip = svc.clean_candidates(svc.collect_failed_ops())
    assert [o["id"] for o in keep] == [3]
    assert {2: "test"} == {} or len(skip) == 2

def test_clean_dedup_cluster(tmp_path):
    """时间窗内无atoms簇去重：只留 preview 最长一条。"""
    t = time.time() - 86400
    db = make_db(tmp_path, [
        make_op(1, preview="短", created=t),
        make_op(2, preview="2026-07-20修复了两个bug：notifications read路由GET改POST、toast无限弹窗", created=t + 60),
        make_op(3, preview="2026-07-20修复了两个bug：notifications read路由GET改POST、toast无限弹窗（补充：已验证通过）", created=t + 120),
        make_op(4, preview="另一条独立记忆，时间在窗外", created=t + 5000),
    ])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    keep, skip = svc.clean_candidates(svc.collect_failed_ops())
    ids = [o["id"] for o in keep]
    assert ids == [3, 4]

def test_atoms_record_not_deduped(tmp_path):
    """有 atoms 的记录不参与去重簇（它们是独立提炼成果）。"""
    t = time.time() - 86400
    db = make_db(tmp_path, [
        make_op(1, atoms=[make_atom("甲")], created=t),
        make_op(2, atoms=[make_atom("乙")], created=t + 60),
    ])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    keep, _ = svc.clean_candidates(svc.collect_failed_ops())
    assert len(keep) == 2

def test_build_plan_atoms(tmp_path):
    """atoms 反序列化成 MemoryAtom，空 content 丢弃，unknown 枚举安全。"""
    from core.memory_replay import MemoryReplayService as _S
    _AT, MemoryAtom = _S._load_atom_cls()
    db = make_db(tmp_path, [make_op(1, atoms=[make_atom("有效原子"), make_atom(""), make_atom("未知类型", atom_type="unknown")])])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    plan = svc.build_plan(svc.collect_failed_ops()[0])
    assert len(plan["atoms"]) == 2
    assert isinstance(plan["atoms"][0], MemoryAtom)
    assert plan["atoms"][0].content == "有效原子"
    assert plan["atoms"][0].created_at == 1753142400.0  # 原时间保留

def test_build_plan_metadata(tmp_path):
    """metadata 带 original_created_at + replay 标记。"""
    t0 = 1753142400.0
    db = make_db(tmp_path, [make_op(7, created=t0)])
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    plan = svc.build_plan(svc.collect_failed_ops()[0])
    md = plan["metadata"]
    assert md["original_created_at"] == t0
    assert md["replay_of_op_id"] == 7
    assert md.get("replayed_at") is not None

@pytest.mark.asyncio
async def test_dry_run_no_engine(tmp_path):
    """dry_run 不碰引擎。"""
    db = make_db(tmp_path, [make_op(1, atoms=[make_atom()])])
    eng = StubEngine()
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"), engine=eng)
    report = await svc.replay(dry_run=True)
    assert eng.calls == []
    assert report["planned"] >= 1

@pytest.mark.asyncio
async def test_execute_and_idempotent(tmp_path):
    """实弹调用引擎；成功后 state 落盘；二跑零重复。"""
    db = make_db(tmp_path, [make_op(1, atoms=[make_atom()]), make_op(2)])
    eng = StubEngine()
    state = os.path.join(tmp_path, "state.json")
    svc = MemoryReplayService(db, state, engine=eng)
    r1 = await svc.replay(dry_run=False)
    assert len(eng.calls) == 2
    assert r1["succeeded"] == 2
    st = json.load(open(state, encoding="utf-8"))
    assert set(map(int, st["replayed_op_ids"])) == {1, 2}
    r2 = await svc.replay(dry_run=False)
    assert r2["planned"] == 0 and len(eng.calls) == 2

def test_source_db_untouched(tmp_path):
    """原库 failed 记录不被修改（历史证据保全）。"""
    db = make_db(tmp_path, [make_op(1)])
    before = sqlite3.connect(db).execute("SELECT status, step, updated_at FROM memory_write_ops WHERE id=1").fetchone()
    svc = MemoryReplayService(db, os.path.join(tmp_path, "state.json"))
    svc.collect_failed_ops(); svc.clean_candidates(svc.collect_failed_ops())
    after = sqlite3.connect(db).execute("SELECT status, step, updated_at FROM memory_write_ops WHERE id=1").fetchone()
    assert before == after

