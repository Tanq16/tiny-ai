"""Holds a multi-turn conversation with a local Gemma through MLX, over text, images and audio."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import tinyai_common as common

MAX_TOKENS = 4096
TEMPERATURE = 0.7
VOICE_ONLY = "[voice message]"

ROLE_HEADINGS = {"user": "You", "assistant": "Assistant", "error": "Error"}


class Turn:
    def __init__(self, role: str, text: str, files: list[str]) -> None:
        self.role = role
        self.text = text
        self.files = files


def probe(repo: str) -> tuple[bool, bool]:
    from huggingface_hub import hf_hub_download

    config = json.loads(Path(hf_hub_download(repo, "config.json")).read_text(encoding="utf-8"))
    return bool(config.get("audio_config")), bool(config.get("vision_config"))


class Session:
    def __init__(self, repo: str, system: str, rep: common.Reporter) -> None:
        self.repo = repo
        self.rep = rep
        self.model = None
        self.processor = None
        self.prompt_cache = None
        self.images: list[str] = []
        self.messages: list[dict[str, Any]] = []
        if system:
            self.messages.append({"role": "system", "content": [{"type": "text", "text": system}]})

    def load(self) -> tuple[Any, Any]:
        if self.model is not None:
            return self.model, self.processor
        from mlx_vlm import load
        from mlx_vlm.generate import PromptCacheState

        self.rep.progress(None, f"loading {self.repo}")
        # Weight loading narrates on stdout, which would corrupt the NDJSON stream.
        with contextlib.redirect_stdout(sys.stderr):
            self.model, self.processor = load(self.repo)
        self.prompt_cache = PromptCacheState()
        self.rep.log(f"loaded {self.repo}")
        return self.model, self.processor

    def reply(self, text: str, images: list[str], audio: list[str]) -> str:
        from mlx_vlm import stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        model, processor = self.load()
        self.images.extend(images)
        content: list[dict[str, Any]] = [{"type": "image"} for _ in images]
        content.append({"type": "text", "text": text or VOICE_ONLY})
        self.messages.append({"role": "user", "content": content})

        prompt = apply_chat_template(
            processor,
            model.config,
            self.messages,
            num_images=len(self.images),
            num_audios=len(audio),
        )
        answer = ""
        # mlx-vlm 0.6.17 returns degenerate text for gemma4 when passed a VisionFeatureCache,
        # so every turn re-encodes its pictures.
        for chunk in stream_generate(
            model,
            processor,
            prompt,
            image=self.images or None,
            audio=audio or None,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            prompt_cache_state=self.prompt_cache,
        ):
            answer += chunk.text
            self.rep.delta(chunk.text)

        answer = answer.strip()
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
        return answer


def write_transcript(outdir: Path, repo: str, turns: list[Turn]) -> Path:
    lines = [f"# Chat with {repo}", ""]
    for turn in turns:
        lines += [f"## {ROLE_HEADINGS.get(turn.role, turn.role)}", ""]
        if turn.files:
            lines += ["Attached: " + ", ".join(turn.files), ""]
        lines += [turn.text, ""]
    target = outdir / "chat.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def read_command(line: str) -> tuple[str, list[str], list[str]]:
    command = json.loads(line)
    text = str(command.get("text") or "").strip()
    images = [str(path) for path in command.get("images") or []]
    audio = [str(path) for path in command.get("audio") or []]
    return text, images, audio


def run(args: argparse.Namespace, rep: common.Reporter) -> None:
    outdir = common.ensure_outdir(args.outdir)
    hears, sees = probe(args.model)
    rep.start(device="mlx", model=args.model, audio=hears, vision=sees)

    session = Session(args.model, (args.system or "").strip(), rep)
    turns: list[Turn] = []

    while line := sys.stdin.readline():
        if not line.strip():
            continue
        try:
            text, images, audio = read_command(line)
        except ValueError as exc:
            rep.warn(f"ignored an unreadable command: {exc}")
            continue

        names = [Path(path).name for path in images + audio]
        turns.append(Turn("user", text or VOICE_ONLY, names))
        if audio and not hears:
            failure = f"{args.model} has no audio encoder, so it cannot listen to a recording."
        elif images and not sees:
            failure = f"{args.model} has no vision encoder, so it cannot look at an image."
        else:
            failure = ""

        if failure:
            turns.append(Turn("error", failure, []))
            rep.chat("error", failure)
            continue
        try:
            answer = session.reply(text, images, audio)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            turns.append(Turn("error", failure, []))
            rep.chat("error", failure)
            continue
        turns.append(Turn("assistant", answer, []))
        rep.chat("assistant", answer)

    rep.progress(1.0, "writing transcript")
    rep.artifact(write_transcript(outdir, args.model, turns), kind="markdown", label="Transcript")
    rep.result({"model": args.model, "turns": len(turns)})
    rep.done()


parser = common.base_parser("chat", "Hold a conversation with a local MLX model over text, images and audio.")
parser.add_argument(
    "--model",
    default="mlx-community/gemma-4-e4b-it-4bit",
    help="Hugging Face repo holding the MLX weights to chat with",
)
parser.add_argument("--system", default="", help="system prompt placed ahead of the conversation")


def main() -> None:
    common.run("chat", run, parser)
