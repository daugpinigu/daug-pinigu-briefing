"""One-time WhatsApp Web login - scan QR code, save persistent session.

Usage:
    python scripts/wa_login.py

Opens Chromium with WhatsApp Web. Scan the QR code with your phone
(WhatsApp > Settings > Linked Devices > Link a Device). Once connected,
the script saves the browser profile to ~/.whatsapp-briefing-profile/.

Subsequent runs of wa_refresh.py use this profile and skip QR.
The session lasts months unless you unlink the device on your phone.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / '.whatsapp-briefing-profile'
WA_URL = 'https://web.whatsapp.com'


def main():
    PROFILE_DIR.mkdir(exist_ok=True)
    print(f"Browser profile: {PROFILE_DIR}")
    print(f"Opening WhatsApp Web...")

    with sync_playwright() as p:
        # channel='chrome': WhatsApp atmeta bundled Playwright Chromium
        # ("update Chrome" ekranas, 2026-07-07) - reikia tikro Google Chrome.
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            channel='chrome',
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
            timezone_id='Europe/Vilnius',
            args=['--disable-blink-features=AutomationControlled'],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WA_URL, wait_until='domcontentloaded', timeout=30000)

        # Success = chat pane atsirado. Keli selektoriai, nes WhatsApp UI
        # keiciasi: #pane-side stabiliausias per metus.
        LOGGED_IN = ('#pane-side, div[aria-label="Chat list"], '
                     'div[data-testid="chat-list"]')

        page.bring_to_front()
        if page.query_selector(LOGGED_IN):
            print("\nJau prisijungta - sesija aktyvi, QR nereikia.")
        else:
            print("\n" + "=" * 50)
            print("Nuskenuok QR koda su telefonu (langas atsidares):")
            print("WhatsApp > Settings > Linked Devices > Link a Device")
            print("QR atsinaujina automatiskai. Laukiu iki 10 min.")
            print("=" * 50)
            ok = False
            last_state = ''
            for i in range(200):  # 200 * 3s = 10 min
                page.wait_for_timeout(3000)
                if page.query_selector(LOGGED_IN):
                    ok = True
                    break
                # QR pasensta ~1 min - jei atsirado reload overlay, spausk
                try:
                    reload_btn = page.query_selector(
                        'button[aria-label*="eload"], div[data-testid="refresh-large"], '
                        'span[data-icon="refresh-large"], button:has-text("reload")')
                    if reload_btn:
                        reload_btn.click()
                        print("  (QR atnaujintas)")
                except Exception:
                    pass
                # Login progreso logas - matosi, ar skenas ivyko
                try:
                    txt = page.evaluate("document.body.innerText")[:80].replace('\n', ' ')
                    if txt != last_state:
                        last_state = txt
                        print(f"  [{i*3}s] {txt}")
                except Exception:
                    pass
            if ok:
                print("\nPrisijungta sekmingai!")
            else:
                print("\nTimeout - nepavyko prisijungti per 10 min.")
                context.close()
                sys.exit(1)

        # Verify channels tab exists
        try:
            channels_btn = page.query_selector(
                'button[aria-label="Channels"], div[data-testid="tab-channels"]'
            )
            if channels_btn:
                print("Channels tab rastas.")
            else:
                print("warn: Channels tab nerastas - gali reiketi atnaujinti WhatsApp.")
        except Exception:
            pass

        print(f"\nSesija issaugota: {PROFILE_DIR}")
        print("\nKitas zingsnis: python scripts/wa_refresh.py")
        # Auto-close: sesija jau profilyje, ENTER nereikia (veikia ir be TTY,
        # pvz. paleidus foniniu rezimu). Trumpa pauze, kad WA baigtu sync'a.
        page.wait_for_timeout(8000)
        context.close()


if __name__ == '__main__':
    main()
