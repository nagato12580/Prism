# Document Chunk PKU Extraction Design

## Goal

Upgrade the document governance path so it matches the personal asset unit path:

```text
KnowledgeItem
  -> KnowledgeChunk(parent/child)
  -> PersonalKnowledgeUnit
  -> CanonicalKnowledgePoint
```

The current document path creates one coarse PKU from each parent chunk and uses the Ollama type classifier. The new path should use the configured main LLM to extract multiple atomic PKUs and local PKU relations from each document parent chunk, then reuse the same CKP canonicalization logic used by personal asset units.

## Scope

This design applies only to document ingestion settlement:

```text
settle_document_item_to_governance(db, item_id)
```

It does not change:

- document upload or parsing;
- parent/child chunking;
- child chunk vectorization for traditional RAG;
- `personal_asset_unit` settlement behavior;
- `personal_asset_item` direct settlement, which remains disabled.

## Core Decision

Use an anchor parent chunk with neighboring parent chunks as context.

For each parent chunk, build one extraction window:

```text
previous_parent_chunk: optional
anchor_parent_chunk: required
next_parent_chunk: optional
```

The main LLM may use neighboring chunks to resolve pronouns, terminology, headings, and step continuity. However, persisted PKUs are anchored to the current parent chunk:

```text
PersonalKnowledgeUnit.source_kind = "document_chunk"
PersonalKnowledgeUnit.source_id = anchor_chunk.id

PKURelation.source_kind = "document_chunk"
PKURelation.source_id = anchor_chunk.id
```

This keeps evidence backtracking clear while giving the LLM enough context to avoid under-extracting fragmented chunks.

## Extraction Contract

The backend sends the main LLM:

- document metadata from `KnowledgeItem`: id, title, summary, category, tags, source type;
- the anchor parent chunk: id, index/order, text;
- optional previous and next parent chunk text;
- the same allowed PKU unit types and relation types used by the asset unit extraction path.

The LLM returns strict JSON:

```json
{
  "pkus": [
    {
      "local_id": "pku_1",
      "statement": "Atomic knowledge statement supported by the anchor chunk.",
      "normalized_statement": "Optional normalized statement.",
      "unit_type": "claim",
      "keywords": ["keyword"],
      "domains": ["domain"],
      "entities": ["entity"],
      "concepts": ["concept"],
      "confidence": 0.86,
      "evidence": "Evidence span from the anchor chunk.",
      "reason": "Short extraction reason."
    }
  ],
  "relations": [
    {
      "source_local_id": "pku_1",
      "target_local_id": "pku_2",
      "relation_type": "prerequisite_of",
      "reason": "Short relation reason.",
      "confidence": 0.8
    }
  ]
}
```

Rules:

- each PKU must be atomic, reusable, and semantically complete;
- `unit_type` must be one of the shared PKU unit types;
- relation endpoints must refer to PKUs returned in the same extraction window;
- `evidence` or `evidence_span` should come from the anchor chunk;
- neighboring chunks may explain context but should not be the sole evidence for a persisted PKU.

## Persistence

Each valid extracted PKU creates or reuses one `PersonalKnowledgeUnit` row:

- `user_id = item.user_id or DEFAULT_USER_ID`
- `source_kind = "document_chunk"`
- `source_id = anchor_chunk.id`
- `unit_type = extracted.unit_type`
- `statement = extracted.statement`
- `normalized_statement = normalized statement`
- `normalized_statement_hash = sha256(normalized statement)`
- `modality = "fact"`
- `domains`, `entities`, `concepts`, `keywords` from the LLM with deterministic fallbacks from document metadata
- `evidence_span = extracted.evidence_span`
- `confidence = clamped extracted confidence`
- `llm_model = settings.LLM_MODEL`
- `status = "active"`

Each PKU links to a CKP through the existing `_create_or_get_ckp_from_pku` path:

- reuse lexical, vector, and optional LLM same-as matching already used by asset units;
- create a new CKP when no existing CKP is safe to reuse;
- create a `PKUCanonicalLink` with `relation_type = "same_as"` and `role = "external_reference"`.

