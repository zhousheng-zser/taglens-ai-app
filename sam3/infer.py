import argparse
import base64
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from transformers import Sam3Processor, Sam3Model
import torch
from PIL import Image, ImageDraw
import numpy as np
import cv2
import matplotlib
matplotlib.use('Agg')

def parse_args():
    parser = argparse.ArgumentParser(description="SAM3 Batch Inference")
    parser.add_argument("--input", "-i", type=str, required=True, 
                        help="Input folder path (will be recursively scanned)")
    parser.add_argument("--output", "-o", type=str, default="output",
                        help="Output base folder path (default: output)")
    parser.add_argument("--text", "-t", type=str, required=True, 
                        help="Text prompt for segmentation")
    parser.add_argument("--th", type=float, default=0.5, 
                        help="Threshold for mask confidence (default: 0.5)")
    parser.add_argument(
        "--infer_mode",
        choices=["mask", "bbox"],
        default="mask",
        help="输出形态：mask 或 bbox（默认 mask）",
    )
    return parser.parse_args()

def create_overlay(image_np, masks):
    """
    创建叠加可视化图像
    """
    if len(masks) == 0:
        return image_np.copy()
    
    overlay = image_np.copy()
    colors = [
        (255, 0, 0),    # 红 (RGB)
        (0, 255, 0),    # 绿  
        (0, 0, 255),    # 蓝
        (255, 255, 0),  # 黄
        (255, 0, 255),  # 紫
    ]
    
    for i, mask in enumerate(masks):
        color = colors[i % len(colors)]
        mask_bool = mask > 0.5 if mask.dtype != bool else mask
        
        # 创建彩色叠加层 (40% 透明度)
        colored_layer = np.zeros_like(image_np)
        colored_layer[mask_bool] = color
        
        # 混合
        overlay = cv2.addWeighted(overlay, 1.0, colored_layer, 0.4, 0)
        
        # 绘制轮廓
        mask_uint8 = mask_bool.astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, color, 2)
    
    return overlay


def _iter_masks(masks):
    if masks is None:
        return []
    if isinstance(masks, np.ndarray) and masks.ndim == 2:
        return [masks]
    return list(masks)


def _mask_bbox_polygon(mask_bool: np.ndarray) -> list[list[float]]:
    ys, xs = np.where(mask_bool)
    if len(xs) == 0:
        return []
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(ys.min()), float(ys.max())
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _iter_bboxes_from_masks(masks) -> list[list[list[float]]]:
    bboxes: list[list[list[float]]] = []
    for mask in _iter_masks(masks):
        mask_bool = mask > 0.5 if getattr(mask, "dtype", None) != bool else mask
        points = _mask_bbox_polygon(mask_bool)
        if len(points) == 4:
            bboxes.append(points)
    return bboxes


def _panel_with_title(panel_rgb: np.ndarray, title: str, footer_h: int = 36) -> np.ndarray:
    h, w = panel_rgb.shape[:2]
    canvas = np.ones((h + footer_h, w, 3), dtype=np.uint8) * 255
    canvas[:h] = panel_rgb
    img = Image.fromarray(canvas)
    draw = ImageDraw.Draw(img)
    draw.text((8, h + 8), title, fill=(0, 0, 0))
    return np.array(img)

def render_comparison_figure(image_np, masks, num_masks, text_prompt, threshold):
    """渲染三图对比：原图 | Mask | 叠加图（与 DTC_v2 对齐版式）。"""
    if num_masks > 1:
        stack = [m > 0.5 if getattr(m, "dtype", None) != bool else m for m in _iter_masks(masks)]
        combined_mask = np.any(np.stack(stack, axis=0), axis=0).astype(np.uint8) * 255
    elif num_masks == 1:
        m0 = _iter_masks(masks)[0]
        combined_mask = (m0 > 0.5 if getattr(m0, "dtype", None) != bool else m0).astype(np.uint8) * 255
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


def save_comparison_figure(image_np, masks, num_masks, save_path, text_prompt, threshold):
    render_comparison_figure(image_np, masks, num_masks, text_prompt, threshold).save(save_path)
    print(f"  ✓ Saved: {save_path.name} (detected {num_masks} masks)")


def comparison_figure_png_bytes(image_np, masks, num_masks, text_prompt, threshold) -> bytes:
    buf = io.BytesIO()
    render_comparison_figure(image_np, masks, num_masks, text_prompt, threshold).save(buf, format="PNG")
    return buf.getvalue()


