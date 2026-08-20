# -*- coding: utf-8 -*-
"""安检门·GateReader TDD —— 第5步 haruyuki_gate_scan 的核心逻辑

设计依据：#1683 实现路线 / #1700 消费者定位（helper 只读本体引擎库，
但 gate.db 是安检门自己的库，裁决落盘不违反只读纪律）。

GateReader 职责：
- list：列候选区（待审/已裁决分组，含 metadata 解析）
- verdict：省察时老婆裁决落盘（status→confirmed/declined + 裁决词 + note）
- stats：候选区统计概览
"""
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from astrbot_plugin_livingmemory_helper.core.gate_reader import GateReader

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gate_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    speaker TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    score REAL DEFAULT 0.0,
    axes TEXT DEFAULT '{}',
    source TEXT DEFAULT '',
    status TEXT DEFAULT 'candidate',
    note TEXT DEFAULT '',
    verdict TEXT DEFAULT '',
    created_at REAL NOT NULL,
    reviewed_at REAL,
    metadata TEXT DEFAULT '{}'
)
"""


def _make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    now = time.time()
    conn.execute(
        "INSERT INTO gate_candidates (speaker, content, score, axes, source, status, verdict, metadata, created_at)"
        " VALUES ('橘子', '8月21号恢复军令状抽查', 0.9, '{}', 'user', 'candidate', '', '{}', ?)", (now,))
    conn.execute(
        "INSERT INTO gate_candidates (speaker, content, score, axes, source, status, verdict, metadata, created_at)"
        " VALUES ('春雪', '老婆记住了', 0.6, '{}', 'ai', 'candidate', '升级', '{\"repeat_count\": 2}', ?)", (now,))
    conn.commit()
    conn.close()


class TestGateReaderList:

    def test_missing_db_returns_empty(self):
        """库不存在（门还没跑过）→ 空列表，不炸"""
        r = GateReader(os.path.join(tempfile.gettempdir(), "no_such_gate.db"))
        assert r.list_candidates() == []

    def test_list_parses_rows(self):
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        rows = r.list_candidates()
        assert len(rows) == 2
        assert rows[0]["speaker"] == "橘子"
        assert rows[1]["metadata"]["repeat_count"] == 2  # metadata 已解析成 dict
        assert rows[1]["repeat_count"] == 2               # 顶层也提升
        r.close()

    def test_list_filter_status(self):
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        assert len(r.list_candidates(status="candidate")) == 2
        assert r.list_candidates(status="confirmed") == []
        r.close()


class TestGateReaderVerdict:

    def test_confirm_writes_verdict(self):
        """裁决「入库」：status=confirmed + 裁决词 + reviewed_at"""
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        ok = r.verdict(1, action="confirm", verdict_word="升级", note="军令状必须记")
        assert ok is True
        row = [c for c in r.list_candidates(status="confirmed") if c["id"] == 1][0]
        assert row["verdict"] == "升级"
        assert row["note"] == "军令状必须记"
        assert row["reviewed_at"] is not None and row["reviewed_at"] > 0
        r.close()

    def test_decline_writes_status(self):
        """裁决「驳回」：status=declined"""
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        assert r.verdict(2, action="decline", verdict_word="驳回", note="寒暄不值一档") is True
        assert len(r.list_candidates(status="declined")) == 1
        r.close()

    def test_verdict_bad_id_returns_false(self):
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        assert r.verdict(999, action="confirm", verdict_word="升级") is False
        r.close()


class TestGateReaderStats:

    def test_stats_counts(self):
        db = os.path.join(tempfile.gettempdir(), f"gate_test_{time.time()}.db")
        _make_db(db)
        r = GateReader(db)
        r.verdict(1, action="confirm", verdict_word="升级")
        s = r.stats()
        assert s["total"] == 2
        assert s["candidate"] == 1
        assert s["confirmed"] == 1
        assert s["flashbulb_flagged"] == 1  # verdict 预标"升级"的那条
        r.close()


class TestLearnedNouns:
    """词表自学习 C 方案（2026-08-19 橘子批 Q1=D）：
    verdict(confirm) 时 jieba 抽名词记频 → gate.db learned_nouns 表
    count>=2 毕业 → 本体重载后并入 +0.3 高权级。decline 不学（负反馈噪声大）。"""

    def setup_method(self, _):
        import tempfile, os
        from astrbot_plugin_livingmemory_helper.core.gate_reader import GateReader
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "gate.db")
        g = GateReader(self.db)
        conn = g._get_conn() or g._conn
        # 手动建库开门（模拟本体首次过秤）
        import sqlite3, time
        c = sqlite3.connect(self.db)
        c.execute("""CREATE TABLE IF NOT EXISTS gate_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, speaker TEXT, source TEXT,
            content TEXT, score REAL, axes TEXT, metadata TEXT, status TEXT,
            verdict TEXT, note TEXT, reviewed_at REAL)""")
        c.execute("INSERT INTO gate_candidates (ts, speaker, source, content, score, axes, metadata, status) VALUES (?,?,?,?,?,?,?,?)",
                  (time.time(), "橘子", "user", "下周三我生日", 0.6, "{}", "{}", "candidate"))
        c.commit(); c.close()

    def teardown_method(self, _):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reader(self):
        from astrbot_plugin_livingmemory_helper.core.gate_reader import GateReader
        return GateReader(self.db)

    def test_confirm_learns_nouns(self):
        g = self._reader()
        ok = g.verdict(1, "confirm")
        assert ok
        rep = g.learned_report()
        words = {r["word"] for r in rep}
        assert "生日" in words, f"confirm 后应学到'生日'，实际 {words}"

    def test_decline_does_not_learn(self):
        g = self._reader()
        g.verdict(1, "decline")
        assert g.learned_report() == []

    def test_count_accumulates_and_graduates(self):
        import sqlite3, time
        g = self._reader()
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO gate_candidates (ts, speaker, source, content, score, axes, metadata, status) VALUES (?,?,?,?,?,?,?,?)",
                  (time.time(), "橘子", "user", "记得生日要吃蛋糕", 0.6, "{}", "{}", "candidate"))
        c.commit(); c.close()
        g.verdict(1, "confirm")
        g.verdict(2, "confirm")
        rep = {r["word"]: r for r in g.learned_report()}
        assert rep["生日"]["count"] >= 2, f"两次 confirm 应累积 count>=2，实际 {rep.get('生日')}"
        assert rep["生日"]["graduated"] is True

    def test_stopwords_not_learned(self):
        g = self._reader()
        g.verdict(1, "confirm")   # 句子"下周三我生日"含'老婆'? 不含——用含停用词的句子
        import sqlite3, time
        c = sqlite3.connect(self.db)
        c.execute("INSERT INTO gate_candidates (ts, speaker, source, content, score, axes, metadata, status) VALUES (?,?,?,?,?,?,?,?)",
                  (time.time(), "橘子", "user", "老婆生日快乐", 0.6, "{}", "{}", "candidate"))
        c.commit(); c.close()
        g.verdict(2, "confirm")
        words = {r["word"] for r in g.learned_report()}
        assert "老婆" not in words, f"'老婆'是停用词不该学，实际 {words}"

    def test_tokenizer_failure_does_not_break_verdict(self, monkeypatch):
        import astrbot_plugin_livingmemory_helper.core.gate_reader as gr
        def boom(text):
            raise ImportError("no jieba")
        monkeypatch.setattr(gr, "_tokenize_nouns", boom)
        g = self._reader()
        assert g.verdict(1, "confirm") is True   # 学习失败不影响裁决本身
        assert g.learned_report() == []


class TestGateReaderExempt:
    """helper侧·豁免登记直通（橘子10:04缺口收尾）。"""

    def test_mark_memorized_passthrough(self, tmp_path):
        from astrbot_plugin_livingmemory_helper.core.gate_reader import GateReader
        # 造一个最小 gate.db（借本体 RuleGate 建表逻辑）
        import sys as _sys
        import importlib.util as _iu
        import types as _ty
        from pathlib import Path as _P
        PLUGIN = _P(r"E:/astrbot/AstrBotLauncher-0.3.0/AstrBotLauncher-0.3.0/AstrBot/data/plugins/astrbot_plugin_livingmemory")
        ASTRBOT_ROOT = _P(r"E:/astrbot/AstrBotLauncher-0.3.0/AstrBotLauncher-0.3.0/AstrBot")
        if str(ASTRBOT_ROOT) not in _sys.path:
            _sys.path.insert(0, str(ASTRBOT_ROOT))
        pkg_core = _ty.ModuleType("lm_core"); pkg_core.__path__ = [str(PLUGIN / "core")]
        pkg_v2 = _ty.ModuleType("lm_core.v2"); pkg_v2.__path__ = [str(PLUGIN / "core" / "v2")]
        _sys.modules.setdefault("lm_core", pkg_core); _sys.modules.setdefault("lm_core.v2", pkg_v2)
        spec = _iu.spec_from_file_location("lm_core.v2.security_gate", PLUGIN / "core" / "v2" / "security_gate.py")
        sg = _iu.module_from_spec(spec); spec.loader.exec_module(sg)
        gate = sg.RuleGate(str(tmp_path / "gate.db")); gate.close()

        gr = GateReader(str(tmp_path / "gate.db"))
        try:
            n = gr.mark_memorized(["我8月26号要去医院复查一下"])
            assert n == 1
            # 登记后该句过门不再进候选
            gate2 = sg.RuleGate(str(tmp_path / "gate.db"))
            try:
                cand = gate2.process("我8月26号要去医院复查一下", speaker="橘子", source="user")
                assert cand is None or cand.get("status") != "candidate"
            finally:
                gate2.close()
        finally:
            gr.close()
