#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["mlx-whisper>=0.4.3"]
# ///
"""Turns speech into text, timestamps and subtitles with MLX Whisper."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

import tinyai_common as common

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm")


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("transcribe", "Transcribe speech with MLX Whisper.")
    parser.add_argument("--input", required=True, help="audio or video file to transcribe")
    parser.add_argument(
        "--model",
        default="mlx-community/whisper-large-v3-turbo",
        help="Hugging Face repo holding MLX Whisper weights",
    )
    parser.add_argument(
        "--task", default="transcribe", choices=("transcribe", "translate"), help="decoding task"
    )
    parser.add_argument("--language", default=None, help="ISO code such as en or fr, empty to detect")
    parser.add_argument(
        "--word-timestamps", action="store_true", help="add word-level timestamps to each segment"
    )
    return parser


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to measure the input but was not found on PATH")
    probe = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(probe.stdout.strip())


def extract_audio(source: Path, target: Path) -> Path:
    from mlx_whisper.audio import SAMPLE_RATE

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to read a video input but was not found on PATH")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            str(target),
        ],
        check=True,
    )
    return target


def write_timestamped(result: dict, target: Path) -> None:
    from mlx_whisper.writers import format_timestamp

    lines = [
        f"[{format_timestamp(s['start'])} --> {format_timestamp(s['end'])}] {s['text'].strip()}"
        for s in result["segments"]
    ]
    target.write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def main(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    import mlx_whisper
    from mlx_whisper.writers import get_writer

    rep.start(device=device, model=args.model, task=args.task, language=args.language or "detect")
    duration = probe_duration(source)
    rep.log(f"{duration:.1f}s of media")

    with tempfile.TemporaryDirectory() as staging:
        audio = source
        if source.suffix.lower() in VIDEO_SUFFIXES:
            rep.progress(None, "extracting audio")
            audio = extract_audio(source, Path(staging) / "audio.wav")
        rep.progress(None, f"transcribing {duration:.0f}s with {args.model}")
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=args.model,
            task=args.task,
            language=args.language or None,
            word_timestamps=args.word_timestamps,
        )

    rep.progress(1.0, "writing transcript")
    write_timestamped(result, outdir / "transcript.txt")
    for fmt in ("srt", "json"):
        get_writer(fmt, str(outdir))(result, "transcript")

    rep.artifact(outdir / "transcript.txt", kind="text", label="Transcript")
    rep.artifact(outdir / "transcript.srt", kind="text", label="Subtitles")
    rep.artifact(outdir / "transcript.json", kind="json", label="Segments")
    rep.log(f"{len(result['segments'])} segments in {result['language']}")
    rep.result({"text": result["text"].strip(), "language": result["language"], "duration": duration})
    rep.done()


if __name__ == "__main__":
    common.run("transcribe", main, build_parser())
