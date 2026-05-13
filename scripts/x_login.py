"""Capture an X.com session for the briefing.

Prefers extracting cookies from your existing Chrome/Brave/Safari (no login
needed — you're already signed in there). Falls back to manual Playwright
login if no browser cookies found.

Usage:
    python scripts/x_login.py

After it saves: base64-encode the file and add as REPO secret X_SESSION_B64:
    base64 -i x_session.json | pbcopy
    → paste into GitHub repo secrets
"""
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / 'x_session.json'

# X.com cookies the briefing needs. `auth_token` is the critical one.
REQUIRED = {'auth_token'}
NICE_TO_HAVE = {'ct0', 'twid', 'guest_id', 'kdt', 'gt'}


def from_browser_cookies():
    """Try to read X cookies from installed browsers."""
    try:
        import browser_cookie3
    except ImportError:
        print("browser_cookie3 not installed. Install: pip install browser-cookie3")
        return None

    browsers = [
        ('Chrome', browser_cookie3.chrome),
        ('Brave', browser_cookie3.brave),
        ('Edge', browser_cookie3.edge),
        ('Firefox', browser_cookie3.firefox),
        ('Safari', browser_cookie3.safari),
    ]
    for name, fn in browsers:
        try:
            cj = fn(domain_name='x.com')
            cookies = list(cj)
            if not cookies:
                # Try twitter.com domain too (X cookies sometimes still on old domain)
                cj2 = fn(domain_name='twitter.com')
                cookies = list(cj2)
            names = {c.name for c in cookies}
            if REQUIRED.issubset(names):
                print(f"✓ Found X session in {name} ({len(cookies)} cookies)")
                return cookies
            elif cookies:
                print(f"  {name}: {len(cookies)} cookies but missing required ({REQUIRED - names})")
        except Exception as e:
            print(f"  {name}: {type(e).__name__}: {str(e)[:80]}")
            continue
    return None


def cookies_to_playwright(cookies):
    """Convert browser_cookie3 cookies to Playwright storage_state format."""
    out_cookies = []
    for c in cookies:
        # Normalize domain
        domain = c.domain
        if not domain.startswith('.') and '.' in domain:
            # Ensure leading dot for cross-subdomain cookies
            if domain in ('x.com', 'twitter.com'):
                domain = '.' + domain
        out_cookies.append({
            'name': c.name,
            'value': c.value,
            'domain': domain,
            'path': c.path or '/',
            'expires': float(c.expires) if c.expires else -1.0,
            'httpOnly': bool(c._rest.get('HttpOnly') if hasattr(c, '_rest') else False),
            'secure': bool(c.secure),
            'sameSite': 'Lax',
        })
    return {'cookies': out_cookies, 'origins': []}


def manual_login():
    """Fallback: open Playwright, wait for user to sign in manually."""
    from playwright.sync_api import sync_playwright
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
        page.goto('https://x.com/login', wait_until='domcontentloaded')
        print()
        print("=" * 60)
        print("Sign in to x.com in the browser, then press ENTER here.")
        print("=" * 60)
        input()
        context.storage_state(path=str(OUTPUT))
        browser.close()
        return True


def main():
    print("Looking for existing X session in your installed browsers...")
    cookies = from_browser_cookies()
    if cookies:
        state = cookies_to_playwright(cookies)
        OUTPUT.write_text(json.dumps(state, indent=2))
        print(f"\n✓ Saved {OUTPUT} ({len(state['cookies'])} cookies, {OUTPUT.stat().st_size} bytes)")
    else:
        print()
        print("No usable X session found in installed browsers.")
        print("Falling back to manual login via Playwright...")
        print()
        try:
            manual_login()
            print(f"\n✓ Saved {OUTPUT}")
        except Exception as e:
            print(f"\nManual login failed: {e}")
            sys.exit(1)

    print()
    print("Next step — add to GitHub Secrets as X_SESSION_B64:")
    print(f"  base64 -i {OUTPUT} | pbcopy")
    print("  → paste into https://github.com/daugpinigu/daug-pinigu-briefing/settings/secrets/actions")
    print()
    print(f"File is in .gitignore — don't commit it.")


if __name__ == '__main__':
    main()
