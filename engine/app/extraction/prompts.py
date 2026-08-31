"""Stage A entity extraction prompt and JSON parsing.

graphify-style discipline: three confidence tiers (EXTRACTED/INFERRED/AMBIGUOUS),
discrete score set (EXTRACTED=1.0; INFERRED in {0.95,0.85,0.75,0.65,0.55}; AMBIGUOUS in [0.1,0.3]).
Score 0.5 is forbidden.
"""
import json
import re

import json_repair

# Stage A extracts entities AND inter-entity relations. Relations give the graph
# the connective tissue that community detection (Step B) needs.
#
# The prompt is split into a fixed skeleton (DEFAULT_STAGE_A_PROMPT) and a
# versionable schema (ENTITY_TYPE_SCHEMA) so the entity-type enumeration can
# evolve without touching the extraction task wording. build_prompt() assembles
# them; STAGE_A_EXTRACTION_PROMPT stays as the fully-assembled template for
# callers that still .format(chunk_text=...) it.
DEFAULT_STAGE_A_PROMPT = """你是知识图谱实体抽取器。从下面的文本片段中抽取「实体」和「实体间关系」。

{schema}

每个实体输出一个对象，字段：
- entity_type: 实体类型（见 schema 枚举）
- surface: 实体在原文中的表面文本（原样，不要改写）
- tier: 置信档，三选一：EXTRACTED（原文直接出现）/ INFERRED（推断）/ AMBIGUOUS（不确定）
- score: 置信分数。EXTRACTED 必须 1.0；INFERRED 取 0.95/0.85/0.75/0.65/0.55 之一；AMBIGUOUS 取 0.1~0.3。禁止 0.5。
- evidence: 原文中支持该实体的短语（原文摘录，<=80字）

若两个实体有明显关系，输出 relations 数组，每个对象：
- subject / object：实体的 surface（必须与 entities 里的 surface 一致）
- predicate：related_to/uses/part_of/defines/supports/contradicts/alternative_to/depends_on 等
- tier / score：同上规则

只输出一个 JSON 对象，形如：
{{"entities": [{{"entity_type":"...","surface":"...","tier":"...","score":1.0,"evidence":"..."}}], "relations": [{{"subject":"...","predicate":"...","object":"...","tier":"...","score":0.85}}]}}
不要输出 JSON 以外的任何文字。

文本片段：
{chunk_text}
"""

ENTITY_TYPE_SCHEMA = """抽取范围（尽量全）：概念、术语、方法、产品、技术、人物、机构、地点、法规、数据集、工具等。
不要只抽人名/机构——这是通用知识库，概念和术语同样重要。
entity_type 枚举：concept/term/method/product/technology/person/organization/place/regulation/dataset/tool/other"""


def build_prompt(chunk_text: str, schema: str = ENTITY_TYPE_SCHEMA) -> str:
    """Assemble the Stage A extraction prompt from skeleton + schema + chunk."""
    return DEFAULT_STAGE_A_PROMPT.format(schema=schema, chunk_text=chunk_text)


STAGE_A_EXTRACTION_PROMPT = DEFAULT_STAGE_A_PROMPT.format(schema=ENTITY_TYPE_SCHEMA, chunk_text="{chunk_text}")

_VALID_SCORES_INFERRED = {0.95, 0.85, 0.75, 0.65, 0.55}


def _extract_json_object(raw: str) -> str | None:
    """Find the first {...} or [...] JSON block, tolerating ```json fences."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.S)
    if fenced:
        return fenced.group(1)
    match = re.search(r"\{.*\}|\[.*\]", raw, re.S)
    return match.group(0) if match else None


def _valid_entity(item: dict) -> bool:
    tier = item.get("tier")
    score = item.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        return False
    if tier == "EXTRACTED":
        return abs(score - 1.0) < 1e-6
    if tier == "INFERRED":
        return any(abs(score - s) < 1e-6 for s in _VALID_SCORES_INFERRED)
    if tier == "AMBIGUOUS":
        return 0.1 <= score <= 0.3
    return False


def _parse_json(raw: str) -> dict | list | None:
    """Parse model output to JSON, tolerating malformed JSON and prose.

    json_repair handles trailing commas / unquoted keys / surrounding prose;
    the regex extractor below is the last-resort fallback for markdown fences.
    """
    if not raw or not raw.strip():
        return None
    try:
        return json_repair.loads(raw)
    except Exception:
        pass
    blob = _extract_json_object(raw)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def parse_stage_a_json(raw: str) -> list[dict]:
    """Parse model output into a validated list of entity dicts.

    Accepts either {"entities":[...]} or a bare [...]. Drops invalid tier/score.
    Returns normalized dicts with keys: entity_type, surface, tier, score, evidence.
    """
    data = _parse_json(raw)
    if data is None:
        return []
    entities = data["entities"] if isinstance(data, dict) else data
    if not isinstance(entities, list):
        return []
    result = []
    for item in entities:
        if not isinstance(item, dict) or not _valid_entity(item):
            continue
        surface = (item.get("surface") or item.get("surface_text") or "").strip()
        if not surface:
            continue
        result.append(
            {
                "entity_type": (item.get("entity_type") or "other").strip() or "other",
                "surface": surface,
                "tier": item["tier"],
                "score": float(item["score"]),
                "evidence": (item.get("evidence") or "").strip(),
            }
        )
    return result


def parse_stage_a_relations(raw: str) -> list[dict]:
    """Parse the relations array from model output. Validates tier/score like entities.

    Returns list of dicts: {subject, predicate, object, tier, score}.
    """
    data = _parse_json(raw)
    if data is None:
        return []
    if not isinstance(data, dict):
        return []
    relations = data.get("relations", [])
    if not isinstance(relations, list):
        return []
    result = []
    for item in relations:
        if not isinstance(item, dict) or not _valid_entity(item):
            continue
        subject = (item.get("subject") or "").strip()
        obj = (item.get("object") or "").strip()
        predicate = (item.get("predicate") or "related_to").strip() or "related_to"
        if not subject or not obj:
            continue
        result.append(
            {
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "tier": item["tier"],
                "score": float(item["score"]),
            }
        )
    return result
