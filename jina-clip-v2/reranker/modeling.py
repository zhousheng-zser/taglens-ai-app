import torch
from torch import nn
from typing import Optional, Tuple, List, Union
from transformers import Qwen2VLForConditionalGeneration
import logging
import warnings
from PIL import Image
from transformers.image_utils import load_image

logger = logging.getLogger(__name__)

LOGIT_BIAS = 2.65  # logit bias for sigmoid normalization

def load_images(images, lazy_load: bool = True):
    # Disable PIL DecompositionBomb threshold for reading large images.
    pil_max_px = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None

    images_batch = []
    for image in images:
        if isinstance(image, Image.Image):
            images_batch.append(image)
        else:
            pil_image = load_image(image)
            if lazy_load:
                images_batch.append(pil_image)
            else:
                # avoid Too many open files error
                images_batch.append(pil_image.copy())
                pil_image.close()
    Image.MAX_IMAGE_PIXELS = pil_max_px

    return images_batch


def formatting_prompts_func(
    query: str,
    doc: str,
    query_type: str = 'text',
    doc_type: str = 'text',
    prefix_str: str = '',
) -> str:
    """
    Format prompts for different combinations of query and content types.

    Args:
        query: Query text or image path
        doc: Content text or image path
        query_type: Whether query is an image
        doc_type: Whether content is an image
        prefix_str: Optional prefix string to add
    """
    # Format query part
    if query_type == 'image':
        query_part = "**Query**:\n<|vision_start|><|image_pad|><|vision_end|>"
    else:
        query_part = f"**Query**:\n{query}"

    # Format content part
    if doc_type == 'image':
        doc_part = "**Document**:\n<|vision_start|><|image_pad|><|vision_end|>"
    else:
        doc_part = f"**Document**:\n{doc}"

    # Combine parts
    prompt = doc_part + '\n' + query_part

    # Add prefix if provided
    if prefix_str:
        prompt = prefix_str + '\n' + prompt

    return prompt


