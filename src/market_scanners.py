"""Market scanners: watchlist 52w high/low + MA crosses, sector rotation,
options flow (basic put/call ratio + IV signals from yfinance options chain).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


SECTOR_ETFS = [
    ('XLK', 'Technology'),
    ('XLF', 'Financials'),
    ('XLV', 'Healthcare'),
    ('XLE', 'Energy'),
    ('XLI', 'Industrials'),
    ('XLY', 'Cons. Discr.'),
    ('XLP', 'Cons. Staples'),
    ('XLU', 'Utilities'),
    ('XLB', 'Materials'),
    ('XLRE', 'Real Estate'),
    ('XLC', 'Communication'),
]


# ---------------------------------------------------------------------------
# 52-week high/low + Golden/Death Cross alerts
# ---------------------------------------------------------------------------

def scan_watchlist_alerts(tickers: list[str]) -> dict:
    """For each ticker, check 52w high/low proximity + MA crosses.

    Returns: {
      near_52w_high: [{ticker, price, high_52w, pct_from_high}, ...],
      near_52w_low:  [...],
      golden_crosses: [{ticker, days_ago, ma50, ma200}],
      death_crosses:  [...],
    }
    """
    out = {
        'near_52w_high': [],
        'near_52w_low': [],
        'golden_crosses': [],
        'death_crosses': [],
    }
    for ticker in tickers:
        try:
            df = yf.Ticker(ticker).history(period='2y', interval='1d', auto_adjust=False)
            if df is None or len(df) < 50:
                continue
        except Exception:
            continue
        closes = df['Close']
        highs = df['High']
        lows = df['Low']
        cur = float(closes.iloc[-1])
        h52 = float(highs.tail(252).max())
        l52 = float(lows.tail(252).min())
        pct_from_high = (cur - h52) / h52 * 100
        pct_from_low = (cur - l52) / l52 * 100

        # 52w threshold: within 3% of high/low
        if pct_from_high >= -3:
            out['near_52w_high'].append({
                'ticker': ticker,
                'price': cur,
                'price_str': _fmt(cur),
                'high_52w': h52,
                'high_52w_str': _fmt(h52),
                'pct_from_high': pct_from_high,
                'pct_str': f"{pct_from_high:+.2f}%",
            })
        if pct_from_low <= 3 and len(closes) >= 252:
            out['near_52w_low'].append({
                'ticker': ticker,
                'price': cur,
                'price_str': _fmt(cur),
                'low_52w': l52,
                'low_52w_str': _fmt(l52),
                'pct_from_low': pct_from_low,
                'pct_str': f"+{pct_from_low:.2f}%",
            })

        # MA cross detection: look for 50DMA crossing 200DMA in last 5 days
        if len(closes) >= 210:
            ma50 = closes.rolling(50).mean()
            ma200 = closes.rolling(200).mean()
            for back in range(5):
                idx = -1 - back
                idx_prev = idx - 1
                if pd.isna(ma50.iloc[idx]) or pd.isna(ma200.iloc[idx]):
                    continue
                if pd.isna(ma50.iloc[idx_prev]) or pd.isna(ma200.iloc[idx_prev]):
                    continue
                # Golden cross: 50 crosses above 200
                if (ma50.iloc[idx_prev] <= ma200.iloc[idx_prev]
                        and ma50.iloc[idx] > ma200.iloc[idx]):
                    out['golden_crosses'].append({
                        'ticker': ticker,
                        'days_ago': back,
                        'ma50_str': _fmt(float(ma50.iloc[idx])),
                        'ma200_str': _fmt(float(ma200.iloc[idx])),
                        'price_str': _fmt(cur),
                    })
                    break
                # Death cross: 50 crosses below 200
                if (ma50.iloc[idx_prev] >= ma200.iloc[idx_prev]
                        and ma50.iloc[idx] < ma200.iloc[idx]):
                    out['death_crosses'].append({
                        'ticker': ticker,
                        'days_ago': back,
                        'ma50_str': _fmt(float(ma50.iloc[idx])),
                        'ma200_str': _fmt(float(ma200.iloc[idx])),
                        'price_str': _fmt(cur),
                    })
                    break

    return out


# ---------------------------------------------------------------------------
# Sector rotation heatmap
# ---------------------------------------------------------------------------

def fetch_sector_rotation() -> list[dict]:
    """Returns sector ETFs with day, week, month, 3mo, YTD returns."""
    out = []
    for symbol, name in SECTOR_ETFS:
        try:
            df = yf.Ticker(symbol).history(period='1y', interval='1d', auto_adjust=False)
            if df is None or len(df) < 50:
                continue
        except Exception:
            continue
        closes = df['Close']
        cur = float(closes.iloc[-1])
        def _ret(bars):
            if len(closes) <= bars:
                return None
            past = float(closes.iloc[-1 - bars])
            return (cur - past) / past * 100
        day = _ret(1)
        week = _ret(5)
        month = _ret(21)
        three_mo = _ret(63)
        ytd_anchor = None
        for idx, val in closes.items():
            if hasattr(idx, 'year') and idx.year == datetime.utcnow().year:
                ytd_anchor = float(val)
                break
        ytd = ((cur - ytd_anchor) / ytd_anchor * 100) if ytd_anchor else None
        out.append({
            'symbol': symbol,
            'name': name,
            'price_str': _fmt(cur),
            'day': day,
            'day_str': _fmt_pct(day),
            'day_color': _heat_color(day),
            'week': week,
            'week_str': _fmt_pct(week),
            'week_color': _heat_color(week, scale=2),
            'month': month,
            'month_str': _fmt_pct(month),
            'month_color': _heat_color(month, scale=4),
            'three_mo_str': _fmt_pct(three_mo),
            'three_mo_color': _heat_color(three_mo, scale=6),
            'ytd_str': _fmt_pct(ytd),
            'ytd_color': _heat_color(ytd, scale=10),
        })
    # Sort by week return desc
    out.sort(key=lambda x: (x['week'] or -999), reverse=True)
    return out


def _heat_color(value: Optional[float], scale: float = 1.0) -> str:
    """Red-to-green gradient. value=0 → grey; large pos → green; large neg → red."""
    if value is None:
        return '#2a2e39'
    v = max(-1.0, min(1.0, value / (3 * scale)))  # clamp
    if v >= 0:
        # green ramp
        intensity = int(60 + v * 110)
        return f'rgba(126,216,126,{0.15 + abs(v) * 0.4})'
    else:
        intensity = int(60 + abs(v) * 110)
        return f'rgba(255,115,115,{0.15 + abs(v) * 0.4})'


# ---------------------------------------------------------------------------
# Options Flow (basic put/call ratio + IV signals from yfinance)
# ---------------------------------------------------------------------------

def fetch_options_flow(tickers: list[str], max_tickers: int = 12) -> list[dict]:
    """For each ticker, compute put/call ratio + IV signal from front-month options.

    Without paid API, we can't get unusual sweeps/block trades. But we can:
      - put/call open interest ratio (sentiment proxy)
      - front-month IV (vs longer-dated) - identifies near-term anxiety
      - net open interest changes day-over-day not available without history

    Returns sorted by abs(put_call_ratio - 1) descending - most skewed first.
    """
    out = []
    for ticker in tickers[:max_tickers]:
        try:
            t = yf.Ticker(ticker)
            exp_dates = t.options
            if not exp_dates:
                continue
            # Pick nearest-month expiry (>5 days out)
            today = datetime.utcnow().date()
            chosen_exp = None
            for d in exp_dates:
                d_dt = datetime.strptime(d, '%Y-%m-%d').date()
                if (d_dt - today).days >= 5:
                    chosen_exp = d
                    break
            if not chosen_exp:
                chosen_exp = exp_dates[0]
            chain = t.option_chain(chosen_exp)
            calls = chain.calls
            puts = chain.puts
            if calls.empty or puts.empty:
                continue
            call_oi = float(calls['openInterest'].sum())
            put_oi = float(puts['openInterest'].sum())
            call_vol = float(calls['volume'].sum())
            put_vol = float(puts['volume'].sum())
            pc_oi = put_oi / call_oi if call_oi > 0 else None
            pc_vol = put_vol / call_vol if call_vol > 0 else None
            cur_price = float(t.history(period='2d', interval='1d')['Close'].iloc[-1])

            # ATM IV (front-month, weighted toward at-the-money)
            calls_atm = calls.iloc[(calls['strike'] - cur_price).abs().argsort()[:3]]
            puts_atm = puts.iloc[(puts['strike'] - cur_price).abs().argsort()[:3]]
            atm_iv_call = float(calls_atm['impliedVolatility'].mean()) if not calls_atm.empty else None
            atm_iv_put = float(puts_atm['impliedVolatility'].mean()) if not puts_atm.empty else None
            atm_iv = ((atm_iv_call or 0) + (atm_iv_put or 0)) / 2 if (atm_iv_call or atm_iv_put) else None

            # Heavy-volume option strikes (biggest single-strike volume on call/put side)
            top_call = calls.nlargest(1, 'volume').iloc[0] if not calls.empty else None
            top_put = puts.nlargest(1, 'volume').iloc[0] if not puts.empty else None

            sentiment = _options_sentiment(pc_oi, pc_vol)

            out.append({
                'ticker': ticker,
                'expiry': chosen_exp,
                'price_str': _fmt(cur_price),
                'pc_oi': pc_oi,
                'pc_oi_str': f"{pc_oi:.2f}" if pc_oi is not None else '-',
                'pc_vol': pc_vol,
                'pc_vol_str': f"{pc_vol:.2f}" if pc_vol is not None else '-',
                'atm_iv_str': f"{atm_iv * 100:.1f}%" if atm_iv else '-',
                'call_oi': int(call_oi),
                'put_oi': int(put_oi),
                'top_call_strike': _fmt(float(top_call['strike'])) if top_call is not None else '-',
                'top_call_vol': int(top_call['volume']) if top_call is not None else 0,
                'top_put_strike': _fmt(float(top_put['strike'])) if top_put is not None else '-',
                'top_put_vol': int(top_put['volume']) if top_put is not None else 0,
                'sentiment': sentiment,
            })
        except Exception as e:
            print(f"    warn: options flow failed for {ticker}: {e}")
            continue
    # Sort by skew strength (most directional bias first)
    out.sort(key=lambda x: abs((x.get('pc_vol') or 1) - 1), reverse=True)
    return out


def _options_sentiment(pc_oi: Optional[float], pc_vol: Optional[float]) -> dict:
    """Classify options sentiment based on put/call ratios.

    Standard interpretation:
      pc < 0.7  → bullish (calls > puts)
      pc 0.7-1.0 → neutral-bullish
      pc 1.0-1.3 → neutral-bearish
      pc > 1.3 → bearish
    """
    ratio = pc_vol if pc_vol is not None else pc_oi
    if ratio is None:
        return {'label': 'unknown', 'color': '#8892a6', 'badge': '?'}
    if ratio < 0.6:
        return {'label': 'Stipriai bullish', 'color': '#22cc44', 'badge': 'BULL'}
    if ratio < 0.85:
        return {'label': 'Bullish', 'color': '#7ed87e', 'badge': 'bull'}
    if ratio < 1.15:
        return {'label': 'Neutralus', 'color': '#f4cc6b', 'badge': 'neut'}
    if ratio < 1.4:
        return {'label': 'Bearish', 'color': '#ff9b3a', 'badge': 'bear'}
    return {'label': 'Stipriai bearish', 'color': '#ff4444', 'badge': 'BEAR'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(p: Optional[float]) -> str:
    if p is None or pd.isna(p):
        return '-'
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 100:
        return f"${p:.2f}"
    return f"${p:.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None or pd.isna(v):
        return '-'
    sign = '+' if v >= 0 else ''
    return f"{sign}{v:.2f}%"


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'sectors':
        for s in fetch_sector_rotation():
            print(f"  {s['symbol']:5s} {s['name']:14s} d={s['day_str']:>7s} w={s['week_str']:>7s} m={s['month_str']:>7s} ytd={s['ytd_str']:>7s}")
    elif len(sys.argv) > 1 and sys.argv[1] == 'alerts':
        tickers = sys.argv[2:] if len(sys.argv) > 2 else ['MU', 'NVDA', 'AVGO', 'META', 'TSLA']
        result = scan_watchlist_alerts(tickers)
        print(json.dumps(result, indent=2, default=str))
    elif len(sys.argv) > 1 and sys.argv[1] == 'options':
        tickers = sys.argv[2:] if len(sys.argv) > 2 else ['MU', 'NVDA', 'AVGO']
        for o in fetch_options_flow(tickers):
            print(f"  {o['ticker']:5s} {o['sentiment']['badge']:4s} P/C OI={o['pc_oi_str']} P/C Vol={o['pc_vol_str']} IV={o['atm_iv_str']}")
    else:
        print("Usage: sectors | alerts <tickers> | options <tickers>")
