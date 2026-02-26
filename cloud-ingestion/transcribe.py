#!/usr/bin/env python3
"""
transcribe.py — Generate an SRT subtitle file from a video.

Primary pipeline: faster-whisper (large-v3) + WhisperX forced alignment (wav2vec2).
  - WhisperX's built-in Silero VAD filters music/silence before transcription,
    which is the main cause of hallucinated lines and drifting timestamps in old films.
  - After transcription, wav2vec2 forced alignment pins each word to its exact
    audio position (~50ms accuracy), replacing Whisper's imprecise cross-attention
    timestamp heuristic.

Fallback (--no-align or whisperx not installed): faster-whisper with VAD + word timestamps.

Usage:
    # On RunPod (GPU, best quality):
    python3 transcribe.py /workspace/videos/carnival_of_souls.mp4

    # Local server (CPU, faster):
    python3 transcribe.py data/videos/film.mp4 --model medium --device cpu

    # Quick pass without alignment:
    python3 transcribe.py film.mp4 --no-align

    # Explicit output path:
    python3 transcribe.py film.mp4 --output /tmp/film.srt

Install:
    # WhisperX (recommended):
    pip install whisperx

    # faster-whisper is already installed in the server venv.
    # WhisperX uses it as its backend, no conflict.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# SRT helpers
# ---------------------------------------------------------------------------

def fmt_ts(seconds: float) -> str:
    """Convert seconds to SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    # Guard against rounding up to 1000ms
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list) -> str:
    """
    Convert a list of segment dicts to SRT format.

    Each segment should have: start, end, text.
    Optionally: words — list of {word, start, end} from forced alignment.
    When word-level timestamps are present, the first word's start and last
    word's end replace the segment boundaries for tighter sync.
    """
    lines = []
    idx = 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))

        # Tighten boundaries using word-level timestamps (WhisperX alignment)
        words = seg.get("words") or []
        if words:
            first_word = words[0]
            last_word = words[-1]
            if isinstance(first_word, dict) and "start" in first_word:
                start = float(first_word["start"])
            if isinstance(last_word, dict) and "end" in last_word:
                end = float(last_word["end"])

        if end <= start:
            end = start + 0.5

        lines.append(str(idx))
        lines.append(f"{fmt_ts(start)} --> {fmt_ts(end)}")
        lines.append(text)
        lines.append("")
        idx += 1

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def extract_audio(video_path: str, audio_path: str) -> None:
    """
    Extract 16kHz mono PCM WAV from video via ffmpeg.
    16kHz mono is Whisper's native input format.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                  # drop video stream
        "-acodec", "pcm_s16le", # 16-bit PCM
        "-ar", "16000",         # 16kHz sample rate
        "-ac", "1",             # mono
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed:\n{result.stderr}")


# ---------------------------------------------------------------------------
# Transcription backends
# ---------------------------------------------------------------------------

def transcribe_whisperx(
    audio_path: str,
    model_size: str,
    device: str,
    language: str,
    batch_size: int,
) -> list:
    """
    Transcribe with WhisperX:
      1. faster-whisper transcription with Silero VAD chunking
      2. wav2vec2 forced alignment for accurate word timestamps

    Silero VAD (built into WhisperX) prevents music/silence from being fed
    to the ASR model — the primary cause of hallucinated dialog in old films.
    """
    import whisperx  # type: ignore

    compute_type = "float16" if device == "cuda" else "int8"
    lang = language if language != "auto" else None

    print(f"  Loading {model_size} ({compute_type}) on {device}...", flush=True)
    model = whisperx.load_model(
        model_size,
        device,
        compute_type=compute_type,
        language=lang,
    )

    print("  Loading audio...", flush=True)
    audio = whisperx.load_audio(audio_path)

    print(f"  Transcribing (VAD + faster-whisper, batch={batch_size})...", flush=True)
    result = model.transcribe(audio, batch_size=batch_size)

    detected_lang = result.get("language", language)
    n_segs = len(result.get("segments", []))
    print(f"  Language: {detected_lang}  |  Segments: {n_segs}", flush=True)

    if not result.get("segments"):
        print("  WARNING: No speech detected.", flush=True)
        return []

    print(f"  Loading alignment model (wav2vec2, lang={detected_lang})...", flush=True)
    try:
        align_model, metadata = whisperx.load_align_model(
            language_code=detected_lang, device=device
        )
        print("  Aligning word timestamps...", flush=True)
        aligned = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        segments = aligned.get("segments", result["segments"])
        print(f"  Alignment complete.", flush=True)
        return segments
    except Exception as exc:
        print(f"  WARNING: Alignment failed ({exc})", flush=True)
        print("  Falling back to unaligned segments.", flush=True)
        return result["segments"]


def transcribe_faster_whisper(
    audio_path: str,
    model_size: str,
    device: str,
    language: str,
    batch_size: int,
) -> list:
    """
    Transcribe with faster-whisper only (no forced alignment).
    Enables built-in VAD filter and word timestamps.
    Timestamps are segment-level with cross-attention word estimates (~100-300ms accuracy).
    """
    from faster_whisper import WhisperModel  # type: ignore

    compute_type = "float16" if device == "cuda" else "int8"
    lang = language if language != "auto" else None

    print(f"  Loading {model_size} ({compute_type}) on {device}...", flush=True)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    print("  Transcribing (VAD enabled)...", flush=True)
    segments_iter, info = model.transcribe(
        audio_path,
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 400,
            "speech_pad_ms": 200,
        },
    )

    print(
        f"  Language: {info.language} ({info.language_probability:.0%})",
        flush=True,
    )

    segments = []
    for seg in segments_iter:
        words = []
        for w in (seg.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": words,
        })

    print(f"  Segments: {len(segments)}", flush=True)
    return segments


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate SRT subtitles from a video (WhisperX + forced alignment)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Models (quality vs speed on GPU):
  large-v3   best quality, ~1x realtime on A4000  (default, recommended for RunPod)
  medium     good quality, ~5x realtime on A4000
  small      decent,       ~15x realtime on A4000
  base       fast,         ~30x realtime

On CPU (server), use medium or small. large-v3 is too slow on CPU.

Examples:
  python3 transcribe.py film.mp4
  python3 transcribe.py film.mp4 --model medium --device cpu
  python3 transcribe.py film.mp4 --no-align --output /tmp/film.srt
        """,
    )
    parser.add_argument("video", help="Path to the video file")
    parser.add_argument(
        "--output", "-o",
        help="Output SRT file (default: <video>.srt alongside the video)",
    )
    parser.add_argument(
        "--model", "-m",
        default="large-v3",
        choices=["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        help="Whisper model size (default: large-v3)",
    )
    parser.add_argument(
        "--device", "-d",
        default="auto",
        choices=["auto", "cuda", "cpu"],
        help="Compute device (default: auto-detect)",
    )
    parser.add_argument(
        "--language", "-l",
        default="en",
        metavar="LANG",
        help="Language code, e.g. en, fr, de (default: en). Use 'auto' to detect.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        metavar="N",
        help="Batch size for inference (default: 16 on GPU, 4 on CPU)",
    )
    parser.add_argument(
        "--no-align",
        action="store_true",
        help="Skip WhisperX forced alignment (faster but less accurate timestamps)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing SRT file",
    )
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve() if args.output else video_path.with_suffix(".srt")

    if output_path.exists() and not args.force:
        print(f"SRT already exists: {output_path}")
        print("Use --force to overwrite.")
        sys.exit(0)

    # Resolve device
    device = args.device
    if device == "auto":
        try:
            import torch  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    # Resolve batch size
    batch_size = args.batch_size if args.batch_size > 0 else (16 if device == "cuda" else 4)

    # Print config
    align_label = "no (--no-align)" if args.no_align else "yes (wav2vec2)"
    print(f"Video:     {video_path.name}")
    print(f"Output:    {output_path}")
    print(f"Model:     {args.model}")
    print(f"Device:    {device}")
    print(f"Language:  {args.language}")
    print(f"Align:     {align_label}")
    print(f"Batch:     {batch_size}")
    print()

    # Extract audio to temp WAV
    tmp_fd, tmp_audio = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)

    try:
        print("Extracting audio (16kHz mono PCM)...")
        extract_audio(str(video_path), tmp_audio)

        # Transcribe
        print("Transcribing...")
        use_align = not args.no_align

        if use_align:
            try:
                segments = transcribe_whisperx(
                    tmp_audio, args.model, device, args.language, batch_size
                )
            except ImportError:
                print("  whisperx not installed — falling back to faster-whisper.")
                print("  For best results: pip install whisperx")
                segments = transcribe_faster_whisper(
                    tmp_audio, args.model, device, args.language, batch_size
                )
        else:
            segments = transcribe_faster_whisper(
                tmp_audio, args.model, device, args.language, batch_size
            )

        if not segments:
            print("\nWARNING: No speech segments produced. SRT will be empty.")

        # Write SRT
        print(f"\nWriting {len(segments)} subtitle entries → {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        srt_content = segments_to_srt(segments)
        output_path.write_text(srt_content, encoding="utf-8")
        print("Done.")

    finally:
        if os.path.exists(tmp_audio):
            os.unlink(tmp_audio)


if __name__ == "__main__":
    main()