class JinaVLForRanking(Qwen2VLForConditionalGeneration):
    def __init__(self, config):
        # Disable weight tying before init so replacing lm_head with Identity doesn't break loading
        config.tie_word_embeddings = False
        super().__init__(config)

        self.padding_side = "left"
        self.num_labels = 1  # config.num_labels

        # hack the lm_head to do nothing, since we only want the hidden states
        self.lm_head = nn.Identity()

        hidden_size = getattr(config, "hidden_size", None) or config.text_config.hidden_size

        # copy the idea from `Qwen2ForRewardModel` to have a MLP layer to get the final score
        self.score = nn.Sequential(
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, self.num_labels),
        )

        # Initialize weights and apply final processing
        self.post_init()

        self.score_token_id = 100

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        pixel_values=None,
        image_grid_thw=None,
        video_grid_thw=None,
        mm_token_type_ids=None,
        **kwargs,
    ) -> torch.Tensor:
        kwargs.pop("output_hidden_states", None)
        kwargs.pop("use_cache", None)
        assert kwargs.pop("labels", None) is None, "labels should not be passed to forward()"

        # Auto-append score token if not already the last token, required for inference that bypasses compute_score
        if input_ids is not None and not (input_ids[:, -1] == self.score_token_id).all():
            batch_size = input_ids.size(0)
            score_token = torch.full(
                (batch_size, 1), self.score_token_id,
                device=input_ids.device, dtype=input_ids.dtype,
            )
            input_ids = torch.cat([input_ids, score_token], dim=1)
            if attention_mask is not None:
                attention_mask = torch.cat([
                    attention_mask,
                    torch.ones(batch_size, 1, device=attention_mask.device, dtype=attention_mask.dtype),
                ], dim=1)
            if mm_token_type_ids is not None:
                mm_token_type_ids = torch.cat([
                    mm_token_type_ids,
                    torch.zeros(batch_size, 1, device=mm_token_type_ids.device, dtype=mm_token_type_ids.dtype),
                ], dim=1)

        outputs = super().forward(
            input_ids=input_ids,
            attention_mask=attention_mask,
            pixel_values=pixel_values,
            image_grid_thw=image_grid_thw,
            video_grid_thw=video_grid_thw,
            mm_token_type_ids=mm_token_type_ids,
            use_cache=False,
            output_hidden_states=True,
            **kwargs,
        )

        # get the hidden states of the last layer
        hidden_states = outputs.hidden_states[-1]

        # IMPORTANT: the padding token must be on the left side
        # get the hidden states of the last token and apply the linear layer
        pooled_logits = self.score(hidden_states[:, -1]).squeeze(-1)

        # normalize scores to [0, 1] with sigmoid with a bias
        return torch.sigmoid(pooled_logits - LOGIT_BIAS)

    @torch.no_grad()
    def compute_score(
        self,
        pairs: Union[List[Tuple[str, str]], Tuple[str, str]],
        batch_size: int = 8,
        max_length: int = 10240,
        max_query_length: int = 512,
        max_doc_length: Optional[int] = None,
        query_type: str = 'text',
        doc_type: str = 'text',
        normalize_scores: bool = True,
        show_progress: bool = False,
    ) -> List[float]:

        if not hasattr(self, "_processor"):
            from transformers import AutoProcessor

            self._processor = AutoProcessor.from_pretrained(
                self.name_or_path, max_pixels=602112, min_pixels=3136, trust_remote_code=True
            )

        assert isinstance(pairs, list)

        if isinstance(pairs[0], str):
            pairs = [pairs]

        max_length = max_length or self.config.max_length

        if max_doc_length is None:
            max_doc_length = max(max_length - max_query_length, max_query_length)

        if max_doc_length < max_query_length:
            warnings.warn(
                f"max_doc_length={max_doc_length} should be greater than max_query_length={max_query_length}"
            )

        assert (
            max_doc_length + max_query_length <= max_length
        ), f"max_doc_length ({max_doc_length}) + max_query_length ({max_query_length}) should be less than max_length ({max_length})"

        max_length = max_length - 1

        all_scores = []

        device = next(self.parameters()).device

        batch_iter = range(0, len(pairs), batch_size)
        if show_progress:
            from tqdm import trange

            batch_iter = trange(0, len(pairs), batch_size, desc="Computing scores")

        for start_index in batch_iter:
            mini_batch = pairs[start_index : start_index + batch_size]

            batch_inputs = []
            for q, d in mini_batch:
                # TEMP FIX: Truncate long documents
                if doc_type == 'text':
                    tokens = self._processor.tokenizer(d, truncation=True, max_length=max_doc_length)
                    if len(tokens['input_ids']) >= max_doc_length:
                        d = self._processor.tokenizer.decode(tokens['input_ids'])

                batch_inputs.append(formatting_prompts_func(q, d, query_type=query_type, doc_type=doc_type))

            batch_images = None
            # if doc_type == 'image':
            #     batch_images = load_images([d for (q, d) in mini_batch])
            # elif query_type == 'image':
            #     batch_images = load_images([q for (q, d) in mini_batch])

            doc_images = []
            query_images = []
            if doc_type == 'image':
                doc_images = load_images([d for (q, d) in mini_batch])
            if query_type == 'image':
                query_images = load_images([q for (q, d) in mini_batch])

            if len(doc_images) == len(query_images) and len(doc_images) > 0:
                batch_images = [[d, q] for q, d in zip(query_images, doc_images)]
            elif len(doc_images) > 0:
                batch_images = doc_images
            elif len(query_images) > 0:
                batch_images = query_images

            batch = self._processor(
                text=batch_inputs,
                images=batch_images,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=max_length,
            )

            # append the reward token to the input_ids, attention_mask, and mm_token_type_ids
            batch_size = batch["input_ids"].size(0)
            batch["input_ids"] = torch.cat(
                [
                    batch["input_ids"],
                    torch.full((batch_size, 1), self.score_token_id, device=batch["input_ids"].device),
                ],
                dim=1,
            )
            batch["attention_mask"] = torch.cat(
                [
                    batch["attention_mask"],
                    torch.ones((batch_size, 1), device=batch["attention_mask"].device),
                ],
                dim=1,
            )
            if "mm_token_type_ids" in batch:
                batch["mm_token_type_ids"] = torch.cat(
                    [
                        batch["mm_token_type_ids"],
                        torch.zeros((batch_size, 1), device=batch["mm_token_type_ids"].device, dtype=batch["mm_token_type_ids"].dtype),
                    ],
                    dim=1,
                )
            # move the batch to the correct device
            batch = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}

            scores = self.forward(**batch).view(-1).cpu().float().numpy()

            all_scores.extend(scores.tolist())

        if len(all_scores) == 1:
            return all_scores[0]
        return all_scores
