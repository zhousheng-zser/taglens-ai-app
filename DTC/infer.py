#!/usr/bin/env python3
"""
批量推理适配层：CLI 与 sam3/infer.py 一致，供 dtc_task_service 调用。
推理核心复用 infer_mask_multi（与 infer_mask.py / infer_mask.sh 同一套 DTC 模型与环境）。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

# DTC 推理固定使用 GPU
DEVICE = "cuda"

DTC_ROOT = Path(__file__).resolve().parent
if str(DTC_ROOT) not in sys.path:
    sys.path.insert(0, str(DTC_ROOT))

from infer_mask_multi import (  # noqa: E402
    build_model,
    build_postprocessor,
    build_transform,
    infer_one,
    prepare_prompt,
)

DEFAULT_CHECKPOINT = DTC_ROOT / "ckpt" / "checkpoint.pt"
DEFAULT_CATEGORY = "complex"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def require_cuda() -> None:
    """启动前校验 GPU；不可用则直接失败（不回落 CPU）。"""
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA 不可用。请检查 NVIDIA 驱动与 PyTorch CUDA 版本是否匹配。"
        )
    try:
        torch.zeros(1, device=DEVICE)
    except RuntimeError as exc:
        raise RuntimeError(
            f"CUDA 初始化失败: {exc}\n"
            "请升级 NVIDIA 驱动，使其支持当前 PyTorch 所需的 CUDA 版本。"
        ) from exc
    print(f"GPU: {torch.cuda.get_device_name(0)} | torch {torch.__version__} | cuda {torch.version.cuda}")


def parse_args():
    parser = argparse.ArgumentParser(description="DTC Batch Inference (sam3/infer.py compatible CLI)")
    parser.add_argument("--input", "-i", type=str, required=True, help="Input folder (recursive scan)")
    parser.add_argument("--output", "-o", type=str, default="output", help="Output base folder")
    parser.add_argument("--text", "-t", type=str, required=True, help="Text prompt")
    parser.add_argument("--th", type=float, default=0.5, help="Detection threshold")
    parser.add_argument(
        "--category",
        choices=["concept", "simple", "complex"],
        default=DEFAULT_CATEGORY,
        help="Prompt category (default: complex, same as infer_mask.sh)",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=str(DEFAULT_CHECKPOINT),
        help="Model checkpoint path",
    )
    return parser.parse_args()


def get_image_files(input_dir: str | Path) -> list[Path]:
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    image_files: list[Path] = []
    for ext in IMAGE_EXTENSIONS:
        image_files.extend(p for p in input_path.rglob(f"*{ext}") if p.is_file())
    return sorted(image_files)


def _iter_masks(masks):
    if masks is None or (isinstance(masks, np.ndarray) and masks.size == 0):
        return []
    if isinstance(masks, np.ndarray) and masks.ndim == 2:
        return [masks]
    return list(masks)


def create_overlay(image_np: np.ndarray, masks, alpha: float = 0.4) -> np.ndarray:
    """彩色 mask 叠加（与 infer_mask_multi 一致，仅用 numpy）。"""
    masks_iter = _iter_masks(masks)
    if not masks_iter:
        return image_np.copy()

    out = image_np.astype(np.float32)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
    for i, mask in enumerate(masks_iter):
        mask_bool = mask > 0.5 if mask.dtype != bool else mask
        if not mask_bool.any():
            continue
        color = np.array(colors[i % len(colors)], dtype=np.float32).reshape(1, 1, 3)
        mask_f = mask_bool.astype(np.float32)[..., None]
        out = out * (1.0 - alpha * mask_f) + color * alpha * mask_f
    return np.clip(out, 0, 255).astype(np.uint8)


def _erode_mask(mask: np.ndarray) -> np.ndarray:
    """3x3 腐蚀，用于提取 mask 外轮廓带。"""
    m = mask.astype(np.uint8)
    h, w = m.shape
    out = np.ones_like(m)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted = np.zeros_like(m)
            y0, y1 = max(0, dy), min(h, h + dy)
            x0, x1 = max(0, dx), min(w, w + dx)
            sy0, sy1 = max(0, -dy), min(h, h - dy)
            sx0, sx1 = max(0, -dx), min(w, w - dx)
            shifted[sy0:sy1, sx0:sx1] = m[y0:y1, x0:x1]
            out = np.minimum(out, shifted)
    return out


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _mask_bbox_polygon(mask_bool: np.ndarray) -> list[list[float]]:
    ys, xs = np.where(mask_bool)
    if len(xs) == 0:
        return []
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _mask_to_polygon(mask_bool: np.ndarray) -> list[list[float]]:
    if not mask_bool.any():
        return []
    boundary = mask_bool & (1 - _erode_mask(mask_bool))
    ys, xs = np.where(boundary)
    if len(xs) < 3:
        return _mask_bbox_polygon(mask_bool)
    hull = _convex_hull([(float(x), float(y)) for x, y in zip(xs, ys)])
    if len(hull) < 3:
        return _mask_bbox_polygon(mask_bool)
    return [[x, y] for x, y in hull]


def _panel_with_title(panel_rgb: np.ndarray, title: str, footer_h: int = 36) -> np.ndarray:
    """在面板底部绘制标题条，便于三图横拼。"""
    h, w = panel_rgb.shape[:2]
    canvas = np.ones((h + footer_h, w, 3), dtype=np.uint8) * 255
    canvas[:h] = panel_rgb
    img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img)
    draw.text((8, h + 8), title, fill=(0, 0, 0))
    return np.array(img)


def render_comparison_figure(
    image_np: np.ndarray,
    masks,
    num_masks: int,
    text_prompt: str,
    threshold: float,
) -> Image.Image:
    if num_masks > 1:
        stack = [m > 0.5 if m.dtype != bool else m for m in masks]
        combined_mask = np.any(np.stack(stack, axis=0), axis=0).astype(np.uint8) * 255
    elif num_masks == 1:
        m0 = masks[0]
        combined_mask = (m0 > 0.5 if m0.dtype != bool else m0).astype(np.uint8) * 255
    else:
        combined_mask = None

    overlay = create_overlay(image_np, masks)

    if combined_mask is not None:
        mask_panel = np.stack([combined_mask] * 3, axis=-1)
        mask_title = f"Mask (n={num_masks})"
    else:
        mask_panel = np.full_like(image_np, 255)
        no_mask_img = Image.fromarray(mask_panel)
        draw = ImageDraw.Draw(no_mask_img)
        draw.text((max(10, image_np.shape[1] // 4), image_np.shape[0] // 2), "No Mask", fill=(255, 0, 0))
        mask_panel = np.array(no_mask_img)
        mask_title = "Mask (n=0)"

    panels = [
        _panel_with_title(image_np, "Original"),
        _panel_with_title(mask_panel, mask_title),
        _panel_with_title(overlay, "Segmentation Overlay"),
    ]
    # 对齐高度后横向拼接
    max_h = max(p.shape[0] for p in panels)
    aligned = []
    for p in panels:
        if p.shape[0] < max_h:
            pad = np.ones((max_h - p.shape[0], p.shape[1], 3), dtype=np.uint8) * 255
            p = np.vstack([p, pad])
        aligned.append(p)
    comparison = np.hstack(aligned)

    header_h = 40
    out_h = comparison.shape[0] + header_h
    out_w = comparison.shape[1]
    canvas = np.ones((out_h, out_w, 3), dtype=np.uint8) * 255
    canvas[header_h:] = comparison
    header_img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(header_img)
    header_text = f'Prompt: "{text_prompt}" | Threshold: {threshold} | Masks: {num_masks}'
    draw.text((12, 10), header_text, fill=(0, 0, 0))
    return Image.fromarray(np.array(header_img))


def save_comparison_figure(
    image_np: np.ndarray,
    masks,
    num_masks: int,
    save_path: Path,
    text_prompt: str,
    threshold: float,
) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    render_comparison_figure(image_np, masks, num_masks, text_prompt, threshold).save(save_path)
    print(f"  ✓ Saved: {save_path.name} (detected {num_masks} masks)")


def comparison_figure_png_bytes(
    image_np: np.ndarray,
    masks,
    num_masks: int,
    text_prompt: str,
    threshold: float,
) -> bytes:
    buf = io.BytesIO()
    render_comparison_figure(image_np, masks, num_masks, text_prompt, threshold).save(buf, format="PNG")
    return buf.getvalue()


def build_labelme_payload(
    image_name: str,
    image_np: np.ndarray,
    masks,
    text_prompt: str,
    image_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    if not image_bytes:
        raise ValueError("image_bytes 不能为空")
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_height, image_width = int(image_np.shape[0]), int(image_np.shape[1])
    return {
        "version": "5.0.5",
        "flags": {},
        "shapes": masks_to_polygon_shapes(masks, text_prompt),
        "imagePath": image_name,
        "Path": image_name,
        "imageData": image_b64,
        "imageHeight": image_height,
        "imageWidth": image_width,
    }


def masks_to_polygon_shapes(masks, label_text: str) -> list[dict]:
    shapes: list[dict] = []
    for mask in _iter_masks(masks):
        mask_bool = mask > 0.5 if getattr(mask, "dtype", None) != bool else mask
        points = _mask_to_polygon(mask_bool)
        if len(points) < 3:
            continue
        shapes.append(
            {
                "label": label_text,
                "points": points,
                "group_id": None,
                "shape_type": "polygon",
                "flags": {},
            }
        )
    return shapes


def save_labelme_json(image_path: Path, image_np: np.ndarray, masks, text_prompt: str, json_save_path: Path) -> None:
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    payload = build_labelme_payload(image_path.name, image_np, masks, text_prompt, image_bytes)
    payload["Path"] = str(image_path.resolve())
    json_save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_save_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved: {json_save_path.name} (labelme json)")


def main() -> int:
    args = parse_args()
    safe_text = args.text.replace(" ", "_").replace("/", "_")
    output_dir = Path(args.output) / f"{safe_text}_{args.th}"
    output_dir.mkdir(parents=True, exist_ok=True)

    require_cuda()
    device = DEVICE
    checkpoint = args.checkpoint or str(DEFAULT_CHECKPOINT)

    print("Configuration:")
    print(f"  Input folder: {args.input}")
    print(f"  Text prompt: {args.text}")
    print(f"  Threshold: {args.th}")
    print(f"  Category: {args.category}")
    print(f"  Checkpoint: {checkpoint}")
    print(f"  Device: {device}")
    print(f"  Output folder: {output_dir}")
    print()

    try:
        image_files = get_image_files(args.input)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    if not image_files:
        print(f"No image files found in {args.input}")
        return 0

    print(f"Found {len(image_files)} images to process")
    print()
    print("Loading DTC model...")
    model = build_model(checkpoint, args.category, device)
    transform = build_transform()
    postprocessor = build_postprocessor(args.th)
    prompt_wrapped = prepare_prompt(args.text, args.category)
    print("Model loaded. Starting batch processing...")
    print("-" * 50)

    input_root = Path(args.input)
    for idx, img_path in enumerate(image_files, 1):
        rel_path = img_path.relative_to(input_root)
        base_name = str(rel_path.with_suffix("")).replace(os.sep, "_")
        print(f"[{idx}/{len(image_files)}] {rel_path}")

        try:
            pil_image = Image.open(img_path).convert("RGB")
            image_np = np.array(pil_image)

            masks, _scores = infer_one(
                pil_image=pil_image,
                prompt_wrapped=prompt_wrapped,
                model=model,
                transform=transform,
                postprocessor=postprocessor,
                category=args.category,
                device=device,
                output_path=None,
            )

            if masks is None or (isinstance(masks, np.ndarray) and masks.size == 0):
                num_masks = 0
            elif isinstance(masks, np.ndarray) and masks.ndim == 2:
                num_masks = 1 if masks.any() else 0
            else:
                num_masks = len(masks)

            save_filename = f"{base_name}_comparison.png"
            save_comparison_figure(
                image_np,
                masks,
                num_masks,
                output_dir / save_filename,
                args.text,
                args.th,
            )

            json_save_path = output_dir / img_path.with_suffix(".json").name
            save_labelme_json(img_path, image_np, masks, args.text, json_save_path)
        except Exception as e:
            print(f"  ✗ Error: {e}")
            continue

    print()
    print("-" * 50)
    print(f"Complete! Results in: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
