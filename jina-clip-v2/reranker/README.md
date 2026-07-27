
---
pipeline_tag: text-classification
tags:
- sentence-transformers
- vidore
- reranker
- qwen2_vl
language:
- multilingual
base_model:
- Qwen/Qwen2-VL-2B-Instruct
inference: false
license: cc-by-nc-4.0
library_name: transformers
---

<br><br>

<p align="center">
<img src="https://huggingface.co/datasets/jinaai/documentation-images/resolve/main/logo.webp" alt="Jina AI: Your Search Foundation, Supercharged!" width="150px">
</p>

<p align="center">
<b>Trained by <a href="https://jina.ai/"><b>Jina AI</b></a>.</b>
</p>

[GGUF](https://huggingface.co/jinaai/jina-reranker-m0-GGUF)| [Blog](https://jina.ai/news/jina-reranker-m0-multilingual-multimodal-document-reranker) | [API](https://jina.ai/reranker) | [AWS](https://aws.amazon.com/marketplace/pp/prodview-ctlpeffe5koac?sr=0-1&ref_=beagle&applicationId=AWSMPContessa) | [Azure](https://azuremarketplace.microsoft.com/en-us/marketplace/apps/jinaai.jina-reranker-m0) | [GCP](https://console.cloud.google.com/marketplace/product/jinaai-public/jina-reranker-m0) |[Arxiv](coming soon)


# jina-reranker-m0: Multilingual Multimodal Document Reranker

## Intended Usage & Model Info

**jina-reranker-m0** is our new **multilingual multimodal reranker** model for ranking visual documents across multiple languages: it accepts a query alongside a collection of visually rich document images, including pages with text, figures, tables, infographics, and various layouts across multiple domains and over 29 languages.
It outputs a ranked list of documents ordered by their relevance to the input query. Compared to `jina-reranker-v2-base-multilingual`, `jina-reranker-m0` also improves text reranking for multilingual content, long documents, and code searching tasks.

## Architecture

**jina-reranker-m0** is built on a decoder-only vision language model architecture, specifically:

- **Base model**: `Qwen2-VL-2B-Instruct`, utilizing its vision encoder, projection layer, and language model
- **Adaptation**: Fine-tuned the language model with LoRA (Low-Rank Adaptation) techniques
- **Output layer**: Post-trained MLP head to generate ranking scores measuring query-document relevance
- **Training objective**: Optimized with pairwise and listwise ranking losses to produce discriminative relevance scores

This represents a significant architectural shift from our previous cross-encoder models:

|                                  | **jina-reranker-m0**                 | **jina-reranker-v2**               |
|----------------------------------|--------------------------------------|-------------------------------------|
| **Architecture**                 | Vision Language Model                | Cross-Encoder                       |
| **Base model**                   | Qwen2-VL-2B                          | Jina-XLM-RoBERTa                    |
| **Parameters**                   | 2.4 B                                | 278 M                               |
| **Max context length**           | 10,240 tokens (query + document)     | 8,192 tokens                        |
| **Image processing**             | 768 × 28 × 28 patches (dynamic resolution) | ❌                            |
| **Multilingual support**         | 29+ languages                         | Multiple languages                 |
| **Tasks supported**              | Text2Text, Text2Image,<br>Image2Text, Text2Mixed | Text2Text |

## Capabilities

- **Multimodal Understanding**: Processes both textual and visual content, including pages with mixed text, figures, tables, and various layouts
- **Long Context Processing**: Handles up to 10K tokens, enabling reranking of lengthy documents
- **Dynamic Image Resolution**: Supports images from 56×56 pixels up to 4K resolution with dynamic patch processing
- **Multilingual Support**: Effectively reranks content across 29+ languages, including bidirectional language pairs
- **Zero-shot Domain Transfer**: Performs well on unseen domains and document types without specific fine-tuning
- **Code Search**: Enhanced capabilities for programming language search and technical document ranking


Compared to `jina-reranker-v2-base-multilingual`, `jina-reranker-m0` significantly improves text reranking for multilingual content, long documents, and code searching tasks, while adding powerful new capabilities for visual document understanding.

# Usage

1. The easiest way to use `jina-reranker-m0` is to call Jina AI's [Reranker API](https://jina.ai/reranker/).

    ```bash
    curl -X POST \
      https://api.jina.ai/v1/rerank \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer JINA_API_KEY" \
      -d '{
      "model": "jina-reranker-m0",
      "query": "slm markdown",
      "documents": [
        {
          "image": "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/handelsblatt-preview.png"
        },
        {
          "image": "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png"
        },
        {
          "image": "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/wired-preview.png"
        },
        {
          "text": "We present ReaderLM-v2, a compact 1.5 billion parameter language model designed for efficient web content extraction. Our model processes documents up to 512K tokens, transforming messy HTML into clean Markdown or JSON formats with high accuracy -- making it an ideal tool for grounding large language models. The models effectiveness results from two key innovations: (1) a three-stage data synthesis pipeline that generates high quality, diverse training data by iteratively drafting, refining, and critiquing web content extraction; and (2) a unified training framework combining continuous pre-training with multi-objective optimization. Intensive evaluation demonstrates that ReaderLM-v2 outperforms GPT-4o-2024-08-06 and other larger models by 15-20% on carefully curated benchmarks, particularly excelling at documents exceeding 100K tokens, while maintaining significantly lower computational requirements."
        },
        {
          "image": "https://jina.ai/blog-banner/using-deepseek-r1-reasoning-model-in-deepsearch.webp"
        },
        {
          "text": "数据提取么？为什么不用正则啊，你用正则不就全解决了么？"
        },
        {
          "text": "During the California Gold Rush, some merchants made more money selling supplies to miners than the miners made finding gold."
        },
        {
          "text": "Die wichtigsten Beiträge unserer Arbeit sind zweifach: Erstens führen wir eine neuartige dreistufige Datensynthese-Pipeline namens Draft-Refine-Critique ein, die durch iterative Verfeinerung hochwertige Trainingsdaten generiert; und zweitens schlagen wir eine umfassende Trainingsstrategie vor, die kontinuierliches Vortraining zur Längenerweiterung, überwachtes Feintuning mit spezialisierten Kontrollpunkten, direkte Präferenzoptimierung (DPO) und iteratives Self-Play-Tuning kombiniert. Um die weitere Forschung und Anwendung der strukturierten Inhaltsextraktion zu erleichtern, ist das Modell auf Hugging Face öffentlich verfügbar."
        }
      ],
      "return_documents": false
    }'
    ```
    You will receive a JSON response with the relevance scores for each document in relation to the query. The response will look like this:

    ```json
    {
      "model":"jina-reranker-m0",
      "usage": {
        "total_tokens":2813
      },
      "results":[
        {
          "index":1,
          "relevance_score":0.9310624287463884
        },
        {
          "index":4,
          "relevance_score":0.8982678574191957
        },
        {
          "index":0,
          "relevance_score":0.890233167219021
        },
        ...
      ]
    }
    ```
    The `relevance_score` field indicates the relevance of each document to the query, with higher scores indicating greater relevance.

2. You can also use the model programmatically with the `sentence_transformers` library.

    Firstly, install Sentence Transformers:
    ```bash
    pip install sentence_transformers
    ```

    Then load the model:
    ```python
    from sentence_transformers import CrossEncoder

    model = CrossEncoder("jinaai/jina-reranker-m0", trust_remote_code=True)
    ```

    **A. Text-to-Text Reranking**
    ```python
    query = "slm markdown"
    documents = [
        "We present ReaderLM-v2, a compact 1.5 billion parameter language model designed for efficient web content extraction. Our model processes documents up to 512K tokens, transforming messy HTML into clean Markdown or JSON formats with high accuracy -- making it an ideal tool for grounding large language models. The models effectiveness results from two key innovations: (1) a three-stage data synthesis pipeline that generates high quality, diverse training data by iteratively drafting, refining, and critiquing web content extraction; and (2) a unified training framework combining continuous pre-training with multi-objective optimization. Intensive evaluation demonstrates that ReaderLM-v2 outperforms GPT-4o-2024-08-06 and other larger models by 15-20% on carefully curated benchmarks, particularly excelling at documents exceeding 100K tokens, while maintaining significantly lower computational requirements.",
        "数据提取么？为什么不用正则啊，你用正则不就全解决了么？",
        "During the California Gold Rush, some merchants made more money selling supplies to miners than the miners made finding gold.",
        "Die wichtigsten Beiträge unserer Arbeit sind zweifach: Erstens führen wir eine neuartige dreistufige Datensynthese-Pipeline namens Draft-Refine-Critique ein, die durch iterative Verfeinerung hochwertige Trainingsdaten generiert; und zweitens schlagen wir eine umfassende Trainingsstrategie vor, die kontinuierliches Vortraining zur Längenerweiterung, überwachtes Feintuning mit spezialisierten Kontrollpunkten, direkte Präferenzoptimierung (DPO) und iteratives Self-Play-Tuning kombiniert. Um die weitere Forschung und Anwendung der strukturierten Inhaltsextraktion zu erleichtern, ist das Modell auf Hugging Face öffentlich verfügbar.",
    ]

    rankings = model.rank(query, documents)
    print(rankings)
    # [{'corpus_id': 0, 'score': 0.6875}, {'corpus_id': 2, 'score': 0.5938},
    #  {'corpus_id': 3, 'score': 0.4590}, {'corpus_id': 1, 'score': 0.4434}]
    ```

    **B. Text-to-Image Reranking**
    ```python
    query = "slm markdown"
    documents = [
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/handelsblatt-preview.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/wired-preview.png",
        "https://jina.ai/blog-banner/using-deepseek-r1-reasoning-model-in-deepsearch.webp",
    ]

    scores = model.predict([(query, doc) for doc in documents])
    print(scores)
    # [0.4980 0.7813 0.4824 0.5039]
    ```

    **C. Image-to-Text Reranking**
    ```python
    query = "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png"
    documents = [
        "We present ReaderLM-v2, a compact 1.5 billion parameter language model designed for efficient web content extraction. Our model processes documents up to 512K tokens, transforming messy HTML into clean Markdown or JSON formats with high accuracy -- making it an ideal tool for grounding large language models. The models effectiveness results from two key innovations: (1) a three-stage data synthesis pipeline that generates high quality, diverse training data by iteratively drafting, refining, and critiquing web content extraction; and (2) a unified training framework combining continuous pre-training with multi-objective optimization. Intensive evaluation demonstrates that ReaderLM-v2 outperforms GPT-4o-2024-08-06 and other larger models by 15-20% on carefully curated benchmarks, particularly excelling at documents exceeding 100K tokens, while maintaining significantly lower computational requirements.",
        "数据提取么？为什么不用正则啊，你用正则不就全解决了么？",
        "During the California Gold Rush, some merchants made more money selling supplies to miners than the miners made finding gold.",
        "Die wichtigsten Beiträge unserer Arbeit sind zweifach: Erstens führen wir eine neuartige dreistufige Datensynthese-Pipeline namens Draft-Refine-Critique ein, die durch iterative Verfeinerung hochwertige Trainingsdaten generiert; und zweitens schlagen wir eine umfassende Trainingsstrategie vor, die kontinuierliches Vortraining zur Längenerweiterung, überwachtes Feintuning mit spezialisierten Kontrollpunkten, direkte Präferenzoptimierung (DPO) und iteratives Self-Play-Tuning kombiniert. Um die weitere Forschung und Anwendung der strukturierten Inhaltsextraktion zu erleichtern, ist das Modell auf Hugging Face öffentlich verfügbar.",
    ]

    scores = model.predict([(query, doc) for doc in documents])
    print(scores)
    # [0.9805 0.7773 0.5664 0.9297]
    ```

    **D. Image-to-Image Reranking**
    ```python
    query = "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png"
    documents = [
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/handelsblatt-preview.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/wired-preview.png",
        "https://jina.ai/blog-banner/using-deepseek-r1-reasoning-model-in-deepsearch.webp",
    ]

    scores = model.predict([(query, doc) for doc in documents])
    print(scores)
    # [0.6250 0.9922 0.8125 0.7930]
    ```


3. Or you can use custom methods via `trust_remote_code=True` using the `transformers` library.

    Before you start, install the `transformers` libraries:

    ```bash
    pip install transformers >= 4.47.3
    ```

    If you run it on a GPU that support FlashAttention-2. By 2024.9.12, it supports Ampere, Ada, or Hopper GPUs (e.g., A100, RTX 3090, RTX 4090, H100),

    ```bash
    pip install flash-attn --no-build-isolation
    ```

    And then use the following code snippet to load the model:

    ```python
    from transformers import AutoModel

    # comment out the flash_attention_2 line if you don't have a compatible GPU
    model = AutoModel.from_pretrained(
        'jinaai/jina-reranker-m0',
        torch_dtype="auto",
        trust_remote_code=True,
        attn_implementation="flash_attention_2"
    )

    model.to('cuda')  # or 'cpu' if no GPU is available
    model.eval()
    ```

    Now you can use the model function `compute_score` to compute the relevance scores for a query and a list of documents. The function takes a list of sentence pairs, where each pair consists of a query and a document. The model will return a list of scores indicating the relevance of each document to the query.

    **A. Visual Documents Reranking**

    For handling the image documents, you can use the following code snippet:
    ```python
    # Example query and documents
    query = "slm markdown"
    documents = [
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/handelsblatt-preview.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/wired-preview.png",
        "https://jina.ai/blog-banner/using-deepseek-r1-reasoning-model-in-deepsearch.webp"
    ]

    # construct sentence pairs
    image_pairs = [[query, doc] for doc in documents]

    scores = model.compute_score(image_pairs, max_length=2048, doc_type="image")
    # [0.49375027418136597, 0.7889736890792847, 0.47813892364501953, 0.5210812091827393]
    ```

    **B. Textual Documents Reranking**

    ```python
    query = "slm markdown"
    documents = [
        "We present ReaderLM-v2, a compact 1.5 billion parameter language model designed for efficient web content extraction. Our model processes documents up to 512K tokens, transforming messy HTML into clean Markdown or JSON formats with high accuracy -- making it an ideal tool for grounding large language models. The models effectiveness results from two key innovations: (1) a three-stage data synthesis pipeline that generates high quality, diverse training data by iteratively drafting, refining, and critiquing web content extraction; and (2) a unified training framework combining continuous pre-training with multi-objective optimization. Intensive evaluation demonstrates that ReaderLM-v2 outperforms GPT-4o-2024-08-06 and other larger models by 15-20% on carefully curated benchmarks, particularly excelling at documents exceeding 100K tokens, while maintaining significantly lower computational requirements.",
        "数据提取么？为什么不用正则啊，你用正则不就全解决了么？",
        "During the California Gold Rush, some merchants made more money selling supplies to miners than the miners made finding gold.",
        "Die wichtigsten Beiträge unserer Arbeit sind zweifach: Erstens führen wir eine neuartige dreistufige Datensynthese-Pipeline namens Draft-Refine-Critique ein, die durch iterative Verfeinerung hochwertige Trainingsdaten generiert; und zweitens schlagen wir eine umfassende Trainingsstrategie vor, die kontinuierliches Vortraining zur Längenerweiterung, überwachtes Feintuning mit spezialisierten Kontrollpunkten, direkte Präferenzoptimierung (DPO) und iteratives Self-Play-Tuning kombiniert. Um die weitere Forschung und Anwendung der strukturierten Inhaltsextraktion zu erleichtern, ist das Modell auf Hugging Face öffentlich verfügbar.",
    ]

    # construct sentence pairs
    text_pairs = [[query, doc] for doc in documents]

    scores = model.compute_score(text_pairs, max_length=1024, doc_type="text")
    ```

    The scores will be a list of floats, where each float represents the relevance score of the corresponding document to the query. Higher scores indicate higher relevance.
    For instance the returning scores in this case will be:
    ```bash
    [0.6839263439178467, 0.4432148039340973, 0.5904013514518738, 0.45481112599372864]
    ```

    **C. Image Querying for Textual Documents**

    The model also supports querying textual documents with an image query. You can use the following code snippet:

    ```python
    query = "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png"

    documents = [
        "We present ReaderLM-v2, a compact 1.5 billion parameter language model designed for efficient web content extraction. Our model processes documents up to 512K tokens, transforming messy HTML into clean Markdown or JSON formats with high accuracy -- making it an ideal tool for grounding large language models. The models effectiveness results from two key innovations: (1) a three-stage data synthesis pipeline that generates high quality, diverse training data by iteratively drafting, refining, and critiquing web content extraction; and (2) a unified training framework combining continuous pre-training with multi-objective optimization. Intensive evaluation demonstrates that ReaderLM-v2 outperforms GPT-4o-2024-08-06 and other larger models by 15-20% on carefully curated benchmarks, particularly excelling at documents exceeding 100K tokens, while maintaining significantly lower computational requirements.",
        "数据提取么？为什么不用正则啊，你用正则不就全解决了么？",
        "During the California Gold Rush, some merchants made more money selling supplies to miners than the miners made finding gold.",
        "Die wichtigsten Beiträge unserer Arbeit sind zweifach: Erstens führen wir eine neuartige dreistufige Datensynthese-Pipeline namens Draft-Refine-Critique ein, die durch iterative Verfeinerung hochwertige Trainingsdaten generiert; und zweitens schlagen wir eine umfassende Trainingsstrategie vor, die kontinuierliches Vortraining zur Längenerweiterung, überwachtes Feintuning mit spezialisierten Kontrollpunkten, direkte Präferenzoptimierung (DPO) und iteratives Self-Play-Tuning kombiniert. Um die weitere Forschung und Anwendung der strukturierten Inhaltsextraktion zu erleichtern, ist das Modell auf Hugging Face öffentlich verfügbar.",
    ]
    # reverse the order of the query and document
    image_pairs = [[query, doc] for doc in documents]
    scores = model.compute_score(image_pairs, max_length=2048, query_type="image", doc_type="text")

    # [0.98099285364151, 0.7701883316040039, 0.5637142062187195, 0.9308615922927856]
    ```

    **D. Image Querying for Image Documents**

    The model also supports querying image documents with an image query. You can use the following code snippet:

    ```python
    query = "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png"

    documents = [
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/handelsblatt-preview.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/paper-11.png",
        "https://raw.githubusercontent.com/jina-ai/multimodal-reranker-test/main/wired-preview.png",
        "https://jina.ai/blog-banner/using-deepseek-r1-reasoning-model-in-deepsearch.webp"
    ]

    image_pairs = [[query, doc] for doc in documents]
    scores = model.compute_score(image_pairs, max_length=2048, doc_type="image", query_type='image')
    # [0.6275860667228699, 0.9922324419021606, 0.8090347051620483, 0.7941296100616455]
    ```

# Model Performance

Performance of the jina-reranker-m0 on ViDoRe, MBEIR, and Winoground visual retrieval benchmarks showcases its capabilities across diverse multimodal retrieval tasks spanning multiple domains and languages. Each dot represents performance scores for different types of visual documents. The boxplots illustrate the distribution of these scores, with the highlighted numbers indicating the average (mean) performance. For complete benchmark results, please refer to the appendix of this post.

We conduct extensive evaluations on the performance of the model across various visual retrieval benchmarks.

![Model performance comparison across benchmarks](https://jina-ai-gmbh.ghost.io/content/images/size/w1600/2025/04/all-benchmarks--6-.png)

As shown in the figure above, the performance of the `jina-reranker-m0` on `ViDoRe`, `MBEIR`, and `Winoground` visual retrieval benchmarks showcases its capabilities across diverse multimodal retrieval tasks spanning multiple domains and languages. Each dot represents performance scores for different types of visual documents. The boxplots illustrate the distribution of these scores, with the highlighted numbers indicating the average (mean) performance.

We also evaluate the performance of the `jina-reranker-m0` across four text-to-text reranking benchmarks. Each benchmark may include multiple datasets, languages, or tasks, represented by individual dots inside the boxplot. The boxplot shows the distribution of these scores, with the highlighted number showing the average (mean) performance. While most benchmarks use NDCG@10 as their performance metric, MKQA uses recall@10 instead, as MKQA's annotation data doesn't support NDCG calculation (the official evaluation uses recall, which determines document relevance through heuristics).

![Model performance comparison across text-to-text benchmarks](https://jina-ai-gmbh.ghost.io/content/images/size/w1600/2025/04/model-perf-boxplot--13-.png)

For complete benchmark results, please refer to the [online results table](https://docs.google.com/spreadsheets/d/1KrCD7l0lhzMkyg3z-gEDmymxe4Eun9Z-C0kU3_cxw7Q/edit?usp=sharing).




# Contact

Join our [Discord community](https://discord.jina.ai/) and chat with other community members about ideas.

# License

`jina-reranker-m0` is listed on AWS & Azure. If you need to use it beyond those platforms or on-premises within your company, note that the models is licensed under CC BY-NC 4.0. For commercial usage inquiries, feel free to [contact us](https://jina.ai/contact-sales/).
