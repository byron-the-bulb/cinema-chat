#!/usr/bin/env python3
"""
clip_generator.py — Generate clips from PySceneDetect scenes using Lighthouse.

Reads JSON from stdin with video metadata, scenes, and captions.
Outputs JSON to stdout with generated clips (embeddings computed separately).

Lighthouse runs on each scene (>= MIN_SCENE_DURATION) to detect highlight
windows with salience scores. Results are sorted by salience and capped at
MAX_CLIPS. Each clip gets any overlapping 'en' caption text attached as its
label — clips with dialog get a dialog_embedding in the embedding step.

Usage (called by processor.go):
    echo '{"video_id": 1, "video_path": "/data/videos/film.mp4", ...}' | \
        python3 clip_generator.py
"""

import json
import sys
import os
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Lighthouse highlight detection (lazy import + cached model)
# ---------------------------------------------------------------------------

_lighthouse_available = None
_lighthouse_model = None


def check_lighthouse():
    global _lighthouse_available
    if _lighthouse_available is None:
        try:
            import lighthouse  # noqa: F401
            _lighthouse_available = True
        except ImportError:
            _lighthouse_available = False
            print("WARNING: lighthouse not installed, using scene fallback",
                  file=sys.stderr, flush=True)
    return _lighthouse_available


def get_lighthouse_model(device="cuda"):
    """Load and cache the Lighthouse CG-DETR model (expensive, only do once)."""
    global _lighthouse_model
    if _lighthouse_model is not None:
        return _lighthouse_model

    if not check_lighthouse():
        return None

    from lighthouse.models import CGDETRPredictor

    weights = os.environ.get("LIGHTHOUSE_WEIGHTS", "")
    if not weights:
        print("WARNING: LIGHTHOUSE_WEIGHTS not set, using scene fallback",
              file=sys.stderr, flush=True)
        return None

    slowfast_path = os.environ.get("SLOWFAST_WEIGHTS", "")
    feature_name = os.environ.get("LIGHTHOUSE_FEATURES", "clip_slowfast")

    print(f"  Loading Lighthouse model (features={feature_name})...",
          file=sys.stderr, flush=True)

    # PyTorch 2.6+ defaults torch.load to weights_only=True, but Lighthouse
    # checkpoints contain easydict.EasyDict which isn't in the safe globals list.
    import torch
    try:
        import easydict
        torch.serialization.add_safe_globals([easydict.EasyDict])
    except (ImportError, AttributeError):
        pass  # older torch or missing easydict — Lighthouse will handle it

    _lighthouse_model = CGDETRPredictor(
        weights,
        device=device,
        feature_name=feature_name,
        slowfast_path=slowfast_path if slowfast_path else None,
    )
    print("  Lighthouse model loaded", file=sys.stderr, flush=True)
    return _lighthouse_model


def extract_segment(video_path, start, end, output_path):
    """Extract a video segment to a temp file using ffmpeg (stream copy, fast)."""
    duration = end - start
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", video_path,
        "-t", f"{duration:.3f}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"WARNING: ffmpeg segment extraction failed: {result.stderr}",
              file=sys.stderr, flush=True)
        return False
    return True


def saliency_to_clips(scores, scene_start, scene_end, percentile, min_dur):
    """
    Convert per-frame saliency scores into clip boundaries.

    Each score covers a ~2-second window.  We threshold at the given
    percentile within this scene, group consecutive above-threshold frames
    (merging across single-frame gaps), and return clips as
    (abs_start, abs_end, avg_score) tuples.
    """
    n = len(scores)
    if n == 0:
        return []

    duration = scene_end - scene_start
    time_per_frame = duration / n

    # Percentile threshold within this scene
    sorted_scores = sorted(scores)
    idx = int(n * percentile / 100.0)
    idx = min(idx, n - 1)
    threshold = sorted_scores[idx]

    # Mark frames above threshold
    above = [s >= threshold for s in scores]

    # Merge single-frame gaps: if frame i-1 and i+1 are above but i is not,
    # include frame i too (avoids fragmenting a moment)
    merged = list(above)
    for i in range(1, n - 1):
        if not above[i] and above[i - 1] and above[i + 1]:
            merged[i] = True

    # Normalize scores to 0-1 (saliency can be negative; downstream
    # SALIENCE_THRESHOLD expects values in 0-1 range)
    s_min = min(scores)
    s_max = max(scores)
    s_range = s_max - s_min if s_max > s_min else 1.0
    norm = [(s - s_min) / s_range for s in scores]

    # Group consecutive True frames into clips
    clips = []
    clip_start_idx = None
    clip_norm_scores = []

    for i in range(n):
        if merged[i]:
            if clip_start_idx is None:
                clip_start_idx = i
                clip_norm_scores = []
            clip_norm_scores.append(norm[i])
        else:
            if clip_start_idx is not None:
                abs_start = scene_start + clip_start_idx * time_per_frame
                abs_end = scene_start + i * time_per_frame
                avg_score = sum(clip_norm_scores) / len(clip_norm_scores)
                if abs_end - abs_start >= min_dur:
                    clips.append((abs_start, abs_end, avg_score))
                clip_start_idx = None

    # Handle clip extending to end of scene
    if clip_start_idx is not None:
        abs_start = scene_start + clip_start_idx * time_per_frame
        abs_end = scene_end
        avg_score = sum(clip_norm_scores) / len(clip_norm_scores)
        if abs_end - abs_start >= min_dur:
            clips.append((abs_start, abs_end, avg_score))

    return clips


