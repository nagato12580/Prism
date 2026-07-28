# Personal Inbox Knowledge KB Design

Date: 2026-07-28

## Goal

Add confirmed personal asset knowledge units to the current knowledge-base question-answering path without introducing a separate primary asset search tool.

The system will expose a system-managed knowledge base named `个人随手记`. Each confirmed `PersonalAssetUnit` is rendered into one fixed Markdown file inside that knowledge base. The file uses the normal knowledge-file preview, download, parsing, indexing, retrieval, citation, and deletion surfaces.

Chat does not search this system KB by default. The user must explicitly enable `包含个人随手记` in the chat page. When enabled, Backend adds the user's personal inbox KB to the authorized knowledge scope, and `query_kb` searches across the selected KB plus the personal inbox KB.

## Current Context

The current authorized chat path is KB-scoped:

1. Frontend posts `/api/v1/chat/answer` with `query` and `kb_uids`.
2. Backend validates requested KBs with `KnowledgeAccessPolicy`.
3. Backend signs an `AuthorizedKnowledgeScope`.
4. Engine builds authorized knowledge tools.
5. `query_kb`, `search_file`, `open_kb_document`, and `find_kb_document` operate on `KnowledgeTopic`, `KnowledgeFile`, and `KnowledgeChunk`.

Personal assets currently have their own management and graph paths through `PersonalAssetItem`, `PersonalAssetUnit`, PKU/CKP, and Neo4j projection. They are not first-class evidence in the new authorized KB QA path because the retrieval evidence contract requires KB provenance such as `kb_uid`, `file_uid`, and `chunk_uid`.

## Product Decisions

1. `个人随手记` is a normal visible knowledge base in the KB list.
2. The KB is a system KB and cannot be deleted.
3. Only confirmed `PersonalAssetUnit` records are synced into this KB.
4. `PersonalAssetItem` records are not synced directly as independent files.
5. One `PersonalAssetUnit` maps to one stable `.md` file.
6. Editing a confirmed Unit overwrites the same derived `.md` file and triggers re-indexing.
7. Existing confirmed Units are backfilled during migration/startup.
8. The Markdown file contains the Unit body plus associated Item summaries and rewritten content.
9. Chat searches `个人随手记` only when the user explicitly enables the chat switch.
10. Deleting a derived Markdown file from `个人随手记` is a source-level delete: it physically deletes the corresponding Unit and orphan source Items.

## Architecture

```text
PersonalAssetUnit confirmed/backfilled/edited
  -> render Markdown
  -> write file content through the knowledge-file storage path
  -> create or update KnowledgeFile / KnowledgeItem / KnowledgeChunk
  -> trigger existing parsing/indexing/generation jobs
  -> file appears in the Personal Inbox KB
  -> chat can retrieve it when include_personal_inbox=true
```

`PersonalAssetUnit` remains the source of truth. `KnowledgeFile`, `KnowledgeItem`, and `KnowledgeChunk` are derived query/download/index records.

## Data Model

Use the existing models where possible and add explicit metadata for system behavior and derivation.

### KnowledgeTopic

The personal inbox KB needs a stable marker. Prefer a first-class field if the model already has an appropriate schema path; otherwise use `extra_meta`.

Required logical fields:

```json
{
  "system_type": "personal_inbox",
  "is_system": true,
  "delete_disabled": true
}
```

The system must enforce non-deletability in Backend, not only in Frontend.

### KnowledgeFile

Each derived file must record its source:

```json
{
  "source_kind": "personal_asset_unit",
  "source_id": "<PersonalAssetUnit.id>",
  "system_kb": "personal_inbox"
}
```

Suggested file fields:

```text
title = PersonalAssetUnit.title
original_filename = safe-title + "-" + unit-id-short + ".md"
media_type = markdown
mime_type = text/markdown
```

The mapping from Unit to file must be unique. Re-syncing the same Unit updates the same file rather than creating a new version.

### PersonalAssetUnit

No new source-of-truth field is required for the first version. The system can find the derived file by querying `KnowledgeFile.extra_meta.source_kind/source_id`. If implementation shows this is too slow or awkward, add a direct `derived_kb_file_uid` field in a later migration.

## Markdown Rendering

Each Unit is rendered as:

```md
# {unit.title}

> 来源：个人随手记
> 类型：PersonalAssetUnit
> 更新时间：{unit.updated_at}

## 摘要

{unit.summary}

## 正文

{unit.content}

## 标签

- {tag}

## 来源碎片

- {item.title}
  - 摘要：{item.summary}
  - 内容：{item.rewritten_content or item.body}
```

Do not include full `raw_text` by default. This keeps retrieval focused and avoids making the derived Markdown noisy. The original Item remains available in the asset tables.

## System KB Creation and Backfill

On migration/startup:

1. Ensure one `个人随手记` KB exists for each user/tenant scope.
2. Mark it as `system_type=personal_inbox`.
3. Backfill all confirmed `PersonalAssetUnit` records.
4. For each Unit, render or update its derived Markdown file.
5. Trigger the existing knowledge ingestion/indexing path.

