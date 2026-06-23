# PKU Vector Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PKU 增加独立向量写入、历史 backfill、query-time PKU vector recall，并把它接入 `governed_evidence` 证据召回链路。

**Architecture:** 新增 `backend/app/services/pku_vectors.py`，复用 CKP 向量服务的 Milvus/OpenAI 模式但使用独立 collection `prism_pku`。PKU 创建后刷新向量，历史 PKU 通过 backfill 脚本补齐；查询时通过 `search_pku_vectors()` 命中 PKU，再回溯 CKP 并提升对应 evidence 排名。

**Tech Stack:** Python, SQLAlchemy, PyMilvus, OpenAI-compatible embeddings, pytest, existing Prism backend/engine modules.

---

### Task 1: PKU 向量服务

**Files:**
- Create: `backend/app/services/pku_vectors.py`
- Create: `backend/tests/test_pku_vectors.py`

- [ ] **Step 1: 写失败测试**

新增 `backend/tests/test_pku_vectors.py`，覆盖独立 collection、upsert、search filter：

```python
def test_pku_vectors_use_dedicated_collection(monkeypatch):
    from backend.app.services import pku_vectors

    created = {}

    class FakeUtility:
        @staticmethod
        def has_collection(name):
            created["has_collection_name"] = name
            return False

    class FakeCollection:
        def __init__(self, name, schema):
            created["collection_name"] = name
            created["schema"] = schema

        def create_index(self, field_name, index_params):
            created["index_field"] = field_name
            created["index_params"] = index_params

    monkeypatch.setattr(pku_vectors.connections, "connect", lambda **kwargs: None)
    monkeypatch.setattr(pku_vectors, "utility", FakeUtility)
    monkeypatch.setattr(pku_vectors, "Collection", FakeCollection)

    pku_vectors.ensure_pku_collection()

    assert created["has_collection_name"] == "prism_pku"
    assert created["collection_name"] == "prism_pku"
    assert created["index_params"]["metric_type"] == "COSINE"
```

```python
def test_upsert_pku_vector_flushes_collection(monkeypatch):
    from backend.app.models import PersonalKnowledgeUnit
    from backend.app.services import pku_vectors

    calls = []

    class FakeCollection:
        def insert(self, rows):
            calls.append(("insert", rows))

        def flush(self):
            calls.append(("flush", None))

    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(pku_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pku_vectors, "ensure_pku_collection", lambda: FakeCollection())

    pku = PersonalKnowledgeUnit(
        id="pku-1",
        user_id="user-1",
        source_kind="document_chunk",
        source_id="chunk-1",
        unit_type="claim",
        statement="Database table storage engine must use InnoDB.",
        normalized_statement="database table storage engine must use innodb",
        normalized_statement_hash="hash-1",
        evidence_span="storage engine must use InnoDB",
        keywords=["database", "innodb"],
        concepts=["storage engine"],
    )

    vector_ref = pku_vectors.upsert_pku_vector(pku)

    assert vector_ref.startswith("pku-")
    assert [call[0] for call in calls] == ["insert", "flush"]
    inserted_rows = calls[0][1]
    assert inserted_rows[2] == ["pku-1"]
    assert inserted_rows[3] == ["user-1"]
    assert inserted_rows[4] == ["claim"]
    assert inserted_rows[5] == ["document_chunk"]
    assert inserted_rows[6] == ["chunk-1"]
```

```python
def test_search_pku_vectors_filters_by_user_unit_type_and_source_kind(monkeypatch):
    from backend.app.services import pku_vectors

    captured = {}

    class FakeEntity:
        def __init__(self):
            self.data = {
                "pku_id": "pku-1",
                "user_id": "user-1",
                "unit_type": "claim",
                "source_kind": "document_chunk",
                "source_id": "chunk-1",
            }

        def get(self, key):
            return self.data[key]

    class FakeHit:
        score = 0.88
        entity = FakeEntity()

    class FakeCollection:
        def load(self):
            captured["loaded"] = True

        def search(self, **kwargs):
            captured["expr"] = kwargs["expr"]
            return [[FakeHit()]]

    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_BASE", "http://embedding.local/v1")
    monkeypatch.setattr(pku_vectors.settings, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(pku_vectors, "embed_text", lambda text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(pku_vectors, "ensure_pku_collection", lambda: FakeCollection())

    hits = pku_vectors.search_pku_vectors(
        text="database engine",
        user_id="user-1",
        unit_type="claim",
        source_kind="document_chunk",
        top_k=5,
    )

    assert 'user_id == "user-1"' in captured["expr"]
    assert 'unit_type == "claim"' in captured["expr"]
    assert 'source_kind == "document_chunk"' in captured["expr"]
    assert hits == [{
        "pku_id": "pku-1",
        "score": 0.88,
        "user_id": "user-1",
        "unit_type": "claim",
        "source_kind": "document_chunk",
        "source_id": "chunk-1",
    }]
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest backend\tests\test_pku_vectors.py -v
```

