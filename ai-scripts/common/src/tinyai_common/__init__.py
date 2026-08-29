"""Shared CLI plumbing for the tiny-ai-suite scripts.

Every script emits the same NDJSON event stream on stdout under ``--json`` so the Go
backend can relay progress without knowing anything about the task it is running.

Wire format, one JSON object per line:

    {"event":"start","task":"stems","data":{"device":"mps"}}
    {"event":"log","level":"info","message":"..."}
    {"event":"progress","fraction":0.42,"message":"...","current":42,"total":100}
    {"event":"artifact","path":"/abs/path.wav","kind":"audio","label":"Vocals","bytes":1234}
    {"event":"result","data":{"text":"..."}}
    {"event":"error","message":"...","traceback":"..."}
    {"event":"done","status":"ok","duration_s":12.3}

``fraction`` is null when the work is indeterminate. Exactly one ``done`` or ``error``
ends the stream.

An interactive task reads one JSON command per line on stdin and keeps running until
stdin closes, adding two events:

    {"event":"delta","message":"partial "}
    {"event":"chat","role":"assistant","message":"the complete turn"}

``delta`` carries a fragment as it is generated and the backend relays it without
recording it, so only the ``chat`` event that closes a turn reaches job history.
``role`` is ``assistant`` for a reply and ``error`` for a turn that failed.

A boolean flag the catalog declares as defaulting on is negatable, so the backend can switch it
off with ``--no-<name>``. Declare those with ``argparse.BooleanOptionalAction``; a flag that
defaults off stays a plain ``store_true``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ARTIFACT_KINDS = ("audio", "image", "text", "markdown", "json", "archive", "other")

LIBSNDFILE_SUFFIXES = frozenset({".wav", ".flac", ".ogg", ".opus", ".mp3", ".aif", ".aiff", ".caf", ".au"})

_MIME_BY_SUFFIX = {
    ".wav": "audio",
    ".mp3": "audio",
    ".flac": "audio",
    ".m4a": "audio",
    ".opus": "audio",
    ".ogg": "audio",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".md": "markdown",
    ".json": "json",
    ".txt": "text",
    ".srt": "text",
    ".vtt": "text",
    ".csv": "text",
    ".html": "text",
    ".zip": "archive",
}


class Reporter:
    """Emits task events as NDJSON for the backend, or as human lines for a terminal."""

    def __init__(self, task: str, *, json_mode: bool, quiet: bool = False) -> None:
        self.task = task
        self.json_mode = json_mode
        self.quiet = quiet
        self.started = time.monotonic()
        self.artifacts: list[dict[str, Any]] = []
        self._last_pretty_len = 0

    @classmethod
    def from_args(cls, task: str, args: argparse.Namespace) -> Reporter:
        return cls(
            task, json_mode=bool(getattr(args, "json", False)), quiet=bool(getattr(args, "quiet", False))
        )

    def start(self, **data: Any) -> None:
        self._emit({"event": "start", "task": self.task, "data": data})

    def log(self, message: str, level: str = "info") -> None:
        self._emit({"event": "log", "level": level, "message": message})

    def warn(self, message: str) -> None:
        self.log(message, level="warn")

    def progress(
        self,
        fraction: float | None,
        message: str = "",
        *,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        if fraction is not None:
            fraction = min(max(fraction, 0.0), 1.0)
        self._emit(
            {
                "event": "progress",
                "fraction": fraction,
                "message": message,
                "current": current,
                "total": total,
            }
        )

    def artifact(self, path: str | Path, *, kind: str | None = None, label: str | None = None) -> Path:
        p = Path(path).resolve()
        kind = kind or _MIME_BY_SUFFIX.get(p.suffix.lower(), "other")
        entry = {
            "event": "artifact",
            "path": str(p),
            "kind": kind,
            "label": label or p.name,
            "bytes": p.stat().st_size if p.exists() else 0,
        }
        self.artifacts.append(entry)
        self._emit(entry)
        return p

    def delta(self, text: str) -> None:
        self._emit({"event": "delta", "message": text})

    def chat(self, role: str, text: str) -> None:
        self._emit({"event": "chat", "role": role, "message": text})

    def result(self, data: dict[str, Any]) -> None:
        self._emit({"event": "result", "data": data})

    def done(self) -> None:
        self._emit({"event": "done", "status": "ok", "duration_s": round(time.monotonic() - self.started, 3)})

    def error(self, message: str, tb: str = "") -> None:
        self._emit({"event": "error", "message": message, "traceback": tb})

    def _emit(self, payload: dict[str, Any]) -> None:
        if self.json_mode:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            return
        self._pretty(payload)

    def _pretty(self, payload: dict[str, Any]) -> None:
        kind = payload["event"]
        if kind == "artifact":
            self._clear_line()
            print(payload["path"])
            return
        if kind == "result":
            self._clear_line()
            text = payload["data"].get("text")
            if isinstance(text, str):
                print(text)
            return
        if kind == "delta":
            print(payload["message"], end="", flush=True)
            return
        if kind == "chat":
            self._clear_line()
            print()
            return
        if self.quiet:
            return
        if kind == "progress":
            self._progress_line(payload)
            return
        self._clear_line()
        if kind == "start":
            detail = " ".join(f"{k}={v}" for k, v in payload["data"].items() if v is not None)
            print(f"[{self.task}] {detail}".rstrip(), file=sys.stderr)
        elif kind == "log":
            print(f"[{payload['level']}] {payload['message']}", file=sys.stderr)
        elif kind == "done":
            print(f"[done] {payload['duration_s']}s", file=sys.stderr)
        elif kind == "error":
            print(f"[error] {payload['message']}", file=sys.stderr)
            if payload.get("traceback"):
                print(payload["traceback"], file=sys.stderr)

    def _progress_line(self, payload: dict[str, Any]) -> None:
        fraction = payload.get("fraction")
        message = payload.get("message") or ""
        if fraction is None:
            line = f"[..] {message}"
        else:
            filled = int(fraction * 24)
            line = f"[{'#' * filled}{'.' * (24 - filled)}] {fraction * 100:5.1f}% {message}"
        if sys.stderr.isatty():
            sys.stderr.write("\r" + line.ljust(self._last_pretty_len))
            sys.stderr.flush()
            self._last_pretty_len = len(line)
        else:
            print(line, file=sys.stderr)

    def _clear_line(self) -> None:
        if self._last_pretty_len and sys.stderr.isatty():
            sys.stderr.write("\r" + " " * self._last_pretty_len + "\r")
            sys.stderr.flush()
            self._last_pretty_len = 0


def base_parser(task: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=task, description=description)
    parser.add_argument("--outdir", default=".", help="directory that receives generated artifacts")
    parser.add_argument("--json", action="store_true", help="emit NDJSON events on stdout")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output in human mode")
    parser.add_argument("--device", default=None, help="torch device override (mps, cpu)")
    return parser


def run(
    task: str, main: Callable[[argparse.Namespace, Reporter], None], parser: argparse.ArgumentParser
) -> None:
    """Parses arguments, runs ``main``, and turns any exception into one error event."""
    args = parser.parse_args()
    reporter = Reporter.from_args(task, args)
    try:
        main(args, reporter)
    except KeyboardInterrupt:
        reporter.error("interrupted")
        sys.exit(130)
    except SystemExit as exc:
        if exc.code:
            reporter.error(f"exited with status {exc.code}")
        raise
    except Exception as exc:  # noqa: BLE001 - the boundary that turns a crash into one event
        reporter.error(f"{type(exc).__name__}: {exc}", traceback.format_exc())
        sys.exit(1)


def resolve_device(override: str | None = None) -> str:
    """Picks the torch device, preferring Metal. Import stays local so MLX-only scripts skip torch."""
    choice = override or os.environ.get("TINYAI_DEVICE")
    if choice:
        return choice
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def ensure_outdir(path: str | Path) -> Path:
    out = Path(path).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def cache_dir(*parts: str) -> Path:
    root = Path(os.environ.get("TINYAI_CACHE", Path.home() / ".cache" / "tiny-ai-suite"))
    target = root.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    return target


def stem_of(path: str | Path) -> str:
    return Path(path).stem


def require_file(path: str | None, label: str) -> Path:
    if not path:
        raise ValueError(f"{label} is required")
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"{label} not found: {p}")
    return p.resolve()


def zip_bundle(paths: Iterable[str | Path], target: str | Path) -> Path:
    import zipfile

    target = Path(target)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in paths:
            item = Path(item)
            archive.write(item, arcname=item.name)
    return target.resolve()


def encode_mp3(source: str | Path, target: str | Path, bitrate: str = "320k") -> Path:
    """Transcodes with ffmpeg, which every script relies on for anything but wav output."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for mp3 output but was not found on PATH")
    cmd: Sequence[str] = [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-b:a", bitrate, str(target)]
    subprocess.run(cmd, check=True)
    return Path(target).resolve()


@contextmanager
def readable_audio(source: str | Path) -> Iterator[Path]:
    path = Path(source)
    if path.suffix.lower() in LIBSNDFILE_SUFFIXES:
        yield path.resolve()
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(f"ffmpeg is required to read {path.suffix} audio but was not found on PATH")
    with tempfile.TemporaryDirectory() as staging:
        decoded = Path(staging) / f"{path.stem}.wav"
        cmd: Sequence[str] = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-c:a",
            "pcm_f32le",
            str(decoded),
        ]
        subprocess.run(cmd, check=True)
        yield decoded


def download(url: str, target: str | Path, reporter: Reporter | None = None, label: str = "") -> Path:
    import urllib.request

    target = Path(target)
    if target.exists():
        return target.resolve()
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url) as response, tmp.open("wb") as handle:  # noqa: S310 - fixed https sources
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while chunk := response.read(1 << 20):
            handle.write(chunk)
            read += len(chunk)
            if reporter and total:
                reporter.progress(
                    read / total, f"downloading {label or target.name}", current=read, total=total
                )
    tmp.rename(target)
    return target.resolve()
