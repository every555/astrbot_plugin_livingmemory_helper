# -*- coding: utf-8 -*-
"""持续意图引擎单测 — 状态机/频控/持久化"""
from datetime import datetime, timedelta

from core.standing_intent import (
    StandingIntentStore,
    STATUS_ARMED, STATUS_FIRED, STATUS_DONE, STATUS_CANCELLED, STATUS_EXPIRED,
)


def _mk(tmp_path):
    return StandingIntentStore(str(tmp_path))


def test_create_defaults(tmp_path):
    s = _mk(tmp_path)
    it = s.create("补单词", "单词,英语")
    assert it["status"] == STATUS_ARMED
    assert it["max_fires"] == 3 and it["cooldown_hours"] == 24
    assert it["keywords"] == ["单词", "英语"]


def test_match_fire_and_cooldown(tmp_path):
    s = _mk(tmp_path)
    s.create("补单词", "单词")
    fired = s.match_and_fire("该背单词了")
    assert len(fired) == 1 and fired[0]["status"] == STATUS_FIRED
    assert s.match_and_fire("又是单词") == []
    assert s.list(STATUS_FIRED) and not s.list(STATUS_ARMED)


def test_max_fires_to_done(tmp_path):
    s = _mk(tmp_path)
    s.create("带伞", "下雨", max_fires=1)
    fired = s.match_and_fire("明天下雨")
    assert fired and fired[0]["status"] == STATUS_DONE
    assert s.match_and_fire("下雨天") == []


def test_cancel(tmp_path):
    s = _mk(tmp_path)
    it = s.create("x", "y")
    assert s.cancel(it["id"])["status"] == STATUS_CANCELLED
    assert s.cancel(it["id"]) is None
    assert s.match_and_fire("yyy") == []


def test_expiry(tmp_path):
    s = _mk(tmp_path)
    s.create("旧意图", "旧")
    s._intents[0]["expires_at"] = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    assert s.list(STATUS_EXPIRED) and not s.list(STATUS_ARMED)
    assert s.match_and_fire("旧") == []


def test_cooldown_rearm(tmp_path):
    s = _mk(tmp_path)
    s.create("补单词", "单词")
    s.match_and_fire("单词")
    s._intents[0]["last_fired_at"] = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
    s._intents[0]["status"] = STATUS_FIRED
    fired = s.match_and_fire("单词")
    assert len(fired) == 1 and fired[0]["fire_count"] == 2


def test_persistence(tmp_path):
    s = _mk(tmp_path)
    s.create("持久", "存档")
    s.match_and_fire("存档一下")
    s2 = StandingIntentStore(str(tmp_path))
    assert len(s2.list()) == 1 and s2.list()[0]["fire_count"] == 1
