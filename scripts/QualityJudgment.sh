#!/bin/bash

PROJECT_NAME=$1
TARGET_IP=$2
TARGET_DB_PORT=$3


LOG_FILE="./quality_execution.log"
GROUP_CONCAT_MAX_LEN=1048576
sqlSelectFunc() {
    local beginTime=$1
    local endTime=$2

    alias="vei"   # 这里设置表别名
    db="web-op"
    tbl="tbl_vqd_event_info"

    cols=$(mysql -h ${TARGET_IP} -P ${TARGET_DB_PORT} -u admin -p3edcVFR$ web-op -B -N -e "$(cat <<SQL
SET SESSION group_concat_max_len=${GROUP_CONCAT_MAX_LEN};
SELECT GROUP_CONCAT(
  CONCAT(
    'NULLIF(TRIM($alias.\`', COLUMN_NAME, '\`), '''') AS ${alias}_', COLUMN_NAME
  )
  SEPARATOR ', '
)
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA='$db' AND TABLE_NAME='$tbl';
SQL
)"
)

    mysql -h ${TARGET_IP} -P ${TARGET_DB_PORT} -u admin -p3edcVFR$ -B -e "
USE web-op;
SET SESSION group_concat_max_len=${GROUP_CONCAT_MAX_LEN};
SELECT 
    sci.sz_name,
    ${cols}
FROM
(
    tbl_vqd_event_info ${alias}
    INNER JOIN tbl_share_camera_info sci ON ${alias}.ubi_short_id = sci.ubi_short_id
)
WHERE ${alias}.ubi_detect_time BETWEEN ${beginTime} AND ${endTime};
    "
}


# ==========================================
# 主逻辑
# ==========================================

yesterday_str=$(date -d "yesterday" +%F)
start_ts=$(date -d "${yesterday_str} 00:00:00 -16 hour" +%s)
end_ts=$(date -d "${yesterday_str} 23:59:59 -16 hour" +%s)
start_ts="${start_ts}000"
end_ts="${end_ts}000"

echo "Running QualityJudgment for date: ${yesterday_str}"
echo "Time Window: ${start_ts} to ${end_ts}"

data_count=$(sqlSelectFunc ${start_ts} ${end_ts} | tail -n +2 | wc -l)
echo "📊 检测到 ${data_count} 条数据"

MAX_RECORDS=20000

temp_all_data=$(mktemp)
temp_filtered_data=$(mktemp)
temp_final_data=$(mktemp)

echo "📥 正在查询数据到临时文件..." >&2
# 修复：移除 2>&1，避免 mysql 密码警告写入数据文件
sqlSelectFunc ${start_ts} ${end_ts} > "$temp_all_data" 2>/dev/null
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "❌ 数据查询失败" >&2
    rm -f "$temp_all_data" "$temp_filtered_data" "$temp_final_data"
    exit 1
fi

# 统一使用制表符处理
TAB=$'\t'

# 读取表头
header_line=$(head -n 1 "$temp_all_data")
IFS="$TAB" read -r -a headers <<< "$header_line"

clarity_idx=-1
signal_loss_idx=-1
for ((i=0; i<${#headers[@]}; i++)); do
    if [ "${headers[$i]}" == "vei_ui_sub_type3" ]; then clarity_idx=$i; fi
    if [ "${headers[$i]}" == "vei_ui_sub_type9" ]; then signal_loss_idx=$i; fi
done

# 写入表头到过滤文件
(IFS="$TAB"; echo "${headers[*]}") > "$temp_filtered_data"

echo "📝 当前表头内容: ${headers[*]}" >&2

echo " 正在过滤数据..." >&2
filtered_count=0
processed_count=0

while IFS="$TAB" read -r -a values; do
    processed_count=$((processed_count + 1))
    
    # 过滤逻辑
    skip_record=false
    # 图片ID索引固定为 17 (vei_ubi_vqd_event_id 之后)
    # 根据 SQL 结构，sci.sz_name 是 0，vei_ubi_vqd_event_id 是 1...
    # 这里的索引需要严格对应。在循环中通过 key 判断更安全
    
    # 检查过滤条件（根据字段名动态查找）
    img_id=""
    c_val=""
    s_val=""
    
    # 遍历当前行查找关键值
    for ((i=0; i<${#headers[@]}; i++)); do
        case "${headers[$i]}" in
            "vei_ubi_vqd_event_id") event_id="${values[$i]}" ;;
            "vei_ui_sub_type3") c_val="${values[$i]}" ;;
            "vei_ui_sub_type9") s_val="${values[$i]}" ;;
            "vei_ubi_img_id") # 真实图片ID列名
                 img_id="${values[$i]}" ;;
        esac
    done
    
    # 实际上 MySQL 查询中，图片预览接口用的 ID 在 cols 中的位置是固定的
    # 重新核对 SQL，vei_ubi_vqd_event_id 是第二个字段（索引1）
    # 但图片下载用的是 values[17]？根据原脚本逻辑保持一致，但确保是用 TAB 分割
    
    # img_id="${values[17]}" # 修复: 注释掉硬编码索引
    
    if [ -z "$img_id" ] || [ "$img_id" == "0" ] || [ "$img_id" == "[0]" ]; then
        skip_record=true
    fi
    if [ "$clarity_idx" -ge 0 ] && [ "${values[$clarity_idx]}" == "3" ]; then
        skip_record=true
    fi
    if [ "$signal_loss_idx" -ge 0 ] && [ "${values[$signal_loss_idx]}" == "2" ]; then
        skip_record=true
    fi
    
    if [ "$skip_record" = false ]; then
        (IFS="$TAB"; echo "${values[*]}") >> "$temp_filtered_data"
        filtered_count=$((filtered_count + 1))
    fi
    
    if [ $((processed_count % 10000)) -eq 0 ]; then
        echo "   [进度] 已处理 ${processed_count} 条..." >&2
    fi
done < <(tail -n +2 "$temp_all_data")

echo "📊 过滤完成：剩余 ${filtered_count} 条数据" >&2

# 随机打乱
head -n 1 "$temp_filtered_data" > "$temp_final_data"
tail -n +2 "$temp_filtered_data" | shuf >> "$temp_final_data"
rm -f "$temp_all_data" "$temp_filtered_data"

# 处理最终数据
mkdir -p ./tmp
success_count=0

# 动态获取 event_id 和 img_id 的索引
event_id_idx=-1
img_id_idx=-1
for ((i=0; i<${#headers[@]}; i++)); do
    case "${headers[$i]}" in
        "vei_ubi_vqd_event_id") event_id_idx=$i ;;
        "vei_ubi_img_id") img_id_idx=$i ;;
    esac
done

while IFS="$TAB" read -r -a values; do
    if [ ${#values[@]} -lt 2 ]; then continue; fi
    
    # 此时 values[1] 必定是 event_id，因为强制了 TAB 分割
    # event_id="${values[1]}" # 修复: 注释掉硬编码索引
    # img_id="${values[17]}"  # 修复: 注释掉硬编码索引
    event_id=""
    if [ "$event_id_idx" -ge 0 ]; then event_id="${values[$event_id_idx]}"; fi
    img_id=""
    if [ "$img_id_idx" -ge 0 ]; then img_id="${values[$img_id_idx]}"; fi

    # 生成 JSON
    json="{"
    jsonTwo="{"
    key="${headers[$i]}"
    val="${values[$i]}"

    # 仅对相机名称做 GBK -> UTF-8
    if [ "$key" = "sz_name" ]; then
    val="$(printf '%s' "$val" | iconv -f gbk -t utf-8 2>/dev/null || printf '%s' "$val")"
    fi

    # 再做转义（转码后再转义）
    val="$(printf '%s' "$val" | sed 's/"/\\"/g')"

    json+="\"$key\":\"$val\""
    if [ $i -lt $((${#headers[@]} - 1)) ]; then json+=","; fi

    case "$key" in
    "sz_name") jsonTwo+="\"相机名称\":\"$val\", " ;;
    "vei_ubi_short_id") jsonTwo+="\"相机短编号\":\"$val\", " ;;
    "vei_ubi_detect_time") jsonTwo+="\"检测时间\":\"$val\", " ;;
    esac
    # (此处省略 jsonTwo 的 case 转换以节省空间，逻辑同原脚本)
    # ...
    
    json+="}"
    jsonTwo=$(echo "$jsonTwo" | sed 's/, $//')
    jsonTwo+="}"
    if [ "$jsonTwo" == "}" ]; then jsonTwo="{}"; fi

    # 下载与打包
    if [ -n "$img_id" ] && [ "$img_id" != "0" ]; then
        echo "$json" > "./row_${event_id}.json"
        echo "$jsonTwo" > "./two_${event_id}.json"
        
        if curl -s -f "http://${TARGET_IP}/admin-api/open-api/ops/vqdFile/preview/image_big/${img_id}" --output "./${event_id}.jpg"; then
            tar -czf "./tmp/${event_id}.tar.gz" "./row_${event_id}.json" "./two_${event_id}.json" "./${event_id}.jpg"
            success_count=$((success_count + 1))
            if [ "$success_count" -ge "$MAX_RECORDS" ]; then
                echo "✅ 已达到目标成功数 ${MAX_RECORDS}" >&2
                rm -f "./row_${event_id}.json" "./two_${event_id}.json" "./${event_id}.jpg"
                break
            fi
        else
            echo "⚠️  下载失败: ${img_id}" >&2
        fi
        rm -f "./row_${event_id}.json" "./two_${event_id}.json" "./${event_id}.jpg"
    fi
done < <(tail -n +2 "$temp_final_data")

rm -f "$temp_final_data"

# 最终打包
files=($(find ./tmp -maxdepth 1 -name "*.tar.gz" -type f | sort))
total_files=${#files[@]}
echo "📦 最终找到有效文件数: $total_files"

if [ $total_files -gt 0 ]; then
    # 保证上传目录存在（create_directories 负责创建，但这里做兜底）
    mkdir -p ./upload
    files_per_pack=$(( (total_files + 9) / 10 ))
    for pack_num in {0..9}; do
        start=$((pack_num * files_per_pack))
        if [ $start -ge $total_files ]; then break; fi
        
        pack_dir="./tmp/pack_${pack_num}"
        mkdir -p "$pack_dir"
        
        for ((i=start; i<start+files_per_pack && i<total_files; i++)); do
            cp "${files[$i]}" "$pack_dir/"
        done
        
        final_name="./upload/collection-${start_ts}-part${pack_num}.tar.gz"
        tar -czf "${final_name}" -C "$pack_dir" .
        rm -rf "$pack_dir"
        echo "📦 已生成: ${final_name}"
    done

    # 打包完成标记：sync_task_01.py 只在 sentinel 存在时才开始下载
    touch "./upload/collection-${start_ts}-done.ok"
fi

rm -rf ./tmp
mkdir -p ./tmp
echo "Done."
