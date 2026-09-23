# YVD

A simple Python CLI for downloading YouTube videos as MP4 or MP3 using `yt-dlp`.

## Requirements

- Python 3
- yt-dlp
- FFmpeg

### Arch Linux

```bash
sudo pacman -S python yt-dlp ffmpeg
```

### Debian / Ubuntu

```bash
sudo apt install python3 yt-dlp ffmpeg
```

## Installation

Clone the repository:

```bash
git clone https://github.com/AeroForger/YVD
cd YVD
```

Make the wrapper executable:

```bash
chmod +x yvd
```

Install YVD:

```bash
sudo mkdir -p /usr/local/lib/yvd
sudo cp main.py /usr/local/lib/yvd/main.py
sudo cp yvd /usr/local/bin/yvd
sudo chmod +x /usr/local/bin/yvd
```

## Usage

Download as MP4:

```bash
yvd "https://www.youtube.com/watch?v=VIDEO_ID" mp4
```

Download as MP3:

```bash
yvd "https://www.youtube.com/watch?v=VIDEO_ID" mp3
```

Files are downloaded to the current directory.

## Uninstall

```bash
sudo rm /usr/local/bin/yvd
sudo rm -rf /usr/local/lib/yvd
```

## License

See MIT License
