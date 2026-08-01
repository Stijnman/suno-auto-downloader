#!/usr/bin/env python3
"""
suno_downloader.py — Suno AI Free-Tier First Bulk Downloader
Version: 2.0.0

Optimized for free Suno accounts that need reliable offline access to their
generated songs after official download options became restricted.

Key improvements over v1.0.0:
  - Free-tier focused (no paid-only features required)
  - Better auth error messages for free accounts
  - Adaptive rate limiting + polite delays
  - Persistent state file for true resume
  - Provenance .txt + full JSON sidecar
  - Optional year-month organization
  - --doctor diagnostic command
  - Safer parallel downloads
  - Cleaner filtering foundation

Usage:
    python3 suno_downloader.py --token YOUR_TOKEN [options]
    python3 suno_downloader.py --doctor
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

# ── Optional dependencies ────────────────────────────────────────────────────
try:
    from mutagen.id3 import (
        ID3, ID3NoHeaderError, TIT2, TPE1, USLT, APIC, TCON, TDRC, COMM
    )
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Version & Constants
# ─────────────────────────────────────────────────────────────────────────────
__version__ = "2.0.0"

SUNO_API_BASE = "https://studio-api.prod.suno.com"
FEED_URL      = f"{SUNO_API_BASE}/api/feed/"
PAGE_SIZE     = 20
DEFAULT_WORKERS = 3          # slightly more conservative for free accounts
REQUEST_DELAY = 0.8          # polite delay between pages
RETRY_LIMIT   = 4
RETRY_DELAY   = 4.0
STATE_FILE    = ".suno_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("suno")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_filename(name: str, max_len: int = 100) -> str:
    """Remove filesystem-unsafe characters and truncate cleanly."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip("._- ")
    if len(name) > max_len:
        name = name[:max_len].rstrip("._- ")
    return name or "untitled"


def build_headers(token: str) -> dict:
    """Build request headers. Supports both Bearer JWT and raw cookie style."""
    token = token.strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Origin": "https://suno.com",
        "Referer": "https://suno.com/",
    }
    if token.lower().startswith("bearer "):
        headers["Authorization"] = token
    elif token.startswith("eyJ"):  # typical JWT
        headers["Authorization"] = f"Bearer {token}"
    else:
        # Treat as cookie value (more resilient for some free sessions)
        headers["Cookie"] = f"__client={token}" if not token.startswith("__client=") else token
        headers["Authorization"] = f"Bearer {token}"  # try both
    return headers


def http_get(url: str, headers: dict, params: dict | None = None,
             stream: bool = False, timeout: int = 35) -> requests.Response:
    """GET with retries, rate-limit awareness, and clear free-tier errors."""
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            r = requests.get(url, headers=headers, params=params,
                             stream=stream, timeout=timeout)

            if r.status_code == 401:
                log.error(
                    "Authentication failed (HTTP 401).\n"
                    "  → Your token/cookie expired or is invalid.\n"
                    "  → Free accounts: tokens last ~60 min. Re-run get_token.js.\n"
                    "  → Tip: use a fresh session from a logged-in browser."
                )
                sys.exit(1)

            if r.status_code == 403:
                log.error(
                    "Access forbidden (HTTP 403).\n"
                    "  → This often happens on free accounts when Suno restricts endpoints.\n"
                    "  → Try a fresh token. If it persists, the free tier may be further limited."
                )
                sys.exit(1)

            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 15 + attempt * 5))
                log.warning("Rate limited (429). Waiting %ds (attempt %d/%d) …",
                            wait, attempt, RETRY_LIMIT)
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r

        except requests.RequestException as exc:
            if attempt < RETRY_LIMIT:
                wait = RETRY_DELAY * attempt
                log.warning("Request failed (%s). Retry %d/%d in %.1fs …",
                            exc, attempt, RETRY_LIMIT, wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Unreachable")


# ─────────────────────────────────────────────────────────────────────────────
# State management (true resume)
# ─────────────────────────────────────────────────────────────────────────────

def load_state(out_dir: Path) -> dict:
    state_path = out_dir / STATE_FILE
    if state_path.exists():
        try:
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"downloaded_ids": [], "last_run": None, "version": __version__}