Expected: `ModuleNotFoundError` 或属性不存在。

- [ ] **Step 3: 实现 `pku_vectors.py`**

实现：

- `PKU_COLLECTION_NAME = "prism_pku"`
- `ensure_pku_collection()`
- `embed_text()`
- `_pku_vector_text(pku)`
- `upsert_pku_vector(pku)`
- `search_pku_vectors(...)`

实现结构参考 `backend/app/services/ckp_vectors.py`，字段包含 `pku_id/user_id/unit_type/source_kind/source_id`。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
python -m pytest backend\tests\test_pku_vectors.py -v
```

Expected: 3 passed.

### Task 2: PKU 创建后刷新向量

**Files:**
- Modify: `backend/app/services/knowledge_governance.py`
- Modify: `backend/tests/test_document_chunk_pku_extraction.py`
- Modify: `backend/tests/test_asset_unit_pku_extraction.py`

- [ ] **Step 1: 写失败测试**

在文档 PKU 测试中加入断言：创建 document PKU 后调用 `upsert_pku_vector` 并更新状态。

测试意图：

```python
monkeypatch.setattr(kg, "upsert_pku_vector", lambda pku: f"pku:{pku.id}")
...
assert pku.embedding_ref == f"pku:{pku.id}"
assert pku.embedding_model
assert pku.embedding_status == "done"
```

在 asset PKU 测试中加入同等断言。

- [ ] **Step 2: 运行目标测试确认失败**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py -k "pku" -v
```

Expected: 新增断言失败，因为还未刷新 PKU 向量。

- [ ] **Step 3: 实现 `_refresh_pku_vector` 并接入创建函数**

在 `knowledge_governance.py`：

```python
from backend.app.services.pku_vectors import upsert_pku_vector
```

新增：

```python
def _refresh_pku_vector(pku: PersonalKnowledgeUnit) -> None:
    try:
        embedding_ref = upsert_pku_vector(pku)
    except Exception:
        pku.embedding_status = "failed"
        return
    if embedding_ref:
        pku.embedding_ref = embedding_ref
        pku.embedding_model = settings.EMBEDDING_MODEL
        pku.embedding_status = "done"
    else:
        pku.embedding_status = "pending"
```

在新建 PKU 后 `db.flush()` 后调用 `_refresh_pku_vector(pku)`，但 existing PKU 直接返回时不重复刷新。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
python -m pytest backend\tests\test_document_chunk_pku_extraction.py backend\tests\test_asset_unit_pku_extraction.py -k "pku" -v
```

Expected: 目标测试通过。

### Task 3: 历史 PKU backfill 脚本

**Files:**
- Create: `backend/scripts/backfill_pku_vectors.py`
- Create or modify: `backend/scripts/__init__.py`
- Create: `backend/tests/test_backfill_pku_vectors.py`

- [ ] **Step 1: 写失败测试**

新增测试覆盖：

- 只处理 active PKU
- 默认跳过已 done 且有 embedding_ref 的 PKU
- 调用 `upsert_pku_vector`
- 输出统计对象或返回统计 dict

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest backend\tests\test_backfill_pku_vectors.py -v
```

Expected: 脚本不存在。

- [ ] **Step 3: 实现 backfill 脚本**

脚本支持：

```powershell
python -m backend.scripts.backfill_pku_vectors --user-id default-user --limit 500
```

参数：

- `--user-id`
- `--limit`
- `--force`
- `--batch-size`

返回/打印统计：

