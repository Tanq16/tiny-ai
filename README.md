<div align="center">
  <img src="internal/server/static/icons/logo.png" alt="Tiny AI Suite Logo" width="140">
  <h1>Tiny AI Suite</h1>

  <a href="https://github.com/Tanq16/tiny-ai/actions/workflows/release.yaml"><img alt="Build Workflow" src="https://github.com/Tanq16/tiny-ai/actions/workflows/release.yaml/badge.svg"></a>&nbsp;<a href="https://github.com/Tanq16/tiny-ai/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/Tanq16/tiny-ai"></a><br><br>
  <a href="#capabilities">Capabilities</a> &bull; <a href="#install">Install</a> &bull; <a href="#usage">Usage</a> &bull; <a href="#notes">Notes</a>
</div>

---

Tiny AI Suite runs eleven local AI models on Apple Silicon: stem separation, denoising, transcription, dictation, speech synthesis, voice cloning, chat, document conversion, OCR, image generation and image upscaling. Each one is a self-contained uv project under `ai-scripts/`, and one Go binary serves a web app that runs them and streams their progress back.

It exists because a Mac with unified memory outruns a free Colab T4 and never disconnects mid-job. Nothing leaves the machine, and there is no account, no queue and no API key.

## Capabilities

| Task | Engine | Runs on | Output |
|---|---|---|---|
| Stem Separator | BS Roformer SW | Metal (torch MPS) | 4 or 6 stems, or drums or vocals against everything else, plus a zip |
| Audio Enhancer | DeepFilterNet3 | Metal or CPU | denoised wav, original kept for A/B |
| Transcriber | MLX Whisper | Metal (MLX) | timestamped text, SRT, JSON segments |
| Dictation | Qwen3-ASR + Gemma 4 12B | Metal (MLX) | clean written text from a browser recording, spelled your way |
| Speech Synthesis | Kokoro 82M | Metal (MLX) | wav or mp3 from 9 preset voices |
| Voice Cloning | F5-TTS | Metal (MLX) | wav in a voice taken from a 5 to 15 second clip, recorded in the browser or uploaded |
| Small Model Chat | Gemma 4, E2B to 31B | Metal (MLX) | a conversation over text, pictures and voice, kept as one job you can reopen |
| Document to Markdown | Marker | Metal (torch MPS) | Markdown, HTML or JSON, with tables, LaTeX and extracted images |
| Image OCR | Surya | Metal (torch MPS) | reading-order text, tables as Markdown and CSV, annotated preview |
| Image Generation | FLUX.2 Klein, 4B to 9B | Metal (MLX) | png from a written prompt, from reference pictures, or both, on a seed you can hold and reuse |
| Image Upscaler | Real-ESRGAN via spandrel | Metal (torch MPS) | upscaled png with the original alongside |

Every task is reachable three ways: the web UI, the HTTP API, and the script on its own from a terminal.

## Screenshots

<details>
<summary>Click to expand</summary>

### Launcher

| Desktop | Mobile |
| :---: | :---: |
| <img src=".github/assets/launcher-desktop.png" alt="Launcher desktop" width="100%" /> | <img src=".github/assets/launcher-mobile.png" alt="Launcher mobile" width="100%" /> |

### Job

| Desktop | Mobile |
| :---: | :---: |
| <img src=".github/assets/job-desktop.png" alt="Job desktop" width="100%" /> | <img src=".github/assets/job-mobile.png" alt="Job mobile" width="100%" /> |

</details>

## Install

