"""BGE 文本向量化（供标签搜索、标签补齐等复用）。"""
from __future__ import annotations

import glob
import os
import threading
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

BGE_MODEL_NAME = os.getenv("BGE_MODEL_NAME", "BAAI/bge-base-zh-v1.5")
BGE_MODEL_CACHE_DIR = Path(
    os.getenv("BGE_MODEL_CACHE_DIR", str(Path(__file__).parent / "model"))
)
_bge_tokenizer = None
_bge_model = None
_bge_device = None
_bge_infer_lock = threading.Lock()


def _hf_hub_cache_root() -> Path:
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _snapshot_has_weights(snapshot_dir: Path) -> bool:
    return (snapshot_dir / "pytorch_model.bin").exists() or any(
        snapshot_dir.glob("*.safetensors")
    )


def _is_valid_bge_snapshot(snapshot_dir: Path) -> bool:
    required = ("config.json", "tokenizer_config.json")
    return snapshot_dir.is_dir() and all(
        (snapshot_dir / name).exists() for name in required
    ) and _snapshot_has_weights(snapshot_dir)


def _iter_snapshot_dirs(base: Path) -> list[Path]:
    """在 base 下查找 models--*/snapshots/* 或直接子目录中的有效快照。"""
    found: list[Path] = []
    if not base.exists():
        return found

    patterns = [
        base / "models--*" / "snapshots" / "*",
        base / "snapshots" / "*",
        base,
    ]
    for pattern in patterns:
        for path_str in glob.glob(str(pattern)):
            path = Path(path_str)
            if _is_valid_bge_snapshot(path):
                found.append(path)

    # 较新的快照优先（按目录 mtime）
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def resolve_bge_snapshot_dir() -> Path | None:
    """
    解析可用的本地 BGE 快照目录。
    优先级：BGE_MODEL_PATH > BGE_MODEL_CACHE_DIR > HuggingFace 默认 hub 缓存。
    """
    explicit = os.getenv("BGE_MODEL_PATH", "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if _is_valid_bge_snapshot(path):
            return path

    for base in (BGE_MODEL_CACHE_DIR, _hf_hub_cache_root()):
        snapshots = _iter_snapshot_dirs(base)
        if snapshots:
            return snapshots[0]

    repo_cache = _hf_hub_cache_root() / f"models--{BGE_MODEL_NAME.replace('/', '--')}"
    snapshots = _iter_snapshot_dirs(repo_cache)
    if snapshots:
        return snapshots[0]

    return None


def get_bge_model():
    """获取 BGE 模型（懒加载，优先本地快照，兼容 HF 默认缓存目录）。"""
    global _bge_tokenizer, _bge_model, _bge_device
    if _bge_tokenizer is None or _bge_model is None:
        import time

        load_start = time.time()
        BGE_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        original_http_proxy = os.environ.pop("HTTP_PROXY", None)
        original_https_proxy = os.environ.pop("HTTPS_PROXY", None)
        original_http_proxy_lower = os.environ.pop("http_proxy", None)
        original_https_proxy_lower = os.environ.pop("https_proxy", None)

        try:
            print("正在加载BGE向量化模型...")
            print(f"  模型名称: {BGE_MODEL_NAME}")
            print(f"  项目缓存目录: {BGE_MODEL_CACHE_DIR}")

            snapshot_dir = resolve_bge_snapshot_dir()
            offline_env = os.getenv("HF_HUB_OFFLINE", "").lower() in ("1", "true", "yes")

            if snapshot_dir is not None:
                print(f"  使用本地快照: {snapshot_dir}")
                load_kwargs = {"local_files_only": True}
                model_source = str(snapshot_dir)
            else:
                print(f"  未找到本地快照（已查: {BGE_MODEL_CACHE_DIR}、{_hf_hub_cache_root()}）")
                if offline_env:
                    raise FileNotFoundError(
                        f"HF 离线模式下无法下载 {BGE_MODEL_NAME}。"
                        f"请将模型放到 {BGE_MODEL_CACHE_DIR}，或设置 BGE_MODEL_PATH 指向快照目录，"
                        f"或执行: huggingface-cli download {BGE_MODEL_NAME}"
                    )
                print("  将尝试从 HuggingFace 下载到项目缓存目录")
                load_kwargs = {"cache_dir": str(BGE_MODEL_CACHE_DIR), "local_files_only": False}
                model_source = BGE_MODEL_NAME

            _bge_tokenizer = AutoTokenizer.from_pretrained(model_source, **load_kwargs)
            _bge_model = AutoModel.from_pretrained(model_source, **load_kwargs)

            if torch.cuda.is_available():
                _bge_device = torch.device("cuda")
                _bge_model = _bge_model.to(_bge_device)
                print(f"  检测到GPU: {torch.cuda.get_device_name(0)}，将使用GPU加速")
            else:
                _bge_device = torch.device("cpu")
                print("  未检测到GPU，将使用CPU")

            _bge_model.eval()
            load_time = time.time() - load_start
            mode_str = "离线" if snapshot_dir else "在线"
            device_str = "GPU" if _bge_device.type == "cuda" else "CPU"
            print(f"✓ BGE向量化模型加载完成（{mode_str},{device_str}）,耗时 {load_time:.2f}秒")
        finally:
            if original_http_proxy:
                os.environ["HTTP_PROXY"] = original_http_proxy
            if original_https_proxy:
                os.environ["HTTPS_PROXY"] = original_https_proxy
            if original_http_proxy_lower:
                os.environ["http_proxy"] = original_http_proxy_lower
            if original_https_proxy_lower:
                os.environ["https_proxy"] = original_https_proxy_lower
    return _bge_tokenizer, _bge_model, _bge_device


def encode_text_to_vector(text: str) -> bytes:
    """
    使用 BGE 模型将文本编码为 768 维向量。

    返回:
        bytes: 768 维 float32 向量的二进制表示
    """
    tokenizer, model, device = get_bge_model()

    with _bge_infer_lock:
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            output = model(**inputs)
            embedding = output.last_hidden_state[:, 0]
            embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

        embedding_np = embedding.cpu().numpy().astype(np.float32)
        return embedding_np.tobytes()
