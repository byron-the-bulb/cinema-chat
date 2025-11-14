#!/usr/bin/env python3
import sys
import json
import os
from typing import List, Dict, Any

import numpy as np
import torch
import librosa
from transformers import ClapModel, ClapProcessor
import contextlib


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


def main():
    payload = read_payload()
    mode = payload.get("mode", "audio")  # "audio" or "text"
    model_id = os.environ.get("CLAP_MODEL_ID", "laion/clap-htsat-fused")

    try:
        with contextlib.redirect_stdout(sys.stderr):
            model = ClapModel.from_pretrained(model_id, use_safetensors=True)
            processor = ClapProcessor.from_pretrained(model_id)
    except Exception as e:
        print(json.dumps({"error": f"failed to load CLAP: {e}"}))
        return

    device = os.environ.get("CLAP_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    model.eval()

    if mode == "text":
        # Text query embedding path
        texts: List[str] = []
        if "texts" in payload and isinstance(payload["texts"], list):
            texts = [str(t) for t in payload["texts"]]
        elif "text" in payload:
            texts = [str(payload["text"])]
        else:
            print(json.dumps({"error": "missing 'text' or 'texts' in payload"}))
            return
        with torch.no_grad():
            inputs = processor(text=texts, return_tensors="pt", padding=True, truncation=True)
            inputs = {k: v.to(device) for k, v in inputs.items()}
            feats = model.get_text_features(**inputs)
            feats = l2_normalize(feats)
        D = int(feats.shape[1])
        out = {"model": model_id, "embedding_dim": D}
        if feats.shape[0] == 1:
            out["vector"] = to_list(feats[0])
        else:
            out["vectors"] = [to_list(v) for v in feats]
        print(json.dumps(out))
        return

    # Audio per‑scene mode
    video_path = payload.get("video_path")
    scenes = payload.get("scenes", [])
    sample_rate = int(payload.get("sample_rate", 48000))

    if not video_path or not isinstance(scenes, list) or len(scenes) == 0:
        print(json.dumps({"error": "invalid input: video_path and scenes are required"}))
        return

    results = []
    D = None

    for s in scenes:
        try:
            si = int(s.get("scene_index"))
            st = float(s.get("start", 0.0))
            et = float(s.get("end", st + 0.1))
            dur = max(0.1, et - st)
        except Exception:
            continue
        try:
            # librosa can decode from video containers via audioread/ffmpeg
            y, sr = librosa.load(video_path, sr=sample_rate, mono=True, offset=st, duration=dur)
            if y is None or y.size == 0:
                continue
        except Exception as e:
            # skip this scene on decode error
            continue
        with torch.no_grad():
            inputs = processor(audios=[y], sampling_rate=sr, return_tensors="pt")
            inputs = {k: v.to(device) for k, v in inputs.items()}
            feats = model.get_audio_features(**inputs)  # (1, D)
            feats = l2_normalize(feats)
        if D is None:
            D = int(feats.shape[1])
        results.append({"scene_index": si, "vector": to_list(feats[0])})

    if D is None:
        print(json.dumps({"error": "no audio embeddings produced"}))
        return

    print(json.dumps({
        "model": model_id,
        "embedding_dim": D,
        "vectors": results,
    }))


if __name__ == "__main__":
    main()
