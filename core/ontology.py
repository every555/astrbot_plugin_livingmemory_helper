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
