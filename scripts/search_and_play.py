#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

import requests


API_BASE = "http://localhost:8080/api/v1"


@dataclass
class SceneResult:
    index: int
    video_id: int
    scene_index: int
    start_time: float
    end_time: float
    duration: float
    fused_score: float


def multimodal_search(
    query: str,
    video_ids: Optional[List[int]],
    limit: int,
    w_text: float,
    w_clip: float,
    w_audio: float,
) -> List[SceneResult]:
    payload = {
        "query": query,
        "limit": limit,
        "weights": {"text": w_text, "clip": w_clip, "audio": w_audio},
    }
    if video_ids:
        payload["video_ids"] = video_ids

    resp = requests.post(f"{API_BASE}/search/multimodal", json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for i, item in enumerate(data.get("results", []), start=1):
        scene = item["scene"]
        fused = item.get("fused_score", 0.0)
        results.append(
            SceneResult(
                index=i,
                video_id=scene["video_id"],
                scene_index=scene["scene_index"],
                start_time=scene["start_time"],
                end_time=scene["end_time"],
                duration=scene["duration"],
                fused_score=fused,
            )
        )
    return results


def get_video_filepath(video_id: int) -> str:
    resp = requests.get(f"{API_BASE}/videos/{video_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()["video"]
    path = data["filepath"]
    # Map container path to host path when running on the host with bind-mounted ./data/videos
    if path.startswith("/data/videos/"):
        # Replace leading /data/videos with ./data/videos
        path = os.path.join(".", path.lstrip("/"))
    return path


def pick_result(results: List[SceneResult]) -> Optional[SceneResult]:
    if not results:
        print("No results.")
        return None

    print("Results:")
    for r in results:
        print(
            f"[{r.index}] video_id={r.video_id} scene_index={r.scene_index} "
            f"start={r.start_time:.3f}s dur={r.duration:.3f}s score={r.fused_score:.4f}"
        )

    while True:
        try:
            choice = input("Select result number to play (or empty to cancel): ").strip()
        except EOFError:
            return None
        if choice == "":
            return None
        if not choice.isdigit():
            print("Please enter a number.")
            continue
        idx = int(choice)
        for r in results:
            if r.index == idx:
                return r
        print("Invalid selection.")


def play_scene(filepath: str, start: float, duration: float) -> None:
    # Use ffplay; require it to be installed on host
    cmd = [
        "ffplay",
        "-loglevel",
        "warning",
        "-autoexit",
        "-ss",
        str(start),
        "-t",
        str(duration),
        filepath,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=False)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Multimodal search and play client")
    parser.add_argument("query", help="search query text, e.g. 'red corvette'")
    parser.add_argument("--video-id", type=int, action="append", dest="video_ids", help="restrict to a specific video_id (can be repeated)")
    parser.add_argument("--limit", type=int, default=10, help="max results to fetch (default 10)")
    parser.add_argument("--w-text", type=float, default=1.0, help="weight for text modality (default 1.0)")
    parser.add_argument("--w-clip", type=float, default=0.0, help="weight for CLIP visual modality (default 0.0)")
    parser.add_argument("--w-audio", type=float, default=0.0, help="weight for audio modality (default 0.0)")

    args = parser.parse_args(argv)

    try:
        results = multimodal_search(
            args.query,
            args.video_ids,
            args.limit,
            args.w_text,
            args.w_clip,
            args.w_audio,
        )
    except Exception as e:
        print("Error calling API:", e)
        return 1

    sel = pick_result(results)
    if not sel:
        return 0

    try:
        filepath = get_video_filepath(sel.video_id)
    except Exception as e:
        print("Failed to get video filepath:", e)
        return 1

    print(f"Playing video_id={sel.video_id} scene_index={sel.scene_index} from {filepath}")
    play_scene(filepath, sel.start_time, sel.duration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
