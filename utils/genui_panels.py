"""
ChatUI 内联交互面板生成模块 (v4.2)
====================================
生成可在聊天界面内渲染的 HTML 面板，使用 <html-genui> 标签。
所有面板：纯CSS、无外部依赖、响应式、深色主题适配。
"""

from typing import Any
from datetime import datetime

# ══════════════════════════════════════════════════════
# 公共样式
# ══════════════════════════════════════════════════════

_BASE_STYLE = """
:root {
  --bg: #1a1a2e;
  --bg-card: #16213e;
  --bg-hover: #1f3460;
  --accent: #e94560;
  --accent2: #ff6b6b;
  --text: #e8e8e8;
  --text-dim: #a0a0b0;
  --border: #2a2a4a;
  --positive: #4ecdc4;
  --negative: #ff6b6b;
  --neutral: #ffd93d;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
  padding: 12px;
  line-height: 1.5;
}
.panel {
  background: var(--bg-card);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
  border: 1px solid var(--border);
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent2);
}
.panel-badge {
  font-size: 11px;
  background: var(--accent);
  color: white;
  padding: 2px 8px;
  border-radius: 10px;
}
.card {
  background: var(--bg);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all 0.2s;
}
.card:hover { background: var(--bg-hover); }
.card.expanded { background: var(--bg-hover); }
.card-content {
  display: none;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  font-size: 13px;
  color: var(--text-dim);
  white-space: pre-wrap;
}
.card.expanded .card-content { display: block; }
.card-time {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.card-title {
  font-size: 13px;
  font-weight: 500;
}
.card-star { color: var(--neutral); margin-right: 4px; }
.tag {
  display: inline-block;
  font-size: 10px;
  background: var(--border);
  color: var(--text-dim);
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 4px;
}
.stat-row {
  display: flex;
  justify-content: space-around;
  margin: 12px 0;
}
.stat-item {
  text-align: center;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--accent2);
}
.stat-label {
  font-size: 11px;
  color: var(--text-dim);
}
.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 80px;
  margin: 12px 0;
}
.bar {
  flex: 1;
  background: var(--accent);
  border-radius: 2px 2px 0 0;
  min-height: 2px;
  transition: height 0.3s;
  position: relative;
}
.bar:hover {
  background: var(--accent2);
}
.bar:hover::after {
  content: attr(data-tip);
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-card);
  color: var(--text);
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  border: 1px solid var(--border);
  z-index: 10;
}
.trend-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
}
.trend-up { background: rgba(78,205,196,0.2); color: var(--positive); }
.trend-down { background: rgba(255,107,107,0.2); color: var(--negative); }
.trend-flat { background: rgba(255,217,61,0.2); color: var(--neutral); }
.group-header {
  font-size: 12px;
  color: var(--text-dim);
  margin: 12px 0 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.group-header span { color: var(--accent2); }
.collapsible { cursor: pointer; user-select: none; }
.collapsible::before {
  content: '▸';
  display: inline-block;
  transition: transform 0.2s;
  margin-right: 4px;
}
.collapsible.open::before { transform: rotate(90deg); }
.group-body {
  display: none;
}
.group-body.open { display: block; }
/* 提醒面板 */
.reminder-card {
  background: var(--bg);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all 0.2s;
}
.reminder-card:hover { background: var(--bg-hover); }
.reminder-card.overdue { border-left: 3px solid var(--negative); }
.reminder-card.upcoming { border-left: 3px solid var(--neutral); }
.reminder-card.normal { border-left: 3px solid var(--positive); }
.reminder-card.done { opacity: 0.5; }
.reminder-card.expanded .reminder-detail { display: block; }
.reminder-detail {
  display: none;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  font-size: 12px;
  color: var(--text-dim);
  white-space: pre-wrap;
}
.reminder-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.reminder-status {
  font-size: 14px;
}
.reminder-id {
  font-size: 10px;
  color: var(--text-dim);
  font-family: monospace;
}
.reminder-time {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 2px;
}
.reminder-content {
  font-size: 13px;
}
.reminder-priority {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
}
.priority-high { background: rgba(255,107,107,0.2); color: var(--negative); }
.priority-normal { background: rgba(78,205,196,0.2); color: var(--positive); }
.priority-low { background: rgba(160,160,176,0.2); color: var(--text-dim); }
.reminder-source {
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 4px;
}
"""


def _wrap_html(title: str, body_content: str) -> str:
    """包装完整的 HTML 页面"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{_BASE_STYLE}</style></head>
<body>{body_content}</body>
</html>"""


