"""Data fetchers: macro events, earnings, market movers."""
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
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
    'Consumer Confidence', 'Housing', 'Industrial Production', 'NFIB',
    'Empire', 'Philly', 'Michigan', 'NFP', 'Trade Balance',
]

EVENT_DESCRIPTIONS = [
    ('Core Inflation Rate', 'Core CPI (be food/energy) - "sticky" infliacijos signalas. Beat = hawkish Fed, bearish stocks/bonds'),
    ('Inflation Rate', 'Headline CPI - infliacijos pulsas. Viršija prognozę = hawkish Fed bias, blogai stocks/bonds'),
    ('Core CPI', 'CPI be food/energy - "sticky" infliacijos signalas. Beat = hawkish Fed'),
    ('Core PCE', 'Fed mėgstamiausia core infliacijos metrika - lemia rate decisions'),
    ('Core PPI', 'PPI be food/energy - švaresnis producer infliacijos rodiklis'),
    ('Fed Chair', 'Fed Chair nominacijos balsavimas - hawkish/dovish naujasis Chair\'as keičia rate path expectations'),
    ('FOMC', 'Fed sprendimas dėl palūkanų - tiesioginis impactas visiems asset\'ams'),
    ('Interest Rate Decision', 'Centrinio banko rate decision - tiesioginis market mover'),
    ('Fed Funds Rate', 'Fed funds rate decision - tiesioginis market mover'),
    ('Fed Interest Rate', 'Fed rate decision - tiesioginis market mover'),
    ('CPI', 'Vartotojų kainų indeksas - infliacijos pulsas. Beat = hawkish Fed, blogai stocks/bonds'),
    ('PPI', 'Producer kainos - leading indicator CPI, ankstesnis signalas apie infliacijos kryptį'),
    ('PCE Price', 'Fed mėgstamiausia infliacijos metrika - lemia rate decisions'),
    ('GDP Growth', 'Bendras ekonomikos augimas - virš consensus = stiprus augimas, gerai cyclicals'),
    ('GDP', 'Bendras ekonomikos augimas - virš consensus = stiprus augimas'),
    ('Non Farm Payrolls', 'NFP - pagrindinis JAV darbo rinkos indikatorius'),
    ('NFP', 'NFP - JAV darbo rinkos hot/cold check'),
    ('Payrolls', 'Darbo vietų kūrimas - stipriau nei tikėtasi vėluoja rate cuts'),
    ('Unemployment Rate', 'Nedarbo lygis - Fed dual mandate, aukštesnis = dovish bias'),
    ('Initial Jobless Claims', 'Savaitinės bedarbystės paraiškos - real-time darbo rinkos signalas'),
    ('Continuing Jobless', 'Continuing jobless claims - struktūrinė darbo rinkos sveikata'),
    ('Jobless', 'Bedarbystės paraiškos - leading darbo rinkos indikatorius'),
    ('ECB', 'ECB sprendimas - EUR ir europinių stocks pagrindinis driver\'is'),
    ('Retail Sales', 'Vartotojų išlaidos - GDP komponentas, US ekonomikos sveikatos check'),
    ('ISM Manufacturing', 'Pramonės aktyvumas - >50 = ekspansija, <50 = kontrakcija'),
    ('ISM Services', 'Paslaugų sektorius - >50 = ekspansija, leading economic indicator'),
    ('ISM', 'Verslo aktyvumas - >50 = ekspansija, <50 = kontrakcija'),
    ('S&P Global PMI', 'PMI - >50 = ekspansija, leading economic indicator'),
    ('Manufacturing PMI', 'Pramonės PMI - leading ekonomikos indicator'),
    ('Services PMI', 'Paslaugų PMI - leading ekonomikos indicator'),
    ('PMI', 'Business activity - >50 = ekspansija'),
    ('Consumer Confidence', 'Vartotojų pasitikėjimas - retail spending predictor'),
    ('Consumer Sentiment', 'Vartotojų nuotaikos - leading vartotojų behavior\'ui'),
    ('Michigan', 'UMich vartotojų pasitikėjimas + 5y infliacijos lūkesčiai'),
    ('Housing Starts', 'Naujos statybos - rate-sensitive, leading housing data'),
    ('Building Permits', 'Statybų leidimai - 6-12 mėn forward economic activity signal'),
    ('Existing Home Sales', 'Egzistuojančių namų pardavimai - housing rinkos pulsas'),
    ('New Home Sales', 'Naujų namų pardavimai - rate-sensitive cyclical indicator'),
    ('Industrial Production', 'Pramonės gamyba - cyclical sectorių driver\'is'),
    ('NFIB', 'Small business optimism - SMB sentimentas, leading employment signal'),
    ('Trade Balance', 'Eksportas - importas, USD ir cyclical pramonėms svarbus'),
    ('Empire State', 'NY Fed regional manufacturing - leading ISM indikatorius'),
    ('Philadelphia Fed', 'Philly Fed manufacturing - leading ISM indikatorius'),
    ('Producer Price', 'Producer kainos - leading CPI signal'),
    ('HICP', 'EZ harmonizuotas CPI - ECB watching metric'),
    ('Fed', 'Fed event - hawkish/dovish tonas, market mover'),
]


