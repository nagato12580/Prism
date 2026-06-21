# LLM Asset Unit PKU Extraction Design

## Goal

When a confirmed `personal_asset_unit` settles into the governance layer, Prism should use the configured main LLM to extract multiple atomic PKUs and PKU-to-PKU relations. The old Ollama small-model unit type classifier must no longer be used for `personal_asset_unit` settlement. If LLM extraction fails or yields no valid PKUs, Prism falls back to a single PKU generated from the asset unit summary.

## Scope

This design applies to `personal_asset_unit -> personal_knowledge_unit` settlement only.

Document chunk settlement can keep its current behavior unless changed in a separate task. Single `personal_asset_item` settlement remains disabled.

## PKU Unit Types

Asset-unit PKU extraction must support these unit types:

- `concept`: concept
- `definition`: definition
- `claim`: claim/opinion
- `method`: method
- `rule`: rule
- `observation`: observation
- `experiment_result`: experiment result
- `decision`: decision
- `problem`: problem
- `question`: question
- `pattern`: experience pattern
- `constraint`: constraint

Invalid LLM unit types are discarded for LLM extraction. Fallback extraction uses deterministic rules and falls back to `claim` if no better type matches.

## LLM Extraction Contract

The backend sends the main LLM the asset unit title, summary, content, category, tags, and source asset IDs. The LLM returns strict JSON:

```json
{
  "pkus": [
    {
      "statement": "Atomic Chinese PKU statement",
      "unit_type": "concept",
      "evidence_span": "Direct evidence from summary or content",
      "keywords": ["keyword"],
      "concepts": ["concept"],
      "entities": ["entity"],
      "domains": ["domain"],
      "group": "optional group",
      "confidence": 0.85,
      "reason": "short extraction reason"
    }
  ],
  "relations": [
    {
      "from": "source PKU statement",
      "to": "target PKU statement",
      "type": "supports",
      "confidence": 0.9,
      "reason": "short relation reason"
    }
  ]
}
```

The prompt requires atomic, concrete, verifiable PKUs. A statement must not be a section title or vague summary. `evidence_span` must come from the asset unit source text.

## Persistence

Each valid extracted PKU creates or reuses one `personal_knowledge_unit` row:

- `source_kind = "personal_asset_unit"`
- `source_id = unit.id`
- `statement = pku.statement`
- `normalized_statement = normalized statement`
- `normalized_statement_hash = sha256(normalized statement)`
- `unit_type = pku.unit_type`
- `evidence_span = pku.evidence_span`
- `keywords`, `concepts`, `entities`, `domains` from LLM output plus safe defaults
- `confidence = clamped pku.confidence`
- `llm_model = settings.LLM_MODEL`
- `status = "active"`

Each PKU still links to a CKP through `pku_canonical_link` with `relation_type = "same_as"` and `role = "synthesized_personal_knowledge"`.

LLM relations create rows in a new `pku_relation` table. The relation endpoints are resolved by exact normalized statement matching against PKUs created or reused during the same settlement run. Relations whose endpoints cannot be resolved are skipped.

`pku_relation` fields:

- `id`
- `user_id`
- `source_pku_id`
- `target_pku_id`
- `relation_type`
- `confidence`
- `reason`
- `source_kind`
- `source_id`
- `llm_model`
- `metadata`
- `created_at`
- `updated_at`

Unique constraint:

- `source_pku_id`, `target_pku_id`, `relation_type`

## Fallback

If LLM extraction is unavailable, fails, returns invalid JSON, returns no PKUs, or all PKUs are invalid, settlement creates one summary PKU only when `unit.summary` is non-empty.

Fallback fields:

- `statement = normalized unit.summary`
- `evidence_span = normalized(unit.content or unit.summary)[:1200]`
- `unit_type = deterministic summary classifier`
- `confidence = unit.confidence.overall or 0.55`
- `llm_model = ""`

Fallback must not use `unit.content[:1200]` as the statement.

## Error Handling

The confirm endpoint should not fail just because LLM extraction fails. The governance result should reflect actual inserted or reused PKU, CKP, CKP link, and PKU relation counts.

If both LLM extraction and summary fallback produce no PKU, settlement returns zero counts.

## Testing

Tests should cover:

- multiple LLM PKUs are persisted from one asset unit;
- LLM-provided unit types include the new 12-type vocabulary;
- Ollama type tagging is not called for asset unit settlement;
- PKU-to-PKU relations are persisted in `pku_relation`;
- invalid relations with unresolved endpoints are skipped;
- invalid PKUs are skipped;
- LLM failure falls back to one summary PKU;
- empty LLM output and empty summary produce zero PKUs.

