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


def fetch_watchlist_earnings_history(watchlist: list, days_back: int = 2,
                                     days_fwd: int = 14) -> dict:
    """Get recent/upcoming earnings for watchlist tickers via yfinance.

    Returns {'recent': [...], 'upcoming': [...]} with actual vs estimate when available.
    """
    import concurrent.futures
    from datetime import datetime as dt, timedelta, timezone

    now_utc = dt.now(timezone.utc)
    recent_cutoff = now_utc - timedelta(days=days_back)
    upcoming_cutoff = now_utc + timedelta(days=days_fwd)

    def one(sym):
        try:
            t = yf.Ticker(sym)
            ed = t.get_earnings_dates(limit=6)
            if ed is None or ed.empty:
                return None, None
            recent = []
            upcoming = []
            for idx, row in ed.iterrows():
                dt_aware = idx.to_pydatetime()
                if dt_aware.tzinfo is None:
                    dt_aware = dt_aware.replace(tzinfo=timezone.utc)
                est = row.get('EPS Estimate')
                actual = row.get('Reported EPS')
                surprise = row.get('Surprise(%)')

                if recent_cutoff <= dt_aware <= now_utc:
                    if pd.notna(actual):
                        recent.append({
                            'symbol': sym,
                            'date': dt_aware,
                            'eps_estimate': float(est) if pd.notna(est) else None,
                            'eps_actual': float(actual) if pd.notna(actual) else None,
                            'surprise_pct': float(surprise) if pd.notna(surprise) else None,
                            'beat': pd.notna(actual) and pd.notna(est) and float(actual) > float(est),
                        })
                elif now_utc < dt_aware <= upcoming_cutoff:
                    upcoming.append({
                        'symbol': sym,
                        'date': dt_aware,
                        'eps_estimate': float(est) if pd.notna(est) else None,
                        'days_away': (dt_aware - now_utc).days,
                    })
            return recent, upcoming
        except Exception:
            return None, None

    all_recent = []
    all_upcoming = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for r, u in ex.map(one, watchlist):
            if r:
                all_recent.extend(r)
            if u:
                all_upcoming.extend(u)

    all_recent.sort(key=lambda x: x['date'], reverse=True)
    all_upcoming.sort(key=lambda x: x['date'])
    return {'recent': all_recent, 'upcoming': all_upcoming[:6]}


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


def fetch_quotes(symbols: list, include_extended: bool = False) -> list:
    """Batch fetch latest quotes via yfinance. Returns list of dicts.

    When include_extended=True, also fetches pre/after-hours prices via
    1h prepost interval. Adds:
      - extended_price: most-recent extended-hours print (or regular if none)
      - extended_change_pct: % vs prior regular session close
      - session: 'pre' | 'post' | 'regular' | 'closed' indicating current session
    """
    if not symbols:
        return []
    try:
        data = yf.download(symbols, period='5d', progress=False,
                           group_by='ticker', auto_adjust=False, threads=True)
    except Exception as e:
        print(f"  warn: yfinance batch fetch failed: {e}")
        return []

    # Optional extended-hours snapshot via 1h bars with prepost.
    ext_data = None
    if include_extended:
        try:
            ext_data = yf.download(symbols, period='2d', interval='1h',
                                   prepost=True, progress=False,
                                   group_by='ticker', auto_adjust=False, threads=True)
        except Exception as e:
            print(f"  warn: yfinance extended fetch failed: {e}")
            ext_data = None

    from datetime import datetime as _dt
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
            row = {
                'symbol': sym,
                'price': last_close,
                'change_pct': change_pct,
                'change_abs': last_close - prev_close,
            }
            if include_extended and ext_data is not None:
                try:
                    ext_df = ext_data if len(symbols) == 1 else ext_data[sym]
                    ext_df = ext_df.dropna(subset=['Close'])
                    if len(ext_df) > 0:
                        # Last bar's Close = latest traded price (may be pre/post or regular)
                        ext_price = float(ext_df['Close'].iloc[-1])
                        ext_ts = ext_df.index[-1]
                        # Compare to the daily close = baseline
                        ext_change = ((ext_price - last_close) / last_close) * 100
                        # Determine session based on US Eastern time of last bar
                        et_hour = ext_ts.tz_convert('America/New_York').hour if hasattr(ext_ts, 'tz_convert') else ext_ts.hour
                        et_min = ext_ts.tz_convert('America/New_York').minute if hasattr(ext_ts, 'tz_convert') else 0
                        et_minutes = et_hour * 60 + et_min
                        if 4 * 60 <= et_minutes < 9 * 60 + 30:
                            session = 'pre'
                        elif 9 * 60 + 30 <= et_minutes < 16 * 60:
                            session = 'regular'
                        elif 16 * 60 <= et_minutes < 20 * 60:
                            session = 'post'
                        else:
                            session = 'closed'
                        row['extended_price'] = ext_price
                        row['extended_change_pct'] = ext_change
                        row['session'] = session
                except (KeyError, IndexError, ValueError):
                    pass
            out.append(row)
        except (KeyError, IndexError, ValueError):
            continue
    return out


def fetch_watchlist_movers(stocks: list, top_n: int = 5, include_extended: bool = False) -> dict:
    """Fetch quotes for watchlist, return top gainers and losers.

    With include_extended=True, ranks by extended_change_pct when available,
    falling back to regular change_pct.
    """
    quotes = fetch_quotes(stocks, include_extended=include_extended)
    sort_key = (lambda x: x.get('extended_change_pct', x['change_pct'])) if include_extended \
               else (lambda x: x['change_pct'])
    sorted_q = sorted(quotes, key=sort_key, reverse=True)
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


