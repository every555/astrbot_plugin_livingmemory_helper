# -*- coding: utf-8 -*-
"""F8 - 外部知识库同步"""
import os
import re
import json
from datetime import datetime
from astrbot.api import logger


class ExternalSync:
    def __init__(self, reader, data_dir: str):
        self.reader = reader
        self.data_dir = data_dir

    def sync_obsidian(self, vault_path: str = None) -> str:
        """同步记忆到 Obsidian 本地库"""
        if not vault_path:
            vault_path = os.path.join(
                self.data_dir, "obsidian_export"
            )
        os.makedirs(vault_path, exist_ok=True)

        memories = self.reader.get_recent_memories(500)
        count = 0
        for m in memories:
            date = m.get("date", "")
            time = m.get("time", "")
            content = m.get("content", "")
            tags = m.get("tags", [])
            tags_yaml = "\n  - ".join(tags) if tags else ""
            importance = m.get("importance", 0)

            safe_title = re.sub(r'[\\/:*?"<>|]', "-", content[:50])
            filename = f"{date}_{time}_{safe_title}.md"
            filepath = os.path.join(vault_path, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write("---\n")
                f.write(f"date: {date}T{time}\n")
                f.write(f"importance: {importance}\n")
                if tags_yaml:
                    f.write(f"tags:\n  - {tags_yaml}\n")
                f.write("---\n\n")
                f.write(f"# {content[:80]}\n\n")
                f.write(f"{content}\n")
            count += 1

        return (
            f"✅ 已同步 {count} 条记忆到 Obsidian 库\n"
            f"   📂 {vault_path}"
        )

    def sync_notion(self) -> str:
        """同步到 Notion — 需要 API key，暂不支持"""
        return (
            "🔧 Notion 同步需要配置 API Token\n"
            "   暂未开放，请先用 Obsidian 导出"
        )

    def get_status(self) -> str:
        """查看同步状态"""
        total = self.reader.get_memory_count()
        return (
            f"📊 同步状态\n"
            f"━" * 24 + "\n"
            f" 💾 总记忆数: {total}\n"
            f" 🔄 Obsidian 已支持\n"
            f" 🔧 Notion 待开发\n"
        )
