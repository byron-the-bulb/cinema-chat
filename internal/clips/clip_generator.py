#!/usr/bin/env python3
"""
clip_generator.py — Generate dialog + visual clips from scenes and captions.

Reads JSON from stdin with video metadata, scenes, and captions.
Outputs JSON to stdout with generated clips (without embeddings — those are
computed separately by the existing embedding runners).

Dialog clips:  Each 'en' caption becomes a clip with padded boundaries.
Visual clips:  Lighthouse detects clip boundaries across the ENTIRE movie,
               chunked by scene boundaries to respect the 150s input limit.
               Clips that overlap >80% with dialog clips are deduplicated.

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
            print("WARNING: lighthouse not installed, visual clip detection disabled",
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
        print("WARNING: LIGHTHOUSE_WEIGHTS not set, skipping visual clip detection",
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


def detect_with_lighthouse(video_path, start, end, device="cuda"):
    """
    Run Lighthouse on a video segment to detect clip boundaries.
    Extracts the segment to a temp file (Lighthouse processes whole files),
    runs CG-DETR, and maps returned windows back to absolute movie time.
    Returns list of (abs_start, abs_end, confidence) tuples.
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

        highlight_windows = prediction.get("pred_relevant_windows", [])

        results = []
        for window in highlight_windows:
            if len(window) >= 3:
                w_start, w_end, confidence = window[0], window[1], window[2]
                # Window times are relative to the extracted segment → offset to absolute
                abs_start = start + max(0, w_start)
                abs_end = start + w_end
                # Clamp to chunk boundaries
                abs_start = max(abs_start, start)
                abs_end = min(abs_end, end)
                if abs_end > abs_start:
                    results.append((abs_start, abs_end, float(confidence)))

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

DIALOG_PAD_SECS = float(os.environ.get("DIALOG_PAD_SECS", "0.3"))
MIN_CLIP_DURATION = float(os.environ.get("MIN_CLIP_DURATION", "0.5"))
MIN_CHUNK_DURATION = float(os.environ.get("MIN_CHUNK_DURATION", "1.0"))
VISUAL_SALIENCE_THRESHOLD = float(os.environ.get("VISUAL_SALIENCE_THRESHOLD", "0.1"))
DEDUP_OVERLAP_THRESHOLD = float(os.environ.get("DEDUP_OVERLAP_THRESHOLD", "0.8"))


# ---------------------------------------------------------------------------
# Dialog clip generation
# ---------------------------------------------------------------------------

def generate_dialog_clips(captions, scenes):
    """
    Each 'en' caption becomes a dialog clip with padded boundaries.
    Links to the source caption and the overlapping scene.
    """
    clips = []
    for cap in captions:
        if cap.get("language") != "en":
            continue

        text = (cap.get("text") or "").strip()
        if not text:
            continue

        start = cap["start_time"] - DIALOG_PAD_SECS
        end = cap["end_time"] + DIALOG_PAD_SECS
        if start < 0:
            start = 0

        duration = end - start
        if duration < MIN_CLIP_DURATION:
            continue

        # Find overlapping scene
        source_scene_id = None
        for s in scenes:
            if s["start_time"] < end and s["end_time"] > start:
                source_scene_id = s["id"]
                break

        clips.append({
            "clip_type": "dialog",
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "label": text,
            "salience_score": cap.get("confidence", 1.0),
            "source_scene_id": source_scene_id,
            "source_caption_id": cap["id"],
        })

    return clips


# ---------------------------------------------------------------------------
# Visual clip generation — Lighthouse on full movie
# ---------------------------------------------------------------------------


MIN_SCENE_FOR_LIGHTHOUSE = float(os.environ.get("MIN_SCENE_FOR_LIGHTHOUSE", "5.0"))
MAX_LIGHTHOUSE_INPUT = float(os.environ.get("MAX_LIGHTHOUSE_INPUT", "150.0"))


