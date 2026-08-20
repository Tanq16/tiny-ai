"""Raises the resolution of an image with a Real-ESRGAN checkpoint run through spandrel."""

from __future__ import annotations

import argparse
import math
import shutil

import tinyai_common as common

WEIGHTS = {
    "anime6b": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
    "x4plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "x2plus": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
}
TILE_OVERLAP = 16


def load_model(name: str, device: str, rep: common.Reporter):
    import spandrel

    url = WEIGHTS[name]
    target = common.cache_dir("models") / url.rsplit("/", 1)[-1]
    common.download(url, target, rep, label=name)
    return spandrel.ModelLoader(device).load_from_file(target).eval()


def run_tiled(model, tensor, tile: int, rep: common.Reporter):
    import torch

    scale = model.scale
    height, width = tensor.shape[2], tensor.shape[3]
    if tile <= 0:
        rep.progress(0.3, "upscaling", current=0, total=1)
        output = model(tensor)
        rep.progress(0.85, "upscaling", current=1, total=1)
        return output

    rows, columns = math.ceil(height / tile), math.ceil(width / tile)
    total = rows * columns
    output = torch.zeros(
        (1, model.output_channels, height * scale, width * scale),
        dtype=tensor.dtype,
        device=tensor.device,
    )
    done = 0
    for row in range(rows):
        for column in range(columns):
            top, left = row * tile, column * tile
            bottom, right = min(top + tile, height), min(left + tile, width)
            outer_top, outer_left = max(top - TILE_OVERLAP, 0), max(left - TILE_OVERLAP, 0)
            outer_bottom = min(bottom + TILE_OVERLAP, height)
            outer_right = min(right + TILE_OVERLAP, width)

            patch = model(tensor[:, :, outer_top:outer_bottom, outer_left:outer_right])
            inner_top, inner_left = (top - outer_top) * scale, (left - outer_left) * scale
            output[:, :, top * scale : bottom * scale, left * scale : right * scale] = patch[
                :,
                :,
                inner_top : inner_top + (bottom - top) * scale,
                inner_left : inner_left + (right - left) * scale,
            ]
            done += 1
            rep.progress(0.3 + 0.55 * done / total, f"tile {done}/{total}", current=done, total=total)
    return output


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    if not 1.0 <= args.scale <= 4.0:
        raise ValueError(f"scale must be between 1.0 and 4.0, got {args.scale}")
    source = common.require_file(args.input, "input")
    outdir = common.ensure_outdir(args.outdir)
    device = common.resolve_device(args.device)

    rep.start(device=device, input=str(source), model=args.model, scale=args.scale, tile=args.tile)

    import numpy as np
    import torch
    from PIL import Image

    image = Image.open(source).convert("RGB")

    rep.progress(0.05, f"loading {args.model} weights")
    model = load_model(args.model, device, rep)
    rep.log(f"{model.architecture.name} at native {model.scale}x")

    pixels = np.asarray(image, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0).to(device)
    output = run_tiled(model, tensor, max(args.tile, 0), rep)

    rep.progress(0.9, "writing artifacts")
    rgb = (output.squeeze(0).permute(1, 2, 0).clamp(0, 1) * 255).round().to(torch.uint8)
    upscaled = Image.fromarray(rgb.cpu().numpy())
    target_size = (round(image.width * args.scale), round(image.height * args.scale))
    if upscaled.size != target_size:
        upscaled = upscaled.resize(target_size, Image.Resampling.LANCZOS)

    original = outdir / f"original{source.suffix}"
    if original != source:
        shutil.copy2(source, original)
    rep.artifact(original, kind="image", label="Original")

    target = outdir / "upscaled.png"
    upscaled.save(target)
    rep.artifact(target, kind="image", label="Upscaled")

    rep.progress(1.0, "complete")
    rep.result(
        {
            "model": args.model,
            "source_size": [image.width, image.height],
            "output_size": list(upscaled.size),
        }
    )
    rep.done()


parser = common.base_parser("upscale", "Upscale an image with Real-ESRGAN weights via spandrel.")
parser.add_argument("--input", required=True, help="image to upscale")
parser.add_argument(
    "--model", default="anime6b", choices=tuple(WEIGHTS), help="Real-ESRGAN checkpoint to run"
)
parser.add_argument("--scale", type=float, default=2.0, help="final size factor, 1.0 to 4.0")
parser.add_argument("--tile", type=int, default=400, help="tile size in pixels; 0 disables tiling")


def main() -> None:
    common.run("upscale", run, parser)
