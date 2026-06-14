# Topic Resource Knowledge Base Design

## Goal

Upgrade Prism's knowledge base from a flat item list into a topic-first resource workspace. Users organize knowledge by one-level topics, upload different media types into a topic, and filter resources by type. Document resources enter the existing text ingestion and RAG pipeline. Image, audio, and video resources are saved with metadata only in the first version.

## Decisions

- Use one-level topics for the first version. Multi-level folders are out of scope.
- Use a default user id, `default-user`, until Prism has a real authentication system.
- Use topic-first organization. Media type is a filter, not the primary navigation.
- Use one upload entry point inside a topic. The backend detects the media type automatically.
- Prevent duplicate files per user and topic using `user_id + topic_id + md5`.
- Parse and vectorize documents only. Images, audio, and video are stored as resources but are not searchable by chat yet.

## Product Shape

The knowledge page becomes a workspace with two main areas:

- Left sidebar: one-level topic list and a create-topic action.
- Main panel: selected topic header, resource statistics, type filter tabs, upload resource action, and resource list.

Type filters:

- All
- Documents
- Images
- Audio
- Video

Each resource row shows enough operational detail to understand its state:

- Title or original filename
- Media type
- Processing status
- File size
- Upload date
- Tags when available
- Error message when processing fails

## Backend Model

### `KnowledgeTopic`

New table for top-level user topics.

Fields:

- `id`
- `user_id`
- `name`
- `description`
- `created_at`
- `updated_at`

Constraints:

- `user_id + name` is unique so a user cannot create duplicate topic names.

### `KnowledgeFile`

Extend the existing file table into the canonical uploaded resource metadata table.

Fields:

- `id`
- `user_id`
- `topic_id`
- `item_id`
- `title`
- `original_filename`
- `media_type`: `document`, `image`, `audio`, or `video`
- `mime_type`
- `file_ext`
- `file_size`
- `md5`
- `storage_path`
- `processing_status`: `pending`, `processing`, `completed`, `failed`, or `metadata_only`
- `description`
- `tags`
- `source_type`: initially `upload`
- `page_count`
- `content_text`
- `uploaded_at`
- `last_modified_at`
- `created_at`
- `updated_at`
- `error_message`

Relationships:

- `topic_id` references `KnowledgeTopic.id`.
- `item_id` references `KnowledgeItem.id` for document resources that enter RAG.

Constraints:

- `user_id + topic_id + md5` is unique.

### `KnowledgeItem`

Keep `KnowledgeItem` as the document knowledge entity consumed by the existing ingestion pipeline.

For uploaded document resources:

- Create a linked `KnowledgeItem`.
- Store parsed document text in `KnowledgeItem.content`.
- Also save the same parsed text in `KnowledgeFile.content_text` for resource inspection/debugging.
- Set `KnowledgeItem.category` to the topic name or topic id based on implementation convenience, but keep `KnowledgeFile.topic_id` as the source of truth.

## Media Type Detection

The upload endpoint infers resource type from MIME type and extension.

Document extensions:

- `.pdf`
- `.doc`
- `.docx`
- `.txt`
- `.md`
- `.markdown`

Image extensions:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`

Audio extensions:

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`
- `.ogg`

Video extensions:

- `.mp4`
- `.mov`
- `.avi`
- `.mkv`
- `.webm`

Unsupported files return a clear validation error.

## Upload Flow

Request:

- Client sends `topic_id`, optional `description`, optional `tags`, and one file.
- Backend uses `default-user` for `user_id`.

Backend steps:

1. Validate topic exists for `default-user`.
2. Save the uploaded file to local storage.
3. Calculate MD5 while saving or immediately after saving.
4. Check `user_id + topic_id + md5` uniqueness.
5. Infer `media_type`, `mime_type`, extension, size, and original filename.
6. Create a `KnowledgeFile` row.
7. If media type is `document`, parse text and create a linked `KnowledgeItem`.
8. Trigger or call the existing engine ingest path for the linked item.
9. Update `processing_status`.

Duplicate behavior:

