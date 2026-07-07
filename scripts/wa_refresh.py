"""Scrape today's messages from WhatsApp Channel(s) for the daily briefing.

Usage:
    python scripts/wa_refresh.py                  # scrape + save JSON
    python scripts/wa_refresh.py --commit         # also git commit+push
    python scripts/wa_refresh.py --visible        # non-headless for debugging

Requires: wa_login.py ran at least once (QR scanned, profile saved).
Output: data/whatsapp_channel.json (consumed by main.py pipeline).

Channels to scrape are configured in CHANNELS below.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / '.whatsapp-briefing-profile'
PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_DIR / 'data' / 'whatsapp_channel.json'
WA_URL = 'https://web.whatsapp.com'

# Channels to scrape. Add more as needed.
CHANNELS = [
    {'name': 'CaktusJxck', 'search': 'CaktusJxck'},
]


def _find(page, *selectors, timeout=5000):
    """Try multiple selectors, return first match."""
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout)
            if el:
                return el
        except Exception:
            continue
    return None


def _scrape_channel(page, channel_name: str) -> list:
    """Navigate to a channel and extract today's messages."""
    messages = []

    # Click Channels tab
    channels_tab = _find(
        page,
        'button[aria-label="Channels"]',
        'div[data-testid="tab-channels"]',
        'span[data-icon="channel"]',
        timeout=8000,
    )
    if channels_tab:
        channels_tab.click()
        page.wait_for_timeout(1500)

    # Search for channel
    search = _find(
        page,
        'div[data-testid="chat-list-search"]',
        'div[contenteditable="true"][data-tab]',
        'button[aria-label="Search"]',
        timeout=5000,
    )
    if search:
        search.click()
        page.wait_for_timeout(500)

    # Type channel name in search
    search_input = _find(
        page,
        'div[data-testid="search-input"] div[contenteditable="true"]',
        'div[title="Search input textbox"]',
        'div[contenteditable="true"][role="textbox"]',
        timeout=5000,
    )
    if search_input:
        search_input.fill('')
        search_input.type(channel_name, delay=80)
        page.wait_for_timeout(2000)

    # Click on the channel in search results
    # Look for a list item containing the channel name
    channel_el = page.query_selector(f'span[title="{channel_name}"]')
    if not channel_el:
        # Broader search
        results = page.query_selector_all('div[data-testid="cell-frame-container"]')
        for r in results:
            text = r.inner_text()
            if channel_name.lower() in text.lower():
                channel_el = r
                break
    if channel_el:
        channel_el.click()
        page.wait_for_timeout(2000)
    else:
        print(f"  warn: Channel '{channel_name}' not found in search results")
        return messages

    # Scroll up a few times to load more messages
    msg_panel = page.query_selector(
        'div[data-testid="conversation-panel-messages"]'
    ) or page.query_selector('div[role="application"]')
    if msg_panel:
        for _ in range(3):
            page.evaluate('''(el) => {
                el.scrollTop = Math.max(0, el.scrollTop - 2000);
            }''', msg_panel)
            page.wait_for_timeout(1000)
        # Scroll back to bottom
        page.evaluate('''(el) => { el.scrollTop = el.scrollHeight; }''', msg_panel)
        page.wait_for_timeout(500)

    # Extract messages - try multiple selector patterns
    msg_containers = page.query_selector_all(
        'div[data-testid="msg-container"]'
    )
    if not msg_containers:
        msg_containers = page.query_selector_all('div.message-in')
    if not msg_containers:
        # Fallback: look for any message-like divs
        msg_containers = page.query_selector_all(
            'div[class*="message"]'
        )

    today_str = datetime.now().strftime('%m/%d/%Y')
    now = datetime.now(timezone.utc)

    for mc in msg_containers:
        try:
            # Extract text
            text_el = mc.query_selector(
                'span.selectable-text'
            ) or mc.query_selector(
                'div[data-testid="msg-text"]'
            ) or mc.query_selector('span[dir]')

            if not text_el:
                continue
            text = text_el.inner_text().strip()
            if not text or len(text) < 5:
                continue

            # Extract time
            time_el = mc.query_selector(
                'span[data-testid="msg-time"]'
            ) or mc.query_selector(
                'span[data-testid="msg-meta"] span'
            )
            time_str = time_el.inner_text().strip() if time_el else ''

            # Parse time to UTC (assuming Vilnius timezone display)
            timestamp_utc = None
            if time_str and re.match(r'\d{1,2}:\d{2}', time_str):
                try:
                    vilnius_now = now.astimezone(
                        __import__('zoneinfo').ZoneInfo('Europe/Vilnius')
                    )
                    h, m = map(int, time_str.split(':'))
                    msg_local = vilnius_now.replace(hour=h, minute=m, second=0, microsecond=0)
                    timestamp_utc = msg_local.astimezone(timezone.utc).isoformat()
                except Exception:
                    pass

            messages.append({
                'text': text,
                'time': time_str,
                'timestamp_utc': timestamp_utc or now.isoformat(),
            })
        except Exception:
            continue

    # Deduplicate by text (WhatsApp sometimes renders duplicates)
    seen = set()
    unique = []
    for m in messages:
        key = m['text'][:80]
        if key not in seen:
            seen.add(key)
            unique.append(m)

    return unique


