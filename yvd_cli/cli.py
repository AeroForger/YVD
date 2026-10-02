"""Command-line interface; yt-dlp handles extraction, progress, and conversion."""

import argparse
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .urls import normalize_url

FORMATS = ("mp4", "mp3")
QUALITY = ("best", "2160", "1440", "1080", "720", "480", "360")
TEMPLATE = "%(title).180B [%(id)s].%(ext)s"
PLAYLIST_TEMPLATE = "%(playlist_title,playlist_id|Playlist).100B/%(playlist_index)03d - " + TEMPLATE


def nonnegative(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return number


def rate(value):
    if not re.fullmatch(r"[1-9]\d*(?:\.\d+)?[KMGkmg]?", value):
        raise argparse.ArgumentTypeError("use a positive rate such as 500K or 2M")
    return value


def playlist_items(value):
    if not re.fullmatch(r"[1-9]\d*(?:-[1-9]\d*)?(?:,[1-9]\d*(?:-[1-9]\d*)?)*", value):
        raise argparse.ArgumentTypeError("use item numbers or ranges, such as 1-5,8,12")
    for item in value.split(","):
        if "-" in item:
            first, last = map(int, item.split("-"))
            if first > last:
                raise argparse.ArgumentTypeError("playlist ranges must be ascending")
    return value


def parser():
    result = argparse.ArgumentParser(
        prog="yvd",
        description="Download YouTube videos as MP4 or MP3, with safe playlist and batch controls.",
        epilog="Examples:\n  yvd URL mp3\n  yvd URL --quality 1080 -o ~/Videos\n"
        "  yvd --batch links.txt -f mp3\n  yvd PLAYLIST_URL --playlist --playlist-items 1-5\n"
        "  yvd URL --info\n  yvd --doctor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument("inputs", nargs="*", metavar="URL", help="one or more YouTube links; legacy trailing mp4/mp3 is supported")
    result.add_argument("--version", action="version", version=f"YVD {__version__}")
    result.add_argument("-f", "--format", type=str.lower, choices=FORMATS, help="output format (default: mp4)")
    result.add_argument("-o", "--output", type=Path, default=Path.cwd(), metavar="DIR", help="destination directory (default: current directory)")
    result.add_argument("-q", "--quality", choices=QUALITY, default="best", help="maximum video height (default: best)")
    result.add_argument("--audio-quality", choices=("best", "320", "256", "192", "128", "96"), default=None, metavar="KBPS", help="MP3 bitrate: 96, 128, 192, 256, 320, or best (default)")
    result.add_argument("-b", "--batch", type=Path, metavar="FILE", help="read one URL per line; use - for stdin; blank lines and # comments are ignored")
    result.add_argument("--playlist", action="store_true", help="explicitly allow playlists; organize videos in a playlist folder")
    result.add_argument("--playlist-items", type=playlist_items, metavar="RANGE", help="selected playlist entries, e.g. 1-5,8 (requires --playlist)")
    result.add_argument("--subtitles", metavar="LANGS", help="save available subtitles as SRT; language codes/regex, e.g. en,ka or en.*")
    result.add_argument("--auto-subs", action="store_true", help="also allow automatic captions (requires --subtitles)")
    result.add_argument("--thumbnail", action="store_true", help="embed cover art in the downloaded file")
    result.add_argument("--archive", type=Path, metavar="FILE", help="skip IDs already downloaded; use separate archive files per output format")
    result.add_argument("--cookies", type=Path, metavar="FILE", help="use a Netscape-format cookie file")
    result.add_argument("--limit-rate", type=rate, metavar="RATE", help="bandwidth cap, e.g. 500K or 2M")
    result.add_argument("--retries", type=nonnegative, default=5, help="network/fragment retries (default: 5)")
    result.add_argument("--overwrite", action="store_true", help="replace existing files (default: preserve them and resume partial downloads)")
    result.add_argument("--fail-fast", action="store_true", help="stop the batch/playlist on the first failure")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--info", action="store_true", help="preview title, channel, duration, and selected format without downloading")
    modes.add_argument("--list-formats", action="store_true", help="show available video/audio formats without downloading")
    modes.add_argument("--dry-run", action="store_true", help="print commands without network requests or file writes")
    modes.add_argument("--doctor", action="store_true", help="check Python, yt-dlp, FFmpeg, FFprobe, and optional JavaScript runtimes")
    result.add_argument("--quiet", action="store_true", help="show only errors during downloads")
    return result


def resolve_downloader():
    executable = shutil.which("yt-dlp")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return None


def collect_urls(args):
    inputs = list(args.inputs)
    legacy_format = None
    if inputs and inputs[-1].lower() in FORMATS:
        legacy_format = inputs.pop().lower()
    if legacy_format and args.format and legacy_format != args.format:
        raise ValueError("trailing format conflicts with --format")
    args.format = args.format or legacy_format or "mp4"
    if args.playlist_items and not args.playlist:
        raise ValueError("--playlist-items requires --playlist")
    if args.auto_subs and not args.subtitles:
        raise ValueError("--auto-subs requires --subtitles LANGS")
    if args.audio_quality and args.format != "mp3":
        raise ValueError("--audio-quality requires MP3 output")
    if args.quality != "best" and args.format == "mp3":
        raise ValueError("--quality controls video height; use --audio-quality for MP3")
    if args.subtitles and not args.subtitles.strip():
        raise ValueError("--subtitles needs at least one language code")
    if args.batch:
        if str(args.batch) == "-":
            lines = sys.stdin.read().splitlines()
        else:
            lines = args.batch.expanduser().read_text(encoding="utf-8-sig").splitlines()
        inputs.extend(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))
    if not inputs:
        raise ValueError("provide a YouTube URL or --batch FILE (see yvd --help)")
    urls = []
    for index, value in enumerate(inputs, 1):
        try:
            url = normalize_url(value, playlist=args.playlist)
        except ValueError as error:
            raise ValueError(f"input {index}: {error}") from error
        if url not in urls:
            urls.append(url)
    return urls


def build_command(args, url, downloader):
    """Build an argument vector; never interpret user input through a shell."""
    command = [*downloader, "--ignore-config", "--yes-playlist" if args.playlist else "--no-playlist",
               "--abort-on-error" if args.fail_fast else "--no-abort-on-error",
               "--retries", str(args.retries), "--fragment-retries", str(args.retries),
               "--socket-timeout", "30"]
    # yt-dlp enables Deno by default; allow installed Node too, without fetching components.
    if shutil.which("node"):
        command += ["--js-runtimes", "node"]
    if args.cookies:
        command += ["--cookies", str(args.cookies.expanduser().resolve())]
    if args.playlist_items:
        command += ["--playlist-items", args.playlist_items]
    if args.format == "mp3":
        command += ["-f", "bestaudio/best", "--extract-audio", "--audio-format", "mp3",
                    "--audio-quality", "0" if args.audio_quality in {None, "best"} else args.audio_quality + "K"]
    else:
        height = "" if args.quality == "best" else f"[height<={args.quality}]"
        selection = (f"bv{height}[vcodec^=avc1]+ba[ext=m4a]/b{height}[ext=mp4]/"
                     f"bv{height}+ba/b{height}")
        command += ["-f", selection, "--merge-output-format", "mp4", "--recode-video", "mp4"]
    if args.info:
        command += ["--simulate", "--dump-single-json", "--no-warnings"]
    elif args.list_formats:
        command += ["--simulate", "--list-formats"]
    else:
        playlist_link = args.playlist and ("?list=" in url or "&list=" in url)
        command += ["--paths", str(args.output.expanduser().resolve()),
                    "--output", PLAYLIST_TEMPLATE if playlist_link else TEMPLATE,
                    "--windows-filenames", "--continue", "--embed-metadata",
                    "--force-overwrites" if args.overwrite else "--no-overwrites"]
        if args.quiet:
            command += ["--quiet", "--no-progress"]
        else:
            command += ["--no-quiet", "--progress", "--print", "after_move:Saved: %(filepath)s"]
        if args.subtitles:
            command += ["--write-subs", "--sub-langs", args.subtitles, "--convert-subs", "srt"]
            if args.auto_subs:
                command += ["--write-auto-subs"]
        if args.thumbnail:
            command += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
        if args.archive:
            command += ["--download-archive", str(args.archive.expanduser().resolve())]
        if args.limit_rate:
            command += ["--limit-rate", args.limit_rate]
    return [*command, "--", url]


def show_info(data):
    if not isinstance(data, dict):
        raise ValueError("yt-dlp returned an invalid preview response")
    if data.get("_type") in {"playlist", "multi_video"}:
        entries = data.get("entries") or []
        print(f"Playlist: {data.get('title') or 'Untitled'} ({len(entries)} selected entries)")
        for entry in entries:
            if entry:
                show_info(entry)
        return
    duration = data.get("duration")
    if duration is None:
        duration_text = "live / unknown"
    else:
        seconds = int(duration)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        duration_text = f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"
    print(f"\nTitle:    {data.get('title') or 'Untitled'}")
    print(f"Channel:  {data.get('channel') or data.get('uploader') or 'Unknown'}")
    print(f"Duration: {duration_text}")
    print(f"Format:   {data.get('resolution') or data.get('format') or 'Unknown'}")
    print(f"Link:     {data.get('webpage_url') or data.get('original_url') or 'Unknown'}")


def doctor():
    print(f"YVD {__version__} | Python {sys.version.split()[0]}")
    downloader = resolve_downloader()
    tools = {"yt-dlp": downloader,
             "ffmpeg": [shutil.which("ffmpeg")] if shutil.which("ffmpeg") else None,
             "ffprobe": [shutil.which("ffprobe")] if shutil.which("ffprobe") else None}
    healthy = True
    for name, command in tools.items():
        if not command:
            print(f"MISSING  {name}")
            healthy = False
            continue
        try:
            flag = "--version" if name == "yt-dlp" else "-version"
            completed = subprocess.run([*command, flag], capture_output=True, text=True, timeout=10)
            lines = (completed.stdout or completed.stderr).splitlines()
            ok = completed.returncode == 0
            print(f"{'OK' if ok else 'FAILED':8} {name}: {lines[0] if lines else 'no version response'}")
            healthy &= ok
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"FAILED   {name}: {error}")
            healthy = False
    runtimes = [name for name in ("deno", "node") if shutil.which(name)]
    print("JavaScript: " + (", ".join(runtimes) if runtimes else "no Deno/Node found; some YouTube videos may need one"))
    if not healthy:
        print("Install yt-dlp, FFmpeg and FFprobe; see README.md for setup.")
    return 0 if healthy else 3


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_intermixed_args(argv)
    try:
        if args.doctor:
            if args.inputs or args.batch:
                argument_parser.error("--doctor does not accept download inputs")
            return doctor()
        try:
            urls = collect_urls(args)
            if args.cookies and not args.cookies.expanduser().is_file():
                raise ValueError("cookie file does not exist or is not a regular file")
        except (ValueError, OSError, UnicodeError) as error:
            argument_parser.error(str(error))
        downloader = resolve_downloader()
        if args.dry_run:
            for url in urls:
                print(shlex.join(build_command(args, url, downloader or ["yt-dlp"])))
            return 0
        if not downloader:
            print("YVD: yt-dlp is missing. Install it with: python -m pip install 'yt-dlp[default]'", file=sys.stderr)
            return 3
        if not (args.info or args.list_formats):
            missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
            if missing:
                print(f"YVD: missing {', '.join(missing)}. Install FFmpeg, then run yvd --doctor.", file=sys.stderr)
                return 3
            try:
                args.output = args.output.expanduser().resolve()
                args.output.mkdir(parents=True, exist_ok=True)
                if args.archive:
                    args.archive = args.archive.expanduser().resolve()
                    args.archive.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                print(f"YVD: cannot prepare output/archive directory: {error}", file=sys.stderr)
                return 1
        failures = []
        processed = 0
        for index, url in enumerate(urls, 1):
            if not args.quiet and not args.info:
                print(f"[{index}/{len(urls)}] {url}", flush=True)
            command = build_command(args, url, downloader)
            processed += 1
            try:
                if args.info:
                    result = subprocess.run(command, capture_output=True, text=True)
                    if result.stderr:
                        print(result.stderr, file=sys.stderr, end="")
                    if result.returncode == 0:
                        show_info(json.loads(result.stdout))
                else:
                    result = subprocess.run(command)
                code = result.returncode
            except (OSError, ValueError, TypeError) as error:
                print(f"YVD: {error}", file=sys.stderr)
                code = 1
            if code:
                failures.append((url, code if code > 0 else 1))
                print(f"YVD: failed ({code}): {url}", file=sys.stderr)
                if args.fail_fast:
                    break
        if len(urls) > 1 and not args.quiet:
            print(f"\nFinished: {processed - len(failures)} input(s) succeeded, {len(failures)} failed, "
                  f"{len(urls) - processed} not attempted.")
            for url, _ in failures:
                print(f"  Failed: {url}", file=sys.stderr)
        return failures[0][1] if failures else 0
    except KeyboardInterrupt:
        print("\nYVD: cancelled. Run the same command again to resume partial downloads.", file=sys.stderr)
        return 130
