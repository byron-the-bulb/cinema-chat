#!/usr/bin/env python3
"""
clip_generator.py — Generate dialog + visual clips from existing scenes and captions.

Reads JSON from stdin with video metadata, scenes, and captions.
Outputs JSON to stdout with generated clips (without embeddings — those are
computed separately by the existing embedding runners).

Dialog clips:  Each 'en' caption becomes a clip with padded boundaries.
Visual clips:  Non-speech gaps are cut at scene boundaries, then scored by
               Lighthouse highlight detection. Only salient moments become clips.

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
            print("WARNING: lighthouse not installed, visual clip scoring disabled",
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
        print("WARNING: LIGHTHOUSE_WEIGHTS not set, skipping visual scoring",
              file=sys.stderr, flush=True)
        return None

    slowfast_path = os.environ.get("SLOWFAST_WEIGHTS", "")
    feature_name = os.environ.get("LIGHTHOUSE_FEATURES", "clip_slowfast")

    print(f"  Loading Lighthouse model (features={feature_name})...",
          file=sys.stderr, flush=True)
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


def score_with_lighthouse(video_path, start, end, device="cuda"):
    """
    Run Lighthouse highlight detection on a video segment.
    Extracts the segment to a temp file (Lighthouse processes whole files),
    runs CG-DETR, and maps returned windows back to absolute movie time.
    Returns list of (abs_start, abs_end, confidence) tuples.
    """
    model = get_lighthouse_model(device)
    if model is None:
        return []

    # Lighthouse processes the entire video file, so extract the segment
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
        print(f"WARNING: Lighthouse scoring failed: {e}", file=sys.stderr, flush=True)
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Dialog clip generation
# ---------------------------------------------------------------------------

DIALOG_PAD_SECS = float(os.environ.get("DIALOG_PAD_SECS", "0.3"))
MIN_CLIP_DURATION = float(os.environ.get("MIN_CLIP_DURATION", "0.5"))
MIN_VISUAL_GAP = float(os.environ.get("MIN_VISUAL_GAP", "1.0"))
VISUAL_SALIENCE_THRESHOLD = float(os.environ.get("VISUAL_SALIENCE_THRESHOLD", "0.1"))


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
# Visual clip generation
# ---------------------------------------------------------------------------

def find_nonspeech_gaps(captions, video_duration):
    """
    Invert the speech timeline to find non-speech gaps.
    Returns list of (start, end) tuples.
    """
    # Collect speech regions from 'en' captions
    speech_regions = []
    for cap in captions:
        if cap.get("language") != "en":
            continue
        speech_regions.append((cap["start_time"], cap["end_time"]))

    if not speech_regions:
        # No speech at all — entire video is a gap
        return [(0, video_duration)]

    # Sort and merge overlapping speech regions
    speech_regions.sort()
    merged = [speech_regions[0]]
    for start, end in speech_regions[1:]:
        if start <= merged[-1][1] + 0.1:  # merge within 100ms
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Find gaps between merged speech regions
    gaps = []
    if merged[0][0] > MIN_VISUAL_GAP:
        gaps.append((0, merged[0][0]))
    for i in range(len(merged) - 1):
        gap_start = merged[i][1]
        gap_end = merged[i + 1][0]
        if gap_end - gap_start >= MIN_VISUAL_GAP:
            gaps.append((gap_start, gap_end))
    if merged[-1][1] < video_duration - MIN_VISUAL_GAP:
        gaps.append((merged[-1][1], video_duration))

    return gaps


def cut_gaps_at_scene_boundaries(gaps, scenes, max_chunk=150.0):
    """
    Split gaps at scene boundaries so each chunk is under max_chunk seconds
    (Lighthouse's input limit).
    Returns list of (start, end, scene_id) tuples.
    """
    # Sort scenes by start time
    sorted_scenes = sorted(scenes, key=lambda s: s["start_time"])

    chunks = []
    for gap_start, gap_end in gaps:
        # Find scene boundaries within this gap
        boundaries = [gap_start]
        for s in sorted_scenes:
            # Scene boundary falls within gap
            if gap_start < s["start_time"] < gap_end:
                boundaries.append(s["start_time"])
            if gap_start < s["end_time"] < gap_end:
                boundaries.append(s["end_time"])
        boundaries.append(gap_end)
        boundaries = sorted(set(boundaries))

        # Create chunks from consecutive boundaries
        for i in range(len(boundaries) - 1):
            c_start = boundaries[i]
            c_end = boundaries[i + 1]
            duration = c_end - c_start

            if duration < MIN_VISUAL_GAP:
                continue

            # Further split if still over max_chunk
            if duration > max_chunk:
                n_splits = int(duration / max_chunk) + 1
                split_dur = duration / n_splits
                for j in range(n_splits):
                    s = c_start + j * split_dur
                    e = c_start + (j + 1) * split_dur
                    if e - s >= MIN_VISUAL_GAP:
                        # Find containing scene
                        scene_id = None
                        for sc in sorted_scenes:
                            if sc["start_time"] <= s and sc["end_time"] >= e:
                                scene_id = sc["id"]
                                break
                        chunks.append((round(s, 3), round(e, 3), scene_id))
            else:
                scene_id = None
                for sc in sorted_scenes:
                    if sc["start_time"] <= c_start and sc["end_time"] >= c_end:
                        scene_id = sc["id"]
                        break
                chunks.append((round(c_start, 3), round(c_end, 3), scene_id))

    return chunks


def generate_visual_clips(captions, scenes, video_path, video_duration, device="cuda"):
    """
    Find non-speech gaps, cut at scene boundaries, score with Lighthouse.
    """
    gaps = find_nonspeech_gaps(captions, video_duration)
    if not gaps:
        print("  No non-speech gaps found", file=sys.stderr, flush=True)
        return []

    chunks = cut_gaps_at_scene_boundaries(gaps, scenes)
    print(f"  Found {len(gaps)} non-speech gaps → {len(chunks)} chunks for scoring",
          file=sys.stderr, flush=True)

    if not check_lighthouse():
        # Without Lighthouse, create clips from chunks using the full gap as the clip
        # (no saliency scoring — all chunks become clips)
        clips = []
        for c_start, c_end, scene_id in chunks:
            clips.append({
                "clip_type": "visual",
                "start_time": c_start,
                "end_time": c_end,
                "label": "",  # IV2 descriptions added later
                "salience_score": 0.5,  # neutral score without Lighthouse
                "source_scene_id": scene_id,
                "source_caption_id": None,
            })
        return clips

    # Score each chunk with Lighthouse
    clips = []
    for i, (c_start, c_end, scene_id) in enumerate(chunks):
        print(f"  Scoring chunk {i+1}/{len(chunks)}: {c_start:.1f}s - {c_end:.1f}s",
              file=sys.stderr, flush=True)

        highlights = score_with_lighthouse(video_path, c_start, c_end, device=device)

        if not highlights:
            # No highlights detected — skip this chunk
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
                "label": "",  # IV2 descriptions added later
                "salience_score": round(score, 4),
                "source_scene_id": scene_id,
                "source_caption_id": None,
            })

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

    # Generate dialog clips
    dialog_clips = generate_dialog_clips(captions, scenes)
    print(f"  Generated {len(dialog_clips)} dialog clips", file=sys.stderr, flush=True)

    # Generate visual clips
    visual_clips = []
    if video_path and video_duration > 0:
        visual_clips = generate_visual_clips(
            captions, scenes, video_path, video_duration, device=device
        )
        print(f"  Generated {len(visual_clips)} visual clips", file=sys.stderr, flush=True)
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
