import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yvd_cli import cli
from yvd_cli.urls import normalize_url

VIDEO = "BaW_jenozKc"
URL = f"https://www.youtube.com/watch?v={VIDEO}"
SECOND = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
PLAYLIST = "https://www.youtube.com/playlist?list=PLtest_123"


def arguments(*values):
    args = cli.parser().parse_intermixed_args(values or [URL])
    urls = cli.collect_urls(args)
    return args, urls


class URLTests(unittest.TestCase):
    def test_supported_video_links(self):
        links = [URL, f"youtu.be/{VIDEO}?si=tracking", f"http://m.youtube.com/watch?t=5&v={VIDEO}",
                 f"https://music.youtube.com/watch?v={VIDEO}", f"https://youtube.com/shorts/{VIDEO}",
                 f"https://youtube.com/live/{VIDEO}", f"https://youtube.com/embed/{VIDEO}",
                 f"https://youtube.com/v/{VIDEO}", f"https://www.youtube-nocookie.com/embed/{VIDEO}",
                 f"https://WWW.YOUTUBE.COM/watch?v={VIDEO}"]
        for link in links:
            with self.subTest(link=link):
                self.assertEqual(normalize_url(link), URL)

    def test_host_and_id_validation(self):
        links = ["", "--exec=bad", "file:///tmp/video", f"ftp://youtube.com/watch?v={VIDEO}",
                 f"https://youtube.com.evil.example/watch?v={VIDEO}",
                 f"https://youtube.com@evil.example/watch?v={VIDEO}",
                 f"https://user:pass@youtube.com/watch?v={VIDEO}",
                 f"https://youtube.com:443/watch?v={VIDEO}",
                 f"https://youtube.com:bad/watch?v={VIDEO}",
                 "https://youtube.com/watch?v=short", "https://youtube.com/@channel",
                 f"https://youtube.com/watch?v={VIDEO}&v={VIDEO}",
                 f"https://youtube.com/watch?v={VIDEO}&v=",
                 f"https://youtube.com/watch?v={VIDEO} extra", "https://[broken", 
                 f"https://youtube-nocookie.com/shorts/{VIDEO}"]
        for link in links:
            with self.subTest(link=link), self.assertRaises(ValueError):
                normalize_url(link)

    def test_playlist_requires_opt_in(self):
        with self.assertRaisesRegex(ValueError, "--playlist"):
            normalize_url(PLAYLIST)
        self.assertEqual(normalize_url(PLAYLIST, playlist=True), PLAYLIST)

    def test_video_playlist_stripped_by_default(self):
        self.assertEqual(normalize_url(URL + "&list=PLtest_123&index=4"), URL)
        self.assertEqual(normalize_url(URL + "&list=PLtest_123", playlist=True), URL + "&list=PLtest_123")

    def test_invalid_playlists(self):
        for link in ("https://youtube.com/playlist", PLAYLIST + "&list=another", "https://youtube.com/playlist?list=%20"):
            with self.subTest(link=link), self.assertRaises(ValueError):
                normalize_url(link, playlist=True)


class ArgumentTests(unittest.TestCase):
    def test_legacy_format_and_default(self):
        self.assertEqual(arguments(URL)[0].format, "mp4")
        self.assertEqual(arguments(URL, "MP3")[0].format, "mp3")
        self.assertEqual(arguments(URL, "--quiet", "mp3")[0].format, "mp3")

    def test_conflicting_format(self):
        with self.assertRaisesRegex(ValueError, "conflicts"):
            arguments(URL, "mp3", "-f", "mp4")

    def test_deduplicates_normalized_links(self):
        _, urls = arguments(URL, f"https://youtu.be/{VIDEO}", SECOND)
        self.assertEqual(urls, [URL, SECOND])

    def test_batch_comments_bom_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "links.txt"
            path.write_text(f"\ufeff# list\n\n{URL}\n  # comment\n{SECOND}\n{URL}\n", encoding="utf-8")
            _, urls = arguments(URL, "--batch", str(path))
            self.assertEqual(urls, [URL, SECOND])

    def test_batch_stdin(self):
        with patch("sys.stdin", io.StringIO(f"# comment\n{URL}\n{SECOND}\n")):
            self.assertEqual(arguments("--batch", "-")[1], [URL, SECOND])

    def test_option_dependencies(self):
        for values in [(URL, "--playlist-items", "1-3"), (URL, "--auto-subs"),
                       (URL, "--audio-quality", "320"), (URL, "mp3", "--quality", "720"),
                       (URL, "--subtitles", " ")]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                arguments(*values)

    def test_empty_input(self):
        args = cli.parser().parse_args([])
        with self.assertRaisesRegex(ValueError, "provide"):
            cli.collect_urls(args)

    def test_ranges(self):
        self.assertEqual(cli.playlist_items("1-5,8,12-15"), "1-5,8,12-15")
        for value in ("0", "5-1", "1:5", "-1", "all", "1,"):
            with self.subTest(value=value), self.assertRaises(Exception):
                cli.playlist_items(value)

    def test_rates_and_retries(self):
        self.assertEqual(cli.rate("2M"), "2M")
        self.assertEqual(cli.rate("500K"), "500K")
        self.assertEqual(cli.nonnegative("0"), 0)
        for value in ("0", "-2M", "fast", "1;echo"):
            with self.subTest(value=value), self.assertRaises(Exception):
                cli.rate(value)
        with self.assertRaises(Exception):
            cli.nonnegative("-1")


