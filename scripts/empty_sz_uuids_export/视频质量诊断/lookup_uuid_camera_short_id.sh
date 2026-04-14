#!/usr/bin/env bash
# 根据当前目录下的 uuids.txt，用 mysql 查询 web-op.tbl_vqd_event_info（与 QualityJudgment.sh 同源），
# 输出 vei_ubi_vqd_event_id 与 vei_ubi_short_id（制表符分隔）。
#
# 默认配置（与 scripts/sync_task_01.py 中 TARGET_SSH_HOST / TARGET_SSH_DB_PORT 一致）：
#   TARGET_IP / TARGET_DB_PORT —— MySQL 地址
#   输入：./uuids.txt（相对「运行脚本时的当前工作目录」）
#   输出：./uuid_vei_ubi_short_id.txt
#
# 依赖：mysql 客户端
#
# 用法：在放有 uuids.txt 的目录执行
#   /path/to/lookup_uuid_camera_short_id.sh
# 可选：-W 密码  |  export MYSQL_PASSWORD=...  |  --no-header  |  -h

set -euo pipefail

# ========== 硬编码（与 sync_task_01.py 一致，改库地址只改这里）==========
TARGET_IP="10.31.243.3"
TARGET_DB_PORT="3308"
UUIDS_FILE="./uuids.txt"
OUT_FILE="./uuid_vei_ubi_short_id.txt"
# ========================================================================

NO_HEADER=0
CHUNK_SIZE=400

MYSQL_HOST="$TARGET_IP"
MYSQL_PORT="$TARGET_DB_PORT"
MYSQL_USER="admin"
DEFAULT_MYSQL_PASSWORD='3edcVFR$'
CLI_MYSQL_PASSWORD=""
MYSQL_DB="web-op"

usage() {
  sed -n '1,18p' "$0" | tail -n +2
  echo "可选: -W PASS（覆盖密码）  --no-header  -h"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -W) CLI_MYSQL_PASSWORD="$2"; shift 2 ;;
    --no-header) NO_HEADER=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ ! -f "$UUIDS_FILE" ]]; then
  echo "找不到 $UUIDS_FILE（请在包含 uuids.txt 的目录下执行本脚本）" >&2
  exit 1
fi

if [[ -n "$CLI_MYSQL_PASSWORD" ]]; then
  MYSQL_PASSWORD="$CLI_MYSQL_PASSWORD"
else
  MYSQL_PASSWORD="${MYSQL_PASSWORD:-$DEFAULT_MYSQL_PASSWORD}"
fi

if ! command -v mysql >/dev/null 2>&1; then
  echo "未找到 mysql 客户端（例如: apt install mysql-client）" >&2
  exit 1
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

ORDERED="$TMPDIR/ordered.txt"
awk '
  {
    gsub(/^[ \t\r]+|[ \t\r]+$/, "")
    if ($0 == "" || substr($0,1,1) == "#") next
    if (!seen[$0]++) print $0
  }
' "$UUIDS_FILE" > "$ORDERED"

if [[ ! -s "$ORDERED" ]]; then
  echo "uuids 文件中没有有效行" >&2
  exit 1
fi

MAP="$TMPDIR/map.tsv"
: > "$MAP"

MYSQL_BASE=(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" -N -B)

run_query() {
  local sql="$1"
  if ! "${MYSQL_BASE[@]}" "$MYSQL_DB" -e "$sql" >>"$MAP" 2>/dev/null; then
    return 1
  fi
  return 0
}

split -l "$CHUNK_SIZE" "$ORDERED" "$TMPDIR/chunk_"
for chunk in "$TMPDIR"/chunk_*; do
  [[ -f "$chunk" ]] || continue
  in_list=""
  while IFS= read -r u || [[ -n "$u" ]]; do
    u="${u//\'/\'\'}"
    in_list+="'$u',"
  done < "$chunk"
  in_list="${in_list%,}"
  [[ -n "$in_list" ]] || continue

  sql="SELECT vei.ubi_vqd_event_id, IFNULL(TRIM(vei.ubi_short_id), '')
FROM tbl_vqd_event_info vei
WHERE vei.ubi_vqd_event_id IN ($in_list);"

  if ! run_query "$sql"; then
    echo "MySQL 查询失败（检查 ${TARGET_IP}:${TARGET_DB_PORT}、账号密码、表结构）" >&2
    exit 1
  fi
done

STATS_OUT="$TMPDIR/stats.txt"
if [[ "$NO_HEADER" -eq 0 ]]; then
  printf '%s\t%s\n' "vei_ubi_vqd_event_id" "vei_ubi_short_id" > "$OUT_FILE"
else
  : > "$OUT_FILE"
fi

awk -v mapfile="$MAP" -v statsfile="$STATS_OUT" -v outf="$OUT_FILE" '
  BEGIN {
    while ((getline line < mapfile) > 0) {
      p = index(line, "\t")
      if (p > 0) {
        eid = substr(line, 1, p - 1)
        sid = substr(line, p + 1)
      } else {
        eid = line
        sid = ""
      }
      m[eid] = sid
    }
    close(mapfile)
    missing = 0
    emptycam = 0
  }
  {
    u = $0
    if (!(u in m)) { missing++; print u "\t" >> outf; next }
    if (m[u] == "") { emptycam++; print u "\t" >> outf; next }
    print u "\t" m[u] >> outf
  }
  END {
    print missing " " emptycam > statsfile
    close(outf)
  }
' "$ORDERED"

read -r missing_in_db empty_short_id < "$STATS_OUT" || true
missing_in_db="${missing_in_db:-0}"
empty_short_id="${empty_short_id:-0}"

total=$(wc -l < "$ORDERED" | tr -d ' ')

echo "uuids: $UUIDS_FILE（去重后 $total 行）"
echo "MySQL: ${MYSQL_USER}@${TARGET_IP}:${TARGET_DB_PORT}/${MYSQL_DB}"
echo "已写入: $OUT_FILE"
echo "库中无此事件 ID: $missing_in_db；ubi_short_id 为空: $empty_short_id"
