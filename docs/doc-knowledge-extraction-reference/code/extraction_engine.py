"""
文档知识抽取引擎 — 从文档中提取结构化知识点的核心管线

三阶段管线:
  1. Extract: 文本切块 → LLM 提取概念+关系 → 同名去重 → 写入 doc_concepts
  2. Merge: 按 group 字段合并概念 → 创建 doc_knowledge_points + relations
  3. Write: LLM 生成描述 + Markdown 文章 → 向量化

支持断点续抽: 中断后重新分析自动检测已有数据，从断点继续。

============ 适配新项目指南 ============
1. 任务调度方式 — 当前使用 Queue + ThreadPoolExecutor，可替换为 Celery/ARQ
2. 数据库操作 — 当前直接使用 SQLAlchemy Session，需替换为新项目的 ORM
3. 文件解析 (Stage 0) — _extract_content 依赖 PyPDF2/python-docx 等解析库
4. 图片处理 (Stage 1.5) — 图片描述生成依赖视觉 LLM，非必需可跳过
5. 分块器 _chunk_text — section 边界识别正则需根据新项目的文档格式调整
6. LLM 调用 — _call_llm_with_system 依赖 httpx + OpenAI 兼容 API
7. 提示词加载 — _load_extraction_prompt 优先从 DB 加载后 fallback 到文件
8. 向量化 (Stage 4) — 依赖外部 Embedding API，非必需可跳过
"""
import os
import re
import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from collections import defaultdict

# ⚠️ 适配点：替换为新项目的数据库层
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ─── 并发配置 ──────────────────────────────────────────
# ⚠️ 适配点：根据 LLM API 限流策略调整
_DOC_MAX_CONCURRENCY = 5   # 文档级并发（同时分析几个文档）
_KN_MAX_CONCURRENCY = 3    # 知识点级并发（同时调用几次 LLM）

# ─── 提示词目录 ────────────────────────────────────────
# ⚠️ 适配点：替换为新项目的提示词存放路径
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'prompts')

# ⚠️ 适配点：映射提示词类型到文件名
_FILE_PROMPT_MAP = {
    '知识点抽取': 'extract_knowledge_points.txt',
    '知识点撰写': 'write_knowledge_point.txt',
}


def _load_prompt(filename: str) -> str:
    """从文件加载提示词模板"""
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _load_extraction_prompt(prompt_type_name: str) -> str:
    """
    优先从 DB 加载提示词，fallback 到文件。

    ⚠️ 适配点：替换为新项目的提示词加载机制
    """
    # 尝试从 DB 加载
    try:
        from backend.app.models.doc_engine_prompt_config import DocEnginePromptConfig
        from backend.app.database import SessionLocal
        with SessionLocal() as session:
            row = session.query(DocEnginePromptConfig).filter(
                DocEnginePromptConfig.prompt_type_name == prompt_type_name
            ).first()
            if row and row.prompt_content:
                return row.prompt_content
    except Exception:
        pass
    # Fallback 到文件
    filename = _FILE_PROMPT_MAP.get(prompt_type_name)
    if filename:
        return _load_prompt(filename)
    raise ValueError(f"Unknown extraction prompt: {prompt_type_name}")


# ─── 系统提示词 ────────────────────────────────────────

SYSTEM_PROMPT = (
    "你是一个专业的知识工程师和知识图谱专家，正在从文档中提取结构化知识点及其关系。"
    "所有知识点名称、描述、别名、分组名必须用中文撰写。JSON字段名和type枚举值保持英文。"
    "只输出原始JSON，不要输出思考过程、解释或markdown代码块。"
)


# ─── LLM 调用工具 ──────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """移除 Qwen 等模型的 <think>...</think> 标签内容"""
    last_end = text.rfind('</think')
    if last_end == -1:
        return text.strip()
    close_bracket = text.find('>', last_end)
    if close_bracket == -1:
        close_bracket = last_end + len('</think') - 1
    return text[close_bracket + 1:].strip()


