#!/usr/bin/env python3

import sys
import json
import os
import math
from typing import List, Tuple

import numpy as np
import torch
import cv2
from transformers import AutoModel
from decord import VideoReader, cpu
import contextlib

"""
iv2_runner.py
- Loads InternVideo2 and generates per-scene visual embeddings.

INPUT (via STDIN, JSON):
{
  "video_path": "/data/videos/ginger.mp4",
  "scenes": [ {"scene_index": 0, "start": 5.13, "end": 6.79}, ... ],
  "sampling": {"frames": 16, "stride": 4, "resolution": 224},
  "device": "cuda:0",
  "model_id": "OpenGVLab/InternVideo2-Stage2_1B-224p-f4"
}

OUTPUT (to STDOUT, JSON on success):
{
  "model": "...",
  "embedding_dim": <int>,
  "vectors": [ {"scene_index": 0, "vector": [ ... ]}, ... ]
}
"""

CLIP_MEAN = [0.48145466, 0.4578275, 0.40821073]
CLIP_STD = [0.26862954, 0.26130258, 0.27577711]
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def sample_indices_mid(center_idx: int, total_frames: int, T: int, stride: int) -> List[int]:
    half = (T // 2)
    start = center_idx - half * stride
    # Adjust if start < 0
    if start < 0:
        start = 0
    indices = [int(start + i * stride) for i in range(T)]
    # Clamp to total_frames-1
    indices = [min(max(0, idx), total_frames - 1) for idx in indices]
    return indices


def resize_frames(frames: np.ndarray, size: int) -> np.ndarray:
    # frames: (T, H, W, C), RGB uint8
    out = []
    for f in frames:
        f_res = cv2.resize(f, (size, size), interpolation=cv2.INTER_LINEAR)
        out.append(f_res)
    return np.stack(out, axis=0)


def to_tensor(frames: np.ndarray, device: str) -> torch.Tensor:
    # frames: (T, H, W, C) RGB uint8
    arr = frames.astype(np.float32) / 255.0
    # to (T, C, H, W)
    arr = np.transpose(arr, (0, 3, 1, 2))
    x = torch.from_numpy(arr).to(device)
    mean = torch.tensor(CLIP_MEAN, device=device).view(1, 3, 1, 1)
    std = torch.tensor(CLIP_STD, device=device).view(1, 3, 1, 1)
    x = (x - mean) / std
    # add batch: (1, T, C, H, W)
    x = x.unsqueeze(0)
    return x


def frames_to_imagenet_tensor(frames: np.ndarray, size: int, device: str) -> torch.Tensor:
    # frames: (T, H, W, C) RGB uint8 -> resize to (size,size), normalize ImageNet -> (T, C, H, W)
    out = []
    for f in frames:
        f_res = cv2.resize(f, (size, size), interpolation=cv2.INTER_LINEAR)
        arr = f_res.astype(np.float32) / 255.0
        arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
        arr = np.transpose(arr, (2, 0, 1))  # C,H,W
        out.append(arr)
    arr = np.stack(out, axis=0)
    x = torch.from_numpy(arr).to(device)
    return x  # (T, C, H, W)


def extract_scene_tensor(vr: VideoReader, fps: float, start: float, end: float, T: int, stride: int, res: int, device: str) -> torch.Tensor:
    total = len(vr)
    # center sample at mid-time
    mid = (start + end) / 2.0
    center_idx = int(round(mid * fps))
    center_idx = max(0, min(center_idx, total - 1))
    idxs = sample_indices_mid(center_idx, total, T, stride)
    # fetch frames
    batch = vr.get_batch(idxs)  # decord NDArray -> (T, H, W, C) RGB
    frames = batch.asnumpy()
    frames = resize_frames(frames, res)
    return to_tensor(frames, device)


def extract_scene_frames(vr: VideoReader, fps: float, start: float, end: float, T: int, stride: int) -> np.ndarray:
    total = len(vr)
    mid = (start + end) / 2.0
    center_idx = int(round(mid * fps))
    center_idx = max(0, min(center_idx, total - 1))
    idxs = sample_indices_mid(center_idx, total, T, stride)
    batch = vr.get_batch(idxs)
    frames = batch.asnumpy()  # (T, H, W, C) RGB
    return frames


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
        video_path = payload.get("video_path")
        scenes = payload.get("scenes", [])
        sampling = payload.get("sampling", {})
        device = payload.get("device", "cuda:0")
        model_id = payload.get("model_id", "OpenGVLab/InternVideo2-Stage2_1B-224p-f4")

        if not video_path or not isinstance(scenes, list) or len(scenes) == 0:
            print(json.dumps({"error": "invalid input: video_path and scenes are required"}))
            return

        backend = payload.get("backend", "iv2")
        frames = int(sampling.get("frames", 16))
        stride = int(sampling.get("stride", 4))
        res = int(sampling.get("resolution", 224))

        use_cuda = device.startswith("cuda") and torch.cuda.is_available()
        torch_device = torch.device(device if use_cuda else "cpu")

        # Load model (pass token explicitly for gated repos)
        try:
            hf_token = os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
            # Redirect potential library stdout messages to stderr so our stdout stays pure JSON
            with contextlib.redirect_stdout(sys.stderr):
                model = AutoModel.from_pretrained(model_id, trust_remote_code=True, token=hf_token)
        except Exception as e:
            print(json.dumps({"error": f"failed to load model: {e}"}))
            return
        model.eval().to(torch_device)

        # Open video once
        try:
            vr = VideoReader(video_path, ctx=cpu(0))
        except Exception as e:
            print(json.dumps({"error": f"failed to open video: {e}"}))
            return
        fps = float(vr.get_avg_fps()) if hasattr(vr, 'get_avg_fps') else 30.0
        if math.isfinite(fps) is False or fps <= 0:
            fps = 30.0

        results = []
        embedding_dim = None

        if backend == "internvl35":
            # Use InternVL3.5 vision encoder per-frame, average to scene vector
            vm = getattr(model, "vision_model", None)
            if vm is None:
                print(json.dumps({"error": "model does not expose vision_model for internvl35 backend"}))
                return
            for s in scenes:
                try:
                    si = int(s.get("scene_index"))
                    st = float(s.get("start", 0.0))
                    et = float(s.get("end", st + 0.1))
                except Exception:
                    continue
                frames_np = extract_scene_frames(vr, fps, st, et, frames, stride)
                x = frames_to_imagenet_tensor(frames_np, res, str(torch_device))  # (T,C,H,W)
                # Keep float32 to avoid dtype mismatch with model biases
                with torch.no_grad():
                    out = vm(pixel_values=x, output_hidden_states=False, return_dict=True)
                    feats = out.pooler_output  # (T, D)
                    scene_vec = feats.mean(dim=0, keepdim=True).detach().cpu().numpy()[0]
                if embedding_dim is None:
                    embedding_dim = int(scene_vec.shape[0])
                results.append({"scene_index": si, "vector": scene_vec.astype(float).tolist()})
        else:
            # Default IV2 path using get_vid_feat
            tensors = []
            scene_indices = []
            for s in scenes:
                try:
                    si = int(s.get("scene_index"))
                    st = float(s.get("start", 0.0))
                    et = float(s.get("end", st + 0.1))
                except Exception:
                    continue
                ten = extract_scene_tensor(vr, fps, st, et, frames, stride, res, str(torch_device))
                tensors.append(ten)
                scene_indices.append(si)

            if not tensors:
                print(json.dumps({"error": "no valid scenes to process"}))
                return

            batch = torch.cat(tensors, dim=0)  # (B, T, C, H, W)
            try:
                with torch.no_grad():
                    feat = model.get_vid_feat(batch.to(torch_device))
            except Exception:
                try:
                    alt = batch.permute(0, 2, 1, 3, 4).contiguous()
                    with torch.no_grad():
                        feat = model.get_vid_feat(alt.to(torch_device))
                except Exception as e2:
                    print(json.dumps({"error": f"inference failed: {e2}"}))
                    return

            if isinstance(feat, (list, tuple)):
                feat = feat[0]
            if hasattr(feat, 'detach'):
                feat = feat.detach().cpu()
            vecs = feat.numpy()
            if vecs.ndim == 1:
                vecs = vecs[None, :]
            embedding_dim = int(vecs.shape[1])
            for i, si in enumerate(scene_indices):
                results.append({
                    "scene_index": int(si),
                    "vector": vecs[i].astype(float).tolist(),
                })

        print(json.dumps({
            "model": model_id,
            "embedding_dim": embedding_dim,
            "vectors": results,
        }))
    except Exception as e:
        print(json.dumps({"error": f"runner exception: {e}"}))


if __name__ == "__main__":
    main()
