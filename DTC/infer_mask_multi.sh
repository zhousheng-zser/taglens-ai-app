#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Input folder
INPUT_DIR="./路口分类/路口"

# Output folder
OUTPUT_DIR="./results"

# Prompt
PROMPT="helmet"

# Checkpoint (empty string = download from HF)
CHECKPOINT="./ckpt/checkpoint.pt"

CATEGORY="complex"
THRESHOLD=0.6
DEVICE="cuda"

MASK_COLOR="0 255 0"
MASK_ALPHA="0.4"

# ============================================================================
# Run
# ============================================================================

PROJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="${PROJ_ROOT}/infer_mask_multi.py"   # 修改为你的实际文件名

EXTRA_ARGS=()
[[ -n "${MASK_COLOR:-}" ]] && EXTRA_ARGS+=(--mask_color ${MASK_COLOR})
[[ -n "${MASK_ALPHA:-}" ]] && EXTRA_ARGS+=(--mask_alpha "${MASK_ALPHA}")

python "${PYTHON_SCRIPT}" \
    --image_path "${INPUT_DIR}" \
    --output_dir "${OUTPUT_DIR}" \
    --prompt "${PROMPT}" \
    --checkpoint_path "${CHECKPOINT}" \
    --category "${CATEGORY}" \
    --detection_threshold "${THRESHOLD}" \
    --device "${DEVICE}" \
    "${EXTRA_ARGS[@]}"