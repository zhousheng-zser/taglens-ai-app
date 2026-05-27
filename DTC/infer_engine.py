# -*- coding: utf-8 -*-
"""
DTC 推理引擎：启动时加载模型，任务执行时复用（不再每次子进程冷启动）。
"""
from __future__ import annotations

import base64
import io
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

import infer as infer_mod
from infer_mask_multi import (
    build_model,
    build_postprocessor,
    build_transform,
    infer_one,
    prepare_prompt,
)

DEVICE = infer_mod.DEVICE
DEFAULT_CHECKPOINT = infer_mod.DEFAULT_CHECKPOINT
DEFAULT_CATEGORY = "simple"
DEFAULT_ADAPTER_SCALE = 0.5


def _date_token() -> str:
    return datetime.now().strftime("%y%m%d")


def _safe_text(text: str) -> str:
    return (text or "").replace(" ", "_").replace("/", "_")


def _task_id() -> str:
    return uuid.uuid4().hex[:12]


def _count_masks(masks) -> int:
    if masks is None or (isinstance(masks, np.ndarray) and masks.size == 0):
        return 0
    if isinstance(masks, np.ndarray) and masks.ndim == 2:
        return 1 if masks.any() else 0
    return len(masks)


def _normalize_comparison_source(stem: str, json_map: Dict[str, Dict[str, Any]]) -> str:
    """对比图文件名 stem 对齐 json stem（兼容旧版末尾 _{num_masks}）。"""
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


def _apply_adapter_scale(model, adapter_scale: float) -> None:
    """将已加载模型各 adapter 层的 scale 设为请求指定值。"""
    scale = float(adapter_scale)
    for module in model.modules():
        if hasattr(module, "adapter_scale"):
            module.adapter_scale = scale


class DtcInferEngine:
    """单例推理引擎，GPU 推理串行加锁。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self._model = None
        self._transform = None
        self._checkpoint = str(DEFAULT_CHECKPOINT)
        self._category = DEFAULT_CATEGORY
        self._adapter_scale = DEFAULT_ADAPTER_SCALE
        self._loaded = False
        self._load_error: Optional[str] = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def load(
        self,
        checkpoint: Optional[str] = None,
        category: str = DEFAULT_CATEGORY,
        adapter_scale: float = DEFAULT_ADAPTER_SCALE,
    ) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                infer_mod.require_cuda()
                ckpt = checkpoint or str(DEFAULT_CHECKPOINT)
                self._checkpoint = ckpt
                self._category = category
                self._adapter_scale = float(adapter_scale)
                self._model = build_model(ckpt, category, DEVICE, adapter_scale=self._adapter_scale)
                self._transform = build_transform()
                self._loaded = True
                self._load_error = None
            except Exception as exc:
                self._loaded = False
                self._load_error = str(exc)
                raise

    def ensure_loaded(self) -> None:
        if not self._loaded:
            if self._load_error:
                raise RuntimeError(f"模型未加载: {self._load_error}")
            raise RuntimeError("模型未加载，请等待服务启动完成")

    def run_batch(
        self,
        input_dir: str | Path,
        output_base: str | Path,
        prompt: str,
        threshold: float,
        category: Optional[str] = None,
        adapter_scale: Optional[float] = None,
    ) -> Dict[str, Any]:
        """同步跑完一个目录，返回任务摘要（供调试或短任务）。"""
        self.ensure_loaded()
        task = {
            "task_id": _task_id(),
            "date": _date_token(),
            "prompt": prompt,
            "threshold": float(threshold),
            "input_path": str(input_dir),
            "output_base": str(output_base),
            "category": category or self._category,
            "adapter_scale": float(adapter_scale if adapter_scale is not None else self._adapter_scale),
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
        category = str(task.get("category") or self._category)
        adapter_scale = float(task.get("adapter_scale", self._adapter_scale))
        out_dir = output_base / f"{_safe_text(prompt)}_{threshold}"
        out_dir.mkdir(parents=True, exist_ok=True)

        _apply_adapter_scale(self._model, adapter_scale)

        image_files = infer_mod.get_image_files(input_root)
        if not image_files:
            raise ValueError(f"输入目录无图片: {input_root}")

        postprocessor = build_postprocessor(threshold)
        prompt_wrapped = prepare_prompt(prompt, category)

        errors: List[str] = []
        with self._infer_lock:
            for idx, img_path in enumerate(image_files, 1):
                rel_path = img_path.relative_to(input_root)
                base_name = str(rel_path.with_suffix("")).replace(os.sep, "_")
                try:
                    pil_image = Image.open(img_path).convert("RGB")
                    image_np = np.array(pil_image)
                    masks, _scores = infer_one(
                        pil_image=pil_image,
                        prompt_wrapped=prompt_wrapped,
                        model=self._model,
                        transform=self._transform,
                        postprocessor=postprocessor,
                        category=category,
                        device=DEVICE,
                        output_path=None,
                    )
                    num_masks = _count_masks(masks)
                    save_filename = f"{base_name}_comparison.png"
                    infer_mod.save_comparison_figure(
                        image_np,
                        masks,
                        num_masks,
                        out_dir / save_filename,
                        prompt,
                        threshold,
                    )
                    json_save_path = out_dir / img_path.with_suffix(".json").name
                    infer_mod.save_labelme_json(img_path, image_np, masks, prompt, json_save_path)
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
        include_comparison: bool = True,
        category: Optional[str] = None,
        adapter_scale: Optional[float] = None,
    ) -> Dict[str, Any]:
        """直接传入图片字节，返回 LabelMe JSON 与可选 comparison 图（不落盘）。"""
        self.ensure_loaded()
        if not images:
            raise ValueError("请至少提供一张图片")
        if not prompt.strip():
            raise ValueError("prompt 不能为空")

        cat = category or self._category
        scale = float(adapter_scale if adapter_scale is not None else self._adapter_scale)
        postprocessor = build_postprocessor(threshold)
        prompt_wrapped = prepare_prompt(prompt.strip(), cat)
        _apply_adapter_scale(self._model, scale)

        results: List[Dict[str, Any]] = []
        errors: List[str] = []

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
                    image_np = np.array(pil_image)
                    masks, _scores = infer_one(
                        pil_image=pil_image,
                        prompt_wrapped=prompt_wrapped,
                        model=self._model,
                        transform=self._transform,
                        postprocessor=postprocessor,
                        category=cat,
                        device=DEVICE,
                        output_path=None,
                    )
                    num_masks = _count_masks(masks)
                    labelme = infer_mod.build_labelme_payload(
                        image_name, image_np, masks, prompt.strip(), raw_bytes
                    )
                    item: Dict[str, Any] = {
                        "sourceName": source,
                        "imageName": image_name,
                        "numMasks": num_masks,
                        "json": labelme,
                    }
                    if include_comparison:
                        png = infer_mod.comparison_figure_png_bytes(
                            image_np, masks, num_masks, prompt.strip(), float(threshold)
                        )
                        item["comparisonMimeType"] = "image/png"
                        item["comparisonImageBase64"] = base64.b64encode(png).decode("ascii")
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
            "algorithm": "dtc",
            "status": "success",
            "result_count": ok_count,
            "results": results,
            "warnings": errors or None,
        }


# 全局引擎实例
engine = DtcInferEngine()
