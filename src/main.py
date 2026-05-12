"""Daily briefing orchestrator. Run once per day."""
import os
import sys
from datetime import datetime
from pathlib import Path
import pytz

from fetch import fetch_macro_events, fetch_earnings, fetch_premarket_movers
from render import render_html, html_to_png
from send import send_photo

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


def main():
    now = datetime.now(VILNIUS)

    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and now.hour != 7:
        print(f"Scheduled run at {now.strftime('%H:%M')} Vilnius - skipping (only run at 07:xx).")
        sys.exit(0)

    date_str = now.strftime('%Y-%m-%d')
    print(f"[{now.strftime('%H:%M:%S')}] Building briefing for {date_str}...")

    print("  Fetching macro events...")
    macro = fetch_macro_events(date_str)
    print(f"    -> {len(macro)} events")

    print("  Fetching earnings...")
    earnings = fetch_earnings(date_str, min_market_cap_b=10.0)
    print(f"    -> {len(earnings)} companies")

    print("  Fetching market movers...")
    movers = fetch_premarket_movers(top_n=5)
    print(f"    -> {len(movers['gainers'])} gainers, {len(movers['losers'])} losers")

    country_priority = {'US': 0, 'EZ': 1, 'DE': 2, 'GB': 3, 'CN': 4, 'JP': 5, 'LT': 6}
    macro_sorted = sorted(
        macro,
        key=lambda e: (
            not e['high_impact'],
            country_priority.get(e['country'], 99),
            e['time_local'],
        ),
    )[:10]
    earnings_top = earnings[:10]

    context = {
        'date_long': format_date_lt(now),
        'macro_events': macro_sorted,
        'earnings': earnings_top,
        'movers': movers,
        'takeaway': build_takeaway(macro_sorted, earnings_top),
        'generated_at': now.strftime('%H:%M'),
    }

    print("  Rendering HTML...")
    html = render_html('briefing.html', context)

    output_path = Path(__file__).resolve().parent.parent / 'output' / f'briefing-{date_str}.png'
    print(f"  Rendering PNG -> {output_path.name}")
    html_to_png(html, output_path)

    print("  Sending to Telegram...")
    caption = f"📊 Daily briefing · {now.strftime('%Y-%m-%d')}"
    send_photo(output_path, caption=caption)

    print(f"[{datetime.now(VILNIUS).strftime('%H:%M:%S')}] Done.")


if __name__ == '__main__':
    main()
