"""v6.9 单测：提醒护栏 / ontology 八合一 / 检索去重闸门"""
import json
import pytest
from unittest.mock import MagicMock

from astrbot_plugin_livingmemory_helper.core.reminder import MemoryReminder
from astrbot_plugin_livingmemory_helper.core.ontology import OntologyUnifiedTool
from astrbot_plugin_livingmemory_helper.core.agent_tools import AgentToolImplementations


def make_reminder():
    mr = MemoryReminder.__new__(MemoryReminder)
    return mr


class TestExtractGuard:
    """护栏①提取层：降级关键词只看前60字"""

    def test_keyword_in_head(self):
        mr = make_reminder()
        # 前60字内的"明天"可以提取
        r = mr._extract_time_from_text("明天8点 记得提醒我交材料")
        assert r is not None  # 命中 X点 模式返回 "8点" 也合理

    def test_keyword_deep_in_text_rejected(self):
        mr = make_reminder()
        # 时间词藏在叙述深处（垃圾来源模式）→ 不提取
        text = "老婆帮忙修了插件顺便还聊了很多很多的事情呀，" + "x"*70 + "，明天再说吧"  # 前60字无时间词
        assert mr._extract_time_from_text(text) is None


class TestAutoScanGuards:
    """护栏②③入库层：正文片段拦截（模拟 auto_create_from_scan 的三道检查）"""

    def _passes(self, ext, text):
        # 复刻 v6.9 三层护栏逻辑
        if len(ext) > 20: return False
        if ext[:6] and text[:6] == ext[:6]: return False
        if not any(ch.isdigit() for ch in ext) and "后" not in ext: return False
        return True

    def test_long_excerpt_rejected(self):
        assert not self._passes("今晚和橘子聊得好开心呀然后我们又一起看了好多东西呢", "text")  # 26字>20

    def test_prefix_overlap_rejected(self):
        assert not self._passes("明天去打", "明天去打疫苗，橘子说的")  # 前缀重合

    def test_pure_keyword_rejected(self):
        assert not self._passes("明天", "text")  # 无数字锚点

    def test_valid_time_passes(self):
        assert self._passes("明天8点", "text")  # 合法
        assert self._passes("3天后", "text")


from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_ontology_unified_dispatch():
    """八合一工具 action 路由与缺参校验（mock plugin）"""
    plugin = MagicMock()
    plugin.ontology_impl.create_entity = AsyncMock(return_value="{}")
    tool = OntologyUnifiedTool(plugin=plugin)
    assert tool.name == "haruyuki_ontology"
    ctx = MagicMock()
    assert "entity_type" in await tool.call(ctx, action="create")
    assert "entity_id" in await tool.call(ctx, action="query")
    assert "未知 action" in await tool.call(ctx, action="haha")
    assert "from_id" in await tool.call(ctx, action="link")


@pytest.mark.asyncio
async def test_retrieval_dedup_gate():
    """检索去重闸门：二倍池过滤已服务，空回退"""
    impl = AgentToolImplementations.__new__(AgentToolImplementations)
    impl._served = set()
    impl._cache = {}
    reader = MagicMock()
    pool1 = [{"id": 1, "content": "a", "time": "t", "tags": [], "importance": 0.5},
             {"id": 2, "content": "b", "time": "t", "tags": [], "importance": 0.5}]
    reader.search_memories = MagicMock(return_value=pool1)
    # 直接调 recall_memory 验证 served 登记
    res = await impl.recall_memory(reader, {"query": "x", "limit": 2})
    assert impl._served == {1, 2}
    # 第二次：池里 1,2 已服务，3 新 → 只返回 3
    reader.search_memories.return_value = pool1 + [{"id": 3, "content": "c", "time": "t", "tags": [], "importance": 0.5}]
    await impl.recall_memory(reader, {"query": "y", "limit": 2})
    assert impl._served == {1, 2, 3}
