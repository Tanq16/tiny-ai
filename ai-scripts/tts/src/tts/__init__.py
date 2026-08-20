"""Reads text aloud in a preset Kokoro 82M voice on MLX."""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

import numpy as np
import tinyai_common as common

REPO = "prince-canuma/Kokoro-82M"
CHUNK_LIMIT = 600

_SENTENCE = re.compile(r"[^.!?]+[.!?]*", re.S)


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        paragraph = " ".join(block.split())
        if not paragraph:
            continue
        if len(paragraph) <= limit:
            chunks.append(paragraph)
            continue
        buffer = ""
        for sentence in _SENTENCE.findall(paragraph):
            if buffer and len(buffer) + len(sentence) > limit:
                chunks.append(buffer.strip())
                buffer = ""
            buffer += sentence
        if buffer.strip():
            chunks.append(buffer.strip())
    return chunks


def load_kokoro():
    from mlx_audio.tts.utils import load_model

    # mlx-audio narrates pipeline setup on stdout, which would corrupt the NDJSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        return load_model(REPO)


def synthesize(model, text: str, voice: str, speed: float) -> list[np.ndarray]:
    with contextlib.redirect_stdout(sys.stderr):
        return [
            np.asarray(result.audio, dtype=np.float32)
            for result in model.generate(text=text, voice=voice, speed=speed, lang_code=voice[:1])
        ]


def write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> Path:
    from mlx_audio.audio_io import write

    write(str(path), audio, sample_rate)
    return path


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    chunks = chunk_text(args.text)
    if not chunks:
        raise ValueError("--text has no speakable content")

    rep.start(device="mlx", voice=args.voice, speed=args.speed, format=args.format, chunks=len(chunks))
    outdir = common.ensure_outdir(args.outdir)

    rep.progress(None, "loading Kokoro 82M")
    model = load_kokoro()
    rep.log(f"loaded {REPO}")

    segments: list[np.ndarray] = []
    for index, chunk in enumerate(chunks):
        rep.progress(
            index / len(chunks), f"chunk {index + 1} of {len(chunks)}", current=index, total=len(chunks)
        )
        segments.extend(synthesize(model, chunk, args.voice, args.speed))
    rep.progress(1.0, "synthesis complete", current=len(chunks), total=len(chunks))

    audio = np.concatenate(segments)
    sample_rate = model.sample_rate
    output = write_wav(outdir / "speech.wav", audio, sample_rate)
    if args.format == "mp3":
        wav = output
        output = common.encode_mp3(wav, outdir / "speech.mp3")
        wav.unlink()

    rep.artifact(output, kind="audio", label="Speech")
    rep.result(
        {
            "voice": args.voice,
            "sample_rate": sample_rate,
            "duration_s": round(len(audio) / sample_rate, 3),
        }
    )
    rep.done()


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("tts", "Read text aloud in a natural preset voice.")
    parser.add_argument("--text", required=True, help="text to speak")
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice id, such as af_heart or bm_george")
    parser.add_argument("--speed", type=float, default=1.0, help="speech rate multiplier")
    parser.add_argument("--format", default="wav", choices=("wav", "mp3"), help="output audio format")
    return parser


def main() -> None:
    common.run("tts", run, build_parser())
