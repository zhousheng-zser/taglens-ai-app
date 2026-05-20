#!/usr/bin/env bash
set -euo pipefail

# Input image path
IMAGE="./路口分类/路口/25343_93.jpg"

PROMPT="white arrow and black background on the road"

CHECKPOINT="./ckpt/checkpoint.pt"

# Output path for the overlaid visualization (optional, comment out if not needed)
OUTPUT="./result.png"

# Prompt category: concept | simple | complexs
CATEGORY="simple"

THRESHOLD=0.5

# Device: cuda | cpu
DEVICE="cuda"

# Mask overlay color (R G B) — uncomment below to customize
MASK_COLOR="0 255 0"

# Mask overlay alpha (0.0 ~ 1.0) — uncomment below to customize
MASK_ALPHA="0.4"

# ============================================================================
# Resolve project root and run
# ============================================================================

PROJ_ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="${PROJ_ROOT}/infer_mask.py"  

# Build optional args
EXTRA_ARGS=()
if [[ -n "${OUTPUT:-}" ]]; then
    EXTRA_ARGS+=(--output_path "${OUTPUT}")
fi
if [[ -n "${MASK_COLOR:-}" ]]; then
    EXTRA_ARGS+=(--mask_color ${MASK_COLOR})
fi
if [[ -n "${MASK_ALPHA:-}" ]]; then
    EXTRA_ARGS+=(--mask_alpha "${MASK_ALPHA}")
fi

python "${PYTHON_SCRIPT}" \
    --image_path "${IMAGE}" \
    --prompt "${PROMPT}" \
    --checkpoint_path "${CHECKPOINT}" \
    --category "${CATEGORY}" \
    --detection_threshold "${THRESHOLD}" \
    --device "${DEVICE}" \
    "${EXTRA_ARGS[@]}"
