"""Telegram delivery."""
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / '.env')

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def send_photo(image_path: Path, caption: str = '') -> dict:
    """Try sendPhoto first; fall back to sendDocument if Telegram rejects (size/dimension)."""
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError('TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment')

    # Try as photo first (inline preview is nicer)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, 'rb') as f:
        files = {'photo': f}
        data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
        r = requests.post(url, files=files, data=data, timeout=30)

    if r.status_code == 200:
        return r.json()

    # Fall back to document (no dimension/ratio limits, up to 50MB)
    print(f"  sendPhoto failed ({r.status_code}: {r.text[:120]}), retrying as document...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(image_path, 'rb') as f:
        files = {'document': f}
        data = {'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'HTML'}
        r = requests.post(url, files=files, data=data, timeout=60)
    r.raise_for_status()
    return r.json()


def send_message(text: str) -> dict:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError('TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment')
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={
        'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'
    }, timeout=15)
    r.raise_for_status()
    return r.json()


if __name__ == '__main__':
    r = send_message('Test from send.py')
    print(r)
