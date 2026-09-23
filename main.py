# Imports
import argparse
import subprocess
import re
import sys

# Arguments
parser = argparse.ArgumentParser()
parser.add_argument("url", type=str, help="Please input a YouTube URL")
parser.add_argument("type", type=str, help="Please input either MP4 or MP3")
args = parser.parse_args()

# Regex patterns
pattern_url = r"^(?:https?:\/\/)?(?:www\.)?(?:m\.)?(?:music\.)?(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))((?:\w|-){11})(?:\S+)?$"

# Check if the arguments are valid
if not re.match(pattern_url, args.url):
    print(f"Invalid URL {args.url}")
    sys.exit(1)

if args.type.lower() not in ("mp3", "mp4"):
    print(f"Invalid type {args.type}")
    sys.exit(2)

def run_ytdlp(command):
    try:
        result = subprocess.run(command)
    except FileNotFoundError:
        print("yt-dlp is not installed.")
        sys.exit(3)

    if result.returncode != 0:
        print("Download failed")
        sys.exit(result.returncode)

def download_mp4(url):
    run_ytdlp([
        "yt-dlp",
        "-f", "bestvideo+bestaudio/best",
        "--merge-output-format", "mp4",
        url
    ])

def download_mp3(url):
    run_ytdlp([
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        url
    ])

if args.type.lower() == "mp3":
    download_mp3(args.url)
else:
    download_mp4(args.url)
