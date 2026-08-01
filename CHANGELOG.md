# Changelog

## [2.0.0] — 2026-08-01  (Free-Tier First)

### Focus
Optimized exclusively for free Suno accounts that need reliable bulk download after official download access became restricted.

### Added
- Versioning system (`VERSION` file + `--version`)
- Persistent state file (`.suno_state.json`) for true resume across runs
- Provenance `.txt` sidecar for every song (title, prompt, lyrics, model, timestamps)
- `--doctor` diagnostic command (auth, API reachability, dependencies)
- `--organize-month` option (YYYY-MM subfolders)
- Clear free-tier error messages (401 / 403 / rate-limit explanations)
- Better support for different token/cookie formats
- Adaptive retry + polite delays tuned for free accounts
- Safer default worker count (3 instead of 4)

### Changed
- Default behaviour prioritises free-tier reliability over paid features
- WAV option removed from primary path (often unavailable / restricted on free)
- Improved library pagination resilience against response shape changes
- Better sanitization and collision-resistant filenames

### Removed / De-prioritized
- No dependence on paid-only endpoints (stems, MIDI, advanced WAV conversion)
- No features that require Pro/Premier

### Backup
Original v1.0.0 files are preserved in Git history (previous commit).

---

## [1.0.0] — Original (Manus-generated)

- Basic full-library pagination
- Parallel MP3/WAV download
- ID3 metadata + JSON sidecars
- Simple skip-if-exists logic
- Token via CLI / env / `.suno_token`
