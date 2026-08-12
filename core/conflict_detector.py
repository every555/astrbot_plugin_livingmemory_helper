# -*- coding: utf-8 -*-
"""F7 - 记忆冲突检测：检测 LivingMemory 中矛盾的记忆"""
import json
from astrbot.api import logger


class ConflictDetector:
    def __init__(self, reader):
        self.reader = reader
        self._conflicts = []  # resolved conflicts

    def detect_conflicts(self, limit: int = 50) -> list:
        """找出最近记忆中可能矛盾的内容"""
        memories = self.reader.get_recent_memories(limit)
        pairs = []

        for i in range(len(memories)):
            for j in range(i + 1, len(memories)):
                a_tags = set(memories[i].get("tags", []))
                b_tags = set(memories[j].get("tags", []))
                common = a_tags & b_tags
                if not common:
                    continue
                a_content = memories[i].get("content", "")
                b_content = memories[j].get("content", "")
                # 简单规则：同话题但关键事实不同 → 可能冲突
                a_facts = " ".join(memories[i].get("key_facts", []))
                b_facts = " ".join(memories[j].get("key_facts", []))

                if a_facts and b_facts and a_facts != b_facts:
                    pairs.append({
                        "id_a": memories[i]["id"],
                        "id_b": memories[j]["id"],
                        "content_a": a_content[:100],
                        "content_b": b_content[:100],
                        "common_tags": list(common),
                    })
                if len(pairs) >= 20:
                    break
            if len(pairs) >= 20:
                break
        return pairs

    def format_conflicts(self, pairs: list) -> str:
        if not pairs:
            return "✅ 没有检测到明显的记忆冲突～"
        lines = [
            f"⚠ 检测到 {len(pairs)} 组潜在冲突：",
            "",
        ]
        for i, p in enumerate(pairs, 1):
            tags = "、".join(p["common_tags"][:3])
            lines.append(f"{i}. 话题: {tags}")
            lines.append(f"   A[{p['id_a']}]: {p['content_a'][:60]}")
            lines.append(f"   B[{p['id_b']}]: {p['content_b'][:60]}")
            lines.append("")
        lines.append("用 /lmem forget <id> 删除错误的记忆")
        return "\n".join(lines)

    def resolve(self, keep_id: int, drop_id: int) -> str:
        """保留一条，删除另一条"""
        # 这里只做标记，实际删除需要用户手动操作
        return (
            f"📌 建议保留 #{keep_id}，删除 #{drop_id}"
            f"\n请发送 /lmem forget {drop_id} 确认删除"
        )
