from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

AUDIO_NAME = "audio.wav"
ACCURACY_MODEL = "Qwen/Qwen3-ASR-1.7B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="episode-vtt",
        description="Extract audio from an episode and write a sibling WebVTT transcript.",
    )
    parser.add_argument("input", help="audio or video file to transcribe")
    parser.add_argument(
        "--glossary-file",
        default=None,
        help="JSON file of vocabulary and known mishearings",
    )
    parser.add_argument(
        "--model",
        default=ACCURACY_MODEL,
        help="Hugging Face repo holding the Qwen3-ASR weights",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="language name such as English, empty to detect",
    )
    return parser


def require_file(path: str, label: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"{label} is not a file: {target}")
    return target


def load_glossary(path: str | None) -> tuple[list[str], list[tuple[str, str]]]:
    if not path:
        return [], []
    raw = json.loads(require_file(path, "glossary file").read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("glossary file must be a JSON object")
    vocabulary = [str(term).strip() for term in raw.get("vocabulary") or [] if str(term).strip()]
    corrections = []
    for entry in raw.get("corrections") or []:
        heard, meant = str(entry.get("from", "")).strip(), str(entry.get("to", "")).strip()
        if heard and meant:
            corrections.append((heard, meant))
    return vocabulary, corrections


def asr_context(vocabulary: list[str], corrections: list[tuple[str, str]]) -> str:
    terms = dict.fromkeys(vocabulary + [meant for _, meant in corrections])
    return " ".join(terms)


def apply_corrections(text: str, corrections: list[tuple[str, str]]) -> str:
    out = text
    for heard, meant in corrections:
        out = re.sub(re.escape(heard), meant, out, flags=re.IGNORECASE)
    return out


def extract_audio(source: Path, target: Path) -> Path:
    from mlx_qwen3_asr.audio import SAMPLE_RATE

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to extract audio but was not found on PATH")
    staging = target.with_name(target.stem + ".partial" + target.suffix)
    try:
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
                str(staging),
            ],
            check=True,
        )
        staging.replace(target)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return target


def on_progress(event: dict) -> None:
    if event.get("event") != "chunk_started":
        return
    idx = event.get("chunk_index")
    total = event.get("total_chunks")
    fraction = event.get("progress")
    if idx is None or total is None:
        return
    pct = f" {fraction * 100:.0f}%" if isinstance(fraction, int | float) else ""
    print(f"transcribing chunk {idx}/{total}{pct}", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    source = require_file(args.input, "input")
    vocabulary, corrections = load_glossary(args.glossary_file)
    audio = Path.cwd() / AUDIO_NAME
    print(f"extracting audio to {audio}", file=sys.stderr)
    extract_audio(source, audio)

    from mlx_qwen3_asr import transcribe
    from mlx_qwen3_asr.writers import write_vtt

    print(f"transcribing with {args.model}", file=sys.stderr)
    result = transcribe(
        str(audio),
        model=args.model,
        context=asr_context(vocabulary, corrections),
        language=args.language or None,
        return_timestamps=True,
        on_progress=on_progress,
    )
    if result.truncated:
        print("the recogniser stopped early, so the transcript may be incomplete", file=sys.stderr)
    if not result.segments:
        raise ValueError("the recording produced no timestamped speech")
    for segment in result.segments:
        segment["text"] = apply_corrections(str(segment.get("text", "")), corrections)

    vtt = source.with_suffix(".vtt")
    write_vtt(result, str(vtt))
    print(vtt)


def main() -> None:
    args = build_parser().parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
