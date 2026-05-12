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
    enrich_news_with_summaries,
)
from render import render_html, html_to_png
from send import send_photo
from publish_web import save_briefing_html, regenerate_index
from watchlist import STOCKS, CRYPTO, FUTURES, AI_TICKERS, NEWS_TICKERS

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


def _safe(label, fn, fallback):
    """Run a fetcher with fallback on exception. Don't let one source kill the briefing."""
    try:
        return fn()
    except Exception as e:
        print(f"  warn: {label} failed ({type(e).__name__}: {str(e)[:80]})")
        return fallback


def main():
    now = datetime.now(VILNIUS)

    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and now.hour != 7:
        print(f"Scheduled run at {now.strftime('%H:%M')} Vilnius - skipping (only run at 07:xx).")
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
    high_iv = iv_data[:8]
    print(f"    -> {len(iv_data)} tickers ranked, top {len(high_iv)} shown")

    print("  Fetching Reddit discussions (r/stocks, r/options, r/StockMarket)...")
    reddit_posts = _safe('Reddit', lambda: fetch_reddit_discussions(max_total=6, min_score=100), [])
    print(f"    -> {len(reddit_posts)} posts")

    print("  Fetching insider purchases (watchlist only, latest 8)...")
    insider = _safe('insider',
                    lambda: fetch_insider_purchases(STOCKS, days=365, min_value=10_000, max_results=8),
                    [])
    print(f"    -> {len(insider)} watchlist insider buys")

    print("  Fetching market news (quality filtered)...")
    market_news = _safe('market news', lambda: fetch_market_news(max_total=5), [])
    print(f"    -> {len(market_news)} market headlines")

    print("  Fetching mover catalysts...")
    big_movers = [m['symbol'] for m in (watchlist['gainers'] + watchlist['losers'])
                  if abs(m['change_pct']) >= 5.0]
    mover_news = _safe('mover catalysts',
                       lambda: fetch_mover_catalysts(big_movers, max_per=1, max_total=4),
                       [])
    print(f"    -> {len(mover_news)} mover catalysts (from {len(big_movers)} big movers)")

    news = mover_news + [n for n in market_news if not any(
        n['title'].lower()[:50] == m['title'].lower()[:50] for m in mover_news
    )]
    news = news[:6]

    print("  Enriching news with article summaries...")
    news = _safe('enrich news', lambda: enrich_news_with_summaries(news), news)
    summary_count = sum(1 for n in news if n.get('summary'))
    print(f"    -> {summary_count}/{len(news)} enriched")

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
