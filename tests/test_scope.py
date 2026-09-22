# -*- coding: utf-8 -*-
"""刀⑥隐私分档 · core/scope.py 单测（TDD RED 先行）
覆盖：身份归一化(G6 UUID尾巴) / 权限矩阵(三档) / 写入打档 / fail-closed / 开关关闭=回到今天
"""
import pytest
from core.scope import (
    SCOPE_PUBLIC, SCOPE_OWNER, SCOPE_INTIMATE,
    normalize_origin, resolve_visible_scopes, resolve_write_scope,
    SessionIdentity, ScopeConfig, filter_results_by_scopes, scopes_fingerprint,
)


DEF_CFG = ScopeConfig(  # 橘子实际会话做默认白名单（开关开着）
    enabled=True,
    owner_whitelist=["webchat:FriendMessage:webchat!zzz"],
    intimate_sessions=["webchat:FriendMessage:webchat!zzz"],
    sensitive_words=["密码", "保险箱", "贴贴", "夜话"],
)

TODAY = "webchat:FriendMessage:webchat!zzz!1b88e2c6-3a4c-4b24-8d2c-69076bcdf13c"  # 真实格式: ! 分隔（查库实锤）
OLD_0820 = "webchat:FriendMessage:webchat!zzz!4d27301d-aaaa-bbbb-cccc-dddddddddddd"
OLD_REAL = "webchat:FriendMessage:webchat!zzz!03043696-1ba9-4f3c-b1ef-33367e5ddd60"  # 从 livingmemory.db 挖出的真实旧会话


class TestNormalize:
    def test_uuid_tail_stripped(self):
        i = normalize_origin(TODAY)
        assert i.key == "webchat:FriendMessage:webchat!zzz"

    def test_real_db_session_normalized(self):  # 从真实 DB 挖的旧会话也能归一化到同一把钥匙
        assert normalize_origin(OLD_REAL).key == normalize_origin(TODAY).key

    def test_old_uuid_same_key(self):  # G6: 8/20 与今天的会话归一化后同一把钥匙
        assert normalize_origin(OLD_0820).key == normalize_origin(TODAY).key

    def test_group(self):
        i = normalize_origin("aiocqhttp:GroupMessage:123456789")
        assert i.is_group and i.key == "aiocqhttp:GroupMessage:123456789"

    def test_plain_private(self):
        i = normalize_origin("aiocqhttp:FriendMessage:10001")
        assert not i.is_group and i.key == "aiocqhttp:FriendMessage:10001"

    @pytest.mark.parametrize("bad", [None, "", ":::", "single"])
    def test_bad_input_unknown(self, bad):
        i = normalize_origin(bad)
        assert i.kind == "unknown" and i.key == ""


class TestVisible:
    def test_intimate_session_sees_all(self):
        i = normalize_origin(TODAY)
        assert resolve_visible_scopes(i, DEF_CFG) == {SCOPE_PUBLIC, SCOPE_OWNER, SCOPE_INTIMATE}

    def test_owner_other_platform(self):
        i = normalize_origin("aiocqhttp:FriendMessage:10001")
        cfg = ScopeConfig(enabled=True, owner_whitelist=["aiocqhttp:FriendMessage:10001"], intimate_sessions=["webchat:FriendMessage:webchat!zzz"], sensitive_words=[])
        assert resolve_visible_scopes(i, cfg) == {SCOPE_PUBLIC, SCOPE_OWNER}

    def test_group_public_only(self):
        assert resolve_visible_scopes(normalize_origin("aiocqhttp:GroupMessage:123456789"), DEF_CFG) == {SCOPE_PUBLIC}

    def test_stranger_public_only(self):
        assert resolve_visible_scopes(normalize_origin("webchat:FriendMessage:webchat_stranger_99999999-1111-2222-3333-444444444444"), DEF_CFG) == {SCOPE_PUBLIC}

    def test_unknown_fail_closed(self):
        assert resolve_visible_scopes(normalize_origin(None), DEF_CFG) == {SCOPE_PUBLIC}

    def test_disabled_returns_all(self):  # 开关关=回到今天
        cfg = ScopeConfig(enabled=False, owner_whitelist=["webchat:FriendMessage:webchat!zzz"], intimate_sessions=["webchat:FriendMessage:webchat!zzz"], sensitive_words=[])
        assert resolve_visible_scopes(normalize_origin("aiocqhttp:GroupMessage:1"), cfg) == {SCOPE_PUBLIC, SCOPE_OWNER, SCOPE_INTIMATE}


