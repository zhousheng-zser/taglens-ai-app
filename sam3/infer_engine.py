# -*- coding: utf-8 -*-
"""
SAM3 推理引擎：启动时加载 HuggingFace 模型，任务执行时复用。
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
from PIL import Image
from transformers import Sam3Model, Sam3Processor

import infer as infer_mod

SAM3_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = SAM3_ROOT / "sam3_pt"
DEVICE = "cuda"


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
        json_map[source] = {
            "sourceName": jf.stem,
            "jsonName": jf.name,
            "jsonPath": str(jf),
        }

    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for img in sorted(out_dir.glob("*_comparison.png")):
        stem = img.name.rsplit("_comparison.png", 1)[0]
        source = _normalize_comparison_source(stem, json_map)
        item = dict(json_map.get(source, {"sourceName": source}))
        item["sourceName"] = source
        item["imageName"] = img.name
        item["imagePath"] = str(img)
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
    ) -> Dict[str, Any]:
        self.ensure_loaded()
        task = {
            "task_id": _task_id(),
            "date": _date_token(),
            "prompt": prompt,
            "threshold": float(threshold),
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
                    image = Image.open(img_path).convert("RGB")
                    image_np = np.array(image)
                    masks = self._infer_image(image, prompt, threshold)
                    num_masks = _count_masks(masks)

                    save_filename = f"{base_name}_comparison.png"
                    infer_mod.save_comparison_figure(
                        image_np, masks, num_masks, out_dir / save_filename, prompt, threshold
                    )
                    json_save_path = out_dir / img_path.with_suffix(".json").name
                    infer_mod.save_labelme_json(img_path, image_np, masks, prompt, json_save_path)
                except Exception as exc:
                    errors.append(f"{rel_path}: {exc}")

        if errors and len(errors) == len(image_files):
            raise RuntimeError("; ".join(errors[:5]))
        if errors:
            task["warnings"] = errors


engine = Sam3InferEngine()