def get_event_description(event_name: str) -> str:
    """Match event name to description by keyword. First match wins (specific first)."""
    name_lower = event_name.lower()
    for keyword, desc in EVENT_DESCRIPTIONS:
        if keyword.lower() in name_lower:
            return desc
    return ''

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


FF_COUNTRY_MAP = {
    'USD': 'US', 'EUR': 'EZ', 'GBP': 'GB', 'JPY': 'JP', 'CNY': 'CN',
    'CAD': 'CA', 'AUD': 'AU', 'CHF': 'CH', 'NZD': 'NZ',
}

PRIORITY_CCY = {'USD'}
SECONDARY_CCY_HIGH_ONLY = {'EUR'}


def _classify_beat_miss(actual_str, expected_str):
    if not actual_str or not expected_str:
        return None
    try:
        a = float(re.sub(r'[^\d.\-]', '', actual_str))
        e = float(re.sub(r'[^\d.\-]', '', expected_str))
    except (ValueError, TypeError):
        return None
    if a > e:
        return 'beat'
    if a < e:
        return 'miss'
    return 'inline'


def _fetch_macro_yahoo_fallback(date_str: str) -> list:
    """Yahoo fallback for macro events, US-only filter."""
    url = f"https://finance.yahoo.com/calendar/economic?day={date_str}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')
        table = soup.find('table')
        if not table:
            return []
        events = []
        for row in table.find_all('tr')[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all('td')]
            if len(cells) < 7 or cells[1] != 'US':
                continue
            name = cells[0].replace('*', '').strip()
            is_high = any(kw.lower() in name.lower() for kw in HIGH_IMPACT_KEYWORDS)
            actual = cells[4] if cells[4] != '-' else None
            forecast = cells[5] if cells[5] != '-' else None
            prior = cells[6] if cells[6] != '-' else None
            events.append({
                'time_local': _utc_to_vilnius(cells[2]),
                'time_raw': cells[2],
                'name': name,
                'country': 'US',
                'period': '',
                'actual': actual,
                'expected': forecast,
                'prior': prior,
                'high_impact': is_high,
                'impact': 'High' if is_high else 'Medium',
                'description': get_event_description(name),
                'beat_miss': _classify_beat_miss(actual, forecast),
            })
        return events
    except Exception:
        return []


def _load_ff_json_cached(max_age_hours: int = 6):
    """Load ForexFactory weekly JSON, cached on disk to avoid rate limits."""
    import json
    import tempfile
    import time
    cache_path = Path(tempfile.gettempdir()) / 'ff_calendar_cache.json'
    if cache_path.exists():
        age_h = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_h < max_age_hours:
            try:
                return json.loads(cache_path.read_text())
            except Exception:
                pass
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    cache_path.write_text(json.dumps(data))
    return data


