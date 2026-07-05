# P1 Task 8 — 端到端验证 Runbook（可直接跑）

> 验证目标：上传一份「概念/术语密集、抽不出 PKU」的文档后，**每个 chunk 都挂上了 Entity 并通过 `MENTIONED_IN` 边进入 Neo4j**，证明「之前不进图的内容现在进图了」。
> 适用分支：`feature/entity-graph-projection`（提交 `1da70a7` 及之前）。
> 在另一台电脑上：`git pull` 后按本清单顺序执行。所有命令在仓库根目录 `AIOne/` 下运行。

---

## 0. 前置条件

```bash
# 0.1 拉取最新分支
cd AIOne
git checkout feature/entity-graph-projection
git pull

# 0.2 确认 .env 至少包含这些键（值按你的环境填）
grep -E '^(DATABASE_URL|LLM_API_BASE|LLM_API_KEY|LLM_MODEL|EMBEDDING_API_BASE|EMBEDDING_API_KEY|EMBEDDING_MODEL|NEO4J_URI|NEO4J_USERNAME|NEO4J_PASSWORD|ENGINE_BASE_URL)=' .env
# 可选：用便宜模型做抽取以控成本
#   ENTITY_EXTRACT_MODEL=qwen2.5:3b   （留空则复用 LLM_MODEL）
#   ENTITY_EXTRACT_WORKERS=4
#   ENTITY_EXTRACT_ENABLED=1          （默认开；置 0 可临时关闭 Stage A）

# 0.3 确认 Docker 已启动
docker --version && docker compose version
```

---

## 1. 启动依赖服务 + 应用

```bash
# 1.1 启动 MySQL / Redis / Milvus / Neo4j / ES / MinIO / etcd / faster-whisper
docker compose up -d

# 1.2 等待 Neo4j 就绪（bolt 7687 可连即 OK）
until docker compose exec -T neo4j cypher-shell -u neo4j -p password "RETURN 1;" >/dev/null 2>&1; do
  echo "waiting neo4j..."; sleep 3
done
echo "neo4j ready"

# 1.3 启动 backend(:5175) 与 engine(:5180)。新开两个终端，或后台起：
SKIP_ENGINE=1 python -m backend.run &       # backend :5175，会自动 migrate
python -m engine.run &                       # engine  :5180

# 1.4 健康检查
curl -s http://localhost:5175/docs >/dev/null && echo "backend OK"
curl -s http://localhost:5180/docs  >/dev/null && echo "engine OK"
```

---

## 2. 准备一份「难抽实体」的测试文档

挑一段**概念/术语密集、无人名机构**的技术笔记（这种内容过去抽不出 PKU/CKP，不会进图）。例：

```bash
cat > /tmp/stage_a_probe.md <<'EOF'
# 混合检索与重排

个人知识库不能只靠向量检索，应结合 metadata filter 与关键词召回，
再用 RRF（Reciprocal Rank Fusion）融合多路结果，最后用 cross-encoder
做重排。chunk 粒度、parent-child 分块、embedding 维度都会影响召回率。
EOF
```

---

## 3. 上传 → 自动入库（捕获 item_id）

```bash
# 3.1 上传文件（backend 会自动触发 engine 摄入）
RESP=$(curl -s -X POST http://localhost:5175/api/v1/upload/file \
  -F "file=@/tmp/stage_a_probe.md")
echo "$RESP"

# 3.2 从返回 JSON 取出 item_id（字段名为 id）
ITEM_ID=$(echo "$RESP" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "ITEM_ID=$ITEM_ID"
```

> 摄入是异步触发的（backend fire-and-forget 调 engine）。等待几秒后进入下一步。

---

## 4. 验证：实体已进图（核心验收点）

```bash
# 4.1 等 Stage A 跑完（最多等 ~60s；取决于 LLM 速度）
sleep 20

# 4.2 Neo4j：该 item 的 Source 节点挂了哪些 Entity（concept/method/term...）
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source)-[:MENTIONED_IN]-(e:Entity)
   WHERE s.item_id = '$ITEM_ID'
   RETURN e.canonical_name AS entity, e.entity_type AS type, e.confidence AS conf
   ORDER BY conf DESC LIMIT 50;"

# 4.3 计数：该 item 的 MENTIONED_IN 边数（应 > 0）
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source)-[:MENTIONED_IN]-(e:Entity)
   WHERE s.item_id = '$ITEM_ID'
   RETURN count(*) AS mention_edges;"
```

