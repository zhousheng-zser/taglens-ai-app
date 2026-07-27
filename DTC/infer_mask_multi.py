#!/usr/bin/env python3

import argparse
import os
import sys
import time

import numpy as np
import torch
from PIL import Image
from PIL import ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

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

SUPPORTED_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def build_transform(resolution=DEFAULT_RESOLUTION, norm=None):
    """Build image transformation pipeline for inference."""
    norm = norm or DEFAULT_NORM
    return ComposeAPI(transforms=[
        RandomResizeAPI(sizes=resolution, max_size=resolution, square=True, consistent_transform=False),
        ToTensorAPI(),
        NormalizeAPI(mean=norm["mean"], std=norm["std"]),
    ])


def build_postprocessor(detection_threshold=0.5):
    """Build post-processor once."""
    return PostProcessImage(
        max_dets_per_img=-1,
        iou_type="segm",
        use_original_sizes_box=True,
        use_original_sizes_mask=True,
        convert_mask_to_rle=False,
        detection_threshold=detection_threshold,
        to_cpu=False,
    )


def build_adapter_config(adapter_scale: float = 0.6) -> dict:
    return {
        "adapter_dim": 64,
        "adapter_heads": 4,
        "adapter_scale": float(adapter_scale),
    }


def build_model(checkpoint_path, category, device="cuda", adapter_scale: float = 0.6):
    """Build and load model once（固定 GPU）。"""
    stage = CATEGORY_TO_STAGE[category]
    model = build_sam3_image_model(
        bpe_path=DEFAULT_BPE if os.path.exists(DEFAULT_BPE) else None,
        checkpoint_path=checkpoint_path,
        eval_mode=True,
        enable_segmentation=True,
        device="cuda",
        load_from_HF=(checkpoint_path is None),
        inst_stage=stage,
        adapter_config=build_adapter_config(adapter_scale),
    )
    model = model.to(device)
    model.eval()
    return model


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


def infer_one(
    pil_image: Image.Image,
    prompt_wrapped,
    model,
    transform,
    postprocessor,
    category: str,
    device: str,
    output_path: str = None,
    mask_color: tuple = (255, 0, 0),
    mask_alpha: float = 0.5,
):
    """Run inference on a single PIL image with pre-built model & auxiliaries."""

    w, h = pil_image.size
    stage = CATEGORY_TO_STAGE[category]

    # ------------------------------------------------------------------
    # 1. Construct datapoint
    # ------------------------------------------------------------------
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
    # 2. Transform & collate
    # ------------------------------------------------------------------
    dp = transform(dp)
    batch = collate([dp], dict_key="dummy")["dummy"]
    batch = copy_data_to_device(batch, torch.device(device))

    # ------------------------------------------------------------------
    # 3. Inference
    # ------------------------------------------------------------------
    with torch.autocast("cuda", dtype=torch.bfloat16), torch.inference_mode():
        output = model(batch, stage)

    # ------------------------------------------------------------------
    # 4. Post-process
    # ------------------------------------------------------------------
    processed = postprocessor.process_results(output, batch.find_metadatas)
    key = 0
    result = processed.get(key, {"masks": [], "scores": []})

    masks = result["masks"]
    scores = result["scores"]

    # Convert to numpy
    if isinstance(masks, torch.Tensor):
        masks = masks.cpu().numpy()
    if isinstance(scores, torch.Tensor):
        scores = scores.float().cpu().numpy()

    if masks.dtype != np.bool_:
        masks = masks > 0.5
    if masks.ndim == 4:
        masks = masks.squeeze(1)

    # ------------------------------------------------------------------
    # 5. Save / visualize (optional)
    # ------------------------------------------------------------------
    if output_path is not None and len(masks) > 0:
        merged_mask = masks[0]
        for m in masks[1:]:
            merged_mask = merged_mask | m

        img_np = np.array(pil_image, dtype=np.float32)
        mask_f = merged_mask.astype(np.float32)[..., None]
        color = np.array(mask_color, dtype=np.float32).reshape(1, 1, 3)
        overlay = img_np * (1.0 - mask_alpha * mask_f) + color * mask_alpha * mask_f
        overlay = np.clip(overlay, 0, 255).astype(np.uint8)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        Image.fromarray(overlay).save(output_path)
        print(f"  Saved: {output_path}")

    return masks, scores