Backfill must be idempotent. Re-running it must update existing derived files, not duplicate them.

Backfill failure for one Unit must not block other Units. Failures should be logged and retryable.

## Sync Rules

### Confirm Unit

When a `PersonalAssetUnit` is confirmed:

1. Ensure the personal inbox KB exists.
2. Render the Unit Markdown.
3. Create or update its derived `KnowledgeFile`.
4. Trigger parsing/indexing.

### Edit Confirmed Unit

When an already confirmed Unit changes:

1. Re-render Markdown.
2. Overwrite the same derived file.
3. Trigger re-indexing.

### Pending Unit

Pending or rejected Units are not synced into the personal inbox KB.

## Chat Integration

Frontend adds a chat switch:

```text
[ ] 包含个人随手记
```

Default: off.

When off:

```json
{
  "kb_uids": ["<selected_kb_uid>"],
  "include_personal_inbox": false
}
```

When on:

```json
{
  "kb_uids": ["<selected_kb_uid>"],
  "include_personal_inbox": true
}
```

Frontend must not manually append the personal inbox KB UID. Backend resolves the current actor's system KB and appends it to the signed authorization scope.

When the switch is enabled, `query_kb` should default to searching all authorized KBs. This avoids requiring the model to manually call `list_kbs` and issue one query per KB. Evidence must preserve `kb_uid` so the answer can distinguish selected-KB evidence from personal-inbox evidence.

## Delete Semantics

Deleting a derived Markdown file from `个人随手记` is a strong cascade operation.

If a `KnowledgeFile` belongs to the personal inbox KB and has:

```json
{
  "source_kind": "personal_asset_unit",
  "source_id": "<unit_id>"
}
```

then file deletion must:

1. Physically delete the corresponding `PersonalAssetUnit`.
2. Read its `source_asset_ids`.
3. For each associated `PersonalAssetItem`, check whether any remaining Unit references it.
4. Physically delete only orphan Items that are no longer referenced by any Unit.
5. Delete derived `KnowledgeFile`, `KnowledgeItem`, and `KnowledgeChunk` records.
6. Trigger existing ES/Milvus/Neo4j cleanup.

If an Item is referenced by another remaining Unit, it must be preserved.

The delete confirmation UI must clearly state that deleting this file also deletes the source personal asset unit and orphan source fragments.

## Error Handling

### Sync Failure

If Unit-to-Markdown sync fails:

- Keep the source `PersonalAssetUnit`.
- Mark or expose the derived file/job state as failed if a file exists.
- Allow retry through backfill or a future repair endpoint.

### Index Failure

If parsing/indexing fails:

- Keep the Markdown file downloadable and previewable.
- Mark file/job status as failed through the existing knowledge-file status path.
- Do not delete or mutate the source Unit.

### Delete Partial Failure

Database deletion of Unit, orphan Items, and derived KB records must happen in one transaction. External index cleanup can be asynchronous and retryable through existing cleanup mechanisms.

The system must not leave a deleted Unit visible as an active file in `个人随手记`.

## Frontend Behavior

Knowledge list:

- Show `个人随手记` as a normal KB.
- Add a system-library visual label.
- Disable KB delete for this KB.

File list:

- Derived `.md` files can be previewed and downloaded like ordinary files.
- Deleting a derived file is allowed, but must show the cascade warning.
- Ordinary KB file deletion behavior remains unchanged.

Chat:

- Add `包含个人随手记` switch.
- Default off.
- Send `include_personal_inbox=true` only when enabled.

## Testing Plan

Backend:

- System personal inbox KB is created during migration/startup.
- System KB cannot be deleted.
- Confirmed `PersonalAssetUnit` creates one derived Markdown file.
- Editing a confirmed Unit updates the same file.
- Backfill creates files for existing confirmed Units without duplicates.
- Deleting a derived personal inbox file deletes the Unit.
- Deleting the file deletes orphan Items.
- Items shared with another Unit are preserved.
- Ordinary KB file deletion does not trigger asset cascade deletion.

Engine:

- `query_kb` searches only the selected KB when `include_personal_inbox=false`.
- `query_kb` searches selected KB plus personal inbox when enabled.
- Multi-KB evidence preserves `kb_uid`.
- Personal inbox evidence is returned as normal KB evidence with file/chunk provenance.

Frontend:

- Chat switch defaults off.
- Chat request includes `include_personal_inbox` only when switch is enabled.
- System KB is visible and marked.
- System KB delete action is disabled.
- Derived Markdown files can be previewed and downloaded.
- Delete confirmation explains source Unit and orphan Item cascade.

## Non-Goals

- Do not add a separate primary `asset_search` tool for this first version.
- Do not sync raw `PersonalAssetItem` records as independent KB files.
- Do not include full Item `raw_text` in generated Markdown by default.
- Do not make the personal inbox KB automatically participate in every chat.
- Do not directly rely on unscoped legacy GraphRAG asset-unit hits as the first-version evidence path.

## Open Implementation Notes

The design intentionally keeps implementation flexible on whether system flags live in first-class columns or `extra_meta`. The required behavior is explicit: system KB detection and source derivation must be enforced server-side and must be testable.
