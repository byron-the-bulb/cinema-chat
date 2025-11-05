#!/usr/bin/env python3
import sys
import json
import os
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
    idx = int(round(mid * fps))
    idx = max(0, min(idx, total - 1))
    frame = vr.get_batch([idx]).asnumpy()[0]  # (H, W, C) RGB uint8
    return frame


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

    # image mode (per-scene image embedding from frame)
    video_path = payload.get("video_path")
    scenes = payload.get("scenes", [])
    if not video_path or not isinstance(scenes, list) or len(scenes) == 0:
        print(json.dumps({"error": "invalid input: video_path and scenes are required for image mode"}))
        return

    try:
        vr = VideoReader(video_path, ctx=cpu(0))
    except Exception as e:
        print(json.dumps({"error": f"failed to open video: {e}"}))
        return

    results = []
    images = []
    scene_indices = []
    for s in scenes:
        try:
            si = int(s.get("scene_index"))
            st = float(s.get("start", 0.0))
            et = float(s.get("end", st + 0.1))
        except Exception:
            continue
        frame = sample_scene_frame(vr, st, et)  # (H, W, C) RGB uint8
        images.append(frame)
        scene_indices.append(si)

    if not images:
        print(json.dumps({"error": "no valid scenes to process"}))
        return

    with torch.no_grad():
        if backend == 'open_clip':
            pil_images = [Image.fromarray(img) for img in images]
            enc_imgs = torch.stack([proc(im).to(device) for im in pil_images], dim=0)
            feats = model.encode_image(enc_imgs)
        else:
            enc = proc(images=images, return_tensors="pt")
            enc = to_device(enc, device)
            feats = model.get_image_features(**enc)
        feats = l2_normalize(feats)

    D = int(feats.shape[1])
    for i, si in enumerate(scene_indices):
        results.append({"scene_index": si, "vector": to_list(feats[i])})

    print(json.dumps({
        "model": f"{backend}:{model_id}",
        "embedding_dim": D,
        "vectors": results,
    }))


if __name__ == "__main__":
    main()
