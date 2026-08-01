# 🎵 Suno Auto-Downloader

**Version 2.0.0 — Free-Tier First**

> Fully automatic bulk downloader for your [Suno AI](https://suno.com) music library.  
> **Optimized for free accounts** that lost easy official download access after the 2026 Warner deal.

Previous version (v1.0.0) is preserved in Git history.

---

## Why this version exists

Free Suno users can still generate songs, but official bulk/download buttons became restricted.  
This tool uses the library feed + CDN audio links that still work for most free accounts, so you can keep an offline archive of everything you created.

---

## ✨ Features (v2.0.0)

| Feature | Details |
|---|---|
| **Free-tier focused** | No paid-only features required |
| **Full library scan** | Paginates your entire history |
| **True resume** | State file tracks what is already downloaded |
| **Provenance package** | `.mp3` + `.json` + human-readable `.txt` for every song |
| **ID3 metadata** | Title, lyrics, cover art, tags embedded |
| **Month organization** | Optional `YYYY-MM` folders |
| **Doctor command** | Diagnostics for auth / API / deps |
| **Polite rate limiting** | Adaptive retries + delays suited to free accounts |
| **Smart skip** | Never re-downloads existing songs |

---

## 🚀 Quick Start

### 1. Install

```bash
git clone https://github.com/Stijnman/suno-auto-downloader.git
cd suno-auto-downloader
pip3 install -r requirements.txt
```

### 2. Get a token (free account)

1. Open [https://suno.com](https://suno.com) and log in.
2. Press **F12** → **Console**.
3. Paste the contents of `get_token.js` and press Enter.
4. The token is printed and copied to clipboard.
5. Save it:

```bash
echo "YOUR_TOKEN_HERE" > .suno_token
```

Tokens last ~60 minutes on free accounts. Re-run `get_token.js` when needed.

### 3. Download everything

```bash
python3 suno_downloader.py
```

Or with options:

```bash
python3 suno_downloader.py --output ~/Music/Suno --organize-month
python3 suno_downloader.py --doctor          # check if everything works
python3 suno_downloader.py --list-only       # just list your songs
python3 suno_downloader.py --workers 2       # slower = safer on free accounts
```

---

## Command-line options

```
--token JWT          Suno token (or use .suno_token / SUNO_TOKEN env)
--output DIR         Output folder (default: ./suno_songs)
--workers N          Parallel downloads (default: 3)
--organize-month     Put songs into YYYY-MM subfolders
--max-pages N        Limit how many pages to scan
--list-only          Only list songs, do not download
--no-metadata        Skip ID3 tagging
--doctor             Run diagnostics
--debug              Verbose logging
--version            Show version
```

---

## Output structure

```
suno_songs/
├── .suno_state.json          ← resume state
├── My Song Title_a1b2c3d4.mp3
├── My Song Title_a1b2c3d4.json
├── My Song Title_a1b2c3d4.txt
└── 2026-07/                  ← if --organize-month
    └── ...
```

---

## Version history

- **2.0.0** (current) — Free-tier first rewrite (see `CHANGELOG.md`)
- **1.0.0** — Original version (preserved in Git history)

---

## Notes for free users

- Official download buttons may be limited or hidden. This tool bypasses the UI limitation by using the same feed + CDN links the website itself uses.
- Keep your token fresh.
- Start with low `--workers` (2–3) if you hit rate limits.
- Run regularly with the same output folder — it only downloads new songs.

---

## Disclaimer

Unofficial tool. Not affiliated with Suno. Use only on your own account and respect Suno’s Terms of Service.  
For personal archival purposes.
