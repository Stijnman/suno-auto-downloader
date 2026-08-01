# 🎵 Suno Auto-Downloader

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Stijnman/suno-auto-downloader?style=social)](https://github.com/Stijnman/suno-auto-downloader)

> **Fully automatic bulk downloader for your [Suno AI](https://suno.com) music library.**  
> Fetches every song you have ever generated, downloads MP3/WAV files in parallel, embeds title, lyrics, and cover art as ID3 tags, and skips files already on disk — so you can run it again and again to stay in sync.

---

## ✨ Features

| Feature | Details |
|---|---|
| **Full library scan** | Paginates through every page of your Suno library automatically |
| **Parallel downloads** | 4 concurrent threads by default (configurable) |
| **Smart sync** | Skips songs already downloaded — safe to re-run |
| **ID3 metadata** | Embeds title, artist (`Suno AI`), lyrics, genre tags, and cover art |
| **JSON sidecars** | Saves a `.json` file next to each song with the full API metadata |
| **MP3 or WAV** | Choose your preferred format with `--wav` |
| **Token flexibility** | Pass token via CLI flag, environment variable, or `.suno_token` file |
| **No GUI needed** | Pure command-line, runs on any OS |

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
git clone https://github.com/Stijnman/suno-auto-downloader.git
cd suno-auto-downloader
pip3 install -r requirements.txt
```

### 2. Get your Suno token

Your Suno session token is a short-lived JWT (~60 min) issued by [Clerk](https://clerk.com/).

**Method A — Browser console (recommended)**

1. Open [https://suno.com](https://suno.com) and log in.
2. Press **F12** → **Console** tab.
3. Paste the contents of [`get_token.js`](get_token.js) and press **Enter**.
4. The token is printed and copied to your clipboard automatically.

**Method B — Network tab**

1. Open [https://suno.com/create](https://suno.com/create) in your browser.
2. Press **F12** → **Network** tab → refresh the page.
3. Find any request containing `?__clerk_api_version` in the URL.
4. Click it → **Headers** → copy the value of the `Authorization` header (everything after `Bearer `).

### 3. Save the token (optional but convenient)

```bash
echo "eyJ..." > .suno_token   # paste your token here
```

The `.suno_token` file is in `.gitignore` and will never be committed.

### 4. Run the downloader

```bash
# Using .suno_token file
python3 suno_downloader.py

# Or pass the token directly
python3 suno_downloader.py --token eyJ...

# Or via environment variable
SUNO_TOKEN=eyJ... python3 suno_downloader.py
```

Songs are saved to `./suno_songs/` by default.

---

## 📖 Usage

```
python3 suno_downloader.py [OPTIONS]

Options:
  --token JWT        Suno Bearer token (JWT)
  --output DIR       Output directory (default: ./suno_songs)
  --wav              Prefer WAV over MP3 when available
  --no-metadata      Skip embedding ID3 metadata into MP3 files
  --workers N        Parallel download threads (default: 4)
  --max-pages N      Stop after N pages of the library (0 = unlimited)
  --list-only        Print all song titles/IDs without downloading
  --debug            Enable verbose debug logging
  -h, --help         Show this help message
```

### Examples

```bash
# Download everything to ~/Music/Suno
python3 suno_downloader.py --output ~/Music/Suno

# Download as WAV with 8 parallel threads
python3 suno_downloader.py --wav --workers 8

# Just list all songs (no download)
python3 suno_downloader.py --list-only

# Download only the first 5 pages (~100 songs)
python3 suno_downloader.py --max-pages 5

# Full verbose run
python3 suno_downloader.py --debug
```

---

## 📂 Output Structure

```
suno_songs/
├── My Awesome Song_a1b2c3d4.mp3      ← audio file with embedded metadata
├── My Awesome Song_a1b2c3d4.json     ← full API metadata (title, lyrics, tags, …)
├── Another Track_e5f6g7h8.mp3
├── Another Track_e5f6g7h8.json
└── …
```

Each JSON sidecar contains the complete raw response from Suno's API, including:

- `id`, `title`, `audio_url`, `image_url`
- `metadata.prompt` (your generation prompt / lyrics)
- `metadata.tags` (style tags)
- `created_at`, `status`, `play_count`, `upvote_count`

---

## 🔐 Token Security

- **Never commit your token.** The `.suno_token` file is listed in `.gitignore`.
- Tokens expire after approximately **60 minutes**. Re-run `get_token.js` to get a fresh one.
- If you get HTTP 401 errors, your token has expired — refresh it.

---

## ⚙️ How It Works

```
┌─────────────────────────────────────────────────────┐
│  1. Authenticate with Bearer token (Clerk JWT)      │
│  2. GET https://studio-api.prod.suno.com/api/feed/  │
│     ?page=1, ?page=2, … until empty response        │
│  3. For each song:                                  │
│     a. Download audio_url → .mp3 / .wav             │
│     b. Download image_url → cover art bytes         │
│     c. Embed ID3 tags (mutagen)                     │
│     d. Write .json sidecar                          │
│  4. Skip songs already on disk (smart sync)         │
└─────────────────────────────────────────────────────┘
```

The downloader talks directly to Suno's internal production API (`studio-api.prod.suno.com`), the same endpoint used by the Suno web application. No third-party services or paid APIs are required.

---

## 🛠️ Requirements

| Package | Purpose |
|---|---|
| `requests` | HTTP client for API calls and file downloads |
| `mutagen` | ID3 tag writing (title, lyrics, cover art) |
| `tqdm` | Progress bar (optional but recommended) |

Python 3.9 or higher is required.

---

## 🔄 Keeping Your Library in Sync

Because the downloader skips existing files, you can schedule it to run automatically:

**Linux / macOS (cron)**

```bash
# Add to crontab: run every day at 8 AM
0 8 * * * cd /path/to/suno-auto-downloader && SUNO_TOKEN=eyJ... python3 suno_downloader.py
```

**Windows (Task Scheduler)**

Create a basic task that runs `python3 suno_downloader.py` with `SUNO_TOKEN` set as a system environment variable.

> **Note:** Tokens expire after ~60 minutes. For scheduled/unattended runs, you will need to refresh the token periodically. The most reliable approach is to re-extract it from your browser before each scheduled run, or implement a token-refresh flow using Clerk's API.

---

## 🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## ⚠️ Disclaimer

This is an **unofficial, community-built tool** and is not affiliated with or endorsed by Suno AI. Use it responsibly and in accordance with [Suno's Terms of Service](https://suno.com/terms). Only download songs that belong to your own account.

---

## 📄 License

[MIT](LICENSE) — free to use, modify, and distribute.
