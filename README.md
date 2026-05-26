# TagLens AI

面向交通/安防场景的 **智能图片标签** 与 **事件视频审核** 一体化平台。前端基于 Next.js，后端基于 FastAPI，数据以本地 SQLite 为主，对象存储对接 MinIO，检索侧结合 **Faiss LSH** 与 **BGE 中文向量**；事件分段支持 **FFmpeg 切分**、**RLQ 多模态描述**，图片侧支持 **通义千问 / Gemini / MiMo** 等多模型标注。

---

## 公司部署环境与访问地址

当前服务部署在公司内网服务器（`192.168.1.155`），**用户只需打开前端 9002 端口**，无需直接访问后端 8000。

| 访问场景 | 地址 | 说明 |
|----------|------|------|
| **公司内网** | [http://192.168.1.155:9002/](http://192.168.1.155:9002/) | 局域网内日常使用（推荐） |
| **公司外网** | [http://www.video-md.cn:9002/](http://www.video-md.cn:9002/) | 域名访问，外网或出差时使用 |

**同机服务端口（运维参考，浏览器一般不直连）**

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | `:9002` | 页面、API 代理、媒体播放 |
| 主后端 | `192.168.1.155:8000` 或本机 `127.0.0.1:8000` | 由 Next `/api/backend` 转发 |
| DTC 分割 | `:8010` | DTC_v2 |
| SAM3 分割 | `:8011` | DTC_v1 |

**配置注意**：`backend/.env` 中 `EVENT_MEDIA_HTTP_ORIGIN` 须与**用户实际打开前端的地址**一致（内网填 `http://192.168.1.155:9002`，外网入口填 `http://www.video-md.cn:9002`），否则事件分段 AI 可能拉不到视频。内网、外网若共用同一后端，可按主要使用场景选其一，或按访问来源分别部署/调整。

---

## 目录

- [公司部署环境与访问地址](#公司部署环境与访问地址)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [服务与端口](#服务与端口)
- [数据库设计](#数据库设计)
- [数据导入与维护脚本](#数据导入与维护脚本)
- [功能模块说明](#功能模块说明)
- [后端 API 一览](#后端-api-一览)
- [环境变量](#环境变量)
- [安装与启动](#安装与启动)
- [生产部署（systemd）](#生产部署systemd)
- [媒体与 MinIO 访问](#媒体与-minio-访问)

---

## 系统架构

整体是 **「浏览器 → 前端 → 主后端 → 数据 / 外部能力」** 四层结构。用户只访问前端端口 **9002**；业务 API 与媒体由前端转发或代理，不直接在浏览器里连 8000。

```
┌──────────────────────────────────────────────────────────────┐
│  ① 用户浏览器（Chrome 等）                                    │
│     内网 http://192.168.1.155:9002  外网 http://www.video-md.cn:9002 │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  ② 前端  Next.js  :9002                                       │
│     · 各功能页面（事件查询、图片标签、数据管理…）               │
│     · /api/backend/*  → 把请求转给主后端 :8000                 │
│     · /bucket-taglens/* → 读 MinIO 里的视频、图片              │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  ③ 主后端  FastAPI  :8000                                     │
│     · 登录与用户、事件检索、图片分析、批量任务、数据运维        │
│     · 读写 SQLite，调 MinIO，调外部 AI，编排 DTC 任务           │
└──────┬──────────────┬──────────────┬────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌─────────────┐ ┌──────────┐ ┌────────────────────────────────┐
│ ④ 本地数据   │ │ MinIO    │ │ ⑤ 外部 / 独立服务（按需调用）   │
│ taglens.db  │ │ 视频图片  │ │ · 通义千问 / Gemini / MiMo     │
│ event.db    │ │ 桶名      │ │ · RLQ（事件分段描述）           │
│ manage.db   │ │ bucket-   │ │ · DTC :8010、SAM3 :8011（分割） │
│ + Faiss索引 │ │ taglens   │ │                                 │
└─────────────┘ └──────────┘ └────────────────────────────────┘
```

### 各层做什么

| 层级 | 端口 | 职责（一句话） |
|------|------|----------------|
| 浏览器 | — | 展示页面，发 `fetch`，播放 `/bucket-taglens/...` 视频 |
| 前端 | 9002 | UI + **统一入口**；把 `/api/backend/...` 代理到后端 |
| 主后端 | 8000 | **所有业务逻辑**：鉴权、查库、AI 调用、后台任务 |
| SQLite | 文件 | 三张库：图片标签、事件记录、用户与审核 |
| MinIO | 服务 | 存事件视频、叠框图、导入图片等大文件 |
| 分割服务 | 8010 / 8011 | GPU 推理，仅「DTC 数据获取」页使用 |
| 外部 AI | HTTPS | 图片打标、事件分段描述等，由后端代发请求 |

### 三条主要业务线

**A. 图片标签与搜索**

1. 用户在「图片标签 / 标签搜索」页操作  
2. 前端 → `/api/backend/analyze`、`/search` 等 → 主后端  
3. 后端调 **Qwen / Gemini / MiMo**，结果写入 **taglens.db**，关键词向量进 **Faiss**  
4. 图片文件在 **MinIO** 或本地 `data/local/img`

**B. 事件查询与审核**

1. 用户登录后进入「事件数据查询」  
2. 前端 → `/api/backend/events/search` → 主后端查 **event.db**  
3. 列表里的视频地址多为 `/bucket-taglens/...`，浏览器经 **前端 9002** 播放  
4. 审核状态写在 **manage.db**；单段/批量「智能描述」由后端调 **RLQ**，再写回 event.db 分段字段  

**C. 数据管理与 DTC**

1. 管理员在「数据管理」触发删路径、视频分块、分段描述补齐等  
2. 长任务在后端 **后台跑**，日志通过 NDJSON 流推给前端  
3. 「DTC 数据获取」：主后端登记任务 → 调用 **8010（DTC）或 8011（SAM3）** → 结果落盘 / 可下载 ZIP  

### 前端如何访问后端（记两条即可）

| 你想调什么 | 浏览器里怎么写 | 实际落到 |
|------------|----------------|----------|
| 业务 API（登录、事件、管理…） | `fetch('/api/backend/auth/login')` 等 | Next 转发到 `http://127.0.0.1:8000/auth/login`（由 `BACKEND_URL` 配置） |
| 看视频 / 看图 | `<video src="/bucket-taglens/xxx.mp4">` | Next 或后端从 **MinIO** 读出文件流 |

登录成功后，后端下发 Cookie `taglens_session`，后续请求经 `/api/backend` 代理时会自动带上。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Next.js 15、React 19、TypeScript、Tailwind CSS、Radix UI |
| 后端 | Python 3、FastAPI、Uvicorn |
| 数据库 | SQLite 3（`taglens.db` / `event.db` / `manage.db`） |
| 向量检索 | Faiss LSH、`BAAI/bge-base-zh-v1.5` |
| 对象存储 | MinIO（S3 兼容） |
| 视频处理 | FFmpeg（事件视频分块） |
| 分割推理 | DTC（自研 checkpoint）、SAM3（需 NVIDIA GPU） |
| AI 标注 | Qwen-VL、Gemini、MiMo；事件分段 RLQ |

---

## 目录结构

```
taglens-ai-app/
├── src/                          # Next.js 前端
│   ├── app/                      # 页面与 API 路由
│   │   ├── api/backend/[...path] # 后端统一代理（含 NDJSON 流式）
│   │   ├── bucket-taglens/       # MinIO 媒体代理
│   │   ├── image-tagger/         # 单张图片智能标签
│   │   ├── search/               # 标签语义搜索
│   │   ├── tag-query/            # 标签库 SQL 式查询
│   │   ├── event-query/          # 事件检索与审核
│   │   ├── bulk-import/          # 批量导入（管理员）
│   │   ├── project-sync/         # 项目脚本同步（管理员）
│   │   ├── data-management/      # 数据运维（管理员）
│   │   ├── dtc-data-fetch/       # DTC/SAM3 分割任务（管理员）
│   │   ├── user-management/      # 用户与审核统计（管理员）
│   │   └── login/                # 登录
│   ├── components/               # UI 组件
│   └── lib/auth.ts               # 会话与权限
├── backend/
│   ├── main.py                   # FastAPI 入口（图片分析、批量导入、项目同步等）
│   ├── core/
│   │   ├── database.py           # taglens.db 初始化与 CRUD
│   │   ├── event_database.py     # event.db 事件检索与分段字段
│   │   ├── manage_database.py    # manage.db 用户/审核/会话
│   │   ├── sync_executor.py      # 异步路由中的同步阻塞线程池
│   │   └── minio_storage_client.py
│   ├── routers/
│   │   ├── auth_api.py
│   │   ├── event_api.py
│   │   ├── management_api.py
│   │   └── dtc_api.py
│   ├── services/                 # Faiss、事件分段 AI、视频切分等
│   ├── prompts/                  # 事件分段 RLQ Prompt
│   └── venv/
├── data/
│   ├── taglens.db                # 图片标签主库
│   ├── event.db                  # 事件主库
│   ├── manage.db                 # 用户与审核库
│   ├── backup/                   # event.db 按日备份
│   ├── local/img/                # 批量导入默认扫描目录
│   ├── segment_desc_fill.log     # 分段描述补齐任务日志
│   └── reextract_missing_tags_gemini.log
├── scripts/                      # 导入、同步、补标签等运维脚本
├── DTC/                          # DTC 分割服务与训练代码
├── sam3/                         # SAM3 分割服务
├── deploy/systemd/               # systemd 单元文件
├── start.sh                      # 前端开发启动
├── start-backend.sh              # 后端启动
└── package.json
```

---

## 服务与端口

| 服务 | 默认端口 | 说明 |
|------|----------|------|
| Next.js 前端 | **9002** | `npm run dev` / `taglens-frontend.service` |
| FastAPI 后端 | **8000** | `start-backend.sh` / `taglens-backend.service` |
| DTC 分割（DTC_v2） | **8010** | `DTC/start_dtc_server.sh` |
| SAM3 分割（DTC_v1） | **8011** | `sam3/start_sam3_server.sh` |

一键拉起（含前后端与两个分割服务）：

```bash
sudo systemctl enable --now taglens.target
```

详见 `deploy/SEGMENT_SERVERS.md`。

---

## 数据库设计

应用使用 **三个独立 SQLite 库**，均在首次启动时由 Python 代码自动建表（无需手工执行 SQL 文件）。

### 1. `data/taglens.db` — 图片标签主库

**初始化**：`backend/core/database.py` → `init_database()`

| 表名 | 用途 |
|------|------|
| `images` | 图片元数据：`uuid`、`file_path`、`relative_path`、`camera_id`、`sz_name`、`sz_tag_ref_json` 等 |
| `tags` | 单图标签，类型 `keyword` / `yolo_object` |
| `analysis_results` | AI 分析结果：`description`、`keywords_json`、`qwen_captions_json`、`yolo_objects_json` |
| `keyword_embeddings` | 每个 keyword 的 BGE 768 维向量（BLOB） |
| `projects` | 项目同步配置：脚本路径、定时、`ai_model`、`api_probability` 等 |

**关联能力**：Faiss 索引与 `uuid` 映射；MinIO 路径前缀与 `relative_path` 一致。

---

### 2. `data/event.db` — 事件检索主库

**初始化**：`backend/core/event_database.py` → `init_event_database()`（建索引、字典表、分段字段迁移）

| 表/对象 | 用途 |
|---------|------|
| `event_records` | 事件主表（由导入脚本写入，见下文字段） |
| `event_project_dict` | 项目 ID → 名称字典 |
| `event_type_dict` | 事件类型编码 → 名称、关联问题列表 `questions_list` |

**`event_records` 核心字段**（导入来源：`scripts/import_event_tree_to_db.py`）：

| 字段组 | 代表字段 |
|--------|----------|
| 标识 | `event_id`, `project_id`, `project_name`, `event_type_corrected`, `event_name_corrected` |
| 时间 | `start_time`, `end_time`, `detect_time` |
| 媒体 | `video_path`, `video_url`, `image_paths`（JSON 数组） |
| 车辆 | `vehicle_plate`, `vehicle_type`, `vehicle_color`, `lane_number` … |
| 分段（扩展） | `segment_count`, `segment_paths_json`, `segment_descriptions_json`, `segment_statuses_json` |
| 问答 | `questions_answers_list` |
| 其它 | `source_name`, `process_status`, `debugging_info_json`, `status`, `created_at` … |

**运维特性**：

- 启动时按天备份到 `data/backup/event.YYYY-MM-DD.db`，保留天数由 `DB_BACKUP_KEEP_DAYS` 控制（默认 7）。
- 分段路径须为有效 `.mp4` 相对路径（常位于 `/bucket-taglens/...`）。

---

### 3. `data/manage.db` — 用户与审核库

**初始化**：`backend/core/manage_database.py` → `init_manage_database()`

| 表名 | 用途 |
|------|------|
| `users` | 用户账号，`role` 为 `admin` / `reviewer`；密码 PBKDF2 哈希 |
| `user_time_ranges` | 审核员可访问的事件时间窗口（任务分配） |
| `event_review_records` | 每条事件的审核进度：`status_review_done`、`qa_review_done`、`description_review_done` |

**默认管理员**：库中无 admin 时自动创建用户 `admin`，初始密码常量 `DEFAULT_ADMIN_PASSWORD`（见 `manage_database.py`）。**部署后请立即修改密码。**

**会话**：Cookie 名 `taglens_session`，HMAC 签名，有效期默认 7 天（`MANAGE_SESSION_MAX_AGE`）。

---

## 数据导入与维护脚本

| 脚本 | 作用 |
|------|------|
| `scripts/import_event_tree_to_db.py` | 从 `event_data_tree.txt` 逐行 JSON 导入 `event_records` |
| `scripts/import_event_records_from_tmp_dbs.py` | 从临时 DB 合并导入事件 |
| `scripts/export_event_data_tree.py` | 导出事件目录树 |
| `scripts/download_minio_data.py` / `download_minio_from_search_results.py` | 按条件从 MinIO 拉取数据 |
| `scripts/reextract_missing_tags_gemini.py` | 使用 Gemini 补全缺失标签（数据管理页可触发） |
| `scripts/sync_task_01.py` / `sync_task_02.py` | 同步任务脚本 |
| `scripts/QualityJudgment.sh` | 质量研判 Shell 流水线 |

**示例：导入事件树**

```bash
cd /opt/Traffic-LLM/zser/taglens-ai-app
python scripts/import_event_tree_to_db.py \
  --input event_data_tree.txt \
  --db data/event.db \
  --batch-size 1000
```

---

## 功能模块说明

### 公开 / 通用页面

| 页面路径 | 功能 |
|----------|------|
| `/` | 产品首页，入口导航 |
| `/image-tagger` | 上传单张图片，调用后端 `/analyze` 生成关键词与描述，可保存入库 |
| `/search` | 基于文本的 **语义标签搜索**（BGE + Faiss），支持相似图检索 |
| `/tag-query` | 按 UUID、路径、标签等条件查询已入库图片 |
| `/event-query` | **事件数据查询**（需登录）：多维筛选、表格/卡片视图、视频与分段预览、叠框图、审核状态勾选、分段描述编辑、**单段 AI 智能描述** |
| `/login` | 用户名密码登录，会话 Cookie |
| `/about` | 关于页 |

### 管理员专属页面

| 页面路径 | 功能 |
|----------|------|
| `/bulk-import` | 扫描 `data/local/img` 批量分析入库，支持暂停/恢复/取消与任务日志 |
| `/project-sync` | 管理 `projects` 表：添加/编辑同步脚本、定时执行、选择 Qwen/Gemini 模型与 API 调用概率 |
| `/data-management` | **数据运维中心**（NDJSON 流式日志）：<br>• 按前缀删除 MinIO + 库内关联数据<br>• 配对一致性检查（JPG/JSON 孤立清理）<br>• 全库 Faiss 向量审计<br>• **事件视频分块**（FFmpeg，按条数/事件类型）<br>• **事件分段描述补齐**（RLQ 批量，可关页后台跑，实时日志流）<br>• **缺失标签补齐**（Gemini 子进程脚本） |
| `/dtc-data-fetch` | 上传图集、提交 DTC_v1(SAM3)/DTC_v2(DTC) 分割任务、查看结果与 ZIP |
| `/user-management` | 用户 CRUD、审核员时间段、审核统计与时序图表 |

### 角色与权限

| 角色 | 能力 |
|------|------|
| `reviewer` | 登录、事件查询与审核、本人时间范围内数据 |
| `admin` | 上述全部 + 批量导入、项目同步、数据管理、DTC、用户管理 |

前端通过 `AuthGate` 与 `Header` 导航控制入口；接口层 `require_admin` 校验。

---

## 后端 API 一览

> 浏览器侧统一加前缀 `/api/backend`（Next 代理）。下表为后端真实路径。

### 认证 ` /auth`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录，写 Cookie |
| POST | `/auth/logout` | 登出 |
| GET | `/auth/me` | 当前用户 |
| GET/POST/DELETE | `/auth/users` … | 用户管理（管理员） |
| GET/POST/DELETE | `/auth/users/{id}/time-ranges` … | 审核时间段 |
| GET | `/auth/review-stats` | 审核汇总 |
| GET | `/auth/review-stats/timeseries` | 审核时序 |

### 事件 ` /events`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/events/meta` | 项目/事件类型下拉字典 |
| POST | `/events/search` | 分页检索（含审核状态、分段、问答筛选） |
| POST | `/events/segment-annotations` | 保存分段描述与审核勾选 |
| POST | `/events/segment-ai-description` | **单段** RLQ 智能描述（线程池，不落盘） |
| POST | `/events/delete` | 删除事件记录（管理员） |

### 数据管理 ` /api/management`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/management/delete-path` | 按 MinIO 前缀删除（流式 NDJSON） |
| POST | `/api/management/check-pairs` | JPG/JSON 配对检查 |
| POST | `/api/management/check-features` | Faiss 与库一致性审计 |
| POST | `/api/management/event-video-segment` | 事件视频 FFmpeg 分块 |
| POST | `/api/management/event-segment-desc-fill` | 启动分段描述批量补齐（后台任务） |
| GET | `/api/management/event-segment-desc-fill/status` | 任务是否在跑 |
| GET | `/api/management/event-segment-desc-fill/log-stream` | 日志 NDJSON 流 |
| POST | `/api/management/reextract-tags` | 启动 Gemini 补标签脚本 |
| GET | `/api/management/reextract-tags/status` | 补标签进程状态 |
| GET | `/api/management/reextract-tags/log-stream` | 补标签日志流 |

### DTC ` /dtc`（后端编排，实际推理在 8010/8011）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/dtc/image-sets/upload` | 上传图集 |
| GET/DELETE | `/dtc/image-sets` … | 图集列表与删除 |
| POST | `/dtc/tasks/upload-run` | 上传并运行 |
| POST | `/dtc/tasks/path` | 指定后端路径创建分割任务 |
| GET | `/dtc/tasks/{id}` / `results` / `zip` / `artifact` | 任务状态与产物 |

### 图片与检索（`main.py` 注册）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/analyze` | 单图 AI 分析 |
| POST | `/save-image` | 入库 |
| POST | `/search` | 语义搜索 |
| GET | `/images` | 列表 |
| POST | `/images/delete` | 删除 |
| POST | `/check-similarity` | 相似度检测 |
| POST/GET | `/bulk-import/*` | 批量导入任务控制 |
| GET/POST | `/projects` `/project/*` | 项目同步脚本管理 |
| GET/POST | `/api/minio/download/*` | MinIO 文件下载 |

---

## 环境变量

### 后端 `backend/.env`（示例项，勿提交真实密钥）

```bash
# --- 图片标注 API ---
QWEN_API_KEY=...
GEMINI_API_KEY=...
MIMO_API_KEY=...
QWEN_MODEL=qwen3-vl-plus
GEMINI_MODEL=gemini-3-flash-preview
MIMO_MODEL=mimo-v2.5
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1

# 代理（访问 DashScope / Gemini 时按需）
# HTTP_PROXY=...
# HTTPS_PROXY=...

# --- 事件分段 RLQ ---
EVENT_SEGMENT_AI_BASE_URL=https://.../v1
EVENT_SEGMENT_AI_API_KEY=EMPTY
EVENT_SEGMENT_AI_MODEL=model/RLQ
EVENT_SEGMENT_AI_TIMEOUT_SEC=600
# 媒体 URL 拼接根（与浏览器访问同源，如 http://192.168.x.x:9002）
EVENT_MEDIA_HTTP_ORIGIN=http://127.0.0.1:9002
EVENT_MEDIA_FETCH_TIMEOUT_SEC=120
EVENT_SEGMENT_DESC_FILL_WORKERS=7

# --- MinIO ---
MINIO_ENDPOINT=...
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=bucket-taglens

# --- 服务 ---
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
UVICORN_RELOAD=false          # 生产务必 false
UVICORN_WORKERS=1
SYNC_EXECUTOR_WORKERS=64      # run_blocking 专用线程池
DB_BACKUP_KEEP_DAYS=7
MANAGE_SESSION_SECRET=...     # 生产请修改
```

### 前端 `.env.local`（可选）

```bash
BACKEND_URL=http://127.0.0.1:8000
DTC_V2_SERVER_URL=http://127.0.0.1:8010
DTC_V1_SERVER_URL=http://127.0.0.1:8011
NEXT_PUBLIC_DTC_V2_SERVER_URL=http://127.0.0.1:8010
NEXT_PUBLIC_DTC_V1_SERVER_URL=http://127.0.0.1:8011
```

---

## 安装与启动

### 依赖准备

- Node.js 20+、npm
- Python 3.10+、venv（`backend/venv`）
- FFmpeg（事件分块）
- 可选：NVIDIA GPU + CUDA（DTC/SAM3）
- MinIO 服务（媒体存储）

### 后端

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt   # 若项目提供
cp .env.example .env              # 自行配置密钥
cd ..
./start-backend.sh
```

`start-backend.sh` 会：初始化 `taglens.db`、释放 8000 端口、默认 **`UVICORN_RELOAD=false`** 启动。

### 前端

```bash
npm install
# 可选：echo "BACKEND_URL=http://127.0.0.1:8000" > .env.local
./start.sh          # 或 npm run dev  →  http://localhost:9002
```

### 分割服务（可选）

```bash
./deploy/start_segment_servers.sh
curl -s http://127.0.0.1:8010/health
curl -s http://127.0.0.1:8011/health
```

---

## 生产部署（systemd）

```bash
cd deploy/systemd
sudo ./install.sh
sudo systemctl enable --now taglens.target
systemctl status taglens.target taglens-backend.service taglens-frontend.service \
  taglens-dtc-v1.service taglens-dtc-v2.service
```

| 单元 | 说明 |
|------|------|
| `taglens-backend.service` | 执行 `start-backend.sh` |
| `taglens-frontend.service` | Next 生产或 dev（见单元内 ExecStart） |
| `taglens-dtc-v1.service` | SAM3 :8011 |
| `taglens-dtc-v2.service` | DTC :8010 |
| `taglens.target` | 聚合启动上述服务 |

**注意**：单元文件内路径默认为 `/opt/Traffic-LLM/zser/taglens-ai-app`，若仓库路径不同需先修改 `.service` 再 `install.sh`。

---

## 媒体与 MinIO 访问

- 库内常存相对路径：`/bucket-taglens/<prefix>/xxx.mp4`。
- 浏览器通过 **`http://<前端主机>:9002/bucket-taglens/...`** 访问（Next `bucket-taglens` 路由或后端代理）。
- 事件分段 AI 拉流时，后端用 `EVENT_MEDIA_HTTP_ORIGIN` 将相对路径拼成可 GET 的绝对 URL；**应与用户浏览器访问的前端 Origin 一致**（内网 `http://192.168.1.155:9002`，外网 `http://www.video-md.cn:9002`）。
- 大文件/流式接口代理超时默认 **600 秒**（`src/app/api/backend/[...path]/route.ts`）。

---

## 事件分段 AI 说明

| 场景 | 机制 |
|------|------|
| 事件查询页 · 单段按钮 | `POST /events/segment-ai-description`，15 线程池，HTTP 拉视频/叠框图，调用 RLQ，**不写库**（前端确认后再保存） |
| 数据管理 · 批量补齐 | `POST /api/management/event-segment-desc-fill`，筛选：有效 mp4、描述为空、事件类型可选；**N 路并行**（`EVENT_SEGMENT_DESC_FILL_WORKERS`）；写库前 per-event 锁 + 快照防覆盖；日志 `data/segment_desc_fill.log` |

Prompt 定义：`backend/prompts/event_segment_prompt.py`（与 `qianwen_test/test.py` 对齐）。

---

## 相关文档

- 分割服务接口与健康检查：`deploy/SEGMENT_SERVERS.md`
- systemd 快捷命令：项目根目录 `shell.txt`

---

## 许可证与贡献

内部项目，部署前请妥善保管 API Key 与 `manage.db` 会话密钥，勿将 `backend/.env` 提交至公开仓库。
