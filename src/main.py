"""Daily briefing orchestrator. Run once per day."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import pytz

from fetch import (
    fetch_macro_events, fetch_earnings, fetch_watchlist_movers,
    fetch_crypto, fetch_index_snapshot, fetch_iv_metrics,
    fetch_market_news, fetch_geopolitics_news, fetch_mover_catalysts, fetch_quotes,
    fetch_insider_purchases, enrich_insider_with_holdings,
    fetch_insider_company_overview, fetch_reddit_discussions,
    enrich_news_with_summaries, fetch_watchlist_earnings_history,
    fetch_article_summary, fetch_reddit_comments,
    fetch_earnings_transcript, fetch_watchlist_catalysts,
    fetch_youtube_videos, fetch_youtube_transcript,
)
from llm import (
    batch_analyze_news, is_enabled as llm_is_enabled,
    extract_earnings_details, analyze_earnings_card,
    analyze_reddit_thread, analyze_macro_event,
    synthesize_youtube_insights, research_past_event_with_web,
    critique_manual_notes,
)
from render import render_html, html_to_png
from send import send_photo
from publish_web import save_briefing_html, regenerate_index
from watchlist import STOCKS, CRYPTO, FUTURES, AI_TICKERS, NEWS_TICKERS, YOUTUBE_CHANNELS

VILNIUS = pytz.timezone('Europe/Vilnius')

LT_MONTHS = {
    1: 'sausio', 2: 'vasario', 3: 'kovo', 4: 'balandžio', 5: 'gegužės',
    6: 'birželio', 7: 'liepos', 8: 'rugpjūčio', 9: 'rugsėjo',
    10: 'spalio', 11: 'lapkričio', 12: 'gruodžio',
}
LT_WEEKDAYS = {
    0: 'pirmadienis', 1: 'antradienis', 2: 'trečiadienis', 3: 'ketvirtadienis',
    4: 'penktadienis', 5: 'šeštadienis', 6: 'sekmadienis',
}


def format_date_lt(dt: datetime) -> str:
    return f"{dt.year} m. {LT_MONTHS[dt.month]} {dt.day} d., {LT_WEEKDAYS[dt.weekday()]}"


def build_takeaway(macro: list, earnings: list) -> str:
    high_impact_us = [e for e in macro if e['high_impact'] and e['country'] == 'US']
    if high_impact_us:
        top = high_impact_us[0]
        return f"{top['name']} ({top['time_local']}) - didžiausias šios dienos event'as."
    top_earnings = earnings[:1]
    if top_earnings:
        e = top_earnings[0]
        return f"Stebėk {e['symbol']} ({e['company'][:30]}) earnings - mcap {e['market_cap']}."
    macro_today = [e for e in macro if e['high_impact']]
    if macro_today:
        e = macro_today[0]
        return f"{e['name']} {e['time_local']} ({e['country']}) - svarbiausias rytojaus signalas."
    return "Tyli diena makro fronte - geras laikas peržiūrėti pozicijas ir planuoti."


def _load_manual_notes() -> list:
    """Load manual notes injected by Radoslav (or me) into data/manual_notes.json.

    Use case: Radoslav sends operational data, news, or context that he wants
    in tomorrow's briefing. We write to this file; pipeline picks it up next run.
    Notes expire automatically (expires_at field) so they don't haunt forever.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    path = Path(__file__).resolve().parent.parent / 'data' / 'manual_notes.json'
    if not path.exists():
        return []
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return []
    notes = data.get('notes', [])
    out = []
    now_utc = _dt.now(_tz.utc)
    for n in notes:
        exp = n.get('expires_at') or data.get('expires_at')
        if exp:
            try:
                exp_dt = _dt.fromisoformat(exp.replace('Z', '+00:00'))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=_tz.utc)
                if now_utc > exp_dt:
                    continue  # expired, skip
            except Exception:
                pass
        out.append(n)
    return out


def _build_placeholder_values(indices: list, crypto: list) -> dict:
    """Build {placeholder_name: formatted_value} from live market data.

    Layer 1 of the manual-notes anti-stale-data system. Pipeline pulls live
    futures + crypto, this builder maps them onto short names like 'wti',
    'brent', 'gold', 'btc' that manual_notes.json can reference via
    {{wti}} / {{brent}} placeholders. Substituting at runtime means I
    can't bake a stale "WTI $80" into a note - the system fills the
    actual live price every run.
    """
    from watchlist import PLACEHOLDER_SYMBOLS, PLACEHOLDER_CRYPTO
    sym_to_index = {i['symbol']: i for i in (indices or [])}
    # Crypto items use 'symbol' field like 'BTC', 'ETH' - normalize to lower.
    sym_to_crypto = {(c.get('symbol') or '').lower(): c for c in (crypto or [])}
    out = {}
    for name, sym in PLACEHOLDER_SYMBOLS.items():
        item = sym_to_index.get(sym)
        if not item or item.get('price') is None:
            continue
        price = item['price']
        # VIX/DXY render as plain numbers, others as $-prefixed.
        if name in ('vix', 'dxy'):
            out[name] = f"{price:.2f}"
        elif price >= 1000:
            out[name] = f"${price:,.2f}"
        else:
            out[name] = f"${price:.2f}"
        # Also expose change_pct as {name}_pct for headline use.
        cp = item.get('change_pct')
        if cp is not None:
            out[f"{name}_pct"] = f"{cp:+.2f}%"
    for name, _coin_id in PLACEHOLDER_CRYPTO.items():
        # Lookup by lowercase symbol (e.g. 'btc') rather than coin_id.
        item = sym_to_crypto.get(name)
        if not item or item.get('price') is None:
            continue
        price = item['price']
        if price >= 1000:
            out[name] = f"${price:,.0f}"
        else:
            out[name] = f"${price:,.2f}"
        cp = item.get('change_pct')
        if cp is not None:
            out[f"{name}_pct"] = f"{cp:+.2f}%"
    return out


