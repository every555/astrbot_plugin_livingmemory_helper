# -*- coding: utf-8 -*-
"""P2-⑩ 工具日志桥测试：log_errors × warstories → 知识毕业候选。"""
import json
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.tool_activity import ToolActivityBridge


def _make_log_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE log_errors(
        id INTEGER PRIMARY KEY, signature TEXT, first_seen TEXT, last_seen TEXT,
        occurrence INTEGER, level TEXT, source TEXT, location TEXT, message TEXT,
        traceback TEXT, acknowledged INTEGER DEFAULT 0, acknowledged_at TEXT)""")
    con.executemany(
        "INSERT INTO log_errors(signature,occurrence,level,location,message,acknowledged) VALUES(?,?,?,?,?,?)",
        rows)
    con.commit(); con.close()


def _make_warstories(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _mk(tmp, name):
    return os.path.join(str(tmp), name)


class FakeGraduator:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def propose_candidate(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(kw)
        return {"id": len(self.calls), "status": "candidate", "message": "ok"}


def test_scan_matches_error_to_warstory(tmp_path):
    db = _mk(tmp_path, "log_errors.db")
    _make_log_db(db, [
        ("v11_features ModuleNotFoundError", 4, "TRACEBACK", "schedulers/v11_scheduler.py", "No module named v11_features", 0),
        ("unrelated timeout", 1, "WARNING", "x.py", "read timeout", 0),
    ])
    ws = _mk(tmp_path, "warstories.jsonl")
    _make_warstories(ws, [{
        "id": "ws1", "meta": {"task": "v11 scheduler fix", "keywords": ["v11_features", "scheduler"]},
        "lessons": "延迟import要写对相对层级",
    }])
    br = ToolActivityBridge(db, ws, state_path=_mk(tmp_path, "state.json"))
    r = br.scan()
    assert r["errors_scanned"] == 2
    assert r["warstories_loaded"] == 1
    assert len(r["matched"]) == 1
    assert r["matched"][0]["error_id"] == 1
    assert r["matched"][0]["warstory_id"] == "ws1"
    assert len(r["orphans"]) == 1 and r["orphans"][0]["error_id"] == 2


def test_scan_skips_acknowledged(tmp_path):
    db = _mk(tmp_path, "log_errors.db")
    _make_log_db(db, [
        ("v11_features ModuleNotFoundError", 4, "TRACEBACK", "schedulers/v11_scheduler.py", "No module named v11_features", 1),
    ])
    ws = _mk(tmp_path, "warstories.jsonl")
    _make_warstories(ws, [{
        "id": "ws1", "meta": {"task": "v11 scheduler fix", "keywords": ["v11_features"]},
        "lessons": "x",
    }])
    br = ToolActivityBridge(db, ws, state_path=_mk(tmp_path, "state.json"))
    r = br.scan()
    assert r["errors_scanned"] == 0 and not r["matched"] and not r["orphans"]


def test_harvest_dry_run_no_propose(tmp_path):
    db = _mk(tmp_path, "log_errors.db")
    _make_log_db(db, [
        ("v11_features ModuleNotFoundError", 4, "TRACEBACK", "s.py", "No module named v11_features", 0),
    ])
    ws = _mk(tmp_path, "warstories.jsonl")
    _make_warstories(ws, [{
        "id": "ws1", "meta": {"task": "v11 fix", "keywords": ["v11_features", "scheduler"]},
        "lessons": "相对导入层级",
    }])
    g = FakeGraduator()
    br = ToolActivityBridge(db, ws, graduator=g, state_path=_mk(tmp_path, "state.json"))
    r = br.harvest(dry_run=True)
    assert g.calls == []
    assert r["proposed"] == 0 and len(r["preview"]) == 1


def test_harvest_proposes_and_dedup(tmp_path):
    db = _mk(tmp_path, "log_errors.db")
    _make_log_db(db, [
        ("v11_features ModuleNotFoundError", 4, "TRACEBACK", "s.py", "No module named v11_features", 0),
    ])
    ws = _mk(tmp_path, "warstories.jsonl")
    _make_warstories(ws, [{
        "id": "ws1", "meta": {"task": "v11 fix", "keywords": ["v11_features", "scheduler"]},
        "lessons": "相对导入层级",
    }])
    g = FakeGraduator()
    st = _mk(tmp_path, "state.json")
    br = ToolActivityBridge(db, ws, graduator=g, state_path=st)
    r1 = br.harvest(dry_run=False)
    assert r1["proposed"] == 1 and len(g.calls) == 1
    kw = g.calls[0]
    assert kw["source_type"] == "insight" and "tool_log_bridge" in kw["tags"]
    # 第二轮：同签名不重复
    r2 = br.harvest(dry_run=False)
    assert r2["proposed"] == 0 and r2["skipped_dup"] == 1 and len(g.calls) == 1


def test_graduator_failure_does_not_crash(tmp_path):
    db = _mk(tmp_path, "log_errors.db")
    _make_log_db(db, [
        ("v11_features ModuleNotFoundError", 4, "TRACEBACK", "s.py", "No module named v11_features", 0),
    ])
    ws = _mk(tmp_path, "warstories.jsonl")
    _make_warstories(ws, [{
        "id": "ws1", "meta": {"task": "v11 fix", "keywords": ["v11_features", "scheduler"]},
        "lessons": "x",
    }])
    g = FakeGraduator(fail=True)
    br = ToolActivityBridge(db, ws, graduator=g, state_path=_mk(tmp_path, "state.json"))
    r = br.harvest(dry_run=False)
    assert r["proposed"] == 0 and r["failed"] == 1
