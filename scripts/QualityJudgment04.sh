#!/bin/bash
# 浦东高位停车服务器：通过 testmvp 抓图并打包，供 sync_task_04.py 下载处理
# 纯 bash 实现（远端 MVP 机无 python3）

PROJECT_NAME="$1"
MVP_IP="$2"

# ==================== 硬编码 MVP 参数（可按需修改）====================
MVP_BIN="/opt/MVP64/Tools/testmvp"
MVP_TOOLS_DIR="/opt/MVP64/Tools"
MVP_USER="1"
MVP_PWD="0"
THREAD=4
STREAM_TIMEOUT=15
THUMBNAIL_SIZE=320
CLEANUP_RETENTION_DAYS=1

LOG_FILE="./quality_execution_04.log"
PROJECT_ROOT="/root/CollectionIMGJudgment"
CAMERAS_RAW_FILE="${PROJECT_ROOT}/cameras_querycameras.txt"
CAMERAS_META_FILE="${PROJECT_ROOT}/cameras_meta.tsv"
CAMERAS_DETAIL_FILE="${PROJECT_ROOT}/camera_details.txt"

# ==========================================
# 工具函数
# ==========================================

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\r'/\\r}"
    s="${s//$'\t'/\\t}"
    printf '%s' "$s"
}

trim_spaces() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

parse_keyword_tags() {
    local keyword="$1"
    local _tag1 _tag2
    _tag1=$(trim_spaces "$(echo "$keyword" | cut -d'|' -f1)")
    _tag2=$(trim_spaces "$(echo "$keyword" | cut -d'|' -f2)")
    # 浦东高位停车业态仅两级；keyword 第三段为相机名冗余，不使用
    TAG1="$_tag1"
    TAG2="$_tag2"
    TAG3=""
}

