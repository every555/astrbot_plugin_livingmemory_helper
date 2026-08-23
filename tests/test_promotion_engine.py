# -*- coding: utf-8 -*-
"""召回驱动晋升引擎单测 — Q2硬门槛+衰减评分 / 审批 / 流动退位 / 持久化"""
import sys, os, tempfile
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.promotion_engine import (
    PromotionEngine, _parse_ts, MIN_ACCESS, ACTIVE_DAYS, MAX_PROMOTED, RETIRE_DAYS,
)


def _ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _row(did, ac, days, text="记忆"):
    now = datetime.now()
    return {"doc_id": did, "text": text, "access_count": ac, "last_accessed_at": _ts(now - timedelta(days=days))}


def _fresh_engine(td):
    return PromotionEngine(td)


def test_parse_ts_both_formats():
    assert _parse_ts("2026-08-20 11:00:00") is not None
    assert _parse_ts("2026-08-20T11:00:00") is not None
    assert _parse_ts("") is None
    assert _parse_ts(None) is None


def test_hard_gate_access_count():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, MIN_ACCESS - 1, 0)])
        assert new == [], "次数不足不应入候选"


def test_hard_gate_recent_access():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 99, ACTIVE_DAYS + 1)])
        assert new == [], "7天外访问不应入候选（防僵尸热点）"


def test_score_decay_ranking():
    """同次数：最近召回 > 较久召回（时间衰减）"""
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 5), _row(2, 10, 1)])
        assert [c["doc_id"] for c in new] == [2, 1]
        assert new[0]["score"] > new[1]["score"]


def test_scan_dedup_and_occupied():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        rows = [_row(1, 10, 1), _row(2, 10, 2)]
        e.scan(rows)
        assert e.scan(rows) == [], "重复扫描应全部去重"
        ent, _ = e.approve(1)
        assert ent, "候选#1 应可审批"
        e.reject(2)
        # rejected 的 doc 下轮可再进；approved/promoted 的不再进
        again = e.scan(rows + [_row(3, 10, 0)])
        ids = [c["doc_id"] for c in again]
        assert 1 not in ids, "已晋升的不应重复入候选"
        assert 3 in ids


def test_candidate_top_limit():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        rows = [_row(i, 100 - i, 0) for i in range(1, 16)]
        new = e.scan(rows)
        assert len(new) == 10, "单轮新增候选上限10"
        assert new[0]["doc_id"] == 1, "高召回优先"


def test_approve_moves_to_promoted():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 1, "重要常驻")])
        ent, err = e.approve(new[0]["id"])
        assert ent and not err
        assert ent["doc_id"] == 1 and ent["status"] == "active"
        assert e.list_active_doc_ids() == [1]
        # 席位进入核心索引合并
        again, err2 = e.approve(999)
        assert again is None, "无效ID应报错"


def test_promoted_seat_cap():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        rows = [_row(i, 50 - i, 0) for i in range(1, 8)]
        new = e.scan(rows)
        for c in new[:MAX_PROMOTED]:
            ent, err = e.approve(c["id"])
            assert ent, err
        over, err = e.approve(new[MAX_PROMOTED]["id"])
        assert over is None and "席位已满" in err


def test_reject_keeps_history():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 1)])
        c, _ = e.reject(new[0]["id"])
        assert c["status"] == "rejected"
        assert e.list_candidates("pending") == []


def test_retire_flow_pending_confirm():
    """30天无人召回 → retire_pending（仍常驻）→ 确认后退位"""
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 1)])
        e.approve(new[0]["id"])
        # 6天前访问：不触发
        assert e.check_retire({1: _ts(datetime.now() - timedelta(days=6))}) == []
        # 35天前访问：触发
        props = e.check_retire({1: _ts(datetime.now() - timedelta(days=35))})
        assert len(props) == 1 and props[0]["status"] == "retire_pending"
        assert e.list_active_doc_ids() == [1], "待退位期间仍常驻核心索引"
        p = e.confirm_retire(1)
        assert p["status"] == "retired"
        assert e.list_active_doc_ids() == []


def test_retire_keep_override():
    """橘子说保留 → 回 active 继续服役"""
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 1)])
        e.approve(new[0]["id"])
        e.check_retire({1: _ts(datetime.now() - timedelta(days=RETIRE_DAYS + 5))})
        p = e.keep(1)
        assert p["status"] == "active"
        assert e.list_active_doc_ids() == [1]


def test_persistence_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        new = e.scan([_row(1, 10, 1, "可持久化内容"), _row(2, 9, 1)])
        e.approve(new[0]["id"])
        e2 = _fresh_engine(td)
        assert e2.list_active_doc_ids() == [1]
        assert len(e2.candidates) == 2
        assert e2.candidates[0]["content"].startswith("可持久化")


def test_meeting_brief_content():
    with tempfile.TemporaryDirectory() as td:
        e = _fresh_engine(td)
        assert "无待审候选" in e.meeting_brief()
        new = e.scan([_row(1, 12, 1, "例会简报候选")])
        brief = e.meeting_brief()
        assert "第二议题" in brief and "例会简报候选" in brief
        assert "召回12次" in brief
