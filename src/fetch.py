"""Data fetchers: macro events, earnings, market movers."""
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

PRIORITY_COUNTRIES = {'US', 'EZ', 'DE', 'GB', 'CN', 'JP', 'LT'}

HIGH_IMPACT_KEYWORDS = [
    'CPI', 'PPI', 'PCE', 'GDP', 'Payroll', 'Unemployment', 'Jobless',
    'Fed', 'FOMC', 'Rate', 'ECB', 'Retail Sales', 'ISM', 'PMI',
    'Consumer Confidence', 'Housing', 'Industrial Production'
]


def _utc_to_vilnius(utc_str: str) -> str:
    """Convert '4:00 AM UTC' to 'HH:MM' Vilnius local time."""
    m = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)\s*UTC', utc_str, re.I)
    if not m:
        return utc_str
    h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == 'PM' and h != 12:
        h += 12
    if ap == 'AM' and h == 12:
        h = 0
    today = datetime.now(pytz.utc).replace(hour=h, minute=mn, second=0, microsecond=0)
    vilnius = today.astimezone(pytz.timezone('Europe/Vilnius'))
    return vilnius.strftime('%H:%M')


def fetch_macro_events(date_str: str) -> list:
    """Fetch macro economic events for a given date (YYYY-MM-DD)."""
    url = f"https://finance.yahoo.com/calendar/economic?day={date_str}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'lxml')
    table = soup.find('table')
    if not table:
        return []

    events = []
    for row in table.find_all('tr')[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cells) < 7:
            continue
        event_name, country, event_time, period, actual, expected, prior = cells[:7]
        if country not in PRIORITY_COUNTRIES:
            continue
        is_high_impact = any(kw.lower() in event_name.lower() for kw in HIGH_IMPACT_KEYWORDS)
        event_name_clean = event_name.replace('*', '').strip()
        events.append({
            'time_local': _utc_to_vilnius(event_time),
            'time_raw': event_time,
            'name': event_name_clean,
            'country': country,
            'period': period,
            'actual': actual if actual != '-' else None,
            'expected': expected if expected != '-' else None,
            'prior': prior if prior != '-' else None,
            'high_impact': is_high_impact,
        })
    return events


def fetch_earnings(date_str: str, min_market_cap_b: float = 10.0) -> list:
    """Fetch earnings calendar for date, filtered by minimum market cap (billions USD)."""
    url = f"https://finance.yahoo.com/calendar/earnings?day={date_str}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'lxml')
    table = soup.find('table')
    if not table:
        return []

    out = []
    for row in table.find_all('tr')[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cells) < 8:
            continue
        symbol, company, event_name, call_time, eps_est, reported_eps, surprise, mcap = cells[:8]
        mcap_b = _parse_market_cap(mcap)
        if mcap_b is None or mcap_b < min_market_cap_b:
            continue
        out.append({
            'symbol': symbol,
            'company': company,
            'call_time': call_time,
            'eps_est': eps_est if eps_est != '-' else None,
            'reported_eps': reported_eps if reported_eps != '-' else None,
            'surprise': surprise if surprise != '-' else None,
            'market_cap': mcap,
            'market_cap_b': mcap_b,
        })
    out.sort(key=lambda x: x['market_cap_b'], reverse=True)
    return out


def _parse_market_cap(s: str):
    if not s or s == '-':
        return None
    m = re.match(r'([\d.]+)([BTM])', s)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2)
    mult = {'T': 1000, 'B': 1, 'M': 0.001}
    return val * mult.get(unit, 0)


def fetch_finviz_calendar(date_str: str) -> list:
    """Fetch finviz economic calendar (additional US-focused source)."""
    r = requests.get("https://finviz.com/calendar.ashx", headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    today = datetime.strptime(date_str, '%Y-%m-%d').strftime('%a %b %d')

    events = []
    rows = soup.select('table.calendar tr')
    current_date = None
    for row in rows:
        date_cell = row.find('td', class_='calendar-date')
        if date_cell:
            current_date = date_cell.get_text(strip=True)
        if current_date != today:
            continue
        time_cell = row.find('td', class_='calendar-time')
        name_cell = row.find('td', class_='calendar-event')
        if time_cell and name_cell:
            events.append({
                'time': time_cell.get_text(strip=True),
                'name': name_cell.get_text(strip=True),
                'source': 'finviz',
            })
    return events


def fetch_premarket_movers(top_n: int = 5) -> dict:
    """Fetch top gainers and losers from Finviz (uses 'today' data)."""
    out = {'gainers': [], 'losers': []}
    for kind, url_suffix in [
        ('gainers', 'screener.ashx?v=111&s=ta_topgainers&o=-change'),
        ('losers', 'screener.ashx?v=111&s=ta_toplosers&o=change'),
    ]:
        try:
            r = requests.get(f"https://finviz.com/{url_suffix}", headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, 'lxml')
            rows = soup.select('table.screener_table tr')[1:top_n + 1]
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all('td')]
                if len(cells) >= 10:
                    out[kind].append({
                        'symbol': cells[1],
                        'company': cells[2][:30],
                        'price': cells[8],
                        'change': cells[9],
                    })
        except Exception as e:
            print(f"  warn: failed to fetch {kind}: {e}")
    return out


if __name__ == '__main__':
    today_str = datetime.now(pytz.timezone('Europe/Vilnius')).strftime('%Y-%m-%d')
    print(f"Testing fetchers for {today_str}\n")

    print("=== MACRO EVENTS ===")
    macro = fetch_macro_events(today_str)
    for e in macro[:10]:
        marker = '⚠' if e['high_impact'] else ' '
        print(f"  {marker} {e['time_local']} [{e['country']}] {e['name']}")

    print(f"\n=== EARNINGS (mcap >$10B) ===")
    earn = fetch_earnings(today_str)
    for e in earn[:8]:
        print(f"  {e['symbol']:<6} {e['company'][:30]:<30} {e['call_time']:<4} mcap: {e['market_cap']}")

    print(f"\n=== PRE-MARKET MOVERS ===")
    movers = fetch_premarket_movers()
    print("  Gainers:")
    for m in movers['gainers'][:3]:
        print(f"    {m['symbol']:<6} {m['change']:<8} {m['price']}")
    print("  Losers:")
    for m in movers['losers'][:3]:
        print(f"    {m['symbol']:<6} {m['change']:<8} {m['price']}")
