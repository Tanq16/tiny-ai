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
OVERLAP = 4
RELEASES = "https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download"
CONFIGS = "https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/v1.0.22/configs"
STEM_LABELS = {"rest": "Everything else"}

FOUR = ("drums", "bass", "other", "vocals")
SIX = ("vocals", "drums", "bass", "guitar", "piano", "other")
RHYTHM = ("drums", "bass", "vocals")


@dataclass(frozen=True)
class Demucs:
    name: str


@dataclass(frozen=True)
class Msst:
    kind: str
    config: str
    weights: str


MODELS: dict[str, Demucs | Msst] = {
    "htdemucs": Demucs("htdemucs"),
    "htdemucs_ft": Demucs("htdemucs_ft"),
    "htdemucs_6s": Demucs("htdemucs_6s"),
    "scnet_xl": Msst(
        "scnet",
        f"{RELEASES}/v1.0.15/config_musdb18_scnet_xl_more_wide_v5.yaml",
        f"{RELEASES}/v1.0.15/model_scnet_ep_36_sdr_10.0891.ckpt",
    ),
    "bs_roformer": Msst(
        "bs_roformer",
        f"{RELEASES}/v1.0.12/config_bs_roformer_384_8_2_485100.yaml",
        f"{RELEASES}/v1.0.12/model_bs_roformer_ep_17_sdr_9.6568.ckpt",
    ),
    "melband_vocals": Msst(
        "mel_band_roformer",
        f"{CONFIGS}/KimberleyJensen/config_vocals_mel_band_roformer_kj.yaml",
        "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt",
    ),
    "bs_roformer_vocals": Msst(
        "bs_roformer",
        f"{CONFIGS}/viperx/model_bs_roformer_ep_317_sdr_12.9755.yaml",
        "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/"
        "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    ),
}


@dataclass(frozen=True)
class Preset:
    sources: tuple[tuple[str, tuple[str, ...]], ...]
    outputs: tuple[str, ...]
    residual: str = ""
    tta: bool = False


PRESETS: dict[str, Preset] = {
    "four-fast": Preset((("htdemucs", FOUR),), FOUR),
    "four-better": Preset((("scnet_xl", FOUR),), FOUR),
    "four-best": Preset(
        (("scnet_xl", FOUR), ("bs_roformer", FOUR), ("htdemucs_ft", FOUR)),
        FOUR,
        tta=True,
    ),
    "six-better": Preset((("htdemucs_6s", SIX),), SIX),
    "six-best": Preset(
        (
            ("scnet_xl", RHYTHM),
            ("bs_roformer", RHYTHM),
            ("htdemucs_ft", RHYTHM),
            ("htdemucs_6s", ("guitar", "piano")),
        ),
        SIX,
        residual="other",
        tta=True,
    ),
    "drums-fast": Preset(
        (("scnet_xl", ("drums",)),), ("drums", "rest"), residual="rest"
    ),
    "drums-best": Preset(
        (
            ("scnet_xl", ("drums",)),
            ("bs_roformer", ("drums",)),
            ("htdemucs_ft", ("drums",)),
        ),
        ("drums", "rest"),
        residual="rest",
        tta=True,
    ),
    "vocals-fast": Preset(
        (("melband_vocals", ("vocals",)),), ("vocals", "instrumental"), residual="instrumental"
    ),
    "vocals-best": Preset(
        (("melband_vocals", ("vocals",)), ("bs_roformer_vocals", ("vocals",))),
        ("vocals", "instrumental"),
        residual="instrumental",
        tta=True,
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = common.base_parser("stems", "Split a track into stems.")
    parser.add_argument("--input", required=True, help="audio file to separate")
    parser.add_argument(
        "--preset",
        default="four-fast",
        choices=tuple(PRESETS),
        help="model combination and the split it produces",
    )
    parser.add_argument("--format", default="wav", choices=("wav", "mp3"), help="stem file format")
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="averaging passes over shifted copies that trade time for separation quality",
    )
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

    audio, _ = librosa.load(str(source), sr=SAMPLE_RATE, mono=False)
    if audio.ndim == 1:
        audio = np.stack([audio, audio])
    return np.ascontiguousarray(audio, dtype=np.float32)


def run_demucs(spec: Demucs, mix: np.ndarray, passes: int, device: str, tracker: Tracker) -> dict:
    import torch
    from demucs.api import Separator

    def report(info: dict) -> None:
        if info.get("state") != "end":
            return
        done = info["model_idx_in_bag"] * passes + info["shift_idx"]
        within = info["segment_offset"] / max(info["audio_length"], 1)
        tracker.at((done + within) / (info["models"] * passes))

    separator = Separator(model=spec.name, device=device, shifts=passes, callback=report)
    _, sources = separator.separate_tensor(torch.from_numpy(mix), SAMPLE_RATE)
    return {name: wav.cpu().numpy().astype(np.float32) for name, wav in sources.items()}


def run_msst(
    key: str, spec: Msst, mix: np.ndarray, passes: int, tta: bool, device: str,
    rep: common.Reporter, tracker: Tracker,
) -> dict:
    import torch
    from utils.model_utils import apply_tta, bigshifts_wrapper
    from utils.settings import get_model_from_config

    store = common.cache_dir("stems")
    config_path = common.download(spec.config, store / f"{key}.yaml", rep, label=f"{key} config")
    weights_path = common.download(spec.weights, store / f"{key}.ckpt", rep, label=f"{key} weights")

    model, config = get_model_from_config(spec.kind, str(config_path))
    rate = int(config.audio.sample_rate)
    if rate != SAMPLE_RATE:
        raise ValueError(f"{key} expects {rate} Hz, which this task does not resample to")
    config.training.use_amp = False
    config.inference.num_overlap = OVERLAP

    weights = torch.load(str(weights_path), map_location="cpu", weights_only=False)
    for wrapper in ("state", "state_dict", "model_state_dict"):
        if isinstance(weights, dict) and wrapper in weights:
            weights = weights[wrapper]
    model.load_state_dict(weights)
    model = model.to(device).eval()

    sources = bigshifts_wrapper(
        config, model, mix, device, model_type=spec.kind, pbar=True, bigshifts=passes
    )
    if tta:
        sources = apply_tta(
            config, model, mix, sources, device, spec.kind, bigshifts=passes, pbar=True
        )
    del model
    return {name: np.asarray(wav, dtype=np.float32) for name, wav in sources.items()}


def separate(
    preset: Preset, mix: np.ndarray, passes: int, device: str, rep: common.Reporter, tracker: Tracker
) -> dict:
    gathered: dict[str, list[np.ndarray]] = {}
    span = 1.0 / len(preset.sources)
    for index, (key, wanted) in enumerate(preset.sources):
        spec = MODELS[key]
        slots = passes * (3 if preset.tta and isinstance(spec, Msst) else 1)
        tracker.phase(f"separating with {key}", index * span, span, slots)
        if isinstance(spec, Demucs):
            produced = run_demucs(spec, mix, passes, device, tracker)
        else:
            produced = run_msst(key, spec, mix, passes, preset.tta, device, rep, tracker)
        missing = [name for name in wanted if name not in produced]
        if missing:
            raise ValueError(f"{key} produced no {', '.join(missing)} stem")
        for name in wanted:
            gathered.setdefault(name, []).append(produced[name])

    stems = {name: np.mean(takes, axis=0) for name, takes in gathered.items()}
    if preset.residual:
        others = [stems[name] for name in preset.outputs if name != preset.residual]
        stems[preset.residual] = mix - np.sum(others, axis=0)
    return {name: stems[name] for name in preset.outputs}


def write_stems(
    stems: dict, outdir: Path, base: str, fmt: str, rep: common.Reporter
) -> list[Path]:
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
    passes = max(args.passes, 1)

    rep.start(device=device, preset=args.preset, format=args.format, passes=passes)
    tracker = Tracker(rep)
    if any(isinstance(MODELS[key], Msst) for key, _ in preset.sources):
        install_progress(tracker)

    rep.progress(None, "reading the track")
    mix = load_mix(source)
    stems = separate(preset, mix, passes, device, rep, tracker)

    base = common.stem_of(source)
    rep.progress(1.0, f"writing {len(stems)} stems")
    written = write_stems(stems, outdir, base, args.format, rep)
    rep.artifact(common.zip_bundle(written, outdir / f"{base}_stems.zip"), kind="archive", label="All stems")
    rep.log(f"{len(written)} stems written to {outdir}")
    rep.done()


def main() -> None:
    common.run("stems", run, build_parser())
