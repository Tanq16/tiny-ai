"""Splits a track into instrument stems with Demucs."""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Callable
from pathlib import Path

import tinyai_common as common

LEAD_STEM = "vocals"
REST_STEM = "instrumental"


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("stems", "Split a track into stems with Demucs.")
    parser.add_argument("--input", required=True, help="audio file to separate")
    parser.add_argument("--model", default="htdemucs", help="pretrained Demucs model")
    parser.add_argument("--two-stems", action="store_true", help="separate vocals from everything else")
    parser.add_argument("--format", default="wav", choices=("wav", "mp3"), help="stem file format")
    parser.add_argument(
        "--shifts",
        type=int,
        default=1,
        help="averaging passes that trade time for separation quality",
    )
    return parser


def segment_reporter(rep: common.Reporter, passes: int) -> Callable[[dict], None]:
    def report(info: dict) -> None:
        if info.get("state") != "end":
            return
        done = info["model_idx_in_bag"] * passes + info["shift_idx"]
        within = info["segment_offset"] / max(info["audio_length"], 1)
        rep.progress((done + within) / (info["models"] * passes), "separating")

    return report


def two_stem_split(sources: dict) -> dict:
    rest = sum(wav for name, wav in sources.items() if name != LEAD_STEM)
    return {LEAD_STEM: sources[LEAD_STEM], REST_STEM: rest}


def write_stems(
    sources: dict, samplerate: int, outdir: Path, base: str, fmt: str, rep: common.Reporter
) -> list[Path]:
    from demucs.api import save_audio

    written = []
    with tempfile.TemporaryDirectory() as staging:
        for name, wav in sources.items():
            raw = Path(staging if fmt == "mp3" else outdir) / f"{base}_{name}.wav"
            save_audio(wav, str(raw), samplerate=samplerate)
            final = common.encode_mp3(raw, outdir / f"{base}_{name}.mp3") if fmt == "mp3" else raw
            written.append(rep.artifact(final, kind="audio", label=name.replace("_", " ").title()))
    return written


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    from demucs.api import Separator

    rep.start(device=device, model=args.model, format=args.format, shifts=args.shifts)
    rep.progress(None, f"loading {args.model}")
    passes = max(args.shifts, 1)
    separator = Separator(
        model=args.model,
        device=device,
        shifts=args.shifts,
        callback=segment_reporter(rep, passes),
    )
    if args.two_stems and LEAD_STEM not in separator.model.sources:
        raise ValueError(f"model {args.model} has no {LEAD_STEM} stem to split on")

    _, sources = separator.separate_audio_file(source)
    if args.two_stems:
        sources = two_stem_split(sources)

    base = common.stem_of(source)
    rep.progress(1.0, f"writing {len(sources)} stems")
    written = write_stems(sources, separator.samplerate, outdir, base, args.format, rep)
    rep.artifact(common.zip_bundle(written, outdir / f"{base}_stems.zip"), kind="archive", label="All stems")
    rep.log(f"{len(written)} stems written to {outdir}")
    rep.done()


def main() -> None:
    common.run("stems", run, build_parser())