FORBIDDEN_META_PATTERNS = [
    # AI meta-references / apologies that must never reach the published brief.
    # If any of these match, _check_no_meta strips the manual note and logs loud.
    r'\batsipra(?:šau|šom|šome)\b',
    r'\bankstesn[eė] klaid',
    r'\bmano klaid',
    r'\bAI klaid',
    r'\b(?:asistent|modelis)\b',
    r'\bpataisym',
    r'\bpatikslin',
    r'\bperdarom?u?\b',
    r'\bkaip min[eė]jau\b',
    r'\bkaip raš[ai]?u anksč',
    r'\b(?:kontekstas|patikslinimas)\s*[-:—]\s*atsipra',
    r"\bne ['\"][^'\"]+['\"]\s*-\s*(?:active|tikra)",  # "ne 'X' - active" hidden correction
]


def _check_no_meta(notes: list) -> list:
    """Programmatic safety net for the no-meta-in-published rule.

    Scans each manual note's text fields for AI-meta phrases. If any forbidden
    pattern matches, the note is REMOVED from the published set and a loud
    warning is printed - better to ship a brief without that note than to ship
    a note that says 'atsiprašau už ankstesnę klaidą' to paying members.

    Memory rule alone wasn't enough (kept slipping through). This is the code
    backstop per the 'Sisteminės klaidos - kode, ne atminty' rule.
    """
    import re
    compiled = [re.compile(p, re.I) for p in FORBIDDEN_META_PATTERNS]
    clean = []
    for n in notes:
        haystack = ' '.join(str(n.get(f, '')) for f in ('headline', 'analysis', 'long_term'))
        for m in n.get('metrics', []):
            haystack += ' ' + ' '.join(str(m.get(f, '')) for f in ('label', 'value', 'change'))
        matched = None
        for pat in compiled:
            if pat.search(haystack):
                matched = pat.pattern
                break
        if matched:
            print(f"  Manual notes BLOCKED ({n.get('ticker','?')}): meta-text matched /{matched}/ - removed from publish")
            continue
        clean.append(n)
    return clean


def _substitute_placeholders(notes: list, values: dict) -> tuple:
    """Walk manual_notes and replace {{placeholder}} tokens with live values.

    Applies to: headline, analysis, long_term text fields + each metric's
    label/value/change. Returns (updated_notes, substitution_log) so the
    pipeline can log what was filled in and what was missing.
    """
    import re
    log = {'filled': [], 'missing': []}
    pattern = re.compile(r'\{\{(\w+)\}\}')

    def sub_one(text):
        if not isinstance(text, str):
            return text

        def replace(m):
            key = m.group(1).lower()
            if key in values:
                log['filled'].append(key)
                return values[key]
            log['missing'].append(key)
            return m.group(0)  # leave token intact - signals an unfilled var
        return pattern.sub(replace, text)

    out = []
    for n in notes:
        new_n = dict(n)
        for field in ('headline', 'analysis', 'long_term'):
            if field in new_n:
                new_n[field] = sub_one(new_n[field])
        new_metrics = []
        for m in new_n.get('metrics', []):
            new_m = dict(m)
            for f in ('label', 'value', 'change'):
                if f in new_m:
                    new_m[f] = sub_one(new_m[f])
            new_metrics.append(new_m)
        new_n['metrics'] = new_metrics
        out.append(new_n)
    # Dedup logs
    log['filled'] = sorted(set(log['filled']))
    log['missing'] = sorted(set(log['missing']))
    return out, log


def _load_whatsapp_channel() -> list:
    """Load WhatsApp channel messages from data/whatsapp_channel.json.

    Scraped locally by scripts/wa_refresh.py from CaktusJxck and other
    followed channels. Returns list of {text, time, channel} dicts.
    Empty if file missing or older than 24h.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    path = Path(__file__).resolve().parent.parent / 'data' / 'whatsapp_channel.json'
    if not path.exists():
        return []
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return []
    try:
        gen = _dt.fromisoformat(data.get('generated_at', '').replace('Z', '+00:00'))
        age_h = (_dt.now(_tz.utc) - gen).total_seconds() / 3600
        if age_h > 24:
            print(f"  warn: whatsapp_channel.json is {age_h:.1f}h old (stale)")
            return []
    except Exception:
        pass
    msgs = data.get('messages', [])
    # Filter to messages with meaningful text (skip empty/time-only)
    return [m for m in msgs if m.get('text', '').strip() and len(m['text'].strip()) > 10]


def _load_ibkr_news() -> list:
    """Load IBKR-sourced news from data/ibkr_news.json.

    Returns list of {ticker, headline, provider, time, pub_dt} entries,
    deserialized + filtered to ≤36h old. Empty if file missing/stale.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    path = Path(__file__).resolve().parent.parent / 'data' / 'ibkr_news.json'
    if not path.exists():
        return []
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return []
    try:
        gen = _dt.fromisoformat(data.get('generated_at', '').replace('Z', '+00:00'))
        if _dt.now(_tz.utc) - gen > _td(hours=24):
            return []
    except Exception:
        pass
    items = data.get('items', [])
    out = []
    for item in items:
        t = item.get('time', '')
        try:
            pub_dt = _dt.fromisoformat(t.replace('Z', '+00:00'))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=_tz.utc)
        except Exception:
            pub_dt = None
        item['pub_dt'] = pub_dt
        out.append(item)
    return out


