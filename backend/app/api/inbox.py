# prism/backend/app/api/inbox.py
import json
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from openai import OpenAI
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..models.inbox import InboxRawItem, InboxReviewItem, MemoryEntry, NotebookNote
from ..models.knowledge_item import KnowledgeItem
from ..schemas.inbox import (
    InboxCreateResponse,
    InboxItemCreate,
    InboxRawItemOut,
    InboxReviewOut,
    MemoryEntryOut,
    NotebookNoteOut,
    ReviewSettleResponse,
    ReviewUpdate,
)

router = APIRouter(prefix="/inbox", tags=["inbox"])
DEFAULT_USER_ID = "default-user"

KINDS = {"knowledge", "opinion", "resource", "task", "memory", "idea", "chat"}
ACTIONS = {"make_wiki", "save_note", "save_resource", "remember", "review_later", "ignore"}


def _clean_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value[:8]:
        tag = str(item).strip().strip("#")
        if tag and tag not in tags:
            tags.append(tag[:32])
    return tags


def _short_title(text: str, fallback: str = "未命名收件") -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return fallback
    return text[:40] + ("..." if len(text) > 40 else "")


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _rule_classify(item: InboxRawItem) -> dict:
    text = f"{item.title}\n{item.content}\n{item.source_url}".lower()
    has_url = bool(item.source_url) or "http://" in text or "https://" in text
    is_video = any(key in text for key in ["bilibili", "youtube", "视频", "抖音", "小红书"])
    if has_url or is_video:
        kind = "resource"
        action = "save_resource"
        category = "稍后看"
    elif any(key in text for key in ["我希望", "我想", "我不想", "我更喜欢", "偏好", "习惯"]):
        kind = "memory"
        action = "remember"
        category = "个人偏好"
    elif any(key in text for key in ["todo", "待办", "提醒", "稍后", "要做"]):
        kind = "task"
        action = "review_later"
        category = "待处理"
    elif any(key in text for key in ["观点", "认为", "看法", "评论", "启发", "有意思"]):
        kind = "opinion"
        action = "save_note"
        category = "观点"
    elif len(item.content) > 180 or any(key in text for key in ["原理", "方法", "技术", "知识", "教程", "系统"]):
        kind = "knowledge"
        action = "make_wiki"
        category = "知识点"
    else:
        kind = "idea"
        action = "save_note"
        category = "灵感"

    return {
        "kind": kind,
        "title": item.title or _short_title(item.content),
        "summary": _short_title(item.content, "暂无摘要"),
        "suggested_action": action,
        "category": category,
        "tags": [category],
        "rationale": "规则兜底分类：根据来源、关键词和文本长度判断。",
        "confidence": 0.55,
    }


def _llm_classify(item: InboxRawItem) -> dict | None:
    if not settings.LLM_API_BASE or not settings.LLM_API_KEY:
        return None
    client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    prompt = {
        "role": "user",
        "content": json.dumps(
            {
                "task": "把用户丢进 Prism Inbox 的材料分类，判断它该如何沉淀。只返回 JSON。",
                "allowed_kind": sorted(KINDS),
                "allowed_suggested_action": sorted(ACTIONS),
                "source": {
                    "title": item.title,
                    "content": item.content[:5000],
                    "source_type": item.source_type,
                    "source_url": item.source_url,
                    "source_platform": item.source_platform,
                },
                "json_shape": {
                    "kind": "knowledge/opinion/resource/task/memory/idea/chat",
                    "title": "短标题，不超过30字",
                    "summary": "一句话摘要",
                    "suggested_action": "make_wiki/save_note/save_resource/remember/review_later/ignore",
                    "category": "主题分类",
                    "tags": ["2-5个标签"],
                    "rationale": "为什么这样处理",
                    "confidence": 0.0,
                },
                "rules": [
                    "可稳定复用的知识点选 knowledge + make_wiki",
                    "观点、评论、灵感选 opinion/idea + save_note",
                    "视频、文章链接、资源推荐选 resource + save_resource",
                    "关于用户长期偏好、目标、约束的内容选 memory + remember",
                    "需要以后处理但还不是知识的内容选 task + review_later",
                ],
            },
            ensure_ascii=False,
        ),
    }
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是 Prism 的个人信息整理器。输出严格 JSON，不要 Markdown。"},
                prompt,
            ],
            temperature=0.2,
            max_tokens=700,
        )
        return _parse_json_object(resp.choices[0].message.content or "")
    except Exception:
        return None


