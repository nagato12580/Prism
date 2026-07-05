# EntityExtractor MVP 改造实施文档（交给 Claude Code 执行）

> 日期：2026-07-02
> 目标读者：Claude Code / 后续接手 agent / 开发者
> 目标：在不破坏现有高精度规则实体抽取的前提下，引入一个可控的 **Hybrid EntityExtractor**（规则优先 + 条件触发的 LLM 补充抽取），先完成 MVP 骨架，支持后续持续扩展。

---

## 一、背景

当前实体抽取逻辑集中在：

- `backend/app/services/entity_extraction.py`

现状特点：
- 优势：
  - 对论文 front matter（标题、作者、机构、邮箱）精度较高
  - 幂等落库逻辑稳定
  - 已接入 CKP/PKU 图桥接与 `entity_graph_search`
- 局限：
  - 几乎只覆盖 front matter 风格文本
  - 正文、中文、弱结构笔记的实体覆盖不足
  - 实体类型过少，主要是 `person / organization / email / paper`
  - 关系类型很少，仅 `authored / affiliated_with`

本次不是要推翻规则抽取，而是要把它升级为：

```text
规则抽取（高精度）
    +
LLM 补充抽取（高召回，仅在必要时触发）
    -> merge / 去重 / alias resolution
    -> 仍然复用现有 MySQL 落库与 Neo4j 投影链路
```

---

## 二、实施目标（MVP 范围）

本次 Claude Code 执行的范围 **只做 MVP**，不做大规模全面重构。

### 本次必须完成

1. 新增一个 `EntityExtractor` 骨架服务
2. 保留现有规则抽取逻辑不变，作为第一层
3. 加入一个 **LLM 补充抽取接口层**（即使先用 stub / disabled fallback，也要把骨架和 schema 接好）
4. 支持结构化 JSON prompt schema
5. 支持最小 merge 逻辑
6. 支持“是否触发 LLM”的判定逻辑
7. 保持与现有 `extract_and_settle_entities()` / 图投影兼容
8. 增加相应测试
9. 文档化当前 MVP 行为边界

### 本次不要做

1. 不要重写 Neo4j 投影逻辑
2. 不要删除 `entity_extraction.py` 现有规则逻辑
3. 不要一次性扩展所有实体类型到 20+ 个
4. 不要一开始就强制全量 backfill 依赖真实 LLM 成功
5. 不要引入复杂的新数据库表

---

## 三、建议产物

### 代码新增/改动文件

#### 1. 新增服务文件
建议新增：

- `backend/app/services/entity_extractor.py`

职责：
- 统一编排规则抽取 + LLM 补充抽取 + merge + 落库

#### 2. 新增 prompt 模板
建议新增：

- `backend/app/prompts/templates/extract_entities.jinja2`

若当前 backend prompt 体系更适合 Python builder，也可新增：
- `backend/app/prompts/entity_extraction.py`

二选一或同时保留均可，但要和现有 `renderer.py` 兼容。

#### 3. 兼容入口改动
建议在现有：

- `backend/app/services/entity_extraction.py`

中保留 `extract_and_settle_entities()` 作为统一入口，但内部可以逐步委托给新服务。

#### 4. 测试文件
建议新增或扩展：

- `backend/tests/test_entity_extractor.py`
- 以及必要时更新：
  - `backend/tests/test_entity_extraction.py`
  - `backend/tests/test_graph_projection.py`
  - `engine/tests/test_entity_graph_search_tool.py`

---

## 四、MVP 设计要求

## 4.1 EntityExtractor 类接口

建议最小接口如下：

```python
@dataclass
class EntityExtractionResult:
    entities: list[dict]
    relations: list[dict]
    success: bool
    used_rules: bool
    used_llm: bool
    error: str | None = None


class EntityExtractor:
    VALID_ENTITY_TYPES = [
        "person",
        "organization",
        "paper",
        "email",
    ]

    VALID_RELATION_TYPES = [
        "authored",
        "affiliated_with",
        "has_email",
        "co_author",
        "mentions",
    ]

    def extract_from_text(...):
        ...
```

