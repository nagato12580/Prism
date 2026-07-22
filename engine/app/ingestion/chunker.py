# prism/engine/app/ingestion/chunker.py
"""Parent-child chunking with optional page marker preservation."""

from dataclasses import dataclass
import re

import tiktoken

from engine.app.config import settings


CHILD_CHUNK_TOKENS = 256
PARENT_CHUNK_TOKENS = 1024
CHILD_OVERLAP_RATIO = 0.1

_SENT_SEP = re.compile(r"(?<=[。！？.\!\?\n])")
_PAGE_MARKER = re.compile(r"\[\[PAGE:(\d+)\]\]")
_encoder = tiktoken.get_encoding("cl100k_base")


@dataclass
class TextChunk:
    content: str
    page_start: int | None = None
    page_end: int | None = None


class ParentChunk:
    """A parent chunk and its child chunks."""

    def __init__(
        self,
        content: str,
        page_start: int | None = None,
        page_end: int | None = None,
    ):
        self.content = content
        self.page_start = page_start
        self.page_end = page_end
        self.children: list[TextChunk] = []


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def _split_sentences(text: str) -> list[TextChunk]:
    current_page: int | None = None
    parts: list[TextChunk] = []
    cursor = 0

    for match in _PAGE_MARKER.finditer(text):
        segment = text[cursor : match.start()]
        parts.extend(_split_plain_segment(segment, current_page))
        current_page = int(match.group(1))
        cursor = match.end()

    parts.extend(_split_plain_segment(text[cursor:], current_page))
    return parts


def _split_plain_segment(text: str, page: int | None) -> list[TextChunk]:
    return [
        TextChunk(part.strip(), page, page)
        for part in _SENT_SEP.split(text)
        if part and part.strip()
    ]


def _join_chunks(chunks: list[TextChunk]) -> TextChunk:
    pages = [chunk.page_start for chunk in chunks if chunk.page_start is not None]
    return TextChunk(
        "".join(chunk.content for chunk in chunks),
        min(pages) if pages else None,
        max(pages) if pages else None,
    )


def _merge_to_chunks(
    sentences: list[TextChunk], target_tokens: int, overlap_ratio: float = 0.0
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    cur: list[TextChunk] = []
    cur_tokens = 0
    for sent in sentences:
        sent_tokens = count_tokens(sent.content)
        if sent_tokens >= target_tokens:
            if cur:
                chunks.append(_join_chunks(cur))
                cur, cur_tokens = [], 0
            chunks.append(sent)
            continue
        if cur_tokens + sent_tokens > target_tokens and cur:
            chunks.append(_join_chunks(cur))
            if overlap_ratio > 0:
                keep = max(1, int(len(cur) * overlap_ratio))
                cur = cur[-keep:]
                cur_tokens = sum(count_tokens(s.content) for s in cur)
            else:
                cur, cur_tokens = [], 0
        cur.append(sent)
        cur_tokens += sent_tokens
    if cur:
        chunks.append(_join_chunks(cur))
    return chunks


def chunk_parent_child(
    text: str,
    parent_tokens: int | None = None,
    child_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[ParentChunk]:
    """Split text into parent chunks and child chunks."""
    text = text.strip()
    if not text:
        return []
    sentences = _split_sentences(text)
    parent_content_chunks = _merge_to_chunks(
        sentences,
        parent_tokens if parent_tokens is not None else settings.PARENT_CHUNK_TOKENS,
    )
    result: list[ParentChunk] = []
    for pc in parent_content_chunks:
        parent = ParentChunk(pc.content, pc.page_start, pc.page_end)
        child_sents = _split_sentences(pc.content)
        parent.children = _merge_to_chunks(
            child_sents,
            child_tokens if child_tokens is not None else settings.CHILD_CHUNK_TOKENS,
            (overlap_tokens / child_tokens if overlap_tokens is not None and child_tokens and child_tokens > 0 else 0)
            if overlap_tokens is not None
            else settings.CHILD_OVERLAP_RATIO,
        )
        for child in parent.children:
            if child.page_start is None:
                child.page_start = parent.page_start
            if child.page_end is None:
                child.page_end = parent.page_end
        result.append(parent)
    return result


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Backward-compatible API: return all child chunk strings."""
    cleaned = text.strip().replace("[[PAGE:", "")
    cleaned = cleaned.replace("。", "")
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - max(overlap, 0)) if overlap > 0 else chunk_size
    while start < len(cleaned):
        chunks.append(cleaned[start : start + chunk_size])
        start += step
    return chunks
