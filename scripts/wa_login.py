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
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={'width': 1280, 'height': 900},
            locale='en-US',
            timezone_id='Europe/Vilnius',
            args=['--disable-blink-features=AutomationControlled'],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(WA_URL, wait_until='domcontentloaded', timeout=30000)

        # Check if already logged in (chat list visible) or need QR scan
        try:
            page.wait_for_selector(
                'div[aria-label="Chat list"], div[data-testid="chat-list"]',
                timeout=8000,
            )
            print("\nJau prisijungta - sesija aktyvi, QR nereikia.")
        except Exception:
            print("\n" + "=" * 50)
            print("Nuskenuok QR koda su telefonu:")
            print("WhatsApp > Settings > Linked Devices > Link a Device")
            print("=" * 50)
            try:
                page.wait_for_selector(
                    'div[aria-label="Chat list"], div[data-testid="chat-list"]',
                    timeout=120000,
                )
                print("\nPrisijungta sekmingai!")
            except Exception:
                print("\nTimeout - nepavyko prisijungti per 2 min.")
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
        print("Galima uzdaryti langą.")
        print("\nKitas zingsnis: python scripts/wa_refresh.py")
        input("\nSpausk ENTER kad uzdaryti...")
        context.close()


if __name__ == '__main__':
    main()
