# EntityExtractor 设计方案 + Prompt Schema + 最小可行 LLM 补充抽取草案

> 日期：2026-07-02
> 目标：在不破坏现有规则抽取高精度 front-matter 能力的前提下，引入一个可控、可回退、可评测的 LLM 补充实体抽取层，提升正文 / 中文 / 弱结构文本上的实体覆盖率。

---

## 一、设计目标

当前 `backend/app/services/entity_extraction.py` 的规则抽取有三大优点：

1. **高精度**：对论文 front matter（标题 / 作者 / 机构 / 邮箱）非常强
2. **低成本**：无额外模型推理成本，运行快
3. **幂等**：落库逻辑稳定，适合大规模 backfill

但它也有明确上限：

- 主要识别 front matter，**正文覆盖不足**
- `person` 目前基本只支持英文 Title-Case 姓名
- `organization` / `paper` 在弱结构文本里仍有误识别或漏召回
- 关系类型只有 `authored` / `affiliated_with`

因此目标不是“用 LLM 替换规则”，而是：

> **把现有规则抽取保留为高精度第一层，再加一个 LLM 补充层，专门处理规则看不准、规则抽不到、或需要跨句理解的情况。**

---

## 二、推荐架构

```text
原始 chunk / asset text
    ↓
阶段 1：规则抽取（现有 entity_extraction.py）
    ├─ 高精度 entity candidates
    ├─ 高精度 relation candidates
    └─ 候选噪声过滤
    ↓
阶段 2：LLM 补充抽取（新 EntityExtractor）
    ├─ 只在需要时触发（条件触发）
    ├─ 输出结构化 JSON
    └─ 仅补 person / organization / paper / relation
    ↓
阶段 3：merge / alias 归并 / 去重
    ├─ 规则结果与 LLM 结果合并
    ├─ alias_map 归并
    └─ 置信度冲突处理
    ↓
阶段 4：落库
    ├─ KnowledgeEntity
    ├─ EntityAlias
    ├─ EntityMention
    └─ EntityRelation
```

### 关键原则

1. **规则优先**：front matter 不用 LLM 覆盖，LLM 只做补充
2. **按需触发**：不是所有 chunk 都跑 LLM，控制成本
3. **结构化输出**：LLM 只输出 JSON，不输出解释
4. **置信度分层**：规则和 LLM 的置信度体系分开设计
5. **幂等合并**：最终仍通过统一 `upsert` 落库，不新增第二套实体表

---

## 三、EntityExtractor 设计草案

建议新增一个独立服务：

```python
class EntityExtractor:
    """Hybrid entity extractor: rules first, LLM as fallback/augment."""

    VALID_ENTITY_TYPES = ["person", "organization", "paper", "email"]
    VALID_RELATION_TYPES = [
        "authored",
        "affiliated_with",
        "has_email",
        "co_author",
        "mentions",
        "cites",
    ]

    def extract_from_text(
        self,
        text: str,
        source_kind: str,
        item_id: str = "",
        chunk_id: str = "",
        user_id: str = "default-user",
        session=None,
        use_llm: bool = True,
    ) -> EntityExtractionResult:
        ...
```

### 建议的数据结构

```python
@dataclass
class EntityExtractionResult:
    entities: list[dict]
    relations: list[dict]
    success: bool
    used_rules: bool
    used_llm: bool
    error: str | None = None
```

### 推荐的内部方法

```python
def _extract_with_rules(self, text: str, source_kind: str) -> list[EntityCandidate]:
    ...  # 直接复用现有 extract_entity_candidates_from_text


def _should_invoke_llm(self, text: str, rule_candidates: list[EntityCandidate], source_kind: str) -> bool:
    ...


def _extract_with_llm(self, text: str, source_kind: str) -> tuple[list[dict], list[dict]]:
    ...


def _merge_candidates(self, rule_candidates, llm_entities, llm_relations):
    ...


def _write_to_db(self, db, merged_entities, merged_relations, ...):
    ...
```

---

## 四、LLM 什么时候触发（最小可行策略）

LLM 不能全量跑，否则：
- 成本高
- backfill 过慢
- 结果波动大

建议只在这些情况触发：

### 触发条件 A：规则没有抽到 person / organization
适用于：
- 正文型 chunk
- 中文材料
- 混合自然语言笔记

```python
if not any(c.entity_type in {"person", "organization"} for c in rule_entities):
    return True
```

### 触发条件 B：文本更像正文，不像 front matter
例如：
- 行数很多
- 没有明确作者行
- 没有邮箱
- 没有机构关键词，但有明显名字候选

### 触发条件 C：source_kind 是 `personal_asset_item` / `personal_asset_unit`
资产类正文更自由，规则 NER 覆盖不足，LLM 更有价值。