```text
scanned
updated
skipped
failed
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
python -m pytest backend\tests\test_backfill_pku_vectors.py -v
```

Expected: tests pass.

### Task 4: governed_evidence 接入 PKU 向量召回

**Files:**
- Modify: `engine/app/agent/tools/governed_knowledge.py`
- Modify: `engine/tests/test_governed_knowledge_search.py`

- [ ] **Step 1: 写失败测试**

新增测试：

```python
def test_governed_evidence_uses_pku_vector_hits_to_recall_ckp(monkeypatch):
    # CKP 文本不包含 query 词，PKU statement/evidence_span 包含 query 词。
    # monkeypatch search_ckp_vectors -> []
    # monkeypatch search_pku_vectors -> [{"pku_id": pku.id, "score": 0.91}]
    # 断言 _query_governed_evidence 返回该 CKP，并将该 PKU 的 source 排在前面。
```

新增降级测试：

```python
def test_governed_evidence_degrades_when_pku_vector_search_fails(monkeypatch):
    # monkeypatch search_pku_vectors raise RuntimeError
    # lexical/CKP 路径仍然可返回结果
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "pku_vector" -v
```

Expected: 失败，因为 engine 工具还没有导入/使用 `search_pku_vectors`。

- [ ] **Step 3: 实现 PKU vector recall 融合**

在 `governed_knowledge.py`：

1. 导入 `search_pku_vectors`。
2. 新增 `_safe_search_pku_vectors(query, limit)`。
3. 新增 `_pku_vector_ckp_candidates(db, pku_hits)`。
4. 扩展 `_fuse_ckp_candidates(...)` 支持 `pku_vector_hits`。
5. 扩展 `_score_pku_evidence(...)` 支持 `pku_vector_score`。
6. 在 `_build_evidence_bundle(..., evidence_mode=True)` 中对命中 PKU 加 boost。

建议权重：

```text
CKP vector weight: 0.45
CKP lexical weight: 0.30
PKU vector weight: 0.25
```

PKU evidence score 加：

```text
0.20 * pku_vector_score
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
python -m pytest engine\tests\test_governed_knowledge_search.py -k "governed_evidence" -v
```

Expected: governed evidence 相关测试通过。

### Task 5: 运行 backfill 和三链路测评

**Files:**
- Read/Write: database PKU embedding fields
- Create: `evaluation/runs/retrieval/<timestamp>_compare/`

- [ ] **Step 1: 运行相关测试**

Run:

```powershell
python -m pytest backend\tests\test_pku_vectors.py backend\tests\test_backfill_pku_vectors.py engine\tests\test_governed_knowledge_search.py engine\tests\test_compare_retrieval_chains.py -v
```

Expected: all pass.

- [ ] **Step 2: 编译检查**

Run:

```powershell
python -m py_compile backend\app\services\pku_vectors.py backend\scripts\backfill_pku_vectors.py engine\app\agent\tools\governed_knowledge.py
```

Expected: exit 0.

- [ ] **Step 3: backfill 历史 PKU**

Run:

```powershell
python -m backend.scripts.backfill_pku_vectors --user-id default-user --limit 1000
```

Expected: 输出 scanned/updated/skipped/failed。

- [ ] **Step 4: 重跑测评**

Run:

```powershell
python -m engine.eval.compare_retrieval_chains --dataset evaluation/datasets/formal_docs_v1.json --chains traditional governed governed_evidence --verbose
```

Expected: 新 run 写入 `evaluation/runs/retrieval/`。

### Task 6: 中文测评报告

**Files:**
- Create: `evaluation/runs/retrieval/<timestamp>_compare/pku_vector_retrieval_report.md`
- Modify: `evaluation/README.md`

- [ ] **Step 1: 写中文报告**

报告包含：

- 本阶段改造内容
- PKU 向量链路设计思想
- backfill 统计
- 三链路新指标
- 与上一轮 `governed_evidence` 指标对比
- 失败样本类型
- 下一步建议

- [ ] **Step 2: 更新 README**

在 `evaluation/README.md` 加最新 run 和报告路径。

- [ ] **Step 3: 最终汇报**

向用户汇报：

- 改了哪些文件
- 跑了哪些测试
- backfill 结果
- 测评结果
- 是否达到 Phase 2 目标
