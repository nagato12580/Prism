# Step B + P3 端到端验证 Runbook（可直接跑）

> 目的：单元测试全是 mock 的，**不证明真实服务跑起来后图谱扩展/社区/god/surprising 真的进了检索**。本 runbook 用真实服务 + 真实 Neo4j 验证：
> - **Step B**：入库后 Neo4j 里 Entity 真带 `community_id/is_god/cohesion`，有 `surprising` 边，重入库社区稳定。
> - **P3**：`unified_search` 真实运行时**真的把图扩展候选捞进了结果**（带 `source_marker=graph_*/community/god/surprising`），rerank 正常（或正确降级）。
>
> 在另一台机器：`git pull` 后按顺序执行。仓库根目录 `AIOne/` 下运行。分支 `feature/entity-graph-projection`（tip `dd3cd21`）。

---

## 0. 前置

```bash
cd AIOne
git checkout feature/entity-graph-projection && git pull

# .env 至少有：DATABASE_URL / LLM_API_BASE/KEY/MODEL / EMBEDDING_* / NEO4J_*(bolt://...:7687, neo4j/password)
# 可选 rerank（P3）：RERANK_API_BASE/KEY/MODEL；留空则验证降级路径
grep -E '^(DATABASE_URL|LLM_API_BASE|LLM_API_KEY|LLM_MODEL|EMBEDDING_API_BASE|NEO4J_URI|RERANK_)' .env

docker compose up -d
# 等 Neo4j 就绪
until docker compose exec -T neo4j cypher-shell -u neo4j -p password "RETURN 1;" >/dev/null 2>&1; do echo "wait neo4j"; sleep 3; done
echo "neo4j ready"

SKIP_ENGINE=1 python -m backend.run &
python -m engine.run &
curl -s http://localhost:5175/docs >/dev/null && echo backend OK
curl -s http://localhost:5180/docs  >/dev/null && echo engine OK
```

---

## Part A — Step B 验证（社区/god/cohesion/surprising 真写回）

### A1. 上传一份概念密集文档

```bash
cat > /tmp/probe.md <<'EOF'
# 混合检索与重排
个人知识库不能只靠向量检索，应结合 metadata filter 与关键词召回，
再用 RRF 融合多路结果，最后用 cross-encoder 重排。
chunk 粒度、parent-child 分块、embedding 维度都会影响召回率。
重排器（reranker）能显著提升最相关结果的排序。
EOF

RESP=$(curl -s -X POST http://localhost:5175/api/v1/upload/file -F "file=@/tmp/probe.md")
ITEM_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "ITEM_ID=$ITEM_ID"
sleep 45   # 等 Stage A 抽取 + 全图 run_analysis（含 Louvain）
```

### A2. 验证实体进图（P1/Step A 基础）

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source)-[:MENTIONED_IN]-(e:Entity) WHERE s.item_id='$ITEM_ID'
   RETURN e.canonical_name AS entity, e.entity_type AS type LIMIT 30;"
```
期望：列出 `concept/method/term` 类实体（混合检索/RRF/重排/embedding…）。

### A3. 验证社区 / god / cohesion（Step B 核心）

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity) WHERE e.community_id IS NOT NULL
   RETURN e.community_id AS cid, e.is_god AS god, e.cohesion AS coh, count(*) AS n
   ORDER BY cid;"
```
**验收**：实体按 `community_id` 分了组；至少有一个 `is_god=true`；`cohesion` 有非空浮点值。
> 若全表只有 1 个社区、无 god：说明图太小或边太少。多上传几份相关文档让图谱丰富后再验。

### A4. 验证 surprising 边

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) WHERE r.surprising=true
   RETURN a.canonical_name, b.canonical_name, r.note LIMIT 10;"
```
**验收**：图足够大时出现跨社区 `surprising=true` 桥接边（图很小可能为空，正常）。

### A5. 验证社区稳定性（重入库 community_id 不漂）

```bash
BEFORE=$(docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity) WHERE e.community_id IS NOT NULL RETURN count(DISTINCT e.community_id);" | grep -oE '[0-9]+' | tail -1)
echo "社区数 before: $BEFORE"

# 重入库同一 item（engine 删旧 chunk、重跑 Stage A + 全图分析）
curl -s -X POST http://localhost:5180/api/v1/ingest -H 'Content-Type: application/json' -d "{\"item_id\":\"$ITEM_ID\"}"
sleep 45

AFTER=$(docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity) WHERE e.community_id IS NOT NULL RETURN count(DISTINCT e.community_id);" | grep -oE '[0-9]+' | tail -1)
echo "社区数 after:  $AFTER"

# 抽查：同名实体的 community_id 应基本不变（稳定重映射）
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (e:Entity) WHERE e.community_id IS NOT NULL
   RETURN e.canonical_name, e.community_id ORDER BY e.canonical_name LIMIT 20;"
```
**验收**：`AFTER` 与 `BEFORE` 接近（不翻倍）；关键实体的 `community_id` 重入库前后一致。

---

## Part B — P3 验证（检索真的用了图扩展 + rerank）

### B1. 直接探针：真实调用 unified_search（最可靠，绕过 agent 层）

这个脚本用**真实 DB + 真实 Neo4j**（+ 真实 rerank 若配置）直接跑 `unified_search`，打印每条候选的 `source_marker`。能直接看到图扩展是否贡献了候选。

```bash
cat > /tmp/probe_unified.py <<'PY'
import os, sys
sys.path.insert(0, "/path/to/AIOne")  # ← 改成你这台机器的 AIOne 绝对路径
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from engine.app.config import settings
from engine.app.retrieval.unified import unified_search
from backend.app.services.graph_client import GraphClient

