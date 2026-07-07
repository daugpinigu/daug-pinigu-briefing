"""Sentiment & macro indicators: Fear & Greed Index, CME FedWatch.

These are cheap-to-fetch macro/sentiment proxies that contextualize the brief.
"""
from __future__ import annotations

import json
import re
from typing import Optional
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'application/json, text/html',
}


def fetch_crypto_fear_greed() -> Optional[dict]:
    """Alternative.me Crypto Fear & Greed Index (free, no auth).

    Returns: {value: int, classification: str, prev_day, prev_week,
              prev_month, trend, label_lt}
    """
    try:
        r = requests.get(
            'https://api.alternative.me/fng/?limit=30',
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        data = r.json().get('data', [])
        if not data:
            return None
    except Exception as e:
        print(f"  warn: Fear & Greed fetch failed: {e}")
        return None

    def _g(i):
        return int(data[i]['value']) if i < len(data) else None

    today = _g(0)
    prev_day = _g(1)
    prev_week = _g(7)
    prev_month = _g(29) or _g(len(data) - 1)
    classification = data[0].get('value_classification', '')

    classification_lt = {
        'Extreme Fear': 'Ekstremali baimė',
        'Fear': 'Baimė',
        'Neutral': 'Neutralus',
        'Greed': 'Godumas',
        'Extreme Greed': 'Ekstremalus godumas',
    }.get(classification, classification)

    # Color gradient
    if today < 25:
        color = '#ff4444'
    elif today < 45:
        color = '#ff9b3a'
    elif today < 55:
        color = '#f4cc6b'
    elif today < 75:
        color = '#7ed87e'
    else:
        color = '#22cc44'

    delta_day = today - prev_day if prev_day is not None else 0
    delta_week = today - prev_week if prev_week is not None else 0

    # Trend label turi atsižvelgti į absoliutų lygį: +12 baimės zonoje yra
    # baimės atsitraukimas, ne euforija (2026-07-07: 15->27 buvo parodyta
    # kaip 'staigus euforijos kilimas', nors indeksas tebespausdino Baimė).
    if delta_week >= 10:
        trend = 'staigus euforijos kilimas' if today >= 55 else 'baimė sparčiai atsitraukia'
    elif delta_week >= 5:
        trend = 'sentimentas šiltesnis'
    elif delta_week <= -10:
        trend = 'staigus baimės kilimas' if today < 55 else 'godumas sparčiai vėsta'
    elif delta_week <= -5:
        trend = 'sentimentas šaltesnis'
    else:
        trend = 'stabilus'

    return {
        'value': today,
        'classification': classification,
        'classification_lt': classification_lt,
        'color': color,
        'prev_day': prev_day,
        'prev_week': prev_week,
        'prev_month': prev_month,
        'delta_day': delta_day,
        'delta_week': delta_week,
        'delta_month': today - prev_month if prev_month is not None else 0,
        'trend_text': trend,
        'history_30d': [_g(i) for i in range(min(30, len(data)))][::-1],
    }


def fetch_cme_fedwatch() -> Optional[dict]:
    """CME FedWatch implied Fed funds rate path.

    Free source: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
    Page renders via JS so we scrape the underlying JSON endpoint when available,
    and fall back to a text scrape of the public page.

    Returns: {meetings: [{date, current_implied_rate, probabilities: [...]}],
              fetched_at: iso}
    """
    # Try CME's public probabilities JSON (changes from time to time)
    endpoints = [
        'https://www.cmegroup.com/services/fed-watch-tool/probabilities',
        'https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G',  # Fed funds futures
    ]
    for url in endpoints:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200 and r.text and r.text.strip().startswith(('{', '[')):
                # Got JSON - try to parse meaningful data
                try:
                    data = r.json()
                    # If structure looks like FedWatch probabilities
                    if isinstance(data, dict) and ('meetings' in data or 'data' in data):
                        return _parse_cme_json(data)
                except Exception:
                    pass
        except Exception:
            continue

    # Fallback: scrape a public mirror that exposes the FedWatch summary
    try:
        r = requests.get(
            'https://www.investing.com/central-banks/fed-rate-monitor',
            headers=HEADERS, timeout=10,
        )
        if r.status_code == 200:
            return _parse_investing_fedwatch(r.text)
    except Exception as e:
        print(f"  warn: Investing FedWatch fallback failed: {e}")

    return None


def _parse_cme_json(data: dict) -> Optional[dict]:
    """Best-effort parse of CME JSON. Structure varies, defensive."""
    try:
        meetings = []
        raw = data.get('meetings') or data.get('data', {}).get('meetings') or []
        for m in raw[:4]:
            date = m.get('meetingDate') or m.get('date')
            current = m.get('targetRate') or m.get('current')
            probs = m.get('probabilities', [])
            meetings.append({
                'date': date,
                'current_rate': current,
                'probabilities': probs,
            })
        if meetings:
            return {
                'meetings': meetings,
                'source': 'CME',
                'fetched_at': datetime.utcnow().isoformat(),
            }
    except Exception:
        pass
    return None


def _parse_investing_fedwatch(html: str) -> Optional[dict]:
    """Investing.com Fed Rate Monitor scrape. Returns next 3-4 meeting probs."""
    soup = BeautifulSoup(html, 'lxml')
    meetings = []
    # Each meeting block contains a date and a list of rate scenarios with probs
    blocks = soup.select('.fedRateBlock, .meetingPanel, [data-meeting]')
    for blk in blocks[:4]:
        date_el = blk.select_one('.meetingDate, .date, h3')
        date_str = date_el.get_text(strip=True) if date_el else None
        scenarios = []
        for row in blk.select('tr, .rateRow'):
            cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th', 'div'])][:4]
            if len(cells) >= 2 and '%' in cells[-1]:
                scenarios.append({'rate': cells[0], 'prob': cells[-1]})
        if date_str and scenarios:
            meetings.append({
                'date': date_str,
                'scenarios': scenarios[:6],
            })

    if not meetings:
        return None
    return {
        'meetings': meetings,
        'source': 'Investing.com (FedWatch mirror)',
        'fetched_at': datetime.utcnow().isoformat(),
    }


def fetch_cme_fedwatch_simple() -> Optional[dict]:
    """Simpler FedWatch: derive cut/hold/hike probabilities from
    Fed funds futures via yfinance (ZQ contracts).

    Returns a summary of probabilities for the next FOMC meeting based on
    current Fed funds futures pricing implied rate vs. current Fed funds rate.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        # Current Fed funds upper bound (we hardcode from latest known FOMC dot)
        # As of 2026 H1: Fed funds target range 3.50% - 3.75% (upper 3.75%)
        # If reality has moved, manual_notes can override.
        current_target_upper = 3.75
        current_target_mid = 3.625

        # Get front-month Fed funds futures (closest expiry)
        ff = yf.Ticker('ZQ=F')
        info = ff.history(period='5d', interval='1d')
        if info.empty:
            return None
        last_price = float(info['Close'].iloc[-1])
        # ZQ contract: implied Fed funds rate = 100 - price
        implied_rate = 100 - last_price
        bias_bps = (implied_rate - current_target_mid) * 100  # basis points

        # Tikimybės tiesiai iš futures bias: pilnai įkainotas 25bp žingsnis
        # = 100%. Likutis eina į HOLD, o priešinga kryptis (cut, kai bias
        # vanagiškas) = 0. Ankstesnis hardcoded 18/65/17 spausdino fantominę
        # 18% cut tikimybę, kai rinka realiai kainojo hike uodegą
        # (2026-07-07: brief 65/18/17 vs realus FedWatch ~74 hold/26 hike/0 cut).
        step_frac = max(-1.0, min(1.0, bias_bps / 25.0))
        if step_frac >= 0:
            hike_prob = round(step_frac * 100)
            cut_prob = 0
        else:
            cut_prob = round(-step_frac * 100)
            hike_prob = 0
        hold_prob = 100 - hike_prob - cut_prob
        if bias_bps <= -18:
            implied_action = 'CUT'
        elif bias_bps <= -10:
            implied_action = 'lean CUT'
        elif bias_bps >= 18:
            implied_action = 'HIKE'
        elif bias_bps >= 10:
            implied_action = 'lean HIKE'
        else:
            implied_action = 'HOLD'

        return {
            'source': 'Fed funds futures (ZQ=F)',
            'fetched_at': datetime.utcnow().isoformat(),
            'current_target_range': f'{current_target_upper - 0.25:.2f}%-{current_target_upper:.2f}%',
            'implied_rate': round(implied_rate, 3),
            'bias_bps': round(bias_bps, 1),
            'implied_action': implied_action,
            'next_meeting_probs': {
                'cut_25bp': cut_prob,
                'hold': hold_prob,
                'hike_25bp': hike_prob,
            },
            'interpretation_lt': _fed_interpretation(implied_action, bias_bps),
        }
    except Exception as e:
        print(f"  warn: Fed funds futures fetch failed: {e}")
        return None


def _fed_interpretation(action: str, bias_bps: float) -> str:
    if 'CUT' in action.upper():
        return f"Rinka kainoja Fed cut (futures implied {abs(bias_bps):.0f}bp žemiau dabartinio target)"
    if 'HIKE' in action.upper():
        return f"Rinka kainoja Fed hike (futures implied {abs(bias_bps):.0f}bp aukščiau dabartinio target)"
    return f"Rinka kainoja Fed hold ({bias_bps:+.0f}bp nuokrypis nuo dabartinio target)"


if __name__ == '__main__':
    print('=== Fear & Greed ===')
    fg = fetch_crypto_fear_greed()
    if fg:
        print(f"  Value: {fg['value']} ({fg['classification_lt']})")
        print(f"  Day: {fg['delta_day']:+d}, Week: {fg['delta_week']:+d}, Trend: {fg['trend_text']}")
        print(f"  30d history: {fg['history_30d']}")
    else:
        print('  failed')

    print('=== Fed funds futures ===')
    fw = fetch_cme_fedwatch_simple()
    if fw:
        print(json.dumps(fw, indent=2, ensure_ascii=False))
    else:
        print('  failed')
