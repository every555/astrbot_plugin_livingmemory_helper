"""v2.1 家庭协作事件桥（helper 侧）。

职责：
- publish_family_event: 向 livingmemory 的 EventBus 发布家庭协作事件（try/except 降级，绝不炸）
- register_family_subscribers: 注册 helper 侧订阅者
    A6 预言到期 → 创建回访提醒（reminder.create）
    A8 冲突确认 → 沉淀知识候选（knowledge.propose_candidate）
    A9 教训记录 → 沉淀知识候选（LESSON_ADDED 事件）

设计原则：家人之间"说一声"不直接命令；任何一步失败不影响主流程。
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger("family_bus")

_HAS_BUS = False
_bus = None
_MemoryEvent = None
_MemoryEventType = None

_IMPORT_PATHS = [
    # AstrBot 运行时真实模块路径（star_manager 用 data.plugins.<name> 加载插件）
    "data.plugins.astrbot_plugin_livingmemory.core.events.event_bus",
    # 独立测试/开发环境（插件目录加进 sys.path 时）
    "astrbot_plugin_livingmemory.core.events.event_bus",
]


def _try_import_bus():
    """按优先级尝试导入 livingmemory 的事件总线，返回 (bus, MemoryEvent, MemoryEventType) 或 None。"""
    for mod_path in _IMPORT_PATHS:
        try:
            mod = __import__(mod_path, fromlist=["MemoryEvent", "MemoryEventType", "get_event_bus"])
            return mod.get_event_bus(), mod.MemoryEvent, mod.MemoryEventType
        except Exception:
            continue
    return None


_bus_imported = _try_import_bus()
if _bus_imported is not None:
    _bus, _MemoryEvent, _MemoryEventType = _bus_imported
    _HAS_BUS = True
else:
    _bus = None
    _MemoryEvent = None
    _MemoryEventType = None
    _HAS_BUS = False
    logger.warning(
        "[FamilyBus] livingmemory 事件总线不可用（降级为无操作）: "
        "两种导入路径均失败（data.plugins.astrbot_plugin_livingmemory / astrbot_plugin_livingmemory）"
    )


def publish_family_event(event_type_value: str, memory_id: int = 0, metadata: dict | None = None) -> bool:
    """发布家庭协作事件（fire-and-forget，失败仅告警）。"""
    if not _HAS_BUS or _bus is None or _MemoryEvent is None or _MemoryEventType is None:
        return False
    try:
        et = _MemoryEventType(event_type_value)
        _bus.publish_nowait(
            _MemoryEvent(type=et, memory_id=memory_id, metadata=metadata or {})
        )
        return True
    except Exception:
        logger.warning(f"[FamilyBus] 发布 {event_type_value} 失败", exc_info=True)
        return False


def register_family_subscribers(plugin) -> bool:
    """注册 helper 侧订阅者（A6/A8/A9）。plugin 需有 .reminder 和 .knowledge_graduator。"""
    if not _HAS_BUS or _bus is None or _MemoryEventType is None:
        logger.warning("[FamilyBus] 总线不可用，跳过订阅注册")
        return False

    # ── A6：预言到期 → 创建回访验证提醒 ──
    async def on_prophecy_expired(event) -> None:
        try:
            meta = event.metadata or {}
            content = str(meta.get("content") or "预言")
            target = (datetime.now() + timedelta(hours=1)).isoformat()
            r = plugin.reminder.create(
                f"预言到期待回访验证：{content[:80]}",
                target,
                source="prophecy_expired",
                memory_id=int(event.memory_id) if event.memory_id else None,
            )
            logger.info(f"[FamilyBus] A6 预言→提醒 已创建 #{r.get('id')}")
        except BaseException:
            logger.warning("[FamilyBus] A6 预言→提醒失败", exc_info=True)

    on_prophecy_expired._family_id = "hl_sub_a6_prophecy_remind"  # 热重载去重

    # ── A8：冲突确认 → 沉淀为知识候选 ──
    async def on_conflict_confirmed(event) -> None:
        try:
            meta = event.metadata or {}
            reason = str(meta.get("reason") or "")
            rtype = str(meta.get("resolution_type") or "未知")
            title = f"记忆冲突确认（#{event.memory_id}）"
            conclusion = f"记忆冲突已确认为「{rtype}」" + (f"：{reason[:60]}" if reason else "")
            plugin.knowledge_graduator.propose_candidate(
                title=title,
                conclusion=conclusion,
                background="家庭反馈回路 A8：冲突确认自动沉淀为知识候选",
                source_type="insight",
                source_id=int(event.memory_id) if event.memory_id else 0,
                knowledge_type="relationship",
                tags=["冲突", "家庭反馈"],
                importance=0.7,
            )
            logger.info(f"[FamilyBus] A8 冲突→知识候选 #{event.memory_id}")
        except BaseException:
            logger.warning("[FamilyBus] A8 冲突→知识失败", exc_info=True)

    on_conflict_confirmed._family_id = "hl_sub_a8_conflict_knowledge"  # 热重载去重

    # ── A9：教训记录 → 沉淀为知识候选 ──
    async def on_lesson_added(event) -> None:
        try:
            meta = event.metadata or {}
            content = str(meta.get("content") or "")
            category = str(meta.get("category") or "lesson")
            if not content:
                return
            plugin.knowledge_graduator.propose_candidate(
                title=f"教训沉淀：{content[:24]}",
                conclusion=content[:120],
                background="家庭反馈回路 A9：error_learner 教训自动沉淀为知识候选",
                source_type="lesson",
                source_id=int(event.memory_id) if event.memory_id else 0,
                knowledge_type="technical",
                tags=["教训", "家庭反馈", category],
                importance=0.65,
            )
            logger.info(f"[FamilyBus] A9 教训→知识候选 #{event.memory_id}")
        except BaseException:
            logger.warning("[FamilyBus] A9 教训→知识失败", exc_info=True)

    on_lesson_added._family_id = "hl_sub_a9_lesson_knowledge"  # 热重载去重

    _bus.subscribe(_MemoryEventType.PROPHECY_EXPIRED, on_prophecy_expired)
    _bus.subscribe(_MemoryEventType.CONFLICT_CONFIRMED, on_conflict_confirmed)
    _bus.subscribe(_MemoryEventType.LESSON_ADDED, on_lesson_added)
    logger.info("[FamilyBus] 已注册订阅者: A6 预言→提醒 / A8 冲突→知识 / A9 教训→知识")
    return True
