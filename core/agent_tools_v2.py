# -*- coding: utf-8 -*-
"""记忆生态系统 v2.0 对外查询工具（家庭协作版 5 工具）。

让 LLM（老婆）能在对话中主动查看 v2 数据：
- haruyuki_causal_chain   因果证据链追溯
- haruyuki_conflict_check 记忆冲突记录
- haruyuki_profile        记忆画像
- haruyuki_prophecy       记忆预言
- haruyuki_expression     当前表达风格

设计：只读查询，工具实现走 plugin._tool_* 方法（与现有 8 工具一致）。
"""
from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext


@pydantic_dataclass
class HaruyukiCausalChainTool(FunctionTool[AstrAgentContext]):
    """追溯记忆的因果证据链。"""

    plugin: Any = None
    name: str = "haruyuki_causal_chain"
    description: str = (
        "追溯某条记忆的因果证据链（前因/后果）。当橘子问「这条记忆从哪来的」"
        "「为什么会想起这个」「这件事导致了什么」时调用。支持按记忆ID或关键词定位。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "关键词或记忆ID，如「樱花」或 42",
                },
                "direction": {
                    "type": "string",
                    "description": "遍历方向: both(双向)/cause(前因)/effect(后果)",
                    "default": "both",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "最大遍历深度，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_causal_chain(kwargs)


@pydantic_dataclass
class HaruyukiConflictCheckTool(FunctionTool[AstrAgentContext]):
    """查看记忆冲突记录。"""

    plugin: Any = None
    name: str = "haruyuki_conflict_check"
    description: str = (
        "查看记忆冲突检测记录（新记忆与旧记忆矛盾的检测结果）。"
        "当橘子问「我有没有说过矛盾的话」「记忆有没有冲突」「帮我检查记忆一致性」时调用。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "过滤状态: candidate(待确认)/confirmed(已确认)/resolved(已解决)，留空查全部",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 20",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_conflict_check(kwargs)


@pydantic_dataclass
class HaruyukiProfileTool(FunctionTool[AstrAgentContext]):
    """查看记忆画像。"""

    plugin: Any = None
    name: str = "haruyuki_profile"
    description: str = (
        "查看记忆画像（从记忆中提炼的稳定特征，含置信度与证据链）。"
        "当橘子问「你了解我什么」「我的画像」「你觉得我是什么样的人」时调用。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "persona_id": {
                    "type": "string",
                    "description": "画像主体，默认 default（橘子）",
                    "default": "default",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回特征条数，默认 20",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_profile(kwargs)


@pydantic_dataclass
class HaruyukiProphecyTool(FunctionTool[AstrAgentContext]):
    """查看记忆预言。"""

    plugin: Any = None
    name: str = "haruyuki_prophecy"
    description: str = (
        "查看记忆预言（基于记忆规律生成的未来预测，到期自动回溯验证）。"
        "当橘子问「你有什么预言」「预言验证得怎么样」「我的规律预测」时调用。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "过滤状态: active(生效中)/verified(已验证)/failed(已失败)，留空查全部",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数，默认 20",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_prophecy(kwargs)


@pydantic_dataclass
class HaruyukiExpressionTool(FunctionTool[AstrAgentContext]):
    """查看当前表达风格。"""

    plugin: Any = None
    name: str = "haruyuki_expression"
    description: str = (
        "查看当前表达风格快照（记忆画像驱动的表达联动：亲密/温暖/俏皮度）。"
        "当橘子问「你现在是什么风格」「表达风格」「你了解自己的说话方式吗」时调用。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "persona_id": {
                    "type": "string",
                    "description": "画像主体，默认 default",
                    "default": "default",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_expression(kwargs)


# ══════════════════════════════════════════════════════
# v2.1 工具 6: 家庭反馈总览
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiFamilyStatusTool(FunctionTool[AstrAgentContext]):
    """查看家庭反馈回路状态（家人之间谁给谁说了什么）。"""

    plugin: Any = None
    name: str = "haruyuki_family_status"
    description: str = (
        "查看记忆家庭协作反馈回路的总览：各家人（模块）之间的互动次数、"
        "最近发生的反馈事件。当橘子问「家庭反馈」「家人互动」「反馈回路」「"
        "最近谁给谁说了什么」「家庭状态」时调用。"
        "返回可交互 HTML 面板和自然语言摘要。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "最近反馈事件条数，默认 20",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_family_status(kwargs)


# ══════════════════════════════════════════════════════
# v2.1 工具 7: 家庭例会（日报）
# ══════════════════════════════════════════════════════

@pydantic_dataclass
class HaruyukiFamilyMeetingTool(FunctionTool[AstrAgentContext]):
    """查看/生成家庭例会日报（全家今日动态 + 第一议题归档审批）。"""

    plugin: Any = None
    name: str = "haruyuki_family_meeting"
    description: str = (
        "查看或生成家庭例会日报：汇总全家今日动态（画像更新、预言验证、冲突裁定、"
        "因果链、表达进化、归档动作、反馈互动），第一议题永远是归档候选审批。"
        "当橘子问「家庭例会」「今日日报」「今天全家干了啥」「例会」「日报」时调用。"
        "action=generate 生成当日日报；action=get 查看指定日期；action=list 列出最近日报。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "操作类型：generate(生成日报)/get(查看日报)/list(最近日报)/stats(台账)",
                    "default": "get",
                },
                "date": {
                    "type": "string",
                    "description": "日期 YYYY-MM-DD（get/generate 时使用，默认今天）",
                    "default": "",
                },
                "limit": {
                    "type": "integer",
                    "description": "list 条数，默认 7",
                    "default": 7,
                    "minimum": 1,
                    "maximum": 30,
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        return await self.plugin._tool_family_meeting(kwargs)