class CommandTests(unittest.TestCase):
    def command(self, *values):
        args, urls = arguments(*values)
        return cli.build_command(args, urls[0], ["yt-dlp"])

    def test_mp4_limits_every_video_fallback(self):
        command = self.command(URL, "--quality", "720")
        selection = command[command.index("-f") + 1]
        for branch in selection.split("/"):
            self.assertIn("[height<=720]", branch)
        self.assertIn("--recode-video", command)
        self.assertIn("--no-playlist", command)
        self.assertIn("--ignore-config", command)
        self.assertEqual(command[-2:], ["--", URL])

    def test_mp3_quality(self):
        command = self.command(URL, "mp3", "--audio-quality", "320")
        self.assertEqual(command[command.index("--audio-quality") + 1], "320K")
        self.assertIn("--extract-audio", command)
        self.assertNotIn("--recode-video", command)
        command = self.command(URL, "mp3")
        self.assertEqual(command[command.index("--audio-quality") + 1], "0")

    def test_playlist_paths_and_selection(self):
        command = self.command(PLAYLIST, "--playlist", "--playlist-items", "1-3")
        self.assertIn("--yes-playlist", command)
        self.assertIn(cli.PLAYLIST_TEMPLATE, command)
        self.assertEqual(command[command.index("--playlist-items") + 1], "1-3")

    def test_single_video_with_playlist_enabled_keeps_normal_filename(self):
        command = self.command(URL, "--playlist")
        self.assertIn(cli.TEMPLATE, command)
        self.assertNotIn(cli.PLAYLIST_TEMPLATE, command)

    def test_preview_avoids_output_operations(self):
        for mode in ("--info", "--list-formats"):
            with self.subTest(mode=mode):
                command = self.command(URL, mode, "--archive", "state/archive.txt", "--thumbnail", "--subtitles", "en")
                self.assertIn("--simulate", command)
                for option in ("--paths", "--download-archive", "--embed-thumbnail", "--write-subs", "--embed-metadata"):
                    self.assertNotIn(option, command)

    def test_captions_cover_and_resume(self):
        command = self.command(URL, "--subtitles", "en,ka", "--auto-subs", "--thumbnail")
        for option in ("--continue", "--no-overwrites", "--write-subs", "--write-auto-subs", "--embed-thumbnail"):
            self.assertIn(option, command)
        self.assertEqual(command[command.index("--convert-subs") + 1], "srt")

    def test_overwrite_and_quiet(self):
        command = self.command(URL, "--overwrite", "--quiet", "--limit-rate", "2M")
        self.assertIn("--force-overwrites", command)
        self.assertIn("--no-progress", command)
        self.assertNotIn("--print", command)
        self.assertIn("2M", command)

    def test_output_path_is_a_single_literal_argument(self):
        command = self.command(URL, "--output", "folder with spaces;$(touch BAD)")
        self.assertTrue(command[command.index("--paths") + 1].endswith("folder with spaces;$(touch BAD)"))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.output = Path(self.folder.name) / "downloads"

    def run_cli(self, values, **kwargs):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return cli.main([*values, "--output", str(self.output)], **kwargs)

    def test_missing_downloader_no_side_effects(self):
        with patch.object(cli, "resolve_downloader", return_value=None):
            self.assertEqual(self.run_cli([URL]), 3)
        self.assertFalse(self.output.exists())
        self.assertIn("yt-dlp is missing", self.stderr.getvalue())

    def test_missing_ffmpeg_no_side_effects(self):
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value=None):
            self.assertEqual(self.run_cli([URL]), 3)
        self.assertFalse(self.output.exists())
        self.assertIn("missing ffmpeg, ffprobe", self.stderr.getvalue())

    def test_dry_run_needs_no_dependencies_or_writes(self):
        with patch.object(cli, "resolve_downloader", return_value=None), patch.object(cli.subprocess, "run") as run:
            self.assertEqual(self.run_cli([URL, "--dry-run", "--archive", str(self.output / "state.txt")]), 0)
            run.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertIn("yt-dlp --ignore-config", self.stdout.getvalue())

    def test_invalid_batch_is_validated_before_download(self):
        path = Path(self.folder.name) / "invalid.txt"
        path.write_text(URL + "\nhttps://evil.example/video\n")
        with patch.object(cli.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as error:
                self.run_cli(["--batch", str(path)])
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_batch_continues_and_propagates_failure(self):
        results = [subprocess.CompletedProcess([], 7), subprocess.CompletedProcess([], 0)]
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value="/bin/tool"), patch.object(cli.subprocess, "run", side_effect=results) as run:
            self.assertEqual(self.run_cli([URL, SECOND]), 7)
            self.assertEqual(run.call_count, 2)
        self.assertIn("1 input(s) succeeded, 1 failed", self.stdout.getvalue())

    def test_fail_fast_reports_unattempted_inputs(self):
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value="/bin/tool"), patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 4)) as run:
            self.assertEqual(self.run_cli([URL, SECOND, "--fail-fast"]), 4)
            self.assertEqual(run.call_count, 1)
        self.assertIn("1 not attempted", self.stdout.getvalue())

    def test_interrupted_download(self):
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value="/bin/tool"), patch.object(cli.subprocess, "run", side_effect=KeyboardInterrupt):
            self.assertEqual(self.run_cli([URL]), 130)
        self.assertIn("resume", self.stderr.getvalue())

    def test_preview_without_ffmpeg_and_output_directory(self):
        data = {"title": "Preview", "channel": "Test", "duration": 3671, "resolution": "1280x720", "webpage_url": URL}
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(data), stderr="")
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value=None), patch.object(cli.subprocess, "run", return_value=result):
            self.assertEqual(self.run_cli([URL, "--info"]), 0)
        self.assertFalse(self.output.exists())
        self.assertIn("1:01:11", self.stdout.getvalue())
        self.assertIn("Preview", self.stdout.getvalue())

    def test_invalid_preview_response_is_failure(self):
        for response in ("invalid json", "[]", "null"):
            with self.subTest(response=response):
                result = subprocess.CompletedProcess([], 0, stdout=response, stderr="")
                with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.subprocess, "run", return_value=result):
                    self.assertEqual(self.run_cli([URL, "--info"]), 1)

    def test_output_file_instead_of_directory(self):
        self.output.write_text("preserve me")
        with patch.object(cli, "resolve_downloader", return_value=["yt-dlp"]), patch.object(cli.shutil, "which", return_value="/bin/tool"), patch.object(cli.subprocess, "run") as run:
            self.assertEqual(self.run_cli([URL]), 1)
            run.assert_not_called()
        self.assertEqual(self.output.read_text(), "preserve me")

    def test_missing_cookie_file(self):
        with self.assertRaises(SystemExit) as error:
            self.run_cli([URL, "--cookies", str(self.output / "cookies.txt")])
        self.assertEqual(error.exception.code, 2)

    def test_doctor_missing_tools(self):
        with contextlib.redirect_stdout(self.stdout), patch.object(cli, "resolve_downloader", return_value=None), patch.object(cli.shutil, "which", return_value=None):
            self.assertEqual(cli.doctor(), 3)
        self.assertIn("MISSING", self.stdout.getvalue())

    def test_module_fallback(self):
        with patch.object(cli.shutil, "which", return_value=None), patch.object(cli.importlib.util, "find_spec", return_value=object()):
            self.assertEqual(cli.resolve_downloader(), [cli.sys.executable, "-m", "yt_dlp"])


if __name__ == "__main__":
    unittest.main()