Apple Silicon only. Needs Go 1.27+, [uv](https://docs.astral.sh/uv/), and ffmpeg.

```bash
git clone https://github.com/Tanq16/tiny-ai && cd tiny-ai
make build
./tiny-ai-suite serve
```

`make build` downloads the pinned frontend assets and embeds them in the binary. Open `http://127.0.0.1:7777`.

Each task installs its own dependencies on first use, which takes a minute or two and downloads model weights on top. To get that over with up front:

```bash
make py-sync   # every task environment, roughly 9 GB on disk
make voices    # the three built-in voice cloning reference clips
```

`make voices` is required before the Voice Cloning presets work; without it that task falls back to needing your own reference clip.

## Usage

Every task takes `--outdir`, `--json`, `--quiet` and `--device` on top of its own flags, and prints artifact paths on stdout. `--json` switches it to the NDJSON event stream the server consumes.

```bash
uv run --project ai-scripts/transcribe transcribe --input talk.opus --outdir out
uv run --project ai-scripts/dictate dictate --input note.m4a --lexicon data/lexicon.json --outdir out
uv run --project ai-scripts/stems stems --input song.mp3 --preset drums-best --format mp3 --outdir out
uv run --project ai-scripts/tts tts --text "Ready when you are." --voice bf_emma --outdir out
uv run --project ai-scripts/imagegen imagegen --prompt "a red fox in fresh snow" --seed 42 --variants 3 --outdir out
uv run --project ai-scripts/imagegen imagegen --prompt "a finished oil painting of this scene" --reference sketch.png --size match --outdir out
echo '{"text":"hello"}' | uv run --project ai-scripts/chat chat --model mlx-community/gemma-4-e4b-it-4bit --outdir out
cd ai-scripts/doc2md && uv run doc2md --input paper.pdf --pages 1-10 --outdir out
```

### Layout

```
ai-scripts/
├── common/       tinyai-common: the event protocol every task speaks
├── stems/        pyproject.toml, uv.lock, src/stems/
├── denoise/      ...
└── upscale/
```

Each task is its own uv project with its own lockfile and virtualenv, sharing only `common` as an editable path dependency. That isolation is not cosmetic: DeepFilterNet holds Audio Enhancer on torch 2.8 and numpy 1.26 while every other torch task resolves to 2.13 and 2.5, so a single environment for all eleven does not exist. Adding a task is `uv init --package --no-workspace ai-scripts/<name>`, then `uv add --editable ../common`.

### Server flags

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `7777` | Port |
| `--data` | `./data` | Where uploads, outputs and job history live |
| `--scripts` | `./ai-scripts` | Directory holding the task projects |
| `--jobs` | `1` | Concurrent jobs, at least 1 |
| `--debug` | off | Debug-level logging |

### API

```bash
curl -X POST localhost:7777/api/jobs -F task=tts -F text="Hello" -F voice=af_heart
curl -N localhost:7777/api/jobs/<id>/events    # SSE progress
curl -O localhost:7777/api/jobs/<id>/artifacts/speech.wav
```

`GET /api/tasks` returns the catalog the UI renders its forms from, so a client can discover every task and parameter without hardcoding them. `GET` and `PUT /api/lexicon` read and replace the dictation vocabulary, which the browser attaches to each dictation job.

A chat job stays open and takes turns instead of running once:

```bash
ID=$(curl -sX POST localhost:7777/api/jobs -F task=chat -F model=mlx-community/gemma-4-e4b-it-4bit | jq -r .id)
curl -X POST localhost:7777/api/jobs/$ID/messages -F text="What is in this picture?" -F file=@photo.png
curl -N localhost:7777/api/jobs/$ID/events        # assistant tokens arrive as "delta" events
curl -X POST localhost:7777/api/jobs/$ID/finish   # closes the chat and writes the transcript
```

`GET /api/jobs/<id>/inputs/<name>` serves a file that was attached to a turn, which is how the browser shows the pictures and recordings back in the transcript.

## Notes

- **One job at a time by default.** The batch tasks contend for the same unified memory, so `--jobs 1` avoids an out-of-memory failure halfway through a long run. Raise it if you know the two tasks fit.
- **A chat runs in its own lane.** It holds its weights in memory for as long as it is open, so it sits beside the job queue rather than inside it, and only one chat is open at a time. Finish chat ends it, writes the transcript and frees the lane.
- **A chat hears a recording only on the turn it arrives.** Pictures stay in context for the whole conversation, but MLX binds audio to the last message, so later turns carry the model's reply rather than the sound.
- **The two largest chat models are mute.** Gemma 4 26B A4B and 31B carry no audio encoder, so they read pictures but cannot listen. The composer says so before the weights download, and a voice message to one comes back as an error rather than a guess.
- **Deleting a chat deletes its history.** The transcript and every attachment live under `data/jobs/<id>/`, so the job is the conversation.
- **Recording needs an HTTPS address.** Browsers only open the microphone in a secure context, so the recorders in Dictation, Voice Cloning and Small Model Chat are dead on a plain `http://` LAN address. Put a TLS-terminating proxy in front, or use those tasks from the machine the server runs on.
- **Dictation is two passes.** Qwen3-ASR writes the transcript with the vocabulary biasing its decoder, then Gemma rewrites it into clean prose using the vocabulary and the correction list. The job page shows one pane with diff, raw and polished tabs, and copies whichever tab is open.
- **Loopback by default.** The server executes local scripts and has no authentication, so binding it to `0.0.0.0` hands anyone on the network a shell-adjacent surface.
- **A reference picture sets the layout, the prompt sets the subject.** Up to four go in at once. A rough sketch is followed closely enough that crude shapes need naming, or a triangle meant as a pine comes back as a tent.
- **Image models are ungated.** Every option downloads without a HuggingFace account, which rules out FLUX.1-dev, Kontext, Redux and Krea 2 despite their quality. The 9B entries carry the FLUX Non-Commercial Licence even though the weights come from an open mirror.
- **Image weights are large.** The 4-bit Klein 4B is a 4.6 GB download, the recommended 8-bit 15 GB, the base 4B 8.6 GB and either 9B 18 GB.
- **Klein base models are the slow tier.** They run 50 steps against the distilled 4, and take a real guidance scale that the distilled ones reject.
- **LoRAs live in `data/loras/`.** The form uploads into it and the runner exports it as `LORA_LIBRARY_PATH`, so a bare name resolves. A HuggingFace repo id or a `.safetensors` path still works, several separated by commas, each optionally suffixed with `:0.5` to set its strength.
- **Voice cloning cuts a long reference.** F5-TTS conditions on the reference clip and the new speech as one sequence, so anything past 15 seconds is dropped and the transcript is taken from what remains. A longer clip left whole comes back as babble.
- **First run of a task is slow.** It resolves an environment and downloads weights. Later runs start in about a second.
- **Job history survives a restart.** State lives under `data/jobs/<id>/`; a job that was running when the server died is marked failed on reload, because its process is gone.
- **No Docker.** Metal is unreachable from a Linux container on macOS, which would drop every task to CPU.
- **Adding a task** is one entry in `internal/catalog/tasks.go` and one uv project whose entry point is named after it. The form, the API and the argv are generated from the catalog entry, and the event protocol is documented at the top of `ai-scripts/common/src/tinyai_common/__init__.py`.