def _repair_json(text: str) -> dict:
    """
    从 LLM 响应中提取并修复 JSON。
    处理 LLM 可能输出的 markdown 代码块、前后多余文本等。

    ⚠️ 适配点：如果新项目使用 OpenAI SDK 的 json_mode，可能不需要此函数
    """
    from json_repair import repair_json

    cleaned = text.strip()
    # 找到 JSON 的起止位置
    lines = cleaned.split('\n')
    json_lines = []
    found_json = False
    for line in lines:
        stripped = line.strip()
        if not found_json and (stripped.startswith('{') or stripped.startswith('[')):
            found_json = True
        if found_json:
            json_lines.append(line)
    if json_lines:
        cleaned = '\n'.join(json_lines)

    # 找到最后一个 } 或 ]
    json_end = max(cleaned.rfind('}'), cleaned.rfind(']'))
    if json_end != -1:
        cleaned = cleaned[:json_end + 1]

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return json.loads(repair_json(cleaned))


def _call_llm_with_system(system_prompt: str, user_prompt: str, llm_config: dict) -> str:
    """
    调用 LLM（OpenAI 兼容 API + 重试 + 指数退避）。

    ⚠️ 适配点：替换为新项目的 LLM 调用方式
    """
    import httpx

    url = llm_config.get('api_url', '').rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json'}
    api_key = llm_config.get('api_key', '')
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    model_name = llm_config.get('model_name', 'default')
    temperature = llm_config.get('temperature', 0.3)
    max_tokens = llm_config.get('max_tokens', 4096)
    timeout = llm_config.get('timeout', 120)
    max_retries = llm_config.get('max_retries', 3)

    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ],
        'temperature': temperature,
        'max_tokens': max_tokens,
        'stream': False,
    }

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=float(timeout), write=30.0, pool=10.0),
            ) as client:
                resp = client.post(url, json=payload, headers=headers)
                body = resp.json()
                choices = body.get('choices', [])
                if choices:
                    msg = choices[0].get('message', {})
                    content = (msg.get('content') or msg.get('reasoning') or '').strip()
                    return _strip_thinking(content)
                err_msg = body.get('error', {}).get('message', '') or body.get('message', 'no choices')
                last_exc = RuntimeError(f"LLM returned no choices: {err_msg}")
        except Exception as e:
            last_exc = e

        if attempt < max_retries:
            wait_time = 2 ** attempt
            logger.warning(f"LLM call failed (attempt {attempt}/{max_retries}), retrying in {wait_time}s: {last_exc}")
            time.sleep(wait_time)

    raise last_exc


# ========== Chunking (基于 kmc-wiki_python DocumentChunker) ==========
# ⚠️ 适配点：根据新项目的文档格式调整 section 边界正则

SECTION_PATTERNS = [
    re.compile(r'^#{1,3}\s+'),                                          # Markdown 标题
    re.compile(r'^\d+[\.\s]+\S'),                                       # 数字编号
    re.compile(r'^[A-Z]\d+\s*(发起|确认|审核|审批|知会)'),                # 流程节点
    re.compile(r'^（[一二三四五六七八九十]+）'),                            # 中文序号
    re.compile(r'^\d+[、\)\）]'),                                        # 数字顿号
    re.compile(r'审批要点[：:]'),
    re.compile(r'^备注[：:]'),
]

MAX_CHUNK_SIZE = 4000  # ⚠️ 适配点：根据 LLM 上下文窗口调整
OVERLAP_SIZE = 200     # ⚠️ 适配点：5% of chunk size
MIN_CHUNK_SIZE = 300   # ⚠️ 适配点：太小的 chunk 无意义


def _is_section_boundary(line: str) -> bool:
    """判断一行是否是 section 边界"""
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    return any(p.match(stripped) for p in SECTION_PATTERNS)


