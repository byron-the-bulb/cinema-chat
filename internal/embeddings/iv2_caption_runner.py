#!/usr/bin/env python3
import sys
import json
import os
import math
from typing import Any, Dict, List, Tuple

import torch
from transformers import AutoModel, AutoTokenizer
from decord import VideoReader, cpu
import contextlib
from PIL import Image
import torchvision.transforms as T
from torchvision.transforms.functional import InterpolationMode

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def read_payload() -> Dict[str, Any]:
    raw = sys.stdin.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        sys.exit(0)


def load_model_and_tokenizer(model_id: str, device: str) -> Tuple[Any, Any]:
    hf_token = os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True, token=hf_token)
            model = AutoModel.from_pretrained(model_id, trust_remote_code=True, token=hf_token)
    except Exception as e:
        print(json.dumps({"error": f"failed to load model: {e}"}))
        sys.exit(0)
    model.to(device)
    model.eval()
    return tokenizer, model


def open_video(video_path: str) -> Tuple[VideoReader, float]:
    try:
        vr = VideoReader(video_path, ctx=cpu(0))
    except Exception as e:
        print(json.dumps({"error": f"failed to open video: {e}"}))
        sys.exit(0)
    if hasattr(vr, "get_avg_fps"):
        try:
            fps = float(vr.get_avg_fps())
        except Exception:
            fps = 30.0
    else:
        fps = 30.0
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    return vr, fps


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

    # Fallback to naive mapping if get_frame_timestamp is not usable
    if not math.isfinite(fps) or fps <= 0:
        fps = 30.0
    idx = int(round(t * fps))
    return max(0, min(idx, total - 1))


def build_transform(input_size: int):
    mean, std = IMAGENET_MEAN, IMAGENET_STD
    transform = T.Compose([
        T.Lambda(lambda img: img.convert("RGB") if img.mode != "RGB" else img),
        T.Resize((input_size, input_size), interpolation=InterpolationMode.BICUBIC),
        T.ToTensor(),
        T.Normalize(mean=mean, std=std),
    ])
    return transform


def select_scene_frames(
    vr: VideoReader,
    fps: float,
    start: float,
    end: float,
    target_fps: float,
    max_frames: int,
) -> List[Image.Image]:
    total = len(vr)
    if total == 0:
        return []
    if target_fps <= 0:
        target_fps = 5.0
    if max_frames <= 0:
        max_frames = 1

    if not math.isfinite(start):
        start = 0.0
    if not math.isfinite(end) or end <= start:
        end = start + 0.1

    duration = max(end - start, 1e-3)
    n = int(duration * target_fps)
    if n <= 0:
        n = 1
    if n > max_frames:
        n = max_frames

    times: List[float] = [start + (duration * (i + 0.5) / n) for i in range(n)]
    idxs: List[int] = []
    last_idx = None
    for t in times:
        idx = time_to_index(vr, fps, t)
        if last_idx is None or idx != last_idx:
            idxs.append(idx)
            last_idx = idx

    if not idxs:
        idxs = [time_to_index(vr, fps, start)]

    batch = vr.get_batch(idxs)
    frames = batch.asnumpy()
    images: List[Image.Image] = []
    for i in range(frames.shape[0]):
        images.append(Image.fromarray(frames[i]).convert("RGB"))
    return images


def generate_caption(model: Any, tokenizer: Any, images: List[Image.Image], question: str, device: str) -> str:
    if not images:
        raise RuntimeError("no images provided for captioning")

    # Convert frames to InternVL-style pixel_values tensor with ImageNet normalization.
    input_size = 448
    transform = build_transform(input_size)
    frame_tensors: List[torch.Tensor] = []
    for img in images:
        frame_tensors.append(transform(img))  # (3, H, W)
    pixel_values = torch.stack(frame_tensors, dim=0)  # (F, 3, H, W)

    # Map to device
    if device.startswith("cuda") and torch.cuda.is_available():
        torch_device = torch.device(device)
    else:
        torch_device = torch.device("cpu")
    # Keep default float32 to match model biases
    pixel_values = pixel_values.to(device=torch_device)

    # One patch per frame; num_patches_list length must match number of <image> tokens.
    num_frames = pixel_values.size(0)
    num_patches_list = [1] * num_frames

    # Build video-style question prefix with one <image> token per frame.
    prefix = "".join(f"Frame{i+1}: <image>\\n" for i in range(num_frames))
    full_question = prefix + question

    generation_config = dict(max_new_tokens=256, do_sample=False)

    if not hasattr(model, "chat"):
        raise RuntimeError("model object has no chat(...) method")

    try:
        with torch.no_grad():
            out = model.chat(
                tokenizer,
                pixel_values,
                full_question,
                generation_config,
                num_patches_list=num_patches_list,
                history=None,
                return_history=False,
            )
    except Exception as e:
        raise RuntimeError(f"chat() call failed: {e}")

    # Some variants may return (response, history); normalize to string.
    if isinstance(out, tuple):
        answer = out[0]
    else:
        answer = out
    if not isinstance(answer, str):
        raise RuntimeError("chat(...) did not return a string")
    return answer.strip()


def main() -> None:
    payload = read_payload()
    video_path = payload.get("video_path")
    scenes = payload.get("scenes") or []
    prompt = payload.get("prompt") or os.getenv("IV2_CAPTION_PROMPT") or ""
    model_id = payload.get("model_id", "")
    sampling = payload.get("sampling") or {}
    device = payload.get("device") or ("cuda:0" if torch.cuda.is_available() else "cpu")

    # Determine how many frames to sample per scene and the target temporal sampling rate.
    try:
        max_frames = int(sampling.get("frames", 16))
    except Exception:
        max_frames = 16
    try:
        target_fps = float(sampling.get("fps", 0.0))
    except Exception:
        target_fps = 0.0
    if not target_fps or target_fps <= 0:
        try:
            target_fps = float(os.getenv("IV2_CAPTION_FPS", "5"))
        except Exception:
            target_fps = 5.0

    if not model_id:
        model_id = "OpenGVLab/InternVL3_5-2B"

    if not video_path or not isinstance(scenes, list) or not scenes:
        print(json.dumps({"error": "invalid input: video_path and scenes are required"}))
        return

    try:
        vr, fps = open_video(video_path)
    except SystemExit:
        return

    try:
        tokenizer, model = load_model_and_tokenizer(model_id, device)
    except SystemExit:
        return

    captions: List[Dict[str, Any]] = []
    total_scenes = len(scenes)
    for idx, s in enumerate(scenes):
        try:
            si = int(s.get("scene_index"))
            st = float(s.get("start", 0.0))
            et = float(s.get("end", st + 0.1))
        except Exception:
            continue
        print(
            f"[iv2_caption_runner] processing scene {idx+1}/{total_scenes} (scene_index={si}, start={st:.3f}, end={et:.3f})",
            file=sys.stderr,
            flush=True,
        )
        try:
            images = select_scene_frames(vr, fps, st, et, target_fps, max_frames)
            if not images:
                continue
        except Exception:
            continue
        question = prompt.strip()
        if not question:
            question = "Describe this video scene in one concise sentence."
        # Placeholder caption logic; replace with real IV2-based captioning.
        try:
            text = generate_caption(model, tokenizer, images, question, device)
        except Exception as e:
            print(str(e), file=sys.stderr)
            continue
        captions.append({"scene_index": si, "text": text})

    out = {
        "model": model_id,
        "captions": captions,
        "error": "",
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()

