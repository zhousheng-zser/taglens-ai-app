# Jina Reranker 迁移与能力分析

> 阶段交付：已迁移权重与参考脚本；**本阶段未改** TagLens 搜索业务代码。

## 1. 迁移校验

| 项 | 结果 |
|----|------|
| 本地路径 | `/opt/Traffic-LLM/zser/taglens-ai-app/jina-clip-v2/reranker`（独立子目录，与 CLIP 的 `config.json` 分离） |
| 目录体积 | ~4.6G |
| `model.safetensors` | 远端与本地均为 **4889523546** 字节（一致） |
| 身份 | `_name_or_path: jinaai/jina-reranker-v3`；README 称 **jina-reranker-m0**；架构 `JinaVLForRanking`（Qwen2-VL / ~2.4B） |
| 关键文件 | `config.json`、`modules.json`、`modeling.py`、`custom_transformer.py`、`tokenizer.json` 均在 |
| 参考脚本 | `scripts/ref_t2i_query/run_reranker.py`、`api.py`、`api_rerank_refs.txt` |

## 2. 源站两阶段检索（正确用法）

源站 [`run_reranker.py`](../scripts/ref_t2i_query/run_reranker.py) / API 片段：

```text
查询(文本或图)
  → jina-clip-v2 编码为向量
  → 与图索引做余弦粗排 TopK（如 coarse_k=100）
  → reranker.compute_score(query, candidate_image) 精排
  → 按 rerank 分取 final_k
```

要点：

- **CLIP** 负责 text/image → 向量，以及全库（或大库）向量召回。
- **Reranker** 只对粗排候选做 `(query, document)` 相关性打分；`doc_type`/`query_type` 可为 `text`/`image`。
- Reranker **没有** 可用的 embedding 输出接口；不能单独替代「文本转向量 + 全库对比」。

## 3. 与本机 TagLens「描述向量」链路对照

| 维度 | 源站 t2i-query | TagLens 描述向量搜索 |
|------|----------------|----------------------|
| 召回标的 | **原图** CLIP 向量索引 | `description_embeddings`（对 **分析描述文本** 的 Jina 文本向量） |
| 查询编码 | CLIP text / image | Jina CLIP `encode_text`（`jina_embedding_service`） |
| 粗排 | 余弦 TopK | 内存缓存余弦（`description_search_cache`） |
| 精排 | `compute_score` 对 **图路径** | **无** |
| 模型常驻 | CLIP + 可选 Reranker | 仅 Jina CLIP（描述模式） |

因此：现网描述搜索只有「粗排等价物」，且标的是 **description 文本**，不是源站的 **图侧索引**。效果差若存在，可能来自（1）缺精排；（2）检索对象是描述而非像素；（3）阈值/阈值与源站不一致——不能简单归因为「缺 reranker」一项。

## 4. 关键问题结论

| 点 | 结论 |
|----|------|
| 能否替代 text→vector | **不能**；是 ranking head（VLM + MLP），非 embedding 模型 |
| 与现网效果差的关系 | 源站 = CLIP 粗排 + Rerank；本机描述模式 ≈ 仅粗排，且对 **文本描述** 而非图 |
| 若要接 TagLens | 更合理：现有向量搜 TopN 后，对候选 `description`（`query_type=text, doc_type=text`）或原图（`doc_type=image`）调用 `compute_score`；做成开关，勿替换编码链路 |
| 风险 | 权重 ~5GB；2.4B VLM 显存与延迟；`trust_remote_code`；纯文本 description 场景下多模态优势有限；与 CLIP 双模型常驻需估 GPU |

## 5. 建议（是否值得改搜索）

**暂不建议立刻改线上搜索逻辑。**

理由：

1. 接入成本高（显存、延迟、进程常驻或按需加载），需先在固定 TopN（如 50–100）上做离线 A/B。
2. 若主要痛点是「文搜图不准」，更应优先评估：**图侧 CLIP 索引**（对齐源站粗排标的），再叠加 rerank；仅在 description 文本上精排，收益可能有限。
3. 权重与参考脚本已就位，确认方案后再在描述搜索返回前加可选 `use_reranker` 即可。

**后续（需你确认后再做）：**

- 方案 A：描述向量 TopN → 对 `description` 文本 rerank（改动小，对齐当前库表）。
- 方案 B：建图侧 CLIP 索引 → 粗排 + 对原图 rerank（对齐源站，工程量大）。
- 方案 C：不接 rerank，先调阈值/回填质量/查询改写。

## 6. 本阶段明确未做

- 未改 `backend/main.py` / `description_search_cache.py` 等搜索逻辑  
- 未回填新表、未换 embedding 模型  
- 未迁移整个 `t2i-query`（含其它大模型与 datasets）
