"""Splits a track into instrument stems."""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tinyai_common as common

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

SAMPLE_RATE = 44100
MODEL_KIND = "bs_roformer"
MODEL_HOST = "https://huggingface.co/lainlives/audio-separator-models/resolve/main"
MODEL_CONFIG = f"{MODEL_HOST}/BS-Roformer-SW.yaml"
MODEL_WEIGHTS = f"{MODEL_HOST}/BS-Roformer-SW.ckpt"
STEM_LABELS = {"rest": "Everything else"}

FOUR = ("drums", "bass", "other", "vocals")
SIX = ("vocals", "drums", "bass", "guitar", "piano", "other")


@dataclass(frozen=True)
class Preset:
    outputs: tuple[str, ...]
    residual: str
    tta: bool = False


PRESETS: dict[str, Preset] = {
    "four-fast": Preset(FOUR, "other"),
    "four-best": Preset(FOUR, "other", tta=True),
    "six-fast": Preset(SIX, "other"),
    "six-best": Preset(SIX, "other", tta=True),
    "drums-fast": Preset(("drums", "rest"), "rest"),
    "drums-best": Preset(("drums", "rest"), "rest", tta=True),
    "vocals-fast": Preset(("vocals", "instrumental"), "instrumental"),
    "vocals-best": Preset(("vocals", "instrumental"), "instrumental", tta=True),
}


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("stems", "Split a track into stems.")
    parser.add_argument("--input", required=True, help="audio file to separate")
    parser.add_argument(
        "--preset",
        default="four-fast",
        choices=tuple(PRESETS),
        help="the split to produce and how much time to spend on it",
    )
    parser.add_argument("--format", default="wav", choices=("wav", "mp3"), help="stem file format")
    return parser


@dataclass
class Tracker:
    rep: common.Reporter
    label: str = ""
    base: float = 0.0
    span: float = 1.0
    slots: int = 1
    slot: int = -1

    def phase(self, label: str, base: float, span: float, slots: int) -> None:
        self.label, self.base, self.span = label, base, span
        self.slots, self.slot = max(slots, 1), -1
        self.rep.progress(base, label)

    def open(self) -> None:
        self.slot = min(self.slot + 1, self.slots - 1)

    def at(self, fraction: float) -> None:
        within = min(max(fraction, 0.0), 1.0)
        done = (max(self.slot, 0) + within) / self.slots
        self.rep.progress(self.base + self.span * done, self.label)


def install_progress(tracker: Tracker) -> None:
    from utils import model_utils

    class Bar:
        def __init__(self, iterable=None, total=None, **_) -> None:
            self.iterable = iterable
            self.total = total or 0
            self.seen = 0
            if iterable is None:
                tracker.open()

        def __iter__(self):
            return iter(self.iterable or ())

        def update(self, amount: int = 1) -> None:
            self.seen += amount
            if self.total:
                tracker.at(self.seen / self.total)

        def close(self) -> None:
            return None

    # demix reports its chunk loop only through this module-level tqdm name.
    model_utils.tqdm = Bar


def load_mix(source: Path) -> np.ndarray:
    import librosa

    with common.readable_audio(source) as readable:
        audio, _ = librosa.load(str(readable), sr=SAMPLE_RATE, mono=False)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    return np.ascontiguousarray(audio, dtype=np.float32)


def load_model(device: str, rep: common.Reporter):
    import torch
    from utils.settings import get_model_from_config

    store = common.cache_dir("stems")
    config_path = common.download(MODEL_CONFIG, store / "bs_roformer_sw.yaml", rep, label="model config")
    weights_path = common.download(MODEL_WEIGHTS, store / "bs_roformer_sw.ckpt", rep, label="model weights")

    model, config = get_model_from_config(MODEL_KIND, str(config_path))
    rate = int(config.audio.sample_rate)
    if rate != SAMPLE_RATE:
        raise ValueError(f"the model expects {rate} Hz, which this task does not resample to")
    config.training.use_amp = False

    weights = torch.load(str(weights_path), map_location="cpu", weights_only=False)
    for wrapper in ("state", "state_dict", "model_state_dict"):
        if isinstance(weights, dict) and wrapper in weights:
            weights = weights[wrapper]
    model.load_state_dict(weights)
    return model.to(device).eval(), config


def separate(preset: Preset, mix: np.ndarray, device: str, rep: common.Reporter, tracker: Tracker) -> dict:
    from utils.model_utils import apply_tta, demix

    model, config = load_model(device, rep)
    tracker.phase("separating", 0.0, 1.0, 3 if preset.tta else 1)
    produced = demix(config, model, mix, device, MODEL_KIND, pbar=True)
    if preset.tta:
        produced = apply_tta(config, model, mix, produced, device, MODEL_KIND, bigshifts=1, pbar=True)
    del model

    stems: dict[str, np.ndarray] = {}
    for name in preset.outputs:
        if name == preset.residual:
            continue
        if name not in produced:
            raise ValueError(f"the model produced no {name} stem")
        stems[name] = np.asarray(produced[name], dtype=np.float32)
    stems[preset.residual] = mix - np.sum(list(stems.values()), axis=0)
    return {name: stems[name] for name in preset.outputs}


def write_stems(stems: dict, outdir: Path, base: str, fmt: str, rep: common.Reporter) -> list[Path]:
    import soundfile as sf

    written = []
    with tempfile.TemporaryDirectory() as staging:
        for name, wav in stems.items():
            raw = Path(staging if fmt == "mp3" else outdir) / f"{base}_{name}.wav"
            sf.write(str(raw), np.asarray(wav).T, SAMPLE_RATE, subtype="FLOAT")
            final = common.encode_mp3(raw, outdir / f"{base}_{name}.mp3") if fmt == "mp3" else raw
            label = STEM_LABELS.get(name, name.replace("_", " ").title())
            written.append(rep.artifact(final, kind="audio", label=label))
    return written


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)
    preset = PRESETS[args.preset]

    rep.start(device=device, preset=args.preset, format=args.format)
    tracker = Tracker(rep)
    install_progress(tracker)

    rep.progress(None, "reading the track")
    mix = load_mix(source)
    stems = separate(preset, mix, device, rep, tracker)

    base = common.stem_of(source)
    rep.progress(1.0, f"writing {len(stems)} stems")
    written = write_stems(stems, outdir, base, args.format, rep)
    rep.artifact(common.zip_bundle(written, outdir / f"{base}_stems.zip"), kind="archive", label="All stems")
    rep.log(f"{len(written)} stems written to {outdir}")
    rep.done()


def main() -> None:
    common.run("stems", run, build_parser())
