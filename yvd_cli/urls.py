"""Validate YouTube links before they reach the downloader."""

import re
from urllib.parse import parse_qs, urlencode, urlsplit

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
PLAYLIST_ID = re.compile(r"[A-Za-z0-9_-]{2,200}\Z")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
EMBED_HOSTS = {"youtube-nocookie.com", "www.youtube-nocookie.com"}


def normalize_url(value: str, *, playlist: bool = False) -> str:
    """Accept video/playlist links, discard tracking, and enforce playlist opt-in."""
    value = value.strip()
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("expected a YouTube URL without whitespace")
    if "://" not in value:
        value = "https://" + value
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"}:
            raise ValueError("only HTTP and HTTPS YouTube links are supported")
        if parts.username or parts.password or parts.port is not None:
            raise ValueError("credentials and custom ports are not allowed in YouTube links")
        host = (parts.hostname or "").lower()
    except ValueError as error:
        raise ValueError(f"invalid YouTube URL: {error}") from error
    if host not in HOSTS | EMBED_HOSTS | {"youtu.be", "www.youtu.be"}:
        raise ValueError("expected a youtube.com or youtu.be link")
    query = parse_qs(parts.query, keep_blank_values=True)
    segments = parts.path.strip("/").split("/")
    video = None
    if host in {"youtu.be", "www.youtu.be"} and len(segments) == 1:
        video = segments[0]
    elif host in HOSTS and parts.path.rstrip("/") == "/watch":
        videos = query.get("v", [])
        if len(videos) != 1:
            raise ValueError("a watch link must contain exactly one video ID")
        video = videos[0]
    elif host in HOSTS | EMBED_HOSTS and len(segments) == 2 and segments[0] in {"shorts", "live", "embed", "v"}:
        if host in EMBED_HOSTS and segments[0] != "embed":
            raise ValueError("youtube-nocookie.com only supports embed links")
        video = segments[1]
    elif host in HOSTS and parts.path.rstrip("/") == "/playlist":
        if not playlist:
            raise ValueError("playlist links require --playlist")
    else:
        raise ValueError("expected a video, Shorts, live, embed, or playlist link")
    if video is not None and not VIDEO_ID.fullmatch(video):
        raise ValueError("YouTube video IDs must contain 11 letters, digits, underscores, or hyphens")
    params = {}
    if video:
        params["v"] = video
    if playlist and "list" in query:
        lists = query["list"]
        if len(lists) != 1 or not PLAYLIST_ID.fullmatch(lists[0]):
            raise ValueError("invalid YouTube playlist ID")
        params["list"] = lists[0]
    if not video and "list" not in params:
        raise ValueError("playlist link is missing its list ID")
    path = "watch" if video else "playlist"
    return f"https://www.youtube.com/{path}?{urlencode(params)}"