def detect_with_lighthouse(video_path, start, end, device="cuda"):
    """
    Run Lighthouse on a video segment and use per-frame saliency scores
    to find clip boundaries.  Saliency is query-independent — it measures
    visual importance without needing a text query.
    Returns list of (abs_start, abs_end, avg_saliency) tuples.
    """
    model = get_lighthouse_model(device)
    if model is None:
        return []

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        if not extract_segment(video_path, start, end, tmp_path):
            return []

        video = model.encode_video(tmp_path)
        prediction = model.predict("", video)

        saliency = prediction.get("pred_saliency_scores", [])

        if not saliency:
            print(f"    No saliency scores returned", file=sys.stderr, flush=True)
            return []

        # Log stats for debugging / tuning
        s_min = min(saliency)
        s_max = max(saliency)
        s_mean = sum(saliency) / len(saliency)
        print(f"    Saliency: {len(saliency)} frames, "
              f"min={s_min:.2f} max={s_max:.2f} mean={s_mean:.2f}",
              file=sys.stderr, flush=True)

        results = saliency_to_clips(
            saliency, start, end, SALIENCY_PERCENTILE, MIN_CLIP_DURATION,
        )

        return results

    except Exception as e:
        print(f"WARNING: Lighthouse detection failed: {e}", file=sys.stderr, flush=True)
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_CLIP_DURATION = float(os.environ.get("MIN_CLIP_DURATION", "0.5"))
MIN_SCENE_DURATION = float(os.environ.get("MIN_SCENE_FOR_LIGHTHOUSE", "3.0"))
MAX_LIGHTHOUSE_INPUT = float(os.environ.get("MAX_LIGHTHOUSE_INPUT", "140.0"))
SALIENCE_THRESHOLD = float(os.environ.get("VISUAL_SALIENCE_THRESHOLD", "0.1"))
SALIENCY_PERCENTILE = float(os.environ.get("SALIENCY_PERCENTILE", "60"))  # top 40%
MAX_CLIPS = int(os.environ.get("MAX_CLIPS", "0"))  # 0 = no limit


# ---------------------------------------------------------------------------
# Clip generation
# ---------------------------------------------------------------------------