PERIOD_SUFFIX_RE = re.compile(
    r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|Q[1-4])\b\s*$',
    re.IGNORECASE,
)


def _strip_period_suffix(name: str) -> str:
    """Remove trailing period markers like 'APR', 'MAR', 'Q1' from event names."""
    return PERIOD_SUFFIX_RE.sub('', name).strip()


def fetch_macro_events_tradingeconomics(date_str: str) -> list:
    """Primary macro source. Scrapes TradingEconomics calendar with actuals.

    Returns US (importance 3) events with actual/consensus/previous when released.
    Time on TE is UTC, converted to Vilnius local.
    """
    from datetime import datetime as dt
    url = "https://tradingeconomics.com/calendar?importance=3&country=united%20states"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  warn: TradingEconomics fetch failed: {e}")
        return []

    soup = BeautifulSoup(r.text, 'lxml')
    table = soup.find('table', class_='table')
    if not table:
        return []

    target_dt = datetime.strptime(date_str, '%Y-%m-%d')
    target_day_str = target_dt.strftime('%A %B %-d %Y')

    events = []
    current_date_match = False
    for row in table.find_all('tr'):
        cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
        if not cells:
            continue
        if len(cells) > 0 and any(weekday in cells[0] for weekday in
                                   ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']):
            current_date_match = (cells[0] == target_day_str)
            continue
        if not current_date_match or len(cells) < 9:
            continue
        time_utc = cells[0]
        country = cells[1]
        if country != 'US':
            continue
        event_raw = cells[4] if len(cells) >= 5 else ''
        event_name = _strip_period_suffix(event_raw)
        actual = cells[5] if len(cells) >= 6 and cells[5] else None
        previous = cells[6] if len(cells) >= 7 and cells[6] else None
        consensus = cells[7] if len(cells) >= 8 and cells[7] else None
        forecast = cells[8] if len(cells) >= 9 and cells[8] else None

        try:
            t_naive = datetime.strptime(time_utc, '%I:%M %p')
            t_utc = target_dt.replace(hour=t_naive.hour, minute=t_naive.minute, tzinfo=pytz.utc)
            time_local = t_utc.astimezone(pytz.timezone('Europe/Vilnius')).strftime('%H:%M')
        except Exception:
            time_local = time_utc

        expected = consensus or forecast
        beat_miss = _classify_beat_miss(actual, expected)

        events.append({
            'time_local': time_local,
            'time_raw': time_utc,
            'name': event_name,
            'country': 'US',
            'period': '',
            'actual': actual,
            'expected': expected,
            'prior': previous,
            'high_impact': True,
            'impact': 'High',
            'description': get_event_description(event_name),
            'beat_miss': beat_miss,
        })

    return events


def fetch_macro_events(date_str: str) -> list:
    """Fetch macro economic events. Primary: TradingEconomics (has actuals).

    Fallbacks: ForexFactory JSON (forecasts only), then Yahoo. Merges
    so we get actuals from TE plus any extra events from FF.
    """
    from datetime import datetime as dt

    te_events = fetch_macro_events_tradingeconomics(date_str)
    te_names = {(e['name'].lower(), e['time_local']) for e in te_events}

    # Augment with ForexFactory events that TE doesn't have (e.g., Fed speeches)
    try:
        all_events = _load_ff_json_cached()
    except Exception as e:
        print(f"  warn: ForexFactory fetch failed: {e}")
        if te_events:
            return te_events
        return _fetch_macro_yahoo_fallback(date_str)

    def _topic_keys(name: str) -> set:
        """Extract topic keywords for cross-source dedup (CPI == Inflation Rate, etc.)."""
        n = name.lower()
        topics = set()
        if 'cpi' in n or 'inflation' in n:
            topics.add('cpi')
            if 'core' in n:
                topics.add('core_cpi')
            if 'm/m' in n or 'mom' in n or 'monthly' in n:
                topics.add('cpi_m')
            if 'y/y' in n or 'yoy' in n or 'annual' in n:
                topics.add('cpi_y')
        if 'ppi' in n or 'producer pric' in n:
            topics.add('ppi')
        if 'pce' in n:
            topics.add('pce')
        if 'payroll' in n or 'nfp' in n or 'non-farm' in n:
            topics.add('payrolls')
        if 'unemploy' in n:
            topics.add('unemployment')
        if 'jobless' in n:
            topics.add('jobless')
        if 'fomc' in n or 'fed funds' in n:
            topics.add('fomc')
        if 'fed chair' in n:
            topics.add('fed_chair')
        if 'retail sales' in n:
            topics.add('retail')
        if 'gdp' in n:
            topics.add('gdp')
        if 'ism' in n:
            topics.add('ism')
        if 'pmi' in n:
            topics.add('pmi')
        return topics

    te_signatures = {(t, frozenset(_topic_keys(e['name']))) for e in te_events for t in [e['time_local']]}

    merged = list(te_events)
    for ev in all_events:
        date_iso = ev.get('date', '')
        if not date_iso.startswith(date_str):
            continue
        ccy = ev.get('country', '')
        impact = ev.get('impact', 'Low')

        if ccy in PRIORITY_CCY:
            if impact not in ('High', 'Medium'):
                continue
        elif ccy in SECONDARY_CCY_HIGH_ONLY:
            if impact != 'High':
                continue
        else:
            continue

        try:
            event_dt = dt.fromisoformat(date_iso)
            event_utc = event_dt.astimezone(pytz.utc)
            event_vilnius = event_utc.astimezone(pytz.timezone('Europe/Vilnius'))
            time_local = event_vilnius.strftime('%H:%M')
        except Exception:
            time_local = '-'

        title = ev.get('title', '')
        ff_topics = _topic_keys(title)
        is_dup = any(
            t == time_local and (ff_topics & te_topics)
            for t, te_topics in te_signatures
        )
        if is_dup:
            continue

        forecast = ev.get('forecast') or None
        previous = ev.get('previous') or None
        actual = ev.get('actual') or None
        if forecast == '':
            forecast = None
        if previous == '':
            previous = None
        if actual == '':
            actual = None

        beat_miss = _classify_beat_miss(actual, forecast)
        merged.append({
            'time_local': time_local,
            'time_raw': date_iso,
            'name': title,
            'country': FF_COUNTRY_MAP.get(ccy, ccy),
            'period': '',
            'actual': actual,
            'expected': forecast,
            'prior': previous,
            'high_impact': impact == 'High',
            'impact': impact,
            'description': get_event_description(title),
            'beat_miss': beat_miss,
        })
    merged.sort(key=lambda e: e['time_local'])
    return merged


def fetch_earnings(date_str: str, min_market_cap_b: float = 500.0,
                   watchlist_symbols: list = None) -> list:
    """Fetch earnings calendar. Keep if mcap >= min_market_cap_b OR symbol in watchlist."""
    watchlist_set = set(watchlist_symbols or [])
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
        in_watchlist = symbol in watchlist_set
        passes_mcap = mcap_b is not None and mcap_b >= min_market_cap_b
        if not (in_watchlist or passes_mcap):
            continue
        out.append({
            'symbol': symbol,
            'company': company,
            'call_time': call_time,
            'eps_est': eps_est if eps_est != '-' else None,
            'reported_eps': reported_eps if reported_eps != '-' else None,
            'surprise': surprise if surprise != '-' else None,
            'market_cap': mcap,
            'market_cap_b': mcap_b or 0,
            'in_watchlist': in_watchlist,
        })
    out.sort(key=lambda x: (not x['in_watchlist'], -x['market_cap_b']))
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


NEWS_NOISE_PATTERNS = [
    re.compile(p, re.I) for p in [
        r'price\s+target',
        r'price\s+prediction',
        r'\d+%?\s+upside',
        r'(should|could)\s+(buy|invest|own)',
        r'analyst.*(?:raises|lowers|cuts|hikes).*target',
        r'\b(buy|sell)\s+(now|today)\b',
        r'top\s+\d+\s+stocks?',
        r'best\s+stocks?\s+to',
        r'\d+\s+halo\s+stocks',
        r'simply\s+wall',
        r'\d+\s+reasons?\s+to',
        r'why\s+(invest|own|buy)',
        r'(reasons?|signs?)\s+(?:to\s+)?(buy|sell)',
        r'flavor of the day',
        r'reduced their stake by 100%',  # Often misleading - small insider, full sale
        r'\bclass\s+action',  # Law firm spam
        r'reminds investors',
        r'investor\s+rights',
        r'price\s+forecast',
        r'penny stocks?',
        r'best\s+\d+\s+(?:cheap|small)',
        r'fool\.com',
    ]
]

NEWS_BOOST_PATTERNS = [
    re.compile(p, re.I) for p in [
        r'\b(?:drops?|falls?|plunges?|tumbles?|sinks?)\s+\d+',
        r'\b(?:surges?|soars?|jumps?|spikes?|rallies?|skyrockets?)\s+\d+',
        r'\b(?:climbs?|gains?|rises?)\s+\d+%',
        r'\b(?:slumps?|slides?|crashes?)\s+\d+',
        r'(?:beats?|tops?|misses?|trails?)\s+(?:estimates?|expectations?|forecast)',
        r'(?:reports?|reported|posts?)\s+(?:Q\d|quarterly|earnings)',
        r'(?:raises?|lowers?|cuts?)\s+(?:guidance|outlook|forecast)',
        r'(?:acquires?|acquisition|to\s+acquire|merger\s+with|buys?\s+\w+\s+for)',
        r'(?:lawsuit|sued|charged|FTC|DOJ|SEC\s+(?:probe|investigation))',
        r'(?:downgrade|upgrade)\s+to\s+(?:buy|sell|hold|overweight|underweight)',
        r'(?:layoffs?|fires?|cuts?)\s+\d+',
        r'(?:CEO|CFO|COO).*(?:steps?\s+down|fired|resigns?|appointed?|named|out)',
        r'(?:approves?|approved|rejects?|rejection).*FDA',
        r'\bguidance\b',
        r'\b(?:warning|cuts|slashes)\b',
        r'\b(?:beats?|misses?)\b.*(?:Q\d|earnings)',
        r'\b(?:hires?|hired|joins?)\b.*\b(?:CEO|CFO|board)',
        r'(?:data\s+center|AI\s+(?:deal|contract|partnership))',
        r'(?:bankruptcy|chapter\s+11|delisting)',
        r'(?:Tesla|Apple|Nvidia|Microsoft|Google|Meta|Amazon|Anthropic|OpenAI).*(?:announces?|launches?|unveils?)',
        r'(?:tariffs?|trade\s+war|sanctions?)',
        r'(?:Fed|FOMC|Powell).*(?:hikes?|cuts?|holds?|signals?)',
    ]
]

NEWS_BLOCKED_PUBLISHERS = {
    'simply wall st.', 'simply wall st', 'motley fool', 'the motley fool',
    '247 wall st.', '24/7 wall st.', '24/7 wall st', 'yahoo finance video',
    'investorplace', 'tipranks', 'gurufocus', 'tradingview',
}

NEWS_GOOD_PUBLISHERS_BOOST = {
    'bloomberg', 'reuters', 'wsj', 'wall street journal', 'financial times',
    'ft', 'cnbc', 'marketwatch', 'barron\'s', 'barrons', 'forbes',
    'business insider', 'the information', 'axios', 'semafor',
}


def _score_headline(title: str, publisher: str) -> int:
    """Score a news headline. Positive = quality catalyst, negative = noise."""
    if not title:
        return -10
    score = 0
    pub_l = (publisher or '').lower().strip()
    if pub_l in NEWS_BLOCKED_PUBLISHERS:
        score -= 5
    if any(g in pub_l for g in NEWS_GOOD_PUBLISHERS_BOOST):
        score += 2
    for pat in NEWS_NOISE_PATTERNS:
        if pat.search(title):
            score -= 4
    for pat in NEWS_BOOST_PATTERNS:
        if pat.search(title):
            score += 3
    return score


def _fetch_rss_feed(url: str, source_label: str, timeout: int = 10) -> list:
    """Fetch and parse an RSS feed. Returns list of {title, publisher, pub_dt, link}."""
    from datetime import datetime as dt
    import email.utils
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'xml')
    except Exception:
        return []
    out = []
    for item in soup.find_all('item')[:30]:
        title_el = item.find('title')
        title = title_el.get_text(strip=True) if title_el else ''
        if not title:
            continue
        pub_el = item.find('pubDate')
        pub_dt = None
        if pub_el:
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub_el.get_text(strip=True))
            except Exception:
                pub_dt = None
        link_el = item.find('link')
        link = link_el.get_text(strip=True) if link_el else ''
        out.append({
            'title': title,
            'publisher': source_label,
            'pub_dt': pub_dt,
            'link': link,
        })
    return out


