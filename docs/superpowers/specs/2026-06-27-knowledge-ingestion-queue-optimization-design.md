# Knowledge Ingestion Queue Optimization Design

## Goal

Upgrade Prism's document vectorization pipeline so it can handle large batches of papers through a Redis-backed producer-consumer queue, while making fast retrieval available before slower PKU/CKP governance finishes.

## Background

The current document ingestion flow executes heavy work directly from the resource ingest trigger. When several papers are vectorized at the same time, the engine can run multiple long ingestion transactions concurrently. This caused MySQL `knowledge_chunk` lock waits and deadlocks during concurrent inserts.

Single-document latency is also high because the current pipeline combines several expensive stages:

- PDF text may be extremely large or malformed, such as a paper parsed as hundreds of pages and millions of characters.
- Embedding calls use a small batch size.
- Milvus vectors are inserted one by one.
- PKU/CKP governance runs inside the same user-facing ingestion path.

This design changes ingestion from direct execution to queued background work, separates fast retrieval from governance, adds progress visibility, and blocks abnormal document text before it reaches expensive vectorization.

## Chosen Approach

Use a Redis queue plus a MySQL job table with two worker stages:

- Redis handles producer-consumer queue delivery.
- MySQL stores durable job status, progress, attempts, errors, and recovery state.
- Ingest workers process vectorization jobs with default concurrency 2.
- Governance workers process PKU/CKP jobs separately with stricter concurrency.
- Backend APIs produce jobs and return quickly.
- Frontend resource cards show both retrieval status and governance progress.

This avoids 100+ frontend requests becoming 100+ simultaneous heavy jobs. The UI produces many jobs, while workers consume them at a controlled pace.

## Architecture

### Producers

Backend knowledge APIs become job producers:

- `POST /knowledge/resources/{resource_id}/ingest` enqueues one document vectorization job.
- `POST /knowledge/topics/{topic_id}/ingest` enqueues all eligible documents in the topic.

The API validates resource eligibility, creates or reuses an active MySQL job, pushes `{job_id}` to Redis, updates visible resource state, and returns immediately.

### Queues

Redis queues:

- `prism:queue:ingest`
- `prism:queue:governance`

Redis payloads contain only the job id:

```json
{"job_id": "uuid"}
```

Document text, embeddings, and progress are never stored in Redis.

### Consumers

The worker layer has two consumer pools:

- Ingest worker pool, default concurrency `2`.
- Governance worker pool, default concurrency `1`.

The worker reads `job_id` from Redis, locks the MySQL job, changes it from `queued` to `processing`, performs work, updates progress, and writes terminal state.

### Recovery

A recovery loop handles service restarts and crashes:

- Re-enqueue MySQL `queued` jobs that are missing from Redis.
- Return stale `processing` jobs to `queued` when `locked_at` exceeds a timeout.
- Repair resource/job state mismatches into a retriable state.

## Resource State Model

`knowledge_file.processing_status` continues to represent retrieval/vectorization readiness:

- `completed`: text parsed, waiting for vectorization
- `queued`: vectorization queued
- `processing`: vectorization running
- `done`: vectorization complete and retrievable
- `failed`: vectorization failed
- `text_invalid`: parsed text failed quality checks and cannot be vectorized
- `metadata_only`: non-document resource

New governance fields on `knowledge_file` represent PKU/CKP status:

- `governance_status`: `not_started | queued | processing | done | failed | skipped`
- `governance_progress_current`
- `governance_progress_total`
- `governance_error_message`
- `governance_started_at`
- `governance_finished_at`

Frontend primary display rules:

- `processing_status = done` and `governance_status = done`: complete
- `processing_status = done` and `governance_status in queued/processing`: governance running
- `processing_status = done` and `governance_status = failed`: partial complete
- `processing_status = done` and `governance_status in skipped/not_started`: vectorized
- `processing_status = failed`: vectorization failed
- `processing_status = queued`: queued
- `processing_status = processing`: vectorizing
- `processing_status = completed`: ready to vectorize
- `processing_status = text_invalid`: text invalid

The frontend can localize these labels in Chinese. `partial complete` means retrieval vectors are usable, but PKU/CKP governance did not complete.

## Job Table

Add `knowledge_job` as the durable job source of truth.

Fields:

- `id`
- `job_type`: `ingest | governance`
- `resource_id`
- `item_id`
- `topic_id`
- `status`: `queued | processing | done | failed | canceled`
- `priority`
- `attempts`
- `max_attempts`, default `3` for initial attempt plus 2 automatic retries
- `progress_current`
- `progress_total`
- `stage`
- `error_code`
- `error_message`
- `locked_by`
- `locked_at`
- `available_at`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

Indexes and constraints:

- Index `status, available_at, priority, created_at` for recovery and consumption.
- Index `resource_id`.
- Index `item_id`.
- Index `topic_id`.
- Prevent multiple active jobs with the same `resource_id` and `job_type`.

Active job statuses are `queued` and `processing`.

## Ingest Worker Flow

For each ingest job:

1. Pop `job_id` from `prism:queue:ingest`.
2. Atomically claim the MySQL job.
3. Set resource `processing_status = processing`.
4. Load resource and item.
5. Re-run document text quality checks.
6. Clear old chunks, old ES records, and old document governance rows.
7. Chunk with balanced defaults:
   - child chunk tokens: `384`
   - parent chunk tokens: `1536`
   - overlap ratio: `0.1`
