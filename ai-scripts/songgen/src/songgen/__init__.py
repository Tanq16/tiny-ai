from __future__ import annotations

import argparse
import contextlib
import os
import secrets
import sys
from pathlib import Path
from typing import Any, NamedTuple, TextIO

import tinyai_common as common

SEED_LIMIT = 2**32
SAMPLE_RATE = 48000
SEMANTIC_FRAME_RATE = 25
ABC_TOKEN_STRIDE = 64
YUE_MODEL = "m-a-p/YuE2-3B"
YUE_VAE = "m-a-p/YuE2-Vae"
ACE_MAIN_DIT = "acestep-v15-turbo"
MIN_DURATION = 10
MAX_DURATION = 600


class Recipe(NamedTuple):
    family: str
    engine: str
    steps: int
    config: str = ""


class Rendered(NamedTuple):
    audio: Path
    seconds: float
    extras: tuple[Path, ...]
    detail: dict[str, Any]


MODELS = {
    "yue2": Recipe("yue", "YuE2-3B", 32),
    "ace-turbo": Recipe("ace", "ACE-Step 1.5 turbo", 8, ACE_MAIN_DIT),
    "ace-base": Recipe("ace", "ACE-Step 1.5 base", 32, "acestep-v15-base"),
}


class Relay:
    def __init__(self, rep: common.Reporter, stream: TextIO) -> None:
        self.rep = rep
        self.stream = stream

    def progress(self, fraction: float | None, message: str = "", **counts: int | None) -> None:
        # Both engines run with stdout redirected away, so aim the event at the real stream.
        with contextlib.redirect_stdout(self.stream):
            self.rep.progress(fraction, message, **counts)

    def log(self, message: str) -> None:
        with contextlib.redirect_stdout(self.stream):
            self.rep.log(message)

    def ace(self, value: float, desc: str = "") -> None:
        self.progress(float(value), desc)


class TokenStage:
    def __init__(self, relay: Relay, stride: int, total: int, render) -> None:
        self.relay = relay
        self.stride = stride
        self.total = total
        self.render = render
        self.count = 0

    def __call__(self, _phase: str, _token: int) -> None:
        self.count += 1
        if self.count % self.stride == 0:
            self.relay.progress(None, self.render(self.count), current=self.count, total=self.total)


def clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def run_yue(
    args: argparse.Namespace, relay: Relay, recipe: Recipe, outdir: Path, seed: int, steps: int, device: str
) -> Rendered:
    import soundfile as sf
    from yue2 import YuE2Pipeline
    from yue2.protocol import GenerationConfig

    relay.progress(None, f"loading and verifying {YUE_MODEL}")
    config = GenerationConfig(ode_steps=steps)
    pipe = YuE2Pipeline.from_pretrained(
        YUE_MODEL, vae=YUE_VAE, device=device, generation_config=config, progress=False
    )
    try:
        plan = pipe.plan(
            style=args.style,
            lyrics=args.lyrics,
            seed=seed,
            on_token=TokenStage(
                relay,
                ABC_TOKEN_STRIDE,
                config.abc.max_tokens,
                lambda n: f"planning the score, {n} tokens",
            ),
        )
        semantic = pipe.generate_semantic(
            plan,
            on_token=TokenStage(
                relay,
                SEMANTIC_FRAME_RATE,
                config.semantic.max_tokens,
                lambda n: f"composing, {clock(n / SEMANTIC_FRAME_RATE)} of audio",
            ),
        )
        relay.progress(None, f"rendering over {steps} solver steps")
        latents = pipe.synthesize(semantic)
        relay.progress(None, "decoding audio")
        audio = pipe.decode(latents)
    finally:
        pipe.close()

    if semantic.truncated:
        ceiling = clock(config.semantic.max_tokens / SEMANTIC_FRAME_RATE)
        relay.log(f"the song reached the {ceiling} ceiling and stops without an ending")

    target = outdir / "song.flac"
    sf.write(target, audio, SAMPLE_RATE, subtype="PCM_24")
    extras: tuple[Path, ...] = ()
    if plan.abc is not None:
        score = outdir / "score.abc"
        score.write_text(plan.abc, encoding="utf-8")
        extras = (score,)
    return Rendered(
        target,
        len(audio) / SAMPLE_RATE,
        extras,
        {"truncated": {"score": plan.truncated, "song": semantic.truncated}},
    )


