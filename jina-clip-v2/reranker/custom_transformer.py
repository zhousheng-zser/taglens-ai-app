"""Custom Transformer module for jina-reranker-m0 that fixes image ordering for image-image pairs.

The Qwen2VL processor extracts images from messages in iteration order. ST creates messages
as [query_msg, doc_msg], but the chat template renders doc-first. For single-image pairs this
is fine, but for image-image pairs the two images get swapped. This module swaps the pair
elements so the processor extracts images in doc-first order, matching the template rendering.
Since both elements render as identical <|image_pad|> tokens, the role swap is invisible.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from sentence_transformers.base.modality import is_image_url_or_path
from sentence_transformers.base.modules.transformer import Transformer


def _is_image(item: Any) -> bool:
    return isinstance(item, Image.Image) or (isinstance(item, str) and is_image_url_or_path(item))


class JinaRerankerTransformer(Transformer):
    def preprocess(
        self,
        inputs: list,
        prompt: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        # Swap image-image pairs so the processor extracts images in doc-first order,
        # matching the chat template's doc-first rendering.
        swapped = []
        for item in inputs:
            if isinstance(item, (list, tuple)) and len(item) == 2 and _is_image(item[0]) and _is_image(item[1]):
                swapped.append((item[1], item[0]))
            else:
                swapped.append(item)

        return super().preprocess(swapped, prompt=prompt, **kwargs)