**验收标准：**
- 4.2 能列出 `concept`/`method`/`term` 等**非人名/非机构**的实体（如「混合检索」「RRF」「重排」「embedding」），证明概念类内容已进图。
- 4.3 `mention_edges > 0`。
- 对照：上传前同样的文档，Neo4j 里**不会**有这些 `MENTIONED_IN` 边（旧逻辑只抽人名/机构/邮箱/论文标题）。

---

## 5. 幂等性 / 重入库（验证不产生孤儿 mention）

```bash
# 5.1 记录重入库前的边数
BEFORE=$(docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source)-[:MENTIONED_IN]-(e:Entity) WHERE s.item_id = '$ITEM_ID' RETURN count(*);" \
  | grep -oE '[0-9]+' | tail -1)
echo "edges before reingest: $BEFORE"

# 5.2 对同一 item 重新摄入（engine 会删旧 chunk、生成新 chunk UUID、重跑 Stage A）
curl -s -X POST http://localhost:5180/api/v1/ingest \
  -H 'Content-Type: application/json' \
  -d "{\"item_id\": \"$ITEM_ID\"}"
echo
sleep 20

# 5.3 重入库后的边数 —— 应与 BEFORE 基本一致（不单调累积）
AFTER=$(docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source)-[:MENTIONED_IN]-(e:Entity) WHERE s.item_id = '$ITEM_ID' RETURN count(*);" \
  | grep -oE '[0-9]+' | tail -1)
echo "edges after reingest:  $AFTER"

# 5.4 不应存在指向「已删除 chunk」的僵尸 Source 节点（标题是裸 UUID 的要警惕）
docker compose exec -T neo4j cypher-shell -u neo4j -p password --format plain \
  "MATCH (s:Source) WHERE s.item_id = '$ITEM_ID' RETURN s.id, s.title LIMIT 20;"
```

**验收标准：** `AFTER` 与 `BEFORE` 接近（允许因重抽产生小幅波动，但**不应翻倍/单调增长**）；没有标题为纯 chunk-UUID 的僵尸 Source。

---

## 6. （可选）MySQL 侧交叉核对

```bash
# 用你 .env 里 DATABASE_URL 的用户/库名替换
docker compose exec -T mysql mysql -uroot -p"<DB_PASSWORD>" "<DB_NAME>" -e \
  "SELECT COUNT(*) AS mentions FROM entity_mention WHERE item_id='$ITEM_ID';
   SELECT entity_type, COUNT(*) FROM entity_mention m
     JOIN knowledge_entity e ON e.id=m.entity_id
     WHERE m.item_id='$ITEM_ID' GROUP BY entity_type;"
```

`entity_mention` 行数应与 Neo4j `MENTIONED_IN` 边数一致。

---

## 7. 回滚开关（如有问题临时关闭 Stage A）

在 `.env` 里设 `ENTITY_EXTRACT_ENABLED=0` 并重启 engine 即可。Stage A 整段短路，不影响现有入库/检索。

---

## 8. 清理（可选）

```bash
# 删掉测试 item 的图数据（按需）
docker compose exec -T neo4j cypher-shell -u neo4j -p password \
  "MATCH (s:Source) WHERE s.item_id='$ITEM_ID' DETACH DELETE s;"
rm -f /tmp/stage_a_probe.md
```

---

## 结果记录

| 检查项 | 期望 | 实测 |
|--------|------|------|
| 4.2 列出概念/术语类 Entity | ✅ 有 concept/method/term | |
| 4.3 MENTIONED_IN 边数 | > 0 | |
| 5.3 重入库后边数 | 与 BEFORE 接近，不翻倍 | |
| 5.4 无僵尸 Source | ✅ | |

全部通过 → **P1 验收完成**。
```