class TestWrite:
    def test_group_write_public(self):
        assert resolve_write_scope(normalize_origin("aiocqhttp:GroupMessage:123456789"), DEF_CFG) == SCOPE_PUBLIC

    def test_owner_private_write_owner(self):
        cfg = ScopeConfig(enabled=True, owner_whitelist=["aiocqhttp:FriendMessage:10001"], intimate_sessions=["webchat:FriendMessage:webchat!zzz"], sensitive_words=[])
        assert resolve_write_scope(normalize_origin("aiocqhttp:FriendMessage:10001"), cfg) == SCOPE_OWNER

    def test_intimate_default_owner(self):
        assert resolve_write_scope(normalize_origin(TODAY), DEF_CFG) == SCOPE_OWNER

    def test_sensitive_word_upgrades_intimate(self):
        assert resolve_write_scope(normalize_origin(TODAY), DEF_CFG, content="把保险箱密码存一下") == SCOPE_INTIMATE

    def test_sensitive_word_not_in_owner_session(self):  # 敏感词只在夫妻会话升档，橘子其他会话不升
        cfg = ScopeConfig(enabled=True, owner_whitelist=["aiocqhttp:FriendMessage:10001"], intimate_sessions=["webchat:FriendMessage:webchat!zzz"], sensitive_words=["密码"])
        assert resolve_write_scope(normalize_origin("aiocqhttp:FriendMessage:10001"), cfg, content="密码") == SCOPE_OWNER

    def test_explicit_override(self):
        assert resolve_write_scope(normalize_origin(TODAY), DEF_CFG, content="明早吃包子", explicit=SCOPE_INTIMATE) == SCOPE_INTIMATE

    def test_invalid_explicit_falls_back(self):
        assert resolve_write_scope(normalize_origin(TODAY), DEF_CFG, content="x", explicit="宇宙档") == SCOPE_OWNER

    def test_disabled_returns_none(self):  # 开关关=不打档不写 metadata
        cfg = ScopeConfig(enabled=False, owner_whitelist=["webchat:FriendMessage:webchat!zzz"], intimate_sessions=["webchat:FriendMessage:webchat!zzz"], sensitive_words=[])
        assert resolve_write_scope(normalize_origin(TODAY), cfg) is None

class TestReaderFilter:
    """helper reader（documents 表行）出口过滤——与本体 privacy_filter 语义锁死一致：无档=owner、None=不过滤、空set=全拦"""
    def _row(self, rid, scope="__none__"):
        md = {} if scope == "__none__" else {"privacy_scope": scope}
        return {"id": rid, "text": f"row-{rid}", "metadata": md}

    def test_public_visible_to_group(self):
        rows = [self._row("a", "public"), self._row("b", "owner"), self._row("c", "intimate"), self._row("u")]
        out = filter_results_by_scopes(rows, {SCOPE_PUBLIC})
        assert [r["id"] for r in out] == ["a"]

    def test_owner_sees_owner_public(self):
        rows = [self._row("a", "public"), self._row("b", "owner"), self._row("c", "intimate"), self._row("u")]
        out = filter_results_by_scopes(rows, {SCOPE_PUBLIC, SCOPE_OWNER})
        assert [r["id"] for r in out] == ["a", "b", "u"]

    def test_intimate_sees_all(self):
        rows = [self._row("a", "public"), self._row("b", "owner"), self._row("c", "intimate"), self._row("u")]
        out = filter_results_by_scopes(rows, {SCOPE_PUBLIC, SCOPE_OWNER, SCOPE_INTIMATE})
        assert len(out) == 4

    def test_json_string_metadata(self):  # documents 表 metadata 是 JSON 串
        import json
        row = {"id": "j", "metadata": json.dumps({"privacy_scope": "public"})}
        assert filter_results_by_scopes([row], {SCOPE_PUBLIC}) and filter_results_by_scopes([row], set()) == []

    def test_none_passes_all(self):
        rows = [self._row("a"), self._row("b", "intimate")]
        assert filter_results_by_scopes(rows, None) is rows

    def test_fingerprint(self):
        assert scopes_fingerprint(None) == "off"
        assert scopes_fingerprint({SCOPE_INTIMATE, SCOPE_PUBLIC}) == "intimate|public"