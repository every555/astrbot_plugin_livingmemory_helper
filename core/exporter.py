# -*- coding: utf-8 -*-
"""F3 - 记忆导出工具"""
import json
import os
import re
from datetime import datetime


class MemoryExporter:
    def __init__(self, reader, export_dir: str):
        self.reader = reader
        self.export_dir = export_dir
        os.makedirs(export_dir, exist_ok=True)

    def export_markdown(
        self, tags: str = None, limit: int = 100
    ) -> str:
        """导出为 Markdown"""
        if tags:
            tag_list = re.split(r"[,，\s]+", tags.strip())
            memories = []
            for tag in tag_list:
                memories.extend(self.reader.search_memories_by_tag(tag, limit))
            memories = memories[:limit]
        else:
            memories = self.reader.get_recent_memories(limit)

        if not memories:
            return "没有可导出的记忆。"

        today = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# 记忆导出 - {today}",
            f"共 {len(memories)} 条记忆",
            "",
            "---",
            "",
        ]
        current_date = ""
        for m in memories:
            date = m.get("date", "")
            if date != current_date:
                current_date = date
                lines.append(f"## {date}")
                lines.append("")
            time = m.get("time", "")
            content = m.get("content", "")
            tags_str = "、".join(m.get("tags", []))
            importance = m.get("importance", 0)
            lines.append(f"### {time}")
            lines.append(f"**内容**：{content}")
            lines.append(f"**标签**：`{tags_str}`")
            lines.append(f"**重要性**：{importance:.2f}")
            lines.append("")

        # 保存文件
        filename = f"memory_export_{today}.md"
        filepath = os.path.join(self.export_dir, filename)
        full_text = "\n".join(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_text)
        return f"✅ 已导出 {len(memories)} 条记忆到 {filepath}"

    def export_json(self, tags: str = None, limit: int = 100) -> str:
        """导出为 JSON"""
        if tags:
            memories = self.reader.search_memories_by_tag(tags.strip(), limit)
        else:
            memories = self.reader.get_recent_memories(limit)

        data = {
            "export_time": datetime.now().isoformat(),
            "count": len(memories),
            "memories": memories,
        }
        filename = f"memory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.export_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return f"✅ 已导出 {len(memories)} 条记忆到 {filepath}"

    def export_obsidian(
        self, tags: str = None, limit: int = 100
    ) -> str:
        """导出为 Obsidian 格式（每条记忆一个文件）"""
        if tags:
            memories = self.reader.search_memories_by_tag(tags.strip(), limit)
        else:
            memories = self.reader.get_recent_memories(limit)

        vault_dir = os.path.join(self.export_dir, "obsidian_vault")
        os.makedirs(vault_dir, exist_ok=True)

        count = 0
        for m in memories:
            date = m.get("date", "")
            time = m.get("time", "")
            content = m.get("content", "")
            tags_str = "/".join(m.get("tags", []))
            importance = m.get("importance", 0)
            key_facts = "、".join(m.get("key_facts", []))

            safe_title = re.sub(r'[\\/:*?"<>|]', "-", content[:40])
            filename = f"{date}_{time}_{safe_title}.md"
            filepath = os.path.join(vault_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("---\n")
                f.write(f"date: {date}T{time}:00+08:00\n")
                f.write(f"tags: [{tags_str}]\n")
                f.write(f"importance: {importance}\n")
                f.write("---\n\n")
                f.write(f"# {content[:80]}\n\n")
                f.write(f"{content}\n")
                if key_facts:
                    f.write(f"\n**关键信息**：{key_facts}\n")
            count += 1

        return f"✅ 已导出 {count} 条记忆到 {vault_dir}"

    def export_all(self, format_type: str, limit: int = 500) -> str:
        if format_type == "md":
            return self.export_markdown(limit=limit)
        elif format_type == "json":
            return self.export_json(limit=limit)
        elif format_type == "obsidian":
            return self.export_obsidian(limit=limit)
        return f"未知格式: {format_type}，支持 md/json/obsidian"
