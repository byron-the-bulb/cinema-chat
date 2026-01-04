#!/usr/bin/env python3
import sys
import json
import os
import math
from typing import List, Dict, Any

import numpy as np
import torch
from decord import VideoReader, cpu
from PIL import Image
import contextlib

try:
    import open_clip  # preferred path
    HAS_OPEN_CLIP = True
except Exception:
    HAS_OPEN_CLIP = False
    from transformers import CLIPModel, CLIPProcessor  # fallback


def l2_normalize(x: torch.Tensor) -> torch.Tensor:
    return torch.nn.functional.normalize(x, p=2, dim=-1)


def to_list(x: torch.Tensor) -> List[float]:
    return x.detach().cpu().to(torch.float32).numpy().astype(np.float32).tolist()


def read_payload() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        sys.exit(0)


def time_to_index(vr: VideoReader, fps: float, t: float) -> int:
    total = len(vr)
    if total == 0:
        return 0
    if t <= 0:
        return 0

    lo, hi = 0, total - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            ts_start, _ = vr.get_frame_timestamp(mid)
        except Exception:
            break
        if ts_start <= t:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    else:
        return best

    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    idx = int(round(t * fps))
    return max(0, min(idx, total - 1))


def _resolve_open_clip_spec(model_id: str):
    # Map HF-like IDs to open_clip specs
    model_name = 'ViT-B-32'
    pretrained = 'openai'
    mid = (model_id or '').lower()
    if 'laion' in mid:
        pretrained = 'laion2b_s34b_b79k'
    return model_name, pretrained


def load_model(model_id: str):
    if HAS_OPEN_CLIP:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                model_name, pretrained = _resolve_open_clip_spec(model_id)
                model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=pretrained)
                tokenizer = open_clip.get_tokenizer(model_name)
            return (model, preprocess, tokenizer, 'open_clip')
        except Exception as e:
            # fall through to transformers
            pass
    # Fallback to transformers
    try:
        with contextlib.redirect_stdout(sys.stderr):
            t_model = CLIPModel.from_pretrained(model_id or 'openai/clip-vit-base-patch32', use_safetensors=True)
            t_proc = CLIPProcessor.from_pretrained(model_id or 'openai/clip-vit-base-patch32')
        return (t_model, t_proc, None, 'transformers')
    except Exception as e:
        print(json.dumps({"error": f"failed to load CLIP: {e}"}))
        sys.exit(0)


def to_device(x, device: str):
    return {k: v.to(device) for k, v in x.items()}


def sample_scene_frame(vr: VideoReader, start: float, end: float) -> np.ndarray:
    total = len(vr)
    fps = float(vr.get_avg_fps()) if hasattr(vr, 'get_avg_fps') else 30.0
    mid = (start + end) / 2.0
    idx = time_to_index(vr, fps, mid)
    frame = vr.get_batch([idx]).asnumpy()[0]  # (H, W, C) RGB uint8
    return frame


def sample_scene_frames_multi(vr: VideoReader, start: float, end: float, target_fps: float = 5.0, max_frames: int = 32) -> List[np.ndarray]:
    total = len(vr)
    fps = float(vr.get_avg_fps()) if hasattr(vr, 'get_avg_fps') else 30.0
    if end <= start:
        return [sample_scene_frame(vr, start, end)]

    duration = max(end - start, 1e-3)
    n = int(duration * target_fps)
    if n <= 0:
        n = 1
    if n > max_frames:
        n = max_frames

    idxs: List[int] = []
    last_idx = None
    for i in range(n):
        t = start + (duration * (i + 0.5) / n)
        idx = time_to_index(vr, fps, t)
        if last_idx is None or idx != last_idx:
            idxs.append(idx)
            last_idx = idx
    batch = vr.get_batch(idxs).asnumpy()
    return [batch[i] for i in range(batch.shape[0])]


def main():
    payload = read_payload()
    mode = payload.get("mode", "text")  # "text" or "image"
    model_id = os.environ.get("CLIP_MODEL_ID", "openai/clip-vit-base-patch32")

    model, proc, tokenizer, backend = load_model(model_id)
    device = os.environ.get("CLIP_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    if backend == 'open_clip':
        model = model.to(device)
        model.eval()
    else:
        model = model.to(device)
        model.eval()

    if mode == "text":
        texts: List[str] = []
        if "texts" in payload and isinstance(payload["texts"], list):
            texts = [str(t) for t in payload["texts"]]
        elif "text" in payload:
            texts = [str(payload["text"])]
        else:
            print(json.dumps({"error": "missing 'text' or 'texts' in payload"}))
            return
        with torch.no_grad():
            if backend == 'open_clip':
                tok = tokenizer(texts)
                feats = model.encode_text(tok.to(device))
            else:
                enc = proc(text=texts, return_tensors="pt", padding=True, truncation=True)
                enc = to_device(enc, device)
                feats = model.get_text_features(**enc)
            feats = l2_normalize(feats)
        out = {"model": f"{backend}:{model_id}", "embedding_dim": int(feats.shape[1])}
        if feats.shape[0] == 1:
            out["vector"] = to_list(feats[0])
        else:
            out["vectors"] = [to_list(v) for v in feats]
        print(json.dumps(out))
        return

    # image mode (per-scene image embedding from multiple frames)
    video_path = payload.get("video_path")
    scenes = payload.get("scenes", [])
    target_fps = float(payload.get("target_fps", 5.0))
    if not video_path or not isinstance(scenes, list) or len(scenes) == 0:
        print(json.dumps({"error": "invalid input: video_path and scenes are required for image mode"}))
        return

    try:
        vr = VideoReader(video_path, ctx=cpu(0))
    except Exception as e:
        print(json.dumps({"error": f"failed to open video: {e}"}))
        return

    results = []
    D = None
    for s in scenes:
        try:
            si = int(s.get("scene_index"))
            st = float(s.get("start", 0.0))
            et = float(s.get("end", st + 0.1))
        except Exception:
            continue

        frames = sample_scene_frames_multi(vr, st, et, target_fps=target_fps)
        if not frames:
            continue

        with torch.no_grad():
            if backend == 'open_clip':
                pil_images = [Image.fromarray(img) for img in frames]
                enc_imgs = torch.stack([proc(im).to(device) for im in pil_images], dim=0)
                feats = model.encode_image(enc_imgs)
            else:
                enc = proc(images=frames, return_tensors="pt")
                enc = to_device(enc, device)
                feats = model.get_image_features(**enc)
            feats = l2_normalize(feats)

        # Ensure 2D tensor
        if feats.ndim == 1:
            feats = feats.unsqueeze(0)

        if D is None:
            D = int(feats.shape[1])

        # Average frame embeddings to a single scene vector
        vec = feats.mean(dim=0, keepdim=True)[0]
        results.append({"scene_index": si, "vector": to_list(vec)})

    if not results:
        print(json.dumps({"error": "no valid scenes to process"}))
        return

    print(json.dumps({
        "model": f"{backend}:{model_id}",
        "embedding_dim": D if D is not None else 0,
        "vectors": results,
    }))


if __name__ == "__main__":
    main()
