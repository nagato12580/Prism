#!/usr/bin/env bash
# clear_all_data.sh — 清空所有数据库容器内部的数据
#
# 范围（docker-compose.ecs-full.yml 的数据服务，容器与命名卷均保留）：
#   MySQL / Redis / etcd / MinIO / Milvus / Neo4j / Elasticsearch
#
# 方式：停掉数据容器 → 用各容器自己的镜像挂载命名卷、清空卷内数据文件 →
#       重启数据容器让其重新初始化（容器、卷本身都不删除）。
#       若 backend/engine/frontend 正在运行，清空并等 MySQL 就绪后会重启它们，
#       让 auto_migrate 重建表、collection、索引。
#   ※ 上传文件卷 uploads_data（用户文件）不在清理范围内。
#
# 用法：
#   scripts/clear_all_data.sh               # 交互确认后执行
#   scripts/clear_all_data.sh -y            # 跳过确认直接执行
#   scripts/clear_all_data.sh -y --no-start # 清空但不重启数据容器（保持停止）
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# 活跃部署使用的 compose 文件（.env 中 COMPOSE_FILE=docker-compose.ecs-full.yml，可用环境变量覆盖）
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.ecs-full.yml}"

# 数据服务及其清理顺序
DATA_SERVICES=(mysql redis etcd minio milvus neo4j elasticsearch)
# 应用容器（清空后需要重启以重建 schema）
APP_SERVICES=(backend engine frontend)

ASSUME_YES=0
START_AFTER=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)     ASSUME_YES=1; shift ;;
    --no-start)   START_AFTER=0; shift ;;
    -h|--help)
      echo "Usage: $0 [-y] [--no-start] [--compose FILE]"
      echo "  -y, --yes       跳过确认直接清空"
      echo "  --no-start      清空后不重启数据容器（保持停止，稍后自行 docker compose up -d）"
      echo "  --compose FILE  指定 compose 文件（默认 docker-compose.ecs-full.yml）"
      exit 0
      ;;
    --compose)    COMPOSE_FILE="$2"; shift 2 ;;
    *)
      echo "[ERROR] 未知参数: $1" >&2
      echo "Usage: $0 [-y] [--no-start] [--compose FILE]" >&2
      exit 2
      ;;
  esac
done

# 前置检查
if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] 未找到 docker 命令" >&2
  exit 1
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[ERROR] compose 文件不存在: $COMPOSE_FILE" >&2
  exit 1
fi

# 取容器第一个「命名数据卷」（跳过 64 位 hash 的匿名卷），输出 VOL|DEST
named_volume() {
  local cid="$1" m n d
  for m in $(docker inspect "$cid" --format '{{range .Mounts}}{{if .Name}}{{.Name}}|{{.Destination}} {{end}}{{end}}' 2>/dev/null); do
    n="${m%%|*}"; d="${m#*|}"
    if [[ -z "$n" || -z "$d" ]]; then continue; fi
    [[ "$n" =~ ^[0-9a-f]{64}$ ]] && continue
    printf '%s|%s' "$n" "$d"
    return 0
  done
  return 1
}

echo "==> compose 文件: $COMPOSE_FILE"
echo "==> 将要清空的数据容器:"
for s in "${DATA_SERVICES[@]}"; do
  CID="$(docker compose -f "$COMPOSE_FILE" ps -a -q "$s" 2>/dev/null || true)"
  if [[ -n "$CID" ]]; then
    NV="$(named_volume "$CID")"
    if [[ -n "$NV" ]]; then
      printf '    - %-15s (卷: %s -> %s)\n' "$s" "${NV%%|*}" "${NV#*|}"
    else
      printf '    - %-15s (卷: <未找到>)\n' "$s"
    fi
  else
    printf '    - %-15s (无容器，跳过)\n' "$s"
  fi
done
echo "    以上容器与卷将保留，仅清空内部数据，不可恢复！"

if [[ "$ASSUME_YES" -eq 0 ]]; then
  read -r -p "确认清空？(y/N) " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "已取消，未做任何改动。"; exit 0; }
fi

# 记录当前正在运行的应用容器（清空后需要重启它们以重建 schema）
RUNNING_APP=()
for s in "${APP_SERVICES[@]}"; do
  CID="$(docker compose -f "$COMPOSE_FILE" ps -a -q "$s" 2>/dev/null || true)"
  if [[ -n "$CID" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "$CID" 2>/dev/null)" == "true" ]]; then
    RUNNING_APP+=("$s")
  fi
done

echo "==> 停止数据容器 ..."
docker compose -f "$COMPOSE_FILE" stop "${DATA_SERVICES[@]}"

echo "==> 清空数据容器内部数据 ..."
WIPED=0; FAILED=()
for s in "${DATA_SERVICES[@]}"; do
  CID="$(docker compose -f "$COMPOSE_FILE" ps -a -q "$s" 2>/dev/null || true)"
  if [[ -z "$CID" ]]; then
    echo "  [skip] $s：无容器"
    continue
  fi
  IMG="$(docker inspect "$CID" --format '{{.Config.Image}}')"
  NV="$(named_volume "$CID")" || true
  VOL="${NV%%|*}"; DEST="${NV#*|}"
  if [[ -z "$VOL" || -z "$DEST" || "$NV" == "|" ]]; then
    echo "  [skip] $s：未找到命名数据卷"
    FAILED+=("$s"); continue
  fi
  printf '  [%s] 清空 %s ... ' "$s" "$VOL"
  if docker run --rm -v "$VOL:$DEST" --entrypoint sh "$IMG" -c "find '$DEST' -mindepth 1 -delete"; then
    echo "✓"
    WIPED=$((WIPED+1))
  else
    echo "✗ 失败"
    FAILED+=("$s")
  fi
done
echo "  已清空 $WIPED 个数据卷${FAILED:+/ 失败: ${FAILED[*]}}"

if [[ "$START_AFTER" -eq 0 ]]; then
  echo "==> 完成（未重启）。数据容器保持停止，稍后执行: docker compose -f $COMPOSE_FILE up -d"
  exit 0
fi

echo "==> 重启数据容器（重新初始化空数据）..."
docker compose -f "$COMPOSE_FILE" up -d "${DATA_SERVICES[@]}"

# 等待 MySQL 就绪（重新初始化需要时间）
echo "==> 等待 MySQL 就绪 ..."
mysql_cid="$(docker compose -f "$COMPOSE_FILE" ps -a -q mysql 2>/dev/null || true)"
if [[ -n "$mysql_cid" ]]; then
  for _ in $(seq 1 60); do
    st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$mysql_cid" 2>/dev/null || echo unknown)"
    [[ "$st" == "healthy" ]] && break
    sleep 2
  done
  echo "  MySQL 状态: $st"
fi

if [[ ${#RUNNING_APP[@]} -gt 0 ]]; then
  echo "==> 重启应用容器（auto_migrate 重建 schema）: ${RUNNING_APP[*]}"
  docker compose -f "$COMPOSE_FILE" restart "${RUNNING_APP[@]}"
else
  echo "==> 应用容器未运行，无需重启。"
  echo "    启动整个栈: docker compose -f $COMPOSE_FILE up -d"
fi

echo ""
echo "==> 完成。数据容器已清空并重启，容器/卷均保留；上传文件(uploads_data)未受影响。"
docker compose -f "$COMPOSE_FILE" ps --format '  {{.Name}}\t{{.Status}}' "${DATA_SERVICES[@]}" 2>/dev/null || true