def main():
    visible = '--visible' in sys.argv
    commit = '--commit' in sys.argv

    if not PROFILE_DIR.exists():
        print(f"Error: No WhatsApp profile found at {PROFILE_DIR}")
        print("Run first: python scripts/wa_login.py")
        sys.exit(1)

    print(f"Opening WhatsApp Web ({'visible' if visible else 'headless'})...")
    all_messages = []

    with sync_playwright() as p:
        # channel='chrome': WhatsApp atmeta bundled Playwright Chromium
        # ("update Chrome" ekranas, 2026-07-07) - reikia tikro Google Chrome.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=not visible,
            channel='chrome',
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
            timezone_id='Europe/Vilnius',
            args=['--disable-blink-features=AutomationControlled'],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WA_URL, wait_until='domcontentloaded', timeout=30000)

        # Wait for WhatsApp to load
        loaded = _find(
            page,
            'div[aria-label="Chat list"]',
            'div[data-testid="chat-list"]',
            timeout=20000,
        )
        if not loaded:
            # Check for QR code (session expired)
            qr = page.query_selector('canvas[aria-label="Scan me!"]') or \
                 page.query_selector('div[data-testid="qrcode"]')
            if qr:
                print("Error: WhatsApp sesija pasibaige. Reikia perscanuoti QR.")
                print("Run: python scripts/wa_login.py")
                context.close()
                sys.exit(1)
            print("warn: WhatsApp Web neatsidare per 20s, bandau testi...")

        for ch in CHANNELS:
            print(f"  Scraping channel: {ch['name']}...")
            msgs = _scrape_channel(page, ch['search'])
            print(f"    -> {len(msgs)} messages")
            for m in msgs:
                m['channel'] = ch['name']
            all_messages.extend(msgs)

        context.close()

    # Write output
    output_data = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'channels': [ch['name'] for ch in CHANNELS],
        'messages': all_messages,
    }
    OUTPUT.write_text(json.dumps(output_data, indent=2, ensure_ascii=False))
    print(f"\nSaved {len(all_messages)} messages to {OUTPUT}")

    if commit:
        print("Committing to git...")
        subprocess.run(
            ['git', 'add', str(OUTPUT)],
            cwd=str(PROJECT_DIR),
        )
        subprocess.run(
            ['git', 'commit', '-m', f'WhatsApp channel refresh {datetime.now().strftime("%Y-%m-%d %H:%M")} [skip ci]'],
            cwd=str(PROJECT_DIR),
        )
        subprocess.run(
            ['git', 'push'],
            cwd=str(PROJECT_DIR),
        )
        print("Pushed to remote.")


if __name__ == '__main__':
    main()