def run_ace(
    args: argparse.Namespace, relay: Relay, recipe: Recipe, outdir: Path, seed: int, steps: int, device: str
) -> Rendered:
    checkpoints = common.cache_dir("songgen", "acestep")
    # ACE-Step reads these at import time and in its handler constructor, so the imports stay below.
    os.environ.setdefault("ACESTEP_PROJECT_ROOT", str(checkpoints))
    os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", str(checkpoints))
    os.environ.setdefault("ACESTEP_DISABLE_TQDM", "1")

    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler
    from acestep.model_downloader import DEFAULT_LM_MODEL, ensure_dit_model, ensure_main_model

    relay.progress(None, "fetching ACE-Step weights")
    ok, message = ensure_main_model(checkpoints_dir=checkpoints)
    if not ok:
        raise RuntimeError(message)
    if recipe.config != ACE_MAIN_DIT:
        ok, message = ensure_dit_model(recipe.config, checkpoints_dir=checkpoints)
        if not ok:
            raise RuntimeError(message)

    relay.progress(None, f"loading {recipe.config}")
    dit = AceStepHandler()
    status, ok = dit.initialize_service(
        project_root=str(checkpoints),
        config_path=recipe.config,
        device=device,
        use_flash_attention=False,
        compile_model=False,
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        use_mlx_dit=False,
    )
    if not ok:
        raise RuntimeError(status)

    llm = LLMHandler()
    status, ok = llm.initialize(
        checkpoint_dir=str(checkpoints),
        lm_model_path=DEFAULT_LM_MODEL,
        backend="pt",
        device=device,
        offload_to_cpu=False,
        dtype=None,
    )
    if not ok:
        raise RuntimeError(status)

    result = generate_music(
        dit,
        llm,
        GenerationParams(
            task_type="text2music",
            caption=args.style,
            lyrics=args.lyrics,
            duration=float(args.duration) if args.duration else -1.0,
            inference_steps=steps,
            seed=seed,
        ),
        GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format="flac"),
        save_dir=str(outdir),
        progress=relay.ace,
    )
    if not result.success or not result.audios:
        raise RuntimeError(result.error or result.status_message or "ACE-Step produced no audio")

    audio = result.audios[0]
    if not audio["path"]:
        raise RuntimeError("ACE-Step generated a song but could not write it to disk")
    target = outdir / "song.flac"
    Path(audio["path"]).replace(target)
    metadata = result.extra_outputs.get("lm_metadata") or {}
    return Rendered(
        target,
        audio["tensor"].shape[-1] / audio["sample_rate"],
        (),
        {
            key: metadata[key]
            for key in ("bpm", "keyscale", "timesignature", "vocal_language")
            if metadata.get(key) not in (None, "", "N/A")
        },
    )


def deliver(source: Path, fmt: str) -> Path:
    if fmt == "flac":
        return source
    target = source.with_suffix(".mp3")
    common.encode_mp3(source, target)
    source.unlink()
    return target


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    if not args.style.strip():
        raise ValueError("--style has no content")
    if not args.lyrics.strip():
        raise ValueError("--lyrics has no content")
    if args.duration and not MIN_DURATION <= args.duration <= MAX_DURATION:
        raise ValueError(
            f"--duration must be between {MIN_DURATION} and {MAX_DURATION} seconds, "
            "or 0 to let the model choose"
        )

    recipe = MODELS[args.model]
    steps = args.steps if args.steps > 0 else recipe.steps
    seed = args.seed if args.seed is not None else secrets.randbelow(SEED_LIMIT)
    device = common.resolve_device(args.device)
    if args.duration and recipe.family == "yue":
        rep.warn("--duration is an ACE-Step control; YuE2 takes its length from the lyrics and the score")

    rep.start(
        device=device,
        model=args.model,
        engine=recipe.engine,
        seed=seed,
        steps=steps,
        duration=args.duration or None,
        format=args.format,
    )
    outdir = common.ensure_outdir(args.outdir)
    relay = Relay(rep, sys.stdout)
    generate = run_yue if recipe.family == "yue" else run_ace

    # Both engines narrate weight loading on stdout, which would corrupt the NDJSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        rendered = generate(args, relay, recipe, outdir, seed, steps, device)

    target = deliver(rendered.audio, args.format)
    rep.progress(1.0, "complete")
    rep.artifact(target, kind="audio", label=f"{clock(rendered.seconds)} at seed {seed}")
    for extra in rendered.extras:
        rep.artifact(extra)
    rep.result(
        {
            "model": args.model,
            "engine": recipe.engine,
            "seed": seed,
            "steps": steps,
            "seconds": round(rendered.seconds, 2),
            "sample_rate": SAMPLE_RATE,
            "file": target.name,
            **rendered.detail,
        }
    )
    rep.done()


parser = common.base_parser("songgen", "Generate a full song from a style prompt and lyrics.")
parser.add_argument("--style", required=True, help="style tags, instruments, voice and tempo")
parser.add_argument("--lyrics", required=True, help="lyrics, with [Verse] and [Chorus] section markers")
parser.add_argument("--model", default="yue2", choices=tuple(MODELS), help="model to generate with")
parser.add_argument(
    "--duration",
    type=float,
    default=0,
    help="target length in seconds, ACE-Step only; 0 lets the model choose",
)
parser.add_argument("--seed", type=int, default=None, help="seed to reproduce a run; random when unset")
parser.add_argument("--steps", type=int, default=0, help="solver steps; 0 takes the model's own default")
parser.add_argument("--format", default="flac", choices=("flac", "mp3"), help="output audio format")


def main() -> None:
    common.run("songgen", run, parser)
