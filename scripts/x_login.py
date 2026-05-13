"""One-time X.com login helper.

Opens a visible browser, navigates to x.com login, waits for you to sign in
manually. When you're done (see your home feed), press ENTER in this terminal
to save the session cookies + localStorage to `x_session.json`.

Usage:
    python scripts/x_login.py

After it saves: base64-encode the file and add as REPO secret X_SESSION_B64:
    base64 -i x_session.json | pbcopy   # macOS, then paste into GH Secrets

Sessions typically last 30-90 days. Re-run this when X starts returning
login walls in the briefing run.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parent.parent / 'x_session.json'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
        )
        page = context.new_page()
        print("Opening x.com — sign in manually in the browser window.")
        page.goto('https://x.com/login', wait_until='domcontentloaded')

        print()
        print("=" * 60)
        print("ACTION REQUIRED:")
        print("  1. Sign in to x.com in the browser window")
        print("  2. Wait until you see your home feed")
        print("  3. Come back here and press ENTER to save the session")
        print("=" * 60)
        input()

        # Capture full storage state (cookies + localStorage)
        context.storage_state(path=str(OUTPUT))
        print(f"\nSaved session to: {OUTPUT}")
        print(f"Size: {OUTPUT.stat().st_size} bytes")
        print()
        print("Next step — add to GitHub Secrets as X_SESSION_B64:")
        print(f"  base64 -i {OUTPUT} | pbcopy")
        print("  → paste into https://github.com/daugpinigu/daug-pinigu-briefing/settings/secrets/actions")
        print()
        print("File is in .gitignore — never commit it directly.")
        browser.close()


if __name__ == '__main__':
    main()