# ══════════════════════════════════════════════════════
# 面板1: 回忆搜索结果
# ══════════════════════════════════════════════════════

def render_recall_panel(results: list[dict], query: str) -> str:
    """生成回忆搜索结果的交互面板"""
    cards_html = ""
    for i, m in enumerate(results, 1):
        time_str = m.get("time", m.get("date", "")) or "未知时间"
        content = m.get("content", "")
        tags = m.get("tags", [])
        imp = m.get("importance", 0)
        star = "⭐" if imp > 0.8 else ("✨" if imp > 0.6 else "")
        tags_html = "".join(f'<span class="tag">{t}</span>' for t in tags[:3])

        cards_html += f"""
<div class="card" onclick="this.classList.toggle('expanded')">
  <div class="card-time">{time_str}</div>
  <div class="card-title">{star} 记忆 #{i} {tags_html}</div>
  <div class="card-content">{content}</div>
</div>"""

    body = f"""
<div class="panel">
  <div class="panel-header">
    <span class="panel-title">🔍 回忆面板</span>
    <span class="panel-badge">{len(results)} 条</span>
  </div>
  <p style="font-size:12px;color:var(--text-dim);margin-bottom:8px;">
    关于「<span style="color:var(--accent2)">{query}</span>」的记忆
  </p>
  {cards_html}
  <p style="font-size:11px;color:var(--text-dim);margin-top:8px;text-align:center;">
    点击卡片展开详情
  </p>
</div>"""
    return _wrap_html(f"回忆 - {query}", body)


# ══════════════════════════════════════════════════════
# 面板2: 今日摘要
# ══════════════════════════════════════════════════════

def render_today_panel(memories: list[dict], date_str: str, weekday: str, is_today: bool = False) -> str:
    """生成今日摘要的时间线面板"""
    intro = "今天" if is_today else f"{date_str}（{weekday}）"

    # 统计
    total = len(memories)
    pos = sum(1 for m in memories if m.get("sentiment") == "positive")
    neg = sum(1 for m in memories if m.get("sentiment") == "negative")
    high = sum(1 for m in memories if m.get("importance", 0) > 0.7)
    mood = "😊 开心" if pos > neg else ("😔 低落" if neg > pos else "😐 平静")

    cards_html = ""
    memories_sorted = sorted(memories, key=lambda m: m.get("time", m.get("date", "")) or "")
    for i, m in enumerate(memories_sorted[:10], 1):
        time_str = m.get("time", "") or ""
        content = (m.get("content", "") or "")[:150]
        imp = m.get("importance", 0)
        star = "⭐" if imp > 0.8 else ("✨" if imp > 0.6 else "")
        sent = m.get("sentiment", "")
        sent_icon = "😊" if sent == "positive" else ("😔" if sent == "negative" else "😐")

        cards_html += f"""
<div class="card" onclick="this.classList.toggle('expanded')">
  <div class="card-time">{time_str} {sent_icon}</div>
  <div class="card-title">{star} {content[:50]}{'...' if len(content) > 50 else ''}</div>
  <div class="card-content">{content}</div>
</div>"""

    if total > 10:
        cards_html += f'<p style="font-size:11px;color:var(--text-dim);text-align:center;">…以及另外 {total - 10} 条</p>'

    body = f"""
<div class="panel">
  <div class="panel-header">
    <span class="panel-title">📅 今日摘要</span>
    <span class="panel-badge">{total} 条</span>
  </div>
  <p style="font-size:13px;color:var(--text-dim);margin-bottom:8px;">
    {intro}，我们共同经历了这些：
  </p>
  <div class="stat-row">
    <div class="stat-item">
      <div class="stat-value">{total}</div>
      <div class="stat-label">总记忆</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">{mood}</div>
      <div class="stat-label">心情</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">{high}</div>
      <div class="stat-label">重要</div>
    </div>
  </div>
  {cards_html}
  <p style="font-size:11px;color:var(--text-dim);margin-top:8px;text-align:center;">
    点击卡片展开详情
  </p>
</div>"""
    return _wrap_html(f"今日摘要 - {date_str}", body)


# ══════════════════════════════════════════════════════
# 面板3: 搜索结果（按日期分组）
# ══════════════════════════════════════════════════════

