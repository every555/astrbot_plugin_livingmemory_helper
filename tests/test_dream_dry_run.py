# -*- coding: utf-8 -*-
"""P0-3 Auto-Dream 测试：dry_run 预览 / 冲突巡检 / 报告落盘 / 零写入保证"""
import os
import json
import time
import asyncio
import sqlite3
import pytest
from astrbot_plugin_livingmemory_helper.core.dream_engine import DreamEngine


class FakeReader:
    def __init__(self, db_path, memories=None):
        self.db_path = db_path
        self._memories = memories or []

    def get_recent_memories(self, limit=50):
        return self._memories[:limit]

    def get_memory_count_since(self, ts):
        return 99


def _make_db(tmp_path):
    db = os.path.join(tmp_path, "livingmemory.db")
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT UNIQUE, text TEXT, metadata TEXT,
        created_at REAL, updated_at REAL)""")
    docs = [
        # 高相似对: 1(imp0.3) vs 2(imp0.6) → Jaccard 4/6=0.67 应归并1入2
        # (注: 中文连续串被整串当一个词,空格分词才产生多词集合——原版算法已知局限,P1演化再升级)
        ("d1", "橘雪英语 背单词 每日打卡 晚上复习 streak", {"importance": 0.3}),
        ("d2", "橘雪英语 背单词 每日打卡 晚上复习 坚持", {"importance": 0.6}),
        # 不相似 + 高保护
        ("d3", "专升本考试在2027年4月", {"importance": 0.9}),
        ("d4", "今天吃了甜椒炒肉", {"importance": 0.2}),
    ]
    now = time.time()
    for i, (d, text, meta) in enumerate(docs, 1):
        con.execute("INSERT INTO documents(id,doc_id,text,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (i, d, text, json.dumps(meta, ensure_ascii=False), now, now))
    con.commit()
    con.close()
    return db


def _snapshot(db):
    con = sqlite3.connect(db)
    rows = con.execute("SELECT id,doc_id,text,metadata FROM documents ORDER BY id").fetchall()
    con.close()
    return rows


def _make_engine(tmp_path, memories=None):
    db = _make_db(tmp_path)
    reader = FakeReader(db, memories)
    eng = DreamEngine(reader, str(tmp_path))
    return eng, db


CONFLICT_MEMS = [
    {"id": 1, "content": "橘子台式机密码是131428", "tags": ["台式机", "密码"], "key_facts": ["131428"]},
    {"id": 2, "content": "橘子台式机密码改成了999", "tags": ["台式机", "密码"], "key_facts": ["999"]},
]


def test_dry_run_report_structure(tmp_path):
    eng, db = _make_engine(tmp_path)
    rep = eng.dry_run_dream()
    assert rep["mode"] == "dry_run"
    assert set(["consolidate_pairs", "prune_preview", "conflicts", "totals"]) <= set(rep.keys())
    t = rep["totals"]
    assert set(["merge_candidates", "prune_candidates", "conflict_candidates"]) <= set(t.keys())


def test_dry_run_zero_write(tmp_path):
    eng, db = _make_engine(tmp_path)
    before = _snapshot(db)
    eng.dry_run_dream()
    after = _snapshot(db)
    assert before == after, "dry_run 绝不允许改动 documents"
    assert not os.path.exists(os.path.join(str(tmp_path), ".dream_engine.lock")), "dry_run 不得抢锁"


def test_dry_run_no_backup_side_effect(tmp_path):
    eng, db = _make_engine(tmp_path)
    eng.dry_run_dream()
    assert not os.path.exists(eng.backup_path), "dry_run 不得生成备份"


def test_consolidate_preview_catches_similar(tmp_path):
    eng, db = _make_engine(tmp_path)
    pairs = eng._preview_consolidate_pairs()
    assert len(pairs) >= 1, "d1/d2 相似度>0.6 应被捕获"
    p = pairs[0]
    assert p["keep_id"] == 2 and p["merge_id"] == 1, "importance 高者(0.6)应保留"


def test_conflict_scan_via_fake_reader(tmp_path):
    eng, db = _make_engine(tmp_path, memories=CONFLICT_MEMS)
    conflicts = eng._run_conflict_scan()
    assert len(conflicts) == 1
    assert conflicts[0]["id_a"] == 1 and conflicts[0]["id_b"] == 2


def test_report_saved_and_loaded(tmp_path):
    eng, db = _make_engine(tmp_path)
    eng.dry_run_dream()
    assert os.path.exists(eng.report_file)
    rep = eng.load_dream_report()
    assert rep is not None and rep["mode"] == "dry_run"
    # 篡改为 27h 前 → 过期
    rep["saved_at"] = time.time() - 27 * 3600
    with open(eng.report_file, "w", encoding="utf-8") as f:
        json.dump(rep, f)
    assert eng.load_dream_report() is None, "超26h应视为过期"


def test_run_dream_dry_run_routes(tmp_path):
    eng, db = _make_engine(tmp_path, memories=CONFLICT_MEMS)
    rep = asyncio.run(eng.run_dream(force=False, dry_run=True))
    assert rep is not None and rep["mode"] == "dry_run"
    assert rep["totals"]["conflict_candidates"] == 1
    assert _snapshot(db) == _snapshot(db), "sanity"


# ── P1-① 分词修复：CJK bigram 替换整串正则 ──
from astrbot_plugin_livingmemory_helper.core.dream_engine import _bigram_tokens


def test_bigram_tokens_split_cjk():
    """中文长句不再整串当一个词，出二元组；英文数字保留整词。"""
    toks = _bigram_tokens("今天橘子背完了U10全部单词")
    assert len(toks) >= 5
    assert "橘子" in toks
    assert "u10" in toks


def test_bigram_true_duplicates_still_detected():
    """真重复对相似度 >= 0.6（归并阈值不失守）。"""
    a = _bigram_tokens("橘子背完了U10最后一章，253词全清")
    b = _bigram_tokens("橘子背完了U10最后一章，253词全清")
    u = a | b
    assert len(a & b) / len(u) >= 0.6


def test_bigram_date_overlap_no_false_positive():
    """同日期不同事的记忆：假阳性压到 <0.4（旧正则会撞出 0.4+）。"""
    a = _bigram_tokens("8月22日春雪交卷P0三项全完工")
    b = _bigram_tokens("8月22日橘子背英语U10还差4分钟")
    u = a | b
    sim = len(a & b) / len(u) if u else 0.0
    assert sim < 0.4


def test_bigram_empty_and_none_safe():
    assert _bigram_tokens("") == set()
    assert _bigram_tokens(None) == set()
