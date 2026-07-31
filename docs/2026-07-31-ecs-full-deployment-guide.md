# Prism 阿里云 ECS 单机 Docker 部署手册

本文面向已经把代码拉到服务器上的情况，目标是在 `2核8G` 的阿里云 ECS 上，使用 Docker 部署 Prism 的单机全量能力版本。

本文对应的部署文件：

- `docker-compose.ecs-full.yml`
- `.env.ecs-full`
- `.env.ecs-full.example`

注意：

- 这是单机全量部署，已经尽量压低了内存和并发参数，但 `2核8G` 仍然比较紧。
- 第一次启动会比较慢，尤其是 `Elasticsearch`、`Milvus`、`Neo4j`。
- 如果后续出现 OOM、容器频繁重启、入库很慢，优先考虑升级实例规格。
- 当前部署文件里的 Neo4j 镜像固定为 `neo4j:5.26.28`，不要手动改回 `5.28.1`。
- 前端 Docker 构建已切换到 `pnpm@9.15.9`，用来兼容仓库里的 `frontend/pnpm-lock.yaml`。

## 1. 前提

假设：

- 服务器系统为 Linux
- 项目目录为 `/mnt/work_space/AIOne`
- 你已经有可用的 LLM/Embedding 接口和密钥

如果项目目录不是 `/mnt/work_space/AIOne`，把下面命令里的路径替换成你的实际路径。

## 2. 进入项目目录

```bash
cd /mnt/work_space/AIOne
```

## 3. 安装 Docker

如果服务器还没有 Docker，执行：

```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

如果执行 `docker` 没权限，可以先用：

```bash
sudo usermod -aG docker $USER
newgrp docker
```

## 4. 配置内核参数

`Elasticsearch` 需要 `vm.max_map_count`，否则启动会失败。

执行：

```bash
sudo sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-prism.conf
sudo sysctl --system
```

验证：

```bash
sysctl vm.max_map_count
```

预期输出：

```text
vm.max_map_count = 262144
```

## 5. 准备环境变量文件

复制模板：

```bash
cp .env.ecs-full.example .env.ecs-full
```

编辑文件：

```bash
vim .env.ecs-full
```

优先确认以下内容：

```env
MYSQL_ROOT_PASSWORD=CHANGE-ME
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin

JWT_SECRET=一串随机长字符串
KNOWLEDGE_SCOPE_SECRET=一串随机长字符串

LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=你的大模型密钥
LLM_MODEL=deepseek-v4-flash

EMBEDDING_API_BASE=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=你的 embedding 密钥
SILICONFLOW_API_KEY=你的 embedding 密钥

RERANK_API_BASE=https://api.siliconflow.cn/v1/rerank
RERANK_API_KEY=你的 rerank 密钥
RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

说明：

- 上面 `MYSQL_ROOT_PASSWORD`、`NEO4J_USERNAME`、`NEO4J_PASSWORD`、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD` 已经按当前仓库里的现有默认配置写好。
- `LLM_API_KEY`、`EMBEDDING_API_KEY`、`SILICONFLOW_API_KEY`、`RERANK_API_KEY` 这些密钥项，按你当前项目现有 `.env` 已经可以直接沿用。
- 如果你不打算调整密钥来源，可以直接使用仓库里的 `.env.ecs-full`，不必手工重填这一段。

如果你暂时没有 `rerank` 服务，可以先这样改：

```env
RERANK_ENABLED=0
RERANK_API_BASE=
RERANK_API_KEY=
RERANK_MODEL=
```

如果你暂时没有 `community label` 专用模型，可以留空：

```env
COMMUNITY_LABEL_MODEL=
ENTITY_EXTRACT_MODEL=
DEEP_SEARCH_JUDGE_MODEL=
```

这些值留空时，通常会回退到 `LLM_MODEL` 或直接关闭对应增强能力，能减少启动和运行时风险。

按当前仓库现状，下面这些值已经是可直接使用的：

```env
ENTITY_EXTRACT_MODEL=
COMMUNITY_LABEL_MODEL=
DEEP_SEARCH_JUDGE_MODEL=gpt-5.4-mini
DEEP_SEARCH_JUDGE_API_BASE=https://chat.ekti.cc/v1
DEEP_SEARCH_JUDGE_MIN_OVERALL_SCORE=0.8
```

## 6. 启动服务

执行：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml up -d --build
```

首次执行会做下面这些事：

- 构建 `backend`
- 构建 `engine`
- 构建 `frontend`
- 构建 `prism-es-ik`
- 拉取 MySQL、Redis、Milvus、Neo4j、MinIO、etcd 等镜像
- 创建数据卷
- 启动全部容器