def generate_clips(scenes, video_path, video_duration, captions, device="cuda"):
    """
    Run Lighthouse on each PySceneDetect scene to find salient highlights.
    Scenes < MIN_SCENE_DURATION are skipped. Long scenes (> 150s) are split.
    Results sorted by salience, capped at MAX_CLIPS, then overlapping captions
    are attached as labels.
    """
    sorted_scenes = sorted(scenes, key=lambda s: s["start_time"])

    # Build per-scene segments (split long scenes for Lighthouse's 150s limit)
    segments = []
    skipped = 0
    for s in sorted_scenes:
        dur = s["end_time"] - s["start_time"]
        if dur < MIN_SCENE_DURATION:
            skipped += 1
            continue
        if dur <= MAX_LIGHTHOUSE_INPUT:
            segments.append((s["start_time"], s["end_time"], s["id"]))
        else:
            pos = s["start_time"]
            while pos < s["end_time"]:
                seg_end = min(pos + MAX_LIGHTHOUSE_INPUT, s["end_time"])
                if seg_end - pos >= MIN_SCENE_DURATION:
                    segments.append((pos, seg_end, s["id"]))
                pos = seg_end

    print(f"  {len(segments)} scenes >= {MIN_SCENE_DURATION}s for Lighthouse "
          f"(skipped {skipped} short scenes)",
          file=sys.stderr, flush=True)

    raw_clips = []

    if not check_lighthouse() or get_lighthouse_model(device) is None:
        # Fallback: each qualifying scene becomes a clip with default salience
        print("  Lighthouse unavailable — using scene boundaries as clips",
              file=sys.stderr, flush=True)
        for s_start, s_end, scene_id in segments:
            raw_clips.append({
                "start_time": round(s_start, 3),
                "end_time": round(s_end, 3),
                "salience_score": 0.5,
                "source_scene_id": scene_id,
            })
    else:
        # Run Lighthouse on each scene
        for i, (s_start, s_end, scene_id) in enumerate(segments):
            print(f"  Lighthouse scene {i+1}/{len(segments)}: "
                  f"{s_start:.1f}s - {s_end:.1f}s ({s_end - s_start:.1f}s)",
                  file=sys.stderr, flush=True)

            highlights = detect_with_lighthouse(video_path, s_start, s_end, device=device)

            if not highlights:
                # No highlights — use the whole scene as a clip
                raw_clips.append({
                    "start_time": round(s_start, 3),
                    "end_time": round(s_end, 3),
                    "salience_score": 0.5,
                    "source_scene_id": scene_id,
                })
                continue

            for h_start, h_end, score in highlights:
                if score < SALIENCE_THRESHOLD:
                    continue
                if h_end - h_start < MIN_CLIP_DURATION:
                    continue
                raw_clips.append({
                    "start_time": round(h_start, 3),
                    "end_time": round(h_end, 3),
                    "salience_score": round(score, 4),
                    "source_scene_id": scene_id,
                })

    print(f"  {len(raw_clips)} raw clips from Lighthouse", file=sys.stderr, flush=True)

    # Sort by salience descending, cap at MAX_CLIPS
    raw_clips.sort(key=lambda c: c["salience_score"], reverse=True)
    if MAX_CLIPS > 0 and len(raw_clips) > MAX_CLIPS:
        print(f"  Capping from {len(raw_clips)} to {MAX_CLIPS} clips by salience",
              file=sys.stderr, flush=True)
        raw_clips = raw_clips[:MAX_CLIPS]

    # Sort back by time for output
    raw_clips.sort(key=lambda c: c["start_time"])

    # Attach overlapping 'en' captions as labels
    en_captions = [c for c in captions if c.get("language") == "en"
                   and (c.get("text") or "").strip()]

    clips = []
    for rc in raw_clips:
        # Collect all overlapping caption texts
        overlapping_texts = []
        source_caption_id = None
        for cap in en_captions:
            if cap["start_time"] < rc["end_time"] and cap["end_time"] > rc["start_time"]:
                overlapping_texts.append(cap["text"].strip())
                if source_caption_id is None:
                    source_caption_id = cap["id"]

        label = " ".join(overlapping_texts) if overlapping_texts else ""

        clips.append({
            "clip_type": "clip",
            "start_time": rc["start_time"],
            "end_time": rc["end_time"],
            "label": label,
            "salience_score": rc["salience_score"],
            "source_scene_id": rc["source_scene_id"],
            "source_caption_id": source_caption_id,
        })

    with_dialog = sum(1 for c in clips if c["label"])
    print(f"  {len(clips)} clips total ({with_dialog} with dialog)",
          file=sys.stderr, flush=True)

    return clips


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return

    video_id = payload.get("video_id")
    video_path = payload.get("video_path", "")
    video_duration = payload.get("video_duration", 0)
    scenes = payload.get("scenes", [])
    captions = payload.get("captions", [])
    device = payload.get("device", "cuda")

    if not video_id:
        print(json.dumps({"error": "missing video_id"}))
        return

    print(f"Generating clips for video {video_id}: "
          f"{len(scenes)} scenes, {len(captions)} captions",
          file=sys.stderr, flush=True)

    if not video_path or video_duration <= 0:
        print(json.dumps({"error": "missing video_path or video_duration"}))
        return

    clips = generate_clips(scenes, video_path, video_duration, captions, device=device)

    with_dialog = sum(1 for c in clips if c["label"])
    print(json.dumps({
        "video_id": video_id,
        "clips": clips,
        "clip_count": len(clips),
        "with_dialog": with_dialog,
    }))


if __name__ == "__main__":
    main()
