"""Fetch X.com posts locally and commit results for GH Actions to consume.

X binds sessions to IP/device fingerprint, so the cookies we extract from
Chrome don't authenticate from GitHub Actions' datacenter IPs. The fix:
run the X fetch from this machine (where your session is valid), write
the results to data/x_posts.json, and commit. The GH Actions daily run
then reads that file as a static input.

Usage:
    python scripts/x_refresh.py              # fetch + write JSON
    python scripts/x_refresh.py --commit     # also git add/commit/push
"""
import argparse
import base64
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'
OUTPUT = DATA_DIR / 'x_posts.json'
SESSION_FILE = ROOT / 'x_session.json'

sys.path.insert(0, str(ROOT / 'src'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true',
                    help='git add/commit/push after writing')
    ap.add_argument('--max', type=int, default=10,
                    help='max posts to keep (default 10)')
    args = ap.parse_args()

    if not SESSION_FILE.exists():
        print(f"No session at {SESSION_FILE}. Run: python scripts/x_login.py")
        sys.exit(1)

    # Load session and set env var for fetch_x_posts
    raw = SESSION_FILE.read_text()
    os.environ['X_SESSION_B64'] = base64.b64encode(raw.encode()).decode()

    from fetch import fetch_x_posts
    from watchlist import STOCKS

    print(f"Fetching X posts for {len(STOCKS)} watchlist tickers...")
    posts = fetch_x_posts(STOCKS, max_total=args.max, hours_window=24)
    print(f"  -> {len(posts)} posts")

    # Serialize datetime to ISO string for JSON
    serialized = []
    for p in posts:
        d = dict(p)
        if 'pub_dt' in d and d['pub_dt']:
            d['pub_dt'] = d['pub_dt'].isoformat()
        serialized.append(d)

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'posts': serialized,
    }
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    for p in posts[:5]:
        print(f"  [{p['ticker']}] @{p['handle']} ({p['likes']}♥) {p['text'][:80]}...")

    if args.commit:
        print("\nCommitting...")
        subprocess.run(['git', 'add', str(OUTPUT)], check=True, cwd=ROOT)
        diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
        if diff.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(['git', 'commit', '-m',
                        f'X posts refresh {datetime.now().strftime("%Y-%m-%d %H:%M")} [skip ci]'],
                       check=True, cwd=ROOT)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, cwd=ROOT)
        print("Pushed.")


if __name__ == '__main__':
    main()
