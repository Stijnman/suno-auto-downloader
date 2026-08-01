/**
 * get_token.js — Run this in your browser's DevTools console while on suno.com
 *
 * Steps:
 *   1. Open https://suno.com and log in.
 *   2. Press F12 → Console tab.
 *   3. Paste this entire script and press Enter.
 *   4. Your token will be printed and copied to the clipboard automatically.
 *   5. Paste it into the .suno_token file or use --token on the CLI.
 *
 * The token is a Clerk JWT that expires after ~60 minutes.
 * Re-run this script whenever you need a fresh token.
 */

(async () => {
  try {
    // Clerk stores the active session on window.__clerk_db_jwt or via the Clerk SDK
    let token = null;

    // Method 1: Clerk SDK (most reliable)
    if (window.Clerk && window.Clerk.session) {
      token = await window.Clerk.session.getToken();
    }

    // Method 2: Fallback — scan localStorage for a Clerk JWT
    if (!token) {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        const val = localStorage.getItem(key);
        if (val && val.startsWith("eyJ") && val.split(".").length === 3) {
          token = val;
          break;
        }
      }
    }

    if (!token) {
      console.error("Could not find a Suno token. Make sure you are logged in at suno.com.");
      return;
    }

    console.log("%c✅ Your Suno token:", "color: green; font-weight: bold");
    console.log(token);

    // Copy to clipboard
    await navigator.clipboard.writeText(token);
    console.log("%c📋 Token copied to clipboard!", "color: blue");
    console.log("\nPaste it into .suno_token or use:  python3 suno_downloader.py --token <paste>");
  } catch (err) {
    console.error("Error extracting token:", err);
  }
})();