# 解析 testmvp -querycameras 输出，逻辑与 backend parse_testmvp_querycameras_output 保持一致
parse_querycameras_output() {
    local raw_file="$1"
    local meta_file="$2"
    local detail_file="$3"
    local count=0
    local line camid name keyword

    : > "$meta_file"
    : > "$detail_file"

    while IFS= read -r line || [ -n "$line" ]; do
        line=$(trim_spaces "$line")
        [[ "$line" != *"camera id:"* ]] && continue

        camid=$(echo "$line" | sed -n 's/.*camera id:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
        [ -z "$camid" ] && continue

        name=$(echo "$line" | sed -n 's/.*name:[[:space:]]*\([^,]*\).*/\1/p')
        name=$(trim_spaces "$name")
        keyword=$(echo "$line" | sed -n 's/.*keyword:[[:space:]]*\(.*\)/\1/p')
        keyword=$(trim_spaces "$keyword")

        parse_keyword_tags "$keyword"
        printf '%s\t%s\t%s\t%s\t%s\n' "$camid" "$name" "$TAG1" "$TAG2" "$TAG3" >> "$meta_file"
        printf '%s\n' "$line" >> "$detail_file"
        count=$((count + 1))
    done < "$raw_file"

    if [ "$count" -eq 0 ]; then
        return 1
    fi
    echo "$count"
    return 0
}

write_camera_json_files() {
    local work_dir="$1"
    local event_id="$2"
    local camid="$3"
    local cam_name="$4"
    local tag1="$5"
    local tag2="$6"
    local tag3="$7"
    local grab_datetime="$8"
    local row_json="${work_dir}/row_${event_id}.json"
    local two_json="${work_dir}/two_${event_id}.json"

    printf '{"sz_name":"%s","szTagRef1":"%s","szTagRef2":"%s","szTagRef3":"%s"}' \
        "$(json_escape "$cam_name")" \
        "$(json_escape "$tag1")" \
        "$(json_escape "$tag2")" \
        "$(json_escape "$tag3")" > "$row_json"

    printf '{"相机短编号":"%s","相机名称":"%s","检测时间":"%s"}' \
        "$(json_escape "$camid")" \
        "$(json_escape "$cam_name")" \
        "$(json_escape "$grab_datetime")" > "$two_json"
}

daily_cleanup() {
    log_msg "开始每日清理（保留 ${CLEANUP_RETENTION_DAYS} 天内 upload 文件）..."
    mkdir -p "${PROJECT_ROOT}/upload"
    find "${PROJECT_ROOT}/upload" -maxdepth 1 -type f \( -name 'collection-*.tar.gz' -o -name 'collection-*-done.ok' \) -mtime +${CLEANUP_RETENTION_DAYS} -delete 2>/dev/null || true
    rm -rf "${PROJECT_ROOT}/snapshot" "${PROJECT_ROOT}/snapshot-"*.tgz 2>/dev/null || true
    rm -f "${MVP_TOOLS_DIR}/camid.txt" "${CAMERAS_RAW_FILE}" "${CAMERAS_META_FILE}" "${CAMERAS_DETAIL_FILE}" 2>/dev/null || true
    log_msg "每日清理完成"
}

fetch_camera_list() {
    log_msg "正在获取相机列表: ${MVP_BIN} -ip ${MVP_IP} -user ${MVP_USER} -pwd ${MVP_PWD} -querycameras"
    cd "${MVP_TOOLS_DIR}" || exit 1
    "${MVP_BIN}" -ip "${MVP_IP}" -user "${MVP_USER}" -pwd "${MVP_PWD}" -querycameras > "${CAMERAS_RAW_FILE}" 2>&1
    if [ ! -s "${CAMERAS_RAW_FILE}" ]; then
        log_msg "❌ querycameras 无输出，终止"
        exit 1
    fi

    local total
    total=$(parse_querycameras_output "${CAMERAS_RAW_FILE}" "${CAMERAS_META_FILE}" "${CAMERAS_DETAIL_FILE}")
    if [ $? -ne 0 ] || [ -z "${total}" ] || [ "${total}" -eq 0 ]; then
        log_msg "❌ 未能解析相机列表，终止"
        exit 1
    fi
    log_msg "📊 相机总数: ${total}"
}

multi_thread_grab_and_pack() {
    local meta_file="${CAMERAS_META_FILE}"
    local work_dir="${PROJECT_ROOT}/grab_work"
    local pack_tmp="${PROJECT_ROOT}/tmp"

    rm -rf "${work_dir}"
    mkdir -p "${work_dir}" "${pack_tmp}"
    rm -f "${pack_tmp}"/*.tar.gz 2>/dev/null || true

    local tmp_fifo="/tmp/$$.fifo"
    mkfifo "${tmp_fifo}"
    exec 6<>"${tmp_fifo}"
    rm -f "${tmp_fifo}"

    local i
    for ((i=0; i<THREAD; i++)); do
        echo >&6
    done

    local total_cam_count
    total_cam_count=$(wc -l < "${meta_file}")
    log_msg "开始多线程抓图，线程数=${THREAD}，相机数=${total_cam_count}"

    local datetime_start
    datetime_start=$(date +"%Y-%m-%d %H:%M:%S")

    for ((i=1; i<=total_cam_count; i++)); do
        read -u6
        {
            local meta_line camid cam_name tag1 tag2 tag3 event_id grab_datetime image_path
            meta_line=$(sed -n "${i}p" "${meta_file}")
            camid=$(echo "$meta_line" | cut -f1)
            cam_name=$(echo "$meta_line" | cut -f2)
            tag1=$(echo "$meta_line" | cut -f3)
            tag2=$(echo "$meta_line" | cut -f4)
            tag3=$(echo "$meta_line" | cut -f5)

            if [[ "${camid}" =~ ^[0-9]+$ ]] && [ "${camid}" -gt 0 ]; then
                event_id="${camid}"
                grab_datetime=$(date +%Y%m%d-%H%M%S)
                image_path="${work_dir}/${event_id}.jpg"

                cd "${MVP_TOOLS_DIR}" || true
                "${MVP_BIN}" -ip "${MVP_IP}" -user "${MVP_USER}" -pwd "${MVP_PWD}" \
                    -camid "${camid}" -hide -startlive -timeout "${STREAM_TIMEOUT}" \
                    -snapshot "${image_path}" >/dev/null 2>&1
                local testmvp_return=$?

                if [ "${testmvp_return}" -eq 0 ] && [ -f "${image_path}" ]; then
                    local row_json="${work_dir}/row_${event_id}.json"
                    local two_json="${work_dir}/two_${event_id}.json"
                    local sub_tar="${pack_tmp}/${event_id}.tar.gz"

                    write_camera_json_files \
                        "${work_dir}" "${event_id}" "${camid}" "${cam_name}" \
                        "${tag1}" "${tag2}" "${tag3}" "${grab_datetime}"

                    tar -czf "${sub_tar}" -C "${work_dir}" \
                        "row_${event_id}.json" "two_${event_id}.json" "${event_id}.jpg"

                    rm -f "${row_json}" "${two_json}" "${image_path}"
                fi
            fi
            echo >&6
        } &
    done
    wait
    exec 6>&-

    local datetime_end cost_time online_count
    datetime_end=$(date +"%Y-%m-%d %H:%M:%S")
    cost_time=$(( $(date -d "${datetime_end}" +%s) - $(date -d "${datetime_start}" +%s) ))
    online_count=$(find "${pack_tmp}" -maxdepth 1 -name '*.tar.gz' -type f | wc -l)
    log_msg "抓图完成: total=${total_cam_count}, success=${online_count}, cost=${cost_time}s"

    rm -rf "${work_dir}"
}

final_pack_upload() {
    local start_ts
    start_ts=$(date -d "$(date +%F) 00:00:00" +%s)
    start_ts="${start_ts}000"

    local files=()
    while IFS= read -r f; do
        files+=("$f")
    done < <(find ./tmp -maxdepth 1 -name "*.tar.gz" -type f | sort)

    local total_files=${#files[@]}
    log_msg "📦 最终有效子包数: ${total_files}"

    if [ "${total_files}" -eq 0 ]; then
        log_msg "⚠️ 无有效抓图结果，跳过最终打包"
        return
    fi

    mkdir -p ./upload
    local files_per_pack=$(( (total_files + 9) / 10 ))
    local pack_num start i pack_dir final_name

    for pack_num in {0..9}; do
        start=$((pack_num * files_per_pack))
        if [ "${start}" -ge "${total_files}" ]; then
            break
        fi

        pack_dir="./tmp/pack_${pack_num}"
        mkdir -p "${pack_dir}"

        for ((i=start; i<start+files_per_pack && i<total_files; i++)); do
            cp "${files[$i]}" "${pack_dir}/"
        done

        final_name="./upload/collection-${start_ts}-part${pack_num}.tar.gz"
        tar -czf "${final_name}" -C "${pack_dir}" .
        rm -rf "${pack_dir}"
        log_msg "📦 已生成: ${final_name}"
    done

    touch "./upload/collection-${start_ts}-done.ok"
    log_msg "✅ 打包完成标记: collection-${start_ts}-done.ok"
}

# ==========================================
# 主逻辑
# ==========================================

cd "${PROJECT_ROOT}" || exit 1
mkdir -p "${PROJECT_ROOT}/tmp" "${PROJECT_ROOT}/upload"

log_msg "Running QualityJudgment04 for project: ${PROJECT_NAME}, MVP_IP: ${MVP_IP}"

daily_cleanup
fetch_camera_list
multi_thread_grab_and_pack
final_pack_upload

rm -rf ./tmp
mkdir -p ./tmp
log_msg "Done."