def main():
    parser = argparse.ArgumentParser(description="DTC Inference (Single or Batch)")
    parser.add_argument("--image_path", required=True,
                        help="Path to input image OR folder containing images")
    parser.add_argument("--prompt", required=True, help="Text instruction / query")
    parser.add_argument("--checkpoint_path", default=None,
                        help="Model checkpoint path (downloads from HF if omitted)")
    parser.add_argument("--category", choices=["concept", "simple", "complex"],
                        default="simple", help="Prompt category")
    parser.add_argument("--output_path", default=None,
                        help="Path to save overlaid result PNG (single-image mode only)")
    parser.add_argument("--output_dir", default=None,
                        help="Directory to save results (batch/folder mode)")
    parser.add_argument("--mask_color", nargs=3, type=int, default=[255, 0, 0],
                        metavar=("R", "G", "B"), help="RGB mask color")
    parser.add_argument("--mask_alpha", type=float, default=0.5,
                        help="Mask transparency")
    parser.add_argument("--device", default="cuda", help="Device")
    parser.add_argument("--detection_threshold", type=float, default=0.5,
                        help="Detection threshold")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Build model & auxiliaries ONCE
    # ------------------------------------------------------------------
    print("Loading model...")
    model = build_model(args.checkpoint_path, args.category, args.device)
    transform = build_transform()
    postprocessor = build_postprocessor(args.detection_threshold)
    prompt_wrapped = prepare_prompt(args.prompt, args.category)
    print("Model loaded. Ready for inference.\n")

    mask_color = tuple(args.mask_color)

    input_path = args.image_path

    # ==================================================================
    # Batch mode: input is a directory
    # ==================================================================
    if os.path.isdir(input_path):
        output_dir = args.output_dir or "./results"
        os.makedirs(output_dir, exist_ok=True)

        files = sorted([
            f for f in os.listdir(input_path)
            if os.path.splitext(f.lower())[1] in SUPPORTED_EXTS
        ])

        if not files:
            print(f"No supported images found in {input_path}")
            sys.exit(1)

        print(f"Found {len(files)} image(s) in '{input_path}'")
        print(f"Saving results to '{output_dir}'\n")

        for idx, fname in enumerate(files, 1):
            img_path = os.path.join(input_path, fname)
            pil_image = Image.open(img_path).convert("RGB")

            name_no_ext = os.path.splitext(fname)[0]
            out_path = os.path.join(output_dir, f"{name_no_ext}.png")

            print(f"[{idx}/{len(files)}] {fname}")
            start_time = time.time()
            masks, scores = infer_one(
                pil_image=pil_image,
                prompt_wrapped=prompt_wrapped,
                model=model,
                transform=transform,
                postprocessor=postprocessor,
                category=args.category,
                device=args.device,
                output_path=out_path,
                mask_color=mask_color,
                mask_alpha=args.mask_alpha,
            )
            end_time = time.time()
            print(f"  Inference time: {end_time - start_time:.2f} seconds")
            print(f"  Predicted {len(masks)} mask(s)")
            for i, s in enumerate(scores):
                print(f"    Mask {i}: score = {s:.4f}")

        print(f"\nAll done. Results saved to: {output_dir}")

    # ==================================================================
    # Single mode: input is a file
    # ==================================================================
    else:
        if not os.path.isfile(input_path):
            print(f"Error: {input_path} is not a valid file or directory")
            sys.exit(1)

        pil_image = Image.open(input_path).convert("RGB")
        masks, scores = infer_one(
            pil_image=pil_image,
            prompt_wrapped=prompt_wrapped,
            model=model,
            transform=transform,
            postprocessor=postprocessor,
            category=args.category,
            device=args.device,
            output_path=args.output_path,
            mask_color=mask_color,
            mask_alpha=args.mask_alpha,
        )

        print(f"Predicted {len(masks)} mask(s)")
        for i, s in enumerate(scores):
            print(f"  Mask {i}: score = {s:.4f}")


if __name__ == "__main__":
    main()
