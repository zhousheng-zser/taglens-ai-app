"""Jina CLIP v2 文本向量化（description 语义向量）。"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = BASE_DIR / "jina-clip-v2"
JINA_MODEL_NAME = os.getenv("JINA_MODEL_NAME", "jina-clip-v2")
JINA_EMBED_DIM = int(os.getenv("JINA_EMBED_DIM", "1024"))
JINA_TRUNCATE_DIM = int(os.getenv("JINA_TRUNCATE_DIM", "2048"))

_net = None
_device = None
_infer_lock = threading.Lock()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def get_jina_model():
    """懒加载 Jina CLIP v2 模型（离线优先）。"""
    global _net, _device
    if _net is not None:
        return _net, _device

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    if str(MODEL_DIR) not in sys.path:
        sys.path.insert(0, str(MODEL_DIR))

    import transformers.models.clip.modeling_clip as clip_mod

    if not hasattr(clip_mod, "clip_loss"):
        def clip_loss(similarity):
            batch = torch.arange(similarity.size(0), device=similarity.device)
            return (
                F.cross_entropy(similarity, batch)
                + F.cross_entropy(similarity.T, batch)
            ) / 2

        clip_mod.clip_loss = clip_loss

    cfg_mod = _load_module("configuration_clip", MODEL_DIR / "configuration_clip.py")
    model_mod = _load_module("modeling_clip", MODEL_DIR / "modeling_clip.py")

    with open(MODEL_DIR / "config.json", encoding="utf-8") as f:
        raw = json.load(f)
    config = model_mod.JinaCLIPConfig(**raw)
    config._name_or_path = str(MODEL_DIR)

    net = model_mod.JinaCLIPModel(config=config)
    net.eval()

    from safetensors.torch import load_file

    state = load_file(str(MODEL_DIR / "model.safetensors"))
    net.load_state_dict(state, strict=False)

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _net = net.to(_device)
    print(f"[jina_embedding] 模型就绪 device={_device} dim={JINA_EMBED_DIM}")
    return _net, _device


def encode_description_to_vector(text: str) -> tuple[bytes, int]:
    """
    将 description 编码为 Jina CLIP 向量。

    返回:
        (embedding_bytes, dim)
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("description 不能为空")

    net, device = get_jina_model()
    with _infer_lock:
        with torch.no_grad():
            emb = net.encode_text([text], truncate_dim=JINA_TRUNCATE_DIM)
        if isinstance(emb, np.ndarray):
            vec = emb.squeeze().astype(np.float32)
        else:
            vec = emb.cpu().float().numpy().squeeze().astype(np.float32)

    blob = vec.tobytes()
    return blob, int(vec.shape[0])
