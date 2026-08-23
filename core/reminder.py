# -*- coding: utf-8 -*-
"""
F4 - 记忆提醒联动 v2.0 (P3)
===================================
- 从记忆内容智能提取时间/事件，创建提醒
- 支持 Dashboard CRUD API
- LLM 钩子注入即将到期提醒到聊天上下文
- 定时扫描到期提醒
"""
import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional
from astrbot.api import logger


# ─── 时间关键词映射 ───
_TIME_KEYWORDS = {
    "明天": 1, "后天": 2, "大后天": 3,
    "下周": 7, "下下周": 14,
    "下个月": 30,
    "今晚": 0, "今天": 0, "今天晚上": 0,
    "早上": 0, "上午": 0, "中午": 0, "下午": 0, "晚上": 0,
    "一会儿": 0, "待会": 0, "等下": 0, "等一下": 0,
}

_HOUR_KEYWORDS = {
    "早上": 8, "上午": 9, "中午": 12, "下午": 14,
    "傍晚": 17, "晚上": 20, "今晚": 21, "深夜": 23,
}

# 含时间暗示的记忆关键词
_SCAN_KEYWORDS = [
    "%点%", "%分钟%", "%小时%", "%明天%", "%后天%", "%下周%",
    "%约定%", "%提醒%", "%记得%", "%别忘了%", "%截止%",
    "%ddl%", "%deadline%", "%日%", "%月%", "%报名%",
    "%考试%", "%面试%", "%出发%", "%到达%", "%开会%",
    "%提交%", "%交付%", "%上线%", "%发布%",
]


