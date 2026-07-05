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
_STOP_TERMS = {
    "什么",
    "哪些",
    "哪个",
    "多少",
    "如何",
    "怎么",
    "相关",
    "资料",
    "知识点",
    "出处",
    "出现",
    "提到",
    "关联",
    "里",
    "的",
    "与",
    "和",
    "or",
    "and",
    "the",
    "what",
    "which",
    "where",
    "related",
}


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


def _query_terms(query: str) -> list[str]:
    stripped = query.strip()
    if not stripped:
        return []
    terms: list[str] = []
    lowered = stripped.lower()
    for token in re.findall(r"[A-Za-z0-9._%+-@]+|[\u4e00-\u9fff]{2,}", lowered):
        token = token.strip()
        if not token or token in _STOP_TERMS:
            continue
        if len(token) == 1:
            continue
        terms.append(token)
    # Also add normalized compact key for mixed/scripted entity names.
    normalized = _normalize_entity_key(stripped)
    if normalized and normalized not in terms and normalized not in _STOP_TERMS:
        terms.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term not in seen:
            deduped.append(term)
            seen.add(term)
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


def _dedupe_dicts(items: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key_values: list[Any] = []
        for field in key_fields:
            value = item.get(field)
            if isinstance(value, list):
                value = tuple(value)
            elif isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            key_values.append(value)
        key = tuple(key_values)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _text_term_hits(text: str, query_terms: list[str]) -> int:
    lowered = (text or "").lower()
    return sum(1 for term in query_terms if term and term in lowered)


def _score_governed_path(path: dict[str, Any], query_terms: list[str]) -> tuple[int, float, float, float, str]:
    title_hits = _text_term_hits(str(path.get("ckp_title") or ""), query_terms)
    support = float(path.get("support_confidence") or 0.0)
    ckp_conf = float(path.get("ckp_confidence") or 0.0)
    pku_conf = float(path.get("pku_confidence") or 0.0)
    title = str(path.get("ckp_title") or "")
    return (title_hits, support, ckp_conf, pku_conf, title)


def _score_source(source: dict[str, Any], governed_paths: list[dict[str, Any]], query_terms: list[str]) -> tuple[int, int, float, float, str]:
    source_kind = source.get("source_kind")
    source_id = source.get("source_id")
    matching_paths = [
        path
        for path in governed_paths
        if path.get("source_kind") == source_kind and path.get("source_id") == source_id
    ]
    governed_count = len(matching_paths)
    text_hits = _text_term_hits(str(source.get("title") or source.get("snippet") or ""), query_terms)
    best_support = max((float(path.get("support_confidence") or 0.0) for path in matching_paths), default=0.0)
    source_conf = float(source.get("confidence") or 0.0)
    title = str(source.get("title") or source.get("snippet") or "")
    return (governed_count, text_hits, best_support, source_conf, title)


def _score_entity_path(path: dict[str, Any], governed_paths: list[dict[str, Any]]) -> tuple[int, str, str]:
    path_nodes = path.get("path") or []
    entity_name = str(path_nodes[0] if path_nodes else "")
    governed_count = sum(1 for item in governed_paths if item.get("entity_name") == entity_name)
    relation_type = str(path.get("relation_type") or "")
    display = " ".join(str(part) for part in path_nodes)
    return (governed_count, relation_type, display)


def _rank_governed_paths(governed_paths: list[dict[str, Any]], query_terms: list[str], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(governed_paths, key=lambda item: _score_governed_path(item, query_terms), reverse=True)
    return _dedupe_dicts(ranked, ("entity_name", "pku_id", "ckp_id", "source_kind", "source_id"))[:limit]


def _rank_sources(sources: list[dict[str, Any]], governed_paths: list[dict[str, Any]], query_terms: list[str], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(sources, key=lambda item: _score_source(item, governed_paths, query_terms), reverse=True)
    return _dedupe_dicts(ranked, ("source_kind", "source_id", "snippet"))[:limit]


def _rank_entity_paths(paths: list[dict[str, Any]], governed_paths: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(paths, key=lambda item: _score_entity_path(item, governed_paths), reverse=True)
    return _dedupe_dicts(ranked, ("relation_type", "path"))[:limit]


def _unique_non_empty(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
        if len(deduped) >= limit:
            break
    return deduped


def _query_aware_summary(
    status: str,
    query: str,
    entities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    governed_paths: list[dict[str, Any]],
) -> str:
    if status != "success":
        return "No entity graph context found for the normalized query keys."

    entity_names = _unique_non_empty(
        [str(entity.get("canonical_name") or entity.get("name") or "") for entity in entities],
        limit=2,
    )
    ckp_titles = _unique_non_empty(
        [str(item.get("ckp_title") or "") for item in governed_paths],
        limit=3,
    )
    source_titles = _unique_non_empty(
        [str(source.get("title") or source.get("snippet") or "") for source in sources],
        limit=2,
    )

    entity_part = ", ".join(entity_names) if entity_names else query.strip()
    ckp_part = ", ".join(ckp_titles)
    source_part = ", ".join(source_titles)

    if governed_paths:
        summary = (
            f"Found entity context for {entity_part}. "
            f"Most relevant knowledge points: {ckp_part}."
        )
        if source_part:
            summary += f" Source-backed evidence appears in: {source_part}."
        summary += (
            f" Returned {len(governed_paths)} CKP/PKU path(s), {len(sources)} source(s), "
            f"and {len(paths)} entity path(s)."
        )
        return summary

    if sources:
        summary = f"Found entity context for {entity_part}."
        if source_part:
            summary += f" Source-backed evidence appears in: {source_part}."
        summary += f" Returned {len(sources)} source(s) and {len(paths)} entity path(s)."
        return summary

    return (
        f"Found entity context for {entity_part}. "
        f"Returned {len(paths)} entity path(s), but no source-backed or CKP/PKU evidence was found."
    )


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
        UNWIND entities AS e3
        OPTIONAL MATCH (e3)<-[bridge:MENTIONS_ENTITY]-(pku:PKU)<-[support:SUPPORTED_BY]-(ckp:CKP)
        WITH entities, sources, paths,
             collect(DISTINCT {
                 entity_name: coalesce(e3.canonical_name, e3.name),
                 pku_id: pku.id,
                 pku_unit_type: pku.unit_type,
                 ckp_id: ckp.id,
                 ckp_title: ckp.title,
                 source_kind: bridge.source_kind,
                 source_id: bridge.source_id,
                 pku_confidence: pku.confidence,
                 ckp_confidence: ckp.confidence,
                 support_role: support.role,
                 support_confidence: support.confidence
             })[..$limit] AS governed_paths
        RETURN entities, sources, paths, governed_paths
        """
        params = {"keys": normalized_keys, "limit": limit}
        with self.driver.session(database=self.database) as session:
            records = list(session.run(query, params))

        entities: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        paths: list[dict[str, Any]] = []
        governed_paths: list[dict[str, Any]] = []
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
            for governed_path in record.get("governed_paths", []) or []:
                data = _plain_dict(governed_path)
                if data.get("pku_id") and data.get("ckp_id"):
                    governed_paths.append(data)
        return {
            "entities": entities,
            "sources": sources,
            "paths": paths,
            "governed_paths": governed_paths,
        }

    def close(self) -> None:
        close = getattr(self.driver, "close", None)
        if close is not None:
            close()


class EntityGraphSearchService:
    def __init__(self, client: Any | None = None):
        self.client = client if client is not None else Neo4jEntityQueryClient()

    def search_entity_context(self, query: str, limit: int = 8) -> dict[str, Any]:
        normalized_keys = _alias_keys(query)
        query_terms = _query_terms(query)
        if not normalized_keys:
            return {
                "status": "insufficient",
                "summary": "Entity graph search requires a non-empty entity query.",
                "entities": [],
                "sources": [],
                "paths": [],
                "governed_paths": [],
                "normalized_keys": normalized_keys,
                "query_terms": query_terms,
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
                "governed_paths": [],
                "normalized_keys": normalized_keys,
                "query_terms": query_terms,
            }
        entities = list(payload.get("entities", []))
        governed_paths = _rank_governed_paths(list(payload.get("governed_paths", [])), query_terms, limit)
        sources = _rank_sources(list(payload.get("sources", [])), governed_paths, query_terms, limit)
        paths = _rank_entity_paths(list(payload.get("paths", [])), governed_paths, limit)
        status = "success" if entities or sources or governed_paths else "insufficient"
        summary = _query_aware_summary(status, query, entities, sources, paths, governed_paths)
        return {
            "status": status,
            "summary": summary,
            "entities": entities,
            "sources": sources,
            "paths": paths,
            "governed_paths": governed_paths,
            "normalized_keys": normalized_keys,
            "query_terms": query_terms,
        }


def _summary(
    status: str,
    entities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    governed_paths: list[dict[str, Any]],
) -> str:
    if status == "success":
        if governed_paths:
            ckp_titles = [str(item.get("ckp_title") or "") for item in governed_paths if item.get("ckp_title")]
            unique_titles: list[str] = []
            seen_titles: set[str] = set()
            for title in ckp_titles:
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                unique_titles.append(title)
            preview = ", ".join(unique_titles[:3])
            more = len(unique_titles) - min(len(unique_titles), 3)
            suffix = f" (+{more} more)" if more > 0 else ""
            return (
                f"Found {len(entities)} entity result(s), {len(governed_paths)} CKP/PKU path(s), "
                f"and {len(sources)} source(s). Related knowledge points: {preview}{suffix}."
            )
        return (
            f"Found {len(entities)} entity result(s), "
            f"{len(sources)} source(s), {len(paths)} entity path(s), "
            f"and {len(governed_paths)} CKP/PKU path(s)."
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
        if not payload.get("summary"):
            payload["summary"] = _query_aware_summary(
                payload.get("status", "insufficient"),
                query,
                list(payload.get("entities", [])),
                list(payload.get("sources", [])),
                list(payload.get("paths", [])),
                list(payload.get("governed_paths", [])),
            )
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
            "governed_path_count": len(payload.get("governed_paths", [])),
        }
        return json.dumps(payload, ensure_ascii=False)

    return StructuredTool.from_function(
        func=run,
        name=KEY,
        description=(
            "Search the entity graph (Neo4j) for people, organizations, papers, aliases, and source-backed "
            "multi-hop paths. Use when the user asks whether a named entity exists, who/what it relates to, "
            "or which sources mention it — and ALWAYS use it before declaring a named entity absent. "
            "Do NOT use to filter CKP topics by type — use knowledge_topic_search. "
            "Do NOT use for semantic evidence recall — use knowledge_evidence_search or governed_knowledge_v2."
        ),
        args_schema=EntityGraphSearchInput,
    )


register_tool(
    ToolSpec(
        key=KEY,
        name=KEY,
        description=(
            "Search the entity graph (Neo4j) for people, organizations, papers, aliases, and source-backed "
            "multi-hop paths. Use when the user asks whether a named entity exists, who/what it relates to, "
            "or which sources mention it — and ALWAYS use it before declaring a named entity absent. "
            "Do NOT use to filter CKP topics by type — use knowledge_topic_search. "
            "Do NOT use for semantic evidence recall — use knowledge_evidence_search or governed_knowledge_v2."
        ),
        builder=build,
        default_enabled=True,
    )
)