def save_state(out_dir: Path, state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["version"] = __version__
    state_path = out_dir / STATE_FILE
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        log.warning("Could not save state file: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Library fetching
# ─────────────────────────────────────────────────────────────────────────────

def fetch_all_songs(token: str, max_pages: int = 0) -> list[dict]:
    """
    Paginate the Suno feed and collect every song.
    Free-tier friendly: polite delays + clear logging.
    """
    headers = build_headers(token)
    songs: list[dict] = []
    page = 1
    seen_ids: set[str] = set()

    log.info("Scanning library (free-tier friendly mode) …")
    while True:
        if max_pages and page > max_pages:
            log.info("Reached --max-pages=%d limit.", max_pages)
            break

        url = f"{FEED_URL}?page={page}"
        log.debug("GET %s", url)
        try:
            r = http_get(url, headers)
        except Exception as exc:
            log.error("Failed to fetch page %d: %s", page, exc)
            break

        data = r.json()

        # Handle multiple possible response shapes
        if isinstance(data, list):
            clips = data
        elif isinstance(data, dict):
            clips = (
                data.get("clips")
                or data.get("songs")
                or data.get("items")
                or data.get("tracks")
                or data.get("results")
                or []
            )
        else:
            clips = []

        if not clips:
            log.info("No more songs on page %d. Scan complete.", page)
            break

        new_on_page = 0
        for item in clips:
            song = item.get("clip", item) if isinstance(item, dict) else item
            if not isinstance(song, dict):
                continue
            sid = song.get("id")
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                songs.append(song)
                new_on_page += 1

        log.info("Page %d → %d new songs (total: %d)", page, new_on_page, len(songs))
        page += 1
        time.sleep(REQUEST_DELAY)

    log.info("Library scan finished. %d unique songs found.", len(songs))
    return songs


# ─────────────────────────────────────────────────────────────────────────────
# Metadata & provenance
# ─────────────────────────────────────────────────────────────────────────────

def embed_id3_metadata(filepath: Path, song: dict, cover_data: Optional[bytes]) -> None:
    if not MUTAGEN_AVAILABLE:
        return
    try:
        try:
            tags = ID3(str(filepath))
        except ID3NoHeaderError:
            tags = ID3()

        title = song.get("title") or "Unknown Title"
        metadata = song.get("metadata") or {}
        lyrics = metadata.get("prompt") or metadata.get("lyrics") or metadata.get("gpt_description_prompt") or ""
        tags_str = metadata.get("tags") or ""
        created = (song.get("created_at") or "")[:10]

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
            text=f"Suno AI | id={song.get('id', '')} | free-tier archive"
        )
        if cover_data:
            tags["APIC"] = APIC(
                encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data
            )
        tags.save(str(filepath), v2_version=3)
    except Exception as exc:
        log.warning("Metadata embed failed for %s: %s", filepath.name, exc)


def write_provenance_txt(filepath: Path, song: dict) -> None:
    """Human-readable provenance file (important for free users)."""
    metadata = song.get("metadata") or {}
    lines = [
        f"Title: {song.get('title') or 'Untitled'}",
        f"ID: {song.get('id')}",
        f"Created: {song.get('created_at') or 'unknown'}",
        f"Model: {song.get('model_name') or metadata.get('model') or 'unknown'}",
        f"Status: {song.get('status') or 'unknown'}",
        "",
        "=== Tags / Style ===",
        metadata.get("tags") or "(none)",
        "",
        "=== Lyrics / Prompt ===",
        metadata.get("prompt") or metadata.get("lyrics") or metadata.get("gpt_description_prompt") or "(none)",
        "",
        f"Archived with suno_downloader v{__version__} (free-tier first)",
        f"Archived at: {datetime.now(timezone.utc).isoformat()}",
    ]
    txt_path = filepath.with_suffix(".txt")
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Single song download
# ─────────────────────────────────────────────────────────────────────────────

def download_song(
    song: dict,
    out_dir: Path,
    existing_ids: set[str],
    embed_meta: bool,
    organize_by_month: bool,
) -> tuple[str, bool, str]:
    song_id = song.get("id", "unknown")
    title = sanitize_filename(song.get("title") or song_id)

    audio_url = song.get("audio_url")
    if not audio_url:
        # Some free responses only expose the CDN link under different keys
        audio_url = (
            song.get("audio_url_mp3")
            or song.get("mp3_url")
            or (song.get("metadata") or {}).get("audio_url")
        )

    if not audio_url:
        return song_id, False, "No audio URL (common on heavily restricted free accounts)"

    # Decide target directory
    target_dir = out_dir
    if organize_by_month:
        created = song.get("created_at") or ""
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            month_folder = dt.strftime("%Y-%m")
            target_dir = out_dir / month_folder
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    filename = f"{title}_{song_id[:8]}.mp3"
    filepath = target_dir / filename

    if filepath.exists() or song_id in existing_ids:
        return song_id, True, f"SKIP: {filename}"

    # Download
    try:
        r = requests.get(audio_url, stream=True, timeout=90)
        if r.status_code != 200:
            return song_id, False, f"HTTP {r.status_code} on audio URL"
        with open(filepath, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
    except Exception as exc:
        if filepath.exists():
            filepath.unlink(missing_ok=True)
        return song_id, False, f"Download error: {exc}"

    # Cover + ID3
    cover_data = None
    if embed_meta:
        image_url = song.get("image_url") or song.get("image_large_url")
        if image_url:
            try:
                cr = requests.get(image_url, timeout=20)
                if cr.ok:
                    cover_data = cr.content
            except Exception:
                pass
        embed_id3_metadata(filepath, song, cover_data)

    # Sidecars
    json_path = filepath.with_suffix(".json")
    try:
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(song, jf, indent=2, ensure_ascii=False)
    except Exception:
        pass

    write_provenance_txt(filepath, song)

    return song_id, True, f"OK: {filename}"


# ─────────────────────────────────────────────────────────────────────────────
# Batch orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def download_all(
    songs: list[dict],
    out_dir: Path,
    embed_meta: bool,
    workers: int,
    organize_by_month: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(out_dir)
    existing_ids: set[str] = set(state.get("downloaded_ids", []))

    # Also scan existing JSON sidecars
    for jf in out_dir.rglob("*.json"):
        if jf.name == STATE_FILE:
            continue
        try:
            with open(jf, encoding="utf-8") as f:
                d = json.load(f)
                if d.get("id"):
                    existing_ids.add(d["id"])
        except Exception:
            pass

    to_download = [s for s in songs if s.get("id") not in existing_ids]
    log.info(
        "Ready: %d total songs | %d already archived | %d to download",
        len(songs), len(existing_ids), len(to_download)
    )

    if not to_download:
        log.info("Nothing new to download. Library is up to date.")
        return

    ok = skipped = failed = 0
    iterator = to_download
    if TQDM_AVAILABLE:
        iterator = tqdm(to_download, desc="Downloading", unit="song")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                download_song, song, out_dir, existing_ids,
                embed_meta, organize_by_month
            ): song
            for song in to_download
        }
        for future in as_completed(futures):
            song_id, success, msg = future.result()
            if "SKIP" in msg:
                skipped += 1
                log.debug(msg)
            elif success:
                ok += 1
                existing_ids.add(song_id)
                log.info(msg)
            else:
                failed += 1
                log.warning("FAIL [%s]: %s", song_id[:12], msg)

            # Periodic state save
            if (ok + failed) % 10 == 0:
                state["downloaded_ids"] = list(existing_ids)
                save_state(out_dir, state)

    state["downloaded_ids"] = list(existing_ids)
    save_state(out_dir, state)

    log.info("─" * 55)
    log.info("Finished.  Downloaded: %d  |  Skipped: %d  |  Failed: %d",
             ok, skipped, failed)
    log.info("Output: %s", out_dir.resolve())


