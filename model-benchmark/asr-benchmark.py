#!/usr/bin/env python3
"""
asr-benchmark.py — Local ASR model comparison, no CUDA required.

Tests WhisperX (faster-whisper / CTranslate2 INT8) and Qwen3-ASR
(HuggingFace transformers) side-by-side on any audio or video file.

Designed for AMD / CPU machines (Ryzen AI MAX, etc.).
Will use ROCm or CUDA automatically if torch detects it; otherwise CPU.

Usage:
  python asr-benchmark.py <audio_or_video_file> [options]

Options:
  --models         Comma-separated models to run (default: whisperx,qwen3)
                   Choices: whisperx, qwen3
  --whisper-model  Whisper model size (default: large-v3)
                   Options: tiny, base, small, medium, large-v2, large-v3,
                            large-v3-turbo, distil-large-v3
  --qwen-model     HuggingFace model ID (default: Qwen/Qwen3-ASR-1.7B)
  --aligner-model  ForcedAligner for word timestamps (default: Qwen/Qwen3-ForcedAligner-0.6B)
  --device         Force device: auto, cpu, cuda  (default: auto)
  --language       Language code, e.g. 'en' (default: auto-detect)
  --max-secs       Truncate audio to N seconds for quick tests
  --ref            Reference transcript file for WER calculation
  --output-dir     Where to write SRT files (default: ./benchmark-out)

Examples:
  # Quick 60s test comparing both models:
  python asr-benchmark.py data/videos/clip.mp4 --max-secs 60

  # Full run, whisperx only:
  python asr-benchmark.py data/videos/carnival_of_souls.mp4 --models whisperx

  # Force CPU, compare model sizes:
  python asr-benchmark.py clip.mp4 --device cpu --whisper-model large-v3-turbo

  # With reference transcript for WER:
  python asr-benchmark.py clip.mp4 --ref reference.txt
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class BenchResult:
    model: str
    model_id: str
    device_used: str
    elapsed_s: float
    audio_duration_s: float
    rtf: float           # elapsed / audio_duration  (lower = faster)
    segments: List[dict]
    word_count: int
    char_count: int
    peak_rss_mb: float   # resident set size delta (proxy for model RAM)
    language: str = "?"
    wer: Optional[float] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def transcript(self) -> str:
        return " ".join(s.get("text", "").strip() for s in self.segments)


# ── Audio helpers ─────────────────────────────────────────────────────────────

def get_duration(path: str) -> float:
    """Return audio/video duration in seconds via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", "format=duration", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def to_wav(src: str, dst: str, max_secs: Optional[int] = None) -> None:
    """Extract/convert audio to 16kHz mono WAV (Whisper-compatible)."""
    cmd = ["ffmpeg", "-y", "-i", src]
    if max_secs:
        cmd += ["-t", str(max_secs)]
    cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", dst]
    subprocess.run(cmd, capture_output=True, check=True)


# ── SRT helpers ───────────────────────────────────────────────────────────────

