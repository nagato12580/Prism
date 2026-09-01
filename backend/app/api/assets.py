# prism/backend/app/api/assets.py
import logging
import os
import threading
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from openai import OpenAI
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..security.actor import ActorContext, get_actor_context
from ..prompts.asset_parse import (
    build_asset_parse_messages,
    build_knowledge_synthesis_messages,
)
from ..models.asset import AssetRelation, AssetUsageEvent, ExtensionPoint, PersonalAsset, PersonalAssetItem, PersonalAssetUnit
from ..models.memory import MemoryEntry
from ..services.knowledge_governance import GovernanceResult
from ..services.asset_items import (
    _clean_dict_list,
    _clean_tags,
    _keyword_index_text,
    _parse_json_object,
    _short_title,
    create_asset_item_from_raw,
)
from ..services.memory_context import recall_preference_context
from ..services.memory_entity import extract_and_link_entities
from ..services.memory_extraction import _check_semantic_duplicate
from ..services.memory_vectors import upsert_entry_vector
from ..services.personal_inbox import sync_personal_asset_unit_to_kb
from ..utils.time import local_now
from ..schemas.asset import (
    AssetConfirmRequest,
    AssetConfirmResponse,
    AssetDraftCreate,
    AssetDraftOut,
    AssetDraftUpdate,
    AssetOverviewOut,
    AssetRegenerateRequest,
    AssetSearchResult,
    PersonalAssetItemCreate,
    PersonalAssetItemOut,
    PersonalAssetItemUpdate,
    PersonalAssetOut,
    PersonalAssetUnitConfirmResponse,
    PersonalAssetUnitCreate,
    PersonalAssetUnitOut,
    PersonalAssetUnitUpdate,
)
from engine.app.graph.pipeline import run_graph_ingest_pipeline

router = APIRouter(prefix="/assets", tags=["assets"])
DEFAULT_USER_ID = "default-user"
DEFAULT_TENANT_ID = "default-user"
log = logging.getLogger(__name__)


_MEMORY_TYPE_BY_KIND = {
    "preference": "preference",
    "goal": "goal",
    "fact": "fact",
}


def _memory_type_from_kind(asset_kind: str | None) -> str:
    normalized = (asset_kind or "").strip().lower()
    return _MEMORY_TYPE_BY_KIND.get(normalized, "context")


def _index_entry_vector(entry: MemoryEntry) -> None:
    """资产沉淀记忆写入后建向量索引；失败不阻塞入库，仅标记 pending 供回填。"""
    try:
        vector_id = upsert_entry_vector(entry)
    except Exception:
        vector_id = ""
    if vector_id:
        entry.embedding_ref = vector_id
        entry.embedding_model = settings.EMBEDDING_MODEL
        entry.embedding_status = "done"
    else:
        entry.embedding_status = "pending"


def _merge_confirmed_extensions(
    current: Any,
    confirmed: list[dict[str, Any]],
    *,
    confirmed_at: datetime,
) -> tuple[list[dict[str, Any]], int]:
    extensions = _clean_dict_list(current)
    by_title = {
        str(item.get("title") or "").strip(): index
        for index, item in enumerate(extensions)
        if str(item.get("title") or "").strip()
    }
    count = 0
    timestamp = confirmed_at.isoformat()

    for extension in confirmed:
        title = str(extension.get("title") or "").strip()
        if not title:
            continue
        normalized = {
            **extension,
            "title": title[:255],
            "reason": str(extension.get("reason") or "")[:1000],
            "suggested_kind": str(extension.get("suggested_kind") or "knowledge")[:64],
            "confidence": float(extension.get("confidence") or 0.5),
            "status": "confirmed",
            "confirmed_at": timestamp,
        }
        if title in by_title:
            extensions[by_title[title]] = {**extensions[by_title[title]], **normalized}
        else:
            by_title[title] = len(extensions)
            extensions.append(normalized)
        count += 1

    return extensions, count


