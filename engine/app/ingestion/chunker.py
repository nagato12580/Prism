# prism/engine/app/ingestion/chunker.py
"""语义分块：按句子边界切分，支持 overlap。"""
import re

# 中文句号、问号、感叹号 + 英文句号
SENTENCE_END = re.compile(r"[。！？!?.\n]+")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """将文本切分为不超过 chunk_size 字符的块，相邻块有 overlap 字符重叠。"""
    if not text or not text.strip():
        return []

    # 按句子边界切分
    sentences = SENTENCE_END.split(text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current = ""

    for sentence in sentences:
        # 单句本身超长，硬切
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), chunk_size):
                chunks.append(sentence[i:i + chunk_size])
            continue

        if len(current) + len(sentence) + 1 <= chunk_size:
            current = current + "。" + sentence if current else sentence
        else:
            chunks.append(current)
            # overlap：取当前块末尾 overlap 字符作为下一块开头
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:] + "。" + sentence
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks
