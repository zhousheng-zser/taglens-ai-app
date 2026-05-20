#!/usr/bin/env python3

import argparse
import os
import sys

import numpy as np
import torch
from PIL import Image, ImageDraw

# ============================================================================
# Project path initialization
# ============================================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SAM3_PKG = os.path.join(PROJECT_ROOT, "sam3")
if SAM3_PKG not in sys.path:
    sys.path.insert(0, SAM3_PKG)

import sam3
from sam3 import build_sam3_image_model
from sam3.eval.postprocessors import PostProcessImage
from sam3.model.utils.misc import copy_data_to_device
from sam3.train.data.collator import collate_fn_api as collate
from sam3.train.data.sam3_image_dataset import (
    Datapoint,
    FindQueryLoaded,
    Image as SAMImage,
    InferenceMetadata,
)
from sam3.train.transforms.basic_for_api import (
    ComposeAPI,
    NormalizeAPI,
    RandomResizeAPI,
    ToTensorAPI,
)

# ============================================================================
# Constants
# ============================================================================
DEFAULT_BPE = os.path.join(SAM3_PKG, "assets", "bpe_simple_vocab_16e6.txt.gz")

CATEGORY_TO_STAGE = {
    "concept": "0_0",
    "simple": "1_1",
    "complex": "1_2",
}

DEFAULT_RESOLUTION = 1008
DEFAULT_NORM = {"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}
DEFAULT_ADAPTER = {"adapter_dim": 64, "adapter_heads": 4, "adapter_scale": 0.6}


def build_transform(resolution=DEFAULT_RESOLUTION, norm=None):
    """Build image transformation pipeline for inference."""
    norm = norm or DEFAULT_NORM
    return ComposeAPI(transforms=[
        RandomResizeAPI(sizes=resolution, max_size=resolution, square=True, consistent_transform=False),
        ToTensorAPI(),
        NormalizeAPI(mean=norm["mean"], std=norm["std"]),
    ])


def prepare_prompt(text: str, category: str):
    """Wrap raw text into the prompt format expected by the model."""
    if category == "concept":
        return text
    if category == "simple":
        return {
            "concept": [],
            "simple_query": [text, text],
            "complex_query": [],
        }
    if category == "complex":
        return {
            "concept": [],
            "simple_query": [],
            "complex_query": [text, text],
        }
    raise ValueError(f"Unknown category: {category}")


def infer_single_image(
    image_path: str,
    prompt: str,
    checkpoint_path: str,
    category: str = "simple",
    device: str = "cuda",
    detection_threshold: float = 0.5,
    output_path: str = None,
    box_color: tuple = (255, 0, 0),
    box_width: int = 3,
):
    """Run DTC inference on a single image and return predicted bounding boxes."""

    # ------------------------------------------------------------------
    # 1. Load image
    # ------------------------------------------------------------------
    pil_image = Image.open(image_path).convert("RGB")
    w, h = pil_image.size

    # ------------------------------------------------------------------
    # 2. Build model
    # ------------------------------------------------------------------
    stage = CATEGORY_TO_STAGE[category]
    model = build_sam3_image_model(
        bpe_path=DEFAULT_BPE if os.path.exists(DEFAULT_BPE) else None,
        checkpoint_path=checkpoint_path,
        eval_mode=True,
        enable_segmentation=False,
        device="cuda",
        load_from_HF=(checkpoint_path is None),
        inst_stage=stage,
        adapter_config=DEFAULT_ADAPTER,
    )
    model = model.to(device)
    model.eval()

    # ------------------------------------------------------------------
    # 3. Build transform & postprocessor
    # ------------------------------------------------------------------
    transform = build_transform()
    postprocessor = PostProcessImage(
        max_dets_per_img=-1,
        iou_type="bbox",
        use_original_sizes_box=True,
        use_original_sizes_mask=True,
        convert_mask_to_rle=False,
        detection_threshold=detection_threshold,
        to_cpu=False,
    )

    # ------------------------------------------------------------------
    # 4. Construct datapoint
    # ------------------------------------------------------------------
    prompt_wrapped = prepare_prompt(prompt, category)
    dp = Datapoint(
        find_queries=[
            FindQueryLoaded(
                query_text=prompt_wrapped,
                image_id=0,
                object_ids_output=[],
                is_exhaustive=True,
                query_processing_order=0,
                inference_metadata=InferenceMetadata(
                    coco_image_id=0,
                    original_image_id=0,
                    original_category_id=1,
                    original_size=(h, w),
                    object_id=0,
                    frame_index=0,
                ),
            )
        ],
        images=[SAMImage(data=pil_image, objects=[], size=(h, w))],
    )

    # ------------------------------------------------------------------
    # 5. Transform & collate
    # ------------------------------------------------------------------
    dp = transform(dp)
    batch = collate([dp], dict_key="dummy")["dummy"]
    batch = copy_data_to_device(batch, torch.device(device))

    # ------------------------------------------------------------------
    # 6. Inference
    # ------------------------------------------------------------------
    with torch.autocast("cuda", dtype=torch.bfloat16), torch.inference_mode():
        output = model(batch, stage)

    # ------------------------------------------------------------------
    # 7. Post-process
    # ------------------------------------------------------------------
    processed = postprocessor.process_results(output, batch.find_metadatas)
    key = 0  # coco_image_id set to 0 above
    result = processed.get(key, {"boxes": [], "scores": []})

    boxes = result["boxes"]
    scores = result["scores"]

    # Convert to numpy
    if isinstance(boxes, torch.Tensor):
        boxes = boxes.cpu().numpy()
    if isinstance(scores, torch.Tensor):
        scores = scores.float().cpu().numpy()

    # Ensure boxes shape is (N, 4)
    if boxes.ndim == 1 and boxes.shape[0] == 4:
        boxes = boxes.reshape(1, 4)

    # ------------------------------------------------------------------
    # 8. Save / visualize (optional)
    # ------------------------------------------------------------------
    if output_path is not None and len(boxes) > 0:
        img_draw = pil_image.copy()
        draw = ImageDraw.Draw(img_draw)

        for box in boxes:
            x1, y1, x2, y2 = map(float, box)
            draw.rectangle([x1, y1, x2, y2], outline=box_color, width=box_width)

        img_draw.save(output_path)
        print(f"Saved bbox result to {output_path}")

    return boxes, scores, pil_image


def main():
    parser = argparse.ArgumentParser(description="DTC Single Image Inference (BBox)")
    parser.add_argument("--image_path", required=True, help="Path to input image")
    parser.add_argument("--prompt", required=True, help="Text instruction / query")
    parser.add_argument("--checkpoint_path", default=None, help="Model checkpoint path (downloads from HF if omitted)")
    parser.add_argument("--category", choices=["concept", "simple", "complex"], default="simple",
                        help="Prompt category (default: simple)")
    parser.add_argument("--output_path", default=None, help="Path to save the bbox result PNG (optional)")
    parser.add_argument("--box_color", nargs=3, type=int, default=[255, 0, 0], metavar=("R", "G", "B"),
                        help="RGB color of the bounding box (default: 255 0 0)")
    parser.add_argument("--box_width", type=int, default=3, help="Width of the bounding box line (default: 3)")
    parser.add_argument("--device", default="cuda", help="Device to run on (default: cuda)")
    parser.add_argument("--detection_threshold", type=float, default=0.5, help="Detection threshold (default: 0.5)")
    args = parser.parse_args()

    boxes, scores, pil_image = infer_single_image(
        image_path=args.image_path,
        prompt=args.prompt,
        checkpoint_path=args.checkpoint_path,
        category=args.category,
        device=args.device,
        detection_threshold=args.detection_threshold,
        output_path=args.output_path,
        box_color=tuple(args.box_color),
        box_width=args.box_width,
    )

    print(f"Predicted {len(boxes)} box(es)")
    for i, (box, s) in enumerate(zip(boxes, scores)):
        x1, y1, x2, y2 = box
        print(f"  Box {i}: [{x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}], score = {s:.4f}")


if __name__ == "__main__":
    main()
