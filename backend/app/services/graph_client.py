from typing import Any

from neo4j import GraphDatabase

from backend.app.config import settings


ALLOWED_NODE_LABELS = {"CKP", "PKU", "Source", "Entity", "Alias"}
ALLOWED_RELATIONSHIP_TYPES = {
    "HAS_CHILD",
    "SUPPORTED_BY",
    "RELATED_TO",
    "EVIDENCED_BY",
    "MENTIONS_ENTITY",
    "ABOUT_ENTITY",
    "MENTIONED_IN",
    "ALIAS_OF",
    "AUTHORED",
    "AFFILIATED_WITH",
    "EDUCATED_AT",
    "HAS_EMAIL",
    "CO_AUTHOR",
}


class GraphClient:
    def __init__(self, driver=None, database: str | None = None):
        self.driver = driver or GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
        self.database = database or settings.NEO4J_DATABASE

    def close(self) -> None:
        close = getattr(self.driver, "close", None)
        if close:
            close()

    def upsert_ckp(self, data: dict[str, Any]) -> None:
        self._upsert_node(
            "CKP",
            data,
            ["user_id", "title", "ckp_type", "status", "confidence"],
        )

    def upsert_pku(self, data: dict[str, Any]) -> None:
        self._upsert_node(
            "PKU",
            data,
            ["user_id", "unit_type", "statement_hash", "confidence", "status"],
        )

    def upsert_source(self, data: dict[str, Any]) -> None:
        self._upsert_node(
            "Source",
            data,
            ["source_kind", "source_id", "item_id", "title"],
        )

    def upsert_entity(self, data: dict[str, Any]) -> None:
        self._upsert_node(
            "Entity",
            data,
            [
                "user_id",
                "entity_type",
                "canonical_name",
                "normalized_key",
                "status",
                "confidence",
            ],
        )

    def upsert_alias(self, data: dict[str, Any]) -> None:
        alias_data = dict(data)
        entity_id = alias_data.get("entity_id")
        if "id" not in alias_data and entity_id and alias_data.get("key"):
            alias_data["id"] = f"{entity_id}:{alias_data['key']}"
        alias_data.setdefault("entity_id", None)

        query = """
        MERGE (n:Alias {id: $id})
        SET n += {key: $key, surface_text: $surface_text, entity_id: $entity_id}
        """
        self._execute_write(query, alias_data)

        if entity_id:
            self.relate("Alias", alias_data["id"], "ALIAS_OF", "Entity", entity_id)

    def relate(
        self,
        start_label: str,
        start_id: str,
        rel_type: str,
        end_label: str,
        end_id: str,
        props: dict[str, Any] | None = None,
    ) -> None:
        self._validate_label(start_label)
        self._validate_label(end_label)
        self._validate_relationship_type(rel_type)

        query = f"""
        MATCH (a:{start_label} {{id: $start_id}})
        MATCH (b:{end_label} {{id: $end_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        SET r += $props
        """
        self._execute_write(
            query,
            {"start_id": start_id, "end_id": end_id, "props": props or {}},
        )

    def delete_item_sources(self, item_id: str) -> None:
        """Delete all :Source nodes (and their edges) for one item. Idempotent."""
        query = """
        MATCH (s:Source {item_id: $item_id})
        DETACH DELETE s
        """
        self._execute_write(query, {"item_id": item_id})

    def _upsert_node(self, label: str, data: dict[str, Any], fields: list[str]) -> None:
        self._validate_label(label)
        assignments = ", ".join(f"{field}: ${field}" for field in fields)
        query = f"""
        MERGE (n:{label} {{id: $id}})
        SET n += {{{assignments}}}
        """
        self._execute_write(query, data)

    def _execute_write(self, query: str, params: dict[str, Any]) -> None:
        with self.driver.session(database=self.database) as session:
            session.execute_write(lambda tx: tx.run(query, **params))

    @staticmethod
    def _validate_label(label: str) -> None:
        if label not in ALLOWED_NODE_LABELS:
            raise ValueError(f"Invalid Neo4j node label: {label}")

    @staticmethod
    def _validate_relationship_type(rel_type: str) -> None:
        if rel_type not in ALLOWED_RELATIONSHIP_TYPES:
            raise ValueError(f"Invalid Neo4j relationship type: {rel_type}")
