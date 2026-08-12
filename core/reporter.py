# -*- coding: utf-8 -*-
"""F6 - 统计日报/周报"""
from datetime import datetime, timedelta
from astrbot.api import logger


class MemoryReporter:
    def __init__(self, reader):
        self.reader = reader

    def daily_report(self) -> str:
        """今日报告"""
        today = datetime.now().strftime("%Y-%m-%d")
        stats = self.reader.get_stats_for_date(today)
        total = stats["total"]
        hour_dist = stats.get("hour_distribution", {})

        tags = self.reader.get_all_tags()
        tag_counts = self._count_tags(today)

        lines = [
            f"📊 记忆日报 — {today}",
            "━" * 36,
            f" 📝 今日新增：{total} 条",
            "",
        ]
        if hour_dist:
            peak = max(hour_dist, key=lambda h: hour_dist[h])
            lines.append(f" 🔥 最活跃：{peak} 点（{hour_dist[peak]} 条）")
        lines.append("")
        if tag_counts:
            lines.append(" 🏷 热门话题：")
            for tag, cnt in tag_counts[:5]:
                lines.append(f"   {tag}（{cnt}次）")
        lines.append("━" * 36)
        lines.append(f" 💾 总记忆：{self.reader.get_memory_count()} 条")
        return "\n".join(lines)

    def weekly_report(self) -> str:
        """本周报告"""
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        week_num = today.isocalendar()[1]

        total_weekly = 0
        daily_counts = []
        for i in range(7):
            d = monday + timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            if d <= today:
                s = self.reader.get_stats_for_date(date_str)
                cnt = s["total"]
                total_weekly += cnt
                daily_counts.append((d.strftime("%m/%d"), cnt))

        total_all = self.reader.get_memory_count()

        lines = [
            f"📊 记忆周报 — 第 {week_num} 周",
            "━" * 36,
            f" 📝 本周新增：{total_weekly} 条",
            "",
            " 📅 每日：",
        ]
        for d, c in daily_counts:
            bar = "█" * min(c, 20)
            lines.append(f"   {d} {bar} {c}")

        lines.append("")
        lines.append("━" * 36)
        lines.append(f" 💾 总记忆：{total_all} 条")
        return "\n".join(lines)

    def _count_tags(self, date_str: str) -> list:
        """统计某日话题频率"""
        conn = self.reader._connect()
        rows = conn.execute(
            "SELECT metadata FROM documents WHERE date(created_at) = ?",
            (date_str,),
        ).fetchall()
        conn.close()

        counts = {}
        for r in rows:
            meta = self.reader._parse_meta(r[0])
            topics = meta.get("topics", [])
            for t in topics:
                counts[t] = counts.get(t, 0) + 1
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)