### 必须满足
- 规则结果仍然可单独工作
- 即使 LLM client 不存在，也不能把现有功能搞坏
- 返回结果必须结构化，可被测试直接断言

---

## 4.2 LLM 触发策略（MVP）

本次只做最小触发策略，避免成本过高。

建议实现 `_should_invoke_llm()`，规则如下：

### 触发 LLM 的情况

1. `source_kind in {"personal_asset_item", "personal_asset_unit"}`
2. 规则没有抽到 `person` 或 `organization`
3. 文本中存在中文，且规则抽取不足
4. 文本不像 front matter（例如没有作者行、没有邮箱、没有明显机构行）

### 不触发 LLM 的情况

1. 典型论文 front matter
2. 已经抽到高质量 `paper + authors + org + email`
3. 明显代码 / yaml / config 噪声文本

---

## 4.3 Prompt Schema

### System Prompt 目标

约束 LLM：
- 只输出 JSON
- 不输出 Markdown
- 不猜测
- 精度优先
- 只用允许的实体类型和关系类型

### User Prompt 目标

输入：
- `SourceKind`
- `Language`
- `ChunkContent`

输出 schema：

```json
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
      "type": "authored|affiliated_with|has_email|co_author|mentions",
      "to": "string",
      "confidence": 0.0,
      "evidence_span": "string",
      "reason": "short string"
    }
  ]
}
```

### 本次注意
- 先只要求 LLM 支持 `person / organization / paper / email`
- 不要在 MVP 阶段一次加入 model/framework/protocol 等太多类型

---

## 4.4 Merge 逻辑（MVP）

建议实现 `_merge_candidates()` 或同等功能。

### 实体合并 key

```python
(entity_type, normalized_key)
```

### 关系合并 key

```python
(from, type, to)
```

### 合并优先级

1. 规则抽取优先于 LLM 抽取
2. email 以规则结果为准
3. 规则 stop-list 明确禁止的人名/机构，LLM 结果也不能强行通过
4. aliases 合并进同一 canonical entity
5. confidence 取更高值，或保留规则优先的值

---

## 4.5 落库策略（必须兼容现有表）

不要新建第二套实体表。

继续复用：
- `KnowledgeEntity`
- `EntityAlias`
- `EntityMention`
- `EntityRelation`

建议保留：
- `extract_and_settle_entities()` 作为外部统一入口

实现方式可以是：

```python
def extract_and_settle_entities(...):
    extractor = EntityExtractor(...)
    result = extractor.extract_from_text(...)
    ...  # 统一调用现有 upsert 逻辑
```

或者：
- `EntityExtractor` 内部直接复用 `_upsert_entity / _upsert_aliases / _upsert_mention / _upsert_relation`

关键要求：
- 不破坏现有幂等性
- 不破坏现有 graph projection 依赖

---

## 五、测试要求

本次必须新增/覆盖以下测试：

### 5.1 新增 `EntityExtractor` 骨架测试

至少包括：

1. **规则优先**
   - 规则已能抽到高质量实体时，不触发 LLM 或 LLM 不覆盖规则结果

2. **LLM 触发条件**
   - 正文 / 中文 / 资产类文本会触发
   - front matter 不触发

3. **LLM 缺失时安全降级**
   - `llm_client is None` 时仍返回规则结果，不抛异常

4. **LLM JSON parse 失败时安全降级**
   - fallback 到规则结果

5. **merge 行为**
   - aliases 合并
   - 规则与 LLM 冲突时规则优先

### 5.2 现有回归必须不退

至少重跑：

```powershell
python -m pytest backend/tests/test_entity_extraction.py -q --no-header
python -m pytest backend/tests/test_graph_projection.py backend/tests/test_graph_sync.py engine/tests/test_entity_graph_search_tool.py -q --no-header
```