- If the same user uploads the same file into the same topic, return a conflict error.
- The response includes a stable error code such as `duplicate_resource_in_topic`.
- The frontend can localize that error as: `This file has already been uploaded to the current topic.`

## Processing Behavior

### Documents

Documents enter the existing RAG pipeline.

Status flow:

- `pending`
- `processing`
- `completed`
- `failed`

Expected outputs:

- Saved file on disk.
- `KnowledgeFile` metadata.
- Parsed `content_text`.
- Linked `KnowledgeItem`.
- `KnowledgeChunk` rows after ingest.
- Milvus vectors through existing ingestion code.

### Images, Audio, Video

First version stores metadata only.

Status:

- `metadata_only`

These resources appear in the topic resource list and type filters, but they do not affect chat answers yet.

## API Design

### Topics

Add endpoints under the existing backend `/api/v1/knowledge` namespace.

- `POST /api/v1/knowledge/topics`
- `GET /api/v1/knowledge/topics`
- `GET /api/v1/knowledge/topics/{topic_id}`
- `PUT /api/v1/knowledge/topics/{topic_id}`
- `DELETE /api/v1/knowledge/topics/{topic_id}`

Delete behavior:

- First version only allows deleting an empty topic. If resources exist, the API returns a conflict error.

### Resources

Add resource endpoints:

- `POST /api/v1/knowledge/topics/{topic_id}/resources`
- `GET /api/v1/knowledge/topics/{topic_id}/resources`
- `GET /api/v1/knowledge/resources/{resource_id}`
- `DELETE /api/v1/knowledge/resources/{resource_id}`

List filters:

- `media_type`
- `tag`
- `processing_status`

The existing `KnowledgeItem` CRUD endpoints can remain for manual text notes in this phase.

## Frontend Design

`KnowledgePage.tsx` becomes a topic resource workspace.

Core UI:

- Topic sidebar.
- New topic button.
- Empty state when no topic exists.
- Selected topic header with description and resource counts.
- Type filter tabs.
- Upload resource button.
- Resource list with status labels.
- Duplicate upload error display.

Upload behavior:

- User clicks one upload button inside the selected topic.
- File picker accepts all supported extensions.
- Frontend sends the file to the selected topic resource endpoint.
- Backend detects type; frontend does not need separate upload buttons per type.

## Error Handling

Expected errors:

- Topic not found.
- Unsupported file type.
- Duplicate file in current topic.
- Document parse failure.
- Engine ingest failure.
- File storage failure.

Document parse or ingest failure leaves the resource row visible with `processing_status = failed` and an `error_message`.

## Tests

Backend tests:

- Create/list/update topic.
- Prevent duplicate topic name per user.
- Upload document resource and create linked `KnowledgeItem`.
- Prevent duplicate resource per `user_id + topic_id + md5`.
- Upload image/audio/video as `metadata_only`.
- Filter resources by media type.
- Reject unsupported file type.
- Block deletion of a topic with resources.

Engine or ingestion tests:

- Existing `ingest_item` still works for document-backed `KnowledgeItem`.
- Document upload path calls or triggers ingestion with the linked item id.

Frontend tests:

- Knowledge page exposes topic sidebar.
- Upload button is scoped to selected topic.
- Type filters exist and map to backend `media_type` values.
- Duplicate upload error can be displayed.

## Non-Goals

- Multi-level directories.
- Authentication or real user management.
- Image OCR.
- Audio transcription.
- Video frame extraction or transcription.
- Multimedia resources entering chat retrieval.
- Moving resources between topics.
- Bulk upload.
- Cloud object storage.

## Implementation Notes

- Local storage path is deterministic enough for debugging but does not depend on the original filename alone. A good first version path is based on `user_id`, `topic_id`, and `md5`.
- If document parsing libraries are missing for PDF or DOCX, implement parser support incrementally by file type while keeping metadata storage available for all supported extensions.
- The existing auto-migration helper may need to handle new columns, unique constraints, and foreign keys carefully. If it cannot safely add constraints, use explicit migration logic for this feature.