def _split_by_paragraphs(text: str) -> list[str]:
    """按空行切分长文本为段落组"""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ''
    for para in paragraphs:
        if not para.strip():
            continue
        if len(current) + len(para) + 2 > MAX_CHUNK_SIZE:
            if current:
                chunks.append(current)
            current = para
        else:
            current = (current + '\n\n' + para) if current else para
    if current:
        chunks.append(current)
    return chunks


def _chunk_text(text: str) -> list[str]:
    """
    文本分块器：
    1. 按 section 边界切分
    2. 超过 MAX_CHUNK_SIZE 的 section 按段落再切
    3. 相邻 chunk 加 OVERLAP_SIZE 字符重叠
    4. 短于 MIN_CHUNK_SIZE 的 chunk 合并到上一个
    """
    if not text or len(text) <= MAX_CHUNK_SIZE:
        return [text] if text else []

    # 1. 按 section 边界切
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

    # 2. 超长的 section 按段落再切
    chunks = []
    for sec in sections:
        if len(sec) <= MAX_CHUNK_SIZE:
            chunks.append(sec)
        else:
            chunks.extend(_split_by_paragraphs(sec))

    # 3. 添加重叠
    if OVERLAP_SIZE > 0 and len(chunks) > 1:
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                chunk = chunks[i - 1][-OVERLAP_SIZE:] + '\n' + chunk
            overlapped.append(chunk)
        chunks = overlapped

    # 4. 合并过小的 chunk
    merged = [chunks[0]] if chunks else []
    for chunk in chunks[1:]:
        if len(chunk) < MIN_CHUNK_SIZE and merged:
            merged[-1] = merged[-1] + '\n' + chunk
        else:
            merged.append(chunk)

    return [c for c in merged if c.strip()]


# ========== Stage 2: 概念提取 ==========================================

def _extract_knowledge_points_from_chunk(
    chunk_text: str, source_path: str, llm_config: dict
) -> tuple[list[dict], list[dict]]:
    """
    对单个文本 chunk 调用 LLM，提取概念和关系。

    Returns:
        (concepts: list[dict], relations: list[dict])

    ⚠️ 适配点：提示词模板需要根据新项目的领域重写
    """
    template = _load_extraction_prompt('知识点抽取')
    prompt = template.replace('{SourcePath}', source_path).replace('{ChunkContent}', chunk_text)

    response = _call_llm_with_system(SYSTEM_PROMPT, prompt, llm_config)
    try:
        data = _repair_json(response)
    except Exception:
        from ..utils.llm_client import extract_json_from_response
        data = extract_json_from_response(response)

    concepts = data.get('concepts', [])
    relations = data.get('relations', [])
    return concepts, relations


def _merge_concepts(all_concepts: list[dict]) -> tuple[list[dict], dict]:
    """
    同名概念去重 + 描述合并。

    规则：
    - 同名概念的 description 拼接（去重追加）
    - 同名概念的 aliases 收集合并
    - 保留首次出现的 group 和 category
    - 构建 alias_map（别名 → 规范名称）

    Returns:
        (deduped_concepts, alias_map)

    ⚠️ 适配点：如果同名概念的描述拼接不适合你的场景，可改为覆盖或保留最长
    """
    seen = {}
    alias_map = {}

    for c in all_concepts:
        name = c.get('name', '').strip()
        if not name:
            continue

        if name in seen:
            # 合并描述（追加不重复的部分）
            existing_desc = seen[name].get('description', '')
            new_desc = c.get('description', '')
            if new_desc and new_desc not in existing_desc:
                seen[name]['description'] = existing_desc + '; ' + new_desc if existing_desc else new_desc
            # 合并别名
            existing_aliases = seen[name].get('aliases', [])
            for a in c.get('aliases', []):
                if a not in existing_aliases:
                    existing_aliases.append(a)
                alias_map[a.strip()] = name
            seen[name]['aliases'] = existing_aliases
            # 保留首次出现的 group/category
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


# ========== Stage 3: 知识点合并 ========================================