### 触发条件 D：文本包含中文人名候选
例如连续 2-4 个中文字符，且上下文像人/机构描述。

### 不触发的情况
- 经典论文 front matter
- 规则已经抽到了高质量作者/机构/邮箱组合
- 文本明显是代码块 / yaml / config 噪声

---

## 五、Prompt Schema 设计

建议完全参考你给的 `ConceptExtractor` 思路：

### 5.1 System Prompt

```text
You are an entity extraction specialist.

Extract ONLY high-confidence entities and relations from the given text.

Rules:
1. Output ONLY valid JSON.
2. Keep JSON field names and enum values in English.
3. Entity names, aliases, and relation evidence spans must stay in the original language of the text.
4. Do not guess unsupported entities.
5. Prefer precision over recall.
6. If the text does not clearly support an entity or relation, omit it.
```

### 5.2 User Prompt 模板（建议文件名：`extract-entities`）

```text
Source kind: {{ SourceKind }}
Language hint: {{ Language }}

Text:
{{ ChunkContent }}

Extract entities and relations from the text.

Allowed entity types:
- person
- organization
- paper
- email

Allowed relation types:
- authored
- affiliated_with
- has_email
- co_author
- mentions
- cites

Return JSON with this exact schema:

{
  "entities": [
    {
      "type": "person|organization|paper|email",
      "name": "string",
      "aliases": ["string"],
      "confidence": 0.0,
      "evidence_span": "string",
      "reason": "short string"
    }
  ],
  "relations": [
    {
      "from": "string",
      "type": "authored|affiliated_with|has_email|co_author|mentions|cites",
      "to": "string",
      "confidence": 0.0,
      "evidence_span": "string",
      "reason": "short string"
    }
  ]
}

Constraints:
- Only output entities directly supported by the text.
- If multiple aliases refer to the same entity, keep one canonical name and list the others in aliases.
- For people, prefer real names over titles such as "Senior Member" or "Corresponding Author".
- For organizations, avoid copying entire sentences; return only the organization span.
- For papers, return short title-like spans only.
- If nothing reliable can be extracted, return {"entities": [], "relations": []}.
```

---

## 六、最小可行 JSON schema

### entities

```json
{
  "type": "person",
  "name": "Yanchao Tan",
  "aliases": ["Tan Yanchao", "谭彦超"],
  "confidence": 0.92,
  "evidence_span": "Shide Du, Zihan Fang, Yanchao Tan, Changwei Wang",
  "reason": "author line"
}
```

### relations

```json
{
  "from": "Yanchao Tan",
  "type": "affiliated_with",
  "to": "Fuzhou University",
  "confidence": 0.88,
  "evidence_span": "College of Computer and Data Science, Fuzhou University",
  "reason": "author affiliation line"
}
```

### 为什么需要 `reason`
不一定要落库，但非常适合：
- debug
- badcase 复盘
- 后续人工审查

---

## 七、最小可行实现草案

下面是和你现有 `entity_extraction.py` 兼容的最小可行实现草案。注意：这是**接口级草案**，不是直接可运行成品，因为你后端当前没有统一的 `LLMClient` 封装。