def _asset_result(asset: PersonalAsset, score: float) -> AssetSearchResult:
    return AssetSearchResult(
        asset_id=asset.id,
        asset_kind=asset.asset_kind,
        title=asset.title,
        summary=asset.summary,
        source_type=asset.source_type,
        source_platform=asset.source_platform,
        tags=asset.tags or [],
        category=asset.category,
        score=score,
    )


def _asset_text(asset: PersonalAsset) -> str:
    return "\n".join(
        part
        for part in [
            f"标题：{asset.title}",
            f"类型：{asset.asset_kind}",
            f"分类：{asset.category}",
            f"标签：{', '.join(asset.tags or [])}",
            f"摘要：{asset.summary or ''}",
            f"正文：{asset.body or ''}",
        ]
        if part.strip()
    )


def _fallback_personal_asset_unit(assets: list[PersonalAsset], title: str = "", instruction: str = "") -> dict[str, Any]:
    categories = Counter(asset.category or "未分类" for asset in assets)
    tags: Counter[str] = Counter()
    for asset in assets:
        tags.update(asset.tags or [])
    content_parts = []
    for index, asset in enumerate(assets, start=1):
        content_parts.append(
            f"## {index}. {asset.title}\n\n"
            f"{asset.summary or asset.body or ''}\n\n"
            f"- 类型：{asset.asset_kind}\n"
            f"- 分类：{asset.category or '未分类'}\n"
            f"- 标签：{', '.join(asset.tags or [])}"
        )
    leading_category = categories.most_common(1)[0][0] if categories else "知识整理"
    return {
        "title": title or f"{leading_category}知识整理",
        "summary": f"基于 {len(assets)} 条个人知识资产整理出的知识草稿。",
        "content": "\n\n".join(content_parts),
        "category": leading_category,
        "tags": [name for name, _ in tags.most_common(8)] or [leading_category],
        "outline": [{"title": asset.title, "asset_id": asset.id} for asset in assets[:12]],
        "confidence": {"overall": 0.45, "synthesis": 0.45},
        "rationale": "AI 汇编不可用，使用资产摘要兜底生成可编辑知识草稿。",
    }


def _ai_synthesize_knowledge(assets: list[Any], title: str = "", instruction: str = "") -> dict[str, Any] | None:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return None
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    system_prompt, user_message = build_knowledge_synthesis_messages(
        assets=assets,
        title=title,
        instruction=instruction,
    )
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=2400,
        )
        return _parse_json_object(resp.choices[0].message.content or "")
    except Exception:
        return None


def _normalize_personal_asset_unit(
    assets: list[Any],
    parsed: dict[str, Any] | None,
    *,
    title: str = "",
    instruction: str = "",
) -> dict[str, Any]:
    fallback = _fallback_personal_asset_unit(assets, title=title, instruction=instruction)
    data = parsed if isinstance(parsed, dict) else fallback
    return {
        "title": _short_title(str(data.get("title") or fallback["title"]), "知识草稿"),
        "summary": str(data.get("summary") or fallback["summary"]).strip()[:1200],
        "content": str(data.get("content") or fallback["content"]).strip(),
        "category": str(data.get("category") or fallback["category"]).strip()[:128],
        "tags": _clean_tags(data.get("tags")) or fallback["tags"],
        "outline": _clean_dict_list(data.get("outline")) or fallback["outline"],
        "confidence": data.get("confidence") if isinstance(data.get("confidence"), dict) else fallback["confidence"],
        "rationale": str(data.get("rationale") or fallback["rationale"]).strip()[:1200],
    }


def _item_body(item: PersonalAssetItem) -> str:
    extract_text = "\n".join(str(entry.get("content", "")) for entry in (item.extracts or []) if isinstance(entry, dict))
    return item.rewritten_content or item.body or extract_text or item.summary or item.raw_text