def _merge_groups(concepts: list[dict]) -> list[dict]:
    """
    按 group 字段合并概念为知识点。

    规则：
    - 相同 group 的概念合并为一个知识点：
      title = group 名
      description = "子概念名：描述\n\n子概念名：描述..."
    - 无 group 的概念独立成知识点

    ⚠️ 适配点：合并策略（拼接 vs LLM 重新整理）可根据需要调整
    """
    groups = defaultdict(list)
    ungrouped = []
    for c in concepts:
        grp = c.get('group', '').strip()
        if grp:
            groups[grp].append(c)
        else:
            ungrouped.append(c)

    merged = []
    # 有 group 的：合并
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
        })

    # 无 group 的：独立
    merged.extend(ungrouped)
    return merged


# ========== Stage 3.5a: 描述生成 =====================================

def _gen_desc_worker(kp_title: str, kp_desc: str, kp_category: str, llm_config: dict) -> str | None:
    """
    为知识点生成 100-200 字的精炼描述。

    ⚠️ 适配点：提示词中的描述长度和风格要求可调整
    """
    desc_prompt = (
        f"请为以下知识点生成一段简洁、准确的描述（100-200字），概括其核心含义。\n\n"
        f"知识点名称：{kp_title}\n"
        f"分类：{kp_category}\n"
        f"原始概念描述（参考）：\n{kp_desc}\n\n"
        f"要求：\n"
        f"1. 用专业、简洁的语言概括该知识点的核心内容\n"
        f"2. 涵盖关键要素和适用范围\n"
        f"3. 不要使用列表格式，输出为一段完整的文字\n"
        f"4. 只输出描述文本，不要输出标题或其他内容"
    )
    try:
        return _call_llm_with_system(
            "你是一个专业的知识工程师。请为知识点生成简洁准确的描述。",
            desc_prompt, llm_config
        )
    except Exception as e:
        logger.warning(f"Description generation failed for '{kp_title}': {e}")
        return None


# ========== Stage 3.5b: 文章生成 =====================================

def _gen_article_worker(
    kp_title: str, kp_desc: str, kp_category: str,
    doc_tags: list, source_name: str, llm_config: dict,
    doc_images: list | None = None,
) -> tuple[str, list[dict]]:
    """
    为知识点生成结构化 Markdown 文章。

    文章结构:
      # 标题
      ## 概述
      ## 关键要点
      ## 适用场景
      ## 注意事项

    自动解析 LLM 输出的 doc_image:// 引用，记录关联图片。

    Returns:
        (article_markdown, referenced_images)

    ⚠️ 适配点：文章结构模板、图片引用机制可根据需要调整
    """
    template = _load_extraction_prompt('知识点撰写')

    # 构建图片上下文
    img_ctx = ''
    if doc_images:
        img_lines = [
            f'  - 图片ID={im["id"]}, 描述: {im["caption"]}'
            for im in doc_images if im.get('caption')
        ]
        if img_lines:
            img_ctx = '\n文档中包含以下图片（可根据语义相关性选择引用）：\n' + '\n'.join(img_lines)

    prompt = (
        template
        .replace('{Title}', kp_title)
        .replace('{Description}', kp_desc)
        .replace('{Category}', kp_category)
        .replace('{Tags}', ', '.join(doc_tags))
        .replace('{SourcePath}', source_name)
        .replace('{ImageContext}', img_ctx)
    )

    article = _call_llm_with_system(
        "你是一个专业的技术文档撰写专家。根据提供的知识点信息，撰写结构清晰的 Markdown 格式知识文章。只输出 Markdown 内容。",
        prompt, llm_config
    )

    # 解析图片引用
    referenced_images = []
    if doc_images and 'doc_image://' in article:
        referenced_ids = set(int(m) for m in re.findall(r'doc_image://(\d+)', article))
        referenced_images = [
            {"id": im["id"], "caption": im["caption"]}
            for im in doc_images if im["id"] in referenced_ids
        ]

    return article, referenced_images


# ========== 主管线 ===================================================