class MemoryReminder:
    def __init__(self, reader, data_dir: str):
        self.reader = reader
        self.data_path = os.path.join(data_dir, "reminders.json")
        self._reminders = self._load()

    # ─────────── 持久化 ───────────

    def _load(self) -> list:
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧格式 {"reminders": [...]}
            if isinstance(data, dict) and "reminders" in data:
                return data["reminders"]
            if isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def _save(self):
        os.makedirs(os.path.dirname(self.data_path) or ".", exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self._reminders, f, ensure_ascii=False, indent=2)

    # ─────────── CRUD API ───────────

    def create(self, content: str, target_time: str, source: str = "manual",
               memory_id: Optional[int] = None, priority: str = "normal") -> dict:
        """创建一个新提醒"""
        reminder = {
            "id": self._next_id(),
            "content": content[:200],
            "target_time": target_time,          # ISO 8601 字符串或自然语言
            "parsed_time": self._parse_natural_time(target_time),  # 解析后的 ISO
            "source": source,                     # manual / auto_scan / memory_extract
            "memory_id": memory_id,
            "priority": priority,                 # low / normal / high
            "done": False,
            "fired": False,                       # 是否已触发
            "created_at": datetime.now().isoformat(),
        }
        self._reminders.append(reminder)
        self._save()
        logger.info(f"[Reminder] 创建提醒 #{reminder['id']}: {content[:50]} → {target_time}")
        return reminder

    def create_from_memory(self, memory_id: int, target_time: str) -> str:
        """从记忆创建提醒（兼容旧接口）"""
        mem = self.reader.get_memory_by_id(memory_id)
        if not mem:
            return f"未找到 ID 为 {memory_id} 的记忆"
        content = mem.get("content", "")
        r = self.create(content[:200], target_time, source="memory_extract", memory_id=memory_id)
        return (
            f"⏰ 已创建提醒 #{r['id']}：\n"
            f"   内容：{content[:60]}...\n"
            f"   时间：{target_time}"
        )

    def list_reminders(self, include_done: bool = False) -> str:
        """列出提醒（文本格式，给命令用）"""
        items = self._reminders if include_done else [r for r in self._reminders if not r["done"]]
        if not items:
            return "当前没有待办的提醒～"
        lines = ["⏰ 记忆提醒列表：", ""]
        for r in items[-20:]:  # 最多显示 20 条
            status = "✅" if r["done"] else ("🔔" if r.get("fired") else "⏳")
            lines.append(
                f"  {status} #{r['id']} | {r['target_time']} | "
                f"{r['content'][:50]}"
            )
        return "\n".join(lines)

    def list_reminders_api(self, include_done: bool = False) -> list:
        """列出提醒（dict 格式，给 API 用）"""
        items = self._reminders if include_done else [r for r in self._reminders if not r["done"]]
        return items

    def cancel(self, reminder_id: int) -> str:
        for r in self._reminders:
            if r["id"] == reminder_id:
                r["done"] = True
                self._save()
                return f"已取消提醒 #{reminder_id}: {r['content'][:50]}"
        return f"未找到提醒 #{reminder_id}"

    def delete(self, reminder_id: int) -> str:
        before = len(self._reminders)
        self._reminders = [r for r in self._reminders if r["id"] != reminder_id]
        if len(self._reminders) < before:
            self._save()
            return f"已删除提醒 #{reminder_id}"
        return f"未找到提醒 #{reminder_id}"

    def get_upcoming(self, hours: int = 24) -> list:
        """获取未来 N 小时内即将到期的提醒"""
        now = datetime.now()
        cutoff = now + timedelta(hours=hours)
        upcoming = []
        for r in self._reminders:
            if r["done"] or r.get("fired"):
                continue
            parsed = r.get("parsed_time")
            if parsed:
                try:
                    t = datetime.fromisoformat(parsed)
                    if t.tzinfo is not None:  # v6.4.2 防御：aware→naive
                        t = t.astimezone().replace(tzinfo=None)
                    if now <= t <= cutoff:
                        r["_parsed_dt"] = t.isoformat()
                        upcoming.append(r)
                except Exception:
                    pass
        upcoming.sort(key=lambda x: x.get("_parsed_dt", ""))
        return upcoming

    def get_overdue(self) -> list:
        """获取已过期但未触发的提醒"""
        now = datetime.now()
        overdue = []
        for r in self._reminders:
            if r["done"] or r.get("fired"):
                continue
            parsed = r.get("parsed_time")
            if parsed:
                try:
                    t = datetime.fromisoformat(parsed)
                    if t.tzinfo is not None:  # v6.4.2 防御：aware→naive
                        t = t.astimezone().replace(tzinfo=None)
                    if t < now:
                        overdue.append(r)
                except Exception:
                    pass
        return overdue

    def mark_fired(self, reminder_id: int):
        for r in self._reminders:
            if r["id"] == reminder_id:
                r["fired"] = True
                self._save()
                return

    # ─────────── 智能扫描 ───────────

    def scan_time_keywords(self) -> list:
        """扫描记忆中的时间关键词，返回候选提醒"""
        conn = self.reader._connect()
        results = []
        seen_ids = set()

        for kw in _SCAN_KEYWORDS:
            rows = conn.execute(
                "SELECT id, text, metadata, created_at FROM documents "
                "WHERE text LIKE ? ORDER BY created_at DESC LIMIT 5",
                (kw,),
            ).fetchall()
            for r in rows:
                if r[0] in seen_ids:
                    continue
                seen_ids.add(r[0])
                # 尝试从内容中提取时间
                extracted_time = self._extract_time_from_text(r[1])
                if extracted_time:
                    results.append({
                        "id": r[0],
                        "text": r[1][:200],
                        "created_at": r[3],
                        "extracted_time": extracted_time,
                    })

        conn.close()
        return results

    def auto_create_from_scan(self) -> list:
        """自动扫描并创建提醒（去重）"""
        candidates = self.scan_time_keywords()
        existing_memory_ids = {r.get("memory_id") for r in self._reminders if r.get("memory_id")}
        created = []

        for c in candidates:
            if c["id"] in existing_memory_ids:
                continue
            parsed = self._parse_natural_time(c["extracted_time"])
            if not parsed:
                continue
            # v6.9 三层护栏：自动扫描的垃圾拦截（2026-08-20 清洗 86 条垃圾后的根治）
            ext = c.get("extracted_time", "")
            # ① 时间文本超20字=正文片段被误当日标
            if len(ext) > 20:
                continue
            # ② 时间文本与正文开头重合=解析失败的标志
            if ext[:6] and c.get("text", "")[:6] == ext[:6]:
                continue
            # ③ 纯关键词（今晚/明天）无数字锚点=信息量太弱，拒绝；必须有 X点/X日/X天后
            if not any(ch.isdigit() for ch in ext) and "后" not in ext:
                continue
            # 只创建未来的提醒
            try:
                t = datetime.fromisoformat(parsed)
                if t.tzinfo is not None:  # v6.4.2 防御：aware→naive
                    t = t.astimezone().replace(tzinfo=None)
                if t <= datetime.now():
                    continue
            except Exception:
                continue

            # 防止从旧记忆创建无效提醒：
            # 如果记忆创建于3天前以上，且解析出的时间距现在超过6个月，
            # 说明是历史日期被 +1 年后的误判，跳过
            try:
                mem_created = datetime.fromisoformat(c.get("created_at", "").replace("Z", "+00:00"))
                if mem_created.tzinfo is not None:  # v6.4.2 防御：aware→naive
                    mem_created = mem_created.astimezone().replace(tzinfo=None)
                mem_age = (datetime.now() - mem_created).days
                if mem_age > 3 and (t - datetime.now()).days > 180:
                    logger.debug(f"[Reminder] 跳过旧记忆 #{c['id']} (age={mem_age}d, parsed={parsed})")
                    continue
            except Exception:
                pass

            r = self.create(
                content=c["text"][:200],
                target_time=c["extracted_time"],
                source="auto_scan",
                memory_id=c["id"],
            )
            created.append(r)

        return created

    # ─────────── 时间解析 ───────────

    def _parse_natural_time(self, text: str) -> Optional[str]:
        """将自然语言时间解析为 ISO 8601 字符串"""
        if not text:
            return None
        text = text.strip()

        # 已经是 ISO 格式
        if "T" in text and "-" in text:
            try:
                dt = datetime.fromisoformat(text)
                # v6.4.2 修复：带时区的 ISO（如 +08:00）解析出 aware 时间，
                # 与 naive 的 datetime.now() 比较会 TypeError 被 except 吞掉，
                # 提醒从此永不触发（2026-08-19 午休闹钟哑火事故）
                if dt.tzinfo is not None:
                    dt = dt.astimezone().replace(tzinfo=None)
                return dt.isoformat()
            except Exception:
                pass

        now = datetime.now()
        result = None

        # 匹配 "X点Y分" 模式（优先匹配带分钟的）
        hm_match = re.search(r'(\d{1,2})\s*[点时]\s*(\d{1,2})\s*分?', text)
        if hm_match:
            hour = int(hm_match.group(1))
            minute = int(hm_match.group(2))
        else:
            # 匹配 "X点/Y点" 模式
            hour_match = re.search(r'(\d{1,2})\s*[点时]', text)
            hour = int(hour_match.group(1)) if hour_match else None
            minute = 0

        # 匹配 "X分钟/X小时后"
        delta_match = re.search(r'(\d+)\s*(分钟|小时|天)\s*(后|以后)', text)
        if delta_match:
            n = int(delta_match.group(1))
            unit = delta_match.group(2)
            if unit == "分钟":
                result = now + timedelta(minutes=n)
            elif unit == "小时":
                result = now + timedelta(hours=n)
            elif unit == "天":
                result = now + timedelta(days=n)
            if result and hour:
                result = result.replace(hour=hour, minute=minute, second=0)
            if result:
                return result.isoformat()

        # 匹配关键词
        for kw, days_delta in _TIME_KEYWORDS.items():
            if kw in text:
                target = now + timedelta(days=days_delta)
                if hour is None:
                    hour = _HOUR_KEYWORDS.get(kw, 9)
                target = target.replace(hour=hour, minute=minute, second=0)
                return target.isoformat()

        # 匹配 "X月X日" 模式
        md_match = re.search(r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]', text)
        if md_match:
            month = int(md_match.group(1))
            day = int(md_match.group(2))
            year = now.year
            try:
                target = datetime(year, month, day, hour or 9, 0, 0)
                if target < now:
                    target = target.replace(year=year + 1)
                return target.isoformat()
            except Exception:
                pass

        return None

    def _extract_time_from_text(self, text: str) -> Optional[str]:
        """从记忆文本中提取时间信息"""
        if not text:
            return None
        # 优先匹配明确的时间模式
        patterns = [
            r'(\d{1,2})\s*[点时]\s*(\d{1,2})?\s*(上午|下午|晚上|am|pm)?',
            r'(明天|后天|大后天|下周|下下周|下个月)\s*(?:\d{1,2}\s*[点时]|上午|下午|晚上|中午|凌晨|傍晚|清晨)',
            r'(\d{1,2})\s*(分钟|小时|天)\s*(后|以后)',
            r'(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0)
        # 降级到关键词匹配（v6.9 护栏：只在前60字内找——
        # 叙述性记忆的时间词藏在正文中间，靠前的才是真提醒意图）
        head = text[:60]
        for kw in list(_TIME_KEYWORDS.keys()) + list(_HOUR_KEYWORDS.keys()):
            if kw in head:
                # 返回包含关键词的一小段
                idx = head.index(kw)
                start = max(0, idx - 5)
                end = min(len(head), idx + len(kw) + 10)
                return head[start:end]
        return None

    # ─────────── 辅助 ───────────

    def _next_id(self) -> int:
        if not self._reminders:
            return 1
        return max(r["id"] for r in self._reminders) + 1
