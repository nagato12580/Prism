from __future__ import annotations

from hashlib import sha256
import logging
from pathlib import Path
from re import sub
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import KnowledgeFile, KnowledgeTopic, PersonalAssetItem, PersonalAssetUnit
from backend.app.models.knowledge_types import StageStatus
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import RedisJobPublisher
from backend.app.storage.files import LocalFileStorage
from backend.app.utils.time import local_now


logger = logging.getLogger(__name__)

PERSONAL_INBOX_NAME = "个人随手记"
PERSONAL_INBOX_SYSTEM_TYPE = "personal_inbox"
PERSONAL_ASSET_UNIT_SOURCE_KIND = "personal_asset_unit"


def _storage() -> LocalFileStorage:
    return LocalFileStorage(Path(settings.KNOWLEDGE_STORAGE_ROOT))


def _publish_job(job_id: str) -> None:
    RedisJobPublisher(settings.REDIS_URL, settings.KNOWLEDGE_INGEST_QUEUE).publish(job_id)


def ensure_personal_inbox_kb(
    db: Session,
    *,
    tenant_id: str,
    owner_user_id: str,
) -> KnowledgeTopic:
    topic = (
        db.query(KnowledgeTopic)
        .filter_by(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            system_type=PERSONAL_INBOX_SYSTEM_TYPE,
            deleted_at=None,
        )
        .order_by(KnowledgeTopic.created_at.asc(), KnowledgeTopic.id.asc())
        .first()
    )
    if topic is not None:
        return topic

    topic = KnowledgeTopic(
        kb_uid=_personal_inbox_kb_uid(tenant_id, owner_user_id),
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        user_id=owner_user_id,
        name=PERSONAL_INBOX_NAME,
        description="系统自动生成的个人资产知识库。",
        system_type=PERSONAL_INBOX_SYSTEM_TYPE,
        is_system=True,
        delete_disabled=True,
    )
    try:
        with db.begin_nested():
            db.add(topic)
            db.flush()
        return topic
    except IntegrityError:
        existing = (
            db.query(KnowledgeTopic)
            .filter_by(
                kb_uid=_personal_inbox_kb_uid(tenant_id, owner_user_id),
                deleted_at=None,
            )
            .order_by(KnowledgeTopic.created_at.asc(), KnowledgeTopic.id.asc())
            .first()
        )
        if existing is not None:
            return existing
        raise


def render_personal_asset_unit_markdown(db: Session, unit: PersonalAssetUnit) -> str:
    lines: list[str] = [
        f"# {unit.title}",
        "",
        "## 元数据",
        f"- ID: {unit.id}",
        f"- 来源: {PERSONAL_ASSET_UNIT_SOURCE_KIND}",
        f"- 类型: {unit.category or unit.status or ''}",
        f"- 更新时间: {unit.updated_at.isoformat() if unit.updated_at else ''}",
    ]
    if unit.tags:
        lines.append(f"- 标签: {', '.join(str(tag) for tag in unit.tags)}")

    if unit.summary:
        lines.extend(["", "## 摘要", unit.summary])
    if unit.content:
        lines.extend(["", "## 内容", unit.content])

    source_ids = list(unit.source_asset_ids or [])
    if source_ids:
        items = (
            db.query(PersonalAssetItem)
            .filter(PersonalAssetItem.id.in_(source_ids))
            .all()
        )
        by_id = {item.id: item for item in items}
        lines.extend(["", "## 来源片段"])
        for source_id in source_ids:
            item = by_id.get(source_id)
            if item is None:
                continue
            item_title = item.title or item.raw_title or item.id
            lines.extend(["", f"### {item_title}", f"- ID: {item.id}"])
            if item.raw_title and item.raw_title != item_title:
                lines.append(f"- 原始标题: {item.raw_title}")
            if item.summary:
                lines.extend(["", item.summary])
            item_content = item.rewritten_content or item.body or item.summary
            if item_content:
                lines.extend(["", item_content])

    return "\n".join(lines).rstrip() + "\n"


