# Bulk Media Transcription

A repeatable process for generating WebVTT subtitles across large video libraries.

## Architecture

The operation runs in three decoupled stages:

1. **Discovery and Mapping**: Identifies video files missing subtitles and assigns stable identifiers.
2. **Parallel Audio Extraction**: Decodes audio streams concurrently via FFmpeg to temporary mono WAV files.
3. **Serial Transcription and Placement**: Transcribes one audio file at a time to WebVTT subtitles. Moves each subtitle file to its target directory and purges the temporary WAV file.

Audio extraction is parallelized because FFmpeg decoding is lightweight and CPU-bound.
Transcription runs serially to prevent GPU memory saturation, context-switching overhead, and thermal throttling.

## Stage 1: Discovery and Mapping

Scan the target directory recursively for video containers missing sibling subtitle files.
Generate a unique identifier for each candidate to avoid filename collisions in flat working directories.

### Mapping Record Schema

Store discovered tasks in a flat JSON array:

```json
[
  {
    "id": "item_001_a1b2c3",
    "video_path": "/path/to/library/Season 01/Episode 01/video.mkv",
    "audio_path": "item_001_a1b2c3.wav",
    "vtt_path": "item_001_a1b2c3.vtt",
    "dest_vtt": "/path/to/library/Season 01/Episode 01/subtitles.vtt"
  }
]
```

Persisting this mapping to disk provides crash recovery.
A resumed run reloads the mapping and skips any entry whose `dest_vtt` already exists.

## Stage 2: Parallel Audio Extraction

Extract mono 16 kHz WAV audio files using a thread pool or process pool.
Eight workers provide high throughput without saturating disk bandwidth.

### Extraction Command

```bash
ffmpeg -y -loglevel error -i "$VIDEO_PATH" -vn -ac 1 -ar 16000 "$TMP_AUDIO.partial.wav"
mv "$TMP_AUDIO.partial.wav" "$TMP_AUDIO.wav"
```

Writing to a temporary `.partial.wav` file guarantees that incomplete extractions are never processed.

## Stage 3: Serial Transcription and Placement

Iterate through the mapping one entry at a time.
Invoke the ASR pipeline sequentially on each extracted audio file.

### Execution Loop

For each item in the mapping:

1. Skip the item if `dest_vtt` already exists.
2. Verify `audio_path` is present on disk.
3. Run the transcription command against `audio_path` with the glossary file:

```bash
uv run episode-vtt "$AUDIO_PATH" --glossary-file glossary.json
```

4. Verify the resulting WebVTT file is non-empty.
5. Move `$VTT_PATH` to `$DEST_VTT`.
6. Delete `$AUDIO_PATH` immediately to reclaim disk space.

Immediate deletion keeps peak disk usage bounded to the size of the initial audio extractions.

## Error Handling and Resumability

Missing target files define the remaining queue.
If transcription fails on an individual file, log the error and continue to the next item.
Re-running the command inspects `dest_vtt` presence to resume remaining items without re-transcribing completed episodes.
Delete the mapping file only after all entries have their destination subtitle files in place.
