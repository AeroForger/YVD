"""Exercise real yt-dlp/FFmpeg against generated media on a loopback server.

Only extraction is substituted with --load-info-json. Downloads, selection,
merging, conversion, metadata, subtitles, thumbnails and archives run normally.
"""

import functools
import http.server
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from yvd_cli.cli import build_command, collect_urls, parser, resolve_downloader

URL = "https://www.youtube.com/watch?v=BaW_jenozKc"


class Handler(http.server.SimpleHTTPRequestHandler):
    requests = 0

    def do_GET(self):
        type(self).requests += 1
        super().do_GET()

    def log_message(self, *args):
        pass


@unittest.skipUnless(resolve_downloader() and shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "integration requires yt-dlp, ffmpeg and ffprobe")
class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="yvd-integration-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.make_media("video.mp4", ["-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10", "-t", "1",
                                     "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
        cls.make_media("audio.m4a", ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                                     "-t", "1", "-c:a", "aac"])
        cls.make_media("fallback.webm", ["-f", "lavfi", "-i", "color=c=red:s=160x90:r=10",
                                         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                                         "-t", "1", "-c:v", "libvpx-vp9", "-c:a", "libopus"])
        cls.make_media("cover.jpg", ["-f", "lavfi", "-i", "color=c=green:s=64x64", "-frames:v", "1"])
        (cls.root / "captions.vtt").write_text("WEBVTT\n\n00:00.000 --> 00:00.900\nYVD subtitle test\n")
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(cls.root)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.stop_server)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.formats = [
            {"format_id": "v", "url": cls.base + "/video.mp4", "ext": "mp4", "vcodec": "avc1.42001e",
             "acodec": "none", "width": 160, "height": 90, "fps": 10, "protocol": "http"},
            {"format_id": "a", "url": cls.base + "/audio.m4a", "ext": "m4a", "vcodec": "none",
             "acodec": "mp4a.40.2", "abr": 128, "protocol": "http"},
        ]

    @classmethod
    def make_media(cls, name, options):
        result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *options,
                                 "-threads", "1", str(cls.root / name)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr)

    @classmethod
    def stop_server(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def fixture(self, name, *, fallback=False, playlist=False):
        info = {"id": "BaW_jenozKc", "title": "YVD Local Test", "uploader": "YVD Test Channel",
                "duration": 1, "webpage_url": URL, "extractor": "youtube", "extractor_key": "Youtube",
                "formats": self.formats,
                "subtitles": {"en": [{"url": self.base + "/captions.vtt", "ext": "vtt"}]},
                "thumbnails": [{"url": self.base + "/cover.jpg", "id": "cover", "ext": "jpg"}]}
        if fallback:
            info["formats"] = [{"format_id": "webm", "url": self.base + "/fallback.webm", "ext": "webm",
                                "vcodec": "vp9", "acodec": "opus", "width": 160, "height": 90, "protocol": "http"}]
        if playlist:
            second = dict(info, id="jNQXAC9IVRw", title="YVD Second Test", webpage_url="https://youtube.com/watch?v=jNQXAC9IVRw")
            info = {"_type": "playlist", "id": "PLyvd_test", "title": "YVD Test Playlist", "extractor": "youtube:tab",
                    "extractor_key": "YoutubeTab", "entries": [info, second]}
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(info))
        return path

    def download(self, name, *options, fallback=False, playlist=False):
        output = self.root / name
        url = URL + "&list=PLyvd_test" if playlist else URL
        args = parser().parse_intermixed_args([url, "--output", str(output), *options])
        urls = collect_urls(args)
        command = build_command(args, urls[0], resolve_downloader())
        fixture = self.fixture(name, fallback=fallback, playlist=playlist)
        # yt-dlp's default cleaning removes playlist entries from saved JSON.
        command = [*command[:-2], "--no-clean-info-json", "--load-info-json", str(fixture)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output, result

    def probe(self, file):
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(file)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_mp4_merges_video_and_audio_and_embeds_metadata(self):
        output, result = self.download("merge", "--quality", "720")
        files = list(output.glob("*.mp4"))
        self.assertEqual(len(files), 1)
        data = self.probe(files[0])
        self.assertEqual({stream["codec_type"] for stream in data["streams"]}, {"video", "audio"})
        self.assertEqual(data["format"]["tags"]["title"], "YVD Local Test")
        self.assertIn("Saved:", result.stdout)
        self.assertFalse(list(output.glob("*.part")))

    def test_non_mp4_fallback_is_reencoded(self):
        output, _ = self.download("fallback", fallback=True)
        files = list(output.glob("*.mp4"))
        self.assertEqual(len(files), 1)
        data = self.probe(files[0])
        self.assertIn("h264", {stream["codec_name"] for stream in data["streams"]})
        self.assertFalse(list(output.glob("*.webm")))

    def test_mp3_cover_art_subtitles_and_bitrate(self):
        output, _ = self.download("audio", "mp3", "--audio-quality", "192", "--subtitles", "en", "--thumbnail")
        files = list(output.glob("*.mp3"))
        self.assertEqual(len(files), 1)
        data = self.probe(files[0])
        audio = next(stream for stream in data["streams"] if stream["codec_type"] == "audio")
        self.assertEqual(audio["codec_name"], "mp3")
        self.assertEqual(int(audio["bit_rate"]), 192000)
        self.assertTrue(any(stream.get("disposition", {}).get("attached_pic") for stream in data["streams"]))
        subtitles = list(output.glob("*.srt"))
        self.assertEqual(len(subtitles), 1)
        self.assertIn("YVD subtitle test", subtitles[0].read_text())

    def test_archive_skips_second_download(self):
        archive = self.root / "archive.txt"
        self.download("archived", "--archive", str(archive))
        self.assertIn("youtube BaW_jenozKc", archive.read_text())
        requests_before = Handler.requests
        _, result = self.download("archived", "--archive", str(archive))
        self.assertEqual(Handler.requests, requests_before)
        self.assertIn("already been recorded in the archive", result.stdout)

    def test_preview_has_no_downloads(self):
        requests_before = Handler.requests
        output, result = self.download("preview", "--info")
        self.assertFalse(output.exists())
        self.assertEqual(Handler.requests, requests_before)
        self.assertEqual(json.loads(result.stdout)["title"], "YVD Local Test")

    def test_existing_file_is_preserved_and_overwrite_redownloads(self):
        output, _ = self.download("preserved")
        file = next(output.glob("*.mp4"))
        before = (file.stat().st_mtime_ns, hashlib.sha256(file.read_bytes()).hexdigest())
        requests_before = Handler.requests
        self.download("preserved")
        self.assertEqual(Handler.requests, requests_before)
        self.assertEqual((file.stat().st_mtime_ns, hashlib.sha256(file.read_bytes()).hexdigest()), before)
        self.download("preserved", "--overwrite")
        self.assertGreater(Handler.requests, requests_before)
        self.assertNotEqual(file.stat().st_mtime_ns, before[0])

    def test_quiet_download_has_no_status_output(self):
        output, result = self.download("quiet", "--quiet")
        self.assertEqual(len(list(output.glob("*.mp4"))), 1)
        self.assertEqual(result.stdout, "")

    def test_playlist_selection_and_numbered_folder(self):
        output, _ = self.download("playlist", "--playlist", "--playlist-items", "2", playlist=True)
        files = list(output.rglob("*.mp4"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.name, "YVD Test Playlist")
        self.assertTrue(files[0].name.startswith("002 - YVD Second Test"), files[0].name)


if __name__ == "__main__":
    unittest.main()
