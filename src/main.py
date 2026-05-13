"""Daily briefing orchestrator. Run once per day."""
import os
import sys
from datetime import datetime
from pathlib import Path
import pytz

from fetch import (
    fetch_macro_events, fetch_earnings, fetch_watchlist_movers,
    fetch_crypto, fetch_index_snapshot, fetch_iv_metrics,
    fetch_market_news, fetch_mover_catalysts, fetch_quotes,
    fetch_insider_purchases, fetch_reddit_discussions,
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

    print("  Fetching watchlist earnings history (recent + upcoming)...")
    wl_earnings = _safe('watchlist earnings',
                        lambda: fetch_watchlist_earnings_history(STOCKS, days_back=2, days_fwd=14),
                        {'recent': [], 'upcoming': []})
    print(f"    -> {len(wl_earnings['recent'])} recent, {len(wl_earnings['upcoming'])} upcoming")

    print("  Fetching indices/futures/VIX...")
    indices = _safe('indices', lambda: fetch_index_snapshot(FUTURES), [])
    print(f"    -> {len(indices)} indices")

    print("  Fetching watchlist movers...")
    watchlist = _safe('watchlist movers',
                      lambda: fetch_watchlist_movers(STOCKS, top_n=5),
                      {'gainers': [], 'losers': []})
    print(f"    -> {len(watchlist['gainers'])} gainers, {len(watchlist['losers'])} losers")

    print("  Fetching crypto...")
    crypto = _safe('crypto', lambda: fetch_crypto(CRYPTO), [])
    print(f"    -> {len(crypto)} coins")

    print("  Fetching AI sector quotes...")
    ai_quotes_raw = _safe('AI quotes', lambda: fetch_quotes(AI_TICKERS), [])
    ai_quotes = sorted(ai_quotes_raw, key=lambda x: abs(x['change_pct']), reverse=True)[:8]
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

    # Manual notes - explicit content Radoslav (or I) want in the next briefing,
    # injected via data/manual_notes.json with auto-expiry. Outlives single
    # conversations and survives the GH Actions pipeline boundary.
    manual_notes = _load_manual_notes()
    print(f"  Loaded {len(manual_notes)} manual notes from data/manual_notes.json")

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

    print("  Fetching insider purchases (watchlist, past 12mo, aggregated by insider)...")
    insider = _safe('insider',
                    lambda: fetch_insider_purchases(STOCKS, days=730, min_value=10_000, max_results=15),
                    [])
    print(f"    -> {len(insider)} watchlist insider buys")

    print("  Fetching market news (quality filtered)...")
    market_news = _safe('market news', lambda: fetch_market_news(max_total=6), [])
    print(f"    -> {len(market_news)} market headlines")

    print("  Fetching mover catalysts...")
    big_movers = [m['symbol'] for m in (watchlist['gainers'] + watchlist['losers'])
                  if abs(m['change_pct']) >= 5.0]
    mover_news = _safe('mover catalysts',
                       lambda: fetch_mover_catalysts(big_movers, max_per=1, max_total=4),
                       [])
    print(f"    -> {len(mover_news)} mover catalysts (from {len(big_movers)} big movers)")

    print("  Fetching watchlist catalysts (M&A, FDA, lawsuits, buybacks across all 50 tickers)...")
    wl_catalysts = _safe('watchlist catalysts',
                         lambda: fetch_watchlist_catalysts(STOCKS, max_total=12, hours_window=48),  # 2 dienos
                         [])
    print(f"    -> {len(wl_catalysts)} watchlist catalyst items")

    # Merge: watchlist catalysts > mover catalysts > market news.
    # Watchlist catalysts surface M&A/FDA on specific tickers regardless of price move.
    news = wl_catalysts + mover_news + [n for n in market_news if not any(
        n['title'].lower()[:50] == m['title'].lower()[:50]
        for m in (wl_catalysts + mover_news)
    )]
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
                e['analysis'] = _safe(f"analyze {e['symbol']}",
                                       lambda: analyze_earnings_card(
                                           e['symbol'], e['eps_actual'], e['eps_estimate'],
                                           e.get('extracted', {})
                                       ), '')
                e['extracted_metrics'] = _earnings_extracted_to_metrics(e.get('extracted', {}))
            print(f"    -> {sum(1 for e in wl_earnings['recent'] if e.get('analysis'))} cards enriched")

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

        # YouTube synthesis: combine all video transcripts into one narrative
        yt_synthesis = ''
        if yt_videos:
            print(f"  LLM synthesizing {len(yt_videos)} YouTube videos into investor narrative...")
            yt_synthesis = _safe('YouTube synthesis',
                                  lambda: synthesize_youtube_insights(yt_videos, STOCKS), '')
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

    context = {
        'date_long': format_date_lt(now),
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