db = sessionmaker(bind=create_engine(settings.DATABASE_URL, pool_pre_ping=True))()
gc = GraphClient()
try:
    for mode in ("fast", "deep"):
        print(f"\n===== mode={mode} =====")
        hits = unified_search(
            "混合检索和重排是怎么做的", top_k=10, mode=mode,
            db=db, graph_client=gc, topic_ids=None, source_types=None, allowed_item_ids=None,
        )
        print(f"返回 {len(hits)} 条候选")
        for h in hits:
            print(f"  chunk={h.get('chunk_id')}  marker={h.get('source_marker')}  score={h.get('score')}")
        markers = {h.get("source_marker") for h in hits}
        graph_markers = {m for m in markers if m and m != "rerank"}
        print(f"  → 图扩展贡献标记: {graph_markers or '（无——图扩展未命中）'}")
finally:
    db.close(); gc.close()
PY
DATABASE_URL="$(grep ^DATABASE_URL .env | cut -d= -f2-)" python /tmp/probe_unified.py
```
> 把 `/path/to/AIOne` 改成实际路径。`DATABASE_URL` 从 .env 取（脚本里 settings 已会读，这里再 export 保险）。

**验收**：
- `fast` 模式：出现 `source_marker=graph_1hop`（或 rerank 后统一为 `rerank`，但至少**候选总数 > 纯向量召回**，说明图扩展有贡献）。
- `deep` 模式：出现 `community/god/surprising` 标记。
- 若所有 marker 都是 `None` 或只有向量：说明种子实体匹配失败或 Neo4j 扩展没生效——查 engine 日志的 `[graph_expand]`/`[unified]` 警告。

### B2. 日志负面检查（无降级警告 = 链路通）

```bash
# 看 engine 日志里有没有 P3 相关的失败降级警告
docker compose logs engine 2>/dev/null | grep -E "\[unified\]|\[graph_expand\]|\[rerank\]" | tail -20
```
**验收**：
- 无 `[unified] hybrid_failed` / `[graph_expand] *_failed` → 检索主链路通。
- `[rerank] degraded` 出现 → rerank 没配或挂了（符合预期则 OK，它降级为 RRF）。

### B3. rerank 配置/降级切换验证

```bash
# 情况1：配了 rerank → 探针里候选 marker 应出现 rerank
# 情况2：临时关掉 → 验证降级
export RERANK_ENABLED=0
# 重启 engine 使配置生效（或 .env 改 RERANK_ENABLED=0 后重启）
python /tmp/probe_unified.py
# 期望：仍正常返回候选，不报错，marker 不含 rerank（纯 RRF 顺序）
```

### B4. agent 对话冒烟（端到端打通）

```bash
curl -s -N -X POST http://localhost:5180/api/v1/chat/answer \
  -H 'Content-Type: application/json' \
  -d '{"query":"混合检索和重排是怎么做的？","history":[]}' | head -c 2000
```
**验收**：流式返回正常（NDJSON 事件：agent_status/tool_call/token/done），回答引用了知识库内容、不报错。
> 想看图扩展是否进 agent 的证据：开深度搜索（前端开关，或后端 `deep_search_enabled=true`）再问，trace/日志里 source_marker 更丰富。

---

## 结果记录

| 检查项 | 期望 | 实测 |
|--------|------|------|
| A2 实体进图 | concept/method 类实体 | |
| A3 社区/god/cohesion | 分组 + is_god + cohesion 有值 | |
| A4 surprising 边 | 图足够大时出现 | |
| A5 重入库社区稳定 | AFTER≈BEFORE，实体 cid 不变 | |
| B1 图扩展贡献候选 | fast→graph_1hop；deep→community/god/surprising | |
| B2 无降级警告 | 无 *_failed | |
| B3 rerank 降级 | 关闭后仍正常返回 | |
| B4 对话冒烟 | 流式正常、引用知识库 | |

全部通过 → **Step B + P3 运行时验证完成**，可放心进入 P4/P5。

---

## 常见问题排查

- **A3 无 god / 只 1 个社区**：图谱太小。多上传 5~10 份相关文档再验。
- **B1 图扩展无贡献**：
  1. 查 `match_seed_entities` —— query 词经 jieba 分词后能否命中 `EntityAlias`/`KnowledgeEntity`（用 Neo4j/Mysql 看实体名是否和 query 词重叠）。
  2. 查 Neo4j `(:Entity)-[:MENTIONED_IN]->(:Source)` 边是否存在（Step A 投影是否成功）。
  3. 查 `graph.neighbors` 的 Cypher 变长路径 `*1..N` 是否在你 Neo4j 版本可用（5.28.1 支持）。
- **B4 对话报错**：查 engine 日志 `docker compose logs engine --tail 50`。

## 清理（可选）

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p password \
  "MATCH (s:Source) WHERE s.item_id='$ITEM_ID' DETACH DELETE s;"
rm -f /tmp/probe.md /tmp/probe_unified.py
```