8. Embed child chunks with batch size `64`.
9. Bulk insert MySQL chunks.
10. Bulk insert Milvus vectors.
11. Bulk index ES documents.
12. Mark resource `processing_status = done`.
13. Mark ingest job `done`.
14. Automatically create and enqueue a governance job.

Ingestion no longer calls `settle_document_item_to_governance()` directly.

## Governance Worker Flow

For each governance job:

1. Pop `job_id` from `prism:queue:governance`.
2. Claim the MySQL job.
3. Set resource `governance_status = processing`.
4. Load parent chunks for the item.
5. Set `governance_progress_total` to parent chunk count.
6. For each parent chunk, extract PKU/CKP data and update progress.
7. On success, set `governance_status = done`.
8. On retryable failure, requeue until attempts are exhausted.
9. On exhausted failure, set `governance_status = failed`.

When governance fails after vectorization succeeds, the resource remains searchable and displays as `partial complete`.

## Performance Optimizations

### Governance Separation

Fast retrieval is complete when chunking, embedding, Milvus, and ES indexing are done. PKU/CKP governance runs separately. This shortens the user-visible vectorization path.

### Milvus Batch Insert

Add `insert_vectors_batch` to insert all child chunk vectors for a document in one Milvus operation. Keep `insert_vectors` for compatibility and tests.

### Embedding Batch Size

Set default `EMBEDDING_BATCH_SIZE=64`. Keep it configurable through environment variables.

### Configurable Chunk Sizes

Add config values:

- `CHILD_CHUNK_TOKENS=384`
- `PARENT_CHUNK_TOKENS=1536`
- `CHILD_OVERLAP_RATIO=0.1`

The chunker reads these values from config instead of hard-coded constants.

## Document Text Quality Gate

Add a document text quality check before vectorization. If it fails, vectorization is blocked and the resource becomes `text_invalid`.

Default checks:

- Total character count must not exceed `300000`.
- Average characters per page must not exceed `12000` when `page_count` is known.
- `page_count > 100` and `chars > 300000` is invalid.

The error message includes measured metrics and a user-facing recommendation to re-upload or fix parsing. Text quality failures are hard failures and are not automatically retried.

## Frontend UX

Topic page:

- Add a topic-level batch vectorize button.
- It enqueues all eligible documents in the current topic.
- The response reports queued, skipped, and failed counts.
- The frontend no longer loops over all documents issuing one request per resource.

Resource cards:

- Show primary status: ready to vectorize, queued, vectorizing, vectorized, governance running, complete, partial complete, vectorization failed, or text invalid.
- Show progress detail such as `embedding 64/180` or `governance 12/40`.
- Show `partial complete` prominently and offer governance retry.
- Show `vectorization failed` with vectorization retry.
- Show `text invalid` with the measured reason and no vectorization button.

Polling:

- Continue polling while any visible resource has queued/running ingest or governance work.
- Resource list responses include governance fields and latest job summary.

## Error Handling

### Hard Failures

Hard failures are not automatically retried:

- Text quality failure
- Missing resource
- Missing item
- Non-document resource sent to ingest

### Retryable Failures

Retryable failures are automatically retried twice:

- Embedding provider timeout or 5xx
- Milvus transient failure
- ES transient failure
- Worker crash while a job is processing

Retry uses lightweight backoff:

- First retry after about 30 seconds.
- Second retry after about 2 minutes.

### Partial Success

If vectorization succeeds and governance fails:

- `processing_status` stays `done`.
- `governance_status` becomes `failed`.
- Primary UI status is `partial complete`.
- User can retry governance manually.

## Testing Strategy

Backend API tests:

- Single-resource ingest creates or reuses a job and does not run heavy work inline.
- Topic ingest enqueues eligible documents and skips ineligible documents.
- Duplicate clicks do not create duplicate active jobs.
- Failed resources can be manually retried.

Queue and worker tests:

- Redis payload contains only `job_id`.
- Worker transitions `queued -> processing -> done`.
- Ingest success creates a governance job.
- Stale processing jobs recover to `queued`.
- Retryable errors retry twice.
- Hard failures do not retry.

Performance path tests:

- Embedding uses batch size `64`.
- Milvus batch insert is called instead of per-vector insert.
- Chunker uses `384/1536` by default.
- Ingest pipeline does not call `settle_document_item_to_governance`.
- Governance worker owns PKU/CKP construction.

Text quality tests:

- Normal 10-20 page papers pass.
- 858-page or multi-million-character documents are blocked.
- Missing page count falls back to total character limit.
- Error messages include useful measured metrics.

Frontend tests:

- Topic page exposes the batch vectorize action.
- Status badge displays partial complete, governance running, and text invalid.
- Polling continues while ingest or governance work is active.
- Partial completion offers governance retry.

## Rollout Notes

This change should be delivered incrementally:

1. Add job model, statuses, and API behavior while keeping existing ingest callable behind workers.
2. Add Redis producer-consumer worker plumbing.
3. Move ingest execution into workers.
4. Separate governance into its own job.
5. Add Milvus batch insert, embedding batch default, and chunk config.
6. Add text quality gate.
7. Update frontend status display and topic-level batch action.

Existing resources with `completed`, `failed`, or `done` statuses remain valid. Resources stuck in `processing` from older runs should be recoverable by the job recovery loop or manual reset.