def _load_ibkr_iv() -> dict:
    """Load IBKR-sourced IV from data/iv_metrics.json (refreshed locally).

    Returns {symbol: iv_pct} dict. Empty if file missing or older than 24h.
    main() merges this on top of in-process Black-Scholes IV — IBKR values
    win where present, BS fills the rest.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    path = Path(__file__).resolve().parent.parent / 'data' / 'iv_metrics.json'
    if not path.exists():
        return {}
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return {}
    try:
        gen = _dt.fromisoformat(data.get('generated_at', '').replace('Z', '+00:00'))
        if _dt.now(_tz.utc) - gen > _td(hours=24):
            return {}
    except Exception:
        pass
    return {m['symbol']: m['iv'] for m in data.get('metrics', []) if 'symbol' in m and 'iv' in m}


def _load_x_posts() -> list:
    """Load X posts from data/x_posts.json (refreshed locally).

    Empty list if file missing or older than 48h (stale).
    Deserializes pub_dt back to datetime.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    path = Path(__file__).resolve().parent.parent / 'data' / 'x_posts.json'
    if not path.exists():
        return []
    try:
        data = _json.loads(path.read_text())
    except Exception:
        return []
    try:
        gen = _dt.fromisoformat(data.get('generated_at', '').replace('Z', '+00:00'))
        age = _dt.now(_tz.utc) - gen
        if age > _td(hours=48):
            print(f"  warn: x_posts.json is {age.total_seconds()/3600:.1f}h old (stale)")
            return []
    except Exception:
        pass
    posts = data.get('posts', [])
    for p in posts:
        if 'pub_dt' in p and isinstance(p['pub_dt'], str):
            try:
                p['pub_dt'] = _dt.fromisoformat(p['pub_dt'].replace('Z', '+00:00'))
            except Exception:
                p['pub_dt'] = None
    return posts


def _safe(label, fn, fallback):
    """Run a fetcher with fallback on exception. Don't let one source kill the briefing."""
    try:
        return fn()
    except Exception as e:
        print(f"  warn: {label} failed ({type(e).__name__}: {str(e)[:80]})")
        return fallback


def _detect_ticker(title: str, watchlist: list) -> str:
    """Scan title for any watchlist ticker. Returns first match or empty."""
    import re as _re
    if not title:
        return ''
    # Match TICKER as whole word, optionally with $ prefix (e.g. $HIMS or HIMS)
    upper = title.upper()
    for sym in watchlist:
        if _re.search(rf'(?<![A-Z])\$?{_re.escape(sym)}(?![A-Z])', upper):
            return sym
    return ''


def _earnings_extracted_to_metrics(extracted: dict) -> list:
    """Convert earnings extracted dict to metrics-grid cells (label/value/note)."""
    metrics = []
    if extracted.get('revenue_actual'):
        notes = []
        if extracted.get('revenue_estimate'):
            notes.append(f"vs est {extracted['revenue_estimate']}")
        if extracted.get('revenue_yoy_change'):
            notes.append(f"{extracted['revenue_yoy_change']} YoY")
        cell = {'label': 'Revenue', 'value': extracted['revenue_actual']}
        if notes:
            cell['note'] = ' · '.join(notes)
        metrics.append(cell)
    if extracted.get('guidance_next_q_rev'):
        metrics.append({'label': 'Next Q guide', 'value': extracted['guidance_next_q_rev']})
    if extracted.get('guidance_fy_rev'):
        cell = {'label': 'FY guide', 'value': extracted['guidance_fy_rev']}
        if extracted.get('guidance_ebitda_fy'):
            cell['note'] = f"EBITDA {extracted['guidance_ebitda_fy']}"
        metrics.append(cell)
    elif extracted.get('guidance_ebitda_fy'):
        metrics.append({'label': 'FY EBITDA', 'value': extracted['guidance_ebitda_fy']})
    if extracted.get('stock_reaction'):
        metrics.append({'label': 'Reakcija', 'value': extracted['stock_reaction']})
    return metrics


def _dedup_news_by_ticker(news_items: list, watchlist: list) -> list:
    """Merge news with same ticker into one entry; extra articles become extra_links.

    First item per ticker is kept (highest score in list order). Others contribute
    link + publisher into 'extra_links'. Items without a detected ticker pass through.
    """
    by_ticker = {}
    out = []
    for n in news_items:
        tk = (n.get('ticker') or '').upper() or _detect_ticker(n.get('title', ''), watchlist)
        if tk:
            n['ticker'] = tk
            if tk in by_ticker:
                primary = by_ticker[tk]
                primary.setdefault('extra_links', []).append({
                    'title': n.get('title', '')[:120],
                    'link': n.get('link', ''),
                    'publisher': n.get('publisher', ''),
                })
                continue
            by_ticker[tk] = n
        out.append(n)
    return out


