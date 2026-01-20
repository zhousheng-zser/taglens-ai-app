#!/bin/bash

PROJECT_NAME=$1
TARGET_IP=$2
TARGET_DB_PORT=$3


sqlSelectFunc() {
    local beginTime=$1
    local endTime=$2

    alias="vei"   # 这里设置表别名
    db="web-op"
    tbl="tbl_vqd_event_info"

    cols=$(mysql -h ${TARGET_IP} -P ${TARGET_DB_PORT} -u webadmin -p3edcVFR$ web-op -B -N -e "$(cat <<SQL
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



    mysql -h ${TARGET_IP} -P ${TARGET_DB_PORT} -u webadmin -p3edcVFR$ -B -e "
USE web-op;

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


while true;
do

    now=$(date +%s)
    end_ts="$(( now - 48*3600 ))"
    start_ts="$(( end_ts - 60 ))"

    end_ts="${end_ts}000"
    start_ts="${start_ts}000"


    sqlSelectFunc ${start_ts} ${end_ts} | {

        IFS=$'\t' read -r -a headers
        while IFS=$'\t' read -r -a values; do
	    json="{"
	    jsonTwo="{"

	    for i in "${!headers[@]}"; do
		key=${headers[$i]}
      		val=${values[$i]}


                val=$(echo -n "$val" | iconv -f GBK -t UTF-8)

      		val=$(echo "$val" | sed 's/"/\\"/g')
                
	        if [ "$key" == "vei_ui_result_status" ]; then
                    val="NULL"
                fi	

		json+="\"$key\":\"$val\""
	        if [[ $i -lt $((${#headers[@]} - 1)) ]]; then
        	    json+=","
		fi

		if [ "$key" == "sz_name" ]; then
	            jsonTwo+="\"相机名称\":\"$val\", "
      		fi

		if [ "$key" == "vei_ubi_short_id" ]; then
                    jsonTwo+="\"相机短编号\":\"$val\", "
                fi

		if [ "$key" == "vei_ubi_detect_time" ]; then
                    jsonTwo+="\"检测时间\":\"$val\", "
                fi

		if [ "$key" == "vei_ui_sub_type1" ]; then
		    innerKey="亮度异常"
                    case "$val" in
                	1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                	2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                	3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
			4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
			5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
			6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
              	    esac
		fi

		if [ "$key" == "vei_ui_sub_type2" ]; then
		    innerKey="对比度异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type3" ]; then
                    innerKey="清晰度异常"
		    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac

		fi

		if [ "$key" == "vei_ui_sub_type4" ]; then
                    innerKey="噪声异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
		fi

		if [ "$key" == "vei_ui_sub_type5" ]; then
                    innerKey="条纹异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type6" ]; then
                    innerKey="图像偏色"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type7" ]; then
                    innerKey="画面冻结"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type8" ]; then
                    innerKey="画面抖动"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type9" ]; then
                    innerKey="信号丢失"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type10" ]; then
                    innerKey="图像遮挡"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type11" ]; then
                    innerKey="时钟异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type12" ]; then
                    innerKey="转动异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type13" ]; then
                    innerKey="缩放异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type14" ]; then
                    innerKey="场景异常"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi

		if [ "$key" == "vei_ui_sub_type15" ]; then
                    innerKey="雨雪遮挡"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi


		if [ "$key" == "vei_ui_sub_type16" ]; then
                    innerKey="录像状态"
                    case "$val" in
                        1) jsonTwo+="\"${innerKey}\":\"正常\", " ;;
                        2) jsonTwo+="\"${innerKey}\":\"异常\", "   ;;
                        3) jsonTwo+="\"${innerKey}\":\"未诊断\", "   ;;
                        4) jsonTwo+="\"${innerKey}\":\"未启用\", "   ;;
                        5) jsonTwo+="\"${innerKey}\":\"异常已修复\", "   ;;
                        6) jsonTwo+="\"${innerKey}\":\"异常未修复\", "   ;;
                    esac
                fi



		if [ "$key" == "vei_ui_stream_id" ]; then
		    jsonTwo+="\"码流序号\":\"$val\", "
		fi


		if [ "$key" == "vei_ui_get_stream_cost" ]; then
                    jsonTwo+="\"拉流耗时\":\"$val\", "
                fi


		if [ "$key" == "vei_ui_task_frame_size" ]; then
                    jsonTwo+="\"帧率\":\"$val\", "
                fi

		if [ "$key" == "vei_ud_code_rate" ]; then
                    jsonTwo+="\"码率\":\"$val\", "
                fi

		if [ "$key" == "vei_ui_gop" ]; then
                    jsonTwo+="\"GOP\":\"$val\", "
                fi

		if [ "$key" == "vei_sz_resolution" ]; then
                    jsonTwo+="\"分辨率\":\"$val\", "
                fi

		if [ "$key" == "vei_sz_server_ip" ]; then
                    jsonTwo+="\"服务器地址\":\"$val\", "
                fi

		if [ "$key" == "vei_sz_error_text" ]; then
                    jsonTwo+="\"错误描述\":\"$val\", "
                fi


		if [ "$key" == "vei_ui_encode_format" ]; then
                     case "$val" in
                        0) jsonTwo+="\"编码格式\":\"H264\", " ;;
                        1) jsonTwo+="\"编码格式\":\"H265\", "   ;;
                    esac
		fi





	
		

		
	    done

	    json+="}"
	    jsonTwo=${jsonTwo::-2}
	    jsonTwo+="}"



	    echo "$json"  > "./row_${values[1]}.json"
    	    echo "$jsonTwo" > "./two_${values[1]}.json"

	    if [ "${values[17]}" != "0" ]; then
	    	curl http://${TARGET_IP}/admin-api/open-api/ops/vqdFile/preview/image_big/${values[17]} --output ./${values[1]}.jpg
		tar -czvf ./tmp/${values[1]}.tar.gz ./row_${values[1]}.json ./two_${values[1]}.json ./${values[1]}.jpg
	    fi

	    rm -f ./row_${values[1]}.json
	    rm -f ./two_${values[1]}.json
	    rm -f ./${values[1]}.jpg

	done


    }


    tar -czvf ./upload/collection-${start_ts}.tar.gz -C ./tmp .
    rm -rf ./tmp/*

    filenum=$(ls -l ./upload/ | grep "^-" | wc -l)


    while true;
    do
	if [ ${filenum} -gt 10 ]; then
	    sleep 1000
        else
            break
        fi
     done


     sleep 600




done
