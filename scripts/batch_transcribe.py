from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

SAMPLE_RATE = 16000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch transcribe episodes to WebVTT subtitles.")
    parser.add_argument(
        "--library-dir",
        default="/Users/tanq/telly/library/The Mentalist",
        help="Path to show library directory",
    )
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2, 3, 4, 5],
        help="Seasons to process (default: 2 3 4 5)",
    )
    parser.add_argument(
        "--glossary-file",
        default="glossary.json",
        help="Path to glossary JSON file",
    )
    parser.add_argument(
        "--extract-workers",
        type=int,
        default=8,
        help="Parallel ffmpeg workers for audio extraction (default: 8)",
    )
    parser.add_argument(
        "--transcribe-workers",
        type=int,
        default=1,
        help="Parallel transcription workers (default: 1)",
    )
    parser.add_argument(
        "--mapping-file",
        default="mapping.json",
        help="Path to mapping JSON file",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only run audio extraction pass and save mapping",
    )
    parser.add_argument(
        "--transcribe-only",
        action="store_true",
        help="Only run transcription pass from existing mapping",
    )
    return parser


def find_missing_episodes(library_dir: Path, seasons: list[int]) -> list[dict]:
    items = []
    for s_num in seasons:
        s_dir = library_dir / f"Season {s_num}"
        if not s_dir.is_dir():
            continue
        for ep_dir in sorted(s_dir.iterdir()):
            if ep_dir.is_dir() and ep_dir.name.startswith("Episode"):
                dest_vtt = ep_dir / "subtitles.vtt"
                video_file = ep_dir / "video.mkv"
                if not dest_vtt.exists() and video_file.exists():
                    rand_id = f"s{s_num:02d}_{ep_dir.name.replace(' ', '').lower()}_{uuid.uuid4().hex[:6]}"
                    items.append({
                        "id": rand_id,
                        "season": s_num,
                        "episode": ep_dir.name,
                        "video_path": str(video_file),
                        "audio_path": f"{rand_id}.wav",
                        "vtt_path": f"{rand_id}.vtt",
                        "dest_vtt": str(dest_vtt),
                    })
    return items


def extract_single_audio(item: dict) -> None:
    audio_path = Path(item["audio_path"])
    if audio_path.exists() and audio_path.stat().st_size > 0:
        return
    staging = audio_path.with_name(audio_path.stem + ".partial.wav")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            item["video_path"],
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            str(staging),
        ],
        check=True,
    )
    staging.replace(audio_path)


def transcribe_single_audio(item: dict, glossary_file: str) -> None:
    vtt_path = Path(item["vtt_path"])
    if vtt_path.exists() and vtt_path.stat().st_size > 0:
        return
    cmd = [
        "uv",
        "run",
        "episode-vtt",
        item["audio_path"],
        "--glossary-file",
        glossary_file,
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Transcription failed for {item['id']}:\n{proc.stderr}")


def main() -> None:
    args = build_parser().parse_args()
    library_dir = Path(args.library_dir).expanduser().resolve()
    glossary_path = Path(args.glossary_file).resolve()
    mapping_path = Path(args.mapping_file).resolve()

    if not glossary_path.is_file():
        print(f"Glossary file not found: {glossary_path}", file=sys.stderr)
        sys.exit(1)

    if mapping_path.is_file():
        print(f"Loading existing mapping from {mapping_path.name}")
        with open(mapping_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    else:
        items = find_missing_episodes(library_dir, args.seasons)
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2)
        print(f"Discovered {len(items)} episodes missing subtitles. Saved mapping to {mapping_path.name}")

    if not items:
        print("No missing episodes found. Done.")
        return

    if not args.transcribe_only:
        print(f"\n--- Pass 1: Extracting audio for {len(items)} episodes ({args.extract_workers} workers) ---")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.extract_workers) as executor:
            futures = {executor.submit(extract_single_audio, item): item for item in items}
            done_count = 0
            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                try:
                    future.result()
                    done_count += 1
                    print(f"[{done_count}/{len(items)}] Extracted audio for Season {item['season']} {item['episode']} -> {item['audio_path']}")
                except Exception as exc:
                    print(f"Error extracting {item['id']}: {exc}", file=sys.stderr)
                    sys.exit(1)

    if args.extract_only:
        print("Audio extraction complete. Halting as requested (--extract-only).")
        return

    print(f"\n--- Pass 2: Transcribing {len(items)} episodes ({args.transcribe_workers} workers) ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.transcribe_workers) as executor:
        futures = {executor.submit(transcribe_single_audio, item, str(glossary_path)): item for item in items}
        done_count = 0
        for future in concurrent.futures.as_completed(futures):
            item = futures[future]
            try:
                future.result()
                done_count += 1
                # Once transcribed, immediately move subtitles.vtt and remove wav to free disk
                vtt_file = Path(item["vtt_path"])
                dest_file = Path(item["dest_vtt"])
                audio_file = Path(item["audio_path"])
                if vtt_file.exists() and vtt_file.stat().st_size > 0:
                    shutil.copy2(vtt_file, dest_file)
                    vtt_file.unlink(missing_ok=True)
                if audio_file.exists():
                    audio_file.unlink(missing_ok=True)
                print(f"[{done_count}/{len(items)}] Transcribed & Placed Season {item['season']} {item['episode']} -> {dest_file.name}")
            except Exception as exc:
                print(f"Error transcribing {item['id']}: {exc}", file=sys.stderr)

    # Check remaining files
    remaining = [item for item in items if not Path(item["dest_vtt"]).exists()]
    if not remaining:
        print("All subtitles.vtt files successfully created and placed.")
        if mapping_path.exists():
            mapping_path.unlink(missing_ok=True)
    else:
        print(f"Completed with {len(remaining)} episodes remaining.")


if __name__ == "__main__":
    main()