def render_search_panel(groups: dict[str, list], query: str, days: int, total: int) -> str:
    """生成搜索结果的分组折叠面板"""
    groups_html = ""
    sorted_dates = sorted(groups.keys())

    for i, date_key in enumerate(sorted_dates[:10], 1):
        items = groups[date_key]
        items_html = ""
        for m in items[:5]:
            content = (m.get("content", "") or "")[:100]
            time_str = m.get("time", "") or ""
            items_html += f"""
      <div class="card" onclick="this.classList.toggle('expanded')">
        <div class="card-time">{time_str}</div>
        <div class="card-title">{content[:40]}{'...' if len(content) > 40 else ''}</div>
        <div class="card-content">{content}</div>
      </div>"""
        if len(items) > 5:
            items_html += f'<p style="font-size:11px;color:var(--text-dim);">…共 {len(items)} 条</p>'

        groups_html += f"""
    <div class="group-header collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
      📅 <span>{date_key}</span>（{len(items)}条）
    </div>
    <div class="group-body">{items_html}</div>"""

    body = f"""
<div class="panel">
  <div class="panel-header">
    <span class="panel-title">🔍 搜索面板</span>
    <span class="panel-badge">{total} 条</span>
  </div>
  <p style="font-size:12px;color:var(--text-dim);margin-bottom:4px;">
    最近 {days} 天关于「<span style="color:var(--accent2)">{query}</span>」的记忆
  </p>
  <p style="font-size:11px;color:var(--text-dim);margin-bottom:8px;">
    跨越 {len(sorted_dates)} 个日期
  </p>
  {groups_html}
  <p style="font-size:11px;color:var(--text-dim);margin-top:8px;text-align:center;">
    点击日期展开记忆列表
  </p>
</div>"""
    return _wrap_html(f"搜索 - {query}", body)


# ══════════════════════════════════════════════════════
# 面板4: 情感趋势
# ══════════════════════════════════════════════════════

def render_sentiment_panel(daily_data: list[dict], trend: str, stats: dict) -> str:
    """生成情感趋势的图表面板"""
    max_count = max((d.get("count", 0) for d in daily_data), default=1) or 1

    bars_html = ""
    for d in daily_data:
        count = d.get("count", 0)
        height = int((count / max_count) * 100) if max_count > 0 else 0
        date_label = d.get("date", "")[-5:]  # MM-DD
        bars_html += f'<div class="bar" style="height:{max(height, 3)}%" data-tip="{d.get("date","")}: {count}条"></div>'

    # 趋势样式
    trend_class = "trend-up" if "上升" in trend else ("trend-down" if "下降" in trend else "trend-flat")
    trend_icon = "📈" if "上升" in trend else ("📉" if "下降" in trend else "📊")

    total = stats.get("total", 0)
    active_days = stats.get("active_days", 0)
    total_days = stats.get("total_days", len(daily_data))
    peak = stats.get("peak_date", "")
    peak_count = stats.get("peak_count", 0)

    # 日期标签（只显示首尾和中间）
    date_labels = ""
    if daily_data:
        first = daily_data[0].get("date", "")[-5:]
        last = daily_data[-1].get("date", "")[-5:]
        mid_idx = len(daily_data) // 2
        mid = daily_data[mid_idx].get("date", "")[-5:] if mid_idx < len(daily_data) else ""
        date_labels = f"""
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-dim);margin-top:4px;">
        <span>{first}</span>
        <span>{mid}</span>
        <span>{last}</span>
      </div>"""

    body = f"""
<div class="panel">
  <div class="panel-header">
    <span class="panel-title">💕 情感趋势</span>
    <span class="panel-badge">{total_days} 天</span>
  </div>
  <div class="stat-row">
    <div class="stat-item">
      <div class="stat-value">{total}</div>
      <div class="stat-label">总记忆</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">{active_days}</div>
      <div class="stat-label">活跃天数</div>
    </div>
    <div class="stat-item">
      <div class="stat-value">{peak_count}</div>
      <div class="stat-label">单日最多</div>
    </div>
  </div>
  <div class="bar-chart">
    {bars_html}
  </div>
  {date_labels}
  <div style="margin-top:12px;text-align:center;">
    <span class="trend-badge {trend_class}">{trend_icon} {trend}</span>
  </div>
  <p style="font-size:11px;color:var(--text-dim);margin-top:8px;text-align:center;">
    {peak} 是记忆最多的一天
  </p>
</div>"""
    return _wrap_html("情感趋势", body)


# ══════════════════════════════════════════════════════
# 面板5: 提醒列表
# ══════════════════════════════════════════════════════

