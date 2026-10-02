# YVD

Download YouTube videos as MP4 or MP3 from the terminal. YVD adds quality controls,
batch downloads, explicit playlist selection, subtitles, cover art, and dependency
checks around [yt-dlp](https://github.com/yt-dlp/yt-dlp).

The original commands still work:

```bash
./yvd "https://www.youtube.com/watch?v=VIDEO_ID" mp4
./yvd "https://www.youtube.com/watch?v=VIDEO_ID" mp3
```

Replace `VIDEO_ID` with the video's 11-character ID, or paste a complete video,
Shorts, live, embed, or `youtu.be` link. Quote links containing `&` in your shell.

## Setup

Requirements: Python 3.10+, yt-dlp, FFmpeg, and FFprobe. FFprobe normally comes
with FFmpeg. Current YouTube extraction may also need Deno or Node.js; YVD allows
installed Node.js in addition to yt-dlp's default Deno runtime.

### Run from the checkout

On Arch Linux:

```bash
sudo pacman -S python yt-dlp ffmpeg deno
./yvd --doctor
```

On Debian / Ubuntu, install FFmpeg and an isolated Python environment:

```bash
sudo apt install python3 python3-venv ffmpeg
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
yvd --doctor
```

For extraction troubleshooting and JavaScript runtime setup, see the
[yt-dlp installation guide](https://github.com/yt-dlp/yt-dlp#installation).

### Install as a command

From this directory, use an existing Python environment or pipx:

```bash
pipx install .
yvd --doctor
```

The package installs the `yvd` command and yt-dlp's Python dependencies. Install
FFmpeg separately through your operating system's package manager. The Python
entry point also works on Windows and macOS when these tools are on `PATH`:

```bash
python -m yvd_cli --doctor
```

The `./yvd` shell launcher works from any working directory and downloads into
the directory you run it from. For an older manual installation, copy **both**
`main.py` and `yvd_cli/` into `/usr/local/lib/yvd/`, and the executable `yvd`
launcher into `/usr/local/bin/`. Installing the package is preferred.

## Downloads

Choose a destination and a maximum video resolution:

```bash
yvd "https://youtu.be/VIDEO_ID" --quality 1080 --output ~/Videos
```

Available height caps: `360`, `480`, `720`, `1080`, `1440`, `2160`, or `best`.
YVD prefers H.264 video and M4A audio for MP4, with fallbacks when those streams
are unavailable. Other source containers are converted to MP4. A height cap never
falls back to a higher resolution; if nothing fits, the download fails clearly.
This selects available streams rather than upscaling or resizing video.

Choose MP3 bitrate and add cover art:

```bash
yvd "https://youtu.be/VIDEO_ID" mp3 --audio-quality 320 --thumbnail -o ~/Music
```

MP3 quality defaults to best variable bitrate. Fixed bitrates are `96`, `128`,
`192`, `256`, and `320` kbps. A higher bitrate cannot restore source quality.
Titles, IDs, and extensions form the filenames; embedded metadata retains the
video title and available channel information. Filenames avoid Windows-invalid
characters and limit title length.

Completed files are preserved by default. Partial downloads resume when you run
the same command again. Use `--overwrite` to explicitly replace existing files.

## Batches and playlists

Download multiple links in one command:

```bash
yvd "https://youtu.be/VIDEO_ID" "https://youtu.be/ANOTHER_ID_" -f mp3
```

Or create `links.txt`, with one URL per line. Blank lines and lines beginning
with `#` are ignored:

```text
# My download queue
https://www.youtube.com/watch?v=VIDEO_ID
https://www.youtube.com/shorts/ANOTHER_ID_
```

```bash
yvd --batch links.txt --quality 720 -o ~/Videos
cat links.txt | yvd --batch - -f mp3
```

YVD validates all links before starting and removes duplicate normalized links.
A failed download does not prevent later inputs from running. The final summary
reports succeeded, failed, and unattempted inputs, and the command exits with a
failure code if any input failed. Use `--fail-fast` to stop immediately.

Playlists require explicit opt-in:

```bash
yvd "https://www.youtube.com/playlist?list=PLAYLIST_ID" --playlist --playlist-items 1-5,8
```

Playlist files go into a folder named after the playlist, with numbered filenames
that preserve playlist order. Without `--playlist`, video links containing a
`list` parameter download only that video; pure playlist links are rejected.
Playlist summaries count input links, rather than individual videos. An input
can have saved some videos while still reporting a failure for another entry.

Avoid repeated downloads across runs with an archive:

```bash
yvd --batch links.txt -f mp3 --archive ~/.local/share/yvd/mp3-archive.txt
```

Archive records are written by yt-dlp after successful processing. Use **separate
archive files for MP4 and MP3**, since an archive tracks video IDs, not formats.
The archive also takes precedence over `--overwrite` for recorded IDs.

## Captions, authentication, and network controls

Save available human captions as SRT, optionally accepting automatic captions:

```bash
yvd "https://youtu.be/VIDEO_ID" --subtitles "en.*,ka" --auto-subs
```

Captions stay beside the media file. Availability and language tags depend on
the video. Use `--thumbnail` to embed available cover art in MP4 or MP3.

Use an exported Netscape-format cookie file when authentication is needed:

```bash
yvd "https://youtu.be/VIDEO_ID" --cookies /path/to/cookies.txt
```

Limit bandwidth and change retry counts:

```bash
yvd "https://youtu.be/VIDEO_ID" --limit-rate 2M --retries 8
```

Downloads use five network/fragment retries and a 30-second socket timeout by
default. Progress remains visible through download and conversion; `--quiet`
shows only errors. Ctrl+C returns exit code 130 and keeps resumable partial files.

## Inspect before downloading

```bash
yvd "https://youtu.be/VIDEO_ID" --info
yvd "https://youtu.be/VIDEO_ID" --list-formats
yvd "https://youtu.be/VIDEO_ID" --quality 720 --dry-run
yvd --doctor
yvd --help
```

`--info` shows title, channel, duration, and the selected source format.
`--list-formats` shows yt-dlp's available stream table. Both contact YouTube but
skip media downloads and output/archive directory creation. `--dry-run` prints
the argument vector as a shell-quoted command without running yt-dlp, contacting
YouTube, or writing files; it works even when dependencies are missing.

YVD ignores global yt-dlp configuration so external presets do not override its
format, playlist, or output behavior. Options shown by `yvd --help` control YVD.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All inputs succeeded, or the requested check/preview succeeded |
| `1` | Local filesystem/process/preview failure |
| `2` | Invalid input or arguments |
| `3` | Required dependency missing, or doctor check failed |
| `130` | Cancelled with Ctrl+C |
| Other nonzero codes | First failed yt-dlp invocation's exit code |

## Development and verification

```bash
python3 -m unittest discover -s tests -v
```

Unit tests cover URL validation, playlist opt-in, argument conflicts, batch
validation/deduplication, dependency failures, preview behavior, cancellation,
and failure propagation. Integration tests generate tiny local media fixtures
and use real yt-dlp, FFmpeg, and FFprobe through a loopback HTTP server to verify
merging, fallback conversion, MP3 bitrate, subtitles, cover art, metadata,
archives, previews, and numbered playlist selection. They do not contact YouTube
and skip when the required media tools are absent.

To run just the unit tests:

```bash
python3 -m unittest discover -s tests -p test_cli.py -v
```

## Uninstall

For pipx installations:

```bash
pipx uninstall yvd
```

For a virtual environment, run `python -m pip uninstall yvd`. For the old manual
installation, remove `/usr/local/bin/yvd` and `/usr/local/lib/yvd`.

## License

MIT, as specified by the original project.
