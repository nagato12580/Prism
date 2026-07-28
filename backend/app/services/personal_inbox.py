from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from re import sub

from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.models import KnowledgeFile, KnowledgeTopic, PersonalAssetItem, PersonalAssetUnit
from backend.app.models.knowledge_types import StageStatus, uuid4_str
from backend.app.services.knowledge_jobs import JobCommand, KnowledgeJobService
from backend.app.services.knowledge_uploads import RedisJobPublisher
from backend.app.storage.files import LocalFileStorage


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
        .one_or_none()
    )
    if topic is not None:
        return topic

    topic = KnowledgeTopic(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        user_id=owner_user_id,
        name=PERSONAL_INBOX_NAME,
        description="系统自动生成的个人资产知识库。",
        system_type=PERSONAL_INBOX_SYSTEM_TYPE,
        is_system=True,
        delete_disabled=True,
    )
    db.add(topic)
    db.flush()
    return topic


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
        filename = _markdown_filename(title, unit.id)
        file_row = (
            db.query(KnowledgeFile)
            .filter_by(
                tenant_id=tenant_id,
                kb_uid=topic.kb_uid,
                source_kind=PERSONAL_ASSET_UNIT_SOURCE_KIND,
                source_id=unit.id,
                deleted_at=None,
            )
            .one_or_none()
        )
        file_uid = file_row.file_uid if file_row is not None else uuid4_str()
        staged = storage.stage(tenant_id, topic.kb_uid, file_uid, filename, content)
        new_storage_uri = storage.commit(staged)

        if file_row is None:
            file_row = KnowledgeFile(
                file_uid=file_uid,
                tenant_id=tenant_id,
                user_id=owner_user_id,
                kb_uid=topic.kb_uid,
                topic_id=topic.id,
                title=title,
                original_filename=filename,
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
            db.add(file_row)
        else:
            old_storage_uri = file_row.storage_uri
            file_row.topic_id = topic.id
            file_row.title = title
            file_row.original_filename = filename
            file_row.relative_path = "personal-inbox"
            file_row.media_type = "document"
            file_row.mime_type = "text/markdown"
            file_row.storage_uri = new_storage_uri
            file_row.content_sha256 = staged.sha256
            file_row.size_bytes = staged.size_bytes
            file_row.file_size = staged.size_bytes
            file_row.md5 = sha256(content).hexdigest()[:32]
            file_row.content_text = markdown
            file_row.system_type = PERSONAL_INBOX_SYSTEM_TYPE
            file_row.parsed_content_version = (file_row.parsed_content_version or 0) + 1

        _reset_processing_state(file_row)
        db.flush()

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
            try:
                storage.delete(old_storage_uri)
            except Exception:
                pass

        if publish:
            try:
                _publish_job(job.id)
                KnowledgeJobService(db).stage_enqueued(job.id)
            except Exception:
                db.rollback()

        db.refresh(file_row)
        return file_row
    except Exception:
        db.rollback()
        if new_storage_uri is not None:
            try:
                storage.delete(new_storage_uri)
            except Exception:
                pass
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
    for unit in units:
        try:
            sync_personal_asset_unit_to_kb(
                db,
                unit,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                publish=publish,
            )
        except Exception:
            db.rollback()
            continue
        synced += 1
    return synced


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


def _markdown_filename(title: str, unit_id: str) -> str:
    safe_title = sub(r"[\\/:*?\"<>|]+", "-", (title or "").strip()).strip(" .")
    if not safe_title:
        safe_title = unit_id
    return f"{safe_title[:120]}.md"
