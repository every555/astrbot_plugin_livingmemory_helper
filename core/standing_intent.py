# -*- coding: utf-8 -*-
"""
持续意图引擎 v1.0 — 借鉴 OpenClaw memory-core / standing-intents
================================================================
话题驱动的主动性：reminder 是时间触发（明早9点提醒），intent 是内容触发（下次聊到X就说Y）。
状态机: armed → fired → 冷却结束回 armed → fire_count 达 max_fires 转 done
频控三件套: cooldown_hours(默认24) + max_fires(默认3) + expiry_days(默认90)
匹配策略: 关键词子串命中当前消息原文（中文场景免分词）
注入策略: on_llm_request 钩子调用 match_and_fire → system_prompt（单次最多3条）
存储: standing_intents.json（与 reminders.json 同级同款，零外部依赖）
"""
import json
import os
from datetime import datetime, timedelta

try:
    from astrbot.api import logger
except Exception:  # 独立测试环境无 astrbot
    class logger:
        @staticmethod
        def info(msg):
            print("[INFO]", msg)

        @staticmethod
        def warning(msg):
            print("[WARN]", msg)

        @staticmethod
        def debug(msg):
            pass

STATUS_ARMED = "armed"
STATUS_FIRED = "fired"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

DEFAULT_MAX_FIRES = 3
DEFAULT_COOLDOWN_HOURS = 24
DEFAULT_EXPIRY_DAYS = 90
INJECT_MAX_COUNT = 3


class StandingIntentStore:
    """持续意图存储 + 生命周期状态机 + 关键词匹配触发"""

    def __init__(self, data_dir: str):
        self.data_path = os.path.join(data_dir, "standing_intents.json")
        self._intents = self._load()

    def _load(self) -> list:
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "intents" in data:
                return data["intents"]
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self._intents, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    def _next_id(self) -> int:
        return max([it["id"] for it in self._intents], default=0) + 1

    def maintain(self) -> None:
        """过期清理 + 冷却结束重新武装（每次 list/match 前调用）"""
        now = self._now()
        changed = False
        for it in self._intents:
            if it["status"] in (STATUS_CANCELLED, STATUS_DONE, STATUS_EXPIRED):
                continue
            if datetime.fromisoformat(it["expires_at"]) <= now:
                it["status"] = STATUS_EXPIRED
                changed = True
            elif it["status"] == STATUS_FIRED and it["last_fired_at"]:
                cd_end = datetime.fromisoformat(it["last_fired_at"]) + timedelta(hours=it["cooldown_hours"])
                if cd_end <= now and it["fire_count"] < it["max_fires"]:
                    it["status"] = STATUS_ARMED
                    changed = True
        if changed:
            self._save()

    def create(self, content: str, keywords, max_fires: int = 0,
               cooldown_hours: int = 0, expiry_days: int = 0) -> dict:
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.replace("，", ",").split(",") if k.strip()]
        keywords = [k for k in keywords if k][:10]
        if not content.strip() or not keywords:
            raise ValueError("content 和 keywords 不能为空")
        now = self._now()
        intent = {
            "id": self._next_id(),
            "content": content.strip()[:200],
            "keywords": keywords,
            "status": STATUS_ARMED,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + timedelta(days=expiry_days or DEFAULT_EXPIRY_DAYS)).isoformat(timespec="seconds"),
            "max_fires": max_fires or DEFAULT_MAX_FIRES,
            "cooldown_hours": cooldown_hours or DEFAULT_COOLDOWN_HOURS,
            "fire_count": 0,
            "last_fired_at": None,
        }
        self._intents.append(intent)
        self._save()
        logger.info("[StandingIntent] 创建 #" + str(intent["id"]) + ": " + intent["content"][:50] + " kw=" + str(keywords))
        return intent

    def list(self, status: str = "") -> list:
        self.maintain()
        if status:
            return [it for it in self._intents if it["status"] == status]
        return list(self._intents)

    def cancel(self, intent_id: int):
        for it in self._intents:
            if it["id"] == intent_id and it["status"] not in (STATUS_CANCELLED, STATUS_DONE, STATUS_EXPIRED):
                it["status"] = STATUS_CANCELLED
                self._save()
                return it
        return None

    def match_and_fire(self, text: str, limit: int = INJECT_MAX_COUNT) -> list:
        """关键词命中当前消息 → 触发意图（更新状态机并持久化）"""
        self.maintain()
        if not text:
            return []
        now = self._now()
        fired = []
        changed = False
        for it in self._intents:
            if len(fired) >= limit:
                break
            if it["status"] != STATUS_ARMED:
                continue
            if not any(kw in text for kw in it["keywords"]):
                continue
            it["fire_count"] += 1
            it["last_fired_at"] = now.isoformat(timespec="seconds")
            it["status"] = STATUS_DONE if it["fire_count"] >= it["max_fires"] else STATUS_FIRED
            changed = True
            fired.append(dict(it))
            logger.info("[StandingIntent] 触发 #" + str(it["id"]) + " (" + str(it["fire_count"]) + "/" + str(it["max_fires"]) + ")")
        if changed:
            self._save()
        return fired