首次启动时间可能比较长，尤其是在网络较慢时。

如果你想先单独验证前端镜像是否能构建通过，可以先执行：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml build frontend
```

如果前端单独构建通过，再执行全量启动：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml up -d --build
```

## 7. 查看启动状态

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml ps
```

如果所有核心服务都起来了，再继续下一步。

核心服务包括：

- `mysql`
- `redis`
- `etcd`
- `minio`
- `milvus`
- `neo4j`
- `elasticsearch`
- `engine`
- `backend`
- `frontend`

说明：

- 当前部署文件里的 Neo4j 镜像已经固定为 `neo4j:5.26.28`。
- 之前的 `neo4j:5.28.1` 在当前 Docker Hub 官方标签列表中不可用，拉取时会报 `denied` 或 `not found`。
- 当前前端 Dockerfile 已固定使用 `pnpm@9.15.9`。如果你看到 `ERR_PNPM_LOCKFILE_BREAKING_CHANGE`，说明服务器上的代码还没更新到最新版本，需要先 `git pull`。

## 8. 查看日志

如果某个容器没有起来，查看完整日志：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200
```

也可以只看某个服务，例如：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200 elasticsearch
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200 milvus
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200 neo4j
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200 engine
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs -f --tail=200 backend
```

## 9. 验证服务

先在服务器本机验证：

```bash
curl http://127.0.0.1:8080
curl http://127.0.0.1:5175/health
curl http://127.0.0.1:5180/health
```

说明：

- `8080` 是前端入口
- `5175` 是后端健康检查
- `5180` 是引擎健康检查

只要 `5175` 和 `5180` 返回正常，说明应用主链路已经起来了。

## 10. 浏览器访问

在阿里云控制台确认安全组已经放行 `8080` 端口后，浏览器打开：

```text
http://你的服务器公网IP:8080
```

如果你后续要正式对外提供服务，建议再加一个反向代理或 HTTPS 层。

## 11. 常用运维命令

重启：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml restart
```

停止：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml down
```

停止并删除数据卷：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml down -v
```

重新构建并启动：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml up -d --build
```

查看容器状态：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml ps
```

## 12. 常见问题

### 12.1 Elasticsearch 启动失败

优先检查：

```bash
sysctl vm.max_map_count
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs --tail=200 elasticsearch
```

如果内存不足，可以进一步下调：

```env
ES_JAVA_OPTS=-Xms512m -Xmx512m
```

但这会进一步影响检索稳定性和性能。

### 12.2 容器频繁重启或被杀

先查：

```bash
free -h
docker stats
```

重点观察：

- `elasticsearch`
- `milvus`
- `neo4j`
- `engine`

如果出现明显 OOM，说明 `2核8G` 已经压不住当前负载。

### 12.3 frontend 构建失败

如果你看到类似下面的错误：

```text
ERR_PNPM_LOCKFILE_BREAKING_CHANGE
```

说明服务器上的前端 Dockerfile 还是旧版本，还在使用 `pnpm 8`。先执行：

```bash
cd /srv/prism
git pull
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml build frontend
```

如果你看到的是普通的 TypeScript 编译错误，也先执行 `git pull`，因为部署文件已经同步了本次修复。

### 12.4 页面能打开，但上传或知识检索异常

重点检查：

```bash
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs --tail=200 engine
docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml logs --tail=200 backend
```

同时确认：

- `LLM_API_BASE` 和 `LLM_API_KEY` 正确
- `EMBEDDING_API_KEY` 或 `SILICONFLOW_API_KEY` 正确
- 如果启用了 rerank，`RERANK_*` 配置正确

### 12.5 外网打不开 8080

检查：

```bash
ss -lntp | grep 8080
```

如果本机监听正常，再去阿里云控制台检查安全组是否放行 `8080/tcp`。

## 13. 推荐执行顺序

如果你希望最稳妥，按这个顺序执行：

1. `cd /mnt/work_space/AIOne`
2. 安装 Docker
3. 配置 `vm.max_map_count`
4. `cp .env.ecs-full.example .env.ecs-full`
5. 编辑 `.env.ecs-full`
6. `docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml up -d --build`
7. `docker compose --env-file .env.ecs-full -f docker-compose.ecs-full.yml ps`
8. `curl http://127.0.0.1:5175/health`
9. `curl http://127.0.0.1:5180/health`
10. 浏览器访问 `http://公网IP:8080`

## 14. 文件位置

本次部署相关文件如下：

- `docker-compose.ecs-full.yml`
- `.env.ecs-full`
- `.env.ecs-full.example`
- `docs/2026-07-31-ecs-full-deployment-guide.md`
