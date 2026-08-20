#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "mlx-audio>=0.5.0",
#     "misaki>=0.9.4",
#     "num2words>=0.5.14",
#     "spacy>=3.8.0",
#     "phonemizer-fork>=3.3.2",
#     "espeakng-loader>=0.2.4",
#     "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
# ///
"""Renders the built-in reference clips and transcripts that voiceclone.py speaks with."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

import tinyai_common as common
import tts

PRESETS = {
    "warm-narrator": (
        "af_heart",
        "The kettle was still warm when she found the letter, and for a long moment she simply stood "
        "there, reading the same two lines over and over again.",
    ),
    "studio-host": (
        "bm_george",
        "Good evening, and welcome back to the programme. Tonight we are looking at three stories that "
        "barely made the news, and one that absolutely should have.",
    ),
    "casual-peercast": (
        "am_adam",
        "So I tried it for about a week, and honestly, I was ready to hate it, but by Thursday I caught "
        "myself recommending the thing to a friend over lunch.",
    ),
}


def main() -> None:
    outdir = common.ensure_outdir(Path(__file__).resolve().parent / "assets" / "voices")
    model = tts.load_kokoro()
    for preset, (voice, text) in PRESETS.items():
        audio = np.concatenate(tts.synthesize(model, text, voice, 1.0))
        clip = tts.write_wav(outdir / f"{preset}.wav", audio, model.sample_rate)
        (outdir / f"{preset}.json").write_text(json.dumps({"text": text, "voice": voice}, indent=2) + "\n")
        print(f"{clip} {voice} {len(audio) / model.sample_rate:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
