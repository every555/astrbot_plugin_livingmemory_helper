# -*- coding: utf-8 -*-
"""格式化输出工具"""

ACKIS = {
    "positive": "😊", "negative": "😔", "neutral": "😐",
}


def format_timeline(
    memories: list, date_label: str, detail: bool = False, weekday: str = ""
) -> str:
    if not memories:
        return f"📅 {date_label} — 暂无记忆记录"

    header = f"📅 {date_label}" + (f"（{weekday}）" if weekday else "")
    if detail:
        return _format_timeline_detail(header, memories)
    return _format_timeline_simple(header, memories)


def _format_timeline_simple(header: str, memories: list) -> str:
    lines = [header, "━" * 36]
    for m in memories:
        time = m.get("time", "??:??")
        content = m.get("content", "")[:60]
        icon = _pick_icon(m)
        lines.append(f" 🕐 {time}   {icon} {content}")
    lines.append("━" * 36)
    total = len(memories)
    hour_dist = _hour_summary(memories)
    lines.append(f" 📊 共 {total} 条记忆")
    if hour_dist:
        lines.append(f" 📈 最活跃时段：{hour_dist}")
    return "\n".join(lines)


def _format_timeline_detail(header: str, memories: list) -> str:
    lines = [header + " — 详细时间轴", "━" * 44]
    for m in memories:
        time = m.get("time", "??:??")
        content = m.get("content", "")[:80]
        icon = _pick_icon(m)
        tags = " / ".join(m.get("tags", [])) or "无标签"
        importance = m.get("importance", 0)
        full = m.get("full_text", content)[:120]
        lines.append(f" 🕐 {time} | {icon} {content}")
        lines.append(f" ├ 话题：{tags}")
        lines.append(f" ├ 重要性：{importance:.2f}")
        lines.append(f" └ 原文：{full}")
        lines.append("")
    lines.append("━" * 44)
    return "\n".join(lines)


def _pick_icon(memory: dict) -> str:
    tags = " ".join(memory.get("tags", [])).lower()
    content = memory.get("content", "").lower()
    if "error_lesson" in tags:
        return "📖"
    if "画图" in tags or "画画" in tags or "图" in tags:
        return "📸"
    if "提醒" in tags or "约定" in tags or "定时" in tags:
        return "⏰"
    if "单词" in tags or "学习" in tags:
        return "📝"
    sentiment = memory.get("sentiment", "")
    if sentiment == "positive":
        return "💬"
    if sentiment == "negative":
        return "💭"
    return "💬"


def _hour_summary(memories: list) -> str:
    hour_counts = {}
    for m in memories:
        time = m.get("time", "")
        if time and ":" in time:
            hour = time.split(":")[0]
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
    if not hour_counts:
        return ""
    peak = max(hour_counts, key=lambda h: hour_counts[h])
    return f"{peak}:00~{int(peak) + 1}:00"


SENTIMENT_MAP = {
    "positive": "😊 积极",
    "negative": "😔 负面",
    "neutral": "😐 中性",
}

TOPIC_ICONS = {
    "画图": "📸", "画画": "📸",
    "约定": "📅", "计划": "📅",
    "提醒": "⏰", "定时": "⏰",
    "学习": "📝", "单词": "📝",
    "日常": "🏠", "生活": "🏠",
    "开发": "💻", "代码": "💻",
    "游戏": "🎮", "动漫": "🎬",
    "心情": "💭", "情感": "💭",
    "error_lesson": "📖",
}
