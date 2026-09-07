# episode-vtt

Standalone Qwen3-ASR script. Point it at an episode, get a sibling `.vtt`.

```bash
cd /path/to/show
uv run --project /path/to/tiny-ai-suite/scripts episode-vtt S01E01.mkv --glossary-file glossary.json
```

Writes `audio.wav` in the directory you ran it from. Writes `S01E01.vtt` next to the input file. Needs Apple Silicon, ffmpeg, and a first-run download of the 1.7B weights.

## Glossary

JSON object, same shape as the suite lexicon:

```json
{
  "vocabulary": ["Jon Snow", "Winterfell"],
  "corrections": [{"from": "John Snow", "to": "Jon Snow"}]
}
```

`vocabulary` and each correction `to` are fed to the recogniser as context. After decoding, each `from` is replaced with `to` in the cue text, case-insensitive. Timestamps are left alone.

Copy `glossary.example.json` and fill it from the show's Wikipedia character list, IMDb/TMDB credits, or a fan wiki. Add names the recogniser keeps missing as you go.