def _do_analyze(doc_id: int, db_session_factory, llm_config: dict, embed_config: dict | None = None):
    """
    文档分析主管线 — 三阶段架构（遵循 kmc-wiki 架构）：

    1. Extract: chunk → LLM extract concepts → dedup → store in doc_concepts
    2. Merge: group concepts by 'group' field → create doc_knowledge_points + relations
    3. Write: generate descriptions + Markdown articles + embeddings

    支持断点续抽。

    ⚠️ 适配点：整个函数直接操作具体 ORM 模型和数据库，
              新项目需要整体替换数据访问层。

    ⚠️ 适配点：当前实现是同步的，适合 ThreadPoolExecutor 后台执行。
              如需 asyncio，需要改造所有 DB 和 HTTP 调用。
    """
    db = db_session_factory()

    try:
        # ⚠️ 适配点：替换为新项目的文档模型
        record = db.query(DocumentFile).filter(DocumentFile.id == doc_id).first()
        if not record:
            return

        record.status = 'processing'
        record.analyze_progress_current = 0
        record.analyze_progress_total = 0
        db.commit()

        # ── 断点续抽检测 ──
        # ⚠️ 适配点：替换为新项目的模型查询
        existing_concepts = db.query(DocConcept).filter(DocConcept.doc_id == doc_id).all()
        existing_kps = db.query(KnowledgePoint).filter(
            KnowledgePoint.doc_id.like(f'%{doc_id}%')
        ).all()

        doc_concepts = []
        kp_records = []
        all_relations = []
        alias_map = {}

        if existing_kps:
            # 最远断点：知识点已存在 → 从描述/文章/向量化继续
            _log_analyze(db, doc_id, '断点续抽', f'检测到 {len(existing_kps)} 个已有知识点，跳过解析和提取')
            record.analyze_stage = '断点续抽：知识点已合并'
            db.commit()
        elif existing_concepts:
            # 中间断点：概念已提取 → 从合并继续
            _log_analyze(db, doc_id, '断点续抽', f'检测到 {len(existing_concepts)} 个已有概念，跳过解析和提取')
            record.analyze_stage = '断点续抽：概念已提取'
            db.commit()
            doc_concepts = existing_concepts
        else:
            # ── Stage 0: 文件解析 ──
            # ⚠️ 适配点：根据新项目的文件格式需求调整解析器
            record.analyze_stage = '读取解析文件'
            db.commit()

            if not record.storage_path or not os.path.isfile(record.storage_path):
                record.status = 'failed'
                record.analyze_stage = f'文件不存在'
                db.commit()
                return

            text, images = _extract_content(record.storage_path, record.file_password or '')

            if not text.strip():
                record.status = 'failed'
                record.analyze_stage = '解析失败：文件内容为空'
                db.commit()
                return

            _log_analyze(db, doc_id, '读取解析', f'文件解析完成，提取文本 {len(text)} 字符')

            # ── Stage 1.5: 图片语义识别（可选）──
            # ⚠️ 适配点：如果不需要图片处理，跳过此阶段
            if images and llm_config:
                record.analyze_stage = '图片语义识别'
                db.commit()
                text = _enhance_with_captions(text, images, llm_config)

            # ── Stage 2: 概念提取 ──
            record.analyze_stage = '知识点提取'
            db.commit()

            if not llm_config:
                record.status = 'failed'
                record.analyze_stage = '未配置大模型'
                db.commit()
                return

            # Excel 预切块
            is_xlsx = record.mime_type and 'spreadsheet' in record.mime_type
            if is_xlsx:
                chunks = [c.strip() for c in text.split('\n\n') if c.strip()]
            else:
                chunks = _chunk_text(text)

            total_chunks = len(chunks)
            all_concepts = []
            record.analyze_stage = '概念提取'
            record.analyze_progress_current = 0
            record.analyze_progress_total = total_chunks
            db.commit()
            _log_analyze(db, doc_id, '概念提取', f'文本切分为 {total_chunks} 个切片，开始并发提取')

            # ⚠️ 适配点：ThreadPoolExecutor 可替换为 asyncio.gather
            chunk_done = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                chunk_futures = {
                    executor.submit(
                        _extract_knowledge_points_from_chunk,
                        chunk, record.original_name, llm_config
                    ): i
                    for i, chunk in enumerate(chunks)
                }
                for future in as_completed(chunk_futures):
                    i = chunk_futures[future]
                    chunk_done += 1
                    try:
                        concepts, relations = future.result()
                        all_concepts.extend(concepts)
                        all_relations.extend(relations)
                        _log_analyze(db, doc_id, '概念提取',
                                     f'切片 {i+1}/{total_chunks}: {len(concepts)} 个概念',
                                     current=i+1, total=total_chunks)
                    except Exception as e:
                        _log_analyze(db, doc_id, '概念提取',
                                     f'切片 {i+1}/{total_chunks} 失败: {e}',
                                     status='warning')
                    record.analyze_progress_current = chunk_done
                    db.commit()

            if not all_concepts:
                record.status = 'failed'
                record.analyze_stage = '概念提取失败：所有切片均未返回有效结果'
                db.commit()
                return

            # 同名去重
            deduped, alias_map = _merge_concepts(all_concepts)
            _log_analyze(db, doc_id, '概念提取',
                         f'{len(all_concepts)} 原始概念 → {len(deduped)} 去重后概念')

            # 写入 doc_concepts 表
            # ⚠️ 适配点：替换为新项目的 ORM 写入方式
            for c in deduped:
                name = c.get('name', '').strip()
                if not name:
                    continue
                concept_record = DocConcept(
                    doc_id=doc_id,
                    title=name,
                    type=c.get('type', 'concept'),
                    description=c.get('description', ''),
                    aliases=','.join(c.get('aliases', [])),
                    group=c.get('group', ''),
                    category=c.get('category', ''),
                )
                db.add(concept_record)
            db.commit()

            doc_concepts = db.query(DocConcept).filter(DocConcept.doc_id == doc_id).all()

        # ── Stage 3: 知识点合并 ──
        if not kp_records:
            record.analyze_stage = '知识点合并'
            db.commit()

            # 按 group 合并
            grouped = _merge_groups_from_records(doc_concepts)
            _log_analyze(db, doc_id, '知识点合并',
                         f'{len(doc_concepts)} 个概念 → {len(grouped)} 个知识点')

            doc_tags = []
            name_to_kp = {}
            for entry_data in grouped:
                name = entry_data['name']
                kp_record = KnowledgePoint(
                    doc_id=str(doc_id),
                    title=name,
                    description=entry_data['description'],
                    category=entry_data['category'],
                    tags=','.join(doc_tags),
                    aliases=','.join(entry_data['aliases']),
                    group=entry_data['group'],
                    status='整理中',
                )
                db.add(kp_record)
                kp_records.append((kp_record, entry_data))
                name_to_kp[name] = kp_record
                for a in entry_data['aliases']:
                    alias_map[a.strip()] = name
                for sub_name in entry_data.get('sub_concept_names', []):
                    alias_map[sub_name] = name
            db.flush()

            # 解析关系（概念名 → 知识点名映射）
            for rel in all_relations:
                from_name = alias_map.get(rel['from'], rel['from'])
                to_name = alias_map.get(rel['to'], rel['to'])
                from_kp = name_to_kp.get(from_name)
                to_kp = name_to_kp.get(to_name)
                if from_kp and to_kp:
                    db.add(KnowledgeRelation(
                        from_kp_id=from_kp.id,
                        to_kp_id=to_kp.id,
                        type=rel.get('type', ''),
                        confidence=rel.get('confidence', 1.0),
                    ))
            db.flush()

        # ── 检查哪些 KP 还需要处理（断点续抽）──
        kps_need_desc = [(kp, data) for kp, data in kp_records if not (kp.description or '').strip()]
        kps_need_article = [(kp, data) for kp, data in kp_records if not (kp.content or '').strip()]
        kps_need_embed = [(kp, data) for kp, data in kp_records if not (kp.embedding or '').strip()]

        # ── Stage 3.5a: 描述生成 ──
        if kps_need_desc:
            record.analyze_stage = '描述生成'
            record.analyze_progress_total = len(kps_need_desc)
            db.commit()
            _log_analyze(db, doc_id, '描述生成', f'开始为 {len(kps_need_desc)} 个知识点并发生成描述')

            desc_ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(
                        _gen_desc_worker, kp.title, kp.description or data.get('description', ''),
                        kp.category or data.get('category', ''), llm_config
                    ): kp
                    for kp, data in kps_need_desc
                }
                for future in as_completed(futures):
                    kp = futures[future]
                    try:
                        new_desc = future.result()
                        if new_desc:
                            kp.description = new_desc
                            desc_ok += 1
                    except Exception as e:
                        _log_analyze(db, doc_id, '描述生成', f'知识点「{kp.title}」描述生成失败: {e}', status='warning')
                    record.analyze_progress_current = desc_ok
                    db.commit()
            _log_analyze(db, doc_id, '描述生成', f'描述生成完成: {desc_ok}/{len(kps_need_desc)}')

        # ── Stage 3.5b: 文章生成 ──
        if kps_need_article:
            record.analyze_stage = '文章生成'
            record.analyze_progress_total = len(kps_need_article)
            db.commit()
            _log_analyze(db, doc_id, '文章生成', f'开始为 {len(kps_need_article)} 个知识点并发生成文章')

            doc_img_records = db.query(DocImage).filter(DocImage.doc_id == doc_id).all()
            doc_images_list = [{"id": im.id, "caption": im.caption or ''} for im in doc_img_records]

            article_ok = 0
            with ThreadPoolExecutor(max_workers=_KN_MAX_CONCURRENCY) as executor:
                futures = {
                    executor.submit(
                        _gen_article_worker,
                        kp.title, kp.description or data.get('description', ''),
                        kp.category or data.get('category', ''),
                        doc_tags, record.original_name, llm_config, doc_images_list,
                    ): kp
                    for kp, data in kps_need_article
                }
                pending = set(futures.keys())
                while pending:
                    done, pending = wait(pending, timeout=3, return_when=FIRST_COMPLETED)
                    for future in done:
                        kp = futures[future]
                        try:
                            article, ref_images = future.result()
                            kp.content = article
                            kp.status = '已发布'
                            if ref_images:
                                kp.images = json.dumps(ref_images, ensure_ascii=False)
                            article_ok += 1
                            _log_analyze(db, doc_id, '文章生成', f'知识点「{kp.title}」文章生成成功')
                        except Exception as e:
                            _log_analyze(db, doc_id, '文章生成', f'知识点「{kp.title}」文章生成失败: {e}', status='warning')
                        record.analyze_progress_current = article_ok
                        db.commit()
            _log_analyze(db, doc_id, '文章生成', f'文章生成完成: {article_ok}/{len(kps_need_article)}')

        # ── Stage 4: 向量化 ──
        # ⚠️ 适配点：如果使用独立向量数据库（Milvus/Pinecone），替换此阶段
        if kps_need_embed and embed_config:
            record.analyze_stage = '向量化'
            db.commit()
            _log_analyze(db, doc_id, '向量化', f'开始批量向量化 {len(kps_need_embed)} 个知识点')

            texts = []
            kp_list = []
            for kp, _ in kps_need_embed:
                content_excerpt = (kp.content or '')[:500]
                text = f"{kp.title}\n{kp.description or ''}\n{content_excerpt}"
                texts.append(text)
                kp_list.append(kp)

            embed_ok = 0
            try:
                vectors = _get_embeddings(texts, embed_config)
                if vectors and len(vectors) == len(texts):
                    for kp, vec in zip(kp_list, vectors):
                        if vec:
                            kp.embedding = json.dumps(vec)
                            embed_ok += 1
                    db.flush()
            except Exception as e:
                logger.warning(f"Embedding batch failed: {e}")
            _log_analyze(db, doc_id, '向量化', f'向量化完成: {embed_ok}/{len(kps_need_embed)}')

        # ── 完成 ──
        record.status = 'completed'
        record.analyze_stage = '分析完成'
        record.analyze_progress_current = record.analyze_progress_total
        db.commit()
        _log_analyze(db, doc_id, '分析完成', f'共产生 {len(kp_records)} 个知识点')

    except Exception as e:
        logger.exception(f"Document analysis failed for doc_id={doc_id}")
        try:
            record.status = 'failed'
            record.analyze_stage = f'异常: {str(e)[:200]}'
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _log_analyze(db, doc_id: int, stage: str, message: str, status: str = 'info', current: int = 0, total: int = 0):
    """记录分析日志"""
    log = DocAnalyzeLog(doc_id=doc_id, stage=stage, message=message,
                        status=status, progress_current=current, progress_total=total)
    db.add(log)
    db.commit()