FINTWIT_ACCOUNTS = [
    'DeItaone', 'firstsquawk', 'unusual_whales', 'zerohedge', 'WSJmarkets',
]

REDDIT_SUBS = [
    ('stocks', 'top', 'day'),         # quality stock discussion
    ('options', 'top', 'day'),        # options-seller content
    ('StockMarket', 'top', 'day'),    # macro/market commentary
]


def fetch_reddit_discussions(subs: list = None, max_total: int = 6,
                             min_score: int = 50) -> list:
    """Fetch quality discussions from r/stocks, r/options, r/StockMarket.

    Filters by score (>=50 upvotes), prefers posts mentioning tickers or
    substantive titles. Drops daily threads and meme content.
    """
    import concurrent.futures
    from datetime import datetime as dt, timezone, timedelta
    subs = subs or REDDIT_SUBS
    cutoff = dt.now(timezone.utc) - timedelta(hours=24)

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

    def fetch_sub(spec):
        sub, sort, t = spec
        url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit=15&t={t}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            r.raise_for_status()
            data = r.json().get('data', {}).get('children', [])
        except Exception:
            return []
        out = []
        for item in data:
            p = item.get('data', {})
            title = p.get('title', '')
            score = p.get('score', 0)
            num_comments = p.get('num_comments', 0)
            created = p.get('created_utc', 0)
            permalink = p.get('permalink', '')
            stickied = p.get('stickied', False)
            if stickied:
                continue
            if score < min_score:
                continue
            if any(pat.search(title) for pat in NOISE_TITLE_PATTERNS):
                continue
            pub_dt = dt.fromtimestamp(created, tz=timezone.utc) if created else None
            if pub_dt and pub_dt < cutoff:
                continue
            out.append({
                'sub': sub,
                'title': title,
                'score': score,
                'num_comments': num_comments,
                'pub_dt': pub_dt,
                'link': f"https://reddit.com{permalink}",
            })
        return out

    all_posts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for items in ex.map(fetch_sub, subs):
            all_posts.extend(items)

    seen = set()
    deduped = []
    for p in all_posts:
        key = re.sub(r'\W+', '', p['title'].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    deduped.sort(key=lambda x: x['score'], reverse=True)
    return deduped[:max_total]


def fetch_x_fintwit(accounts: list = None, per_account: int = 3,
                    max_total: int = 8, hours_window: int = 24) -> list:
    """Fetch tweets from public X syndication API (no auth needed).

    Returns recent tweets from financial accounts. Filters out retweets and
    keeps only original tweets with substantive content (>40 chars).
    """
    import json as _json
    from datetime import datetime as dt, timezone, timedelta
    accounts = accounts or FINTWIT_ACCOUNTS
    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)

    x_headers = {
        **HEADERS,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://platform.twitter.com/',
    }

    def fetch_one(acct):
        try:
            url = f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{acct}?showHeader=false"
            r = requests.get(url, headers=x_headers, timeout=12)
            if r.status_code != 200:
                return []
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', r.text)
            if not m:
                return []
            data = _json.loads(m.group(1))
            entries = (data.get('props', {})
                       .get('pageProps', {})
                       .get('timeline', {})
                       .get('entries', []))
            out = []
            for entry in entries[:per_account * 4]:
                content = entry.get('content', {})
                tweet = content.get('tweet') or {}
                text = tweet.get('full_text') or tweet.get('text', '')
                created_at = tweet.get('created_at', '')
                if not text or len(text) < 40:
                    continue
                if text.startswith('RT @'):
                    continue
                try:
                    pub_dt = dt.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')
                except Exception:
                    pub_dt = None
                if pub_dt and pub_dt < cutoff:
                    continue
                text_clean = re.sub(r'https?://\S+', '', text).strip()
                text_clean = re.sub(r'\s+', ' ', text_clean)
                if len(text_clean) < 30:
                    continue
                out.append({
                    'account': acct,
                    'text': text_clean,
                    'pub_dt': pub_dt,
                })
                if len(out) >= per_account:
                    break
            return out
        except Exception:
            return []

    import concurrent.futures
    all_tweets = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for items in ex.map(fetch_one, accounts):
            all_tweets.extend(items)

    seen = set()
    deduped = []
    for t in all_tweets:
        key = re.sub(r'\W+', '', t['text'].lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)

    deduped.sort(key=lambda x: x['pub_dt'] or dt.min.replace(tzinfo=timezone.utc), reverse=True)
    return deduped[:max_total]


