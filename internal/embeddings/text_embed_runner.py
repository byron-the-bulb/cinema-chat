#!/usr/bin/env python3
import sys
import json
import os
from typing import List

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
import contextlib


def mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    # token_embeddings: [batch, seq, hidden]
    # attention_mask: [batch, seq]
    mask = attention_mask.unsqueeze(-1).type_as(token_embeddings)  # [batch, seq, 1]
    masked = token_embeddings * mask
    summed = masked.sum(dim=1)  # [batch, hidden]
    counts = mask.sum(dim=1).clamp(min=1e-9)  # [batch, 1]
    return summed / counts


def normalize_l2(x: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.normalize(x, p=2, dim=1)


def to_python_floats(x: torch.Tensor) -> List[List[float]]:
    return x.detach().cpu().to(torch.float32).numpy().astype(np.float32).tolist()


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return

    texts: List[str] = []
    mode = payload.get("mode", "query")  # "query" or "passage"

    if "texts" in payload and isinstance(payload["texts"], list):
        texts = [str(t) for t in payload["texts"]]
    elif "text" in payload:
        texts = [str(payload["text"])]
    else:
        print(json.dumps({"error": "missing 'text' or 'texts' in payload"}))
        return

    prefixes = {
        "query": "query: ",
        "passage": "passage: ",
    }
    prefix = prefixes.get(mode, "query: ")
    texts = [prefix + t for t in texts]

    model_id = os.environ.get("E5_MODEL_ID", "intfloat/e5-base-v2")

    try:
        # keep stdout clean for JSON only
        with contextlib.redirect_stdout(sys.stderr):
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            model = AutoModel.from_pretrained(model_id)
    except Exception as e:
        print(json.dumps({"error": f"failed to load model: {e}"}))
        return

    device = os.environ.get("E5_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    # Batch texts to avoid CUDA OOM on large workloads.
    try:
        batch_size = int(os.environ.get("E5_BATCH_SIZE", "64"))
        if batch_size <= 0:
            batch_size = 64
    except Exception:
        batch_size = 64

    all_embs: List[List[float]] = []
    try:
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            enc = tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.no_grad():
                out = model(**enc)
                token_embeddings = out.last_hidden_state  # [b, s, h]
                pooled = mean_pooling(token_embeddings, enc["attention_mask"])  # [b, h]
                normed = normalize_l2(pooled)
            all_embs.extend(to_python_floats(normed))
    except Exception as e:
        print(json.dumps({"error": f"failed to compute embeddings: {e}"}))
        return

    if not all_embs:
        print(json.dumps({"error": "no embeddings computed"}))
        return

    result = {
        "model": model_id,
        "embedding_dim": len(all_embs[0]),
    }
    if len(all_embs) == 1:
        result["vector"] = all_embs[0]
    else:
        result["vectors"] = all_embs

    print(json.dumps(result))


if __name__ == "__main__":
    main()
