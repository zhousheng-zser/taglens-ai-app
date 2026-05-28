#!/usr/bin/env python3
import argparse
import base64
import json
import sys
from pathlib import Path

import requests

EXAMPLE = """
提供给外部调用 DTC-Fine（SAM3 v1, 8011）的测试脚本
用法示例（8011 DTC-Fine / taglens-dtc-v1）:

python3 test_sam3_v1.py \\
--host 192.168.1.155 \\
--image /opt/Traffic-LLM/zser/taglens-ai-app/data/images/04137_1013.jpg \\
--prompt helmet \\
--threshold 0.5 \\
--infer-mode mask \\
--include-json-image-data true \\
--include-mask-image true \\
--include-overlay-image true \\
--out /opt/Traffic-LLM/zser/taglens-ai-app/data/dtc_test/sam3_v1

输出: response.json、*_mask.png(可选)、*_overlay.png(可选)、*_image.jpg(可选)
服务: sudo systemctl start taglens-dtc-v1.service   # DTC-Fine
"""


def str2bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def save_outputs(data: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    (out_dir / "response.json").write_text(text, encoding="utf-8")
    for i, item in enumerate(data.get("results") or []):
        name = (item.get("sourceName") or f"result_{i}").strip() or f"result_{i}"
        if item.get("maskImageBase64"):
            (out_dir / f"{name}_mask.png").write_bytes(
                base64.b64decode(item["maskImageBase64"])
            )
        if item.get("overlayImageBase64"):
            (out_dir / f"{name}_overlay.png").write_bytes(
                base64.b64decode(item["overlayImageBase64"])
            )
        if isinstance(item.get("json"), dict):
            lm = dict(item["json"])  # labelme格式数据
            img_b64 = lm.get("imageData")
            if img_b64:
                (out_dir / f"{name}_image.jpg").write_bytes(
                    base64.b64decode(img_b64.split(",")[-1])
                )


def main() -> None:
    if len(sys.argv) == 1:
        print(EXAMPLE.strip())
        return

    ap = argparse.ArgumentParser(description="测试 8011 DTC-Fine 接口并保存结果")
    ap.add_argument(
        "--host",
        required=True,
        help="目标服务主机/IP（不含端口），例如 192.168.1.155",
    )
    ap.add_argument(
        "--image",
        required=True,
        help="待测试图片的本地绝对路径",
    )
    ap.add_argument(
        "--prompt",
        required=True,
        help="分割提示词（如 helmet/car/person）",
    )
    ap.add_argument(
        "--threshold",
        required=True,
        type=float,
        help="检测阈值，通常取值 0~1（建议 0.3~0.7）",
    )
    ap.add_argument(
        "--infer-mode",
        choices=["mask", "bbox"],
        default="mask",
        help="推理形态：mask 返回分割形态，bbox 返回矩形框形态（默认 mask）",
    )
    ap.add_argument(
        "--include-json-image-data",
        default="true",
        help="是否在 results[].json 中返回 imageData(base64 原图)，true/false（默认 true）",
    )
    ap.add_argument(
        "--include-mask-image",
        default="true",
        help="是否返回 results[].maskImageBase64(掩码图)，true/false（默认 true）",
    )
    ap.add_argument(
        "--include-overlay-image",
        default="true",
        help="是否返回 results[].overlayImageBase64(叠框图)，true/false（默认 true）",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="输出目录：保存 response.json 与解码出的图片文件",
    )
    args = ap.parse_args()

    image = Path(args.image)
    if not image.is_file():
        raise SystemExit(f"图片不存在: {image}")

    url = f"http://{args.host}:8011/dtc-fine/segment/images"
    with image.open("rb") as f:
        resp = requests.post(
            url,
            files={"files": (image.name, f, "image/jpeg")},
            data={
                "prompt": args.prompt,
                "threshold": args.threshold,
                "inferMode": args.infer_mode,
                "includeJsonImageData": str2bool(args.include_json_image_data),
                "includeMaskImageBase64": str2bool(args.include_mask_image),
                "includeOverlayImageBase64": str2bool(args.include_overlay_image),
            },
            timeout=600,
        )
    resp.raise_for_status()
    save_outputs(resp.json(), Path(args.out))
    print(f"完成，输出目录: {args.out}")


if __name__ == "__main__":
    main()
