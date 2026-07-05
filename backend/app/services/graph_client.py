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

    def _execute_read(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        with self.driver.session(database=self.database) as session:
            return session.execute_read(lambda tx: tx.run(query, **(params or {})).data())

    def read_entity_communities(self) -> dict[str, int]:
        """Return {entity_id: community_id} for entities that already have one."""
        rows = self._execute_read(
            "MATCH (e:Entity) WHERE e.community_id IS NOT NULL "
            "RETURN e.id AS id, e.community_id AS cid"
        )
        return {r["id"]: r["cid"] for r in rows if r.get("id") is not None}

    def neighbors(self, entity_id: str, hops: int = 1, limit: int = 8) -> list[dict]:
        """Return [{id, kind}] for nodes within `hops` of entity_id (Entity/Source)."""
        query = """
        // neighbors
        MATCH (e:Entity {id: $entity_id})-[:MENTIONED_IN|RELATED_TO*1..%d]-(n)
        WHERE n.id IS NOT NULL AND n.id <> $entity_id
        RETURN DISTINCT n.id AS id,
               CASE WHEN 'Entity' IN labels(n) THEN 'Entity'
                    WHEN 'Source'  IN labels(n) THEN 'Source'
                    ELSE head(labels(n)) END AS kind
        LIMIT $limit
        """ % max(1, int(hops))
        return self._execute_read(query, {"entity_id": entity_id, "limit": limit})

    def community_members(self, community_id: int, limit: int = 10) -> list[dict]:
        query = """
        // community_members
        MATCH (e:Entity {community_id: $cid})
        RETURN e.id AS id LIMIT $limit
        """
        return self._execute_read(query, {"cid": int(community_id), "limit": limit})

    def god_neighbors(self, entity_id: str, limit: int = 10) -> list[str]:
        """Return ids of god entities adjacent to entity_id."""
        query = """
        // god_neighbors
        MATCH (e:Entity {id: $entity_id})-[:RELATED_TO|MENTIONED_IN]-(g:Entity {is_god: true})
        RETURN DISTINCT g.id AS id LIMIT $limit
        """
        return [r["id"] for r in self._execute_read(query, {"entity_id": entity_id, "limit": limit}) if r.get("id")]

    def surprising_endpoints(self, entity_id: str) -> list[str]:
        """Return ids of entities connected to entity_id via a surprising edge."""
        query = """
        // surprising
        MATCH (e:Entity {id: $entity_id})-[r:RELATED_TO {surprising: true}]-(o:Entity)
        RETURN DISTINCT o.id AS id
        """
        return [r["id"] for r in self._execute_read(query, {"entity_id": entity_id}) if r.get("id")]

    def set_entity_analysis(self, entity_id: str, community_id: int, is_god: bool, cohesion: float) -> None:
        query = """
        MATCH (e:Entity {id: $entity_id})
        SET e.community_id = $community_id,
            e.is_god = $is_god,
            e.cohesion = $cohesion
        """
        self._execute_write(
            query,
            {
                "entity_id": entity_id,
                "community_id": community_id,
                "is_god": is_god,
                "cohesion": cohesion,
            },
        )

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