def _srt_ts(secs: float) -> str:
    h, rem = divmod(max(secs, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")


def to_srt(segments: List[dict]) -> str:
    lines, idx = [], 1
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines += [str(idx), f"{_srt_ts(seg['start'])} --> {_srt_ts(seg['end'])}", text, ""]
        idx += 1
    return "\n".join(lines)


def _wc(segments: List[dict]) -> int:
    return sum(len(s.get("text", "").split()) for s in segments)


def _cc(segments: List[dict]) -> int:
    return sum(len(s.get("text", "")) for s in segments)


# ── Device detection ──────────────────────────────────────────────────────────

def detect_device(preference: str = "auto") -> str:
    if preference != "auto":
        return preference
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"   # handles both NVIDIA CUDA and AMD ROCm
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"    # Apple Silicon
    except ImportError:
        pass
    return "cpu"


def _rss_mb() -> float:
    """Current process resident set size in MB."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except ImportError:
        import resource
        # ru_maxrss is in KB on Linux, bytes on macOS
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return kb / 1024 if sys.platform != "darwin" else kb / 1e6


# ── Model runners ─────────────────────────────────────────────────────────────

def run_whisperx(wav: str, model_size: str, language: Optional[str],
                 duration: float, device: str) -> BenchResult:
    """
    WhisperX: faster-whisper (CTranslate2) + word-level alignment.
    Uses CPU INT8 by default — very fast even without GPU.
    """
    try:
        import whisperx

        # CTranslate2: int8 on CPU, float16 on CUDA/ROCm
        compute_type = "float16" if device in ("cuda", "mps") else "int8"
        ct_device = "cpu" if device == "mps" else device  # CTranslate2 has no MPS

        ram0 = _rss_mb()
        t0 = time.perf_counter()

        model = whisperx.load_model(
            model_size, device=ct_device, compute_type=compute_type,
            language=language,
        )
        audio = whisperx.load_audio(wav)
        result = model.transcribe(audio, batch_size=8, language=language)
        lang = result.get("language", "?")

        # Word-level alignment improves SRT timing (optional — skip if model unavailable)
        try:
            ma, meta = whisperx.load_align_model(language_code=lang, device=ct_device)
            result = whisperx.align(result["segments"], ma, meta, audio, ct_device,
                                    return_char_alignments=False)
        except Exception as align_err:
            pass  # alignment is best-effort

        segs = result.get("segments", [])
        elapsed = time.perf_counter() - t0

        return BenchResult(
            model="whisperx",
            model_id=f"faster-whisper/{model_size}",
            device_used=ct_device,
            elapsed_s=elapsed,
            audio_duration_s=duration,
            rtf=elapsed / duration if duration else 0,
            segments=segs,
            word_count=_wc(segs),
            char_count=_cc(segs),
            peak_rss_mb=max(0, _rss_mb() - ram0),
            language=lang,
        )

    except Exception as e:
        return BenchResult(
            model="whisperx", model_id=f"faster-whisper/{model_size}",
            device_used=device, elapsed_s=0, audio_duration_s=duration, rtf=0,
            segments=[], word_count=0, char_count=0, peak_rss_mb=0, error=str(e),
        )


def _words_to_segments(words, max_words: int = 10, max_gap_s: float = 1.5) -> List[dict]:
    """
    Group word-level timestamps (from Qwen3-ForcedAligner) into SRT segments.
    Splits on silence gaps > max_gap_s or after max_words words.
    Each word object has .text, .start_time, .end_time attributes.
    """
    if not words:
        return []
    segments, group = [], []
    for w in words:
        if group and (
            len(group) >= max_words
            or (w.start_time - group[-1].end_time) > max_gap_s
        ):
            segments.append(group)
            group = []
        group.append(w)
    if group:
        segments.append(group)
    return [
        {
            "start": g[0].start_time,
            "end":   g[-1].end_time,
            "text":  " ".join(w.text for w in g).strip(),
        }
        for g in segments
    ]


def run_qwen3(wav: str, model_id: str, language: Optional[str],
              duration: float, device: str,
              aligner_id: str = "Qwen/Qwen3-ForcedAligner-0.6B") -> BenchResult:
    """
    Qwen3-ASR via the official qwen-asr package.
    Install: pip install qwen-asr

    Uses Qwen3-ForcedAligner-0.6B for word timestamps → proper SRT output.
    device: "cpu" or "cuda:0"
    dtype:  bfloat16 (Zen5 supports AVX-512 BF16; falls back to float32 on error)
    """
    try:
        import torch
        from qwen_asr import Qwen3ASRModel

        # bfloat16 works on Zen5 AVX-512; float32 on older CPUs
        dtype = torch.bfloat16 if device != "cpu" else torch.bfloat16
        device_map = device  # "cpu" or "cuda:0"

        ram0 = _rss_mb()
        t0 = time.perf_counter()

        model = Qwen3ASRModel.from_pretrained(
            model_id,
            dtype=dtype,
            device_map=device_map,
            max_inference_batch_size=4,
            max_new_tokens=256,
            forced_aligner=aligner_id,
            forced_aligner_kwargs=dict(dtype=dtype, device_map=device_map),
        )

        # qwen_asr expects a language name like "English", not a code like "en"
        LANG_CODES = {
            "en": "English", "zh": "Chinese", "fr": "French",
            "de": "German",  "es": "Spanish", "ja": "Japanese",
            "ko": "Korean",  "it": "Italian", "pt": "Portuguese",
            "ru": "Russian", "ar": "Arabic",  "nl": "Dutch",
        }
        lang_name = LANG_CODES.get(language or "", language) if language else None

        results = model.transcribe(
            audio=wav,
            language=lang_name,
            return_time_stamps=True,
        )

        r0 = results[0]
        lang_out = getattr(r0, "language", language or "?")

        # r0.time_stamps is a list of word-timestamp objects
        segs = _words_to_segments(r0.time_stamps or [])

        # Fallback: no timestamps → single block with full text
        if not segs and getattr(r0, "text", ""):
            segs = [{"start": 0.0, "end": duration, "text": r0.text}]

        elapsed = time.perf_counter() - t0

        return BenchResult(
            model="qwen3",
            model_id=model_id,
            device_used=device_map,
            elapsed_s=elapsed,
            audio_duration_s=duration,
            rtf=elapsed / duration if duration else 0,
            segments=segs,
            word_count=_wc(segs),
            char_count=_cc(segs),
            peak_rss_mb=max(0, _rss_mb() - ram0),
            language=str(lang_out),
        )

    except Exception as e:
        return BenchResult(
            model="qwen3", model_id=model_id,
            device_used=device, elapsed_s=0, audio_duration_s=duration, rtf=0,
            segments=[], word_count=0, char_count=0, peak_rss_mb=0, error=str(e),
        )


# ── WER (optional) ────────────────────────────────────────────────────────────

def compute_wer(ref_path: str, hypothesis: str) -> Optional[float]:
    """Word Error Rate as a percentage. Requires: pip install jiwer"""
    try:
        from jiwer import wer
        ref = Path(ref_path).read_text(encoding="utf-8").strip()
        return round(wer(ref, hypothesis) * 100, 1)
    except ImportError:
        print("  [wer] Install jiwer for WER calculation: pip install jiwer")
        return None
    except Exception as e:
        print(f"  [wer] Could not compute WER: {e}")
        return None


# ── Formatting ────────────────────────────────────────────────────────────────

def preview(r: BenchResult, chars: int = 280) -> str:
    t = r.transcript
    return (t[:chars] + "…") if len(t) > chars else t


def print_result(r: BenchResult, ref_path: Optional[str], out_dir: Path, stem: str) -> None:
    label = f"[{r.model}]"
    if r.error:
        print(f"  {label} ERROR: {r.error}")
        print(f"  Hint: run setup.sh or check the model ID / network access.")
        return

    # Write SRT
    srt_path = out_dir / f"{stem}_{r.model}.srt"
    srt_path.write_text(to_srt(r.segments), encoding="utf-8")

    # WER
    if ref_path:
        r.wer = compute_wer(ref_path, r.transcript)

    rtf_label = f"{r.rtf:.2f}x realtime" if r.rtf else "?"
    print(f"  Model:    {r.model_id}")
    print(f"  Device:   {r.device_used}")
    print(f"  Time:     {r.elapsed_s:.1f}s  ({rtf_label})")
    print(f"  Words:    {r.word_count}  ({r.char_count} chars)")
    print(f"  Language: {r.language}")
    print(f"  RAM Δ:    {r.peak_rss_mb:.0f} MB")
    if r.wer is not None:
        print(f"  WER:      {r.wer}%")
    print(f"  SRT:      {srt_path}")
    print(f"  Preview:  {preview(r)}")


def print_table(results: List[BenchResult]) -> None:
    ok = [r for r in results if r.ok]
    if len(ok) < 2:
        return
    print("=" * 80)
    print("COMPARISON")
    print("=" * 80)
    H = f"{'Model':<12}  {'ID':<36}  {'Time':>7}  {'RTF':>6}  {'Words':>6}  {'RAM MB':>7}"
    if any(r.wer is not None for r in ok):
        H += f"  {'WER':>6}"
    print(H)
    print("-" * len(H))
    for r in results:
        if r.error:
            print(f"{'  '+r.model:<12}  ERROR: {r.error[:55]}")
            continue
        line = (f"  {r.model:<10}  {r.model_id[:35]:<36}  "
                f"{r.elapsed_s:>7.1f}  {r.rtf:>6.2f}  {r.word_count:>6}  {r.peak_rss_mb:>7.0f}")
        if any(x.wer is not None for x in ok):
            line += f"  {str(r.wer)+'%' if r.wer is not None else '—':>6}"
        print(line)

    # Speed winner
    times = [(r.elapsed_s, r.model) for r in ok]
    fastest = min(times, key=lambda x: x[0])
    print(f"\nFastest: {fastest[1]} ({fastest[0]:.1f}s)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Local ASR benchmark — WhisperX vs Qwen3-ASR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("source", help="Audio or video file")
    p.add_argument("--models", default="whisperx,qwen3",
                   help="Comma-separated list: whisperx,qwen3  (default: both)")
    p.add_argument("--whisper-model", default="large-v3",
                   metavar="SIZE",
                   help="Whisper model size (default: large-v3)")
    p.add_argument("--qwen-model", default="Qwen/Qwen3-ASR-1.7B",
                   metavar="MODEL_ID",
                   help="HuggingFace model ID for Qwen ASR (default: Qwen/Qwen3-ASR-1.7B)")
    p.add_argument("--aligner-model", default="Qwen/Qwen3-ForcedAligner-0.6B",
                   metavar="MODEL_ID",
                   help="ForcedAligner model for word timestamps (default: Qwen/Qwen3-ForcedAligner-0.6B)")
    p.add_argument("--device", default="auto",
                   choices=["auto", "cpu", "cuda"],
                   help="Compute device (default: auto-detect)")
    p.add_argument("--language", default=None,
                   help="ISO language code, e.g. 'en' (default: auto-detect)")
    p.add_argument("--max-secs", type=int, default=None, metavar="N",
                   help="Truncate audio to first N seconds (quick test mode)")
    p.add_argument("--ref", default=None, metavar="FILE",
                   help="Reference transcript for WER calculation")
    p.add_argument("--output-dir", default="./benchmark-out", metavar="DIR",
                   help="Directory for SRT files and JSON results")
    args = p.parse_args()

    src = Path(args.source).resolve()
    if not src.exists():
        print(f"ERROR: file not found: {src}")
        sys.exit(1)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    device = detect_device(args.device)

    print("=" * 60)
    print("ASR BENCHMARK")
    print("=" * 60)
    print(f"Source:   {src.name}")
    print(f"Device:   {device}")
    if args.max_secs:
        print(f"Duration: first {args.max_secs}s only")

    # Extract audio
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = tf.name
    print(f"Extracting audio to 16kHz mono WAV...")
    try:
        to_wav(str(src), wav_path, args.max_secs)
        duration = get_duration(wav_path)
        print(f"Duration: {duration:.1f}s")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: ffmpeg failed: {e.stderr.decode()[:200]}")
        sys.exit(1)

    models = [m.strip().lower() for m in args.models.split(",") if m.strip()]
    print(f"Models:   {', '.join(models)}")
    print()

    results: List[BenchResult] = []

    for model_name in models:
        print(f"{'─' * 60}")
        print(f"Running: {model_name}")
        print(f"{'─' * 60}")

        if model_name == "whisperx":
            r = run_whisperx(wav_path, args.whisper_model, args.language, duration, device)
        elif model_name == "qwen3":
            r = run_qwen3(wav_path, args.qwen_model, args.language, duration, device,
                          aligner_id=args.aligner_model)
        else:
            print(f"  Unknown model '{model_name}'. Valid: whisperx, qwen3")
            continue

        print_result(r, args.ref, out_dir, src.stem)
        results.append(r)
        print()

    # Comparison table
    if len(results) > 1:
        print_table(results)
        print()

    # Save JSON
    ts = time.strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"benchmark_{ts}.json"
    json_path.write_text(json.dumps({
        "source": str(src),
        "duration_s": duration,
        "device": device,
        "whisper_model": args.whisper_model,
        "qwen_model": args.qwen_model,
        "max_secs": args.max_secs,
        "results": [
            {k: v for k, v in asdict(r).items() if k != "segments"}
            | {"segment_count": len(r.segments),
               "transcript_preview": preview(r, 300)}
            for r in results
        ],
    }, indent=2, default=str), encoding="utf-8")
    print(f"Results JSON: {json_path}")
    print(f"SRT files:    {out_dir}/")

    # Cleanup temp wav
    try:
        os.unlink(wav_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