def fetch_market_news(max_total: int = 6, hours_window: int = 24) -> list:
    """Fetch quality market news from CNBC, MarketWatch, Yahoo. Filtered and scored."""
    from datetime import datetime as dt, timezone, timedelta
    feeds = [
        ('CNBC Top', 'https://www.cnbc.com/id/100003114/device/rss/rss.html'),
        ('CNBC Markets', 'https://www.cnbc.com/id/15839069/device/rss/rss.html'),
        ('CNBC Tech', 'https://www.cnbc.com/id/19854910/device/rss/rss.html'),
        ('Yahoo Finance', 'https://finance.yahoo.com/news/rssindex'),
        ('MarketWatch', 'https://feeds.marketwatch.com/marketwatch/topstories/'),
    ]

    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)
    all_items = []
    for label, url in feeds:
        items = _fetch_rss_feed(url, label)
        all_items.extend(items)

    # Filter by recency
    recent = []
    for item in all_items:
        if item['pub_dt'] and item['pub_dt'].tzinfo:
            if item['pub_dt'] < cutoff:
                continue
        recent.append(item)

    # Dedup by title
    seen = set()
    deduped = []
    for n in recent:
        k = re.sub(r'\W+', '', n['title'].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(n)

    # Score and filter
    scored = []
    for n in deduped:
        s = _score_headline(n['title'], n['publisher'])
        if s < -2:
            continue
        scored.append((s, n))

    # Sort by score, then recency
    scored.sort(key=lambda x: (x[0], x[1]['pub_dt'] or dt.min.replace(tzinfo=timezone.utc)), reverse=True)
    return [{'ticker': '', **n} for _, n in scored[:max_total]]


INSIDER_KEY_ROLES = re.compile(
    r'(CEO|CFO|COO|CTO|Pres(?:ident)?|Chair|Founder|Chief\s+\w+\s+Officer)',
    re.I,
)


def _parse_money(s: str) -> float:
    """Parse '+$1,234,567' or '-$50,000' to float."""
    if not s:
        return 0
    s = s.replace(',', '').replace('$', '').replace('+', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0


def fetch_insider_purchases(watchlist: list = None, min_value: float = 50_000,
                            days: int = 2, max_results: int = 10) -> dict:
    """Fetch recent insider C-suite/officer PURCHASES from OpenInsider.

    Filters for CEO/CFO/COO/President/Chair/Founder roles only (no random directors).
    Returns dict with:
      - 'watchlist': purchases on user's watchlist tickers (any size)
      - 'top': other top-value purchases (>= min_value)
    """
    from datetime import datetime as dt, timedelta
    watchlist_set = set(watchlist or [])
    url = "http://openinsider.com/latest-officer-purchases"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"  warn: OpenInsider fetch failed: {e}")
        return {'watchlist': [], 'top': []}

    soup = BeautifulSoup(r.text, 'lxml')
    table = soup.find('table', class_='tinytable')
    if not table:
        return {'watchlist': [], 'top': []}

    cutoff = dt.now() - timedelta(days=days)
    watchlist_hits = []
    top_buys = []

    for row in table.find_all('tr')[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cells) < 13:
            continue
        filing_date = cells[1]
        trade_date = cells[2]
        ticker = cells[3]
        company = cells[4]
        insider = cells[5]
        title = cells[6]
        tx_type = cells[7]
        price = cells[8]
        qty = cells[9]
        value_str = cells[12]

        if 'P - Purchase' not in tx_type:
            continue
        try:
            filing_dt = dt.strptime(filing_date, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if filing_dt < cutoff:
            continue

        is_key_role = bool(INSIDER_KEY_ROLES.search(title))
        if not is_key_role:
            continue

        value = _parse_money(value_str)
        item = {
            'ticker': ticker,
            'company': company[:30],
            'insider': insider[:30],
            'title': title[:25],
            'price': price,
            'qty': qty,
            'value': value,
            'value_str': value_str,
            'filing_date': filing_dt.strftime('%m-%d %H:%M'),
            'trade_date': trade_date,
            'in_watchlist': ticker in watchlist_set,
        }

        if ticker in watchlist_set:
            watchlist_hits.append(item)
        elif value >= min_value:
            top_buys.append(item)

    top_buys.sort(key=lambda x: x['value'], reverse=True)
    watchlist_hits.sort(key=lambda x: x['value'], reverse=True)
    return {
        'watchlist': watchlist_hits[:max_results],
        'top': top_buys[:max_results],
    }


def fetch_mover_catalysts(mover_symbols: list, max_per: int = 1, max_total: int = 4) -> list:
    """For top movers, search news that explains the move. Filtered for catalysts."""
    import concurrent.futures
    from datetime import datetime as dt, timezone, timedelta

    cutoff = dt.now(timezone.utc) - timedelta(hours=24)

    def one(sym):
        try:
            t = yf.Ticker(sym)
            news = getattr(t, 'news', None) or []
            ranked = []
            for n in news[:8]:
                content = n.get('content') or n
                title = content.get('title') or n.get('title') or ''
                pub_ts = content.get('pubDate') or n.get('providerPublishTime')
                publisher = (content.get('provider') or {}).get('displayName') or n.get('publisher', '')
                link = (content.get('canonicalUrl') or {}).get('url') or n.get('link', '')
                pub_dt = None
                if isinstance(pub_ts, str):
                    try:
                        pub_dt = dt.fromisoformat(pub_ts.replace('Z', '+00:00'))
                    except Exception:
                        pass
                elif isinstance(pub_ts, (int, float)):
                    pub_dt = dt.fromtimestamp(pub_ts, tz=timezone.utc)
                if pub_dt and pub_dt < cutoff:
                    continue
                score = _score_headline(title, publisher)
                # Require ticker symbol in title for relevance OR strong catalyst
                if sym not in title.upper() and score < 3:
                    continue
                if score < -1:
                    continue
                ranked.append((score, {
                    'ticker': sym,
                    'title': title,
                    'publisher': publisher,
                    'link': link,
                    'pub_dt': pub_dt,
                }))
            ranked.sort(key=lambda x: x[0], reverse=True)
            return [n for _, n in ranked[:max_per]]
        except Exception:
            return []

    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for items in ex.map(one, mover_symbols):
            out.extend(items)
    seen = set()
    deduped = []
    for n in out:
        k = re.sub(r'\W+', '', n['title'].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(n)
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