# ─────────────────────────────────────────────────────────────────────────────
# Doctor command
# ─────────────────────────────────────────────────────────────────────────────

def run_doctor(token: Optional[str]) -> None:
    print(f"\n🩺  suno_downloader doctor  (v{__version__})")
    print("─" * 50)

    # Python / deps
    print(f"Python          : {sys.version.split()[0]}")
    print(f"requests        : {requests.__version__}")
    print(f"mutagen         : {'OK' if MUTAGEN_AVAILABLE else 'MISSING (pip install mutagen)'}")
    print(f"tqdm            : {'OK' if TQDM_AVAILABLE else 'MISSING (optional)'}")

    # Token
    if not token:
        token = load_token(None, exit_on_fail=False)
    if not token:
        print("Token           : ❌  No token found")
        print("\nFix: run get_token.js in browser console while logged into suno.com")
        return
    print(f"Token           : present ({token[:18]}…)")

    # API reachability
    headers = build_headers(token)
    print("API reachability: ", end="", flush=True)
    try:
        r = requests.get(f"{FEED_URL}?page=1", headers=headers, timeout=15)
        if r.status_code == 200:
            print("OK (200)")
            data = r.json()
            count = 0
            if isinstance(data, list):
                count = len(data)
            elif isinstance(data, dict):
                clips = data.get("clips") or data.get("songs") or data.get("items") or []
                count = len(clips)
            print(f"First page items: {count}")
        elif r.status_code in (401, 403):
            print(f"❌  {r.status_code} — token invalid or free-tier restricted")
        else:
            print(f"⚠️  HTTP {r.status_code}")
    except Exception as exc:
        print(f"❌  {exc}")

    print("\nFree-tier tip:")
    print("  Official downloads are limited on free accounts.")
    print("  This tool uses the library feed + CDN audio links that still work")
    print("  for most free users. Keep a fresh token and run regularly.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Token loading
# ─────────────────────────────────────────────────────────────────────────────

def load_token(args_token: Optional[str], exit_on_fail: bool = True) -> Optional[str]:
    if args_token:
        return args_token.strip()

    env_token = os.environ.get("SUNO_TOKEN", "").strip()
    if env_token:
        log.info("Using token from SUNO_TOKEN environment variable.")
        return env_token

    for candidate in [Path(".suno_token"), Path.home() / ".suno_token"]:
        if candidate.exists():
            token = candidate.read_text(encoding="utf-8").strip()
            if token:
                log.info("Using token from %s", candidate)
                return token

    if exit_on_fail:
        log.error(
            "No token found.\n"
            "  1. Open https://suno.com and log in\n"
            "  2. F12 → Console → paste get_token.js → Enter\n"
            "  3. Save the token to .suno_token or pass --token\n"
            "  Free accounts: tokens expire in ~60 minutes."
        )
        sys.exit(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=f"Suno Free-Tier First Bulk Downloader v{__version__}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 suno_downloader.py --token eyJ...
  python3 suno_downloader.py --output ~/Music/Suno --organize-month
  python3 suno_downloader.py --doctor
  python3 suno_downloader.py --list-only
        """,
    )
    p.add_argument("--token", metavar="JWT", help="Suno Bearer token / JWT")
    p.add_argument("--output", metavar="DIR", default="suno_songs",
                   help="Output directory (default: ./suno_songs)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help=f"Parallel downloads (default: {DEFAULT_WORKERS}, keep low on free accounts)")
    p.add_argument("--max-pages", type=int, default=0,
                   help="Limit pages scanned (0 = unlimited)")
    p.add_argument("--list-only", action="store_true",
                   help="Only list songs, do not download")
    p.add_argument("--no-metadata", action="store_true",
                   help="Skip ID3 embedding")
    p.add_argument("--organize-month", action="store_true",
                   help="Organize into YYYY-MM subfolders")
    p.add_argument("--doctor", action="store_true",
                   help="Run diagnostics (auth, API, deps)")
    p.add_argument("--debug", action="store_true",
                   help="Verbose debug logging")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args()


def main():
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.doctor:
        run_doctor(args.token)
        return

    token = load_token(args.token)
    out_dir = Path(args.output)

    songs = fetch_all_songs(token, max_pages=args.max_pages)

    if not songs:
        log.warning("No songs found. Possible causes:")
        log.warning("  • Empty library")
        log.warning("  • Token from free account with restricted feed access")
        log.warning("  • API shape changed — run --doctor")
        return

    if args.list_only:
        print(f"\n{'ID':<38}  {'Title'}")
        print("─" * 80)
        for s in songs:
            print(f"{s.get('id', ''):<38}  {s.get('title', 'Untitled')}")
        print(f"\nTotal: {len(songs)} songs")
        return

    download_all(
        songs=songs,
        out_dir=out_dir,
        embed_meta=not args.no_metadata,
        workers=args.workers,
        organize_by_month=args.organize_month,
    )


if __name__ == "__main__":
    main()
