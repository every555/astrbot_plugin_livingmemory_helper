# -*- coding: utf-8 -*-
"""confirm 死循环回归测试（2026-08-26 修复）

根因：review_checklist 审查项#3 读候选区 applicability，但 propose_candidate
不收该参数（候选边界恒空），applicability 只在毕业时写入 → 4/5 < 5/5 永真 →
agent_tools confirm 分支无限展示审查清单（鸡蛋死锁）。

修复：review_checklist 接受 applicability_override（confirm 调用带来的边界
文本优先于存量）；带边界的二次 confirm 真 5/5 自然过门 → 毕业并写入边界。
"""
import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
CORE = os.path.join(PLUGIN, "core")
UTILS = os.path.join(PLUGIN, "utils")

_BOOTED = False


def _bootstrap():
    """伪造 astrbot 宿主模块 + 假包骨架，让 agent_tools 可独立导入（知识 #56 手法）。"""
    global _BOOTED
    if _BOOTED:
        return

    class _FakeFunctionTool:
        def __init_subclass__(cls, **kw):
            pass

        def __class_getitem__(cls, item):
            return cls

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = MagicMock()
    astrbot.api = api
    core = types.ModuleType("astrbot.core")
    agent_m = types.ModuleType("astrbot.core.agent")
    tool_m = types.ModuleType("astrbot.core.agent.tool")
    tool_m.FunctionTool = _FakeFunctionTool
    tool_m.ToolExecResult = type("_FakeToolExecResult", (), {})
    rc_m = types.ModuleType("astrbot.core.agent.run_context")
    rc_m.ContextWrapper = type("_FakeCW", (), {})
    agctx_m = types.ModuleType("astrbot.core.astr_agent_context")
    agctx_m.AstrAgentContext = type("_FakeAAC", (), {})
    core.agent = agent_m
    core.astr_agent_context = agctx_m
    agent_m.tool = tool_m
    agent_m.run_context = rc_m
    for n, m in {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.core": core,
        "astrbot.core.agent": agent_m,
        "astrbot.core.agent.tool": tool_m,
        "astrbot.core.agent.run_context": rc_m,
        "astrbot.core.astr_agent_context": agctx_m,
    }.items():
        sys.modules.setdefault(n, m)
    pkg = types.ModuleType("lmh_under_test")
    pkg.__path__ = [PLUGIN]
    core_pkg = types.ModuleType("lmh_under_test.core")
    core_pkg.__path__ = [CORE]
    utils_pkg = types.ModuleType("lmh_under_test.utils")
    utils_pkg.__path__ = [UTILS]
    sys.modules["lmh_under_test"] = pkg
    sys.modules["lmh_under_test.core"] = core_pkg
    sys.modules["lmh_under_test.utils"] = utils_pkg
    _BOOTED = True


def _load(name, relpath):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(PLUGIN, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_graduator(tmp):
    kg = _load("lmh_under_test.core.knowledge_graduator", os.path.join("core", "knowledge_graduator.py"))
    return kg.KnowledgeGraduator(MagicMock(), MagicMock(), tmp)


def _mk_candidate(g):
    r = g.propose_candidate(
        title="经验轨迹加权决策",
        conclusion="任务启动前检索相似历史轨迹，统计成功与失败模式注入决策上下文，完成后沉淀三元组供下次复用。",
        source_type="insight",
        source_id=0,
        knowledge_type="technical",
        importance=0.8,
    )
    assert r.get("id"), "propose 应返回 id: %r" % r
    return r["id"]


def test_review_override_makes_boundary_pass():
    _bootstrap()
    with tempfile.TemporaryDirectory() as tmp:
        g = _make_graduator(tmp)
        kid = _mk_candidate(g)
        base = g.review_checklist(kid)
        assert base["passed"] == 4 and base["total"] == 5, (
            "候选区边界恒空应 4/5（死循环根源），实际 %s/%s" % (base["passed"], base["total"]))
        ov = g.review_checklist(kid, applicability_override="适用：新任务设计前；不适用：闲聊。")
        assert ov["passed"] == 5, "override 后应 5/5，实际 %s/%s" % (ov["passed"], ov["total"])


def test_confirm_with_applicability_graduates():
    _bootstrap()
    at = _load("lmh_under_test.core.agent_tools", os.path.join("core", "agent_tools.py"))
    with tempfile.TemporaryDirectory() as tmp:
        g = _make_graduator(tmp)
        kid = _mk_candidate(g)
        out1 = asyncio.run(at.AgentToolImplementations.knowledge(
            None, g, {"action": "confirm", "knowledge_id": kid}))
        assert "审查清单" in out1, "第一次 confirm（无边界）仍应展示清单，实际: " + out1[:120]
        out2 = asyncio.run(at.AgentToolImplementations.knowledge(
            None, g, {"action": "confirm", "knowledge_id": kid,
                      "applicability": "适用：修 bug 前预检；不适用：纯闲聊。"}))
        assert "已毕业" in out2, "带边界二次 confirm 应毕业，实际: " + out2[:200]
        conn = g._connect()
        row = conn.execute(
            "SELECT applicability FROM graduated_knowledge WHERE id = ?", (kid,)).fetchone()
        conn.close()
        assert row is not None and "预检" in (row["applicability"] or ""), (
            "边界应被写入，实际 %r" % (row["applicability"] if row else None))
