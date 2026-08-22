"""Generates an image from a text prompt with an MLX diffusion model through mflux."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import secrets
import sys
from typing import NamedTuple, TextIO

import tinyai_common as common

SEED_LIMIT = 2**32
LOAD_SHARE = 0.15
STEP_SHARE = 0.95


class Recipe(NamedTuple):
    module: str
    entry: str
    config: str
    steps: int
    quantize: int | None = 8
    path: str | None = None


# Only ungated weights, so a first run never stops to ask for a HuggingFace login.
MODELS = {
    "z-image-turbo-4bit": Recipe(
        "mflux.models.z_image",
        "ZImageTurbo",
        "z_image_turbo",
        9,
        None,
        "filipstrand/Z-Image-Turbo-mflux-4bit",
    ),
    "z-image-turbo": Recipe("mflux.models.z_image", "ZImageTurbo", "z_image_turbo", 9),
    "flux2-klein-4b": Recipe("mflux.models.flux2", "Flux2Klein", "flux2_klein_4b", 4),
    "qwen-image": Recipe("mflux.models.qwen.variants.txt2img.qwen_image", "QwenImage", "qwen_image", 30),
}


class StepReporter:
    """Relays mflux's denoising loop into the event stream; mflux finds it by method name."""

    def __init__(self, rep: common.Reporter, total: int, stream: TextIO) -> None:
        self.rep = rep
        self.total = total
        self.stream = stream

    def call_in_loop(self, t: int, **_: object) -> None:
        done = t + 1
        # The loop runs with stdout redirected away, so aim the event back at the real stream.
        with contextlib.redirect_stdout(self.stream):
            self.rep.progress(
                LOAD_SHARE + (STEP_SHARE - LOAD_SHARE) * done / self.total,
                f"step {done} of {self.total}",
                current=done,
                total=self.total,
            )


def parse_size(value: str) -> tuple[int, int]:
    width, _, height = value.lower().partition("x")
    try:
        size = (int(width), int(height))
    except ValueError:
        raise ValueError(f"--size must look like 1024x1024, got {value!r}") from None
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"--size must be positive, got {value!r}")
    return size


def parse_quantize(value: str) -> int | None:
    return None if value == "none" else int(value)


def parse_loras(spec: str) -> tuple[list[str], list[float]]:
    """Splits `repo-or-path[:scale], ...` into the parallel lists mflux takes."""
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


def load_model(recipe: Recipe, quantize: int | None, lora_paths: list[str], lora_scales: list[float]):
    from mflux.models.common.config import ModelConfig

    module = importlib.import_module(recipe.module)
    generator = getattr(module, recipe.entry)
    # mflux narrates weight loading on stdout, which would corrupt the NDJSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        return generator(
            quantize=quantize,
            model_path=recipe.path,
            model_config=getattr(ModelConfig, recipe.config)(),
            lora_paths=lora_paths or None,
            lora_scales=lora_scales or None,
        )


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    if not args.prompt.strip():
        raise ValueError("--prompt has no content")
    recipe = MODELS[args.model]
    width, height = parse_size(args.size)
    steps = args.steps if args.steps > 0 else recipe.steps
    seed = args.seed if args.seed is not None else secrets.randbelow(SEED_LIMIT)
    quantize = recipe.quantize if args.quantize is None else parse_quantize(args.quantize)
    lora_paths, lora_scales = parse_loras(args.lora)

    rep.start(
        device="mlx",
        model=args.model,
        seed=seed,
        steps=steps,
        size=f"{width}x{height}",
        quantize=quantize,
        loras=len(lora_paths),
    )
    outdir = common.ensure_outdir(args.outdir)

    rep.progress(0.02, f"loading {args.model}")
    model = load_model(recipe, quantize, lora_paths, lora_scales)
    for path, scale in zip(lora_paths, lora_scales, strict=True):
        rep.log(f"loaded LoRA {path} at {scale}")

    model.callbacks.register(StepReporter(rep, steps, sys.stdout))
    rep.progress(LOAD_SHARE, f"step 0 of {steps}", current=0, total=steps)
    with contextlib.redirect_stdout(sys.stderr):
        generated = model.generate_image(
            seed=seed,
            prompt=args.prompt,
            num_inference_steps=steps,
            width=width,
            height=height,
        )

    rep.progress(0.97, "writing artifacts")
    image = getattr(generated, "image", generated)
    target = outdir / "image.png"
    image.save(target)
    rep.artifact(target, kind="image", label="Generated image")

    rep.progress(1.0, "complete")
    rep.result(
        {
            "model": args.model,
            "seed": seed,
            "steps": steps,
            "width": image.width,
            "height": image.height,
            "quantize": quantize,
            "loras": [f"{path}:{scale}" for path, scale in zip(lora_paths, lora_scales, strict=True)],
        }
    )
    rep.done()


parser = common.base_parser("imagegen", "Generate an image from a text prompt with a local MLX model.")
parser.add_argument("--prompt", required=True, help="what to draw")
parser.add_argument(
    "--model", default="z-image-turbo-4bit", choices=tuple(MODELS), help="model to generate with"
)
parser.add_argument("--size", default="1024x1024", help="output size as WIDTHxHEIGHT")
parser.add_argument("--seed", type=int, default=None, help="seed to reproduce a run; random when unset")
parser.add_argument("--steps", type=int, default=0, help="denoising steps; 0 takes the model's own default")
parser.add_argument(
    "--quantize",
    default=None,
    choices=("4", "8", "none"),
    help="override the weight quantization the chosen model ships with",
)
parser.add_argument(
    "--lora",
    default="",
    help="comma separated HuggingFace repos or .safetensors paths, each optionally suffixed with :scale",
)


def main() -> None:
    common.run("imagegen", run, parser)