def _merge_groups_from_records(concept_records) -> list[dict]:
    """
    从 DocConcept ORM 记录按 group 合并。
    等同 _merge_groups 但输入是 ORM 对象列表。
    """
    groups = defaultdict(list)
    ungrouped = []
    for c in concept_records:
        if c.group:
            groups[c.group].append(c)
        else:
            ungrouped.append(c)

    merged = []
    for group_name, members in groups.items():
        parts = []
        all_aliases = []
        sub_names = []
        for m in members:
            if m.description:
                parts.append(f"{m.title}：{m.description}")
            if m.aliases:
                all_aliases.extend(a.strip() for a in m.aliases.split(',') if a.strip())
            sub_names.append(m.title)
        merged.append({
            'name': group_name,
            'description': '\n\n'.join(parts),
            'category': members[0].category if members else '',
            'aliases': list(dict.fromkeys(all_aliases)),
            'group': group_name,
            'type': members[0].type if members else 'concept',
            'sub_concept_names': sub_names,
        })

    for c in ungrouped:
        aliases = [a.strip() for a in c.aliases.split(',') if a.strip()] if c.aliases else []
        merged.append({
            'name': c.title,
            'description': c.description or '',
            'category': c.category or '',
            'aliases': aliases,
            'group': '',
            'type': c.type,
            'sub_concept_names': [c.title],
        })

    return merged


