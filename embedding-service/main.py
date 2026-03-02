"""
Persistent text embedding service for TwistedTV / GoodCLIPS.

Loads intfloat/e5-base-v2 once at startup and serves embeddings via HTTP.
Replaces the per-query Python subprocess that was adding 3-5s of latency.
"""

import os
import logging
from contextlib import asynccontextmanager

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("embedding-service")

# Globals populated at startup
tokenizer = None
model = None
device = None
model_id = None


def mean_pooling(token_embeddings: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).type_as(token_embeddings)
    summed = (token_embeddings * mask).sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model, device, model_id

    model_id = os.environ.get("E5_MODEL_ID", "intfloat/e5-base-v2")
    device = os.environ.get("E5_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")

    logger.info(f"Loading model {model_id} on {device}...")
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModel.from_pretrained(model_id)
    model.to(device)
    model.eval()
    logger.info(f"Model loaded: {model_id} ({device})")

    yield

    logger.info("Shutting down embedding service")


app = FastAPI(title="TwistedTV Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    text: str
    mode: str = "query"  # "query" or "passage"


class EmbedBatchRequest(BaseModel):
    texts: list[str]
    mode: str = "query"


class EmbedResponse(BaseModel):
    vector: list[float]
    model: str
    embedding_dim: int


class EmbedBatchResponse(BaseModel):
    vectors: list[list[float]]
    model: str
    embedding_dim: int


def compute_embeddings(texts: list[str], mode: str) -> list[list[float]]:
    prefixes = {"query": "query: ", "passage": "passage: "}
    prefix = prefixes.get(mode, "query: ")
    prefixed = [prefix + t for t in texts]

    enc = tokenizer(
        prefixed,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    enc = {k: v.to(device) for k, v in enc.items()}

    with torch.no_grad():
        out = model(**enc)
        pooled = mean_pooling(out.last_hidden_state, enc["attention_mask"])
        normed = torch.nn.functional.normalize(pooled, p=2, dim=1)

    return normed.detach().cpu().to(torch.float32).numpy().astype(np.float32).tolist()


@app.post("/embed", response_model=EmbedResponse)
async def embed_single(req: EmbedRequest):
    vectors = compute_embeddings([req.text], req.mode)
    return EmbedResponse(
        vector=vectors[0],
        model=model_id,
        embedding_dim=len(vectors[0]),
    )


@app.post("/embed/batch", response_model=EmbedBatchResponse)
async def embed_batch(req: EmbedBatchRequest):
    vectors = compute_embeddings(req.texts, req.mode)
    return EmbedBatchResponse(
        vectors=vectors,
        model=model_id,
        embedding_dim=len(vectors[0]) if vectors else 0,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": model_id, "device": str(device)}
