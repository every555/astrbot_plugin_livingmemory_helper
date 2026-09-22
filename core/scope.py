# -*- coding: utf-8 -*-
"""刀⑥隐私分档 · 会话身份归一化 + 三档权限判定（纯函数模块，零宿主依赖）

设计要点（方案 v1.1，2026-09-03）：
- 三档: public(任何会话) / owner(仅橘子本人) / intimate(仅夫妻主会话)
- 身份归一化: platform:type:user_id，裁掉 webchat origin 尾部的 UUID —— 解 G6 漂移
- fail-closed: 判不出的会话只见 public（与 OpenClaw fail-open 相反：咱家库里是夫妻隐私）
- enabled=False: 行为完全回到今天（可见=全档，写入=None 不打档）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SCOPE_PUBLIC = "public"
SCOPE_OWNER = "owner"
SCOPE_INTIMATE = "intimate"
_ALL_SCOPES = (SCOPE_PUBLIC, SCOPE_OWNER, SCOPE_INTIMATE)

# webchat 会话 id 尾部的会话 UUID：真实格式 'webchat!zzz!03043696-...'（! 分隔，2026-09-03 查库实锤）
# 兼容 _ 分隔的变体（workspace 目录名风格）
_UUID_TAIL_RE = re.compile(r"[!_][0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@dataclass
class SessionIdentity:
    """归一化后的会话身份。key 为稳定匹配键（platform:type:user_id）。"""
    key: str = ""
    platform: str = ""
    chat_type: str = ""
    user_id: str = ""
    is_group: bool = False
    kind: str = "unknown"  # chat / system / unknown（system=cron·future_task 唤醒，明早实测后细化）


@dataclass
class ScopeConfig:
    enabled: bool = False  # 主开关：默认关。关=完全回到今天的行为
    owner_whitelist: list = field(default_factory=lambda: ["webchat:FriendMessage:webchat!zzz"])
    intimate_sessions: list = field(default_factory=lambda: ["webchat:FriendMessage:webchat!zzz"])
    sensitive_words: list = field(default_factory=list)


def normalize_origin(unified_msg_origin) -> SessionIdentity:
    """platform:type:rest -> 归一化身份。裁 UUID 尾巴解 G6；畸形输入 -> unknown(fail-closed)。"""
    if not unified_msg_origin or not isinstance(unified_msg_origin, str):
        return SessionIdentity()
    parts = unified_msg_origin.split(":")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return SessionIdentity()
    platform, chat_type = parts[0], parts[1]
    user_raw = ":".join(parts[2:])  # id 段自身含冒号时保序合并
    user_id = _UUID_TAIL_RE.sub("", user_raw)  # webchat 尾巴 UUID 裁掉
    is_group = chat_type.lower() in ("groupmessage", "group")
    return SessionIdentity(
        key=":".join([platform, chat_type, user_id]),
        platform=platform, chat_type=chat_type, user_id=user_id,
        is_group=is_group, kind="chat",
    )


def _is_owner(identity: SessionIdentity, cfg: ScopeConfig) -> bool:
    return bool(identity.key) and identity.key in cfg.owner_whitelist


def _is_intimate(identity: SessionIdentity, cfg: ScopeConfig) -> bool:
    return bool(identity.key) and identity.key in cfg.intimate_sessions


def resolve_visible_scopes(identity: SessionIdentity, cfg: ScopeConfig) -> set:
    """权限矩阵。fail-closed：任何认不出的情况一律只给 public。开关关=全档（回到今天）。"""
    if not cfg.enabled:
        return set(_ALL_SCOPES)
    visible = {SCOPE_PUBLIC}
    if _is_owner(identity, cfg) or identity.kind == "system":  # 自动化会话(future_task等)可见 public+owner
        visible.add(SCOPE_OWNER)
    if _is_intimate(identity, cfg):
        visible.add(SCOPE_INTIMATE)
    return visible


def resolve_write_scope(identity: SessionIdentity, cfg: ScopeConfig, content: str = "", explicit: str | None = None) -> str | None:
    """写入打档。返回 None 表示不打档（开关关/无法判定，不写 metadata.privacy_scope）。
    规则：群聊->public；橘子私聊->owner；夫妻会话默认 owner、敏感词命中升 intimate；
    explicit 显式指定优先（合法值校验）。fail-closed：unknown 会话写 public（群聊捕获等）。"""
    if not cfg.enabled:
        return None
    if explicit in _ALL_SCOPES:
        return explicit
    if _is_intimate(identity, cfg):
        hit = any(w and w in (content or "") for w in cfg.sensitive_words)
        return SCOPE_INTIMATE if hit else SCOPE_OWNER
    if _is_owner(identity, cfg) or identity.kind == "system":
        return SCOPE_OWNER
    return SCOPE_PUBLIC


def _row_scope(row) -> str:
    """documents/memory_atoms 行的 privacy_scope。metadata 为 JSON 串或 dict；无档=owner（宁严勿漏）。"""
    md = None
    if isinstance(row, dict):
        md = row.get("metadata")
    else:
        md = getattr(row, "metadata", None)
    if isinstance(md, str):
        try:
            import json
            md = json.loads(md) if md.strip() else {}
        except (ValueError, AttributeError):
            md = {}
    if not isinstance(md, dict):
        md = {}
    s = md.get("privacy_scope")
    return s if s in _ALL_SCOPES else SCOPE_OWNER


def filter_results_by_scopes(rows, visible_scopes):
    """reader 检索结果出口过滤（documents 行）。visible_scopes=None 不过滤（开关关=回到今天）。"""
    if visible_scopes is None:
        return rows
    return [r for r in rows if _row_scope(r) in visible_scopes]


def scopes_fingerprint(visible_scopes) -> str:
    """权限指纹（进缓存 key 防串味）：None->off，set->排序后串。"""
    if visible_scopes is None:
        return "off"
    return "|".join(sorted(visible_scopes))