Each valid extracted relation creates or reuses one `PKURelation` row:

- `source_kind = "document_chunk"`
- `source_id = anchor_chunk.id`
- `llm_model = extraction.llm_model`
- relation endpoints resolved by `local_id` first and normalized statement second;
- unresolved or self-loop relations are skipped.

The returned `GovernanceResult` should include:

- `pku_count`
- `canonical_count`
- `link_count`
- `pku_relation_count`

## Reuse Strategy

The implementation should avoid creating a second governance pipeline. It should reuse or generalize existing asset-unit helpers where practical:

- keep `ExtractedPKU`;
- keep `ExtractedPKURelation`;
- keep `AssetUnitPKUExtraction` or rename/generalize only if the change stays small;
- reuse `_parse_asset_unit_pku_extraction`, or extract a generic parser with equivalent behavior;
- reuse `_create_or_get_ckp_from_pku`;
- reuse `_create_or_get_generic_link`;
- reuse `_create_or_get_pku_relation`;
- add document-specific helpers only where the inputs differ.

Expected new helpers:

- `build_document_chunk_pku_extraction_messages(...)`
- `_extract_document_chunk_pkus_with_llm(item, anchor_chunk, previous_chunk, next_chunk)`
- `_create_or_get_document_pku_from_extracted(...)`
- `_fallback_document_chunk_pku(item, anchor_chunk)`

## Fallback

If the main LLM is unavailable, fails, returns invalid JSON, or returns no valid PKUs for the anchor chunk, fallback creates one coarse PKU from the anchor chunk only.

Fallback fields:

- `statement = normalized(anchor_chunk.chunk_text)[:1200]`
- `unit_type = _unit_type_from_document_text(statement)`
- `evidence_span = statement`
- `keywords = _extract_keywords(statement, item.title, item.summary, item.category, item.tags or [])`
- `confidence = 0.72`
- `llm_model = ""`

The fallback must not call `_ollama_pku_type_decision`. Document settlement should align with asset unit settlement: main LLM first, deterministic local fallback second.

## Error Handling

Document ingestion should not fail solely because PKU extraction fails for one chunk.

Per-anchor behavior:

- LLM extraction errors return an empty extraction for that anchor;
- empty extraction triggers fallback for that anchor;
- invalid PKUs are skipped;
- invalid relations are skipped;
- CKP vector refresh failures mark the CKP vector status as failed through existing behavior and do not abort settlement.

`settle_document_item_to_governance` should still return zero counts when:

- the `KnowledgeItem` does not exist;
- no chunks exist;
- chunks are empty after normalization.

## Re-Ingest And Cleanup

The existing cleanup behavior remains:

```text
clear_document_item_governance(db, item_id)
```

Before a document is re-ingested, old PKUs whose `source_kind = "document_chunk"` and `source_id` belongs to the item are deleted. Existing ORM cascades remove related PKU canonical links and PKU relations. New chunks then produce a fresh governance settlement.

This design keeps CKPs stable across re-ingestion. If a new PKU semantically matches an existing CKP, `_create_or_get_ckp_from_pku` should reuse it.

## Testing

Tests should cover:

- document settlement calls the main LLM extractor per parent anchor chunk;
- extraction windows include previous and next parent chunk context;
- multiple LLM PKUs from one anchor chunk are persisted with `source_kind = "document_chunk"` and `source_id = anchor_chunk.id`;
- document PKU relations are persisted in `pku_relation`;
- document settlement reuses existing CKPs via the shared CKP path;
- document and asset unit PKUs can link to the same CKP with distinct roles;
- LLM empty/failure falls back to one anchor chunk PKU;
- fallback does not call `_ollama_pku_type_decision`;
- invalid relation endpoints are skipped;
- `ingest_item(item_id)` still triggers document governance after chunk creation.

## Non-Goals

- Do not change chunk sizes or parent/child chunking rules.
- Do not create new document source or document chunk tables.
- Do not introduce cross-anchor PKU relations in this iteration.
- Do not replace traditional RAG search.
- Do not make `personal_asset_item` settle directly into PKU/CKP.