# ═══════════════════════════════════════════════════════════════════
# 以下函数为占位符，需要新项目自行实现
# ═══════════════════════════════════════════════════════════════════

def _extract_content(file_path: str, password: str = '') -> tuple[str, list]:
    """
    文件解析：根据扩展名选择解析器提取文本和图片。

    ⚠️ 适配点：根据新项目的文件格式需求实现具体的解析器
    支持格式: PDF, DOCX, XLSX, PPTX
    返回: (text, images_paths)
    """
    raise NotImplementedError("需要根据新项目的文件格式需求实现")


def _enhance_with_captions(text: str, images: list, llm_config: dict) -> str:
    """
    图片语义识别：调用视觉 LLM 为每张图片生成描述，更新文本中的 [图片N] 占位符。

    ⚠️ 适配点：如果不需要图片处理，返回原文本即可
    """
    raise NotImplementedError("需要根据新项目的图片处理需求实现")


def _get_embeddings(texts: list[str], embed_config: dict) -> list[list[float]] | None:
    """
    批量调用 Embedding API 获取文本向量。

    ⚠️ 适配点：根据新项目的 embedding 方案实现
    """
    raise NotImplementedError("需要根据新项目的 embedding 方案实现")


# ⚠️ 适配点：替换为新项目的 ORM 模型导入
# 以下是占位符，需要新项目替换为实际模型
class DocumentFile:
    pass

class DocConcept:
    pass

class KnowledgePoint:
    pass

class KnowledgeRelation:
    pass

class DocAnalyzeLog:
    pass

class DocImage:
    pass
