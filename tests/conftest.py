# -*- coding: utf-8 -*-
"""helper 测试公共配置：把插件根目录 + plugins 目录注入 sys.path，使包可导入。"""
import os
import sys

_PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_PLUGINS_DIR = os.path.join(_PROJECT_ROOT, "..")

for p in (_PROJECT_ROOT, _PLUGINS_DIR):
    p = os.path.abspath(p)
    if p not in sys.path:
        sys.path.insert(0, p)

# ── v6.9: 无 astrbot 宿主环境时的模块 stub（单测用）──
import types
_log = types.SimpleNamespace(info=print, warning=print, error=print, debug=print)
if 'astrbot' not in sys.modules:
    _ns = lambda **kw: types.SimpleNamespace(**kw)
    astrbot = types.ModuleType('astrbot')
    api = types.ModuleType('astrbot.api'); api.logger = _log
    api_event = types.ModuleType('astrbot.api.event')
    api_star = types.ModuleType('astrbot.api.star')
    api_filter = types.ModuleType('astrbot.api.event.filter')
    core_agent = types.ModuleType('astrbot.core.agent.tool')
    run_ctx = types.ModuleType('astrbot.core.agent.run_context')
    astr_ctx = types.ModuleType('astrbot.core.astr_agent_context')
    class _FT:
        def __class_getitem__(cls, item): return cls
    core_agent.FunctionTool = _FT
    core_agent.ToolExecResult = object
    api.AstrBotConfig = dict
    api_event.AstrMessageEvent = object
    api_star.Context = object
    api_filter.llm_tool = lambda *a, **k: (lambda f: f)
    run_ctx.ContextWrapper = object
    astr_ctx.AstrAgentContext = object
    for name, mod in [('astrbot', astrbot), ('astrbot.api', api), ('astrbot.api.event', api_event),
                      ('astrbot.api.star', api_star), ('astrbot.api.event.filter', api_filter),
                      ('astrbot.core.agent.tool', core_agent), ('astrbot.core.agent.run_context', run_ctx),
                      ('astrbot.core.astr_agent_context', astr_ctx)]:
        sys.modules[name] = mod