def _normalize_classification(item: InboxRawItem, raw: dict | None) -> dict:
    data = raw if isinstance(raw, dict) else _rule_classify(item)
    fallback = _rule_classify(item)
    kind = str(data.get("kind") or fallback["kind"]).strip()
    action = str(data.get("suggested_action") or fallback["suggested_action"]).strip()
    if kind not in KINDS:
        kind = fallback["kind"]
    if action not in ACTIONS:
        action = fallback["suggested_action"]
    try:
        confidence = float(data.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        confidence = fallback["confidence"]
    return {
        "kind": kind,
        "title": _short_title(str(data.get("title") or fallback["title"])),
        "summary": str(data.get("summary") or fallback["summary"]).strip()[:1000],
        "suggested_action": action,
        "category": str(data.get("category") or fallback["category"]).strip()[:128],
        "tags": _clean_tags(data.get("tags")) or fallback["tags"],
        "rationale": str(data.get("rationale") or fallback["rationale"]).strip()[:1000],
        "confidence": max(0.0, min(1.0, confidence)),
    }


def _classify_to_review(item: InboxRawItem, db: Session) -> InboxReviewItem:
    data = _normalize_classification(item, _llm_classify(item))
    review = InboxReviewItem(
        raw_item_id=item.id,
        user_id=item.user_id,
        kind=data["kind"],
        title=data["title"],
        summary=data["summary"],
        suggested_action=data["suggested_action"],
        category=data["category"],
        tags=data["tags"],
        rationale=data["rationale"],
        confidence=data["confidence"],
    )
    item.status = "classified"
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def _get_review(review_id: str, db: Session) -> InboxReviewItem:
    review = (
        db.query(InboxReviewItem)
        .options(joinedload(InboxReviewItem.raw_item))
        .filter(InboxReviewItem.id == review_id, InboxReviewItem.user_id == DEFAULT_USER_ID)
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail={"code": "review_not_found", "message": "Review item not found"})
    return review


@router.post("/items", response_model=InboxCreateResponse)
def create_item(payload: InboxItemCreate, db: Session = Depends(get_db)):
    content = payload.content.strip()
    item = InboxRawItem(
        user_id=DEFAULT_USER_ID,
        title=(payload.title or "").strip()[:255],
        content=content,
        source_type=payload.source_type or "manual",
        source_url=(payload.source_url or "").strip(),
        source_platform=(payload.source_platform or "").strip(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    review = _classify_to_review(item, db) if payload.classify else None
    return InboxCreateResponse(item=item, review=review)


@router.get("/items", response_model=list[InboxRawItemOut])
def list_items(status: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(InboxRawItem).filter(InboxRawItem.user_id == DEFAULT_USER_ID)
    if status:
        query = query.filter(InboxRawItem.status == status)
    return query.order_by(InboxRawItem.created_at.desc()).all()


@router.post("/items/{item_id}/classify", response_model=InboxReviewOut)
def classify_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(InboxRawItem).filter(InboxRawItem.id == item_id, InboxRawItem.user_id == DEFAULT_USER_ID).first()
    if not item:
        raise HTTPException(status_code=404, detail={"code": "item_not_found", "message": "Inbox item not found"})
    return _classify_to_review(item, db)


@router.get("/reviews", response_model=list[InboxReviewOut])
def list_reviews(
    status: Optional[str] = Query("pending"),
    kind: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(InboxReviewItem)
        .options(joinedload(InboxReviewItem.raw_item))
        .filter(InboxReviewItem.user_id == DEFAULT_USER_ID)
    )
    if status:
        query = query.filter(InboxReviewItem.status == status)
    if kind:
        query = query.filter(InboxReviewItem.kind == kind)
    return query.order_by(InboxReviewItem.created_at.desc()).all()


@router.put("/reviews/{review_id}", response_model=InboxReviewOut)
def update_review(review_id: str, payload: ReviewUpdate, db: Session = Depends(get_db)):
    review = _get_review(review_id, db)
    if review.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "review_closed", "message": "Review item is already closed"})
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "tags" and value is not None:
            value = _clean_tags(value)
        if value is not None:
            setattr(review, key, value)
    db.commit()
    db.refresh(review)
    return review


@router.post("/reviews/{review_id}/reject", response_model=InboxReviewOut)
def reject_review(review_id: str, db: Session = Depends(get_db)):
    review = _get_review(review_id, db)
    review.status = "rejected"
    if review.raw_item:
        review.raw_item.status = "archived"
    db.commit()
    db.refresh(review)
    return review


@router.post("/reviews/{review_id}/approve", response_model=ReviewSettleResponse)
def approve_review(review_id: str, db: Session = Depends(get_db)):
    review = _get_review(review_id, db)
    if review.status != "pending":
        raise HTTPException(status_code=409, detail={"code": "review_closed", "message": "Review item is already closed"})

    raw = review.raw_item
    if not raw:
        raise HTTPException(status_code=404, detail={"code": "raw_item_missing", "message": "Raw item missing"})

    settled_type = "note"
    settled_ref_id = ""
    content = review.summary or raw.content

    if review.kind == "knowledge" or review.suggested_action == "make_wiki":
        item = KnowledgeItem(
            title=review.title or _short_title(raw.content, "Inbox 知识点"),
            content=raw.content,
            summary=review.summary,
            source_type="inbox",
            source_ref=raw.id,
            tags=review.tags or [],
            category=review.category or "Inbox",
            user_id=DEFAULT_USER_ID,
        )
        db.add(item)
        db.flush()
        settled_type = "knowledge"
        settled_ref_id = item.id
    elif review.kind == "memory" or review.suggested_action == "remember":
        memory = MemoryEntry(
            user_id=DEFAULT_USER_ID,
            title=review.title or "个人记忆",
            content=content,
            memory_type="preference",
            category=review.category or "个人",
            tags=review.tags or [],
            importance=max(0.6, float(review.confidence or 0.6)),
            source_raw_item_id=raw.id,
            source_review_id=review.id,
        )
        db.add(memory)
        db.flush()
        settled_type = "memory"
        settled_ref_id = memory.id
    else:
        note_type = "resource" if review.kind == "resource" else ("task" if review.kind == "task" else review.kind)
        note = NotebookNote(
            user_id=DEFAULT_USER_ID,
            title=review.title or _short_title(raw.content, "Inbox 笔记"),
            content=raw.content,
            note_type=note_type,
            category=review.category or "Inbox",
            tags=review.tags or [],
            source_raw_item_id=raw.id,
            source_review_id=review.id,
        )
        db.add(note)
        db.flush()
        settled_type = "note"
        settled_ref_id = note.id

    review.status = "approved"
    review.settled_type = settled_type
    review.settled_ref_id = settled_ref_id
    raw.status = "settled"
    db.commit()
    db.refresh(review)
    return ReviewSettleResponse(review=review, settled_type=settled_type, settled_ref_id=settled_ref_id)


@router.get("/notes", response_model=list[NotebookNoteOut])
def list_notes(db: Session = Depends(get_db)):
    return (
        db.query(NotebookNote)
        .filter(NotebookNote.user_id == DEFAULT_USER_ID)
        .order_by(NotebookNote.created_at.desc())
        .all()
    )


@router.get("/memories", response_model=list[MemoryEntryOut])
def list_memories(db: Session = Depends(get_db)):
    return (
        db.query(MemoryEntry)
        .filter(MemoryEntry.user_id == DEFAULT_USER_ID)
        .order_by(MemoryEntry.created_at.desc())
        .all()
    )
