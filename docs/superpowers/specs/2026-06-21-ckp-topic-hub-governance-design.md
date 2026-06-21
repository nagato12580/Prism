# CKP Topic Hub Governance Design

Date: 2026-06-21

## Purpose

The current governance implementation treats a `CanonicalKnowledgePoint` as a normalized version of one PKU. That makes CKP and PKU look nearly identical and naturally produces many one-to-one CKP-PKU pairs.

The desired model is different:

- PKU is an atomic knowledge unit extracted from evidence.
- CKP is a topic hub that groups many related PKUs under one reusable knowledge theme.

For example, PKUs about LoRA, SFT data preparation, evaluation, and training rules may all attach to a CKP titled `大模型微调` or to more specific topic hubs such as `LoRA 微调方法` and `微调数据准备`.

## Definitions

### PKU

`PersonalKnowledgeUnit` remains the atomic evidence-backed unit.

Examples:

- `LoRA 通过低秩矩阵减少可训练参数。`
- `指令微调需要覆盖多样化任务格式。`
- `微调前应划分训练集和验证集以避免数据泄漏。`

A PKU should be specific, source traceable, and typed as `definition`, `method`, `rule`, `claim`, `observation`, `experiment_result`, or another supported PKU unit type.

### CKP

`CanonicalKnowledgePoint` becomes a topic hub.

Examples:

- `大模型微调`
- `LoRA 微调方法`
- `微调数据准备`
- `微调效果评估`

A CKP should represent a stable theme that can hold multiple PKUs. It is not required to be semantically equivalent to any one PKU.

Recommended field semantics:

- `title`: concise topic name, such as `大模型微调`.
- `canonical_type`: `topic` for topic hubs.
- `canonical_statement`: a short topic description, such as `围绕大模型微调的概念、方法、规则、经验和评估知识集合。`
- `summary`: generated or refreshed from the PKUs attached to the topic.
- `keywords`, `concepts`, `domains`, `entities`: topic-level descriptors used for matching and display.
- `extra_meta`: source and clustering metadata, including the first local source that introduced the topic.

## Relationship Semantics

The PKU-to-CKP relation should no longer mean exact canonical equivalence.

Use:

```text
PKUCanonicalLink.relation_type = "about"
```

Meaning:

```text
This PKU is about this CKP topic.
```

This allows one PKU to attach to multiple CKPs later if needed. For example, a PKU about LoRA reducing trainable parameters can be about both `LoRA 微调方法` and `参数高效微调`.

`same_as` should be reserved only for true semantic equivalence, and the new extraction paths should not use it for topic membership.

## Governance Flow

Document and personal asset unit settlement should share the same topic-hub flow:

```text
source evidence
  -> extract PKUs
  -> locally cluster PKUs into topic candidates
  -> match each local topic candidate against existing global CKPs
  -> reuse a high-confidence CKP or create a new CKP
  -> link PKUs to CKP with relation_type="about"
  -> record low-confidence matches for future manual merge review
```

## Local-First Aggregation

The first aggregation pass is local.

For document settlement, local means the current `KnowledgeItem`. PKUs extracted from all parent chunks of that document participate in topic clustering.

For personal asset unit settlement, local means the current `PersonalAssetUnit`. PKUs extracted from that unit participate in topic clustering.

Local-first aggregation has three benefits:

- It preserves source context, so generated topics reflect the document or unit that introduced them.
- It avoids aggressive global merges before the topic meaning is clear.
- It makes debugging easier because each CKP candidate can be traced back to one document or one asset unit.

## Topic Candidate Extraction

After PKUs are extracted for a local source, build topic candidates from the PKU set.

The LLM prompt should receive:

- source metadata: title, summary, category, tags;
- local context: document title or asset unit title;
- the list of extracted PKUs with local IDs, statements, unit types, keywords, concepts, entities, and evidence snippets;
- instructions to group PKUs into concise topic hubs.

The LLM returns strict JSON:

