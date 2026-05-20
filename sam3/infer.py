import argparse
import os
import json
import base64
from pathlib import Path
from transformers import Sam3Processor, Sam3Model
import torch
from PIL import Image
import numpy as np
import cv2
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

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

def save_comparison_figure(image_np, masks, num_masks, save_path, text_prompt, threshold):
    """
    保存三图对比：原图 | Mask | 叠加图
    """
    # 合并所有mask为单张二值图（如果有多个instance）
    if num_masks > 1:
        combined_mask = np.any(masks > 0.5, axis=0).astype(np.uint8) * 255
    elif num_masks == 1:
        combined_mask = (masks[0] > 0.5).astype(np.uint8) * 255
    else:
        combined_mask = None
    
    # 创建叠加图
    overlay = create_overlay(image_np, masks)
    
    # 创建三图对比
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    # 原图
    axes[0].imshow(image_np)
    axes[0].set_title('Original', fontsize=12, fontweight='bold')
    axes[0].axis('off')
    
    # Mask (灰度显示)
    if combined_mask is not None:
        axes[1].imshow(combined_mask, cmap='gray')
        axes[1].set_title(f'Mask (n={num_masks})', fontsize=12, fontweight='bold')
    else:
        axes[1].text(0.5, 0.5, 'No Mask\nDetected', 
                    ha='center', va='center', fontsize=12, color='red')
        axes[1].set_title('Mask (n=0)', fontsize=12, fontweight='bold', color='red')
    axes[1].axis('off')
    
    # 叠加图
    axes[2].imshow(overlay)
    axes[2].set_title('Segmentation Overlay', fontsize=12, fontweight='bold')
    axes[2].axis('off')
    
    # 添加总标题
    fig.suptitle(f'Prompt: "{text_prompt}" | Threshold: {threshold} | Masks: {num_masks}', 
                 fontsize=14, y=0.98)
    
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.savefig(save_path, dpi=150, bbox_inches='tight', pad_inches=0.1)
    plt.close()
    
    print(f"  ✓ Saved: {save_path.name} (detected {num_masks} masks)")

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


def save_labelme_json(image_path: Path, image_np: np.ndarray, masks, text_prompt: str, json_save_path: Path):
    """
    生成并保存 LabelMe 风格 JSON
    """
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    image_height, image_width = int(image_np.shape[0]), int(image_np.shape[1])
    shapes = masks_to_polygon_shapes(masks, text_prompt)

    payload = {
        "version": "5.0.5",
        "flags": {},
        "shapes": shapes,
        "imagePath": image_path.name,
        "Path": str(image_path.resolve()),
        "imageData": image_b64,
        "imageHeight": image_height,
        "imageWidth": image_width,
    }

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
            
            save_filename = f"{base_name}_comparison.png"
            save_path = Path(output_dir) / save_filename
            
            # 保存三图对比
            save_comparison_figure(image_np, masks, num_masks, save_path, args.text, args.th)

            # 保存 LabelMe JSON（原图同名，后缀改为 .json）
            json_save_path = Path(output_dir) / img_path.with_suffix(".json").name
            save_labelme_json(img_path, image_np, masks, args.text, json_save_path)
            
        except Exception as e:
            print(f"  ✗ Error: {str(e)}")
            continue
    
    print()
    print("-" * 50)
    print(f"Complete! Results in: {output_dir}")

if __name__ == "__main__":
    main()
