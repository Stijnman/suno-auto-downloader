#!/usr/bin/env python3
"""
suno_downloader.py — Fully automatic Suno AI song downloader.

Fetches every song from your Suno library via the internal API,
downloads MP3s (or WAV) in parallel, embeds metadata (title, lyrics,
cover art), and skips files that already exist on disk.

Usage:
    python3 suno_downloader.py --token YOUR_TOKEN [options]

Or set the SUNO_TOKEN environment variable and run without --token.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

# ── Optional metadata embedding (mutagen) ────────────────────────────────────
try:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError, TIT2, TPE1, USLT, APIC, TCON, TDRC, COMM
    )
    from mutagen.mp3 import MP3
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# ── Optional progress bar (tqdm) ─────────────────────────────────────────────
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
SUNO_API_BASE = "https://studio-api.prod.suno.com"
FEED_URL      = f"{SUNO_API_BASE}/api/feed/"          # paginated library
FEED_V2_URL   = f"{SUNO_API_BASE}/api/feed/v2"        # public feed (unused by default)
PAGE_SIZE     = 20                                     # Suno returns ≤20 items/page
MAX_WORKERS   = 4                                      # parallel download threads
REQUEST_DELAY = 0.5                                    # seconds between page fetches
RETRY_LIMIT   = 3                                      # retries per failed request
RETRY_DELAY   = 3.0                                    # seconds between retries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("suno")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Remove filesystem-unsafe characters and truncate."""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] if len(name) > max_len else name


def build_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }


def http_get(url: str, headers: dict, params: dict = None, stream: bool = False):
    """GET with retry logic."""
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            r = requests.get(url, headers=headers, params=params,
                             stream=stream, timeout=30)
            if r.status_code == 401:
                log.error("Token rejected (HTTP 401). Obtain a fresh token and retry.")
                sys.exit(1)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 10))
                log.warning("Rate-limited. Waiting %ds …", wait)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            if attempt < RETRY_LIMIT:
                log.warning("Request failed (%s). Retry %d/%d …", exc, attempt, RETRY_LIMIT)
                time.sleep(RETRY_DELAY)
            else:
                raise
    return None  # unreachable


# ─────────────────────────────────────────────────────────────────────────────
# Library fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_songs(token: str, max_pages: int = 0) -> list[dict]:
    """
    Paginate through the Suno feed and return every song dict.

    Each dict contains at minimum:
        id, title, audio_url, image_url, metadata (lyrics, tags, …)
    """
    headers = build_headers(token)
    songs: list[dict] = []
    page = 1

    log.info("Fetching song library …")
    while True:
        if max_pages and page > max_pages:
            log.info("Reached --max-pages limit (%d). Stopping.", max_pages)
            break

        url = f"{FEED_URL}?page={page}"
        log.debug("GET %s", url)
        try:
            r = http_get(url, headers)
        except requests.RequestException as exc:
            log.error("Failed to fetch page %d: %s", page, exc)
            break

        data = r.json()

        # Unwrap different response shapes
        if isinstance(data, list):
            clips = data
        elif isinstance(data, dict):
            clips = (
                data.get("clips")
                or data.get("songs")
                or data.get("items")
                or data.get("tracks")
                or []
            )
        else:
            clips = []

        if not clips:
            log.info("No more songs on page %d. Library fully fetched.", page)
            break

        # Unwrap nested {"clip": {...}} wrappers if present
        for item in clips:
            song = item.get("clip", item) if isinstance(item, dict) else item
            if song and song.get("id"):
                songs.append(song)

        log.info("Page %d → %d songs (total so far: %d)", page, len(clips), len(songs))
        page += 1
        time.sleep(REQUEST_DELAY)

    log.info("Library scan complete. Found %d songs.", len(songs))
    return songs


# ─────────────────────────────────────────────────────────────────────────────
# Metadata embedding
# ─────────────────────────────────────────────────────────────────────────────

