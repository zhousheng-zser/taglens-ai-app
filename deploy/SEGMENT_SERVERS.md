# DTC / SAM3 本地分割服务

两个独立 HTTP 服务，**启动时加载模型**，接口前缀不同，便于前端后续按算法切换。

| 算法 | 端口 | 健康检查 | 创建任务（后端路径） |
|------|------|----------|----------------------|
| DTC  | 8010 | `GET /health` | `POST /dtc/tasks/path` |
| SAM3 | 8011 | `GET /health` | `POST /sam3/tasks/path` |

## 启动

```bash
# 仅 DTC
/opt/Traffic-LLM/zser/taglens-ai-app/DTC/start_dtc_server.sh

# 仅 SAM3
/opt/Traffic-LLM/zser/taglens-ai-app/sam3/start_sam3_server.sh

# 两个一起（后台）
/opt/Traffic-LLM/zser/taglens-ai-app/deploy/start_segment_servers.sh
```

## 测试示例

### 健康检查

```bash
curl -s http://127.0.0.1:8010/health | jq
curl -s http://127.0.0.1:8011/health | jq
```

### 后端路径模式（异步任务）

```bash
# DTC
curl -s -X POST http://127.0.0.1:8010/dtc/tasks/path \
  -H 'Content-Type: application/json' \
  -d '{"backendPath":"/opt/Traffic-LLM/zser/taglens-ai-app/data/dtc/images/1","prompt":"helmet","threshold":0.5,"category":"simple","adapter_scale":0.5}'

# SAM3
curl -s -X POST http://127.0.0.1:8011/sam3/tasks/path \
  -H 'Content-Type: application/json' \
  -d '{"backendPath":"/opt/Traffic-LLM/zser/taglens-ai-app/data/dtc/images/1","prompt":"helmet","threshold":0.5}'
```

### 查询任务与结果

```bash
TASK_ID=xxxxxxxxxxxx   # 上一步返回的 task_id

curl -s http://127.0.0.1:8010/dtc/tasks/${TASK_ID}/results | jq '.task.status, .results | length'
curl -s http://127.0.0.1:8011/sam3/tasks/${TASK_ID}/results | jq '.task.status, .results | length'
```

### 同步推理（少量图片，直接返回 results）

```bash
curl -s -X POST http://127.0.0.1:8010/dtc/segment/sync \
  -H 'Content-Type: application/json' \
  -d '{"backendPath":"/path/to/images","prompt":"helmet","threshold":0.5}'
```

### 传图推理（无需 backendPath，响应内联 JSON + comparison）

**multipart 上传（推荐）**

```bash
# DTC_v2 (8010)
curl -s -X POST http://127.0.0.1:8010/dtc/segment/images \
  -F 'files=@/path/to/a.jpg' \
  -F 'prompt=helmet' \
  -F 'threshold=0.5' \
  -F 'includeComparison=true' \
  -F 'category=simple' \
  -F 'adapter_scale=0.5'

# 不要 comparison 图时
curl -s -X POST http://127.0.0.1:8010/dtc/segment/images \
  -F 'files=@/path/to/a.jpg' \
  -F 'prompt=helmet' \
  -F 'threshold=0.5' \
  -F 'includeComparison=false'

# DTC_v1 / SAM3 (8011)
curl -s -X POST http://127.0.0.1:8011/sam3/segment/images \
  -F 'files=@/path/to/a.jpg' \
  -F 'prompt=helmet' \
  -F 'threshold=0.5' \
  -F 'includeComparison=true'
```

**JSON + base64**

```bash
IMG_B64=$(base64 -w0 /path/to/a.jpg)
curl -s -X POST http://127.0.0.1:8010/dtc/segment/images/json \
  -H 'Content-Type: application/json' \
  -d "{\"images\":[{\"name\":\"a.jpg\",\"data\":\"$IMG_B64\"}],\"prompt\":\"helmet\",\"threshold\":0.5,\"includeComparison\":true}"
```

响应 `results[]` 每项字段：

| 字段 | 说明 |
|------|------|
| `sourceName` | 文件名（无扩展名） |
| `imageName` | 原始文件名 |
| `numMasks` | 检测到的 mask 数量 |
| `json` | LabelMe 格式标注（含 `shapes`、`imageData` 等） |
| `comparisonImageBase64` | 三图对比 PNG（仅 `includeComparison=true`） |
| `comparisonMimeType` | `image/png` |
| `error` | 单张失败时的错误信息 |

## 环境

- **DTC**：`DTC/dtc_dep` 虚拟环境 + `DTC/ckpt/checkpoint.pt`  
  - 默认 `category=simple`，`adapter_scale=0.5`（与 `infer_mask.sh` / `infer_mask.py` 一致）  
  - 可通过请求体或环境变量 `DTC_CATEGORY`、`DTC_ADAPTER_SCALE` 覆盖
- **SAM3**：`backend/venv` + `sam3/sam3_pt`
- 均需 **NVIDIA GPU**

任务数据：

- DTC：`data/dtc_tasks/tasks.json`
- SAM3：`data/sam3_tasks/tasks.json`

## 前端「DTC数据获取」页环境变量

Next.js Server Action 与 artifact 代理通过以下变量连接分割服务（未设置时使用 `127.0.0.1` 默认端口）：

| 变量 | 用途 | 默认 |
|------|------|------|
| `DTC_V2_SERVER_URL` | Server Action → DTC（DTC_v2） | `http://127.0.0.1:8010` |
| `DTC_V1_SERVER_URL` | Server Action → SAM3（DTC_v1） | `http://127.0.0.1:8011` |
| `NEXT_PUBLIC_DTC_V2_SERVER_URL` | 浏览器 ZIP 下载（DTC_v2） | 同主机 `:8010` |
| `NEXT_PUBLIC_DTC_V1_SERVER_URL` | 浏览器 ZIP 下载（DTC_v1） | 同主机 `:8011` |

页面算法映射：**DTC_v1** = SAM3（8011 `/sam3/*`），**DTC_v2** = DTC（8010 `/dtc/*`）。DTC_v2 额外支持 `category`、`adapter_scale` 参数。