```json
{
  "topics": [
    {
      "local_id": "topic_1",
      "title": "大模型微调",
      "description": "围绕大模型微调的概念、方法、规则、经验和评估知识集合。",
      "keywords": ["大模型微调", "SFT", "LoRA"],
      "concepts": ["fine-tuning"],
      "domains": ["AI"],
      "entities": [],
      "member_pku_refs": ["pku_1", "pku_2"],
      "confidence": 0.86,
      "reason": "These PKUs describe methods, rules, and concepts around LLM fine-tuning."
    }
  ]
}
```

Rules:

- each topic should have at least one member PKU;
- prefer fewer, meaningful topics over one topic per PKU;
- a topic title should be a noun phrase, not a full claim;
- do not create a topic that merely restates one PKU unless the local source only contains one coherent knowledge point;
- member references must resolve to PKUs produced from the same local source.

Fallback behavior:

- If topic extraction fails, create one local topic from the source title and attach all local PKUs to it.
- If the source title is too generic, derive a short title from the highest-confidence PKU keywords.

## Global Reuse

After local topic candidates are created, each candidate attempts to reuse an existing global CKP.

Matching should compare topic to topic, not PKU statement to CKP statement.

Candidate matching inputs:

- topic title;
- topic description;
- keywords, concepts, domains, entities;
- source title and category;
- sample member PKU statements.

Reuse an existing CKP only when confidence is high, for example:

- exact or near-exact topic title match with compatible keywords and domain;
- vector similarity above a high threshold;
- optional LLM decision says the two are the same topic with high confidence.

If confidence is high, attach PKUs to the existing CKP.

If confidence is low, create a new CKP with `canonical_type="topic"`.

If confidence is medium, create a new CKP and record the possible match for the future manual merge workbench.

## Manual Merge Workbench

Manual CKP merge is required later, but is out of scope for the first implementation pass.

The later workbench should show:

- possible duplicate CKPs;
- similarity reason and confidence;
- each CKP's attached PKUs;
- source documents and asset units;
- actions: merge, keep separate, mark as not same topic.

The first implementation should prepare for this by storing enough metadata to explain candidate matches, even if no dedicated merge table is introduced yet.

## Existing Data Behavior

Existing CKPs may still look like PKU-level canonical statements. The new flow should not attempt a destructive migration automatically.

Recommended first pass:

- newly generated CKPs use `canonical_type="topic"`;
- new PKU links use `relation_type="about"`;
- the Workbench displays relation labels so old `same_as` links and new `about` links can be distinguished;
- orphan or old draft CKPs can be hidden by default in UI later, but data cleanup should be a separate operation.

## Re-Ingest And Cleanup

Document re-ingest currently deletes document-sourced PKUs but leaves CKPs behind. With topic hubs, this can still leave orphan CKPs.

The new cleanup policy should be conservative:

- delete old document-sourced PKUs before re-settlement as today;
- after deleting PKUs, identify CKPs created by that same document that have no remaining active PKU links;
- mark those CKPs as `deprecated` instead of hard deleting them, unless a future admin cleanup explicitly removes them.

This prevents old local topic hubs from cluttering the Workbench while avoiding accidental removal of CKPs reused by other sources.

## API And UI Implications

The CKP Workbench remains the right visual model, but labels should reflect the new semantics:

- CKP cards represent topic hubs.
- PKU cards represent member knowledge.
- link labels should show `about`, not `same_as`, for new data.
- zero-PKU CKPs should be treated as orphan or deprecated candidates, not normal topic hubs.

The graph endpoint should continue to support old and new links during transition.

## Testing

Tests should cover:

- document settlement extracts multiple PKUs and groups them into fewer topic CKPs;
- a CKP title is topic-like and not copied from a PKU statement;
- new document PKU links use `relation_type="about"`;
- personal asset unit settlement uses the same topic-hub CKP path;
- high-confidence topic candidates reuse existing topic CKPs;
- low-confidence candidates create new topic CKPs;
- medium-confidence candidates preserve possible-merge metadata;
- re-ingest marks document-created orphan CKPs as deprecated;
- old `same_as` CKP links remain readable by the graph API.

## Non-Goals

- Do not build the manual merge workbench in the first pass.
- Do not migrate or delete all existing CKPs automatically.
- Do not support arbitrary many-to-many topic assignment beyond what the local topic extraction returns.
- Do not change document chunking or vectorization.
- Do not remove PKU-to-PKU relation extraction.
