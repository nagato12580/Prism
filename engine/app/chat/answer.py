# prism/engine/app/chat/answer.py
"""基础 RAG 问答：检索 → 拼接上下文 → LLM 流式生成。Phase 2 升级为 Agentic。"""
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings
from ..retrieval.hybrid import hybrid_search
from ..llm.client import chat_stream

_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

SYSTEM_PROMPT = """你是 Prism 个人知识助手。基于用户的个人知识库回答问题。
规则：
1. 只使用提供的参考资料回答，不要编造。
2. 如果资料不足，明确说明并建议用户补充知识。
3. 回答用中文，条理清晰。"""


def _load_chunks(chunk_ids: list[str]) -> dict[str, str]:
    """加载 chunk 文本，返回 {chunk_id: text}。"""
    from backend.app.models.knowledge_item import KnowledgeChunk
    db = _Session()
    try:
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.id.in_(chunk_ids)).all()
        return {c.id: c.chunk_text for c in chunks}
    finally:
        db.close()


def answer_stream(query: str, history: list[dict] = None):
    """基础 RAG 问答流式生成。yield NDJSON 行。

    输出格式：
    - {"type": "sources", "data": [{chunk_id, item_id, score}]}
    - {"type": "token", "data": "token文本"}
    - {"type": "done"}
    """
    history = history or []
    try:
        # 1. 检索
        results = hybrid_search(query, top_k=8)
        chunk_map = _load_chunks([r["chunk_id"] for r in results]) if results else {}

        # 2. 发送来源
        yield json.dumps({"type": "sources", "data": results}, ensure_ascii=False) + "\n"

        # 3. 构建上下文
        context_parts = []
        for i, r in enumerate(results):
            text = chunk_map.get(r["chunk_id"], "")
            if text:
                context_parts.append(f"[{i + 1}] {text}")
        context = "\n\n".join(context_parts) if context_parts else "（无相关资料）"

        # 4. LLM 流式生成
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": f"参考资料：\n{context}"},
        ] + history + [{"role": "user", "content": query}]

        for token in chat_stream(messages):
            yield json.dumps({"type": "token", "data": token}, ensure_ascii=False) + "\n"

        yield json.dumps({"type": "done"}) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False) + "\n"
