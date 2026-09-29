---
name: video-audio-editing
description: Edit local video and audio files with ffmpeg through the bundled video-audio CLI: trim, concatenate (optional crossfade), extract audio or a frame, replace an audio track, burn subtitles, add text or image overlays, change speed, aspect ratio, resolution, codec, bitrate, sample rate or channels, convert formats, remove silence, insert B-roll, add fades, build a video from an image plus audio, and read media duration. Use when an agent must transform or inspect video/audio files in the task workspace. Do not use for downloading media or for generative video/audio creation.
---

# Video Audio Editing

Use only the bundled launcher referenced here as `scripts/video-audio`.

When media work begins:

1. Use the exact path of this `SKILL.md` that the runtime advertised and that you read.
2. Resolve `scripts/video-audio` from the directory containing that exact file.
3. From the current task workspace, invoke the resolved launcher with Bash and pass `health-check` first. Keep the task workspace as the shell working directory for every call.

Resolve the launcher from the advertised file whenever needed; do not depend on a persistent shell variable or other shell state. If the runtime provides no exact readable locator for this `SKILL.md`, treat this skill as unsupported rather than guessing or scanning for another copy. Do not use a vendor-specific skill home, register a PATH command, change into the skill bundle, activate an environment, or invoke Python/uv directly.

Requires `ffmpeg` and `ffprobe` on `PATH`. `health-check` fails with `FFMPEG_MISSING` when either is absent.

## Workflow

Treat every command name below as arguments to the resolved launcher, not as a bare PATH command.

1. Run `health-check`. If it fails, read the JSON error before retrying.
2. Inspect inputs first with `get-media-duration --media-path FILE`.
3. Run the editing command. Every option is a long flag named after the operation argument (`--video-path`, `--output-video-path`, `--start-time`, ...). Use `<command> --help` for exact flags.
4. Read `result.outputs` (absolute paths of the files written) and verify with `get-media-duration` when correctness matters.

Booleans that default to true use `--x/--no-x` (for example `--reencode` / `--no-reencode` on `trim-video`). Structured arguments are strict JSON passed inline: `--video-paths-json`, `--audio-paths-json`, `--text-elements-json`, `--broll-clips-json`, `--font-style-json`. Keep JSON in single quotes.

## Quick recipes

- Trim: `trim-video --video-path in.mp4 --output-video-path out.mp4 --start-time 00:00:05 --end-time 00:00:12 [--no-reencode]`
- Concatenate: `concatenate-videos --video-paths-json '["a.mp4","b.mp4"]' --output-video-path joined.mp4` (add `--transition-effect fade --transition-duration 1` for exactly two videos); `concatenate-audios --audio-paths-json '["a.wav","b.wav"]' --output-audio-path joined.wav`
- Extract audio: `extract-audio-from-video --video-path in.mp4 --output-audio-path out.mp3 --audio-codec mp3`
- Extract a frame: `extract-frame-from-video --video-path in.mp4 --output-image-path frame.jpg --frame-location 12.5` (`first`, `last`, seconds or `HH:MM:SS`)
- Replace audio: `replace-audio-track --video-path in.mp4 --new-audio-path voice.wav --output-video-path out.mp4 [--match-duration-mode stretch_video]`
- Subtitles: `add-subtitles --video-path in.mp4 --srt-file-path subs.srt --output-video-path out.mp4 --font-style-json '{"font_size":"22","margin_v":"36"}'`
- Text overlay: `add-text-overlay --video-path in.mp4 --output-video-path out.mp4 --text-elements-json '[{"text":"Hello","start_time":0,"end_time":3}]'`
- Image overlay: `add-image-overlay --video-path in.mp4 --image-path logo.png --output-video-path out.mp4 --position top_right --opacity 0.6`
- Convert: `convert-video-format --input-video-path in.mov --output-video-path out.mp4 --target-format mp4`; audio: `convert-audio-format`; properties: `convert-video-properties`, `convert-audio-properties`, `set-video-resolution`, `set-video-codec`, `set-video-frame-rate`, `set-audio-bitrate`, ...
- Speed / silence / aspect / fades: `change-video-speed --speed-factor 2`, `remove-silence --media-path in.mp4 --output-media-path out.mp4`, `change-aspect-ratio --target-aspect-ratio 9:16 --resize-mode crop`, `add-basic-transitions --transition-type fade_in --duration-seconds 1`
- Image + audio to video: `create-video-from-image-and-audio --image-path cover.png --audio-path track.mp3 --output-video-path out.mp4`

## Output and recovery

Except for help, parse stdout as exactly one JSON value:

- Success: `{"schema_version":"1","ok":true,"command":"...","result":{"message":"...","outputs":["/abs/out.mp4"],"data":{...}}}`
- Failure: `{"schema_version":"1","ok":false,"command":"...","error":{"code":"...","message":"...","retryable":...}}`

Treat stderr as diagnostics. Recover by code:

- `BOOTSTRAP_FAILED`, `CONFIGURATION_ERROR`, `FFMPEG_MISSING`: fix the environment (uv, ffmpeg, `VIDEO_AUDIO_WORKSPACE`) before retrying.
- `INVALID_ARGUMENT`: correct the flag, value or JSON shape.
- `INPUT_NOT_FOUND`: check the input path (relative to the workspace, or absolute).
- `MEDIA_UNREADABLE`: the file is not valid media or lacks the required stream.
- `ARTIFACT_PATH_REJECTED`: choose an output path inside the workspace.
- `ARTIFACT_EXISTS`: choose another output name; pass `--overwrite` only when replacement is intended.
- `FFMPEG_FAILED`: read `error.message` (ffmpeg stderr); adjust codecs, times or filters.
- `INTERNAL_ERROR`: retry once, then report.

## Safety

- Outputs must stay inside the workspace. Existing outputs are preserved unless `--overwrite` is explicit; never overwrite or edit an input in place.
- Inputs may be workspace-relative or absolute but must exist.
- Do not delete source media as part of an edit.
