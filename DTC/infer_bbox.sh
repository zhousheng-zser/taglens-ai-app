
IMAGE="./路口分类/路口/25343_93.jpg"
PROMPT="non-motorized vehicle lane"
CHECKPOINT="./ckpt/checkpoint.pt"

OUTPUT="./result.png"
CATEGORY="complex"            # concept | simple | complex
THRESHOLD=0.5
DEVICE="cuda"

PROJ_ROOT="$(cd "$(dirname "$0")" && pwd)"

python "${PROJ_ROOT}/infer_bbox.py" \
    --image_path "${IMAGE}" \
    --prompt "${PROMPT}" \
    --checkpoint_path "${CHECKPOINT}" \
    --output_path "${OUTPUT}" \
    --category "${CATEGORY}" \
    --detection_threshold "${THRESHOLD}" \
    --device "${DEVICE}"
#    --mask_color ${MASK_COLOR} \
#    --mask_alpha "${MASK_ALPHA}" \
