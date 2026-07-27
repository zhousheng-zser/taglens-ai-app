#!/usr/bin/env python3
"""Jina CLIP v2 文本转向量 - importlib 加载版"""
import os, sys, importlib.util
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch, torch.nn.functional as F
import transformers.models.clip.modeling_clip as clip_module

if not hasattr(clip_module, 'clip_loss'):
    def clip_loss(similarity):
        caption_loss = F.cross_entropy(similarity, torch.arange(similarity.size(0), device=similarity.device))
        image_loss = F.cross_entropy(similarity.T, torch.arange(similarity.size(0), device=similarity.device))
        return (caption_loss + image_loss) / 2.0
    clip_module.clip_loss = clip_loss

MODEL_DIR = "/opt/Traffic-LLM/zser/taglens-ai-app/jina-clip-v2"

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

cfg_mod = load_module("configuration_clip", os.path.join(MODEL_DIR, "configuration_clip.py"))
model_mod = load_module("modeling_clip", os.path.join(MODEL_DIR, "modeling_clip.py"))

JinaCLIPConfig = cfg_mod.JinaCLIPConfig
JinaCLIPModel = model_mod.JinaCLIPModel

import numpy as np
from datetime import datetime

OUTPUT_FILE = "/opt/Traffic-LLM/zser/taglens-ai-app/feature_vectors.txt"
TRUNCATE_DIM = 2048
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def main():
    print(f"🔧 设备: {DEVICE}")
    config = JinaCLIPConfig.from_pretrained(MODEL_DIR)
    model = JinaCLIPModel.from_pretrained(MODEL_DIR, config=config,
        torch_dtype=torch.bfloat16 if DEVICE == "cuda" else torch.float32).to(DEVICE)
    model.eval()
    print("✅ 模型加载完成")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"# Jina CLIP v2 文本特征向量\n# 时间: {datetime.now()}\n\n")

    while True:
        text = input("\n>> 输入文本: ").strip()
        if not text:
            print("👋 退出"); break
        with torch.no_grad():
            emb = model.encode_text([text], truncate_dim=TRUNCATE_DIM)
        vec = emb.cpu().float().numpy().squeeze()
        print(f"📝 {text}  维度: {vec.shape}  范数: {np.linalg.norm(vec):.6f}")
        print(f"   前10个值: {vec[:10].tolist()}")
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 文本: {text}\n")
            f.write(f"# 维度: {vec.shape}\n")
            f.write(", ".join(f"{v:.8f}" for v in vec) + "\n\n")
        print(f"   💾 已保存到 {OUTPUT_FILE}")

if __name__ == "__main__":
    main()