def _item_result(item: PersonalAssetItem, score: float) -> AssetSearchResult:
    return AssetSearchResult(
        asset_id=item.id,
        asset_kind=item.asset_kind,
        title=item.title,
        summary=item.summary,
        source_type=item.source_type,
        source_platform=item.source_platform,
        tags=item.tags or [],
        category=item.category,
        score=score,
    )


def _asset_unit_entity_graph_text(unit: PersonalAssetUnit) -> str:
    parts = [unit.title or "", unit.summary or "", unit.content or ""]
    return "\n\n".join(part.strip() for part in parts if part and part.strip())[:4000]


def _ingest_asset_unit_entity_graph(db: Session, unit: PersonalAssetUnit) -> None:
    text = _asset_unit_entity_graph_text(unit)
    if not text:
        return
    run_graph_ingest_pipeline(
        {
            "source_kind": "personal_asset_unit",
            "source_id": unit.id,
            "item_id": unit.id,
            "text": text,
            "user_id": unit.user_id or DEFAULT_USER_ID,
        },
        db=db,
    )


def _run_asset_unit_entity_graph_ingestion(unit_id: str, user_id: str) -> None:
    db = SessionLocal()
    try:
        unit = (
            db.query(PersonalAssetUnit)
            .filter(
                PersonalAssetUnit.id == unit_id,
                PersonalAssetUnit.user_id == user_id,
            )
            .first()
        )
        if not unit or unit.status != "confirmed":
            return
        _ingest_asset_unit_entity_graph(db, unit)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Failed to ingest personal asset unit entity graph", extra={"unit_id": unit_id})
    finally:
        db.close()


def _schedule_asset_unit_entity_graph_ingestion(unit_id: str, user_id: str) -> None:
    thread = threading.Thread(
        target=_run_asset_unit_entity_graph_ingestion,
        args=(unit_id, user_id),
        daemon=True,
        name=f"asset-unit-graph-ingest-{unit_id}",
    )
    thread.start()


def _ai_parse_asset(
    *,
    content: str,
    title: str = "",
    source_type: str = "manual",
    source_platform: str = "",
    source_url: str = "",
    user_preferences: str = "",
) -> dict[str, Any] | None:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return None
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    system_prompt, user_message = build_asset_parse_messages(
        content=content,
        title=title,
        source_type=source_type,
        source_platform=source_platform,
        source_url=source_url,
        user_preferences=user_preferences,
    )
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2
        )
        return _parse_json_object(resp.choices[0].message.content or "")
    except Exception:
        return None


def _create_asset_item_from_raw(
    *,
    db: Session,
    raw_text: str,
    raw_title: str = "",
    raw_source_type: str = "manual",
    raw_source_platform: str = "",
    raw_source_url: str = "",
    raw_author: str = "",
    raw_tags: list[str] | None = None,
    raw_metadata: dict[str, Any] | None = None,
    user_id: str = DEFAULT_USER_ID,
) -> PersonalAssetItem:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail={"code": "empty_content", "message": "Content is required"})

    user_preferences = ""
    try:
        user_preferences = recall_preference_context(db, raw_text, user_id=user_id)
    except Exception:
        user_preferences = ""

    parsed = _ai_parse_asset(
        content=raw_text,
        title=raw_title,
        source_type=raw_source_type,
        source_platform=raw_source_platform,
        source_url=raw_source_url,
        user_preferences=user_preferences,
    )
    return create_asset_item_from_raw(
        db,
        raw_text=raw_text,
        raw_title=raw_title,
        raw_source_type=raw_source_type,
        raw_source_platform=raw_source_platform,
        raw_source_url=raw_source_url,
        raw_author=raw_author,
        raw_tags=raw_tags,
        raw_metadata=raw_metadata,
        parsed=parsed,
        user_id=user_id,
    )