def embed_id3_metadata(filepath: Path, song: dict, cover_data: Optional[bytes]):
    """Embed ID3 tags (title, artist, lyrics, cover art) into an MP3 file."""
    if not MUTAGEN_AVAILABLE:
        return

    try:
        try:
            tags = ID3(str(filepath))
        except ID3NoHeaderError:
            tags = ID3()

        title    = song.get("title") or "Unknown Title"
        metadata = song.get("metadata") or {}
        lyrics   = metadata.get("prompt") or metadata.get("lyrics") or ""
        tags_str = metadata.get("tags") or ""
        created  = (song.get("created_at") or "")[:10]  # YYYY-MM-DD

        tags["TIT2"] = TIT2(encoding=3, text=title)
        tags["TPE1"] = TPE1(encoding=3, text="Suno AI")
        if lyrics:
            tags["USLT"] = USLT(encoding=3, lang="eng", desc="", text=lyrics)
        if tags_str:
            tags["TCON"] = TCON(encoding=3, text=tags_str)
        if created:
            tags["TDRC"] = TDRC(encoding=3, text=created)
        tags["COMM"] = COMM(
            encoding=3, lang="eng", desc="",
            text=f"Generated by Suno AI | id={song.get('id', '')}"
        )
        if cover_data:
            tags["APIC"] = APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=cover_data,
            )

        tags.save(str(filepath), v2_version=3)
    except Exception as exc:
        log.warning("Could not embed metadata in %s: %s", filepath.name, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Single-song download
# ─────────────────────────────────────────────────────────────────────────────

def download_song(song: dict, out_dir: Path, prefer_wav: bool,
                  existing_ids: set, embed_meta: bool) -> tuple[str, bool, str]:
    """
    Download one song.

    Returns (song_id, success, message).
    """
    song_id = song.get("id", "unknown")
    title   = sanitize_filename(song.get("title") or song_id)

    # Choose audio URL
    audio_url = None
    if prefer_wav:
        audio_url = song.get("audio_url_wav") or song.get("audio_url")
    if not audio_url:
        audio_url = song.get("audio_url")

    if not audio_url:
        return song_id, False, "No audio URL available"

    ext      = ".wav" if (prefer_wav and "wav" in audio_url.lower()) else ".mp3"
    filename = f"{title}_{song_id[:8]}{ext}"
    filepath = out_dir / filename

    # Skip already-downloaded files
    if filepath.exists():
        return song_id, True, f"SKIP (exists): {filename}"

    # Also skip by ID if we already have it under a different name
    if song_id in existing_ids:
        return song_id, True, f"SKIP (id known): {song_id}"

    # Download audio
    try:
        r = requests.get(audio_url, stream=True, timeout=60)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0

        with open(filepath, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    downloaded += len(chunk)
    except Exception as exc:
        if filepath.exists():
            filepath.unlink(missing_ok=True)
        return song_id, False, f"Download error: {exc}"

    # Embed metadata (MP3 only)
    if embed_meta and ext == ".mp3":
        cover_data = None
        image_url  = song.get("image_url") or song.get("image_large_url")
        if image_url:
            try:
                cr = requests.get(image_url, timeout=15)
                if cr.ok:
                    cover_data = cr.content
            except Exception:
                pass
        embed_id3_metadata(filepath, song, cover_data)

    # Save sidecar JSON with full metadata
    json_path = filepath.with_suffix(".json")
    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(song, jf, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return song_id, True, f"OK: {filename}"


# ─────────────────────────────────────────────────────────────────────────────
# Batch download orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def download_all(songs: list[dict], out_dir: Path, prefer_wav: bool,
                 embed_meta: bool, workers: int):
    """Download all songs using a thread pool."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build set of already-downloaded IDs from existing JSON sidecars
    existing_ids: set[str] = set()
    for jf in out_dir.glob("*.json"):
        try:
            with open(jf) as f:
                d = json.load(f)
                if d.get("id"):
                    existing_ids.add(d["id"])
        except Exception:
            pass

    log.info("Starting download of %d songs (%d already on disk) …",
             len(songs), len(existing_ids))

    ok = skipped = failed = 0
    iterator = songs

    if TQDM_AVAILABLE:
        iterator = tqdm(songs, desc="Downloading", unit="song")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(download_song, song, out_dir, prefer_wav,
                        existing_ids, embed_meta): song
            for song in songs
        }
        for future in as_completed(futures):
            song_id, success, msg = future.result()
            if "SKIP" in msg:
                skipped += 1
                log.debug("%s", msg)
            elif success:
                ok += 1
                log.info("%s", msg)
            else:
                failed += 1
                log.warning("FAIL [%s]: %s", song_id, msg)

    log.info("─" * 60)
    log.info("Done.  Downloaded: %d  |  Skipped: %d  |  Failed: %d",
             ok, skipped, failed)
    log.info("Files saved to: %s", out_dir.resolve())


# ─────────────────────────────────────────────────────────────────────────────
# Token helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_token(args_token: Optional[str]) -> str:
    """
    Resolve the Suno JWT token from (in priority order):
      1. --token CLI argument
      2. SUNO_TOKEN environment variable
      3. .suno_token file in the current directory
    """
    if args_token:
        return args_token.strip()

    env_token = os.environ.get("SUNO_TOKEN", "").strip()
    if env_token:
        log.info("Using token from SUNO_TOKEN environment variable.")
        return env_token

    token_file = Path(".suno_token")
    if token_file.exists():
        token = token_file.read_text().strip()
        if token:
            log.info("Using token from .suno_token file.")
            return token

    log.error(
        "No token found.\n"
        "  Provide it via --token, the SUNO_TOKEN env var, or a .suno_token file.\n"
        "  See README.md for how to obtain your token."
    )
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Automatically download all your Suno AI songs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 suno_downloader.py --token eyJ...
  SUNO_TOKEN=eyJ... python3 suno_downloader.py --output ~/Music/Suno
  python3 suno_downloader.py --wav --no-metadata --workers 8
        """,
    )
    p.add_argument("--token",       metavar="JWT",  help="Suno Bearer token (JWT)")
    p.add_argument("--output",      metavar="DIR",  default="suno_songs",
                   help="Output directory (default: ./suno_songs)")
    p.add_argument("--wav",         action="store_true",
                   help="Prefer WAV over MP3 when available")
    p.add_argument("--no-metadata", action="store_true",
                   help="Skip embedding ID3 metadata into MP3 files")
    p.add_argument("--workers",     type=int, default=MAX_WORKERS,
                   help=f"Parallel download threads (default: {MAX_WORKERS})")
    p.add_argument("--max-pages",   type=int, default=0,
                   help="Stop after N pages (0 = unlimited)")
    p.add_argument("--list-only",   action="store_true",
                   help="Only list songs, do not download")
    p.add_argument("--debug",       action="store_true",
                   help="Enable verbose debug logging")
    return p.parse_args()


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    token    = load_token(args.token)
    out_dir  = Path(args.output)
    songs    = fetch_all_songs(token, max_pages=args.max_pages)

    if not songs:
        log.warning("No songs found in your library.")
        return

    if args.list_only:
        print(f"\n{'ID':<38}  {'Title'}")
        print("─" * 80)
        for s in songs:
            print(f"{s.get('id', ''):<38}  {s.get('title', 'Untitled')}")
        print(f"\nTotal: {len(songs)} songs")
        return

    download_all(
        songs     = songs,
        out_dir   = out_dir,
        prefer_wav= args.wav,
        embed_meta= not args.no_metadata,
        workers   = args.workers,
    )


if __name__ == "__main__":
    main()