def generate_visual_clips(scenes, video_path, video_duration, device="cuda"):
    """
    Run Lighthouse on each scene individually to detect highlights.
    This ensures detected clips never cross scene boundaries (visual cuts).
    Short scenes (< MIN_SCENE_FOR_LIGHTHOUSE) are skipped since they're
    already clip-sized. Long scenes (> 150s) are split into sub-segments.
    """
    sorted_scenes = sorted(scenes, key=lambda s: s["start_time"])

    # Build per-scene segments (split long scenes for Lighthouse's 150s limit)
    segments = []
    for s in sorted_scenes:
        dur = s["end_time"] - s["start_time"]
        if dur < MIN_SCENE_FOR_LIGHTHOUSE:
            continue
        if dur <= MAX_LIGHTHOUSE_INPUT:
            segments.append((s["start_time"], s["end_time"], s["id"]))
        else:
            # Split long scene into sub-segments at the limit
            pos = s["start_time"]
            while pos < s["end_time"]:
                seg_end = min(pos + MAX_LIGHTHOUSE_INPUT, s["end_time"])
                if seg_end - pos >= MIN_SCENE_FOR_LIGHTHOUSE:
                    segments.append((pos, seg_end, s["id"]))
                pos = seg_end

    print(f"  {len(segments)} scenes >= {MIN_SCENE_FOR_LIGHTHOUSE}s for Lighthouse "
          f"(skipped {len(sorted_scenes) - len(segments)} short scenes)",
          file=sys.stderr, flush=True)

    if not check_lighthouse():
        clips = []
        for s_start, s_end, scene_id in segments:
            clips.append({
                "clip_type": "visual",
                "start_time": round(s_start, 3),
                "end_time": round(s_end, 3),
                "label": "",
                "salience_score": 0.5,
                "source_scene_id": scene_id,
                "source_caption_id": None,
            })
        return clips

    # Run Lighthouse on each scene individually
    clips = []
    for i, (s_start, s_end, scene_id) in enumerate(segments):
        print(f"  Lighthouse scene {i+1}/{len(segments)}: "
              f"{s_start:.1f}s - {s_end:.1f}s ({s_end - s_start:.1f}s)",
              file=sys.stderr, flush=True)

        highlights = detect_with_lighthouse(video_path, s_start, s_end, device=device)

        if not highlights:
            clips.append({
                "clip_type": "visual",
                "start_time": round(s_start, 3),
                "end_time": round(s_end, 3),
                "label": "",
                "salience_score": 0.5,
                "source_scene_id": scene_id,
                "source_caption_id": None,
            })
            continue

        for h_start, h_end, score in highlights:
            if score < VISUAL_SALIENCE_THRESHOLD:
                continue
            if h_end - h_start < MIN_CLIP_DURATION:
                continue

            clips.append({
                "clip_type": "visual",
                "start_time": round(h_start, 3),
                "end_time": round(h_end, 3),
                "label": "",
                "salience_score": round(score, 4),
                "source_scene_id": scene_id,
                "source_caption_id": None,
            })

    return clips


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def compute_overlap(clip_a, clip_b):
    """
    Compute temporal overlap ratio (IoU-style) between two clips.
    Returns overlap_duration / min(duration_a, duration_b).
    """
    a_start, a_end = clip_a["start_time"], clip_a["end_time"]
    b_start, b_end = clip_b["start_time"], clip_b["end_time"]

    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)
    overlap_duration = max(0, overlap_end - overlap_start)

    min_duration = min(a_end - a_start, b_end - b_start)
    if min_duration <= 0:
        return 0.0
    return overlap_duration / min_duration


def deduplicate_clips(dialog_clips, visual_clips):
    """
    Remove visual clips that overlap significantly with dialog clips.
    A visual clip is removed if it overlaps >DEDUP_OVERLAP_THRESHOLD with
    any dialog clip (same moment already covered by dialog).
    """
    deduped = []
    removed = 0
    for vc in visual_clips:
        dominated = False
        for dc in dialog_clips:
            if compute_overlap(vc, dc) > DEDUP_OVERLAP_THRESHOLD:
                dominated = True
                break
        if dominated:
            removed += 1
        else:
            deduped.append(vc)

    if removed > 0:
        print(f"  Deduplication: removed {removed} visual clips overlapping with dialog",
              file=sys.stderr, flush=True)
    return deduped


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

    # Generate dialog clips from captions
    dialog_clips = generate_dialog_clips(captions, scenes)
    print(f"  Generated {len(dialog_clips)} dialog clips", file=sys.stderr, flush=True)

    # Generate visual clips — Lighthouse on full movie
    visual_clips = []
    if video_path and video_duration > 0:
        visual_clips = generate_visual_clips(
            scenes, video_path, video_duration, device=device
        )
        print(f"  Generated {len(visual_clips)} visual clips (before dedup)",
              file=sys.stderr, flush=True)

        # Deduplicate visual clips that overlap with dialog clips
        visual_clips = deduplicate_clips(dialog_clips, visual_clips)
        print(f"  {len(visual_clips)} visual clips after dedup",
              file=sys.stderr, flush=True)
    else:
        print("  Skipping visual clips (no video_path or duration)",
              file=sys.stderr, flush=True)

    all_clips = dialog_clips + visual_clips

    print(json.dumps({
        "video_id": video_id,
        "clips": all_clips,
        "dialog_count": len(dialog_clips),
        "visual_count": len(visual_clips),
    }))


if __name__ == "__main__":
    main()
