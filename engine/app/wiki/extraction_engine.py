# prism/engine/app/wiki/extraction_engine.py
"""Wiki 文档知识抽取引擎 — 三阶段管线"""
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from ..config import settings
from ..llm.client import chat as llm_chat
from .prompts import (
    EXTRACT_CONCEPTS_PROMPT, DESC_GEN_PROMPT, WRITE_ARTICLE_PROMPT,
    EXTRACTION_SYSTEM_PROMPT, DESC_GEN_SYSTEM_PROMPT, ARTICLE_GEN_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# Engine 独立 DB session
_engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
_Session = sessionmaker(bind=_engine)

# 并发配置
_KN_MAX_CONCURRENCY = 3

# 分块参数
MAX_CHUNK_SIZE = 4000
OVERLAP_SIZE = 200
MIN_CHUNK_SIZE = 300

# Section 边界识别正则（中文文档适配）
SECTION_PATTERNS = [
    re.compile(r'^#{1,3}\s+'),
    re.compile(r'^\d+[\.\s]+\S'),
    re.compile(r'^（[一二三四五六七八九十]+）'),
    re.compile(r'^\d+[、\)\）]'),
    re.compile(r'^[第第]\s*\d+\s*[章节]'),
]


def _is_section_boundary(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    return any(p.match(stripped) for p in SECTION_PATTERNS)


def _chunk_text(text: str) -> list[str]:
    """Section-boundary-aware 文本分块。"""
    if not text or len(text) <= MAX_CHUNK_SIZE:
        return [text] if text else []

    # 按 section 边界切
    sections = []
    current = []
    for line in text.split('\n'):
        if _is_section_boundary(line) and current:
            sections.append('\n'.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append('\n'.join(current))

    # 超长 section 按段落再切
    chunks = []
    for sec in sections:
        if len(sec) <= MAX_CHUNK_SIZE:
            chunks.append(sec)
        else:
            paragraphs = re.split(r'\n\s*\n', sec)
            cur = ''
            for para in paragraphs:
                if not para.strip():
                    continue
                if len(cur) + len(para) + 2 > MAX_CHUNK_SIZE:
                    if cur:
                        chunks.append(cur)
                    cur = para
                else:
                    cur = (cur + '\n\n' + para) if cur else para
            if cur:
                chunks.append(cur)

    # 添加重叠
    if OVERLAP_SIZE > 0 and len(chunks) > 1:
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = chunks[i - 1][-OVERLAP_SIZE:] + '\n' + chunk
            overlapped.append(chunk)
        chunks = overlapped

    # 合并过小的 chunk
    merged = [chunks[0]] if chunks else []
    for chunk in chunks[1:]:
        if len(chunk) < MIN_CHUNK_SIZE and merged:
            merged[-1] = merged[-1] + '\n' + chunk
        else:
            merged.append(chunk)

    return [c for c in merged if c.strip()]


def _repair_json(text: str) -> dict:
    """从 LLM 响应中提取并修复 JSON。"""
    cleaned = text.strip()
    # 找到 JSON 起止
    lines = cleaned.split('\n')
    json_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if not found and (stripped.startswith('{') or stripped.startswith('[')):
            found = True
        if found:
            json_lines.append(line)
    if json_lines:
        cleaned = '\n'.join(json_lines)
    json_end = max(cleaned.rfind('}'), cleaned.rfind(']'))
    if json_end != -1:
        cleaned = cleaned[:json_end + 1]
    return json.loads(cleaned)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """调用 LLM（复用 engine LLM client）。"""
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]
    return llm_chat(messages)


# ── Stage 2: 概念提取 ───────────────────────────────────

def _extract_from_chunk(chunk_text: str, source_path: str) -> tuple[list, list]:
    """对单个 chunk 提取概念和关系。"""
    prompt = EXTRACT_CONCEPTS_PROMPT.replace('{SourcePath}', source_path).replace('{ChunkContent}', chunk_text)
    response = _call_llm(EXTRACTION_SYSTEM_PROMPT, prompt)
    try:
        data = _repair_json(response)
    except json.JSONDecodeError:
        logger.warning(f"JSON repair failed for chunk, raw response: {response[:200]}")
        return [], []
    return data.get('concepts', []), data.get('relations', [])


def _merge_concepts(all_concepts: list) -> tuple[list, dict]:
    """同名概念去重，描述拼接。"""
    seen = {}
    alias_map = {}
    for c in all_concepts:
        name = c.get('name', '').strip()
        if not name:
            continue
        if name in seen:
            existing_desc = seen[name].get('description', '')
            new_desc = c.get('description', '')
            if new_desc and new_desc not in existing_desc:
                seen[name]['description'] = existing_desc + '; ' + new_desc if existing_desc else new_desc
            existing_aliases = seen[name].get('aliases', [])
            for a in c.get('aliases', []):
                if a not in existing_aliases:
                    existing_aliases.append(a)
                alias_map[a.strip()] = name
            seen[name]['aliases'] = existing_aliases
            if c.get('group') and not seen[name].get('group'):
                seen[name]['group'] = c['group']
            if c.get('category') and not seen[name].get('category'):
                seen[name]['category'] = c['category']
        else:
            seen[name] = dict(c)
            alias_map[name] = name
            for a in c.get('aliases', []):
                alias_map[a.strip()] = name
    return list(seen.values()), alias_map


# ── Stage 3: 知识点合并 ─────────────────────────────────

def _merge_groups(concepts: list) -> list:
    """按 group 字段合并概念为知识点。"""
    groups = defaultdict(list)
    ungrouped = []
    for c in concepts:
        grp = c.get('group', '').strip()
        if grp:
            groups[grp].append(c)
        else:
            ungrouped.append(c)

    merged = []
    for group_name, members in groups.items():
        parts = []
        all_aliases = []
        for m in members:
            if m.get('description'):
                parts.append(f"{m.get('name', '')}：{m['description']}")
            all_aliases.extend(m.get('aliases', []))
        merged.append({
            'name': group_name,
            'description': '\n\n'.join(parts),
            'category': members[0].get('category', '') if members else '',
            'aliases': list(dict.fromkeys(all_aliases)),
            'group': group_name,
            'type': members[0].get('type', 'concept') if members else 'concept',
            'sub_concept_names': [m.get('name', '') for m in members],
        })

    for c in ungrouped:
        merged.append({
            'name': c.get('name', ''),
            'description': c.get('description', ''),
            'category': c.get('category', ''),
            'aliases': c.get('aliases', []),
            'group': '',
            'type': c.get('type', 'concept'),
            'sub_concept_names': [c.get('name', '')],
        })

    return merged


# ── Stage 3.5: 描述 + 文章生成 ──────────────────────────

def _gen_description(title: str, description: str, category: str) -> str | None:
    """生成 100-200 字精炼描述。"""
    prompt = DESC_GEN_PROMPT.replace('{Title}', title).replace('{Description}', description or '').replace('{Category}', category or '')
    try:
        return _call_llm(DESC_GEN_SYSTEM_PROMPT, prompt)
    except Exception as e:
        logger.warning(f"Description generation failed for '{title}': {e}")
        return None


def _gen_article(title: str, description: str, category: str, tags: str, source_name: str, doc_images: list | None = None) -> str:
    """生成结构化 Markdown 文章。"""
    img_ctx = ''
    if doc_images:
        img_lines = [f'  - 图片ID={im["id"]}, 描述: {im["caption"]}' for im in doc_images if im.get('caption')]
        if img_lines:
            img_ctx = '\n文档中包含以下图片（可根据语义相关性选择引用）：\n' + '\n'.join(img_lines)

    prompt = (
        WRITE_ARTICLE_PROMPT
        .replace('{Title}', title)
        .replace('{Description}', description or '')
        .replace('{Category}', category or '')
        .replace('{Tags}', tags or '')
        .replace('{SourcePath}', source_name)
        .replace('{ImageContext}', img_ctx)
    )
    return _call_llm(ARTICLE_GEN_SYSTEM_PROMPT, prompt)


# ── 日志辅助 ────────────────────────────────────────────

def _log(db: Session, doc_id: str, stage: str, message: str, status: str = 'info', current: int = 0, total: int = 0):
    from backend.app.models.wiki import WikiExtractionLog
    log = WikiExtractionLog(
        document_id=doc_id, stage=stage, message=message,
        status=status, progress_current=current, progress_total=total,
    )
    db.add(log)
    db.commit()


# ── 主管线 ─────────────────────────────────────────────

def run_extraction(doc_id: str, file_id: str):
    """执行完整的三阶段知识抽取管线。"""
    from backend.app.models.knowledge_item import KnowledgeFile
    from backend.app.models.wiki import (
        WikiDocument, WikiConcept, WikiKnowledgePoint, WikiKnowledgeRelation,
    )

    db = _Session()
    try:
        doc = db.query(WikiDocument).filter(WikiDocument.id == doc_id).first()
        kfile = db.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
        if not doc or not kfile:
            _log(db, doc_id, 'error', 'Document or file not found', 'error')
            return

        text = kfile.content_text or ''
        if not text.strip():
            doc.status = 'failed'
            doc.extract_stage = 'No content'
            _log(db, doc_id, 'error', 'File content is empty', 'error')
            db.commit()
            return

        source_name = kfile.original_filename or 'unknown'
        _log(db, doc_id, 'start', f'Starting extraction, {len(text)} chars', 'info')

        # ── 断点续抽检测 ──
        existing_concepts = db.query(WikiConcept).filter(WikiConcept.document_id == doc_id).all()
        existing_kps = db.query(WikiKnowledgePoint).filter(WikiKnowledgePoint.document_id == doc_id).all()

        all_concepts = []
        all_relations = []
        alias_map = {}

        if existing_kps:
            _log(db, doc_id, 'resume', f'Found {len(existing_kps)} existing KPs, skipping to article generation', 'info')
            doc.extract_stage = 'resume: KPs exist'
        elif existing_concepts:
            _log(db, doc_id, 'resume', f'Found {len(existing_concepts)} existing concepts, skipping to merge', 'info')
            doc.extract_stage = 'resume: concepts exist'
        else:
            # ── Stage 2: 概念提取 ──
            doc.extract_stage = 'Stage 2: concept extraction'
            doc.progress_current = 0
            db.commit()

            chunks = _chunk_text(text)
            total = len(chunks)
            doc.progress_total = total
            db.commit()
            _log(db, doc_id, 'Stage 2', f'Text split into {total} chunks', 'info')

            done = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(_extract_from_chunk, chunk, source_name): i
                    for i, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    i = futures[future]
                    done += 1
                    try:
                        concepts, relations = future.result()
                        all_concepts.extend(concepts)
                        all_relations.extend(relations)
                        _log(db, doc_id, 'Stage 2', f'Chunk {i+1}/{total}: {len(concepts)} concepts', 'info', current=done, total=total)
                    except Exception as e:
                        _log(db, doc_id, 'Stage 2', f'Chunk {i+1}/{total} failed: {e}', 'warning', current=done, total=total)
                    doc.progress_current = done
                    db.commit()

            if not all_concepts:
                doc.status = 'failed'
                doc.extract_stage = 'Stage 2 failed: no concepts'
                _log(db, doc_id, 'Stage 2', 'All chunks returned no results', 'error')
                db.commit()
                return

            # 去重
            deduped, alias_map = _merge_concepts(all_concepts)
            _log(db, doc_id, 'Stage 2', f'{len(all_concepts)} raw → {len(deduped)} deduped concepts', 'info')

            # 写入 wiki_concept
            for c in deduped:
                name = c.get('name', '').strip()
                if not name:
                    continue
                concept = WikiConcept(
                    document_id=doc_id, name=name,
                    type=c.get('type', 'concept'),
                    description=c.get('description', ''),
                    aliases=','.join(c.get('aliases', [])),
                    group_name=c.get('group', ''),
                    category=c.get('category', ''),
                )
                db.add(concept)
            db.commit()
            all_concepts = deduped

        # ── Stage 3: 知识点合并 ──
        if not existing_kps:
            doc.extract_stage = 'Stage 3: merge'
            db.commit()

            if existing_concepts:
                concepts_for_merge = []
                for c in existing_concepts:
                    concepts_for_merge.append({
                        'name': c.name, 'type': c.type, 'description': c.description or '',
                        'aliases': [a.strip() for a in c.aliases.split(',') if a.strip()] if c.aliases else [],
                        'group': c.group_name, 'category': c.category,
                    })
                grouped = _merge_groups(concepts_for_merge)
            else:
                grouped = _merge_groups(all_concepts)

            _log(db, doc_id, 'Stage 3', f'{len(grouped)} knowledge points created', 'info')

            name_to_kp = {}
            kp_records = []
            for entry in grouped:
                name = entry['name']
                kp = WikiKnowledgePoint(
                    document_id=doc_id, title=name,
                    description=entry['description'],
                    category=entry['category'],
                    tags='',
                    aliases=','.join(entry['aliases']),
                    group_name=entry['group'],
                    status='整理中',
                )
                db.add(kp)
                db.flush()
                kp_records.append(kp)
                name_to_kp[name] = kp
                for a in entry['aliases']:
                    alias_map[a.strip()] = name
                for sub_name in entry.get('sub_concept_names', []):
                    alias_map[sub_name] = name

            # 写入关系
            for rel in all_relations:
                from_name = alias_map.get(rel['from'], rel['from'])
                to_name = alias_map.get(rel['to'], rel['to'])
                from_kp = name_to_kp.get(from_name)
                to_kp = name_to_kp.get(to_name)
                if from_kp and to_kp:
                    db.add(WikiKnowledgeRelation(
                        from_point_id=from_kp.id, to_point_id=to_kp.id,
                        type=rel.get('type', ''), confidence=rel.get('confidence', 1.0),
                    ))
            db.commit()
            existing_kps = kp_records

        # ── Stage 3.5a: 描述生成 ──
        kps_need_desc = [kp for kp in existing_kps if not (kp.description or '').strip()]
        if kps_need_desc:
            doc.extract_stage = 'Stage 3.5a: description generation'
            doc.progress_total = len(kps_need_desc)
            db.commit()
            _log(db, doc_id, 'Stage 3.5a', f'Generating descriptions for {len(kps_need_desc)} KPs', 'info')

            ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(_gen_description, kp.title, kp.description or '', kp.category or ''): kp
                    for kp in kps_need_desc
                }
                for future in as_completed(futures):
                    kp = futures[future]
                    try:
                        new_desc = future.result()
                        if new_desc:
                            kp.description = new_desc
                            ok += 1
                    except Exception as e:
                        _log(db, doc_id, 'Stage 3.5a', f'Desc fail for "{kp.title}": {e}', 'warning')
                    doc.progress_current = ok
                    db.commit()
            _log(db, doc_id, 'Stage 3.5a', f'Descriptions: {ok}/{len(kps_need_desc)}', 'info')

        # ── Stage 3.5b: 文章生成 ──
        kps_need_article = [kp for kp in existing_kps if not (kp.content or '').strip()]
        if kps_need_article:
            doc.extract_stage = 'Stage 3.5b: article generation'
            doc.progress_total = len(kps_need_article)
            db.commit()
            _log(db, doc_id, 'Stage 3.5b', f'Generating articles for {len(kps_need_article)} KPs', 'info')

            ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(
                        _gen_article,
                        kp.title, kp.description or '', kp.category or '',
                        kp.tags or '', source_name, None,
                    ): kp
                    for kp in kps_need_article
                }
                for future in as_completed(futures):
                    kp = futures[future]
                    try:
                        article = future.result()
                        kp.content = article
                        kp.status = '已发布'
                        ok += 1
                        _log(db, doc_id, 'Stage 3.5b', f'Article done: "{kp.title}"', 'info')
                    except Exception as e:
                        _log(db, doc_id, 'Stage 3.5b', f'Article fail for "{kp.title}": {e}', 'warning')
                    doc.progress_current = ok
                    db.commit()
            _log(db, doc_id, 'Stage 3.5b', f'Articles: {ok}/{len(kps_need_article)}', 'info')

        # ── 完成 ──
        doc.status = 'completed'
        doc.extract_stage = 'done'
        doc.progress_current = doc.progress_total
        db.commit()
        _log(db, doc_id, 'done', f'Extraction complete: {len(existing_kps)} KPs', 'info')
        logger.info(f"Wiki extraction complete for doc_id={doc_id}")

    except Exception as e:
        logger.exception(f"Wiki extraction failed doc_id={doc_id}")
        try:
            doc = db.query(WikiDocument).filter(WikiDocument.id == doc_id).first()
            if doc:
                doc.status = 'failed'
                doc.extract_stage = f'error: {str(e)[:200]}'
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
