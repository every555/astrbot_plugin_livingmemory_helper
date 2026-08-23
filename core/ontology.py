"""
LivingMemory 知识图谱模块
"""
import json, os, sqlite3, uuid
from datetime import datetime
from enum import Enum


class EntityType(Enum):
    PERSON = "person"
    EVENT = "event"
    TOPIC = "topic"
    PLACE = "place"
    OBJECT = "object"
    CONCEPT = "concept"
    GOAL = "goal"           # v6.0: 目标层级（AIRI goal hierarchy）
    EMOTION = "emotion"     # v6.0: 情感实体
    CUSTOM = "custom"


class RelationType(Enum):
    RELATED = "related"
    PART_OF = "part_of"
    CAUSED = "caused"
    MENTIONED = "mentioned"
    ATTENDED = "attended"
    LOCATED_AT = "located_at"
    HAS = "has"
    BELONGS_TO = "belongs_to"
    SUBGOAL_OF = "subgoal_of"   # v6.0: 子目标关系（goal hierarchy）
    ACHIEVED_BY = "achieved_by" # v6.0: 目标达成方式
    BLOCKED_BY = "blocked_by"   # v6.0: 目标阻塞
    EVOKED = "evoked"           # v6.0: 情感触发关系
    CUSTOM = "custom"


class OntologyManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
                properties TEXT DEFAULT '{}', created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY, from_id TEXT NOT NULL,
                relation_type TEXT NOT NULL, to_id TEXT NOT NULL,
                properties TEXT DEFAULT '{}', created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (from_id) REFERENCES entities(id),
                FOREIGN KEY (to_id) REFERENCES entities(id))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_from ON relations(from_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id)")
            conn.commit()

    def create_entity(self, entity_type: str, properties: dict = None) -> dict:
        eid = str(uuid.uuid4())[:8]
        props = json.dumps(properties or {}, ensure_ascii=False)
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO entities (id, entity_type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                         (eid, entity_type, props, now, now))
            conn.commit()
        return {"success": True, "id": eid, "entity_type": entity_type, "properties": properties or {}}

    def get_entity(self, entity_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
            if not row:
                return {"success": False, "error": f"实体 {entity_id} 不存在"}
            return {"success": True, "id": row["id"], "entity_type": row["entity_type"],
                    "properties": json.loads(row["properties"]),
                    "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def update_entity(self, entity_id: str, properties: dict) -> dict:
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if not conn.execute("SELECT id FROM entities WHERE id = ?", (entity_id,)).fetchone():
                return {"success": False, "error": f"实体 {entity_id} 不存在"}
            conn.execute("UPDATE entities SET properties = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(properties, ensure_ascii=False), now, entity_id))
            conn.commit()
        return {"success": True, "id": entity_id, "properties": properties}

    def delete_entity(self, entity_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            if not conn.execute("SELECT id FROM entities WHERE id = ?", (entity_id,)).fetchone():
                return False
            conn.execute("DELETE FROM relations WHERE from_id = ? OR to_id = ?", (entity_id, entity_id))
            conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
            conn.commit()
        return True

    def list_entities(self, entity_type: str = None, limit: int = 100) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if entity_type:
                rows = conn.execute("SELECT * FROM entities WHERE entity_type = ? ORDER BY updated_at DESC LIMIT ?",
                                    (entity_type, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM entities ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            entities = [{"id": r["id"], "entity_type": r["entity_type"],
                         "properties": json.loads(r["properties"]),
                         "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]
        return {"success": True, "entities": entities, "total": len(entities)}

    def create_relation(self, from_id: str, relation_type: str, to_id: str, properties: dict = None) -> dict:
        rel_id = str(uuid.uuid4())[:8]
        props = json.dumps(properties or {}, ensure_ascii=False)
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            if not conn.execute("SELECT id FROM entities WHERE id = ?", (from_id,)).fetchone():
                return {"success": False, "error": f"源实体 {from_id} 不存在"}
            if not conn.execute("SELECT id FROM entities WHERE id = ?", (to_id,)).fetchone():
                return {"success": False, "error": f"目标实体 {to_id} 不存在"}
            conn.execute("INSERT INTO relations (id, from_id, relation_type, to_id, properties, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (rel_id, from_id, relation_type, to_id, props, now))
            conn.commit()
        return {"success": True, "id": rel_id, "from_id": from_id, "relation_type": relation_type, "to_id": to_id}

    def get_related_entities(self, entity_id: str, relation_type: str = None) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if relation_type:
                rows = conn.execute("""SELECT DISTINCT e.*, r.relation_type,
                    CASE WHEN r.from_id = ? THEN 'outgoing' ELSE 'incoming' END as direction
                    FROM entities e JOIN relations r ON (r.to_id = e.id OR r.from_id = e.id)
                    WHERE (r.from_id = ? OR r.to_id = ?) AND r.relation_type = ? AND e.id != ?""",
                    (entity_id, entity_id, entity_id, relation_type, entity_id)).fetchall()
            else:
                rows = conn.execute("""SELECT DISTINCT e.*, r.relation_type,
                    CASE WHEN r.from_id = ? THEN 'outgoing' ELSE 'incoming' END as direction
                    FROM entities e JOIN relations r ON (r.to_id = e.id OR r.from_id = e.id)
                    WHERE (r.from_id = ? OR r.to_id = ?) AND e.id != ?""",
                    (entity_id, entity_id, entity_id, entity_id)).fetchall()
            related = [{"id": r["id"], "entity_type": r["entity_type"],
                        "properties": json.loads(r["properties"]),
                        "relation_type": r["relation_type"], "direction": r["direction"]} for r in rows]
        return {"success": True, "related": related, "total": len(related)}

    def get_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            ec = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            rc = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
            tc = {}
            for r in conn.execute("SELECT entity_type, COUNT(*) as cnt FROM entities GROUP BY entity_type").fetchall():
                tc[r[0]] = r[1]
        return {"success": True, "entity_count": ec, "relation_count": rc, "type_counts": tc}

    def export_jsonl(self, output_path: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            entities = conn.execute("SELECT * FROM entities").fetchall()
            relations = conn.execute("SELECT * FROM relations").fetchall()
        with open(output_path, "w", encoding="utf-8") as f:
            for e in entities:
                f.write(json.dumps({"type": "entity", **dict(e)}, ensure_ascii=False) + "\n")
            for r in relations:
                f.write(json.dumps({"type": "relation", **dict(r)}, ensure_ascii=False) + "\n")
        return {"success": True, "path": output_path, "entities": len(entities), "relations": len(relations)}

    def import_jsonl(self, input_path: str) -> dict:
        ei = ri = 0
        with open(input_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                item = json.loads(line)
                with sqlite3.connect(self.db_path) as conn:
                    if item["type"] == "entity":
                        conn.execute("INSERT OR REPLACE INTO entities (id, entity_type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                                     (item["id"], item["entity_type"], item["properties"], item["created_at"], item["updated_at"]))
                        ei += 1
                    elif item["type"] == "relation":
                        conn.execute("INSERT OR REPLACE INTO relations (id, from_id, relation_type, to_id, properties, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                     (item["id"], item["from_id"], item["relation_type"], item["to_id"], item["properties"], item["created_at"]))
                        ri += 1
        return {"success": True, "entities_imported": ei, "relations_imported": ri}

    # ━━━ v6.0: 目标层级（AIRI goal hierarchy）━━━

    def create_goal(self, title: str, parent_goal_id: str = None,
                    properties: dict = None) -> dict:
        """创建目标实体。如果指定 parent_goal_id，自动建立 subgoal_of 关系。

        Args:
            title: 目标名称
            parent_goal_id: 父目标实体ID（可选）
            properties: 额外属性（priority, deadline, status 等）
        Returns:
            {"success": True, "id": "xxx", "goal": {...}, "parent_relation": {...}}
        """
        props = properties or {}
        props["title"] = title
        props.setdefault("status", "active")  # active / achieved / abandoned
        result = self.create_entity("goal", props)
        if not result.get("success"):
            return result

        goal_id = result["id"]
        response = {"success": True, "id": goal_id, "goal": result}

        if parent_goal_id:
            rel = self.create_relation(goal_id, "subgoal_of", parent_goal_id)
            response["parent_relation"] = rel

        return response

    def get_goal_tree(self, goal_id: str = None, max_depth: int = 3) -> dict:
        """获取目标层级树。

        Args:
            goal_id: 起始目标ID。None 则从顶层目标（无 subgoal_of 关系的）开始。
            max_depth: 最大递归深度
        Returns:
            {"success": True, "tree": [{goal, subgoals: [...]}]}
        """
        if goal_id:
            entity = self.get_entity(goal_id)
            if not entity.get("success"):
                return entity
            roots = [entity]
        else:
            # 找所有 goal 类型且没有 subgoal_of 关系的实体
            all_goals = self.list_entities("goal", limit=200)
            roots_data = all_goals.get("entities", [])
            # 过滤出没有 subgoal_of(outgoing) 的
            root_ids = set()
            for g in roots_data:
                root_ids.add(g["id"])
            for g in roots_data:
                related = self.get_related_entities(g["id"], "subgoal_of")
                for r in related.get("related", []):
                    if r["direction"] == "outgoing":
                        root_ids.discard(g["id"])
                        break
            roots = [self.get_entity(gid) for gid in root_ids]

        def build_tree(entity_dict, depth):
            if depth >= max_depth:
                return {"goal": entity_dict, "subgoals": [], "truncated": True}
            eid = entity_dict["id"]
            related = self.get_related_entities(eid, "subgoal_of")
            subgoals = []
            for r in related.get("related", []):
                if r["direction"] == "incoming":  # 别人指向我的 subgoal_of
                    child = self.get_entity(r["id"])
                    if child.get("success"):
                        subgoals.append(build_tree(child, depth + 1))
            return {"goal": entity_dict, "subgoals": subgoals}

        tree = [build_tree(r, 0) for r in roots if r.get("success")]
        return {"success": True, "tree": tree}

    def update_goal_status(self, goal_id: str, status: str) -> dict:
        """更新目标状态（active/achieved/abandoned）"""
        entity = self.get_entity(goal_id)
        if not entity.get("success"):
            return entity
        props = entity.get("properties", {})
        props["status"] = status
        props["status_updated_at"] = datetime.now().isoformat()
        return self.update_entity(goal_id, props)


class OntologyToolImplementations:
    def __init__(self, ontology: OntologyManager):
        self.ontology = ontology

    async def create_entity(self, entity_type: str, properties: dict) -> str:
        try:
            return json.dumps(self.ontology.create_entity(entity_type, properties), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def query_entity(self, entity_id: str) -> str:
        try:
            return json.dumps(self.ontology.get_entity(entity_id), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def link_entities(self, from_id: str, relation_type: str, to_id: str) -> str:
        try:
            return json.dumps(self.ontology.create_relation(from_id, relation_type, to_id), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def search_entities(self, entity_type: str = None, conditions: dict = None) -> str:
        try:
            return json.dumps(self.ontology.list_entities(entity_type, limit=50), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def get_related(self, entity_id: str, relation_type: str = None) -> str:
        try:
            return json.dumps(self.ontology.get_related_entities(entity_id, relation_type), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def get_stats(self) -> str:
        try:
            return json.dumps(self.ontology.get_stats(), ensure_ascii=False, indent=2)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# AstrBot Agent Tools
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
import astrbot.api.star as star
from astrbot.api.event.filter import llm_tool
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.astr_agent_context import AstrAgentContext
from typing import Any
from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass


@pydantic_dataclass
class OntologyCreateEntityTool(FunctionTool[AstrAgentContext]):
    """创建实体到知识图谱"""
    plugin: Any = None
    name: str = "haruyuki_ontology_create"
    description: str = "创建实体到知识图谱。参数：entity_type(实体类型), properties(属性JSON)"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "description": "实体类型"},
                "properties": {"type": "string", "description": "属性JSON字符串"}
            },
            "required": ["entity_type", "properties"]
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        entity_type = kwargs.get("entity_type")
        props = json.loads(kwargs.get("properties", "{}"))
        result = await self.plugin.ontology_impl.create_entity(entity_type, props)
        return result


@pydantic_dataclass
class OntologyQueryEntityTool(FunctionTool[AstrAgentContext]):
    """查询实体详情"""
    plugin: Any = None
    name: str = "haruyuki_ontology_query"
    description: str = "查询实体详情。参数：entity_id(实体ID)"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体ID"}
            },
            "required": ["entity_id"]
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        entity_id = kwargs.get("entity_id")
        result = await self.plugin.ontology_impl.query_entity(entity_id)
        return result


@pydantic_dataclass
class OntologyLinkEntitiesTool(FunctionTool[AstrAgentContext]):
    """关联两个实体"""
    plugin: Any = None
    name: str = "haruyuki_ontology_link"
    description: str = "关联两个实体。参数：from_id, relation_type, to_id"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "from_id": {"type": "string", "description": "源实体ID"},
                "relation_type": {"type": "string", "description": "关系类型"},
                "to_id": {"type": "string", "description": "目标实体ID"}
            },
            "required": ["from_id", "relation_type", "to_id"]
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        from_id = kwargs.get("from_id")
        relation_type = kwargs.get("relation_type")
        to_id = kwargs.get("to_id")
        result = await self.plugin.ontology_impl.link_entities(from_id, relation_type, to_id)
        return result


@pydantic_dataclass
class OntologySearchEntitiesTool(FunctionTool[AstrAgentContext]):
    """搜索实体"""
    plugin: Any = None
    name: str = "haruyuki_ontology_search"
    description: str = "搜索实体。参数：entity_type(可选), conditions(可选,JSON)"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "description": "实体类型(可选)"},
                "conditions": {"type": "string", "description": "条件JSON(可选)"}
            },
            "required": []
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        entity_type = kwargs.get("entity_type")
        conditions = kwargs.get("conditions")
        props = json.loads(conditions) if conditions else None
        result = await self.plugin.ontology_impl.search_entities(entity_type, props)
        return result


@pydantic_dataclass
class OntologyGetRelatedTool(FunctionTool[AstrAgentContext]):
    """获取实体的相关实体"""
    plugin: Any = None
    name: str = "haruyuki_ontology_related"
    description: str = "获取实体的相关实体。参数：entity_id, relation_type(可选)"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "实体ID"},
                "relation_type": {"type": "string", "description": "关系类型(可选)"}
            },
            "required": ["entity_id"]
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        entity_id = kwargs.get("entity_id")
        relation_type = kwargs.get("relation_type")
        result = await self.plugin.ontology_impl.get_related(entity_id, relation_type)
        return result


@pydantic_dataclass
class OntologyStatsTool(FunctionTool[AstrAgentContext]):
    """获取知识图谱统计信息"""
    plugin: Any = None
    name: str = "haruyuki_ontology_stats"
    description: str = "获取知识图谱统计信息"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "required": []
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        result = await self.plugin.ontology_impl.get_stats()
        return result


@pydantic_dataclass
class OntologyUnifiedTool(FunctionTool[AstrAgentContext]):
    """知识图谱统一工具（v6.9 八合一：替代原 create/query/link/search/related/stats 六件套）"""
    plugin: Any = None
    name: str = "haruyuki_ontology"
    description: str = ("知识图谱操作统一入口。action 可选: create(创建实体,需entity_type+properties) / query(查实体详情,需entity_id) / update(改实体属性,需entity_id+properties) / delete(删实体,需entity_id) / search(按类型列实体,可选entity_type) / link(建关系,需from_id+relation_type+to_id) / related(查关联实体,需entity_id,可选relation_type) / stats(图谱统计)。当橘子提到实体、关系、知识图谱时使用。")
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "create/query/update/delete/search/link/related/stats", "enum": ["create", "query", "update", "delete", "search", "link", "related", "stats"]},
                "entity_type": {"type": "string", "description": "实体类型(create/search用)"},
                "properties_json": {"type": "string", "description": "属性JSON字符串(create/update用)"},
                "entity_id": {"type": "string", "description": "实体ID(query/update/delete/related用)"},
                "from_id": {"type": "string", "description": "源实体ID(link用)"},
                "relation_type": {"type": "string", "description": "关系类型(link用,可选related用)"},
                "to_id": {"type": "string", "description": "目标实体ID(link用)"}
            },
            "required": ["action"]
        }
    )
    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> str:
        action = str(kwargs.get("action", "")).strip().lower()
        impl = self.plugin.ontology_impl
        mgr = self.plugin.ontology
        try:
            if action == "create":
                entity_type = kwargs.get("entity_type")
                if not entity_type: return "create 需要 entity_type"
                props = json.loads(kwargs.get("properties_json", "{}") or "{}")
                return await impl.create_entity(entity_type, props)
            if action == "query":
                entity_id = kwargs.get("entity_id")
                if not entity_id: return "query 需要 entity_id"
                return await impl.query_entity(entity_id)
            if action == "update":
                entity_id = kwargs.get("entity_id")
                if not entity_id: return "update 需要 entity_id"
                props = json.loads(kwargs.get("properties_json", "{}") or "{}")
                return json.dumps(mgr.update_entity(entity_id, props), ensure_ascii=False, indent=2)
            if action == "delete":
                entity_id = kwargs.get("entity_id")
                if not entity_id: return "delete 需要 entity_id"
                ok = mgr.delete_entity(entity_id)
                return f"✅ 实体 {entity_id} 已删除" if ok else f"未找到实体 {entity_id}"
            if action == "search":
                entity_type = kwargs.get("entity_type") or None
                return await impl.search_entities(entity_type)
            if action == "link":
                from_id, rt, to_id = kwargs.get("from_id"), kwargs.get("relation_type"), kwargs.get("to_id")
                if not (from_id and rt and to_id): return "link 需要 from_id + relation_type + to_id"
                return await impl.link_entities(from_id, rt, to_id)
            if action == "related":
                entity_id = kwargs.get("entity_id")
                if not entity_id: return "related 需要 entity_id"
                return await impl.get_related(entity_id, kwargs.get("relation_type") or None)
            if action == "stats":
                return await impl.get_stats()
            return "未知 action: " + action + "（可选 create/query/update/delete/search/link/related/stats）"
        except json.JSONDecodeError as e:
            return "properties_json 不是合法 JSON: " + str(e)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
