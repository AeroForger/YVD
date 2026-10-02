# YVD 2.0.0 verification

Verified locally on Linux on 2026-10-02, using Python 3.14.7, yt-dlp
2026.08.19, FFmpeg 9.0.2, and FFprobe 9.0.2.

## Automated checks

- `python3 -m unittest discover -s tests -v`: 43 tests passed, including 8
  integration tests using real yt-dlp/FFmpeg and locally generated media.
- `python3 -m compileall -q main.py yvd_cli tests`: passed.
- `sh -n yvd`: passed.
- `./yvd --doctor`: all required dependencies passed their version checks;
  Deno and Node.js were available.
- Source launcher invoked from `/tmp`: `yvd --version` returned `YVD 2.0.0`.
- Built and installed `yvd-2.0.0-py3-none-any.whl` in a temporary Python
  environment. From outside the checkout, the installed `yvd --version`,
  `yvd --doctor`, MP3 dry run, and `python -m yvd_cli --version` passed.

Integration coverage includes separate-stream MP4 merging, WebM-to-MP4
conversion, embedded metadata, 192 kbps MP3 encoding, SRT captions, attached
cover art, playlist numbering/selection, archive skipping without media
requests, preserving existing file contents/timestamps, explicit overwrite,
quiet output, and previews without media requests or output directories.

## Live YouTube checks

The public video `jNQXAC9IVRw` ("Me at the zoo") was tested with these commands,
using temporary output directories:

```bash
./yvd 'https://www.youtube.com/watch?v=jNQXAC9IVRw' --info --retries 0
./yvd 'https://www.youtube.com/watch?v=jNQXAC9IVRw' mp4 --quality 360 --retries 0 -o TEMP/mp4
./yvd 'https://www.youtube.com/watch?v=jNQXAC9IVRw' mp3 --audio-quality 192 --retries 0 -o TEMP/mp3
```

All returned exit code 0. FFprobe confirmed:

| Output | Size | Duration | Media codecs |
| --- | --- | --- | --- |
| MP4 | 745,938 bytes | 19.063583 seconds | H.264 video, AAC audio |
| MP3 | 458,486 bytes | 19.005542 seconds | MP3 audio |

The original yt-dlp test video `BaW_jenozKc` returned "This video is unavailable";
YVD reported failure and returned exit code 1. Live test downloads were removed
with their temporary directories after inspection.

## Scope of verification

Windows/macOS and Python 3.10 are configured in the CI matrix but were not run
locally. Live captions, authenticated videos, and public playlists were not
tested against YouTube; local fixtures verify their downloader options and
processing where applicable. Cancellation/resume control is covered by unit
tests and yt-dlp's continuation options; interrupting a live transfer and then
resuming it was not tested.

This checkout has no `.git` directory. Files were edited directly; no commit,
remote push, or CI run was performed.
