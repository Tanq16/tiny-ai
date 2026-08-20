"""Speaks new text in the voice of a short reference clip with F5-TTS on MLX."""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import tinyai_common as common

MODEL = "lucasnewman/f5-tts-mlx"
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
PRESET_DIR = Path(__file__).resolve().parents[2] / "voices"

_SENTENCE = re.compile(r"[^.!?]+[.!?]*", re.S)


def sentences(text: str) -> list[str]:
    found = [" ".join(part.split()) for part in _SENTENCE.findall(text)]
    return [part for part in found if part]


def resolve_reference(args: argparse.Namespace) -> tuple[Path, str]:
    if args.preset == "custom":
        return common.require_file(args.ref_audio, "--ref-audio"), args.ref_text.strip()
    manifest = PRESET_DIR / f"{args.preset}.json"
    clip = PRESET_DIR / f"{args.preset}.wav"
    if not manifest.exists() or not clip.exists():
        raise FileNotFoundError(
            f"reference preset {args.preset!r} is missing from {PRESET_DIR}; run 'make voices' to render it"
        )
    return clip, json.loads(manifest.read_text())["text"].strip()


def transcribe(clip: Path) -> str:
    import mlx_whisper

    # The MLX loaders narrate on stdout, which would corrupt the NDJSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        return mlx_whisper.transcribe(str(clip), path_or_hf_repo=WHISPER_MODEL)["text"].strip()


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    clip, ref_text = resolve_reference(args)
    spoken = sentences(args.text)
    if not spoken:
        raise ValueError("--text has no speakable content")

    import mlx.core as mx
    from f5_tts_mlx.cfm import F5TTS
    from f5_tts_mlx.generate import FRAMES_PER_SEC, SAMPLE_RATE, TARGET_RMS, estimated_duration
    from f5_tts_mlx.utils import convert_char_to_pinyin
    from mlx_whisper.audio import load_audio
    from soundfile import write as write_wav

    rep.start(device="mlx", preset=args.preset, speed=args.speed, reference=str(clip))
    outdir = common.ensure_outdir(args.outdir)

    if not ref_text:
        rep.progress(None, "transcribing the reference clip")
        ref_text = transcribe(clip)
    rep.log(f"reference transcript: {ref_text}")

    rep.progress(None, "loading F5-TTS")
    with contextlib.redirect_stdout(sys.stderr):
        model = F5TTS.from_pretrained(MODEL)

    reference = load_audio(str(clip), sr=SAMPLE_RATE)
    rms = mx.sqrt(mx.mean(mx.square(reference)))
    if rms < TARGET_RMS:
        reference = reference * TARGET_RMS / rms
    condition = mx.expand_dims(reference, axis=0)

    waves: list[np.ndarray] = []
    for index, sentence in enumerate(spoken):
        rep.progress(
            index / len(spoken), f"sentence {index + 1} of {len(spoken)}", current=index, total=len(spoken)
        )
        with contextlib.redirect_stdout(sys.stderr):
            # The bundled duration predictor under-runs badly enough to clip words off the end.
            frames = int(estimated_duration(reference, ref_text, sentence, args.speed) * FRAMES_PER_SEC)
            wave, _ = model.sample(
                condition, text=convert_char_to_pinyin([f"{ref_text} {sentence}"]), duration=frames
            )
        wave = wave[reference.shape[0] :]
        mx.eval(wave)
        waves.append(np.asarray(wave, dtype=np.float32))
    rep.progress(1.0, "synthesis complete", current=len(spoken), total=len(spoken))

    audio = np.concatenate(waves)
    output = outdir / "voiceclone.wav"
    write_wav(str(output), audio, SAMPLE_RATE)

    rep.artifact(output, kind="audio", label="Cloned speech")
    rep.result(
        {
            "preset": args.preset,
            "reference_audio": str(clip),
            "reference_text": ref_text,
            "sample_rate": SAMPLE_RATE,
            "duration_s": round(len(audio) / SAMPLE_RATE, 3),
        }
    )
    rep.done()


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("voiceclone", "Speak new text in a voice taken from a short reference clip.")
    parser.add_argument("--text", required=True, help="text to speak")
    parser.add_argument(
        "--preset",
        default="warm-narrator",
        choices=("warm-narrator", "studio-host", "casual-peercast", "custom"),
        help="built-in reference voice, or custom to supply your own clip",
    )
    parser.add_argument(
        "--ref-audio", default=None, help="reference clip of 5 to 15 seconds, for --preset custom"
    )
    parser.add_argument(
        "--ref-text", default="", help="exact transcript of the clip; transcribed automatically when empty"
    )
    parser.add_argument("--speed", type=float, default=1.0, help="speech rate multiplier")
    return parser


def main() -> None:
    common.run("voiceclone", run, build_parser())
