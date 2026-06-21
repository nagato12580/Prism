from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.memory import MemoryEntry
from ..schemas.memory import MemoryEntryOut

router = APIRouter(prefix="/memories", tags=["memories"])
DEFAULT_USER_ID = "default-user"


@router.get("", response_model=list[MemoryEntryOut])
def list_memories(
    memory_type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(MemoryEntry).filter(MemoryEntry.user_id == DEFAULT_USER_ID)
    if memory_type:
        query = query.filter(MemoryEntry.memory_type == memory_type)
    return query.order_by(MemoryEntry.importance.desc(), MemoryEntry.updated_at.desc()).limit(limit).all()