def _normal_cdf(x: float) -> float:
    from math import erf, sqrt
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _bs_price(S: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    """Black-Scholes European option price (no dividends)."""
    from math import log, sqrt, exp
    if sigma <= 0 or T <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    if is_call:
        return S * _normal_cdf(d1) - K * exp(-r * T) * _normal_cdf(d2)
    return K * exp(-r * T) * _normal_cdf(-d2) - S * _normal_cdf(-d1)


def _implied_vol(market_price: float, S: float, K: float, T: float,
                  r: float, is_call: bool) -> float:
    """Solve for implied volatility via bisection. Returns sigma (decimal) or 0."""
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return 0.0
    # Intrinsic floor — if market price below intrinsic, can't solve
    intrinsic = max(0.0, (S - K) if is_call else (K - S))
    if market_price <= intrinsic + 0.01:
        return 0.0
    low, high = 0.005, 5.0
    for _ in range(80):
        mid = (low + high) / 2
        price = _bs_price(S, K, T, r, mid, is_call)
        if abs(price - market_price) < 0.005:
            return mid
        if price < market_price:
            low = mid
        else:
            high = mid
        if high - low < 1e-5:
            break
    return mid


def fetch_iv_metrics(symbols: list, risk_free: float = 0.045) -> list:
    """Compute current ATM IV per ticker via yfinance options chain.

    Calculates IV ourselves using Black-Scholes from ATM call/put mid prices —
    yfinance's `impliedVolatility` field returns placeholder values (1e-05)
    that are unusable. Prefers bid/ask mid when market is open, falls back to
    lastPrice when market is closed (bid/ask = 0).

    Returns list sorted by IV desc — highest IV first (best premium-selling
    candidates).
    """
    import concurrent.futures
    from datetime import date

    def _mid_price(row) -> float:
        bid = float(row.get('bid', 0) or 0)
        ask = float(row.get('ask', 0) or 0)
        last = float(row.get('lastPrice', 0) or 0)
        if bid > 0 and ask > 0 and ask >= bid:
            return (bid + ask) / 2.0
        return last

    def _row_iv(row, S, K, T, r, is_call):
        """Compute IV from a single strike, requiring liquid quote."""
        bid = float(row.get('bid', 0) or 0)
        ask = float(row.get('ask', 0) or 0)
        last = float(row.get('lastPrice', 0) or 0)
        vol = float(row.get('volume', 0) or 0)
        oi = float(row.get('openInterest', 0) or 0)
        # Liquidity gate: need either a tight quote OR meaningful open interest.
        # Filters out illiquid strikes that show garbage IVs.
        has_quote = bid > 0 and ask > 0 and (ask - bid) / max(ask, 0.01) < 0.6
        has_oi = oi >= 50 or vol >= 5
        if not (has_quote or has_oi):
            return 0.0
        if has_quote:
            price = (bid + ask) / 2.0
        else:
            price = last
        if price <= 0.05:
            return 0.0
        return _implied_vol(price, S, K, T, r, is_call)

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
            calls, puts = chain.calls, chain.puts
            if calls.empty or puts.empty:
                return None
            dte = (datetime.strptime(target_exp, '%Y-%m-%d').date() - today).days
            T = max(dte, 1) / 365.0
            # Sample 5 strikes nearest to spot from each side. Averaging across
            # near-ATM strikes filters noise from single-strike outliers.
            near_calls = calls.iloc[(calls['strike'] - spot).abs().argsort()[:5]]
            near_puts = puts.iloc[(puts['strike'] - spot).abs().argsort()[:5]]
            ivs = []
            for _, row in near_calls.iterrows():
                iv = _row_iv(row, spot, float(row['strike']), T, risk_free, True)
                # Sanity bounds: 5% to 250%
                if 0.05 <= iv <= 2.5:
                    ivs.append(iv)
            for _, row in near_puts.iterrows():
                iv = _row_iv(row, spot, float(row['strike']), T, risk_free, False)
                if 0.05 <= iv <= 2.5:
                    ivs.append(iv)
            if not ivs:
                return None
            # Use median to reject outliers, not mean
            ivs.sort()
            iv = ivs[len(ivs) // 2] * 100
            return {
                'symbol': sym,
                'iv': iv,
                'spot': spot,
                'dte': dte,
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

REDDIT_UA = 'daug-pinigu-briefing/1.0 (by /u/daugpinigu)'


def _reddit_oauth_token() -> str:
    """Get a Reddit application-only OAuth token using client_credentials grant.

    Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars.
    Returns '' if creds are missing or auth fails.
    """
    import os as _os
    cid = _os.environ.get('REDDIT_CLIENT_ID')
    csec = _os.environ.get('REDDIT_CLIENT_SECRET')
    if not cid or not csec:
        return ''
    try:
        r = requests.post(
            'https://www.reddit.com/api/v1/access_token',
            auth=(cid, csec),
            headers={'User-Agent': REDDIT_UA},
            data={'grant_type': 'client_credentials'},
            timeout=12,
        )
        r.raise_for_status()
        return r.json().get('access_token', '')
    except Exception as e:
        print(f"  reddit OAuth failed: {type(e).__name__}: {str(e)[:120]}")
        return ''


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

    # OAuth path bypasses Reddit's datacenter-IP block. Falls back to public
    # JSON if creds aren't set (works locally, fails on GH Actions).
    token = _reddit_oauth_token()
    reddit_headers = {'User-Agent': REDDIT_UA, 'Accept': 'application/json'}
    if token:
        reddit_headers['Authorization'] = f'bearer {token}'

    import time as _time

    def fetch_sub(spec):
        sub, sort, t = spec
        # When authenticated, use oauth.reddit.com. Otherwise try old.reddit.com
        # then www.reddit.com as best-effort fallbacks.
        if token:
            urls = [f"https://oauth.reddit.com/r/{sub}/{sort}.json?limit=15&t={t}"]
        else:
            urls = [
                f"https://old.reddit.com/r/{sub}/{sort}.json?limit=15&t={t}",
                f"https://www.reddit.com/r/{sub}/{sort}.json?limit=15&t={t}",
            ]
        data = []
        for url in urls:
            try:
                r = requests.get(url, headers=reddit_headers, timeout=12)
                if r.status_code == 429:
                    _time.sleep(2)
                    continue
                if r.status_code != 200:
                    print(f"  reddit r/{sub} {url[:30]}... -> HTTP {r.status_code}")
                    continue
                data = r.json().get('data', {}).get('children', [])
                if data:
                    break
            except Exception as e:
                print(f"  reddit r/{sub} error: {type(e).__name__}: {str(e)[:80]}")
                continue
        if not data:
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


# Brand names for tickers — used to also match natural-language references.
# Required because tickers like SHOP/SOFI may not be written in ALL CAPS.
TICKER_BRANDS = {
    'TSLA': 'Tesla', 'NVDA': 'NVIDIA', 'AAPL': 'Apple', 'MSFT': 'Microsoft',
    'GOOGL': 'Google', 'META': 'Meta', 'AMZN': 'Amazon', 'NFLX': 'Netflix',
    'AMD': 'AMD', 'AVGO': 'Broadcom', 'ASML': 'ASML', 'ADBE': 'Adobe',
    'UNH': 'UnitedHealth', 'BABA': 'Alibaba', 'BIDU': 'Baidu',
    'SOFI': 'SoFi', 'HIMS': 'Hims', 'PYPL': 'PayPal', 'SHOP': 'Shopify',
    'PLTR': 'Palantir', 'HOOD': 'Robinhood', 'RDDT': 'Reddit', 'ZM': 'Zoom',
    'GME': 'GameStop', 'MSTR': 'Strategy', 'NVO': 'Novo Nordisk', 'DUOL': 'Duolingo',
    'CRWV': 'CoreWeave', 'NBIS': 'Nebius', 'RKLB': 'Rocket Lab', 'IREN': 'IREN',
    'ENPH': 'Enphase', 'RIOT': 'Riot Platforms', 'BMNR': 'BitMine',
    'FIG': 'Figma', 'ZETA': 'Zeta Global', 'CLSK': 'CleanSpark',
    'PATH': 'UiPath', 'GRAB': 'Grab', 'SNDK': 'SanDisk', 'MU': 'Micron',
    'ENS': 'EnerSys', 'BE': 'Bloom Energy',
}


CATALYST_KEYWORDS = re.compile(
    r'\b('
    r'acquires?|acquisition|acquired|takeover|merg(?:er|es?|ing)|buyout|'
    r'partner(?:s?|ship)|joint\s+venture|'
    r'FDA\s+(?:approval|approves?|rejection|rejects?|decision|clearance)|'
    r'clinical\s+trial|phase\s+(?:2|3|III|II)|'
    r'lawsuit|settles?|settlement|fine|penalty|'
    r'guidance\s+(?:raise|raises?|raised|cut|cuts?|lowered|withdraws?|withdrawn)|'
    r'raises?\s+(?:guidance|outlook|FY)|cuts?\s+(?:guidance|outlook)|'
    r'buyback|repurchase|dividend\s+(?:increase|hike|cut)|'
    r'stock\s+split|spin[- ]off|IPO\s+filing|'
    r'CEO\s+(?:steps?\s+down|resigns?|fired|named|appointed)|'
    r'CFO\s+(?:steps?\s+down|resigns?|fired|named|appointed)|'
    r'(?:layoffs?|cuts?\s+jobs?|workforce\s+reduction)|'
    r'(?:upgrade|downgrade)d?\s+(?:to|from|by)|price\s+target\s+(?:raised|cut|lowered)|'
    r'shares?\s+(?:surge|plunge|tumble|rally|crash)|'
    r'(?:bought|purchased|sold|adds?)\s+\d[\d,]*\s+shares?|'
    r'capital\s+raise|secondary\s+offering|debt\s+offering|'
    r'(?:beat|miss)es?\s+(?:Q\d|earnings|estimates?|revenue)|'
    r'restructur(?:ing|es?)|'
    r'investigation|probe|subpoena'
    r')\b',
    re.I,
)


def fetch_watchlist_catalysts(watchlist: list, max_total: int = 10,
                              hours_window: int = 36) -> list:
    """Search Google News for catalyst stories on each watchlist ticker.

    Uses Google News RSS (free, no auth) to find M&A, FDA, lawsuits, guidance,
    insider, partnerships across the entire watchlist - not just big movers.
    Filters by catalyst keywords in title, scores by recency + publisher quality.
    """
    import concurrent.futures
    from datetime import datetime as dt, timezone, timedelta
    from email.utils import parsedate_to_datetime as _parsedate

    if not watchlist:
        return []
    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)
    hdrs = {'User-Agent': 'Mozilla/5.0'}

    # Convert hours window to days for the Google News query.
    days_q = max(1, hours_window // 24 + 1)

    def fetch_one(ticker):
        url = (f"https://news.google.com/rss/search?q={ticker}+"
               f"when:{days_q}d&hl=en-US&gl=US&ceid=US:en")
        try:
            r = requests.get(url, headers=hdrs, timeout=10)
            r.raise_for_status()
            txt = r.text
        except Exception:
            return []
        items = re.findall(r'<item>(.*?)</item>', txt, re.DOTALL)
        out = []
        for it in items[:8]:
            tmatch = re.search(r'<title><!\[CDATA\[(.+?)\]\]></title>|<title>(.+?)</title>', it)
            pmatch = re.search(r'<pubDate>(.+?)</pubDate>', it)
            lmatch = re.search(r'<link>(.+?)</link>', it)
            smatch = re.search(r'<source[^>]*>(.+?)</source>', it)
            if not tmatch or not pmatch:
                continue
            title = (tmatch.group(1) or tmatch.group(2) or '').strip()
            # Strip " - Source" suffix from title
            title = re.sub(r'\s+-\s+[^-]+$', '', title).strip()
            try:
                pub_dt = _parsedate(pmatch.group(1))
            except Exception:
                continue
            if not pub_dt or pub_dt < cutoff:
                continue
            # Strict ticker match — uppercase, $-prefixed, parens, or known brand.
            # Avoids "Yogurt SHOP" false positives while still catching "SoFi Acquires".
            ticker_matched = (
                re.search(rf'\${re.escape(ticker)}\b', title) or
                re.search(rf'\b{re.escape(ticker)}\b(?![a-z])', title) or
                re.search(rf'\({re.escape(ticker)}\)', title) or
                re.search(rf'\b{re.escape(ticker)}:', title)
            )
            brand = TICKER_BRANDS.get(ticker)
            if not ticker_matched and brand:
                ticker_matched = re.search(rf'\b{re.escape(brand)}\b', title, re.I)
            if not ticker_matched:
                continue
            if not CATALYST_KEYWORDS.search(title):
                continue
            publisher = (smatch.group(1) if smatch else '').strip()
            if publisher.lower() in NEWS_BLOCKED_PUBLISHERS:
                continue
            link = lmatch.group(1).strip() if lmatch else ''
            out.append({
                'ticker': ticker,
                'title': title,
                'link': link,
                'publisher': publisher,
                'pub_dt': pub_dt,
            })
        return out

    all_hits = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for items in ex.map(fetch_one, watchlist):
            all_hits.extend(items)

    # Score: recency + publisher quality + catalyst strength
    def score(n):
        s = 0
        pub_l = n['publisher'].lower()
        if pub_l in NEWS_GOOD_PUBLISHERS_BOOST:
            s += 5
        # Recency: newer = better
        age_h = (dt.now(timezone.utc) - n['pub_dt']).total_seconds() / 3600
        s += max(0, 24 - age_h) / 4  # up to +6 for fresh news
        title_l = n['title'].lower()
        # Strong catalyst keywords
        for strong in ('acquires', 'acquisition', 'fda approv', 'merger',
                       'buyback', 'lawsuit settles', 'guidance raise'):
            if strong in title_l:
                s += 3
        return s

    all_hits.sort(key=score, reverse=True)
    # Dedup by title prefix (same story from multiple sources)
    seen = set()
    deduped = []
    for n in all_hits:
        key = re.sub(r'\W+', '', n['title'].lower())[:50]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(n)
    return deduped[:max_total]


def fetch_x_posts(watchlist: list, max_total: int = 8,
                   hours_window: int = 24) -> list:
    """Fetch X.com posts mentioning watchlist tickers via authenticated session.

    Requires X_SESSION_B64 env var (base64 of x_session.json captured by
    scripts/x_login.py). Uses Playwright to perform the search with the
    user's auth so we get full content + chronological results.

    Returns list of {ticker, author, handle, text, likes, retweets, link, pub_dt}.
    """
    import os as _os
    import base64 as _b64
    import json as _json
    from datetime import datetime as dt, timezone, timedelta
    from email.utils import parsedate_to_datetime as _parsedate

    session_b64 = _os.environ.get('X_SESSION_B64')
    if not session_b64:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    # Decode session and write to a temp file for Playwright
    import tempfile
    try:
        session_json = _b64.b64decode(session_b64).decode('utf-8')
    except Exception:
        print("  warn: X_SESSION_B64 not valid base64")
        return []
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        f.write(session_json)
        session_path = f.name

    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)
    # Pick a smaller set of high-signal tickers (full search per ticker is slow)
    priority_tickers = watchlist[:25] if len(watchlist) > 25 else watchlist

    posts = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled'],
            )
            context = browser.new_context(
                storage_state=session_path,
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 900},
                locale='en-US',
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            # First verify the session is valid by visiting home
            try:
                page.goto('https://x.com/home', wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(2000)
                url_after = page.url
                title_after = page.title()
                print(f"  x.com session check: url={url_after[:60]} title={title_after[:40]}")
                if 'login' in url_after.lower() or 'flow/login' in url_after:
                    print("  x.com: session not recognized (login wall)")
                    browser.close()
                    return []
            except Exception as e:
                print(f"  x.com home check failed: {type(e).__name__}: {str(e)[:60]}")

            for ticker in priority_tickers:
                if len(posts) >= max_total * 2:
                    break
                # Search "Latest" tab for ticker-tagged posts, exclude replies
                search_url = (f'https://x.com/search?q=%24{ticker}%20-filter%3Areplies'
                              f'%20min_faves%3A50%20lang%3Aen&src=typed_query&f=live')
                try:
                    page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
                    try:
                        page.wait_for_selector('article', timeout=8000)
                    except Exception:
                        if ticker == priority_tickers[0]:
                            print(f"  x.com {ticker} no articles. url={page.url[:80]}")
                        continue
                    # Scroll a bit to load more
                    page.evaluate('window.scrollBy(0, 600)')
                    page.wait_for_timeout(800)
                    articles = page.query_selector_all('article')
                    for a in articles[:5]:
                        try:
                            text_el = a.query_selector('div[data-testid="tweetText"]')
                            text = text_el.inner_text() if text_el else ''
                            if not text or len(text) < 30:
                                continue
                            time_el = a.query_selector('time')
                            pub_str = time_el.get_attribute('datetime') if time_el else ''
                            try:
                                pub_dt = dt.fromisoformat(pub_str.replace('Z', '+00:00'))
                            except Exception:
                                continue
                            if pub_dt < cutoff:
                                continue
                            user_link = a.query_selector('a[href^="/"][role="link"] div[dir="ltr"] span')
                            author = user_link.inner_text() if user_link else ''
                            handle_el = a.query_selector('a[href^="/"][tabindex="-1"]')
                            handle = handle_el.get_attribute('href').lstrip('/') if handle_el else ''
                            # Tweet permalink
                            status_a = a.query_selector('a[href*="/status/"]')
                            link = ''
                            if status_a:
                                link = 'https://x.com' + status_a.get_attribute('href')
                            # Engagement counts
                            def _count(selector):
                                el = a.query_selector(f'[data-testid="{selector}"]')
                                if not el:
                                    return 0
                                txt = el.inner_text() or '0'
                                txt = txt.replace(',', '').upper()
                                if 'K' in txt:
                                    try:
                                        return int(float(txt.replace('K', '')) * 1000)
                                    except Exception:
                                        return 0
                                try:
                                    return int(txt)
                                except Exception:
                                    return 0
                            likes = _count('like')
                            retweets = _count('retweet')
                            posts.append({
                                'ticker': ticker,
                                'author': author[:50],
                                'handle': handle[:30],
                                'text': text[:600],
                                'likes': likes,
                                'retweets': retweets,
                                'link': link,
                                'pub_dt': pub_dt,
                            })
                        except Exception:
                            continue
                except Exception as e:
                    print(f"  x.com {ticker} fail: {type(e).__name__}: {str(e)[:60]}")
                    continue
            browser.close()
    except Exception as e:
        print(f"  warn: X fetch failed: {type(e).__name__}: {str(e)[:80]}")

    # Dedup by tweet link, sort by engagement
    seen = set()
    out = []
    for p in posts:
        if p['link'] in seen or not p['link']:
            continue
        seen.add(p['link'])
        out.append(p)
    out.sort(key=lambda x: x['likes'] + x['retweets'], reverse=True)

    try:
        _os.unlink(session_path)
    except Exception:
        pass
    return out[:max_total]


def fetch_earnings_transcript(ticker: str, max_chars: int = 5000) -> str:
    """Find most recent Motley Fool earnings call transcript for ticker.

    Motley Fool transcripts are publicly accessible (unlike SeekingAlpha which
    blocks scrapers) and have structured TAKEAWAYS + management quotes.
    Returns body text or '' if not found.
    """
    if not ticker:
        return ''
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    # Fool quote pages list per-ticker historical transcripts. Try nasdaq first, then nyse.
    quote_html = ''
    for exch in ('nasdaq', 'nyse'):
        try:
            r = requests.get(f'https://www.fool.com/quote/{exch}/{ticker.lower()}/',
                              headers=headers, timeout=12, allow_redirects=True)
            if r.status_code == 200:
                quote_html = r.text
                break
        except Exception:
            continue
    if not quote_html:
        return ''

    pattern = re.compile(
        rf'(/earnings/call-transcripts/\d{{4}}/\d{{2}}/\d{{2}}/[^"\\]*-{ticker.lower()}-q\d-\d{{4}}-earnings[^"\\]*)',
        re.I,
    )
    matches = pattern.findall(quote_html)
    if not matches:
        return ''
    # Most recent transcript URL is typically first on the page
    transcript_path = matches[0].rstrip('/') + '/'
    url = 'https://www.fool.com' + transcript_path
    try:
        r2 = requests.get(url, headers=headers, timeout=15)
        r2.raise_for_status()
    except Exception:
        return ''

    soup = BeautifulSoup(r2.text, 'lxml')
    body = soup.select_one('div.article-body')
    if not body:
        return ''
    text = body.get_text(' ', strip=True)
    return text[:max_chars]


def fetch_reddit_comments(permalink_url: str, top_n: int = 8) -> list:
    """Fetch top comments for a Reddit thread. Returns list of comment bodies.

    permalink_url is the full link like https://reddit.com/r/stocks/comments/xxx/...
    Reddit's JSON API: just append .json to any permalink.
    """
    if not permalink_url:
        return []
    token = _reddit_oauth_token()
    reddit_headers = {'User-Agent': REDDIT_UA, 'Accept': 'application/json'}
    if token:
        # Rewrite permalink path onto oauth.reddit.com
        path = permalink_url.split('reddit.com', 1)[-1] if 'reddit.com' in permalink_url else permalink_url
        url = 'https://oauth.reddit.com' + path.rstrip('/') + '.json?limit=' + str(top_n * 2)
        reddit_headers['Authorization'] = f'bearer {token}'
    else:
        url = permalink_url.rstrip('/') + '.json?limit=' + str(top_n * 2)
    try:
        r = requests.get(url, headers=reddit_headers, timeout=12)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    if not isinstance(data, list) or len(data) < 2:
        return []
    comments_data = data[1].get('data', {}).get('children', [])
    out = []
    for c in comments_data:
        if c.get('kind') != 't1':
            continue
        cd = c.get('data', {})
        body = cd.get('body', '').strip()
        score = cd.get('score', 0)
        if not body or body == '[deleted]' or body == '[removed]':
            continue
        if score < 5:
            continue
        out.append(body[:500])
        if len(out) >= top_n:
            break
    return out


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


def fetch_article_summary(url: str, max_chars: int = 600) -> str:
    """Fetch first few paragraphs of an article body. Returns clean text.

    Returns '' for Google News redirect URLs that land on consent pages —
    those need Playwright fallback to resolve to the actual publisher.
    """
    if not url:
        return ''
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code != 200:
            return ''
        # Detect consent / interstitial pages — they masquerade as article body.
        if any(s in r.url for s in ('consent.google.com', 'consent.yahoo.com',
                                      'guce.', '/cookieconsent', '/privacy/notice')):
            return ''
        if any(s in r.text[:2500] for s in ('Before you continue',
                                              'guce guce', 'Mums rūpi jūsų privatumas',
                                              'We use cookies and data to')):
            return ''
        soup = BeautifulSoup(r.text, 'lxml')
        for tag in soup.find_all(['script', 'style', 'aside', 'figure', 'nav', 'footer', 'header']):
            tag.decompose()

        article_root = (
            soup.find('article') or
            soup.find('div', attrs={'class': re.compile(r'(article-body|story-body|content-body|article-content)', re.I)}) or
            soup.find('main') or
            soup
        )

        paras = []
        for p in article_root.find_all('p'):
            txt = p.get_text(strip=True)
            if not txt or len(txt) < 40:
                continue
            if any(skip in txt.lower() for skip in [
                'sign up', 'subscribe', 'newsletter', 'follow us', 'click here',
                'all rights reserved', 'terms of service', 'privacy policy',
                'mln view', 'related:', 'related stories'
            ]):
                continue
            paras.append(txt)
            if sum(len(x) for x in paras) >= max_chars:
                break

        if not paras:
            return ''
        joined = ' '.join(paras)
        if len(joined) > max_chars:
            cut = joined[:max_chars]
            last_period = cut.rfind('.')
            if last_period > max_chars * 0.6:
                cut = cut[:last_period + 1]
            else:
                cut = cut.rstrip() + '...'
            joined = cut
        return joined
    except Exception:
        return ''


def fetch_articles_with_browser(urls: list, max_chars: int = 5000) -> dict:
    """Fetch article bodies using Playwright. Used as fallback when the
    requests-based path returns empty (Google News redirects, JS sites).

    For Google News URLs: navigate, accept consent, capture the final
    resolved URL, then extract body from the destination publisher's page.
    Returns {original_url: {body, resolved_url}} dict.
    """
    if not urls:
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}

    out = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled'],
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                locale='en-US',
                timezone_id='America/New_York',
            )
            # Hide webdriver flag (some sites bot-detect on it)
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()
            # Block heavy resources to speed up load
            page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,mp4,webm}',
                       lambda route: route.abort())
            for url in urls:
                resolved_url = url
                body = ''
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=20000)
                    # Handle Google consent page if present
                    if 'consent.google.com' in page.url:
                        for sel in ['button:has-text("Reject all")',
                                     'button:has-text("Accept all")',
                                     'form[action*="save"] button']:
                            try:
                                page.click(sel, timeout=2000)
                                page.wait_for_load_state('domcontentloaded', timeout=10000)
                                break
                            except Exception:
                                continue
                    try:
                        page.wait_for_load_state('networkidle', timeout=5000)
                    except Exception:
                        pass
                    resolved_url = page.url
                    text = page.evaluate("""() => {
                        const selectors = [
                            'article', 'div.article-body', 'div.story-body',
                            'main article', 'main', '[data-test-id*="article"]',
                            'div[class*="ArticleBody"]', 'div[class*="article-content"]',
                            'div[class*="story"]', 'div[itemprop="articleBody"]',
                        ];
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && el.innerText && el.innerText.length > 200) {
                                return el.innerText;
                            }
                        }
                        return document.body ? document.body.innerText : '';
                    }""")
                    if text and len(text) > 200:
                        cleaned = re.sub(r'\s+', ' ', text).strip()
                        cleaned_lo = cleaned.lower()[:300]
                        is_interstitial = any(s in cleaned_lo for s in (
                            'before you continue', 'guce guce', 'mums rūpi',
                            'we use cookies and data to', '403 forbidden',
                            'access denied', 'are you a robot',
                        ))
                        if not is_interstitial:
                            body = cleaned[:max_chars]
                except Exception:
                    pass
                out[url] = {'body': body, 'resolved_url': resolved_url}
            browser.close()
    except Exception as e:
        print(f"  warn: Playwright article fetch failed: {type(e).__name__}: {str(e)[:80]}")
    return out


