"""Generates images from a prompt, and optionally from reference pictures, with FLUX.2 Klein."""

from __future__ import annotations

import argparse
import contextlib
import secrets
import sys
from pathlib import Path
from typing import NamedTuple, TextIO

import tinyai_common as common

SEED_LIMIT = 2**32
LOAD_SHARE = 0.12
STEP_SHARE = 0.95
SIZE_MULTIPLE = 16
MAX_REFERENCES = 4


class Recipe(NamedTuple):
    config: str
    steps: int
    guidance: float
    quantize: int | None = 8
    path: str | None = None


# Distilled Klein checkpoints reject any guidance but 1.0; only the base ones take a scale.
MODELS = {
    "klein-4b": Recipe("flux2_klein_4b", 4, 1.0),
    "klein-4b-4bit": Recipe("flux2_klein_4b", 4, 1.0, None, "Runpod/FLUX.2-klein-4B-mflux-4bit"),
    "klein-9b": Recipe("flux2_klein_9b", 4, 1.0, None, "mflux-community/flux2-klein-9b-mflux-q8"),
    "klein-base-4b": Recipe(
        "flux2_klein_base_4b", 50, 3.5, None, "mflux-community/flux-2-klein-base-4b-mflux-q8"
    ),
    "klein-base-9b": Recipe(
        "flux2_klein_base_9b", 50, 3.5, None, "mflux-community/flux-2-klein-base-9b-mflux-q8"
    ),
}


class StepReporter:
    """Relays mflux's denoising loop into the event stream; mflux finds it by method name."""

    def __init__(self, rep: common.Reporter, total: int, stream: TextIO) -> None:
        self.rep = rep
        self.total = total
        self.stream = stream
        self.offset = 0

    def call_in_loop(self, t: int, **_: object) -> None:
        done = self.offset + t + 1
        # The loop runs with stdout redirected away, so aim the event back at the real stream.
        with contextlib.redirect_stdout(self.stream):
            self.rep.progress(
                LOAD_SHARE + (STEP_SHARE - LOAD_SHARE) * done / self.total,
                f"step {done} of {self.total}",
                current=done,
                total=self.total,
            )


def parse_size(value: str, references: list[str]) -> tuple[int, int]:
    if value.strip().lower() == "match":
        return match_size(references)
    width, _, height = value.lower().partition("x")
    try:
        size = (int(width), int(height))
    except ValueError:
        raise ValueError(f"--size must look like 1024x1024 or be 'match', got {value!r}") from None
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"--size must be positive, got {value!r}")
    return size


def match_size(references: list[str]) -> tuple[int, int]:
    if not references:
        raise ValueError("--size match needs at least one --reference")
    from PIL import Image, ImageOps

    with Image.open(references[0]) as source:
        width, height = ImageOps.exif_transpose(source).size
    return (
        max(SIZE_MULTIPLE, width - width % SIZE_MULTIPLE),
        max(SIZE_MULTIPLE, height - height % SIZE_MULTIPLE),
    )


def parse_loras(spec: str) -> tuple[list[str], list[float]]:
    paths: list[str] = []
    scales: list[float] = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        ref, sep, tail = entry.rpartition(":")
        scale = 1.0
        if sep and ref.strip():
            try:
                scale = float(tail)
                entry = ref.strip()
            except ValueError:
                pass
        paths.append(entry)
        scales.append(scale)
    return paths, scales


def load_model(recipe: Recipe, editing: bool, lora_paths: list[str], lora_scales: list[float]):
    from mflux.models.common.config import ModelConfig
    from mflux.models.flux2.variants import Flux2Klein, Flux2KleinEdit

    generator = Flux2KleinEdit if editing else Flux2Klein
    # mflux narrates weight loading on stdout, which would corrupt the NDJSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        return generator(
            quantize=recipe.quantize,
            model_path=recipe.path,
            model_config=getattr(ModelConfig, recipe.config)(),
            lora_paths=lora_paths or None,
            lora_scales=lora_scales or None,
        )


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    if not args.prompt.strip():
        raise ValueError("--prompt has no content")
    if len(args.reference) > MAX_REFERENCES:
        raise ValueError(f"--reference takes at most {MAX_REFERENCES} pictures")
    references = [str(common.require_file(path, "reference")) for path in args.reference]

    recipe = MODELS[args.model]
    width, height = parse_size(args.size, references)
    steps = args.steps if args.steps > 0 else recipe.steps
    variants = max(args.variants, 1)
    base = args.seed if args.seed is not None else secrets.randbelow(SEED_LIMIT)
    seeds = [(base + i) % SEED_LIMIT for i in range(variants)]
    lora_paths, lora_scales = parse_loras(args.lora)

    rep.start(
        device="mlx",
        model=args.model,
        seed=base,
        steps=steps,
        variants=variants,
        size=f"{width}x{height}",
        references=len(references),
        loras=len(lora_paths),
    )
    outdir = common.ensure_outdir(args.outdir)

    rep.progress(0.02, f"loading {args.model}")
    model = load_model(recipe, bool(references), lora_paths, lora_scales)
    for path, scale in zip(lora_paths, lora_scales, strict=True):
        rep.log(f"loaded LoRA {path} at {scale}")

    reporter = StepReporter(rep, steps * variants, sys.stdout)
    model.callbacks.register(reporter)
    rep.progress(LOAD_SHARE, f"step 0 of {steps * variants}", current=0, total=steps * variants)

    written = []
    for index, seed in enumerate(seeds):
        reporter.offset = index * steps
        extra = {"image_paths": [Path(p) for p in references]} if references else {}
        with contextlib.redirect_stdout(sys.stderr):
            generated = model.generate_image(
                seed=seed,
                prompt=args.prompt,
                num_inference_steps=steps,
                width=width,
                height=height,
                guidance=recipe.guidance,
                **extra,
            )
        image = getattr(generated, "image", generated)
        target = outdir / ("image.png" if variants == 1 else f"image-{index + 1}.png")
        image.save(target)
        rep.artifact(target, kind="image", label=f"Seed {seed}")
        written.append({"file": target.name, "seed": seed})

    rep.progress(1.0, "complete")
    rep.result(
        {
            "model": args.model,
            "seed": base,
            "seeds": seeds,
            "steps": steps,
            "width": width,
            "height": height,
            "references": [Path(p).name for p in references],
            "images": written,
            "loras": [f"{path}:{scale}" for path, scale in zip(lora_paths, lora_scales, strict=True)],
        }
    )
    rep.done()


parser = common.base_parser("imagegen", "Generate images with a local FLUX.2 Klein model.")
parser.add_argument("--prompt", required=True, help="what to draw")
parser.add_argument("--model", default="klein-4b", choices=tuple(MODELS), help="model to generate with")
parser.add_argument(
    "--reference",
    action="append",
    default=[],
    help=f"picture to draw from, repeatable up to {MAX_REFERENCES} times",
)
parser.add_argument("--size", default="1024x1024", help="output size as WIDTHxHEIGHT, or match")
parser.add_argument("--seed", type=int, default=None, help="seed to reproduce a run; random when unset")
parser.add_argument("--variants", type=int, default=1, help="images to draw, on consecutive seeds")
parser.add_argument("--steps", type=int, default=0, help="denoising steps; 0 takes the model's own default")
parser.add_argument(
    "--lora",
    default="",
    help="library names, HuggingFace repos or .safetensors paths, comma separated, each optionally :scale",
)


def main() -> None:
    common.run("imagegen", run, parser)
