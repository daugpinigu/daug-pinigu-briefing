"""Data fetchers: macro events, earnings, market movers."""
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import re
import yfinance as yf
import pandas as pd

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


def fetch_quotes(symbols: list) -> list:
    """Batch fetch latest quotes via yfinance. Returns list of dicts."""
    if not symbols:
        return []
    try:
        data = yf.download(symbols, period='5d', progress=False,
                           group_by='ticker', auto_adjust=False, threads=True)
    except Exception as e:
        print(f"  warn: yfinance batch fetch failed: {e}")
        return []

    out = []
    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = data
            else:
                df = data[sym]
            df = df.dropna(subset=['Close'])
            if len(df) < 2:
                continue
            last_close = float(df['Close'].iloc[-1])
            prev_close = float(df['Close'].iloc[-2])
            change_pct = ((last_close - prev_close) / prev_close) * 100
            out.append({
                'symbol': sym,
                'price': last_close,
                'change_pct': change_pct,
                'change_abs': last_close - prev_close,
            })
        except (KeyError, IndexError, ValueError):
            continue
    return out


def fetch_watchlist_movers(stocks: list, top_n: int = 5) -> dict:
    """Fetch quotes for watchlist, return top gainers and losers."""
    quotes = fetch_quotes(stocks)
    sorted_q = sorted(quotes, key=lambda x: x['change_pct'], reverse=True)
    return {
        'gainers': sorted_q[:top_n],
        'losers': sorted_q[-top_n:][::-1],
    }


def fetch_crypto(crypto_tuples: list) -> list:
    """Fetch crypto prices via CoinGecko. crypto_tuples is [(coingecko_id, display_symbol, name), ...]."""
    if not crypto_tuples:
        return []
    ids = ','.join(c[0] for c in crypto_tuples)
    url = (f"https://api.coingecko.com/api/v3/simple/price?ids={ids}"
           "&vs_currencies=usd&include_24hr_change=true&include_market_cap=true")
    try:
        r = requests.get(url, timeout=15, headers={'accept': 'application/json'})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  warn: CoinGecko fetch failed: {e}")
        return []

    out = []
    for cg_id, symbol, name in crypto_tuples:
        item = data.get(cg_id)
        if not item:
            continue
        out.append({
            'symbol': symbol,
            'name': name,
            'price': item.get('usd', 0),
            'change_pct': item.get('usd_24h_change', 0) or 0,
            'market_cap': item.get('usd_market_cap', 0),
        })
    return out


def fetch_index_snapshot(futures: list) -> list:
    """Fetch indices/futures/VIX snapshot. futures is [(symbol, display_name), ...]."""
    syms = [f[0] for f in futures]
    quotes = fetch_quotes(syms)
    name_map = dict(futures)
    out = []
    for q in quotes:
        out.append({
            'symbol': q['symbol'],
            'name': name_map.get(q['symbol'], q['symbol']),
            'price': q['price'],
            'change_pct': q['change_pct'],
        })
    return out


def fetch_iv_metrics(symbols: list) -> list:
    """Compute current ATM IV per ticker via yfinance options chain.

    For each symbol: averages ATM call/put IV from nearest expiration.
    Returns list sorted by IV desc - highest IV first (best premium-selling candidates).
    """
    import concurrent.futures

    def one(sym):
        try:
            t = yf.Ticker(sym)
            hist = t.history(period='1d')
            if hist.empty:
                return None
            spot = float(hist['Close'].iloc[-1])
            expirations = t.options
            if not expirations:
                return None
            # Find expiration ~30-45 DTE for stable IV
            from datetime import date
            today = date.today()
            target_exp = None
            for exp in expirations:
                exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
                dte = (exp_date - today).days
                if 25 <= dte <= 50:
                    target_exp = exp
                    break
            if not target_exp:
                target_exp = expirations[0]
            chain = t.option_chain(target_exp)
            calls = chain.calls
            puts = chain.puts
            if calls.empty or puts.empty:
                return None
            atm_call = calls.iloc[(calls['strike'] - spot).abs().argmin()]
            atm_put = puts.iloc[(puts['strike'] - spot).abs().argmin()]
            iv_call = float(atm_call.get('impliedVolatility', 0))
            iv_put = float(atm_put.get('impliedVolatility', 0))
            iv = (iv_call + iv_put) / 2 * 100
            if iv <= 0:
                return None
            return {
                'symbol': sym,
                'iv': iv,
                'spot': spot,
                'dte': (datetime.strptime(target_exp, '%Y-%m-%d').date() - today).days,
            }
        except Exception:
            return None

    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(one, symbols):
            if r:
                out.append(r)
    out.sort(key=lambda x: x['iv'], reverse=True)
    return out


def fetch_news(symbols: list, per_ticker: int = 1, max_total: int = 6) -> list:
    """Fetch latest news per ticker via yfinance. Deduplicates by title."""
    import concurrent.futures
    from datetime import datetime as dt

    def one(sym):
        try:
            t = yf.Ticker(sym)
            news = getattr(t, 'news', None) or []
            picked = []
            for n in news[:per_ticker * 3]:
                content = n.get('content') or n
                title = content.get('title') or n.get('title')
                if not title:
                    continue
                pub_ts = content.get('pubDate') or n.get('providerPublishTime')
                publisher = (content.get('provider') or {}).get('displayName') or n.get('publisher', '')
                link = (content.get('canonicalUrl') or {}).get('url') or n.get('link', '')
                if isinstance(pub_ts, str):
                    try:
                        pub_dt = dt.fromisoformat(pub_ts.replace('Z', '+00:00'))
                    except Exception:
                        pub_dt = None
                elif isinstance(pub_ts, (int, float)):
                    pub_dt = dt.fromtimestamp(pub_ts)
                else:
                    pub_dt = None
                picked.append({
                    'ticker': sym,
                    'title': title,
                    'publisher': publisher,
                    'link': link,
                    'pub_dt': pub_dt,
                })
                if len(picked) >= per_ticker:
                    break
            return picked
        except Exception:
            return []

    all_news = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for items in ex.map(one, symbols):
            all_news.extend(items)

    # Deduplicate by title (case-insensitive)
    seen = set()
    deduped = []
    for n in all_news:
        key = (n['title'] or '').lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(n)

    deduped.sort(key=lambda x: x['pub_dt'] or dt.min, reverse=True)
    return deduped[:max_total]


def fetch_premarket_change(symbols: list) -> list:
    """Get pre-market % change for symbols via yfinance prepost data."""
    if not symbols:
        return []
    try:
        data = yf.download(symbols, period='2d', interval='1d', prepost=True,
                           progress=False, group_by='ticker', auto_adjust=False, threads=True)
    except Exception:
        return []

    out = []
    for sym in symbols:
        try:
            df = data if len(symbols) == 1 else data[sym]
            df = df.dropna(subset=['Close'])
            if len(df) < 2:
                continue
            last = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            chg = (last - prev) / prev * 100
            out.append({'symbol': sym, 'price': last, 'change_pct': chg})
        except (KeyError, IndexError, ValueError):
            continue
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