def enrich_news_with_summaries(news_items: list, max_workers: int = 6) -> list:
    """For each news item with a link, fetch article summary.

    Phase 1: parallel requests-based fetch (fast, works for most sources).
    Phase 2: Playwright fallback for items that failed (Google News redirects,
    JS-heavy sources). Single browser session for all phase-2 URLs.
    """
    import concurrent.futures
    if not news_items:
        return news_items
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_article_summary, n.get('link', '')): n for n in news_items}
        for fut in concurrent.futures.as_completed(futures):
            n = futures[fut]
            try:
                n['summary'] = fut.result()
            except Exception:
                n['summary'] = ''

    # Phase 2: Playwright for URLs that returned empty body
    failed_urls = [n['link'] for n in news_items
                    if n.get('link') and not (n.get('summary') or '').strip()]
    if failed_urls:
        print(f"    -> {len(failed_urls)} articles need browser rendering...")
        results = fetch_articles_with_browser(failed_urls, max_chars=5000)
        # Phase 2b: for items where Playwright resolved a URL but didn't get
        # body (bot-blocked publisher), retry that resolved URL via requests.
        retry_urls = []
        for n in news_items:
            url = n.get('link', '')
            if url not in results:
                continue
            r = results[url]
            if r['body']:
                n['summary'] = r['body']
                if r['resolved_url'] and r['resolved_url'] != url:
                    n['link'] = r['resolved_url']  # update to real article URL
            elif r['resolved_url'] and r['resolved_url'] != url and \
                 'news.google.com' not in r['resolved_url']:
                n['link'] = r['resolved_url']
                retry_urls.append(r['resolved_url'])
        if retry_urls:
            print(f"    -> retrying {len(retry_urls)} resolved URLs via requests...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                url_to_body = {u: ex.submit(fetch_article_summary, u) for u in retry_urls}
                for n in news_items:
                    if n.get('summary'):
                        continue
                    fut = url_to_body.get(n.get('link', ''))
                    if fut:
                        try:
                            n['summary'] = fut.result() or ''
                        except Exception:
                            pass
    return news_items


GEOPOL_REQUIRED_KEYWORDS = [
    # Wars / military
    'iran', 'israel', 'gaza', 'lebanon', 'hezbollah', 'houthi',
    'russia', 'ukraine', 'putin', 'kremlin', 'moscow',
    'north korea', 'kim jong', 'taiwan',
    'missile', 'airstrike', 'air strike', 'military strike',
    'drone strike', 'war ', ' war,', ' war.', ' war:',
    # Trade / sanctions / tariffs
    'tariff', 'sanction', 'export control', 'export ban',
    'trade war', 'section 301', 'section 232',
    # Oil / energy chokepoints
    'opec', 'opec+', 'crude oil', 'brent crude', 'wti crude',
    'strait of hormuz', 'suez canal', 'red sea shipping',
    'oil price', 'gasoline price',
    # Diplomacy / summits with named leaders
    'trump-xi', 'trump xi', 'xi jinping',
    'putin trump', 'trump putin',
    # Fed / macro (high signal)
    'fomc', 'fed cut', 'fed hike', 'fed pause',
    'powell', 'jerome powell',
    'cpi report', 'ppi report', 'pce inflation',
    'jobs report', 'nfp', 'unemployment rate',
    # Regulatory
    'clarity act', 'genius act', 'stablecoin bill',
    'executive order',
]


def fetch_geopolitics_news(max_total: int = 4, hours_window: int = 48) -> list:
    """Fetch geopolitics + macro headlines that move markets even without a
    watchlist ticker. Iran-US conflict, OPEC, Strait of Hormuz, Fed pivots,
    war escalation - all hit oil/gold/defense/VIX/USD broadly.

    Uses the same RSS feeds as fetch_market_news but filters STRICTLY: keep only
    headlines that contain at least one keyword from GEOPOL_REQUIRED_KEYWORDS.
    This avoids the Magnum Ice Cream / Coles grocery noise that triggered the
    "drop fetch_market_news entirely" memory rule, while still surfacing the
    war/Iran/oil/Fed signal that's mandatory per Radoslav.
    """
    from datetime import datetime as dt, timezone, timedelta
    feeds = [
        ('CNBC Top', 'https://www.cnbc.com/id/100003114/device/rss/rss.html'),
        ('CNBC World', 'https://www.cnbc.com/id/100727362/device/rss/rss.html'),
        ('Reuters World', 'https://feeds.reuters.com/Reuters/worldNews'),
        ('Yahoo Finance', 'https://finance.yahoo.com/news/rssindex'),
        ('MarketWatch', 'https://feeds.marketwatch.com/marketwatch/topstories/'),
    ]
    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)
    all_items = []
    for label, url in feeds:
        all_items.extend(_fetch_rss_feed(url, label))

    recent = []
    for item in all_items:
        if item['pub_dt'] and item['pub_dt'].tzinfo and item['pub_dt'] < cutoff:
            continue
        title_l = (item.get('title') or '').lower()
        # STRICT keyword gate: title must contain at least one geopol keyword.
        if not any(kw in title_l for kw in GEOPOL_REQUIRED_KEYWORDS):
            continue
        recent.append(item)

    # Dedup
    seen = set()
    deduped = []
    for n in recent:
        k = re.sub(r'\W+', '', n['title'].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        deduped.append(n)

    # Score with bonus for geopol keywords (already keyword-gated, so this is
    # mostly about prioritizing the strongest signals: war, OPEC, Fed)
    HIGH_PRIORITY = ['strait of hormuz', 'fomc', 'fed cut', 'fed hike', 'opec',
                     'sanction', 'tariff', 'missile', 'airstrike', 'war',
                     'iran', 'israel', 'russia']
    scored = []
    for n in deduped:
        s = _score_headline(n['title'], n['publisher'])
        title_l = n['title'].lower()
        for kw in HIGH_PRIORITY:
            if kw in title_l:
                s += 3
        scored.append((s, n))

    scored.sort(key=lambda x: (x[0], x[1]['pub_dt'] or dt.min.replace(tzinfo=timezone.utc)),
                reverse=True)
    return [{'ticker': 'MACRO', 'is_geopolitics': True, **n} for _, n in scored[:max_total]]


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


def _fetch_ticker_insider(ticker: str, days: int, min_value: float) -> list:
    """Fetch all insider transactions for one ticker via OpenInsider per-ticker page.

    Includes BOTH purchases (P) and sales (S). tx_type is normalized to 'buy'
    or 'sell' for downstream filtering/rendering. Hard cutoff at 2025-01-01
    so anything pre-2025 is excluded regardless of the days parameter.
    """
    from datetime import datetime as dt, timedelta
    url = f"http://openinsider.com/screener?s={ticker}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
    except Exception:
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    table = soup.find('table', class_='tinytable')
    if not table:
        return []

    # Per-ticker page columns (no company column since we know the ticker):
    # 0: flag, 1: filing, 2: trade, 3: ticker, 4: insider, 5: title,
    # 6: tx_type, 7: price, 8: qty, 9: shares_owned (post-tx), 10: %, 11: value
    cutoff = dt.now() - timedelta(days=days)
    # Hard floor: never include anything before 2025-01-01 even if days is larger.
    hard_floor = dt(2025, 1, 1)
    if cutoff < hard_floor:
        cutoff = hard_floor
    hits = []
    for row in table.find_all('tr')[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all('td')]
        if len(cells) < 12:
            continue
        try:
            trade_dt = dt.strptime(cells[2], '%Y-%m-%d')
        except ValueError:
            continue
        if trade_dt < cutoff:
            continue
        tx_raw = cells[6]
        if 'P - Purchase' in tx_raw:
            tx_type = 'buy'
        elif 'S - Sale' in tx_raw:
            tx_type = 'sell'
        else:
            continue  # skip awards, gifts, option exercises etc.
        title = cells[5]
        if not INSIDER_KEY_ROLES.search(title):
            continue
        raw_value = _parse_money(cells[11])
        # Sales are reported as negative in OpenInsider (e.g. "-$55,688,750").
        # Use absolute value for filtering + storage so threshold logic and
        # sorting work consistently across buys and sells.
        value = abs(raw_value)
        if value < min_value:
            continue
        # Normalize the value_str display: drop the leading "-" on sells so it
        # reads as "$55.7M" with the SELL tag conveying direction.
        value_str = cells[11].replace('-$', '$').replace('+$', '+$')
        if tx_type == 'sell':
            value_str = value_str.replace('+', '').strip()
        # shares_owned is post-transaction holdings (col 9). For sells this
        # is the remaining stake; for buys it's the new total. Some rows
        # have "" (e.g. options exercises later filed) - default to 0.
        shares_owned_raw = (cells[9] or '').replace(',', '').strip()
        try:
            shares_owned = int(shares_owned_raw)
        except ValueError:
            shares_owned = 0
        hits.append({
            'ticker': ticker,
            'insider': cells[4][:30],
            'title': title[:25],
            'tx_type': tx_type,
            'price': cells[7],
            'qty': cells[8].lstrip('-'),  # drop minus sign on qty for sells
            'value': value,
            'value_str': value_str,
            'shares_owned': shares_owned,
            'filing_date': cells[1][:10],
            'trade_date': cells[2],
        })
    return hits


def fetch_insider_purchases(watchlist: list, days: int = 365,
                            min_value: float = 10_000, max_results: int = 15) -> list:
    """Fetch C-suite insider transactions (BUYS + SELLS) for each watchlist ticker.

    Aggregates repeat transactions by same insider+ticker+tx_type into one entry
    so we surface distinct signals instead of letting one CEO's weekly trades
    fill all slots. Sorts: recent-week first, then by total value DESC.

    Hard cutoff at 2025-01-01 (see _fetch_ticker_insider) — anything earlier
    is excluded regardless of `days` parameter.
    """
    import concurrent.futures
    watchlist_set = set(watchlist or [])
    if not watchlist_set:
        return []

    all_hits = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch_ticker_insider, t, days, min_value): t
                   for t in watchlist_set}
        for fut in concurrent.futures.as_completed(futures):
            try:
                all_hits.extend(fut.result())
            except Exception:
                continue

    # Aggregate by (ticker, insider, tx_type) — same person buying repeatedly = 1 entry,
    # same person selling repeatedly = SEPARATE entry. We do not net buys against sells
    # because the signal differs (a CEO who bought $1M then sold $1M is not a wash —
    # it's two distinct actions with separate context).
    grouped = {}
    for h in all_hits:
        key = (h['ticker'], h['insider'], h['tx_type'])
        single = {
            'trade_date': h['trade_date'],
            'qty': h['qty'],
            'price': h['price'],
            'value': h['value'],
            'value_str': h['value_str'],
        }
        if key not in grouped:
            grouped[key] = {
                'ticker': h['ticker'],
                'insider': h['insider'],
                'title': h['title'],
                'tx_type': h['tx_type'],
                'price': h['price'],
                'qty': h['qty'],
                'value': h['value'],
                'value_str': h['value_str'],
                'trade_date': h['trade_date'],
                'filing_date': h['filing_date'],
                'shares_owned': h.get('shares_owned', 0),
                'buys_count': 1,
                'buys': [single],
            }
        else:
            g = grouped[key]
            g['value'] += h['value']
            g['buys_count'] += 1
            g['buys'].append(single)
            # Keep most recent trade_date as the "latest" pointer, and use
            # that row's shares_owned as the current stake (OpenInsider reports
            # post-transaction holdings, so the most-recent filing has the
            # current count).
            if h['trade_date'] > g['trade_date']:
                g['trade_date'] = h['trade_date']
                g['filing_date'] = h['filing_date']
                g['price'] = h['price']
                g['qty'] = h['qty']
                g['shares_owned'] = h.get('shares_owned', g['shares_owned'])
            # Reformat aggregated value
            g['value_str'] = _fmt_money(g['value'])

    # Sort transactions within each group by date DESC
    for g in grouped.values():
        g['buys'].sort(key=lambda b: b['trade_date'], reverse=True)

    # Flag aggregations where the latest trade is within past 7 days as a
    # visual "šią savaitę" badge. Use date-level comparison (not datetime)
    # to avoid the boundary case where today-7d crosses an hour line and
    # drops a same-day-7-days-ago aggregate (Lisa Su 2026-05-13 vs 2026-05-20
    # 12:13 = False because of the time component).
    from datetime import datetime as _dt, timedelta as _td, date as _date
    week_cutoff_date = (_dt.now() - _td(days=7)).date()
    relevance_cutoff_date = (_dt.now() - _td(days=30)).date()
    for g in grouped.values():
        try:
            latest = _dt.strptime(g['trade_date'], '%Y-%m-%d').date()
            g['recent_week'] = latest >= week_cutoff_date
            g['_within_30d'] = latest >= relevance_cutoff_date
        except ValueError:
            g['recent_week'] = False
            g['_within_30d'] = False

    aggregated = list(grouped.values())
    # NO time-window filtering: per Radoslav, old info stays visible,
    # only new info gets added. Big insider trades like Musk's +$1B TSLA
    # buy (2025-09-12) or Bezos's $5.65B AMZN sells (2025-07-23) remain
    # relevant signal even months later. Mark stale ones (>90d) with a
    # visual badge so the reader knows it's historical context, not "today".
    stale_cutoff_date = (_dt.now() - _td(days=90)).date()
    for x in aggregated:
        try:
            latest = _dt.strptime(x['trade_date'], '%Y-%m-%d').date()
            x['is_stale'] = latest < stale_cutoff_date
        except ValueError:
            x['is_stale'] = False

    # Balance buys vs sells: split into pools, take top N of each by VALUE
    # so big sells (Lisa Su $163M, Bezos $5.65B) are never crowded out by
    # smaller recent sells (GRAB $300K). Recency is now just a visual badge,
    # not a sort key — value dominates.
    buys = sorted([x for x in aggregated if x['tx_type'] == 'buy'],
                  key=lambda x: -x['value'])
    sells = sorted([x for x in aggregated if x['tx_type'] == 'sell'],
                   key=lambda x: -x['value'])

    # Allocate: prefer 1/3 buys + 2/3 sells (buys are rare on watchlist).
    # If one pool is short, the other absorbs the extra slots.
    buy_quota = max(max_results // 3, 4)
    sell_quota = max_results - buy_quota
    buy_take = min(len(buys), buy_quota)
    sell_take = min(len(sells), sell_quota + (buy_quota - buy_take))
    selected = buys[:buy_take] + sells[:sell_take]

    # Final ordering: group by ticker (alphabetical), buys before sells inside
    # each ticker, then value DESC.
    selected.sort(key=lambda x: (
        x['ticker'],
        0 if x['tx_type'] == 'buy' else 1,
        -x['value'],
    ))

    # Show only the 3 MOST RECENT transactions individually. Everything older
    # gets compacted into a single summary line:
    #   "Nuo 2025-08-15 iki 2026-02-18 Bosworth pardavė 245K sh už $32.5M"
    # This keeps the visual short for high-frequency 10b5-1 sellers (Olivan
    # META 40 sandoriai, Huffman RDDT 33) while preserving the time-range +
    # cumulative qty + total value signal.
    for x in selected:
        all_buys = x.get('buys') or []
        # Re-sort by date DESC to identify "most recent N"
        all_buys.sort(key=lambda b: b.get('trade_date', ''), reverse=True)
        if len(all_buys) > 3:
            recent = all_buys[:3]
            older = all_buys[3:]
            # Compute summary stats for older bucket
            from_date = min(b['trade_date'] for b in older)
            to_date = max(b['trade_date'] for b in older)
            total_value = sum(b.get('value', 0) for b in older)
            # Total qty: best-effort parsing of qty strings like "12,345"
            total_qty = 0
            for b in older:
                q = (b.get('qty') or '').replace(',', '').replace('+', '').lstrip('-')
                try:
                    total_qty += int(q)
                except ValueError:
                    pass
            if total_qty >= 1_000_000:
                qty_str = f"{total_qty/1_000_000:.2f}M sh"
            elif total_qty >= 1_000:
                qty_str = f"{total_qty/1_000:.0f}K sh"
            else:
                qty_str = f"{total_qty:,} sh"
            x['buys'] = recent
            x['older_summary'] = {
                'count': len(older),
                'from': from_date,
                'to': to_date,
                'qty_str': qty_str,
                'value_str': _fmt_money_unsigned(total_value),
                'value_total': total_value,
            }
        else:
            x['older_summary'] = None
        x['buys_hidden'] = max(0, len(all_buys) - 3)
    return selected


def enrich_insider_with_holdings(entries: list) -> list:
    """Add current holdings context to each insider entry:
      - holdings_value_str: '$X.XM' = shares_owned × current price
      - pct_company_str: '0.42%' = shares_owned / shares_outstanding × 100
      - current_price: float (used for the value calculation)

    Batched per-ticker yfinance call to fetch current price + shares outstanding.
    """
    import concurrent.futures
    tickers = sorted({e['ticker'] for e in entries if e.get('ticker')})
    if not tickers:
        return entries

    def fetch_one(sym):
        try:
            t = yf.Ticker(sym)
            fi = getattr(t, 'fast_info', None)
            price = None
            shares_out = None
            if fi is not None:
                price = getattr(fi, 'last_price', None) or getattr(fi, 'lastPrice', None)
                shares_out = getattr(fi, 'shares', None)
            if not price or not shares_out:
                info = t.info or {}
                price = price or info.get('currentPrice') or info.get('regularMarketPrice')
                shares_out = shares_out or info.get('sharesOutstanding')
            return sym, float(price or 0), int(shares_out or 0)
        except Exception:
            return sym, 0.0, 0

    cache = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for sym, price, shares_out in ex.map(fetch_one, tickers):
            cache[sym] = (price, shares_out)

    for e in entries:
        price, shares_out = cache.get(e['ticker'], (0.0, 0))
        shares_owned = e.get('shares_owned', 0) or 0
        e['current_price'] = price
        holdings_val = shares_owned * price if (shares_owned > 0 and price > 0) else 0
        tx_val = e.get('value', 0) or 0
        # OpenInsider's "shares_owned" column on Form 4 captures only
        # DIRECT common-stock holdings AFTER the transaction. It misses
        # Class B founder shares (Tenev HOOD, Beck RKLB, Musk TSLA), RSUs,
        # trusts, LLC-held shares, and unexercised options. For founders
        # this dramatically undercounts the real stake.
        # Heuristic: if remaining direct holdings value is < the transaction
        # value, the count is clearly incomplete (you can't sell $100M of
        # stock and have $0.5M left if those were your only shares).
        # In that case, label the holdings as "direct only" to flag that
        # Class B / RSU / trust positions are excluded.
        partial = (tx_val > 0 and holdings_val > 0 and holdings_val < tx_val * 0.6)
        e['holdings_partial'] = partial
        if holdings_val > 0:
            e['holdings_value_str'] = _fmt_money_unsigned(holdings_val)
        else:
            e['holdings_value_str'] = ''
        # % of company: ONLY show if stake >= 1%. DO NOT REVERT.
        # Radoslav guidance (2x explicit, memory `feedback_form4_direct_only.md`):
        # Form 4 "shares_owned" captures DIRECT common stock only - misses
        # unvested RSU/PSU grants, options, Class B, trusts. For C-suite at
        # major tech (Lisa Su 0.23%, Pichai 0.03%, Anthony Noto 0.93%),
        # showing the direct-only % UNDERCOUNTS real economic stake 2-100x.
        # The "(be RSU/opcijų/PSU)" caveat is NOT enough - readers anchor
        # on the number, not the disclaimer. Showing 0.23% for Lisa Su is
        # actively misleading even with the caveat.
        # Only show % for >=1% stakes (Bezos 8.2%, Musk 13.6%, Cohen GME 8.6%,
        # ENPH Kothandaraman 1.4%) - at that scale, direct holdings represent
        # the majority of real economic interest and the % is informative.
        # Previous regression: commit 0667a0f restored % for all entries
        # citing "data going missing" - DO NOT do that again. Missing %
        # is correct, not a bug.
        if shares_owned > 0 and shares_out > 0 and not partial:
            pct = shares_owned / shares_out * 100
            if pct >= 1:
                e['pct_company_str'] = f"{pct:.1f}%"
            else:
                e['pct_company_str'] = ''
        else:
            e['pct_company_str'] = ''
        # Human-readable share count: 1,234,567 -> "1.23M"
        if shares_owned >= 1_000_000:
            e['shares_owned_str'] = f"{shares_owned/1_000_000:.2f}M"
        elif shares_owned >= 1_000:
            e['shares_owned_str'] = f"{shares_owned/1_000:.1f}K"
        elif shares_owned > 0:
            e['shares_owned_str'] = f"{shares_owned:,}"
        else:
            e['shares_owned_str'] = ''
    return entries


def fetch_insider_company_overview(tickers: list) -> dict:
    """For each ticker, return aggregate insider alignment signal:
      - insider_pct: total % of company held by all insiders combined
      - net_6mo_shares: net shares purchased (-sold) over last 6 months
      - buys_6mo / sells_6mo: gross figures
      - alignment: 'buying' / 'selling' / 'neutral' based on net direction

    Per Radoslav: brief should show how aligned insider intentions are with
    the company. Per-row direct holdings only tell part of the story; this
    aggregate level shows whether the leadership as a whole is voting with
    their wallets (buying) or unloading (selling) over a meaningful window.
    """
    import concurrent.futures
    out = {}

    def one(sym):
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            ip = t.insider_purchases
            insider_pct = info.get('heldPercentInsiders', 0) or 0
            buy_sh = sell_sh = net_sh = 0
            if ip is not None and not ip.empty:
                try:
                    buy_sh = float(ip.iloc[0, 1]) if len(ip) > 0 else 0
                except (TypeError, ValueError):
                    buy_sh = 0
                try:
                    sell_sh = float(ip.iloc[1, 1]) if len(ip) > 1 else 0
                except (TypeError, ValueError):
                    sell_sh = 0
                try:
                    net_sh = float(ip.iloc[2, 1]) if len(ip) > 2 else 0
                except (TypeError, ValueError):
                    net_sh = 0
            return sym, insider_pct, buy_sh, sell_sh, net_sh
        except Exception:
            return sym, 0, 0, 0, 0

    def fmt_sh(n):
        n_abs = abs(n)
        if n_abs >= 1_000_000:
            return f"{n_abs/1_000_000:.2f}M"
        if n_abs >= 1_000:
            return f"{n_abs/1_000:.0f}K"
        return f"{int(n_abs):,}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for sym, ipct, buy_sh, sell_sh, net_sh in ex.map(one, tickers):
            volume = buy_sh + sell_sh
            if volume > 0:
                net_pct = net_sh / volume
                if net_pct > 0.05:
                    alignment = 'buying'
                elif net_pct < -0.05:
                    alignment = 'selling'
                else:
                    alignment = 'neutral'
            else:
                alignment = 'none'
            out[sym] = {
                'insider_pct': ipct * 100,
                'insider_pct_str': f"{ipct*100:.2f}%" if ipct > 0 else '',
                'buys_6mo_str': fmt_sh(buy_sh),
                'sells_6mo_str': fmt_sh(sell_sh),
                'net_6mo_str': f"{'+' if net_sh >= 0 else '-'}{fmt_sh(net_sh)} sh",
                'net_6mo_raw': net_sh,
                'alignment': alignment,
            }
    return out


def _fmt_money_unsigned(v: float) -> str:
    """Format float to '$X', '$X.XM', '$X.XB' WITHOUT + sign (for holdings)."""
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def _fmt_money(v: float) -> str:
    """Format float to '+$X' / '+$X.XM' / '+$X.XB'."""
    if v >= 1_000_000_000:
        return f"+${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"+${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"+${v/1_000:.0f}K"
    return f"+${v:.0f}"


def fetch_mover_catalysts(mover_symbols: list, max_per: int = 1, max_total: int = 4,
                          hours_window: int = 24) -> list:
    """For top movers, search news that explains the move. Filtered for catalysts."""
    import concurrent.futures
    from datetime import datetime as dt, timezone, timedelta

    cutoff = dt.now(timezone.utc) - timedelta(hours=hours_window)

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


def fetch_youtube_videos(channels: list, hours_back: int = 48,
                         max_per_channel: int = 3, max_total: int = 12) -> list:
    """Pull latest videos from YouTube channels via RSS, filtered to recent window.

    Returns list of dicts: {video_id, title, channel, published_dt, description, views}
    sorted by published_dt desc. RSS is free and unauthenticated; no API key.
    Skip Shorts (under 90s, link contains /shorts/).
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    import xml.etree.ElementTree as _ET

    cutoff = _dt.now(_tz.utc) - _td(hours=hours_back)
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'yt': 'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }
    out = []
    for channel_id, channel_name in channels:
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"  warn: YT RSS {channel_name} status {r.status_code}")
                continue
            root = _ET.fromstring(r.content)
            count = 0
            for entry in root.findall('atom:entry', ns):
                if count >= max_per_channel:
                    break
                vid = entry.find('yt:videoId', ns)
                title = entry.find('atom:title', ns)
                pub = entry.find('atom:published', ns)
                link = entry.find('atom:link', ns)
                if vid is None or title is None or pub is None:
                    continue
                link_href = link.get('href', '') if link is not None else ''
                if '/shorts/' in link_href:
                    continue  # skip shorts
                try:
                    pub_dt = _dt.fromisoformat(pub.text.replace('Z', '+00:00'))
                except Exception:
                    continue
                if pub_dt < cutoff:
                    continue
                mg = entry.find('media:group', ns)
                desc_el = mg.find('media:description', ns) if mg is not None else None
                desc = desc_el.text if desc_el is not None and desc_el.text else ''
                stats = mg.find('media:community/media:statistics', ns) if mg is not None else None
                views = int(stats.get('views', 0)) if stats is not None else 0
                out.append({
                    'video_id': vid.text,
                    'title': title.text,
                    'channel': channel_name,
                    'published_dt': pub_dt,
                    'description': desc[:2000],
                    'views': views,
                    'link': link_href,
                })
                count += 1
        except Exception as e:
            print(f"  warn: YT RSS {channel_name} failed: {type(e).__name__}: {str(e)[:80]}")
            continue
    out.sort(key=lambda x: x['published_dt'], reverse=True)
    return out[:max_total]


def fetch_youtube_transcript(video_id: str, max_chars: int = 8000) -> str:
    """Fetch transcript via youtube-transcript-api in any available language.

    LLM synthesizer handles translation (Lithuanian output regardless of source lang).
    Empty string on hard failure (captions disabled, IP block, etc).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ''
    api = YouTubeTranscriptApi()
    last_err = None
    for langs in (['en', 'en-US', 'en-GB'], ['de', 'lt', 'fr', 'es', 'pl', 'ru'], None):
        try:
            if langs:
                t = api.fetch(video_id, languages=langs)
            else:
                tr_list = api.list(video_id)
                first = next(iter(tr_list), None)
                if first is None:
                    continue
                t = first.fetch()
            snippets = t.snippets if hasattr(t, 'snippets') else list(t)
            text = ' '.join(s.text.strip() for s in snippets if s.text)
            text = re.sub(r'\s+', ' ', text)
            if not text:
                continue
            if len(text) > max_chars:
                half = max_chars // 2
                text = text[:half] + ' [...] ' + text[-half:]
            return text
        except Exception as e:
            last_err = e
            continue
    if last_err:
        print(f"  warn: YT transcript {video_id} all attempts failed: {type(last_err).__name__}: {str(last_err)[:120]}")
    return ''


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
