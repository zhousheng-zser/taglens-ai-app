# -*- coding: utf-8 -*-
"""
SAM3 推理引擎：启动时加载 HuggingFace 模型，任务执行时复用。
"""
from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from PIL import Image
from transformers import Sam3Model, Sam3Processor

import infer as infer_mod

SAM3_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = SAM3_ROOT / "sam3_pt"
DEVICE = "cuda"
DEFAULT_INFER_MODE = "mask"


def _date_token() -> str:
    return datetime.now().strftime("%y%m%d")


def _safe_text(text: str) -> str:
    return (text or "").replace(" ", "_").replace("/", "_")


def _task_id() -> str:
    return uuid.uuid4().hex[:12]


def _count_masks(masks) -> int:
    if masks is None:
        return 0
    if torch.is_tensor(masks):
        masks = masks.cpu().numpy()
    if isinstance(masks, np.ndarray) and masks.ndim == 0:
        return 0
    return len(masks)


def _normalize_comparison_source(stem: str, json_map: Dict[str, Dict[str, Any]]) -> str:
    if stem in json_map:
        return stem
    if "_" in stem:
        parent, suffix = stem.rsplit("_", 1)
        if suffix.isdigit() and parent in json_map:
            return parent
    return stem


def _collect_results(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    out_dir = Path(task["output_base"]) / f"{_safe_text(task['prompt'])}_{task['threshold']}"
    if not out_dir.exists():
        return []
    json_map: Dict[str, Dict[str, Any]] = {}
    for jf in out_dir.glob("*.json"):
        source = jf.stem
        shape_count = 0
        source_path = ""
        processing_time_ms = None
        try:
            with jf.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            shapes = payload.get("shapes")
            if isinstance(shapes, list):
                shape_count = len(shapes)
            source_path = str(payload.get("Path") or "")
            if isinstance(payload.get("processingTimeMs"), int):
                processing_time_ms = payload.get("processingTimeMs")
        except Exception:
            shape_count = 0
        json_map[source] = {
            "sourceName": jf.stem,
            "jsonName": jf.name,
            "jsonPath": str(jf),
            "shapeCount": shape_count,
            "sourcePath": source_path,
            "processingTimeMs": processing_time_ms,
        }

    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for img in sorted(out_dir.glob("*_overlay.png")):
        stem = img.name.rsplit("_overlay.png", 1)[0]
        source = _normalize_comparison_source(stem, json_map)
        item = dict(json_map.get(source, {"sourceName": source}))
        item["sourceName"] = source
        item["overlayPath"] = str(img)
        item["imageName"] = img.name
        item["imagePath"] = str(img)
        results.append(item)
        seen.add(source)

    for img in sorted(out_dir.glob("*_mask.png")):
        stem = img.name.rsplit("_mask.png", 1)[0]
        source = _normalize_comparison_source(stem, json_map)
        item = dict(json_map.get(source, {"sourceName": source}))
        item["sourceName"] = source
        item["maskPath"] = str(img)
        results.append(item)
        seen.add(source)

    for s, it in json_map.items():
        if s not in seen:
            results.append(dict(it))
    return results


def require_cuda() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用，SAM3 服务需要 GPU")
    torch.zeros(1, device=DEVICE)
    print(f"GPU: {torch.cuda.get_device_name(0)} | torch {torch.__version__}")


class Sam3InferEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._model = None
        self._processor = None
        self._model_dir = str(DEFAULT_MODEL_DIR)
        self._device = DEVICE
        self._loaded = False
        self._load_error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def load(self, model_dir: Optional[str] = None) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                require_cuda()
                model_path = Path(model_dir or DEFAULT_MODEL_DIR)
                if not model_path.is_dir():
                    raise FileNotFoundError(f"模型目录不存在: {model_path}")
                self._model_dir = str(model_path.resolve())
                os.chdir(SAM3_ROOT)
                self._model = Sam3Model.from_pretrained(
                    self._model_dir, ignore_mismatched_sizes=True
                ).to(self._device)
                self._processor = Sam3Processor.from_pretrained(
                    self._model_dir, ignore_mismatched_sizes=True
                )
                self._model.eval()
                self._loaded = True
                self._load_error = None
                print(f"SAM3 model device: {next(self._model.parameters()).device}")
            except Exception as exc:
                self._loaded = False
                self._load_error = str(exc)
                raise

    def ensure_loaded(self) -> None:
        if not self._loaded:
            if self._load_error:
                raise RuntimeError(f"模型未加载: {self._load_error}")
            raise RuntimeError("模型未加载")

    def _infer_image(self, pil_image: Image.Image, prompt: str, threshold: float):
        inputs = self._processor(images=pil_image, text=prompt, return_tensors="pt").to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        results = self._processor.post_process_instance_segmentation(
            outputs,
            threshold=threshold,
            mask_threshold=0.6,
            target_sizes=inputs.get("original_sizes").tolist(),
        )[0]
        masks = results["masks"]
        if torch.is_tensor(masks):
            masks = masks.cpu().numpy()
        return masks

    def run_batch(
        self,
        input_dir: str | Path,
        output_base: str | Path,
        prompt: str,
        threshold: float,
        infer_mode: str = DEFAULT_INFER_MODE,
    ) -> Dict[str, Any]:
        self.ensure_loaded()
        task = {
            "task_id": _task_id(),
            "date": _date_token(),
            "prompt": prompt,
            "threshold": float(threshold),
            "infer_mode": infer_mode if infer_mode in ("mask", "bbox") else DEFAULT_INFER_MODE,
            "input_path": str(input_dir),
            "output_base": str(output_base),
        }
        self._execute_task(task)
        results = _collect_results(task)
        return {
            "task_id": task["task_id"],
            "status": "success",
            "result_count": len(results),
            "output_dir": str(Path(task["output_base"]) / f"{_safe_text(prompt)}_{threshold}"),
            "results": results,
        }

    def _execute_task(self, task: Dict[str, Any]) -> None:
        self.ensure_loaded()
        input_root = Path(task["input_path"])
        output_base = Path(task["output_base"])
        output_base.mkdir(parents=True, exist_ok=True)

        prompt = str(task["prompt"])
        threshold = float(task["threshold"])
        infer_mode = str(task.get("infer_mode") or DEFAULT_INFER_MODE).lower()
        if infer_mode not in ("mask", "bbox"):
            infer_mode = DEFAULT_INFER_MODE
        out_dir = output_base / f"{_safe_text(prompt)}_{threshold}"
        out_dir.mkdir(parents=True, exist_ok=True)

        image_files = infer_mod.get_image_files(input_root)
        if not image_files:
            raise ValueError(f"输入目录无图片: {input_root}")

        errors: List[str] = []
        with self._infer_lock:
            for img_path in image_files:
                rel_path = img_path.relative_to(input_root)
                base_name = str(rel_path.with_suffix("")).replace(os.sep, "_")
                try:
                    started_at = time.perf_counter()
                    image = Image.open(img_path).convert("RGB")
                    image_np = np.array(image)
                    masks = self._infer_image(image, prompt, threshold)
                    num_masks = _count_masks(masks)
                    if infer_mode == "mask":
                        infer_mod.save_mask_figure(image_np, masks, out_dir / f"{base_name}_mask.png")
                    infer_mod.save_overlay_figure(
                        image_np, masks, out_dir / f"{base_name}_overlay.png", infer_mode=infer_mode
                    )
                    json_save_path = out_dir / img_path.with_suffix(".json").name
                    infer_mod.save_labelme_json(
                        img_path,
                        image_np,
                        masks,
                        prompt,
                        json_save_path,
                        infer_mode=infer_mode,
                        processing_time_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                except Exception as exc:
                    errors.append(f"{rel_path}: {exc}")

        if errors and len(errors) == len(image_files):
            raise RuntimeError("; ".join(errors[:5]))
        if errors:
            task["warnings"] = errors

    def run_images(
        self,
        images: List[Tuple[str, bytes]],
        prompt: str,
        threshold: float,
        infer_mode: str = DEFAULT_INFER_MODE,
        include_json_image_data: bool = True,
        include_mask_image_base64: bool = True,
        include_overlay_image_base64: bool = True,
    ) -> Dict[str, Any]:
        """直接传入图片字节，返回 LabelMe JSON 与可选 mask/overlay 图（不落盘）。"""
        self.ensure_loaded()
        if not images:
            raise ValueError("请至少提供一张图片")
        if not prompt.strip():
            raise ValueError("prompt 不能为空")

        results: List[Dict[str, Any]] = []
        errors: List[str] = []
        mode = infer_mode if infer_mode in ("mask", "bbox") else DEFAULT_INFER_MODE

        with self._infer_lock:
            for image_name, raw_bytes in images:
                source = Path(image_name).stem or "image"
                try:
                    pil_image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                except Exception as exc:
                    results.append(
                        {
                            "sourceName": source,
                            "imageName": image_name,
                            "error": f"图片无法解码: {exc}",
                        }
                    )
                    errors.append(f"{image_name}: {exc}")
                    continue

                try:
                    started_at = time.perf_counter()
                    image_np = np.array(pil_image)
                    masks = self._infer_image(pil_image, prompt.strip(), float(threshold))
                    num_masks = _count_masks(masks)
                    labelme = infer_mod.build_labelme_payload(
                        image_name,
                        image_np,
                        masks,
                        prompt.strip(),
                        raw_bytes,
                        infer_mode=mode,
                        include_image_data=include_json_image_data,
                        processing_time_ms=int((time.perf_counter() - started_at) * 1000),
                    )
                    item: Dict[str, Any] = {
                        "sourceName": source,
                        "imageName": image_name,
                        "numMasks": num_masks,
                        "processingTimeMs": int((time.perf_counter() - started_at) * 1000),
                        "json": labelme,
                    }
                    if mode == "mask" and include_mask_image_base64:
                        mask_png = infer_mod.mask_figure_png_bytes(image_np, masks)
                        item["maskMimeType"] = "image/png"
                        item["maskImageBase64"] = base64.b64encode(mask_png).decode("ascii")
                    if include_overlay_image_base64:
                        overlay_png = infer_mod.overlay_figure_png_bytes(image_np, masks, infer_mode=mode)
                        item["overlayMimeType"] = "image/png"
                        item["overlayImageBase64"] = base64.b64encode(overlay_png).decode("ascii")
                    results.append(item)
                except Exception as exc:
                    results.append(
                        {
                            "sourceName": source,
                            "imageName": image_name,
                            "error": str(exc),
                        }
                    )
                    errors.append(f"{image_name}: {exc}")

        ok_count = sum(1 for r in results if "json" in r)
        if ok_count == 0:
            raise RuntimeError("; ".join(errors[:5]) if errors else "全部图片推理失败")

        return {
            "algorithm": "sam3",
            "modelKey": "dtc_v1",
            "modelName": "DTC-Fine-grained",
            "modelAlias": "DTC-Fine",
            "status": "success",
            "result_count": ok_count,
            "results": results,
            "warnings": errors or None,
        }


engine = Sam3InferEngine()