def render_bbox_figure(image_np, masks, text_prompt, threshold):
    image = Image.fromarray(image_np.astype(np.uint8)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for points in _iter_bboxes_from_masks(masks):
        draw.polygon([(p[0], p[1]) for p in points], outline=(255, 0, 0), width=3)
    return image


def save_bbox_figure(image_np, masks, save_path, text_prompt, threshold):
    render_bbox_figure(image_np, masks, text_prompt, threshold).save(save_path)
    print(f"  ✓ Saved: {save_path.name} (bbox view)")


def bbox_figure_png_bytes(image_np, masks, text_prompt, threshold) -> bytes:
    buf = io.BytesIO()
    render_bbox_figure(image_np, masks, text_prompt, threshold).save(buf, format="PNG")
    return buf.getvalue()


def render_mask_figure(image_np, masks):
    masks_iter = _iter_masks(masks)
    if masks_iter:
        stack = [m > 0.5 if getattr(m, "dtype", None) != bool else m for m in masks_iter]
        merged = np.any(np.stack(stack, axis=0), axis=0).astype(np.uint8) * 255
    else:
        merged = np.zeros((image_np.shape[0], image_np.shape[1]), dtype=np.uint8)
    mask_rgb = np.stack([merged] * 3, axis=-1)
    return Image.fromarray(mask_rgb)


def save_mask_figure(image_np, masks, save_path):
    render_mask_figure(image_np, masks).save(save_path)
    print(f"  ✓ Saved: {save_path.name} (mask view)")


def mask_figure_png_bytes(image_np, masks) -> bytes:
    buf = io.BytesIO()
    render_mask_figure(image_np, masks).save(buf, format="PNG")
    return buf.getvalue()


def render_overlay_figure(image_np, masks, infer_mode: str = "mask"):
    if infer_mode == "bbox":
        return render_bbox_figure(image_np, masks, "", 0.0)
    return Image.fromarray(create_overlay(image_np, masks))


def save_overlay_figure(image_np, masks, save_path, infer_mode: str = "mask"):
    render_overlay_figure(image_np, masks, infer_mode=infer_mode).save(save_path)
    print(f"  ✓ Saved: {save_path.name} (overlay view)")


def overlay_figure_png_bytes(image_np, masks, infer_mode: str = "mask") -> bytes:
    buf = io.BytesIO()
    render_overlay_figure(image_np, masks, infer_mode=infer_mode).save(buf, format="PNG")
    return buf.getvalue()


def build_labelme_payload(
    image_name: str,
    image_np: np.ndarray,
    masks,
    text_prompt: str,
    image_bytes: Optional[bytes] = None,
    infer_mode: str = "mask",
    include_image_data: bool = True,
    processing_time_ms: Optional[int] = None,
) -> Dict[str, Any]:
    if image_bytes is None:
        raise ValueError("image_bytes 不能为空")
    image_b64 = base64.b64encode(image_bytes).decode("utf-8") if include_image_data else None
    image_height, image_width = int(image_np.shape[0]), int(image_np.shape[1])
    payload = {
        "version": "5.0.5",
        "flags": {},
        "shapes": (
            masks_to_rectangle_shapes(masks, text_prompt)
            if infer_mode == "bbox"
            else masks_to_polygon_shapes(masks, text_prompt)
        ),
        "imagePath": image_name,
        "Path": image_name,
        "imageData": image_b64,
        "imageHeight": image_height,
        "imageWidth": image_width,
    }
    if isinstance(processing_time_ms, int):
        payload["processingTimeMs"] = processing_time_ms
    return payload

def get_image_files(input_dir):
    """
    递归获取所有图片文件
    """
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    image_files = []
    
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    
    for ext in image_extensions:
        for file_path in input_path.rglob(f"*{ext}"):
            if file_path.is_file():
                image_files.append(file_path)
    
    return sorted(image_files)


def masks_to_polygon_shapes(masks, label_text: str):
    """
    将 instance masks 转为 LabelMe polygon shapes
    """
    shapes = []
    if masks is None:
        return shapes

    # 兼容 (H, W) 单 mask 的情况
    if isinstance(masks, np.ndarray) and masks.ndim == 2:
        masks_iter = [masks]
    else:
        masks_iter = masks

    for mask in masks_iter:
        mask_bool = mask > 0.5 if getattr(mask, "dtype", None) != bool else mask
        mask_uint8 = (mask_bool.astype(np.uint8)) * 255

        contours, _ = cv2.findContours(mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue

        # 每个目标只取最大外轮廓
        contour = max(contours, key=cv2.contourArea)
        if contour is None or len(contour) < 3:
            continue

        points = [[float(pt[0][0]), float(pt[0][1])] for pt in contour]
        if len(points) < 3:
            continue

        shapes.append({
            "label": label_text,
            "points": points,
            "group_id": None,
            "shape_type": "polygon",
            "flags": {},
        })

    return shapes


def masks_to_rectangle_shapes(masks, label_text: str):
    shapes = []
    for points in _iter_bboxes_from_masks(masks):
        shapes.append({
            "label": label_text,
            "points": points,
            "group_id": None,
            "shape_type": "rectangle",
            "flags": {},
        })
    return shapes


def save_labelme_json(
    image_path: Path,
    image_np: np.ndarray,
    masks,
    text_prompt: str,
    json_save_path: Path,
    infer_mode: str = "mask",
    include_image_data: bool = True,
    processing_time_ms: Optional[int] = None,
):
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    payload = build_labelme_payload(
        image_path.name,
        image_np,
        masks,
        text_prompt,
        image_bytes,
        infer_mode=infer_mode,
        include_image_data=include_image_data,
        processing_time_ms=processing_time_ms,
    )
    payload["Path"] = str(image_path.resolve())
    with open(json_save_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Saved: {json_save_path.name} (labelme json)")

def main():
    args = parse_args()
    
    # 构建输出目录: {output_base}/{text}_{threshold}
    safe_text = args.text.replace(" ", "_").replace("/", "_")
    output_dir = Path(args.output) / f"{safe_text}_{args.th}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Configuration:")
    print(f"  Input folder: {args.input}")
    print(f"  Text prompt: {args.text}")
    print(f"  Threshold: {args.th}")
    print(f"  Output base folder: {args.output}")
    print(f"  Output folder: {output_dir}")
    print()
    
    # 获取所有图片文件
    try:
        image_files = get_image_files(args.input)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return
    
    if len(image_files) == 0:
        print(f"No image files found in {args.input}")
        return
    
    print(f"Found {len(image_files)} images to process")
    print()
    
    # 加载模型
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading model on {device}...")
    
    model = Sam3Model.from_pretrained("./sam3_pt", ignore_mismatched_sizes=True).to(device)
    processor = Sam3Processor.from_pretrained("./sam3_pt", ignore_mismatched_sizes=True)
    model.eval()
    # 打印模型参数实际所在设备，确认最终跑在 CPU 还是 GPU。
    print(f"Model actual device: {next(model.parameters()).device}")
    
    print(f"Starting batch processing...")
    print("-" * 50)
    
    # 处理每张图片
    for idx, img_path in enumerate(image_files, 1):
        # 计算相对路径以保持目录结构
        rel_path = img_path.relative_to(Path(args.input))
        base_name = str(rel_path.with_suffix("")).replace(os.sep, "_")
        
        print(f"[{idx}/{len(image_files)}] {rel_path}")
        
        try:
            # 加载图像
            image = Image.open(img_path).convert("RGB")
            image_np = np.array(image)
            
            # 预处理
            inputs = processor(images=image, text=args.text, return_tensors="pt").to(device)
            
            # 推理
            with torch.no_grad():
                outputs = model(**inputs)
            
            # 后处理
            results = processor.post_process_instance_segmentation(
                outputs,
                threshold=args.th,
                mask_threshold=0.6,
                target_sizes=inputs.get("original_sizes").tolist()
            )[0]
            
            # 获取 masks 并计算数量
            masks = results["masks"]
            if torch.is_tensor(masks):
                masks = masks.cpu().numpy()
            num_masks = len(masks)
            
            if args.infer_mode == "mask":
                save_mask_figure(image_np, masks, Path(output_dir) / f"{base_name}_mask.png")
            save_overlay_figure(
                image_np,
                masks,
                Path(output_dir) / f"{base_name}_overlay.png",
                infer_mode=args.infer_mode,
            )

            # 保存 LabelMe JSON（原图同名，后缀改为 .json）
            json_save_path = Path(output_dir) / img_path.with_suffix(".json").name
            save_labelme_json(
                img_path,
                image_np,
                masks,
                args.text,
                json_save_path,
                infer_mode=args.infer_mode,
            )
            
        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
            continue
    
    print()
    print("-" * 50)
    print(f"Complete! Results in: {output_dir}")

if __name__ == "__main__":
    main()
