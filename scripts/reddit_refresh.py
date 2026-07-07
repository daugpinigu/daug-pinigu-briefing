"""Fetch Reddit discussions locally and commit for GH Actions to consume.

Reddit 2026: JSON endpoints (.json) grąžina 403 visiems ne-naršyklės
klientams (requests, curl_cffi su Chrome TLS - vis tiek 403; RSS veikia,
bet be score/komentarų). Veikiantis kelias: Playwright Chromium atsidaro
subreddit puslapį (praeina Fastly challenge, gauna cookies), tada .json
traukiamas in-page fetch'u - 200.

Mirrors the x_refresh.py pattern: fetch locally (home IP), write
data/reddit_posts.json (posts + top comments, so CI never touches
reddit.com), commit. GH Actions main.py falls back to this bridge when
its live fetch returns 0 posts.

Usage:
    python scripts/reddit_refresh.py             # fetch + write JSON
    python scripts/reddit_refresh.py --commit    # also git add/commit/push
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'
OUTPUT = DATA_DIR / 'reddit_posts.json'

SUBS = ['stocks', 'options', 'StockMarket']
MIN_SCORE = 100
MAX_TOTAL = 6
COMMENTS_PER_POST = 8

NOISE_TITLE_PATTERNS = [
    re.compile(p, re.I) for p in [
        r'^(daily|weekly|rate my)\s+',
        r'discussion thread',
        r'whats your',
        r"what'?s your",
        r'rate my portfolio',
        r'^yolo',
        r'mod\s*announcement',
    ]
]

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')


def _page_fetch_json(page, url):
    """Fetch a reddit .json URL from inside the page context (passes edge)."""
    out = page.evaluate(
        """async (url) => {
            const r = await fetch(url, {headers: {'Accept': 'application/json'}});
            return {status: r.status, body: await r.text()};
        }""", url)
    if out['status'] != 200:
        print(f"  fetch {url[:60]}... -> HTTP {out['status']}")
        return None
    try:
        return json.loads(out['body'])
    except Exception:
        return None


def fetch_posts():
    from playwright.sync_api import sync_playwright

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    all_posts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale='en-US')
        page = ctx.new_page()
        # Landing puslapis duoda Fastly/reddit cookies - be jo .json = 403
        page.goto('https://www.reddit.com/r/stocks/', timeout=30000)
        page.wait_for_timeout(2500)

        for sub in SUBS:
            for sort, t in (('hot', 'day'), ('top', 'day')):
                data = _page_fetch_json(
                    page, f'https://www.reddit.com/r/{sub}/{sort}.json?limit=15&t={t}')
                if not data:
                    continue
                for item in data.get('data', {}).get('children', []):
                    d = item.get('data', {})
                    title = d.get('title', '')
                    score = d.get('score', 0)
                    created = d.get('created_utc', 0)
                    if d.get('stickied') or score < MIN_SCORE:
                        continue
                    if any(pat.search(title) for pat in NOISE_TITLE_PATTERNS):
                        continue
                    pub_dt = (datetime.fromtimestamp(created, tz=timezone.utc)
                              if created else None)
                    if pub_dt and pub_dt < cutoff:
                        continue
                    all_posts.append({
                        'sub': sub,
                        'title': title,
                        'score': score,
                        'num_comments': d.get('num_comments', 0),
                        'pub_dt': pub_dt.isoformat() if pub_dt else None,
                        'link': f"https://reddit.com{d.get('permalink', '')}",
                        'permalink': d.get('permalink', ''),
                    })

        # Dedup pagal title + rikiavimas pagal score (kaip pipeline'e)
        seen, deduped = set(), []
        for post in all_posts:
            key = re.sub(r'\W+', '', post['title'].lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(post)
        deduped.sort(key=lambda x: x['score'], reverse=True)
        deduped = deduped[:MAX_TOTAL]

        # Komentarai kiekvienam post'ui - CI jų pats nepasiims (403)
        for post in deduped:
            perma = post.pop('permalink', '')
            comments = []
            if perma:
                cdata = _page_fetch_json(
                    page,
                    f"https://www.reddit.com{perma.rstrip('/')}.json?limit={COMMENTS_PER_POST * 2}")
                if isinstance(cdata, list) and len(cdata) > 1:
                    for c in cdata[1].get('data', {}).get('children', []):
                        if c.get('kind') != 't1':
                            continue
                        cd = c.get('data', {})
                        body = (cd.get('body') or '').strip()
                        if not body or body in ('[deleted]', '[removed]'):
                            continue
                        if cd.get('score', 0) < 5:
                            continue
                        comments.append(body[:500])
                        if len(comments) >= COMMENTS_PER_POST:
                            break
            post['comments'] = comments
            print(f"  [{post['sub']}] {post['score']}pts, {len(comments)} comments: {post['title'][:70]}")

        browser.close()
    return deduped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true',
                    help='git add/commit/push after writing')
    args = ap.parse_args()

    print("Fetching Reddit discussions (r/stocks, r/options, r/StockMarket) via Playwright...")
    posts = fetch_posts()
    print(f"  -> {len(posts)} posts")

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'posts': posts,
    }
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")

    if args.commit:
        print("\nCommitting...")
        subprocess.run(['git', 'add', str(OUTPUT)], check=True, cwd=ROOT)
        diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
        if diff.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(['git', 'commit', '-m',
                        f'Reddit refresh {datetime.now().strftime("%Y-%m-%d %H:%M")} [skip ci]'],
                       check=True, cwd=ROOT)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, cwd=ROOT)
        print("Pushed.")


if __name__ == '__main__':
    main()