```python
import json
from dataclasses import dataclass
from typing import Optional

from backend.app.services.entity_extraction import extract_entity_candidates_from_text
from backend.app.services.entity_resolution import alias_keys_for_surface, normalize_entity_key


@dataclass
class EntityExtractionResult:
    entities: list[dict]
    relations: list[dict]
    success: bool
    used_rules: bool
    used_llm: bool
    error: Optional[str] = None


class EntityExtractor:
    VALID_ENTITY_TYPES = ["person", "organization", "paper", "email"]
    VALID_RELATION_TYPES = [
        "authored",
        "affiliated_with",
        "has_email",
        "co_author",
        "mentions",
        "cites",
    ]

    def __init__(self, prompt_renderer, llm_client=None):
        self.prompt_renderer = prompt_renderer
        self.client = llm_client

    def extract_from_text(self, text: str, source_kind: str) -> EntityExtractionResult:
        rule_candidates = extract_entity_candidates_from_text(text, source_kind=source_kind)
        rule_entities = [c for c in rule_candidates if c.kind == "entity"]
        rule_relations = [c for c in rule_candidates if c.kind == "relation"]

        if not self._should_invoke_llm(text, rule_entities, source_kind):
            return EntityExtractionResult(
                entities=[self._rule_entity_to_dict(c) for c in rule_entities],
                relations=[self._rule_relation_to_dict(c) for c in rule_relations],
                success=True,
                used_rules=True,
                used_llm=False,
            )

        if self.client is None:
            return EntityExtractionResult(
                entities=[self._rule_entity_to_dict(c) for c in rule_entities],
                relations=[self._rule_relation_to_dict(c) for c in rule_relations],
                success=True,
                used_rules=True,
                used_llm=False,
            )

        try:
            llm_entities, llm_relations = self._extract_with_llm(text, source_kind)
            merged_entities, merged_relations = self._merge(rule_entities, rule_relations, llm_entities, llm_relations)
            return EntityExtractionResult(
                entities=merged_entities,
                relations=merged_relations,
                success=True,
                used_rules=True,
                used_llm=True,
            )
        except Exception as exc:
            return EntityExtractionResult(
                entities=[self._rule_entity_to_dict(c) for c in rule_entities],
                relations=[self._rule_relation_to_dict(c) for c in rule_relations],
                success=False,
                used_rules=True,
                used_llm=True,
                error=str(exc),
            )

    def _should_invoke_llm(self, text: str, rule_entities: list, source_kind: str) -> bool:
        if source_kind in {"personal_asset_item", "personal_asset_unit"}:
            return True
        if not any(c.entity_type in {"person", "organization"} for c in rule_entities):
            return True
        if any("\u4e00" <= ch <= "\u9fff" for ch in text):
            return True
        return False

    def _extract_with_llm(self, text: str, source_kind: str) -> tuple[list[dict], list[dict]]:
        prompt = self.prompt_renderer.render(
            "extract-entities",
            SourceKind=source_kind,
            ChunkContent=text,
            Language="zh-CN",
        )
        messages = [
            {"role": "system", "content": "You are an entity extraction specialist. Output ONLY JSON."},
            {"role": "user", "content": prompt},
        ]
        raw = self.client.chat(messages)
        data = json.loads(raw)  # 实际建议配 json_repair
        return data.get("entities", []), data.get("relations", [])
```

---

## 八、merge 规则建议

这部分要借鉴你给的 `ConceptExtractor._merge_concepts()` 思想。

### Entity merge

按 `(type, normalized_key)` 合并：
- `Yanchao Tan`
- `Tan Yanchao`
- `谭彦超`

最终保留一个 canonical name，并维护：
- `aliases`
- `confidence = max(rule, llm)`
- `evidence_span` 可多条保留或只保留最高分

### Relation merge

按 `(from, type, to)` 去重：
- 相同关系只保留一次
- `confidence` 取最大值
- `evidence_span` 可合并或保留最高分

### 规则 vs LLM 冲突

建议优先级：
1. **email**：规则优先
2. **front matter person / organization / paper**：规则优先
3. **正文中的 person / organization / paper**：LLM 可补充
4. **如果 LLM 提取的 entity 被规则 stop-list 明确禁止**，直接丢弃

---

## 九、落库建议

不要新建第二套实体表。继续复用现有：
- `KnowledgeEntity`
- `EntityAlias`
- `EntityMention`
- `EntityRelation`

推荐做法：
- `extract_and_settle_entities()` 保持为唯一落库入口
- LLM 只输出中间候选
- merge 完的结果统一转换成 `EntityCandidate` 再复用现有 `_upsert_*`

也就是说，改造后最好还是：

```python
extract_and_settle_entities(...)
    -> rule candidates
    -> llm candidates (optional)
    -> merge
    -> _upsert_entity / _upsert_alias / _upsert_mention / _upsert_relation
```

这样对 Neo4j 投影层无侵入。

---

## 十、实施优先级建议

### Phase 1（最小可行）
- 新增 `EntityExtractor` 类
- 保留现有规则抽取
- 仅在规则弱场景触发 LLM
- 支持 JSON schema 输出
- 仅补 `person` / `organization`

### Phase 2
- 支持中文人名 / 中文机构
- 支持 `has_email` / `co_author`
- 引入 `json_repair`
- 做 `_merge_entities()`

### Phase 3
- item 级 / 多 chunk 融合
- 更强 alias resolution
- 引入实体专项评测集 v2（person / org / alias）

---

## 十一、最值得立刻做的版本

如果你要一个最值得立刻落地的 MVP，我建议是：

1. **保留现有规则抽取不动**
2. **只新增 LLM 补充 `person` / `organization`**
3. **只在以下条件触发 LLM**：
   - source_kind 是 asset
   - 文本含中文
   - 规则未抽到人名或机构
4. **只新增 2 类关系**：
   - `co_author`
   - `has_email`
5. **继续复用现有 MySQL + Neo4j 投影链路**

这是性价比最高、风险最低的路线。

---

## 十二、一句话结论

> 最合理的优化方式不是把 `entity_extraction.py` 替换成全 LLM，而是把它升级成“规则高精度第一层 + LLM 结构化补充第二层 + 统一 merge / 落库”的混合 EntityExtractor。
