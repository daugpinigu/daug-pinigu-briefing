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

    if args.commit:
        print("\nCommitting...")
        subprocess.run(['git', 'add', str(OUTPUT)], check=True, cwd=ROOT)
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
