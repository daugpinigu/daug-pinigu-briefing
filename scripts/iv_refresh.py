"""Fetch real ATM IV from IBKR TWS API for all watchlist tickers.

Requires:
- TWS running locally with API enabled (File → Global Configuration → API
  → Settings → "Enable ActiveX and Socket Clients", localhost trusted IP).
- ib_insync (pip install ib_insync).

Writes results to data/iv_metrics.json. main.py reads that file if present;
falls back to in-process Black-Scholes calc otherwise.

Usage:
    python scripts/iv_refresh.py              # write JSON
    python scripts/iv_refresh.py --commit     # also git add/commit/push

Market data subscription notes:
- Live/real-time quotes need a paid API data subscription on the account.
- Delayed-frozen (15-min lag) works without subscription via reqMarketDataType(4).
- We use delayed-frozen by default — IV barely moves in 15 min, accurate enough
  for daily briefing ranking.
"""
import argparse
import json
import math
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'
OUTPUT = DATA_DIR / 'iv_metrics.json'

sys.path.insert(0, str(ROOT / 'src'))


# ---- News filter ----
import re

# Skip auto-generated mechanical headlines (just price changes, ETF rises X%, etc.)
NEWS_NOISE_PATTERNS = [re.compile(p, re.I) for p in [
    r'^[^A-Za-z]*[A-Z]+\s+(ETF\s+)?(Climbs|Gains|Falls|Rises|Declines|Closes\s+Flat|Outperforms|Underperforms)\s+\d',
    r'^Today Is All About',
    r'Insider Review For Week Ended',
    r"^[A-Z]+'s\s+(?:Movers|Top Stocks)",
    r"^These Stocks Are Today's Movers",
    r"^Substantial Insider (Purchases|Sales): (Morning|Afternoon|Mid-Day) Report",
    r"^\w+ Stock Rises$",
    r"^\w+ Stock Falls$",
    r"^Best Stocks Of",
    r"^Stocks To Watch:",
    r"Price Target (Announced|Raised|Lowered|Cut|Maintained) (at|to)",  # too granular
    r"^Top \d+ Stocks",
]]

# Keep market-moving headlines
NEWS_KEEP_PATTERNS = [re.compile(p, re.I) for p in [
    # M&A
    r'\b(acquires?|acquisition|to acquire|merger|buyout|takeover)\b',
    # FDA / pharma
    r'\bFDA\s+(approval|approves?|rejects?|rejection|clearance|denies?|decision)\b',
    r'\b(phase\s+(?:2|3|II|III))\b',
    # Earnings strong signals
    r'\b(beats?|misses?)\s+(estimates?|expectations|forecasts?)\b',
    r'\b(raises?|cuts?|lowers?|withdraws?)\s+(guidance|outlook|FY|full[- ]year)\b',
    # Geopolitics / war / sanctions
    r'\b(war|ceasefire|sanctions?|invasion|airstrike|missile|nuclear|strike|attack|escalation)\b',
    r'\b(Russia|Ukraine|Iran|Israel|Gaza|Hamas|Hezbollah|Taiwan|China)\b.{0,40}\b(strike|attack|missile|war|invasion|sanction|conflict|threat|warns?)\b',
    # Macro / Fed
    r'\b(Fed|FOMC|Powell|ECB|BoJ|BoE|Lagarde)\b.{0,30}\b(hikes?|cuts?|holds?|raises?|lowers?|signals?|decision|meeting|minutes)\b',
    r'\b(CPI|PPI|PCE|GDP|NFP|payroll|jobless|unemployment|inflation)\b.{0,30}\b(beats?|misses?|surprise|hotter|cooler|higher|lower|rose|fell)\b',
    r'\b(rate (cut|hike|hold|pause|decision))\b',
    r'\b(recession|stagflation|hard landing|soft landing)\b',
    # Trade / tariffs
    r'\b(tariffs?|trade war|trade deal|export controls)\b',
    # Major corporate events
    r'\b(bankruptcy|chapter 11|delisting|spin[- ]off|IPO)\b',
    r'\b(?:lawsuit|sues|settles?|fined?)\s+(?:for|over|with)\s+\$',  # big lawsuits
    r'\b(layoffs?|cuts?\s+\d+%?\s+(?:of\s+)?(?:staff|workforce|jobs))\b',
    # Leadership
    r'\b(CEO|CFO|COO|chairman)\s+(steps?\s+down|fired|resigns?|named|appointed)\b',
    # Insider buying activity
    r'\b(insider\s+buying|insider\s+purchases?|CEO\s+(?:buys?|bought))\b',
    # Big moves
    r'\b(?:surge|plunge|tumble|rally|crash|jumps?|sinks?)\s+\d{2,}%',
    # Capital actions
    r'\b(buyback|repurchase|capital\s+raise|secondary\s+offering|stock\s+split|dividend\s+(?:increase|hike|cut))\b',
]]


