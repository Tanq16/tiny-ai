"""Renders the built-in reference clips and transcripts that the voiceclone task speaks with."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import tinyai_common as common

from . import load_kokoro, synthesize, write_wav

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

DEFAULT_OUTDIR = Path(__file__).resolve().parents[3] / "voiceclone" / "voices"


def main() -> None:
    parser = argparse.ArgumentParser(prog="make-voices", description=__doc__)
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="directory that receives the clips")
    args = parser.parse_args()

    outdir = common.ensure_outdir(args.outdir)
    model = load_kokoro()
    for preset, (voice, text) in PRESETS.items():
        audio = np.concatenate(synthesize(model, text, voice, 1.0))
        clip = write_wav(outdir / f"{preset}.wav", audio, model.sample_rate)
        (outdir / f"{preset}.json").write_text(json.dumps({"text": text, "voice": voice}, indent=2) + "\n")
        print(f"{clip} {voice} {len(audio) / model.sample_rate:.2f}s", file=sys.stderr)
