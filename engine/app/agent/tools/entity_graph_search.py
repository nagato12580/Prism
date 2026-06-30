from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from engine.app.config import settings
from engine.app.agent.tools.base import ToolContext, ToolSpec, register_tool

try:
    from pypinyin import lazy_pinyin
except ImportError:
    lazy_pinyin = None


KEY = "entity_graph_search"
_ENTITY_KEY_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_TWO_LATIN_WORDS_RE = re.compile(r"^([A-Za-z]+)\s+([A-Za-z]+)$")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


class EntityGraphSearchInput(BaseModel):
    query: str = Field(..., description="Entity name, alias, or compact normalized key to search.")
    limit: int = Field(8, ge=1, le=20, description="Maximum number of graph entities, sources, and paths to return.")


def _normalize_entity_key(text: str) -> str:
    return _ENTITY_KEY_RE.sub("", text.strip().lower())


def _pinyin_keys(text: str) -> list[str]:
    if lazy_pinyin is None or not _CHINESE_RE.search(text):
        return []
    parts = lazy_pinyin(text)
    joined = "".join(parts).lower()
    joined = re.sub(r"[^a-z0-9]+", "", joined)
    if not joined:
        return []
    return [joined]


def _alias_keys(query: str) -> list[str]:
    stripped = query.strip()
    keys = [_normalize_entity_key(stripped)]
    match = _TWO_LATIN_WORDS_RE.match(stripped)
    if match:
        first, second = match.groups()
        keys.extend(
            [
                _normalize_entity_key(f"{first}{second}"),
                _normalize_entity_key(f"{second}{first}"),
            ]
        )
    keys.extend(_pinyin_keys(stripped))

    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def _plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}


def _source_dict(value: Any) -> dict[str, Any]:
    data = _plain_dict(value)
    if data and not data.get("snippet") and data.get("evidence_span"):
        data["snippet"] = data["evidence_span"]
    return data


class Neo4jEntityQueryClient:
    def __init__(self, driver: Any | None = None, database: str | None = None):
        if driver is None:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        self.driver = driver
        self.database = database or settings.NEO4J_DATABASE

    def query_entity_context(self, normalized_keys: list[str], limit: int) -> dict[str, Any]:
        query = """
        WITH $keys AS keys
        OPTIONAL MATCH (direct_entity:Entity)
        WHERE direct_entity.normalized_key IN keys
        WITH keys, collect(DISTINCT direct_entity) AS direct_entities
        OPTIONAL MATCH (matched_alias:Alias)-[:ALIAS_OF]->(aliased_entity:Entity)
        WHERE matched_alias.normalized_key IN keys OR matched_alias.key IN keys
        WITH direct_entities, collect(DISTINCT aliased_entity) AS alias_entities
        WITH direct_entities + alias_entities AS all_entities
        UNWIND all_entities AS entity
        WITH DISTINCT entity
        WHERE entity IS NOT NULL
        WITH collect(DISTINCT entity)[..$limit] AS entities
        UNWIND entities AS e
        OPTIONAL MATCH (e)-[mention:MENTIONED_IN]->(source)
        WITH entities, collect(DISTINCT source {
            .*,
            evidence_span: mention.evidence_span,
            snippet: coalesce(source.snippet, mention.evidence_span),
            confidence: mention.confidence,
            extraction_method: mention.extraction_method,
            source_kind: coalesce(source.source_kind, mention.source_kind),
            source_id: coalesce(source.source_id, mention.source_id)
        })[..$limit] AS sources
        UNWIND entities AS e2
        OPTIONAL MATCH (e2)-[rel]-(neighbor:Entity)
        WITH entities, sources, collect(DISTINCT {
            from: coalesce(e2.canonical_name, e2.name),
            relation_type: type(rel),
            to: coalesce(neighbor.canonical_name, neighbor.name)
        })[..$limit] AS paths
        RETURN entities, sources, paths
        """
        params = {"keys": normalized_keys, "limit": limit}
        with self.driver.session(database=self.database) as session:
            records = list(session.run(query, params))

        entities: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        paths: list[dict[str, Any]] = []
        for record in records:
            for entity in record.get("entities", []) or []:
                data = _plain_dict(entity)
                if data:
                    entities.append(data)
            for source in record.get("sources", []) or []:
                data = _source_dict(source)
                if data:
                    sources.append(data)
            for path in record.get("paths", []) or []:
                data = _plain_dict(path)
                rel_type = data.get("relation_type")
                from_name = data.get("from")
                to_name = data.get("to")
                if rel_type and from_name and to_name:
                    paths.append(
                        {
                            "path": [from_name, rel_type, to_name],
                            "relation_type": rel_type,
                        }
                    )
        return {"entities": entities, "sources": sources, "paths": paths}

    def close(self) -> None:
        close = getattr(self.driver, "close", None)
        if close is not None:
            close()


class EntityGraphSearchService:
    def __init__(self, client: Any | None = None):
        self.client = client if client is not None else Neo4jEntityQueryClient()

    def search_entity_context(self, query: str, limit: int = 8) -> dict[str, Any]:
        normalized_keys = _alias_keys(query)
        if not normalized_keys:
            return {
                "status": "insufficient",
                "summary": "Entity graph search requires a non-empty entity query.",
                "entities": [],
                "sources": [],
                "paths": [],
                "normalized_keys": normalized_keys,
            }
        try:
            payload = self.client.query_entity_context(normalized_keys, limit)
        except Exception as exc:
            return {
                "status": "error",
                "summary": f"Entity graph search failed: {exc}",
                "entities": [],
                "sources": [],
                "paths": [],
                "normalized_keys": normalized_keys,
            }
        entities = list(payload.get("entities", []))
        sources = list(payload.get("sources", []))
        paths = list(payload.get("paths", []))
        status = "success" if entities or sources else "insufficient"
        return {
            "status": status,
            "summary": payload.get("summary") or _summary(status, entities, sources, paths),
            "entities": entities,
            "sources": sources,
            "paths": paths,
            "normalized_keys": normalized_keys,
        }


def _summary(
    status: str,
    entities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    paths: list[dict[str, Any]],
) -> str:
    if status == "success":
        return (
            f"Found {len(entities)} entity result(s), "
            f"{len(sources)} source(s), and {len(paths)} path(s)."
        )
    return "No entity graph context found for the normalized query keys."


def _citation_key(source: Any) -> tuple[Any, Any, Any]:
    if isinstance(source, dict):
        return (
            source.get("source_kind"),
            source.get("source_id"),
            source.get("snippet"),
        )
    return (None, None, repr(source))


def build(ctx: ToolContext, graph_search: Any | None = None) -> StructuredTool:
    service = graph_search if graph_search is not None else EntityGraphSearchService()

    def run(query: str, limit: int = 8) -> str:
        payload = service.search_entity_context(query, limit=limit)
        sources = list(payload.get("sources", []))
        citation_keys = {_citation_key(source) for source in ctx.citations}
        for source in sources:
            key = _citation_key(source)
            if key not in citation_keys:
                ctx.citations.append(source)
                citation_keys.add(key)
        ctx.stats_holder[KEY] = {
            "entity_count": len(payload.get("entities", [])),
            "source_count": len(sources),
            "path_count": len(payload.get("paths", [])),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Search the entity graph for people, organizations, papers, aliases, "
            "and source-backed paths. Use before declaring a named entity absent."
        ),
        args_schema=EntityGraphSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description=(
            "Search the entity graph for people, organizations, papers, aliases, "
            "and source-backed paths. Use before declaring a named entity absent."
        ),
        builder=build,
        default_enabled=True,
    )
)