def _is_market_moving(headline: str) -> bool:
    """True if headline matches a market-moving keyword AND isn't noise."""
    if not headline or len(headline) < 15:
        return False
    # Strip IBKR metadata prefix {A:ID:L:lang}
    h = re.sub(r'^\s*\{[^}]+\}\s*', '', headline)
    # Strip language suffix " -- Source.com" etc.
    if any(p.search(h) for p in NEWS_NOISE_PATTERNS):
        return False
    return any(p.search(h) for p in NEWS_KEEP_PATTERNS)


def _strip_meta(headline: str) -> str:
    """Remove IBKR {A:...} prefix from headline."""
    return re.sub(r'^\s*\{[^}]+\}\s*', '', headline or '').strip()


def fetch_ibkr_news(ib, tickers: list, hours_back: int = 36, max_per_ticker: int = 3,
                     max_total: int = 15) -> list:
    """Fetch market-moving headlines per ticker via IBKR Dow Jones + Briefing.

    Filters out auto-generated noise (price-only updates, mechanical
    insider/movers summaries). Dedups by both article_id and headline text
    (same wire story often appears under multiple tickers).
    """
    from ib_insync import Stock
    end = datetime.now()
    start = end - __import__('datetime').timedelta(hours=hours_back)
    providers = 'BRFG+DJ-RT+DJ-RTG+BRFUPDN+DJNL'
    all_items = []
    seen_ids = set()
    seen_text = set()
    for sym in tickers:
        try:
            contract = Stock(sym, 'SMART', 'USD')
            qc = ib.qualifyContracts(contract)
            if not qc:
                continue
            news = ib.reqHistoricalNews(
                conId=contract.conId,
                providerCodes=providers,
                startDateTime=start.strftime('%Y-%m-%d %H:%M:%S'),
                endDateTime=end.strftime('%Y-%m-%d %H:%M:%S'),
                totalResults=20,
            )
            kept = 0
            for n in news:
                if n.articleId in seen_ids:
                    continue
                clean_headline = _strip_meta(n.headline)
                if not _is_market_moving(clean_headline):
                    continue
                # Text-based dedup: normalize to alphanumeric, take first 60 chars
                norm = re.sub(r'\W+', '', clean_headline.lower())[:60]
                if norm in seen_text:
                    continue
                seen_ids.add(n.articleId)
                seen_text.add(norm)
                all_items.append({
                    'ticker': sym,
                    'headline': clean_headline[:200],
                    'provider': n.providerCode,
                    'article_id': n.articleId,
                    'time': n.time.isoformat() if n.time else '',
                })
                kept += 1
                if kept >= max_per_ticker:
                    break
        except Exception:
            continue
    # Sort by time DESC, cap total
    all_items.sort(key=lambda x: x['time'], reverse=True)
    return all_items[:max_total]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--commit', action='store_true', help='git add/commit/push after writing')
    ap.add_argument('--port', type=int, default=7496, help='TWS API port (7496 Live, 7497 Paper)')
    ap.add_argument('--client-id', type=int, default=42)
    ap.add_argument('--target-dte', type=int, default=30, help='target days to expiration')
    args = ap.parse_args()

    try:
        from ib_insync import IB, Stock, Option, util
    except ImportError:
        print("ib_insync not installed. Run: pip install ib_insync")
        sys.exit(1)

    from watchlist import STOCKS

    ib = IB()
    print(f"Connecting to TWS on 127.0.0.1:{args.port}...")
    try:
        ib.connect('127.0.0.1', args.port, clientId=args.client_id, timeout=8)
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)
    print(f"  ✓ connected (server v{ib.client.serverVersion()}, account {ib.managedAccounts()})")

    # Delayed-frozen — 15-min lag, no live subscription needed. Sufficient for IV.
    ib.reqMarketDataType(4)

    today = date.today()
    results = []

    for i, sym in enumerate(STOCKS, 1):
        print(f"[{i}/{len(STOCKS)}] {sym}...", end=' ', flush=True)
        try:
            contract = Stock(sym, 'SMART', 'USD')
            ib.qualifyContracts(contract)
            spot_t = ib.reqMktData(contract, '', False, False)
            ib.sleep(2)
            spot = spot_t.marketPrice()
            if not spot or math.isnan(spot):
                spot = spot_t.close
            if not spot or math.isnan(spot):
                print("no spot, skip")
                ib.cancelMktData(contract)
                continue

            chains = ib.reqSecDefOptParams(contract.symbol, '', contract.secType, contract.conId)
            ib.cancelMktData(contract)
            if not chains:
                print("no chain")
                continue
            chain = next((c for c in chains if c.exchange == 'SMART'), chains[0])

            # Find expiration closest to target DTE
            best_exp, best_diff = None, 999
            for exp in chain.expirations:
                d = datetime.strptime(exp, '%Y%m%d').date()
                dte = (d - today).days
                if dte < 7:
                    continue
                diff = abs(dte - args.target_dte)
                if diff < best_diff:
                    best_diff = diff
                    best_exp = exp
            if not best_exp:
                print("no exp")
                continue
            exp_date = datetime.strptime(best_exp, '%Y%m%d').date()
            dte = (exp_date - today).days

            # chain.strikes lists all strikes across all expirations including
            # historical ones that don't exist for our chosen exp. Try up to 8
            # closest strikes — first valid (call+put both exist) wins.
            strikes_sorted = sorted(chain.strikes, key=lambda s: abs(s - spot))
            qualified_call, qualified_put, atm_strike = None, None, None
            for candidate in strikes_sorted[:10]:
                call = Option(sym, best_exp, candidate, 'C', 'SMART')
                put = Option(sym, best_exp, candidate, 'P', 'SMART')
                try:
                    results_q = ib.qualifyContracts(call, put)
                except Exception:
                    continue
                if len(results_q) == 2 and results_q[0].conId and results_q[1].conId:
                    qualified_call, qualified_put = results_q
                    atm_strike = candidate
                    break
            if not qualified_call:
                print("no valid strike")
                continue

            call_t = ib.reqMktData(qualified_call, '', False, False)
            put_t = ib.reqMktData(qualified_put, '', False, False)
            # Poll up to 6s — modelGreeks can take a moment to populate.
            iv_c, iv_p = None, None
            for _ in range(12):
                ib.sleep(0.5)
                for src in ('modelGreeks', 'lastGreeks', 'bidGreeks', 'askGreeks'):
                    g = getattr(call_t, src, None)
                    if g and g.impliedVol and not iv_c:
                        iv_c = g.impliedVol
                    g = getattr(put_t, src, None)
                    if g and g.impliedVol and not iv_p:
                        iv_p = g.impliedVol
                if iv_c and iv_p:
                    break
            ib.cancelMktData(qualified_call)
            ib.cancelMktData(qualified_put)

            ivs = [v for v in (iv_c, iv_p) if v and not math.isnan(v) and 0.05 < v < 3.0]
            if not ivs:
                print("no IV")
                continue
            iv_pct = (sum(ivs) / len(ivs)) * 100
            results.append({
                'symbol': sym,
                'iv': round(iv_pct, 2),
                'spot': round(spot, 4),
                'dte': dte,
                'strike': atm_strike,
                'expiration': best_exp,
            })
            print(f"IV={iv_pct:.1f}% spot=${spot:.2f} strike=${atm_strike} DTE={dte}")
        except Exception as e:
            print(f"err: {type(e).__name__}: {str(e)[:60]}")

    # ----- News fetch (IBKR Dow Jones + Briefing.com) -----
    print("\nFetching IBKR news...")
    news_results = fetch_ibkr_news(ib, STOCKS)
    print(f"  -> {len(news_results)} market-moving headlines")

    ib.disconnect()

    results.sort(key=lambda x: x['iv'], reverse=True)
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'IBKR TWS API (delayed-frozen)',
        'metrics': results,
    }
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {OUTPUT}: {len(results)} tickers")
    for r in results[:10]:
        print(f"  {r['symbol']:6} IV={r['iv']:5.1f}%  spot=${r['spot']:7.2f}  DTE={r['dte']}")

    # Write news JSON
    news_path = DATA_DIR / 'ibkr_news.json'
    news_payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'IBKR Dow Jones + Briefing.com',
        'items': news_results,
    }
    news_path.write_text(json.dumps(news_payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {news_path}: {len(news_results)} headlines")
    for n in news_results[:10]:
        print(f"  [{n.get('ticker','-'):6}] {n['time'][:16]} | {n['headline'][:100]}")

    if args.commit:
        print("\nCommitting...")
        subprocess.run(['git', 'add', str(OUTPUT), str(news_path)], check=True, cwd=ROOT)
        diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
        if diff.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(['git', 'commit', '-m',
                        f'IV refresh {datetime.now().strftime("%Y-%m-%d %H:%M")} [skip ci]'],
                       check=True, cwd=ROOT)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True, cwd=ROOT)
        print("Pushed.")


if __name__ == '__main__':
    main()