def main():
    now = datetime.now(VILNIUS)

    # Twice-daily runs: 09:00 Vilnius (morning preview) + 22:00 Vilnius
    # (evening recap with same-day actuals). Other hours skipped.
    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and now.hour not in (9, 22):
        print(f"Scheduled run at {now.strftime('%H:%M')} Vilnius - skipping (only run at 09:xx or 22:xx).")
        sys.exit(0)

    date_str = now.strftime('%Y-%m-%d')
    print(f"[{now.strftime('%H:%M:%S')}] Building briefing for {date_str}...")

    print("  Fetching macro events...")
    macro = _safe('macro', lambda: fetch_macro_events(date_str), [])
    print(f"    -> {len(macro)} events")

    print("  Fetching earnings (>=$500B mcap OR in watchlist)...")
    earnings = _safe('earnings',
                     lambda: fetch_earnings(date_str, min_market_cap_b=500.0, watchlist_symbols=STOCKS),
                     [])
    print(f"    -> {len(earnings)} companies")

    print("  Fetching watchlist earnings history (recent 24h + upcoming 14d)...")
    wl_earnings = _safe('watchlist earnings',
                        lambda: fetch_watchlist_earnings_history(STOCKS, days_back=1, days_fwd=14),
                        {'recent': [], 'upcoming': []})
    print(f"    -> {len(wl_earnings['recent'])} recent, {len(wl_earnings['upcoming'])} upcoming")

    print("  Fetching indices/futures/VIX...")
    indices = _safe('indices', lambda: fetch_index_snapshot(FUTURES), [])
    print(f"    -> {len(indices)} indices")

    print("  Fetching watchlist movers (with pre/after-hours)...")
    watchlist = _safe('watchlist movers',
                      lambda: fetch_watchlist_movers(STOCKS, top_n=5, include_extended=True),
                      {'gainers': [], 'losers': []})
    print(f"    -> {len(watchlist['gainers'])} gainers, {len(watchlist['losers'])} losers")

    print("  Fetching crypto...")
    crypto = _safe('crypto', lambda: fetch_crypto(CRYPTO), [])
    print(f"    -> {len(crypto)} coins")

    print("  Fetching AI sector quotes (with pre/after-hours)...")
    ai_quotes_raw = _safe('AI quotes', lambda: fetch_quotes(AI_TICKERS, include_extended=True), [])
    # Sort by extended change when available, else regular - largest absolute move first
    ai_quotes = sorted(ai_quotes_raw,
                       key=lambda x: abs(x.get('extended_change_pct', x['change_pct'])),
                       reverse=True)[:8]
    print(f"    -> {len(ai_quotes)} AI tickers")

    print("  Fetching IV metrics (option-selling opportunities)...")
    iv_data = _safe('IV', lambda: fetch_iv_metrics(STOCKS), [])
    # Merge IBKR IV (data/iv_metrics.json from local refresh) on top — IBKR wins
    # when present (most-active tickers), Black-Scholes covers the long tail.
    ibkr_iv = _load_ibkr_iv()
    if ibkr_iv:
        ibkr_count = 0
        for row in iv_data:
            if row['symbol'] in ibkr_iv:
                row['iv'] = ibkr_iv[row['symbol']]
                row['source'] = 'IBKR'
                ibkr_count += 1
            else:
                row['source'] = 'BS'
        iv_data.sort(key=lambda x: x['iv'], reverse=True)
        print(f"    merged IBKR overrides for {ibkr_count}/{len(iv_data)} tickers")
    high_iv = iv_data[:8]
    print(f"    -> {len(iv_data)} tickers ranked, top {len(high_iv)} shown")

    print("  Fetching Reddit discussions (r/stocks, r/options, r/StockMarket)...")
    reddit_posts = _safe('Reddit', lambda: fetch_reddit_discussions(max_total=6, min_score=100), [])
    print(f"    -> {len(reddit_posts)} posts")

    # X posts come from data/x_posts.json — refreshed locally by scripts/x_refresh.py
    # since X binds sessions to IP and rejects GH Actions datacenter requests.
    x_posts = _load_x_posts()
    print(f"  Loaded {len(x_posts)} X posts from data/x_posts.json")

    # IBKR news — pre-filtered market-moving headlines from Dow Jones + Briefing
    # Refreshed locally by scripts/iv_refresh.py (twice daily via launchd).
    ibkr_news = _load_ibkr_news()
    print(f"  Loaded {len(ibkr_news)} IBKR headlines from data/ibkr_news.json")
    wa_messages = _load_whatsapp_channel()
    print(f"  Loaded {len(wa_messages)} WhatsApp channel messages from data/whatsapp_channel.json")

    # Manual notes - explicit content Radoslav (or I) want in the next briefing,
    # injected via data/manual_notes.json with auto-expiry. Outlives single
    # conversations and survives the GH Actions pipeline boundary.
    manual_notes = _load_manual_notes()
    print(f"  Loaded {len(manual_notes)} manual notes from data/manual_notes.json")

    # Layer 1 of anti-stale-data: substitute {{wti}}, {{brent}}, {{gold}},
    # {{vix}}, {{btc}}, etc. placeholders in manual_notes with LIVE prices.
    # Manual notes should never hard-code prices that drift - the substitution
    # engine fills them at run time from the same fetch_index_snapshot data
    # the dashboard uses, guaranteeing alignment.
    placeholder_values = _build_placeholder_values(indices, crypto)
    manual_notes, _ph_log = _substitute_placeholders(manual_notes, placeholder_values)
    if _ph_log['filled']:
        print(f"  Manual notes: substituted live values for {', '.join(_ph_log['filled'])}")
    if _ph_log['missing']:
        print(f"  Manual notes WARN: unfilled placeholders {', '.join(_ph_log['missing'])}")

    # Programmatic backstop for the no-meta-in-published rule. Any note that
    # mentions "atsiprašau", "ankstesnė klaida", "patikslinimas" etc. is dropped
    # so it cannot reach paying Discord members. Memory rule alone wasn't
    # enough (kept slipping through), so this is the systemic fix.
    _pre_count = len(manual_notes)
    manual_notes = _check_no_meta(manual_notes)
    if len(manual_notes) < _pre_count:
        print(f"  Manual notes: dropped {_pre_count - len(manual_notes)} note(s) for AI-meta content")

    # YouTube synthesis: pull recent videos from finance channels, fetch transcripts,
    # synthesize into "personal thoughts" prose (no source attribution shown).
    print("  Fetching YouTube videos (last 48h, finance channels)...")
    yt_videos = _safe('YouTube RSS',
                      lambda: fetch_youtube_videos(YOUTUBE_CHANNELS, hours_back=48,
                                                    max_per_channel=2, max_total=10),
                      [])
    print(f"    -> {len(yt_videos)} videos found")
    if yt_videos:
        print("  Fetching YouTube transcripts...")
        for v in yt_videos:
            v['transcript'] = _safe(f"transcript {v['video_id']}",
                                     lambda vid=v['video_id']: fetch_youtube_transcript(vid, max_chars=6000),
                                     '')
        # Keep videos with usable content (either transcript or rich description)
        yt_videos = [v for v in yt_videos
                     if (v.get('transcript') and len(v['transcript']) > 500)
                     or len(v.get('description', '')) > 300]
        # Prefer top 5 most recent with transcripts
        yt_videos.sort(key=lambda x: (1 if x.get('transcript') else 0, x['published_dt']), reverse=True)
        yt_videos = yt_videos[:6]
        tx_count = sum(1 for v in yt_videos if v.get('transcript'))
        print(f"    -> {len(yt_videos)} kept ({tx_count} with transcript)")

    print("  Fetching insider activity (watchlist, since 2025-01-01, aggregated by insider)...")
    insider = _safe('insider',
                    lambda: fetch_insider_purchases(STOCKS, days=730, min_value=10_000, max_results=30),
                    [])
    print(f"    -> {len(insider)} watchlist insider entries")
    if insider:
        print("  Enriching insider entries with holdings context (shares × price, % of company)...")
        insider = _safe('insider holdings', lambda: enrich_insider_with_holdings(insider), insider)
        enriched = sum(1 for x in insider if x.get('holdings_value_str'))
        print(f"    -> {enriched}/{len(insider)} entries enriched with holdings")
        # Per-ticker company-level insider alignment: total insider % + net 6mo
        # direction. Attach to every row so the template can show a per-group
        # header summarizing whether leadership is collectively buying or
        # selling (= alignment signal Radoslav wants).
        print("  Fetching per-ticker insider alignment overview (6mo net + total insider %)...")
        unique_tickers = sorted({x['ticker'] for x in insider})
        overview = _safe('insider overview',
                         lambda: fetch_insider_company_overview(unique_tickers), {})
        for x in insider:
            x['company_overview'] = overview.get(x['ticker'], {})
        print(f"    -> overview for {len(overview)} tickers")

    # News filtering: TODAY's news + weekend catch-up on Mondays.
    # Per Radoslav: yesterday's news gone, only fresh items each day - BUT
    # Monday morning must cover Friday US close through weekend (otherwise
    # weekend developments like geopolitical summits, weekend earnings, or
    # Sunday futures action would all be filtered out).
    midnight_vilnius = now.replace(hour=0, minute=0, second=0, microsecond=0)
    weekday = now.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    if weekday == 0:  # Monday: stretch back to Friday's Vilnius midnight = 3 days
        cutoff_dt = midnight_vilnius - timedelta(days=3)
        print(f"  Monday detected - weekend catch-up window enabled")
    elif weekday == 5:  # Saturday (shouldn't run scheduled, but manual)
        cutoff_dt = midnight_vilnius - timedelta(days=1)
    elif weekday == 6:  # Sunday (shouldn't run scheduled, but manual)
        cutoff_dt = midnight_vilnius - timedelta(days=2)
    else:  # Tue-Fri: just since today's Vilnius midnight
        cutoff_dt = midnight_vilnius
    news_hours = max(int((now - cutoff_dt).total_seconds() / 3600) + 1, 6)
    print(f"  News window: last {news_hours}h (since {cutoff_dt.strftime('%a %m-%d %H:%M')} Vilnius)")

    # QUALITY OVER QUANTITY: drop generic market_news RSS fetch entirely.
    # It surfaces random unrelated stories (ice cream stocks, Australian
    # grocery lawsuits, etc) that have nothing to do with Radoslav's
    # watchlist. BUT geopolitics/macro broad-impact news (Iran-US, OPEC,
    # Fed, Strait of Hormuz, war escalation) are mandatory even without
    # a watchlist ticker - those come from fetch_geopolitics_news with
    # a strict keyword gate.
    market_news = []
    # Geopolitics ALWAYS pulls 48h window: war/OPEC/Fed events often break
    # overnight/weekend and the impact persists across days even if the
    # tight "today only" filter would have dropped them.
    print("  Fetching geopolitics + macro broad-impact news (48h, strict keyword gate)...")
    geopol_news = _safe('geopolitics news',
                        lambda: fetch_geopolitics_news(max_total=4, hours_window=48),
                        [])
    print(f"    -> {len(geopol_news)} geopolitics items")

    print("  Fetching mover catalysts (today only)...")
    big_movers = [m['symbol'] for m in (watchlist['gainers'] + watchlist['losers'])
                  if abs(m['change_pct']) >= 5.0]
    mover_news = _safe('mover catalysts',
                       lambda: fetch_mover_catalysts(big_movers, max_per=1, max_total=4,
                                                     hours_window=news_hours),
                       [])
    print(f"    -> {len(mover_news)} mover catalysts (from {len(big_movers)} big movers)")

    print("  Fetching watchlist catalysts (today only - M&A, FDA, lawsuits, buybacks)...")
    wl_catalysts = _safe('watchlist catalysts',
                         lambda: fetch_watchlist_catalysts(STOCKS, max_total=12,
                                                            hours_window=news_hours),
                         [])
    print(f"    -> {len(wl_catalysts)} watchlist catalyst items")

    # Merge: watchlist catalysts > mover catalysts > geopolitics.
    # Watchlist catalysts surface M&A/FDA on specific tickers regardless of price move.
    # Geopolitics tied to MACRO ticker (no specific stock) - keyword-gated so
    # only war/Iran/OPEC/Fed broad-impact items get through.
    seen_titles = set()
    def _add_unique(out, items):
        for n in items:
            k = n['title'].lower()[:60]
            if k in seen_titles:
                continue
            seen_titles.add(k)
            out.append(n)
        return out
    news = []
    _add_unique(news, wl_catalysts)
    _add_unique(news, mover_news)
    _add_unique(news, geopol_news)
    news = _dedup_news_by_ticker(news, STOCKS)
    news = news[:12]

    print("  Enriching news with article summaries...")
    news = _safe('enrich news', lambda: enrich_news_with_summaries(news), news)
    summary_count = sum(1 for n in news if n.get('summary'))
    print(f"    -> {summary_count}/{len(news)} enriched")

    if llm_is_enabled():
        print("  LLM analyzing news (Lithuanian + structured metrics)...")
        news = _safe('LLM news analysis', lambda: batch_analyze_news(news), news)
        # Filter to only news with successful LLM analysis - no English fallbacks
        news = [n for n in news if n.get('llm_analysis')]
        print(f"    -> {len(news)} news kept (with LLM analysis)")

        if wl_earnings['recent']:
            print("  LLM enriching recent earnings (transcript + guidance + analysis)...")
            for e in wl_earnings['recent']:
                # Prefer Motley Fool transcript (rich management quotes + TAKEAWAYS).
                # Fall back to related news article body if transcript not available.
                transcript = _safe(f"transcript {e['symbol']}",
                                    lambda sym=e['symbol']: fetch_earnings_transcript(sym, max_chars=5000),
                                    '')
                article_body = transcript
                if not article_body:
                    related_news = next(
                        (n for n in news if e['symbol'].upper() in (n.get('title', '').upper() + ' ' + n.get('ticker', '').upper())),
                        None,
                    )
                    if related_news and related_news.get('summary'):
                        article_body = related_news['summary']
                    elif related_news and related_news.get('link'):
                        article_body = _safe('article body', lambda: fetch_article_summary(related_news['link'], max_chars=2000), '')
                e['has_transcript'] = bool(transcript)
                if article_body:
                    e['extracted'] = _safe(f"extract {e['symbol']}",
                                            lambda body=article_body: extract_earnings_details(e['symbol'], body),
                                            {})
                else:
                    e['extracted'] = {}
                analysis_result = _safe(f"analyze {e['symbol']}",
                                         lambda: analyze_earnings_card(
                                             e['symbol'], e['eps_actual'], e['eps_estimate'],
                                             e.get('extracted', {})
                                         ), {'short_term': '', 'long_term': ''})
                # Backward compat: if old-style string returned, wrap it
                if isinstance(analysis_result, str):
                    analysis_result = {'short_term': analysis_result, 'long_term': ''}
                e['analysis_short_term'] = analysis_result.get('short_term', '')
                e['analysis_long_term'] = analysis_result.get('long_term', '')
                # Keep e['analysis'] as legacy single-string for templates not yet updated
                e['analysis'] = e['analysis_short_term']
                e['extracted_metrics'] = _earnings_extracted_to_metrics(e.get('extracted', {}))
            print(f"    -> {sum(1 for e in wl_earnings['recent'] if e.get('analysis_short_term'))} cards enriched")

        # Auto-research: any past-time high-impact event WITHOUT actual data
        # gets filled via Anthropic web_search tool. Critical guarantee:
        # pipeline NEVER leaves a past-time high-impact event with "actual=-".
        # (This is what made Fed Chair vote show empty actual on 2026-05-13.)
        now_hhmm = now.strftime('%H:%M')
        past_missing = [e for e in macro
                        if e.get('high_impact')
                        and not e.get('actual')
                        and e.get('country') in ('US', 'EZ')
                        and e.get('time_local', '99:99') <= now_hhmm]
        if past_missing:
            print(f"  Auto-researching {len(past_missing)} past-time events missing actual data...")
            for e in past_missing[:4]:
                researched = _safe(f"web research {e.get('name','')}",
                                    lambda ev=e: research_past_event_with_web(ev), {})
                if researched.get('actual'):
                    e['actual'] = researched['actual']
                if researched.get('llm_analysis'):
                    e['llm_analysis'] = researched['llm_analysis']
                if researched.get('actual') or researched.get('llm_analysis'):
                    print(f"    + filled {e['name']}: actual={researched.get('actual','')[:40]}")

        # LLM commentary for high-impact US/EZ macro events with actual values
        # (now including auto-researched ones from previous step).
        high_impact_with_actual = [e for e in macro
                                    if e.get('high_impact')
                                    and e.get('actual')
                                    and e.get('country') in ('US', 'EZ')
                                    and not e.get('llm_analysis')]  # skip already-analyzed
        if high_impact_with_actual:
            print(f"  LLM commenting on {len(high_impact_with_actual)} high-impact macro events...")
            for e in high_impact_with_actual[:4]:
                e['llm_analysis'] = _safe(f"macro LLM {e.get('name','')}",
                                            lambda ev=e: analyze_macro_event(ev), '')
            commented = sum(1 for e in high_impact_with_actual if e.get('llm_analysis'))
            print(f"    -> {commented}/{len(high_impact_with_actual[:4])} events with commentary")

        # YouTube synthesis: combine all video transcripts into one narrative.
        # Pass live market context to prevent stale-data hallucination (e.g.
        # LLM citing S&P 500 5700 when actual is 7500).
        # ALSO pass insider signals and manual notes as enrichment context -
        # when GH Actions can't fetch transcripts (YouTube blocks datacenter
        # IPs), the synthesis falls back to titles+descriptions which is thin.
        # Insider data + manual notes give the LLM substance (e.g., "SOFI CEO
        # Anthony Noto buying $2M" is a signal that transforms a generic SOFI
        # narrative into a contrarian take).
        yt_synthesis = ''
        # Check for custom (pre-approved) synthesis text. Per workflow rule
        # (memory: feedback_synthesis_approval), synthesis text must be shown
        # to Radoslav for approval before publishing. If a custom file exists
        # and is fresh (<48h), use it directly instead of LLM generation.
        custom_path = Path(__file__).resolve().parent.parent / 'data' / 'custom_synthesis.txt'
        if custom_path.exists():
            from datetime import datetime as _cdt, timezone as _ctz, timedelta as _ctd
            age_h = (_cdt.now(_ctz.utc) - _cdt.fromtimestamp(
                custom_path.stat().st_mtime, tz=_ctz.utc)).total_seconds() / 3600
            if age_h <= 48:
                raw_synth = custom_path.read_text().strip()
                # Substitute {{wti}} {{brent}} {{btc}} etc. with live prices so
                # the approved text never ships stale numbers. Same engine as
                # manual_notes. Per memory rule: prices must be live, never
                # hardcoded in approved synthesis text.
                _synth_note = [{'headline': raw_synth, 'metrics': [], 'analysis': '', 'long_term': ''}]
                _synth_out, _synth_log = _substitute_placeholders(_synth_note, placeholder_values)
                yt_synthesis = _synth_out[0]['headline']
                print(f"  Using pre-approved custom synthesis ({len(yt_synthesis)} chars, {age_h:.1f}h old)")
                if _synth_log['filled']:
                    print(f"    -> live prices filled: {', '.join(_synth_log['filled'])}")
            else:
                print(f"  Custom synthesis expired ({age_h:.1f}h old), using LLM generation")
        if not yt_synthesis and yt_videos:
            market_ctx = {'indices': indices, 'crypto': crypto}
            # Build enrichment context from insider + manual_notes for the LLM
            insider_context = []
            for x in insider:
                tag = 'PERKA' if x['tx_type'] == 'buy' else 'PARDUODA'
                ov = x.get('company_overview', {})
                align = ov.get('alignment', '')
                insider_context.append(
                    f"  {x['ticker']} {x['insider']} ({x['title']}) {tag} {x['value_str']}"
                    f" · insider'iai {ov.get('insider_pct_str', '?')} kompanijos"
                    f" · 6mo net: {ov.get('alignment', '?').upper()}"
                )
            notes_context = []
            for n in manual_notes:
                notes_context.append(f"  {n.get('ticker','?')}: {n.get('headline','')}")
            enrichment = ''
            if insider_context:
                enrichment += '\n\nINSIDER ACTIVITY (papildomas kontekstas - kas perka/parduoda):\n'
                enrichment += '\n'.join(insider_context[:20])
            if notes_context:
                enrichment += '\n\nMANUAL NOTES (šios dienos akcentai):\n'
                enrichment += '\n'.join(notes_context)
            if wa_messages:
                enrichment += '\n\nWHATSAPP CHANNEL NEWS (CaktusJxck - real-time market headlines):\n'
                for wm in wa_messages[:25]:
                    enrichment += f"  [{wm.get('time','')}] {wm['text'][:200]}\n"
            # Inject enrichment into videos as a pseudo-video for the LLM
            if enrichment:
                yt_videos_enriched = list(yt_videos) + [{
                    'title': 'Papildomas kontekstas: insider activity + dienos akcentai',
                    'description': enrichment,
                    'transcript': '',
                    'video_id': '_enrichment_',
                    'published_dt': '',
                }]
            else:
                yt_videos_enriched = yt_videos
            tx_count = sum(1 for v in yt_videos if v.get('transcript') and len(v['transcript']) > 200)
            print(f"  LLM synthesizing {len(yt_videos)} YouTube videos ({tx_count} with transcripts)"
                  f" + enrichment context into investor narrative...")
            yt_synthesis = _safe('YouTube synthesis',
                                  lambda: synthesize_youtube_insights(yt_videos_enriched, STOCKS, market_ctx), '')
            print(f"    -> {len(yt_synthesis)} chars of synthesis")

        if reddit_posts:
            print("  LLM analyzing Reddit threads (top comments → sentiment summary)...")
            for p in reddit_posts:
                comments = _safe(f"reddit comments {p['sub']}",
                                  lambda url=p.get('link', ''): fetch_reddit_comments(url, top_n=8),
                                  [])
                if comments:
                    p['llm_analysis'] = _safe(f"reddit LLM {p['sub']}",
                                               lambda t=p['title'], c=comments: analyze_reddit_thread(t, c),
                                               '')
                else:
                    p['llm_analysis'] = ''
            enriched = sum(1 for p in reddit_posts if p.get('llm_analysis'))
            print(f"    -> {enriched}/{len(reddit_posts)} threads enriched")
    else:
        print("  LLM disabled (no ANTHROPIC_API_KEY) - skipping analysis")
        yt_synthesis = ''

    country_priority = {'US': 0, 'EZ': 1, 'DE': 2, 'GB': 3, 'CN': 4, 'JP': 5, 'LT': 6}
    macro_sorted = sorted(
        macro,
        key=lambda e: (
            not e['high_impact'],
            country_priority.get(e['country'], 99),
            e['time_local'],
        ),
    )[:8]
    earnings_top = earnings[:10]

    # Layer 2 of anti-stale-data: LLM critic compares manual_notes claims
    # against live market_context + today's date. Logs discrepancies fail-loud.
    # We don't BLOCK on high severity (yet) - first run is observability only,
    # so I can see what the critic catches without breaking the brief delivery.
    critique_result = {'discrepancies': [], 'date_issues': [], 'severity': 'ok'}
    if manual_notes and llm_is_enabled():
        print("  LLM critic: checking manual_notes for stale prices / date drift...")
        critique_ctx = {'indices': indices, 'crypto': crypto}
        today_lt = f"{now.year}-{now.month:02d}-{now.day:02d} ({format_date_lt(now)})"
        critique_result = _safe('manual notes critic',
                                lambda: critique_manual_notes(manual_notes, critique_ctx,
                                                              today_lt),
                                {'discrepancies': [], 'date_issues': [], 'severity': 'ok'})
        d_count = len(critique_result.get('discrepancies', []))
        date_count = len(critique_result.get('date_issues', []))
        print(f"    -> {d_count} price discrepancies, {date_count} date issues, severity={critique_result.get('severity')}")
        for d in critique_result.get('discrepancies', []):
            print(f"       PRICE: '{d.get('claim','?')}' vs live '{d.get('live','?')}' ({d.get('severity','?')})")
        for d in critique_result.get('date_issues', []):
            print(f"       DATE:  '{d.get('claim','?')}' vs actual '{d.get('actual','?')}' ({d.get('severity','?')})")

    context = {
        'date_long': format_date_lt(now),
        'today_iso': now.strftime('%Y-%m-%d'),
        'verification': {
            'filled_placeholders': _ph_log.get('filled', []),
            'critique': critique_result,
            'live_data_fetched_at': now.strftime('%H:%M'),
        },
        'macro_events': macro_sorted,
        'earnings': earnings_top,
        'watchlist': watchlist,
        'crypto': crypto,
        'indices': indices,
        'ai_quotes': ai_quotes,
        'high_iv': high_iv,
        'news': news,
        'insider': insider,
        'reddit_posts': reddit_posts,
        'x_posts': x_posts,
        'ibkr_news': ibkr_news,
        'manual_notes': manual_notes,
        'yt_synthesis': yt_synthesis,
        'wl_earnings': wl_earnings,
        'takeaway': build_takeaway(macro_sorted, earnings_top),
        'generated_at': now.strftime('%H:%M'),
    }

    print("  Rendering HTML...")
    html = render_html('briefing.html', context)

    output_path = Path(__file__).resolve().parent.parent / 'output' / f'briefing-{date_str}.png'
    print(f"  Rendering PNG -> {output_path.name}")
    html_to_png(html, output_path)

    print("  Saving HTML for web...")
    html_path = save_briefing_html(html, date_str)
    regenerate_index()
    print(f"    -> {html_path.relative_to(html_path.parent.parent.parent)}")

    web_url = f"https://daugpinigu.github.io/daug-pinigu-briefing/briefings/briefing-{date_str}.html"
    print("  Sending to Telegram...")
    caption = f"📊 Daily briefing · {now.strftime('%Y-%m-%d')}\n🌐 <a href=\"{web_url}\">Web versija</a>"
    send_photo(output_path, caption=caption)

    print(f"[{datetime.now(VILNIUS).strftime('%H:%M:%S')}] Done.")


if __name__ == '__main__':
    main()