def render_reminder_panel(
    reminders: list[dict],
    upcoming: list[dict] = None,
    overdue: list[dict] = None,
) -> str:
    """生成提醒列表的交互面板

    Args:
        reminders: 所有提醒列表
        upcoming: 即将到期的提醒（24h内）
        overdue: 已过期但未触发的提醒
    """
    upcoming = upcoming or []
    overdue = overdue or []

    total = len(reminders)
    done = sum(1 for r in reminders if r.get("done"))
    active = total - done

    # 按状态分类渲染卡片
    cards_html = ""

    # 先渲染已过期的
    for r in overdue:
        cards_html += _render_reminder_card(r, "overdue")

    # 再渲染即将到期的
    for r in upcoming:
        # 跳过已在 overdue 中的
        if any(o["id"] == r["id"] for o in overdue):
            continue
        cards_html += _render_reminder_card(r, "upcoming")

    # 最后渲染其余的
    shown_ids = {r["id"] for r in overdue} | {r["id"] for r in upcoming}
    for r in reminders:
        if r["id"] in shown_ids or r.get("done"):
            continue
        cards_html += _render_reminder_card(r, "normal")

    # 已完成的（折叠）
    done_items = [r for r in reminders if r.get("done")]
    if done_items:
        done_cards = ""
        for r in done_items[:5]:
            done_cards += _render_reminder_card(r, "done")
        cards_html += f"""
    <div class="group-header collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
      ✅ <span>已完成</span>（{len(done_items)}条）
    </div>
    <div class="group-body">{done_cards}</div>"""

    body = f"""
<div class="panel">
  <div class="panel-header">
    <span class="panel-title">⏰ 提醒面板</span>
    <span class="panel-badge">{active} 待办</span>
  </div>
  <div class="stat-row">
    <div class="stat-item">
      <div class="stat-value">{active}</div>
      <div class="stat-label">待办</div>
    </div>
    <div class="stat-item">
      <div class="stat-value" style="color:var(--negative)">{len(overdue)}</div>
      <div class="stat-label">已过期</div>
    </div>
    <div class="stat-item">
      <div class="stat-value" style="color:var(--neutral)">{len(upcoming)}</div>
      <div class="stat-label">即将到期</div>
    </div>
  </div>
  {cards_html}
  <p style="font-size:11px;color:var(--text-dim);margin-top:8px;text-align:center;">
    点击卡片展开详情 · 红色=过期 · 黄色=即将到期 · 绿色=正常
  </p>
</div>"""
    return _wrap_html("提醒面板", body)


def _render_reminder_card(r: dict, status: str = "normal") -> str:
    """渲染单个提醒卡片"""
    rid = r.get("id", "?")
    content = (r.get("content", "") or "")[:200]
    target_time = r.get("target_time", "") or ""
    parsed = r.get("parsed_time", "") or ""
    source = r.get("source", "manual")
    priority = r.get("priority", "normal")
    done = r.get("done", False)
    fired = r.get("fired", False)

    # 状态图标
    if done:
        icon = "✅"
    elif fired:
        icon = "🔔"
    elif status == "overdue":
        icon = "🔴"
    elif status == "upcoming":
        icon = "🟡"
    else:
        icon = "⏳"

    # 优先级标签
    priority_class = f"priority-{priority}"
    priority_label = {"high": "高", "normal": "中", "low": "低"}.get(priority, priority)

    # 来源标签
    source_label = {"manual": "手动", "auto_scan": "自动扫描", "memory_extract": "记忆提取"}.get(source, source)

    # 时间显示
    time_display = target_time
    if parsed:
        try:
            dt = datetime.fromisoformat(parsed)
            time_display = dt.strftime("%m-%d %H:%M")
        except Exception:
            pass

    return f"""
<div class="reminder-card {status} {'done' if done else ''}" onclick="this.classList.toggle('expanded')">
  <div class="reminder-top">
    <span class="reminder-status">{icon}</span>
    <span class="reminder-id">#{rid}</span>
  </div>
  <div class="reminder-time">🕐 {time_display}</div>
  <div class="reminder-content">{content[:60]}{'...' if len(content) > 60 else ''}</div>
  <div class="reminder-detail">{'-' * 30}
内容: {content}
目标时间: {target_time}
解析时间: {parsed or '(未解析)'}
来源: {source_label}
优先级: {priority_label}
状态: {'已完成' if done else ('已触发' if fired else '待办')}</div>
  <div style="display:flex;gap:4px;align-items:center;margin-top:4px;">
    <span class="reminder-priority {priority_class}">{priority_label}</span>
    <span class="reminder-source">{source_label}</span>
  </div>
</div>"""
