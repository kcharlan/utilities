# Transcription Console
Whisper-powered transcription toolkit with both a polished Streamlit UI and lightweight CLI entry points. Tracks session and lifetime durations, supports wildcard ingestion, and preserves legacy counter files.

## Components

- `app.py` – Streamlit console with sticky transcripts, upload/wildcard ingestion, clipboard buttons, and counter management.
- `transcribe.py` – Alternate Streamlit experience tuned for quick batching (configured via helper scripts).
- `run.sh`, `m4a-run.sh`, `help.sh` – Convenience wrappers for the legacy CLI interface.
- `ui.sh` – Launches `app.py` from the project root.
- `session_backup.json`, `transcription_odometer.txt` – Persist cumulative and lifetime durations; both are updated atomically.
- `setup.sh` – Builds the virtual environment and installs Whisper + Streamlit.

## Environment

```bash
./setup.sh
source venv/bin/activate
```

`openai-whisper` bundles FFmpeg binaries on macOS. If you plan to use the OpenAI API fallback, export `OPENAI_API_KEY`.

## Launching the Streamlit UI

```bash
streamlit run app.py
# or
./ui.sh
```

Highlights:

- Drag-and-drop uploader or wildcard input box for local media files (`wav`, `mp3`, `m4a`, `ogg`, `flac`, `aac`).
- Divider words split transcripts into sections for easier editing (`cut`, `mark`, etc.).
- Session and lifetime counters update in real time and persist to the legacy storage files.
- Per-file metrics: duration, model used, transcript preview, and “Copy to clipboard” buttons.
- Resilient error handling around Whisper loading—falls back to OpenAI API if configured.

## CLI Helpers

The helper scripts wrap `transcribe.py` which accepts `--file` globs and `--model` size.

```bash
./run.sh           # transcribe *.wav with the large Whisper model
./m4a-run.sh       # transcribe *.m4a
./help.sh          # show CLI usage
```

`transcribe.py` stores totals in the same `session_backup.json` and `transcription_odometer.txt` files to keep history consistent across UI and CLI modes.

## Customization

- Adjust default model size or divider words near the top of `app.py`.
- Modify `process_text_with_dividers` to add Markdown headings or timestamps between sections.

## Troubleshooting

- Ensure FFmpeg is available if Whisper complains; the `openai-whisper` wheel downloads a binary, but homebrew’s `ffmpeg` also works.
- Large models (e.g., `large`) require several GB of VRAM; switch to `small` or `medium` on constrained GPUs/CPUs.
- Delete `session_backup.json`/`transcription_odometer.txt` if you want to reset counters—back them up first if the history matters.
