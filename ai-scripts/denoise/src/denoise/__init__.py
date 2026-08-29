"""Strips room noise, hum and static out of a recording with DeepFilterNet3."""

from __future__ import annotations

import argparse
import shutil
import warnings

import tinyai_common as common

UNCAPPED_ATTENUATION = 100.0

# torchaudio below 2.9 is pinned for the deepfilternet I/O path and deprecates itself loudly.
warnings.filterwarnings("ignore", category=UserWarning, module=r"df\.|torchaudio")


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("denoise", "Enhance a noisy recording with DeepFilterNet3.")
    parser.add_argument("--input", required=True, help="audio file to enhance")
    parser.add_argument(
        "--attenuation",
        type=float,
        default=UNCAPPED_ATTENUATION,
        help="caps how far noise is pushed down, in dB",
    )
    parser.add_argument(
        "--keep-original",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="copy the input next to the result",
    )
    return parser


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    from df import config
    from df.enhance import DEFAULT_MODEL, enhance, init_df
    from df.io import load_audio, save_audio

    rep.start(device=device, model=DEFAULT_MODEL, attenuation=args.attenuation)
    rep.progress(None, f"loading {DEFAULT_MODEL}")
    model, df_state, _ = init_df(log_file=None, log_level="ERROR")
    config.set("DEVICE", device, str, "train")
    model = model.to(device)

    with common.readable_audio(source) as readable:
        audio, meta = load_audio(str(readable), sr=df_state.sr())
    seconds = audio.shape[-1] / df_state.sr()
    rep.log(f"{meta.num_channels} channels at {meta.sample_rate} Hz, {seconds:.1f}s")

    rep.progress(None, "enhancing")
    # The catalog caps attenuation at 100 dB, which the engine spells as no cap at all.
    limit = None if args.attenuation >= UNCAPPED_ATTENUATION else args.attenuation
    enhanced = enhance(model, df_state, audio, atten_lim_db=limit)

    rep.progress(1.0, "writing audio")
    base = common.stem_of(source)
    target = outdir / f"{base}_enhanced.wav"
    save_audio(str(target), enhanced, df_state.sr())
    rep.artifact(target, kind="audio", label="Enhanced")

    if args.keep_original:
        kept = outdir / f"{base}_original{source.suffix}"
        if kept != source:
            shutil.copy2(source, kept)
        rep.artifact(kept, kind="audio", label="Original")
    rep.done()


def main() -> None:
    common.run("denoise", run, build_parser())
