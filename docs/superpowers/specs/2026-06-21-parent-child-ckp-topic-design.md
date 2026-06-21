# Parent-Child CKP Topic Design

Date: 2026-06-21

## Decision

CKP becomes a two-level topic structure:

- child CKP: the current CKP meaning, a local topic cluster created from PKUs in one document or one personal asset unit;
- parent CKP: a global topic hub that groups multiple child CKPs around the same broad theme.

PKU remains the atomic evidence-backed knowledge unit. PKUs attach to child CKPs. Parent CKPs summarize and organize child CKPs.

Example:

```text
Parent CKP: LLM fine-tuning
  Child CKP: LoRA fine-tuning methods
    PKU: LoRA reduces trainable parameters with low-rank matrices.
  Child CKP: Fine-tuning data rules
    PKU: SFT data should cover target task formats.
  Child CKP: Fine-tuning evaluation
    PKU: Fine-tuning evaluation should use a held-out validation set.
```

## Why

The existing CKP topic-hub flow already gives useful CKP-to-PKU grouping, and the data model already allows one CKP to link PKUs from both document chunks and personal asset units.

The problem is granularity: local CKPs are still too detailed to act as top-level graph anchors. Making every CKP a broad topic would flatten the graph and put too many unrelated PKUs under one node. A two-level model keeps local precision while adding global readability.

## Data Model

Reuse `CanonicalKnowledgePoint` for both parent and child CKPs.

Recommended metadata:

- child CKP:
  - `canonical_type = "topic"`
  - `extra_meta.topic_level = "child"`
  - `extra_meta.created_from = "document_chunk"` or `"personal_asset_unit"`
  - `extra_meta.source_id` points to the local source
- parent CKP:
  - `canonical_type = "topic"`
  - `extra_meta.topic_level = "parent"`
  - `extra_meta.created_from = "global_topic_rollup"`

Reuse `CanonicalRelation` for CKP hierarchy.

Direction:

```text
source_canonical_id = child CKP
target_canonical_id = parent CKP
relation_type = "subtopic_of"
```

This reads as:

```text
child CKP is a subtopic of parent CKP
```

PKU membership remains:

```text
PKUCanonicalLink.relation_type = "about"
PKUCanonicalLink.role = "topic_member"
```

## Governance Flow

The settlement flow should become:

```text
source evidence
  -> extract PKUs
  -> locally cluster PKUs into child CKPs
  -> match or create a parent CKP for each child CKP
  -> link child CKP to parent CKP with subtopic_of
  -> link PKUs to child CKP with about/topic_member
```

For documents, local scope remains the current `KnowledgeItem`, using PKUs from its parent chunks.

For personal asset units, local scope remains the current `PersonalAssetUnit`.

## Parent CKP Matching

Parent matching should compare topic-to-topic, not PKU-to-topic.

Inputs:

- child CKP title and description;
- child CKP keywords, concepts, domains, and entities;
- source title and category;
- a few member PKU statements.

Rules:

- reuse an existing parent CKP only when the title/domain/keywords or vector match is high confidence;
- create a new parent CKP when no confident parent exists;
- store medium-confidence candidates in metadata for a future manual merge workbench.

The parent title should be broad but still concrete, such as `LLM fine-tuning`, not a generic category like `AI`.

## Prompting

Keep the current local CKP extraction prompt mostly intact. It should continue producing local topic clusters.

Add a second parent-topic assignment step. Given one or more child CKP candidates, ask for a broader parent topic:

```json
{
  "parent_topics": [
    {
      "title": "LLM fine-tuning",
      "description": "Methods, rules, data, and evaluation knowledge for adapting large language models.",
      "member_child_refs": ["child_ckp_1", "child_ckp_2"],
      "keywords": ["fine-tuning", "SFT", "LoRA"],
      "confidence": 0.86,
      "reason": "The child topics all describe fine-tuning methods or rules."
    }
  ]
}
```

Fallback:

- if parent assignment fails, create or reuse a parent from the child CKP's strongest broad keyword or source category plus title;
- if the fallback is too generic, use the child CKP itself as a temporary parent only by metadata, not by self-relation.

## API And UI

The graph API should expose CKP-to-CKP hierarchy edges in addition to current CKP-PKU-source edges.

Workbench default view should become:

```text
Parent CKP list
  -> child CKP list
    -> PKU evidence chain
```

The current CKP cards can be reused as child CKP cards. Parent CKPs should be visually distinct as broad topic anchors.

Network view should render parent CKPs before child CKPs, then PKUs, then sources.

## Migration

No destructive migration in the first pass.

Existing topic CKPs without `extra_meta.topic_level` can be treated as child CKPs. A background or manual operation can later assign them to parent CKPs.

Old `same_as` PKU links should continue to display, but new topic flow should use `about`.

## Tests

Add tests for:

- child CKPs are linked to parent CKPs with `CanonicalRelation(relation_type="subtopic_of")`;
- document and personal asset unit child CKPs can share the same parent CKP;
- graph API returns parent-child CKP edges;
- Workbench groups child CKPs under parent CKPs;
- existing CKPs without parent metadata still remain visible.