如果 `test_entity_extraction.py` 全量在本环境过慢，则至少确保：
- 新增测试通过
- 当前关键定向测试通过
- 图相关 37/37 继续通过

---

## 六、评测要求

本次 MVP 不强制要求完整提升所有离线指标，但必须做最小验证。

### 如果改动影响实体抽取结果
必须执行：

```powershell
python -m backend.scripts.backfill_entity_graph
python -m evaluation.build_entity_graph_eval --limit 25
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains graph_entity_ckp traditional
```

### 验收最低要求

- `entity_graph_v1` query 数不明显下降
- `graph_entity_ckp expanded hit@10` 不低于当前 95% 左右水平
- 不引入明显新的噪声 person/org 实体

---

## 七、建议实施顺序（Claude Code 执行顺序）

### Step 1
新增：
- `backend/app/services/entity_extractor.py`

先只放：
- dataclass
- 类骨架
- `_should_invoke_llm`
- `_extract_with_rules`（直接调现有规则）
- `_extract_with_llm`（先留最小接口）
- `_merge_candidates`

### Step 2
新增 prompt 模板：
- `backend/app/prompts/templates/extract_entities.jinja2`

如果当前 backend 没有统一 LLM client，则先把 prompt/schema 落地，不强绑真实调用。

### Step 3
把 `extract_and_settle_entities()` 接到新骨架上：
- 先保证规则路径不变
- LLM 路径可 disabled / optional

### Step 4
补测试

### Step 5
如果实现了真实 LLM 路径，再跑一次实体专项评测

---

## 八、不要做的事（很重要）

Claude Code 在本次执行时不要：

1. 不要删除现有 `entity_extraction.py` 的规则函数
2. 不要同时扩展 20+ 实体类型
3. 不要引入与现有表完全平行的新实体存储结构
4. 不要改动 Neo4j schema
5. 不要把所有文本都强制走 LLM
6. 不要让 LLM 失败影响当前规则链路可用性

---

## 九、完成定义（Definition of Done）

本次 Claude Code 执行完成后，应满足：

1. 已有一个可读、可测试的 `EntityExtractor` MVP 骨架
2. 已有正式的实体抽取 prompt schema
3. 现有规则抽取能力完全保留
4. LLM 路径至少在接口层存在，并具备安全降级逻辑
5. 新增测试通过
6. 图桥接相关测试不回归
7. 文档中明确记录：
   - 当前 MVP 只做了什么
   - 哪些能力仍是 TODO

---

## 十、推荐交付物清单

本次最好产出：

- `backend/app/services/entity_extractor.py`
- `backend/app/prompts/templates/extract_entities.jinja2`
- 必要的 prompt helper / schema helper
- `backend/tests/test_entity_extractor.py`
- 现有测试的最小更新
- 若有必要，一份简短的实现说明文档更新

---

## 十一、验收命令（建议 Claude Code 最后执行）

```powershell
python -m pytest backend/tests/test_entity_extractor.py -q --no-header
python -m pytest backend/tests/test_graph_projection.py backend/tests/test_graph_sync.py engine/tests/test_entity_graph_search_tool.py -q --no-header
```

如启用了真实 LLM 路径且改动了抽取结果，再执行：

```powershell
python -m backend.scripts.backfill_entity_graph
python -m evaluation.build_entity_graph_eval --limit 25
python -m engine.eval.compare_retrieval_chains \
  --dataset evaluation/datasets/entity_graph_v1.json \
  --chains graph_entity_ckp traditional
```

---

## 十二、一句话执行目标

> 请实现一个 **规则优先、LLM 补充、结构化 JSON 输出、可安全降级** 的 `EntityExtractor` MVP 骨架，并保证现有图桥接链路、Agent 工具链与实体专项评测不被破坏。