def sync_personal_asset_unit_to_kb(
    db: Session,
    unit: PersonalAssetUnit,
    *,
    tenant_id: str,
    owner_user_id: str,
    publish: bool = True,
) -> KnowledgeFile:
    if unit.status != "confirmed":
        raise ValueError("Only confirmed personal asset units can be synced")
    if unit.user_id != owner_user_id:
        raise ValueError("Personal asset unit does not belong to owner_user_id")

    storage = _storage()
    old_storage_uri: str | None = None
    new_storage_uri: str | None = None
    try:
        topic = ensure_personal_inbox_kb(
            db,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        markdown = render_personal_asset_unit_markdown(db, unit)
        content = markdown.encode("utf-8")
        title = unit.title or unit.id
        original_filename = _markdown_filename(title, unit.id)
        file_row = _upsert_personal_inbox_file(
            db,
            storage,
            topic,
            unit,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title=title,
            original_filename=original_filename,
            markdown=markdown,
            content=content,
        )
        old_storage_uri = getattr(file_row, "_previous_storage_uri", None)
        new_storage_uri = file_row.storage_uri

        job = KnowledgeJobService(db).create(
            JobCommand(
                "parse",
                tenant_id,
                topic.kb_uid,
                file_row.file_uid,
                {"auto_index": True},
            ),
            f"{topic.kb_uid}:{file_row.file_uid}:parse:v{file_row.parsed_content_version}",
            commit=False,
        )
        file_row.last_job_id = job.id
        db.commit()

        if old_storage_uri and old_storage_uri != new_storage_uri:
            _delete_storage_if_unreferenced(db, storage, old_storage_uri)

        if publish:
            try:
                _publish_job(job.id)
                KnowledgeJobService(db).stage_enqueued(job.id)
            except Exception:
                logger.exception("Failed to publish personal inbox parse job: job_id=%s", job.id)
                db.rollback()

        db.refresh(file_row)
        return file_row
    except Exception:
        db.rollback()
        if new_storage_uri is not None:
            _delete_storage_if_unreferenced(db, storage, new_storage_uri)
        raise


def backfill_personal_inbox(
    db: Session,
    *,
    tenant_id: str,
    owner_user_id: str,
    publish: bool = True,
) -> int:
    units = (
        db.query(PersonalAssetUnit)
        .filter_by(user_id=owner_user_id, status="confirmed")
        .order_by(PersonalAssetUnit.created_at.asc(), PersonalAssetUnit.id.asc())
        .all()
    )
    synced = 0
    topic = ensure_personal_inbox_kb(
        db,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    for unit in units:
        try:
            if _personal_inbox_file_is_current(
                db,
                unit,
                topic,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            ):
                continue
            sync_personal_asset_unit_to_kb(
                db,
                unit,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                publish=publish,
            )
        except Exception:
            logger.exception("Failed to backfill personal inbox unit: unit_id=%s", unit.id)
            db.rollback()
            continue
        synced += 1
    return synced


def is_personal_inbox_asset_unit_file(file_row: KnowledgeFile) -> bool:
    return (
        file_row.system_type == PERSONAL_INBOX_SYSTEM_TYPE
        and file_row.source_kind == PERSONAL_ASSET_UNIT_SOURCE_KIND
        and bool(file_row.source_id)
    )


def delete_personal_inbox_file_cascade(
    db: Session,
    file_row: KnowledgeFile,
    *,
    tenant_id: str,
):
    if not is_personal_inbox_asset_unit_file(file_row):
        raise ValueError("Only derived personal inbox asset unit files can be cascade-deleted")

    unit = (
        db.query(PersonalAssetUnit)
        .filter_by(id=file_row.source_id)
        .with_for_update()
        .one_or_none()
    )
    source_asset_ids = list(unit.source_asset_ids or []) if unit is not None else []
    if unit is not None:
        db.delete(unit)
        db.flush()

    referenced_item_ids = _referenced_personal_asset_ids(db, source_asset_ids)
    for item_id in source_asset_ids:
        if item_id in referenced_item_ids:
            continue
        item = (
            db.query(PersonalAssetItem)
            .filter_by(id=item_id)
            .with_for_update()
            .one_or_none()
        )
        if item is not None:
            db.delete(item)

    job = KnowledgeJobService(db).create(
        JobCommand("delete", tenant_id, file_row.kb_uid, file_row.file_uid, {}),
        f"{file_row.kb_uid}:{file_row.file_uid}:delete",
        commit=False,
    )
    file_row.deleted_at = local_now()
    file_row.last_job_id = job.id

    from engine.app.knowledge.enrichment import mark_enrichment_stale

    mark_enrichment_stale(
        db,
        file_row.kb_uid,
        reason="file_deleted",
        deleted_file_uids=[file_row.file_uid],
        commit=False,
    )
    return job


def _personal_inbox_file_is_current(
    db: Session,
    unit: PersonalAssetUnit,
    topic: KnowledgeTopic,
    *,
    tenant_id: str,
    owner_user_id: str,
) -> bool:
    file_row = _load_personal_inbox_file(db, tenant_id, topic.kb_uid, unit.id, lock=False)
    if file_row is None:
        file_row = _load_personal_inbox_file_by_uid(
            db,
            _personal_inbox_file_uid(tenant_id, owner_user_id, unit.id),
            lock=False,
        )
    if file_row is None:
        return False

    markdown = render_personal_asset_unit_markdown(db, unit)
    content_sha256 = sha256(markdown.encode("utf-8")).hexdigest()
    content_matches = file_row.content_sha256 == content_sha256
    if not content_matches and file_row.content_text is not None:
        content_matches = file_row.content_text == markdown

    return (
        content_matches
        and file_row.tenant_id == tenant_id
        and file_row.user_id == owner_user_id
        and file_row.kb_uid == topic.kb_uid
        and file_row.topic_id == topic.id
        and file_row.source_kind == PERSONAL_ASSET_UNIT_SOURCE_KIND
        and file_row.source_id == unit.id
        and file_row.system_type == PERSONAL_INBOX_SYSTEM_TYPE
        and file_row.deleted_at is None
    )


def _referenced_personal_asset_ids(db: Session, item_ids: list[str]) -> set[str]:
    candidate_ids = set(item_ids)
    if not candidate_ids:
        return set()
    units = db.query(PersonalAssetUnit.id, PersonalAssetUnit.source_asset_ids).all()
    referenced_ids: set[str] = set()
    for _, source_asset_ids in units:
        referenced_ids.update(candidate_ids.intersection(source_asset_ids or []))
    return referenced_ids


def _reset_processing_state(file_row: KnowledgeFile) -> None:
    file_row.parse_status = StageStatus.PENDING.value
    file_row.index_status = StageStatus.PENDING.value
    file_row.graph_status = StageStatus.PENDING.value
    file_row.parse_error = None
    file_row.index_error = None
    file_row.graph_error = None
    file_row.parse_started_at = None
    file_row.parse_finished_at = None
    file_row.index_started_at = None
    file_row.index_finished_at = None
    file_row.graph_started_at = None
    file_row.graph_finished_at = None
    file_row.active_index_generation = None
    file_row.error_message = None


def _upsert_personal_inbox_file(
    db: Session,
    storage: LocalFileStorage,
    topic: KnowledgeTopic,
    unit: PersonalAssetUnit,
    *,
    tenant_id: str,
    owner_user_id: str,
    title: str,
    original_filename: str,
    markdown: str,
    content: bytes,
) -> KnowledgeFile:
    file_uid = _personal_inbox_file_uid(tenant_id, owner_user_id, unit.id)
    file_row = _load_personal_inbox_file(db, tenant_id, topic.kb_uid, unit.id, lock=True)
    if file_row is None:
        file_row = _load_personal_inbox_file_by_uid(db, file_uid, lock=True)

    while True:
        next_version = (file_row.parsed_content_version + 1) if file_row is not None else 0
        storage_filename = _storage_markdown_filename(title, unit.id, next_version)
        staged = storage.stage(tenant_id, topic.kb_uid, file_uid, storage_filename, content)
        new_storage_uri = storage.commit(staged)

        if file_row is None:
            candidate = KnowledgeFile(
                file_uid=file_uid,
                tenant_id=tenant_id,
                user_id=owner_user_id,
                kb_uid=topic.kb_uid,
                topic_id=topic.id,
                title=title,
                original_filename=original_filename,
                relative_path="personal-inbox",
                media_type="document",
                mime_type="text/markdown",
                storage_uri=new_storage_uri,
                content_sha256=staged.sha256,
                size_bytes=staged.size_bytes,
                file_size=staged.size_bytes,
                md5=sha256(content).hexdigest()[:32],
                content_text=markdown,
                source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
                source_id=unit.id,
                system_type=PERSONAL_INBOX_SYSTEM_TYPE,
                parse_status=StageStatus.PENDING.value,
                index_status=StageStatus.PENDING.value,
                graph_status=StageStatus.PENDING.value,
                parsed_content_version=0,
            )
            _reset_processing_state(candidate)
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                candidate._previous_storage_uri = None
                return candidate
            except IntegrityError:
                _delete_storage_if_unreferenced(db, storage, new_storage_uri)
                file_row = _load_personal_inbox_file(db, tenant_id, topic.kb_uid, unit.id, lock=True)
                if file_row is None:
                    file_row = _load_personal_inbox_file_by_uid(db, file_uid, lock=True)
                if file_row is None:
                    raise
                continue

        old_storage_uri = file_row.storage_uri
        file_row.topic_id = topic.id
        file_row.title = title
        file_row.original_filename = original_filename
        file_row.relative_path = "personal-inbox"
        file_row.media_type = "document"
        file_row.mime_type = "text/markdown"
        file_row.storage_uri = new_storage_uri
        file_row.content_sha256 = staged.sha256
        file_row.size_bytes = staged.size_bytes
        file_row.file_size = staged.size_bytes
        file_row.md5 = sha256(content).hexdigest()[:32]
        file_row.content_text = markdown
        file_row.source_kind = PERSONAL_ASSET_UNIT_SOURCE_KIND
        file_row.source_id = unit.id
        file_row.system_type = PERSONAL_INBOX_SYSTEM_TYPE
        file_row.parsed_content_version = next_version
        _reset_processing_state(file_row)
        db.flush()
        file_row._previous_storage_uri = old_storage_uri
        return file_row


def _load_personal_inbox_file(
    db: Session,
    tenant_id: str,
    kb_uid: str,
    unit_id: str,
    *,
    lock: bool,
) -> KnowledgeFile | None:
    query = db.query(KnowledgeFile).filter_by(
        tenant_id=tenant_id,
        kb_uid=kb_uid,
        source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
        source_id=unit_id,
        deleted_at=None,
    )
    if lock:
        query = query.with_for_update()
    return query.order_by(KnowledgeFile.created_at.asc(), KnowledgeFile.id.asc()).first()


def _load_personal_inbox_file_by_uid(
    db: Session,
    file_uid: str,
    *,
    lock: bool,
) -> KnowledgeFile | None:
    query = db.query(KnowledgeFile).filter_by(file_uid=file_uid, deleted_at=None)
    if lock:
        query = query.with_for_update()
    return query.order_by(KnowledgeFile.created_at.asc(), KnowledgeFile.id.asc()).first()


def _storage_uri_is_referenced(db: Session, storage_uri: str) -> bool:
    return (
        db.query(KnowledgeFile.id)
        .filter_by(storage_uri=storage_uri, deleted_at=None)
        .first()
        is not None
    )


def _delete_storage_if_unreferenced(
    db: Session,
    storage: LocalFileStorage,
    storage_uri: str | None,
) -> None:
    if storage_uri is None or _storage_uri_is_referenced(db, storage_uri):
        return
    try:
        storage.delete(storage_uri)
    except Exception:
        logger.exception(
            "Failed to delete unreferenced personal inbox storage: storage_uri=%s",
            storage_uri,
        )


def _markdown_filename(title: str, unit_id: str) -> str:
    safe_title = sub(r"[\\/:*?\"<>|]+", "-", (title or "").strip()).strip(" .")
    if not safe_title:
        safe_title = unit_id
    return f"{safe_title[:120]}.md"


def _storage_markdown_filename(title: str, unit_id: str, version: int) -> str:
    safe_title = sub(r"[\\/:*?\"<>|]+", "-", (title or "").strip()).strip(" .")
    if not safe_title:
        safe_title = unit_id
    suffix = f"{unit_id[:8]}-v{version}-{uuid4().hex[:8]}"
    return f"{safe_title[:100]}-{suffix}.md"


def _personal_inbox_kb_uid(tenant_id: str, owner_user_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"prism:personal-inbox-kb:{tenant_id}:{owner_user_id}"))


def _personal_inbox_file_uid(tenant_id: str, owner_user_id: str, unit_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"prism:personal-inbox-file:{tenant_id}:{owner_user_id}:{unit_id}"))