@router.post("/items", response_model=PersonalAssetItemOut)
def create_asset_item(
    payload: PersonalAssetItemCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    return _create_asset_item_from_raw(
        db=db,
        raw_text=payload.raw_text,
        raw_title=payload.raw_title or "",
        raw_source_type=payload.raw_source_type,
        raw_source_platform=payload.raw_source_platform or "",
        raw_source_url=payload.raw_source_url or "",
        raw_author=payload.raw_author or "",
        raw_tags=payload.raw_tags,
        raw_metadata=payload.raw_metadata,
        user_id=actor.actor_id,
    )


# ---------------------------------------------------------------------------
# Voice-to-asset-item
# ---------------------------------------------------------------------------

AUDIO_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "voice"
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".webm", ".m4a", ".aac"}
_MAX_AUDIO_SIZE_MB = 25
_MAX_AUDIO_SIZE_BYTES = _MAX_AUDIO_SIZE_MB * 1024 * 1024


def _validate_audio_format(filename: str, content_type: str | None) -> str:
    """Validate audio file extension and return lowercase extension.

    Raises HTTPException(400) on unsupported format.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    # Fallback: try to infer extension from MIME type
    mime_to_ext = {
        "audio/webm": ".webm",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-m4a": ".m4a",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
    }
    if ext not in _ALLOWED_AUDIO_EXTENSIONS and content_type:
        ext = mime_to_ext.get(content_type.split(";")[0].strip(), ext)
    if ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_audio_format",
                "message": f"不支持的音频格式：{ext or '未知'}，支持 mp3/wav/webm/m4a/aac",
            },
        )
    return ext


@router.post("/voice", response_model=PersonalAssetItemOut, status_code=201)
async def voice_to_asset_item(
    audio_file: UploadFile = File(...),
    source_type: str = Form("recording"),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """语音转写并创建资产碎片。

    接收音频文件，通过 DashScope ASR 转写为文字，然后走
    _create_asset_item_from_raw() 进行 AI 解析并放入收件箱。
    """
    # 1) 验证文件大小（读入内存校验）
    audio_bytes = await audio_file.read()
    if len(audio_bytes) > _MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": f"音频文件不能超过 {_MAX_AUDIO_SIZE_MB}MB",
            },
        )

    # 2) 验证格式
    ext = _validate_audio_format(audio_file.filename or "", audio_file.content_type)

    # 3) 保存到本地
    audio_name = f"{uuid.uuid4().hex}{ext}"
    audio_path = AUDIO_UPLOAD_DIR / audio_name
    try:
        audio_path.write_bytes(audio_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"code": "file_write_failed", "message": "音频文件保存失败，请稍后重试"},
        ) from e

    # 4) 调用 ASR 转写
    from ..services.asr import transcribe, ASRError

    try:
        text = await transcribe(
            provider=settings.ASR_PROVIDER,
            api_key=settings.ASR_API_KEY,
            model=settings.ASR_MODEL,
            audio_path=str(audio_path),
        )
    except ASRError as exc:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=500,
            detail={"code": "asr_failed", "message": str(exc)},
        ) from exc

    # 5) 转写成功，删除音频文件（文本已存入数据库）
    try:
        audio_path.unlink(missing_ok=True)
    except Exception:
        pass

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_speech_detected",
                "message": "未检测到语音内容，请重新录制",
            },
        )

    # 6) 走现有资产创建管线
    return _create_asset_item_from_raw(
        db=db,
        raw_text=text.strip(),
        raw_source_type="voice",
        raw_source_platform=source_type,  # "recording" or "upload"
        raw_metadata={
            "audio_path": str(audio_path.relative_to(AUDIO_UPLOAD_DIR.parent)),
            "audio_filename": audio_file.filename,
            "audio_content_type": audio_file.content_type,
            "audio_size_bytes": len(audio_bytes),
        },
        user_id=actor.actor_id,
    )


@router.get("/items", response_model=list[PersonalAssetItemOut])
def list_asset_items(
    status: Optional[str] = Query("pending_review"),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    query = db.query(PersonalAssetItem).filter(PersonalAssetItem.user_id == actor.actor_id)
    if status:
        query = query.filter(PersonalAssetItem.status == status)
    return query.order_by(PersonalAssetItem.updated_at.desc()).all()


@router.put("/items/{item_id}", response_model=PersonalAssetItemOut)
def update_asset_item(
    item_id: str,
    payload: PersonalAssetItemUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id, PersonalAssetItem.user_id == actor.actor_id).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status not in {"pending_review", "confirmed"}:
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Personal asset item cannot be edited"})
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if key in {"tags", "raw_tags", "raw_keywords"}:
            value = _clean_tags(value)
        elif key in {"extracts", "suggested_relations", "suggested_extensions"}:
            value = _clean_dict_list(value)
        setattr(item, key, value)
    item.edited_at = local_now()
    item.keyword_index_text = _keyword_index_text(
        item.raw_title,
        item.raw_text,
        item.raw_tags,
        item.raw_keywords,
        item.title,
        item.summary,
        item.rewritten_content,
        item.body,
        item.tags,
        item.category,
    )
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}")
def delete_asset_item(
    item_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id, PersonalAssetItem.user_id == actor.actor_id).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status != "pending_review":
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Only pending asset items can be deleted"})
    db.query(AssetRelation).filter(
        AssetRelation.user_id == actor.actor_id,
        or_(AssetRelation.from_asset_id == item.id, AssetRelation.to_asset_id == item.id),
    ).delete(synchronize_session=False)
    db.query(ExtensionPoint).filter(
        ExtensionPoint.user_id == actor.actor_id,
        ExtensionPoint.asset_id == item.id,
    ).delete(synchronize_session=False)
    db.query(AssetUsageEvent).filter(
        AssetUsageEvent.user_id == actor.actor_id,
        AssetUsageEvent.asset_id == item.id,
    ).delete(synchronize_session=False)
    db.delete(item)
    db.commit()
    return {"detail": "deleted"}


@router.post("/items/{item_id}/regenerate", response_model=PersonalAssetItemOut)
def regenerate_asset_item(
    item_id: str,
    payload: AssetRegenerateRequest | None = None,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    """调用 AI 重新规范化记录的 Markdown 改写内容和摘要。

    使用请求体中的 raw_text（未提供则从数据库读取）调用 capture_normalize LLM，
    覆盖 rewritten_content 和 summary 字段。其他字段仅在 LLM 返回有效新值时才更新。
    """
    item = db.query(PersonalAssetItem).filter(
        PersonalAssetItem.id == item_id,
        PersonalAssetItem.user_id == actor.actor_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status != "pending_review":
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Only pending asset items can be regenerated"})

    raw_text = ((payload.raw_text or "").strip() if payload and payload.raw_text else item.raw_text).strip()
    title_hint = ((payload.title or "").strip() if payload and payload.title else (item.raw_title or "")).strip()

    from ..prompts.asset_parse import build_capture_normalize_messages

    try:
        system_prompt, user_message = build_capture_normalize_messages(
            content=raw_text,
            title=title_hint,
        )
        client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )
        data = _parse_json_object(resp.choices[0].message.content or "")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "regenerate_failed", "message": f"AI 重新生成失败：{exc}"},
        ) from exc

    content_md = str(data.get("content_md") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not content_md:
        raise HTTPException(
            status_code=422,
            detail={"code": "regenerate_empty", "message": "AI 返回的内容为空，请稍后重试"},
        )

    item.rewritten_content = content_md
    if summary:
        item.summary = summary
    new_title = str(data.get("title") or "").strip()
    if new_title:
        item.title = new_title[:255]
    new_kind = str(data.get("asset_kind") or "").strip()
    if new_kind:
        item.asset_kind = new_kind[:64]
    new_category = str(data.get("category") or "").strip()
    if new_category:
        item.category = new_category[:128]
    new_tags = data.get("tags")
    if isinstance(new_tags, list):
        item.tags = _clean_tags(new_tags)
    item.edited_at = local_now()
    item.keyword_index_text = _keyword_index_text(
        item.raw_title, item.raw_text, item.raw_tags, item.raw_keywords,
        item.title, item.summary, item.rewritten_content, item.tags, item.category,
    )
    db.commit()
    db.refresh(item)
    return item


@router.post("/items/{item_id}/confirm", response_model=AssetConfirmResponse)
def confirm_asset_item(
    item_id: str,
    payload: AssetConfirmRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    item = db.query(PersonalAssetItem).filter(PersonalAssetItem.id == item_id, PersonalAssetItem.user_id == actor.actor_id).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "asset_item_not_found", "message": "Personal asset item not found"})
    if item.status != "pending_review":
        raise HTTPException(status_code=409, detail={"code": "asset_item_closed", "message": "Personal asset item is already closed"})

    relation_count = 0
    for relation in payload.confirm_relations:
        target_id = str(relation.get("target_asset_id") or relation.get("to_asset_id") or "")
        if not target_id:
            continue
        target = db.query(PersonalAssetItem.id).filter(PersonalAssetItem.id == target_id, PersonalAssetItem.user_id == actor.actor_id).first()
        if not target:
            continue
        db.add(
            AssetRelation(
                user_id=actor.actor_id,
                from_asset_id=item.id,
                to_asset_id=target_id,
                relation_type=str(relation.get("relation_type") or "related")[:64],
                reason=str(relation.get("reason") or "")[:1000],
                confidence=float(relation.get("confidence") or 0.5),
                source_draft_id=item.id,
            )
        )
        relation_count += 1

    reviewed_at = local_now()
    item.suggested_extensions, extension_count = _merge_confirmed_extensions(
        item.suggested_extensions,
        _clean_dict_list(payload.confirm_extensions),
        confirmed_at=reviewed_at,
    )

    memory_entry = None
    if payload.create_memory:
        entry_content = (item.summary or item.raw_text or "").strip()
        is_duplicate, _ = _check_semantic_duplicate(db, entry_content, user_id=actor.actor_id)
        if not is_duplicate:
            memory_entry = MemoryEntry(
                user_id=actor.actor_id,
                title=item.title,
                content=item.summary or item.raw_text,
                memory_type=_memory_type_from_kind(item.asset_kind),
                category=item.category,
                tags=item.tags or [],
                importance=max(0.6, float((item.confidence or {}).get("overall", 0.6) or 0.6)),
                source_raw_item_id=item.id,
                source_review_id=item.id,
            )
            db.add(memory_entry)
            db.flush()

    item.status = "confirmed"
    item.reviewed_at = reviewed_at
    item.confirmed_at = reviewed_at
    governance = GovernanceResult(pku_count=0, canonical_count=0, link_count=0)

    if memory_entry is not None:
        _index_entry_vector(memory_entry)
        try:
            extract_and_link_entities(
                db,
                content=memory_entry.title or memory_entry.content,
                source_id=memory_entry.id,
                user_id=actor.actor_id,
            )
        except Exception:
            pass

    db.commit()
    db.refresh(item)
    return AssetConfirmResponse(
        item=item,
        draft=item,
        asset=item,
        relation_count=relation_count,
        extension_count=extension_count,
        pku_count=governance.pku_count,
        canonical_count=governance.canonical_count,
        governance_link_count=governance.link_count,
    )


@router.post("/drafts", response_model=AssetDraftOut)
def create_draft(
    payload: AssetDraftCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail={"code": "empty_content", "message": "Content is required"})

    title = (payload.title or "").strip()
    source_type = payload.source_type or "manual"
    source_platform = (payload.source_platform or "").strip()
    source_url = (payload.source_url or "").strip()

    return _create_asset_item_from_raw(
        db=db,
        raw_text=content,
        raw_title=title,
        raw_source_type=source_type,
        raw_source_platform=source_platform,
        raw_source_url=source_url,
        raw_metadata={"entrypoint": "assets_draft"},
        user_id=actor.actor_id,
    )


@router.get("/drafts", response_model=list[AssetDraftOut])
def list_drafts(
    status: Optional[str] = Query("pending"),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    mapped_status = "pending_review" if status in {"pending", "pending_review"} else status
    return list_asset_items(status=mapped_status, db=db, actor=actor)


@router.put("/drafts/{draft_id}", response_model=AssetDraftOut)
def update_draft(
    draft_id: str,
    payload: AssetDraftUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    return update_asset_item(draft_id, PersonalAssetItemUpdate(**payload.model_dump(exclude_unset=True)), db, actor)


@router.post("/drafts/{draft_id}/confirm", response_model=AssetConfirmResponse)
def confirm_draft(
    draft_id: str,
    payload: AssetConfirmRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    return confirm_asset_item(draft_id, payload, db, actor)


@router.post("/personal_asset_units", response_model=PersonalAssetUnitOut)
def create_personal_asset_unit(
    payload: PersonalAssetUnitCreate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    asset_ids = list(dict.fromkeys(payload.asset_ids))
    assets = (
        db.query(PersonalAssetItem)
        .filter(
            PersonalAssetItem.user_id == actor.actor_id,
            PersonalAssetItem.status == "confirmed",
            PersonalAssetItem.id.in_(asset_ids),
        )
        .all()
    )
    found_ids = {asset.id for asset in assets}
    missing = [asset_id for asset_id in asset_ids if asset_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"code": "asset_not_found", "message": "Some assets were not found", "asset_ids": missing},
        )

    parsed = _ai_synthesize_knowledge(
        assets,
        title=payload.title or "",
        instruction=payload.instruction or "",
    )
    data = _normalize_personal_asset_unit(
        assets,
        parsed,
        title=payload.title or "",
        instruction=payload.instruction or "",
    )
    unit = PersonalAssetUnit(
        user_id=actor.actor_id,
        source_asset_ids=asset_ids,
        status="pending_review",
        **data,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


@router.get("/personal_asset_units", response_model=list[PersonalAssetUnitOut])
def list_personal_asset_units(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    query = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.user_id == actor.actor_id)
    if status:
        query = query.filter(PersonalAssetUnit.status == status)
    return query.order_by(PersonalAssetUnit.updated_at.desc()).all()


@router.get("/personal_asset_units/{unit_id}", response_model=PersonalAssetUnitOut)
def get_personal_asset_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    unit = db.query(PersonalAssetUnit).filter(
        PersonalAssetUnit.id == unit_id,
        PersonalAssetUnit.user_id == actor.actor_id,
    ).first()
    if not unit:
        raise HTTPException(status_code=404, detail={"code": "personal_asset_unit_not_found", "message": "Personal asset unit not found"})
    return unit


@router.put("/personal_asset_units/{unit_id}", response_model=PersonalAssetUnitOut)
def update_personal_asset_unit(
    unit_id: str,
    payload: PersonalAssetUnitUpdate,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == unit_id, PersonalAssetUnit.user_id == actor.actor_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail={"code": "personal_asset_unit_not_found", "message": "Personal asset unit not found"})
    if unit.status not in {"pending", "pending_review", "confirmed"}:
        raise HTTPException(status_code=409, detail={"code": "personal_asset_unit_closed", "message": "Personal asset unit is already closed"})
    was_confirmed = unit.status == "confirmed"
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if key == "tags":
            value = _clean_tags(value)
        elif key == "outline":
            value = _clean_dict_list(value)
        setattr(unit, key, value)
    if not was_confirmed:
        unit.status = "pending_review"
    unit.edited_at = local_now()
    if was_confirmed:
        try:
            db.flush()
            sync_personal_asset_unit_to_kb(
                db,
                unit,
                tenant_id=actor.tenant_id,
                owner_user_id=actor.actor_id,
            )
        except Exception as exc:
            log.exception("Failed to sync edited personal asset unit to personal inbox", extra={"unit_id": unit.id})
            raise HTTPException(
                status_code=500,
                detail={"code": "personal_asset_unit_sync_failed", "message": "Failed to sync personal asset unit to personal inbox"},
            ) from exc
    else:
        db.commit()
    db.refresh(unit)
    return unit


@router.post("/personal_asset_units/{unit_id}/confirm", response_model=PersonalAssetUnitConfirmResponse)
def confirm_personal_asset_unit(
    unit_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    unit = db.query(PersonalAssetUnit).filter(PersonalAssetUnit.id == unit_id, PersonalAssetUnit.user_id == actor.actor_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail={"code": "personal_asset_unit_not_found", "message": "Personal asset unit not found"})
    if unit.status not in {"pending", "pending_review"}:
        raise HTTPException(status_code=409, detail={"code": "personal_asset_unit_closed", "message": "Personal asset unit is already closed"})

    unit.status = "confirmed"
    unit.confirmed_at = local_now()
    try:
        db.flush()
        sync_personal_asset_unit_to_kb(
            db,
            unit,
            tenant_id=actor.tenant_id,
            owner_user_id=actor.actor_id,
        )
    except Exception as exc:
        log.exception("Failed to sync confirmed personal asset unit to personal inbox", extra={"unit_id": unit.id})
        raise HTTPException(
            status_code=500,
            detail={"code": "personal_asset_unit_sync_failed", "message": "Failed to sync personal asset unit to personal inbox"},
        ) from exc
    db.refresh(unit)
    try:
        _schedule_asset_unit_entity_graph_ingestion(unit.id, actor.actor_id)
    except Exception:
        log.exception("Failed to schedule personal asset unit entity graph ingestion", extra={"unit_id": unit.id})
    return PersonalAssetUnitConfirmResponse(
        unit=unit,
        pku_count=0,
        canonical_count=0,
        governance_link_count=0,
        pku_relation_count=0,
    )


@router.get("", response_model=list[PersonalAssetOut])
def list_assets(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    return (
        db.query(PersonalAssetItem)
        .filter(PersonalAssetItem.user_id == actor.actor_id, PersonalAssetItem.status == "confirmed")
        .order_by(PersonalAssetItem.updated_at.desc())
        .all()
    )


@router.get("/search", response_model=list[AssetSearchResult])
def search_assets(
    q: str = Query(""),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    q_norm = q.strip()
    query = db.query(PersonalAssetItem).filter(PersonalAssetItem.user_id == actor.actor_id, PersonalAssetItem.status == "confirmed")
    if q_norm:
        like = f"%{q_norm}%"
        query = query.filter(
            or_(
                PersonalAssetItem.title.like(like),
                PersonalAssetItem.summary.like(like),
                PersonalAssetItem.rewritten_content.like(like),
                PersonalAssetItem.body.like(like),
                PersonalAssetItem.raw_text.like(like),
                PersonalAssetItem.keyword_index_text.like(like),
                PersonalAssetItem.category.like(like),
                PersonalAssetItem.source_platform.like(like),
            )
        )
    assets = query.order_by(PersonalAssetItem.importance.desc(), PersonalAssetItem.updated_at.desc()).limit(limit).all()
    return [_item_result(asset, 1.0 if q_norm else float(asset.importance or 0.5)) for asset in assets]


@router.get("/overview", response_model=AssetOverviewOut)
def overview_assets(
    q: str = Query(""),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor_context),
):
    results = search_assets(q=q, limit=limit, db=db, actor=actor)
    category_counts = Counter(item.category or "未分类" for item in results)
    tag_counts: Counter[str] = Counter()
    for item in results:
        tag_counts.update(item.tags or [])
    categories = [{"name": name, "count": count} for name, count in category_counts.most_common(8)]
    tags = [{"name": name, "count": count} for name, count in tag_counts.most_common(12)]
    if results:
        leading = "、".join(item["name"] for item in categories[:4])
        summary = f"共找到 {len(results)} 条已确认知识资产，主要集中在：{leading}。"
    else:
        summary = "未找到匹配的已确认知识资产。"
    return AssetOverviewOut(
        summary=summary,
        categories=categories,
        tags=tags,
        representative_assets=results[:8],
    )
