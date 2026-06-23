"""Mark Newton-style technical analysis for daily briefing.

For each ticker, computes daily + weekly:
  - Trend vs 20/50/200 DMA
  - RSI(14)
  - Fib retracement (from most recent swing low -> swing high)
  - Fib extension targets (1.272, 1.618, 2.618)
  - Recent pivot S/R levels
  - Newton-style verdict + setup (entry/stop/target)

Returns structured dict consumed by templates/briefing.html.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf


PROJECT_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = PROJECT_DIR / 'data' / 'ta_watchlist.json'


def _load_config() -> dict:
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text())
    return {'core': [], 'max_dynamic': 0,
            'lookback_daily_weeks': 26, 'lookback_weekly_years': 2}


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Wilder's RSI."""
    if len(series) < period + 1:
        return float('nan')
    delta = series.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _fmt_price(p: float) -> str:
    if p is None or pd.isna(p):
        return '-'
    if p >= 1000:
        return f"${p:,.0f}"
    if p >= 100:
        return f"${p:.2f}"
    if p >= 10:
        return f"${p:.2f}"
    return f"${p:.2f}"


def _fmt_pct(x: float) -> str:
    if x is None or pd.isna(x):
        return '-'
    sign = '+' if x >= 0 else ''
    return f"{sign}{x:.2f}%"


def _detect_swing(df: pd.DataFrame, lookback_bars: int) -> tuple[Optional[float], Optional[pd.Timestamp], Optional[float], Optional[pd.Timestamp], str]:
    """Find most-recent significant swing low and swing high in lookback window.

    Returns (low_price, low_date, high_price, high_date, direction).
    direction: 'up' if high is more recent than low, 'down' otherwise.
    Fib retracement is read in the dominant direction.
    """
    if len(df) < 10:
        return None, None, None, None, 'flat'
    recent = df.tail(lookback_bars)
    high_idx = recent['High'].idxmax()
    low_idx = recent['Low'].idxmin()
    high_price = float(recent.loc[high_idx, 'High'])
    low_price = float(recent.loc[low_idx, 'Low'])
    direction = 'up' if high_idx > low_idx else 'down'
    return low_price, low_idx, high_price, high_idx, direction


def _fib_retracement(low: float, high: float) -> dict:
    """0.236 / 0.382 / 0.5 / 0.618 / 0.786 from high pulling back toward low."""
    span = high - low
    return {
        '0.236': high - 0.236 * span,
        '0.382': high - 0.382 * span,
        '0.5':   high - 0.5 * span,
        '0.618': high - 0.618 * span,
        '0.786': high - 0.786 * span,
    }


def _fib_extension(low: float, high: float) -> dict:
    """1.272 / 1.618 / 2.618 projecting above the high."""
    span = high - low
    return {
        '1.272': low + 1.272 * span,
        '1.618': low + 1.618 * span,
        '2.618': low + 2.618 * span,
    }


def _pivots(df: pd.DataFrame, window: int = 5) -> tuple[list[float], list[float]]:
    """Find local pivot highs/lows: bar's high > neighbors within window."""
    highs, lows = [], []
    h = df['High'].values
    l = df['Low'].values
    for i in range(window, len(df) - window):
        if h[i] == max(h[i - window:i + window + 1]):
            highs.append(float(h[i]))
        if l[i] == min(l[i - window:i + window + 1]):
            lows.append(float(l[i]))
    # Keep unique-ish levels (within 2% of each other = one zone)
    def _dedupe(levels: list[float]) -> list[float]:
        out = []
        for v in sorted(levels, reverse=True):
            if not any(abs(v - x) / x < 0.02 for x in out):
                out.append(v)
        return out
    return _dedupe(highs)[:6], _dedupe(lows)[:6]


def _key_levels(price: float, pivots_hi: list[float], pivots_lo: list[float],
                fib_ret: dict, fib_ext: dict, ma50: float, ma200: float) -> dict:
    """Pick top 2 resistance + top 2 support relative to current price."""
    candidates_above = []
    for v in pivots_hi:
        if v > price:
            candidates_above.append({'price': v, 'label': 'recent pivot'})
    for k, v in fib_ext.items():
        if v > price:
            candidates_above.append({'price': v, 'label': f'{k} fib ext'})
    for k, v in fib_ret.items():
        if v > price:
            candidates_above.append({'price': v, 'label': f'{k} fib ret'})
    if ma50 and ma50 > price:
        candidates_above.append({'price': ma50, 'label': '50DMA'})
    if ma200 and ma200 > price:
        candidates_above.append({'price': ma200, 'label': '200DMA'})

    candidates_below = []
    for v in pivots_lo:
        if v < price:
            candidates_below.append({'price': v, 'label': 'recent pivot'})
    for k, v in fib_ret.items():
        if v < price:
            candidates_below.append({'price': v, 'label': f'{k} fib ret'})
    if ma50 and ma50 < price:
        candidates_below.append({'price': ma50, 'label': '50DMA'})
    if ma200 and ma200 < price:
        candidates_below.append({'price': ma200, 'label': '200DMA'})

    # Closest 2 resistance above
    candidates_above.sort(key=lambda x: x['price'])
    resistance = candidates_above[:2]
    # Closest 2 support below
    candidates_below.sort(key=lambda x: -x['price'])
    support = candidates_below[:2]
    return {'resistance': resistance, 'support': support}


def _trend_label(price: float, ma20: float, ma50: float, ma200: float) -> tuple[str, str]:
    """Classify trend and emoji."""
    above_50 = ma50 and price > ma50
    above_200 = ma200 and price > ma200
    ma_stack_bull = ma20 and ma50 and ma200 and (ma20 > ma50 > ma200)
    ma_stack_bear = ma20 and ma50 and ma200 and (ma20 < ma50 < ma200)
    if above_50 and above_200 and ma_stack_bull:
        return 'Stiprus bull', '🟢'
    if above_50 and above_200:
        return 'Bull', '🟢'
    if above_200 and not above_50:
        return 'Bull trend, short-term spaudimas', '🟡'
    if not above_200 and above_50:
        return 'Recovery / bear bounce', '🟡'
    if not above_50 and not above_200 and ma_stack_bear:
        return 'Stiprus bear', '🔴'
    return 'Bear', '🔴'


def _rsi_label(rsi: float) -> str:
    if pd.isna(rsi):
        return '-'
    if rsi >= 80:
        return f'{rsi:.0f} · ekstremaliai overbought'
    if rsi >= 70:
        return f'{rsi:.0f} · overbought zona'
    if rsi >= 55:
        return f'{rsi:.0f} · bullish momentum'
    if rsi >= 45:
        return f'{rsi:.0f} · neutralus'
    if rsi >= 30:
        return f'{rsi:.0f} · bearish momentum'
    if rsi >= 20:
        return f'{rsi:.0f} · oversold zona'
    return f'{rsi:.0f} · ekstremaliai oversold'


def _setup(price: float, trend: str, levels: dict, rsi: float,
           fib_ret: dict, ma50: float) -> dict:
    """Generate Newton-style entry/stop/target setup."""
    bullish = trend.lower().startswith(('stiprus bull', 'bull'))
    bearish = trend.lower().startswith(('stiprus bear', 'bear'))
    res = levels.get('resistance', [])
    sup = levels.get('support', [])

    if bullish and sup and res:
        # Buy pullback to first support, stop at second support, target first resistance
        entry_lo = sup[0]['price']
        entry_hi = price * 0.995  # current-ish
        stop = sup[1]['price'] if len(sup) >= 2 else sup[0]['price'] * 0.95
        target = res[0]['price']
        risk_off = sup[1]['price'] if len(sup) >= 2 else sup[0]['price'] * 0.93
        return {
            'bullish': True,
            'entry_zone': f"{_fmt_price(entry_lo)}-{_fmt_price(entry_hi)}",
            'stop': _fmt_price(stop),
            'target': _fmt_price(target),
            'risk_off': _fmt_price(risk_off),
            'aggressive_break': _fmt_price(res[0]['price']),
            'aggressive_target': _fmt_price(res[1]['price']) if len(res) >= 2 else '-',
            'rsi_warning': rsi >= 70,
        }
    if bearish and res and sup:
        # Short bounces to first resistance, stop above second resistance, target first support
        entry_lo = price * 1.005
        entry_hi = res[0]['price']
        stop = res[1]['price'] if len(res) >= 2 else res[0]['price'] * 1.05
        target = sup[0]['price']
        return {
            'bullish': False,
            'entry_zone': f"{_fmt_price(entry_lo)}-{_fmt_price(entry_hi)}",
            'stop': _fmt_price(stop),
            'target': _fmt_price(target),
            'risk_off': _fmt_price(stop),
            'aggressive_break': _fmt_price(sup[0]['price']),
            'aggressive_target': _fmt_price(sup[1]['price']) if len(sup) >= 2 else '-',
            'rsi_warning': rsi <= 30,
        }
    # Neutral / unclear
    return {
        'bullish': None,
        'entry_zone': 'lauk aiškesnio setup',
        'stop': '-',
        'target': '-',
        'risk_off': '-',
        'aggressive_break': '-',
        'aggressive_target': '-',
        'rsi_warning': False,
    }


def _verdict(trend: str, rsi: float, distance_to_r1_pct: float, distance_to_s1_pct: float) -> str:
    """Newton-style 1-sentence verdict."""
    bull = trend.lower().startswith(('stiprus bull', 'bull'))
    bear = trend.lower().startswith(('stiprus bear', 'bear'))
    if bull and rsi >= 70:
        return f"Bull trend intact, bet RSI {rsi:.0f} overbought - parabolic risk artėjant R1, preferuoti pullback entries."
    if bull and rsi <= 45:
        return f"Bull trend, RSI {rsi:.0f} reset'inasi - geras setup'as add'inti pozicijas link palaikymo."
    if bull:
        return f"Bull momentum tęsiasi (RSI {rsi:.0f}), kol laikomės virš 50DMA - stebėti R1 break confirmation."
    if bear and rsi <= 30:
        return f"Bear trend, RSI {rsi:.0f} oversold - galimas bounce į R1, bet structural setup vis dar weak."
    if bear:
        return f"Bear momentum (RSI {rsi:.0f}), bounces į R1 reikia parduoti, kol nepalankomės virš 50DMA."
    return f"Mixed setup (RSI {rsi:.0f}) - laukti aiškesnio range break before commit."


def _liquid_strike(p: float, direction: str) -> float:
    """Round to a liquid option strike. direction: 'down' (CSP) or 'up' (CC)."""
    if p < 25:
        step = 0.5
    elif p < 50:
        step = 1.0
    elif p < 100:
        step = 2.5
    elif p < 250:
        step = 5.0
    elif p < 500:
        step = 10.0
    elif p < 1000:
        step = 25.0
    else:
        step = 50.0
    import math
    return (math.floor(p / step) if direction == 'down' else math.ceil(p / step)) * step


def _fmt_strike(p: float) -> str:
    return f"${p:,.0f}" if p == int(p) else f"${p:,.2f}".rstrip('0').rstrip('.')


def _cluster_levels(cands: list[dict], tol: float = 0.025) -> list[dict]:
    """Group nearby levels into confluence zones. cands: [{'price','src'}].

    Returns zones sorted by price desc: {'lo','hi','mid','srcs',score}.
    Score = source count (confluence beats proximity).
    """
    zones = []
    for c in sorted(cands, key=lambda x: -x['price']):
        placed = False
        for z in zones:
            if abs(c['price'] - z['mid']) / z['mid'] <= tol:
                z['lo'] = min(z['lo'], c['price'])
                z['hi'] = max(z['hi'], c['price'])
                z['srcs'].append(c['src'])
                z['mid'] = (z['lo'] + z['hi']) / 2
                placed = True
                break
        if not placed:
            zones.append({'lo': c['price'], 'hi': c['price'],
                          'mid': c['price'], 'srcs': [c['src']]})
    for z in zones:
        z['score'] = len(z['srcs'])
    return zones


def _zone_str(z: dict) -> str:
    if abs(z['hi'] - z['lo']) / z['mid'] < 0.005:
        return _fmt_price(z['mid'])
    return f"{_fmt_price(z['lo'])}-{_fmt_price(z['hi'])}"


def _zone_srcs(z: dict, limit: int = 3) -> str:
    seen, out = set(), []
    for s in z['srcs']:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return ' + '.join(out)


def _options_playbook(d: dict, w: dict) -> Optional[dict]:
    """Concrete zones for the options seller / LEAPS buyer.

    Radoslav 2026-06-12: TA must say WHAT TO DO at WHICH levels - buy/CSP
    zones, CC zones, LEAPS window, what trigger to wait for - not generic
    'lauk range break'. Built from daily+weekly raw levels with confluence
    clustering; strikes rounded to liquid increments.
    """
    if not d or not w:
        return None
    price = d['price']

    sup_cands, res_cands = [], []
    def _add(cands, val, src):
        if val and not pd.isna(val) and val > 0:
            cands.append({'price': float(val), 'src': src})

    for k, v in (d.get('fib_ret') or {}).items():
        _add(sup_cands if v < price else res_cands, v, f"D {k} fib")
    for k, v in (w.get('fib_ret') or {}).items():
        _add(sup_cands if v < price else res_cands, v, f"W {k} fib")
    for k, v in (d.get('fib_ext') or {}).items():
        if v > price:
            _add(res_cands, v, f"D {k} ext")
    for ma_key, label in (('ma20', '20DMA'), ('ma50', '50DMA'), ('ma200', '200DMA')):
        _add(sup_cands if (d.get(ma_key) or 0) < price else res_cands, d.get(ma_key), f"D {label}")
    for ma_key, label in (('ma20', '20WMA'), ('ma50', '50WMA')):
        _add(sup_cands if (w.get(ma_key) or 0) < price else res_cands, w.get(ma_key), f"W {label}")
    for v in (d.get('pivots_lo') or []):
        _add(sup_cands if v < price else res_cands, v, 'D pivot')
    for v in (d.get('pivots_hi') or []):
        _add(sup_cands if v < price else res_cands, v, 'D pivot')

    # Keep meaningful distance bands: supports 1.5-40% below, resistance 1-60% above
    sup_cands = [c for c in sup_cands if 0.015 <= (price - c['price']) / price <= 0.40]
    res_cands = [c for c in res_cands if 0.01 <= (c['price'] - price) / price <= 0.60]
    sup_zones = _cluster_levels(sup_cands)            # desc: nearest below first
    res_zones = _cluster_levels(res_cands)[::-1]      # asc: nearest above first

    if not sup_zones or not res_zones:
        return None

    # Buy zone 1 = nearest support; buy zone 2 = best confluence deeper down
    buy1 = sup_zones[0]
    deeper = sup_zones[1:]
    buy2 = max(deeper, key=lambda z: (z['score'], z['mid'])) if deeper else None
    sell1 = res_zones[0]
    farther = res_zones[1:]
    sell2 = max(farther, key=lambda z: z['score']) if farther else None

    csp1 = _liquid_strike(buy1['lo'], 'down')
    csp2 = _liquid_strike(buy2['lo'], 'down') if buy2 else None
    cc1 = _liquid_strike(sell1['hi'], 'up')

    def _pct(v):
        return f"{(v - price) / price * 100:+.0f}%"

    buy_txt = (f"{_zone_str(buy1)} ({_pct(buy1['mid'])}; {_zone_srcs(buy1)}) "
               f"-> CSP {_fmt_strike(csp1)}")
    if buy2:
        buy_txt += (f"; gilesnė {_zone_str(buy2)} ({_pct(buy2['mid'])}; {_zone_srcs(buy2)}) "
                    f"-> CSP {_fmt_strike(csp2)} (didesnė premija, stipresnė konfluencija)")
    sell_txt = (f"{_zone_str(sell1)} ({_pct(sell1['mid'])}; {_zone_srcs(sell1)}) "
                f"-> CC {_fmt_strike(cc1)}")
    if sell2:
        sell_txt += f"; trim zona {_zone_str(sell2)} ({_pct(sell2['mid'])}; {_zone_srcs(sell2)})"

    wait_txt = (f"Virš {_fmt_price(sell1['lo'])} uždarymo - momentum patvirtintas "
                f"(kelias į {_zone_str(sell2) if sell2 else 'aukštesnius ext'}); "
                f"pullback į {_zone_str(buy1)} - akumuliacijos taškas")

    w_trend = (w.get('trend_text') or '').lower()
    d_rsi = d.get('rsi') or 50
    w_bull = w_trend.startswith(('stiprus bull', 'bull'))
    w_bear = w_trend.startswith(('stiprus bear', 'bear'))
    if w_bull and d_rsi <= 50:
        leaps = (f"langas ATVIRAS - weekly bull + daily RSI {d_rsi:.0f} atvėsęs; "
                 f"deep ITM (delta ~0.8) 12-24 mėn.")
    elif w_bull and d_rsi >= 65:
        leaps = (f"struktūra bull, bet daily RSI {d_rsi:.0f} ištemptas - "
                 f"LEAPS pirkti pullback'e į {_zone_str(buy1)}, ne čia")
    elif w_bull:
        leaps = (f"dalinė pozicija OK (weekly bull, RSI {d_rsi:.0f}); "
                 f"pilna - {_zone_str(buy1)} zonoje arba virš {_fmt_price(sell1['hi'])} breakout")
    elif w_bear:
        leaps = f"NE - weekly struktūra prieš; peržiūrėti tik virš {_fmt_price(sell1['hi'])}"
    else:
        leaps = (f"tik {_zone_str(buy2 or buy1)} zonoje su weekly stabilizacija - "
                 f"struktūra dar nepatvirtinta")

    # Weekly insight: where price sits in the weekly fib structure
    w_fibs = sorted(((k, v) for k, v in (w.get('fib_ret') or {}).items()), key=lambda x: x[1])
    below = [(k, v) for k, v in w_fibs if v < price]
    above = [(k, v) for k, v in w_fibs if v >= price]
    pos_bits = []
    if below:
        k, v = below[-1]
        pos_bits.append(f"laikosi virš W {k} fib ({_fmt_price(v)})")
    if above:
        k, v = above[0]
        pos_bits.append(f"kitas weekly lygis viršuje - {k} fib ({_fmt_price(v)}, {_pct(v)})")
    weekly_insight = (f"{w.get('trend_text', '-')}, RSI {w.get('rsi', 0):.0f}"
                      + (": " + "; ".join(pos_bits) if pos_bits else ""))

    # Accumulation zones for the LONG-TERM investor: places to build a multi-year
    # position, not a trader's shallow dip. We prefer confluence (and weekly
    # levels) over mere proximity, so a lone -2% daily pivot doesn't get labelled
    # an accumulation zone when a meatier weekly-confluence zone exists.
    #   near = strongest-confluence support in a realistic, chart-visible band
    #   deep = strongest-confluence support clearly deeper ("major correction")
    def _has_weekly(z):
        return any(str(s).startswith('W ') for s in z['srcs'])

    def _depth(z):
        return (price - z['mid']) / price

    def _accum(z, label):
        lo, hi = float(z['lo']), float(z['hi'])
        mid = (lo + hi) / 2.0
        min_half = mid * 0.004  # >= 0.8% total band so it renders as a band
        if (hi - lo) < 2 * min_half:
            lo, hi = mid - min_half, mid + min_half
        return {'lo': round(lo, 2), 'hi': round(hi, 2), 'mid': round(mid, 2),
                'pct': _pct(z['mid']), 'label': label, 'srcs': _zone_srcs(z)}

    near_pool = [z for z in sup_zones if 0.02 <= _depth(z) <= 0.25]
    near = (max(near_pool, key=lambda z: (z['score'], _has_weekly(z), _depth(z)))
            if near_pool else buy1)
    deep_floor = max(0.10, _depth(near) + 0.03)
    deep_pool = [z for z in sup_zones if _depth(z) > deep_floor]
    deep = (max(deep_pool, key=lambda z: (z['score'], _has_weekly(z), _depth(z)))
            if deep_pool else None)

    accum_zones, _seen_mid = [], []
    for i, z in enumerate([near, deep]):
        if not z:
            continue
        if any(abs(z['mid'] - m) / z['mid'] < 0.01 for m in _seen_mid):
            continue
        _seen_mid.append(z['mid'])
        accum_zones.append(_accum(z, 'Akumuliacija' if not accum_zones else 'Gilesnė akumuliacija'))

    accum_txt = "; ".join(
        f"{_fmt_price(z['lo'])}-{_fmt_price(z['hi'])} ({z['pct']}; {z['srcs']})"
        for z in accum_zones
    )

    return {
        'buy': buy_txt,
        'sell': sell_txt,
        'leaps': leaps,
        'wait': wait_txt,
        'weekly_insight': weekly_insight,
        'accum_zones': accum_zones,
        'accum_txt': accum_txt,
    }


def _chart_payload(df: pd.DataFrame, fib_ret: dict, fib_ext: dict,
                   resistance: list, support: list,
                   ma50_series: pd.Series, ma200_series: pd.Series,
                   visible_bars: int = 130) -> dict:
    """Build Lightweight-Charts ready JSON payload.

    Outputs candles, MA series, and horizontal price lines for fib + S/R.
    visible_bars: how many recent daily bars to embed (default ~6mo).
    """
    recent = df.tail(visible_bars).copy()
    candles = []
    for idx, row in recent.iterrows():
        # Index is timezone-aware datetime; serialize as YYYY-MM-DD
        date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
        candles.append({
            'time': date_str,
            'open': float(row['Open']),
            'high': float(row['High']),
            'low': float(row['Low']),
            'close': float(row['Close']),
        })

    ma50_pts = []
    ma200_pts = []
    for idx, val in ma50_series.tail(visible_bars).items():
        if pd.notna(val):
            ma50_pts.append({'time': idx.strftime('%Y-%m-%d'), 'value': float(val)})
    for idx, val in ma200_series.tail(visible_bars).items():
        if pd.notna(val):
            ma200_pts.append({'time': idx.strftime('%Y-%m-%d'), 'value': float(val)})

    fib_ret_lines = [
        {'label': f'fib {k}', 'value': float(v), 'color': '#b794f4', 'style': 2}
        for k, v in fib_ret.items()
    ]
    fib_ext_lines = [
        {'label': f'{k} ext', 'value': float(v), 'color': '#9d7be0', 'style': 2}
        for k, v in fib_ext.items()
    ]
    res_lines = [
        {'label': f"R{i+1}", 'value': float(r['price']), 'color': '#ff7373', 'style': 0}
        for i, r in enumerate(resistance[:2])
    ]
    sup_lines = [
        {'label': f"S{i+1}", 'value': float(s['price']), 'color': '#7ed87e', 'style': 0}
        for i, s in enumerate(support[:2])
    ]

    return {
        'candles': candles,
        'ma50': ma50_pts,
        'ma200': ma200_pts,
        'fib_ret': fib_ret_lines,
        'fib_ext': fib_ext_lines,
        'resistance': res_lines,
        'support': sup_lines,
    }


def _live_price(t, fallback: float) -> float:
    """Freshest last price - covers the case where yfinance's last daily bar is
    a forming/NaN candle (so its Close lags the actual latest close). Tries
    fast_info then .info, falls back to the last complete close."""
    try:
        lp = t.fast_info.last_price
        if lp and not pd.isna(lp) and lp > 0:
            return float(lp)
    except Exception:
        pass
    try:
        rp = t.info.get('regularMarketPrice')
        if rp and not pd.isna(rp) and rp > 0:
            return float(rp)
    except Exception:
        pass
    return fallback


def _compute_one(df: pd.DataFrame, lookback_bars: int, label: str,
                 current_price: float = None) -> dict:
    """Compute full TA for one timeframe (daily or weekly).

    current_price: when set, overrides the last-bar close for the displayed
    price, trend, level-distances and setup (levels themselves stay computed
    off completed bars - standard daily-TA practice). Used when the last bar
    is a forming/NaN candle so the close lags reality.
    """
    if df is None or len(df) < 30:
        return {'available': False, 'label': label}
    closes = df['Close']
    price = float(current_price) if current_price else float(closes.iloc[-1])
    ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
    ma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    ma200 = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None
    rsi = _rsi(closes, 14)

    low_p, low_d, high_p, high_d, direction = _detect_swing(df, lookback_bars)
    fib_ret = _fib_retracement(low_p, high_p) if low_p and high_p else {}
    fib_ext = _fib_extension(low_p, high_p) if low_p and high_p else {}

    pivots_hi, pivots_lo = _pivots(df.tail(lookback_bars), window=5)
    levels = _key_levels(price, pivots_hi, pivots_lo, fib_ret, fib_ext, ma50 or 0, ma200 or 0)

    trend_text, trend_emoji = _trend_label(price, ma20 or 0, ma50 or 0, ma200 or 0)

    setup = _setup(price, trend_text, levels, rsi, fib_ret, ma50 or 0)

    r1_pct = ((levels['resistance'][0]['price'] - price) / price * 100) if levels['resistance'] else 0
    s1_pct = ((price - levels['support'][0]['price']) / price * 100) if levels['support'] else 0

    verdict_text = _verdict(trend_text, rsi, r1_pct, s1_pct)

    return {
        'available': True,
        'label': label,
        'price_str': _fmt_price(price),
        'trend_text': trend_text,
        'trend_emoji': trend_emoji,
        'rsi': rsi,
        'rsi_label': _rsi_label(rsi),
        'ma20_str': _fmt_price(ma20) if ma20 else '-',
        'ma50_str': _fmt_price(ma50) if ma50 else '-',
        'ma200_str': _fmt_price(ma200) if ma200 else '-',
        'swing_low_str': _fmt_price(low_p),
        'swing_high_str': _fmt_price(high_p),
        'swing_direction': direction,
        'fib_ret': {k: _fmt_price(v) for k, v in fib_ret.items()},
        'fib_ext': {k: _fmt_price(v) for k, v in fib_ext.items()},
        'resistance': [{'price_str': _fmt_price(r['price']), 'label': r['label'],
                        'dist_pct': f"+{(r['price'] - price) / price * 100:.1f}%"}
                       for r in levels['resistance']],
        'support': [{'price_str': _fmt_price(s['price']), 'label': s['label'],
                     'dist_pct': f"-{(price - s['price']) / price * 100:.1f}%"}
                    for s in levels['support']],
        'setup': setup,
        'verdict': verdict_text,
        # Raw numerics for the options playbook (not rendered directly)
        'raw': {
            'price': price, 'rsi': rsi, 'trend_text': trend_text,
            'ma20': ma20, 'ma50': ma50, 'ma200': ma200,
            'fib_ret': fib_ret, 'fib_ext': fib_ext,
            'pivots_hi': pivots_hi, 'pivots_lo': pivots_lo,
        },
    }


def compute_ta(ticker: str, name: str = None) -> Optional[dict]:
    """Fetch and compute daily + weekly TA for one ticker."""
    try:
        t = yf.Ticker(ticker)
        daily = t.history(period='2y', interval='1d', auto_adjust=False)
        weekly = t.history(period='5y', interval='1wk', auto_adjust=False)
        # yfinance appends a forming (today/this-week) candle with NaN OHLC for
        # some tickers - that makes Close.iloc[-1] NaN and silently kills price,
        # levels and the options playbook. Drop incomplete rows so every
        # computation uses the last COMPLETE bar. (2026-06-16: MU/TSLA/NBIS/AMZN
        # lost their playbook this way.)
        if daily is not None:
            daily = daily.dropna(subset=['Close'])
        if weekly is not None:
            weekly = weekly.dropna(subset=['Close'])
        if daily is None or len(daily) < 30:
            return None
    except Exception as e:
        print(f"  warn: TA fetch failed for {ticker}: {e}")
        return None

    cfg = _load_config()
    lookback_daily_bars = cfg.get('lookback_daily_weeks', 26) * 5  # ~5 trading days/week
    lookback_weekly_bars = cfg.get('lookback_weekly_years', 2) * 52

    # Current price + 1d change. Use the freshest live price (handles the case
    # where yfinance's latest daily bar is a forming/NaN candle that lags the
    # real last close - e.g. MU/MRVL on 2026-06-16 showed Friday not Monday).
    last_close = float(daily['Close'].iloc[-1])
    cur = _live_price(t, last_close)
    if len(daily) >= 2:
        prev = float(daily['Close'].iloc[-2])
        change_pct = (cur - prev) / prev * 100
    else:
        change_pct = 0.0

    daily_ta = _compute_one(daily, lookback_daily_bars, 'Daily', current_price=cur)
    weekly_ta = _compute_one(weekly, lookback_weekly_bars, 'Weekly', current_price=cur)

    # Chart payload for Lightweight Charts (daily timeframe, last ~6mo)
    chart = None
    if daily_ta.get('available'):
        recent = daily.tail(lookback_daily_bars)
        low_p, _, high_p, _, _ = _detect_swing(recent, lookback_daily_bars)
        if low_p and high_p:
            fib_ret_raw = _fib_retracement(low_p, high_p)
            fib_ext_raw = _fib_extension(low_p, high_p)
            pivots_hi_raw, pivots_lo_raw = _pivots(recent, window=5)
            ma50_series = daily['Close'].rolling(50).mean()
            ma200_series = daily['Close'].rolling(200).mean()
            levels = _key_levels(cur, pivots_hi_raw, pivots_lo_raw,
                                 fib_ret_raw, fib_ext_raw,
                                 float(ma50_series.iloc[-1]) if pd.notna(ma50_series.iloc[-1]) else 0,
                                 float(ma200_series.iloc[-1]) if pd.notna(ma200_series.iloc[-1]) else 0)
            chart = _chart_payload(daily, fib_ret_raw, fib_ext_raw,
                                   levels['resistance'], levels['support'],
                                   ma50_series, ma200_series,
                                   visible_bars=130)

    playbook = None
    if daily_ta.get('available') and weekly_ta.get('available'):
        try:
            playbook = _options_playbook(daily_ta.get('raw'), weekly_ta.get('raw'))
        except Exception as e:
            print(f"  warn: playbook failed for {ticker}: {e}")

    # Hand the accumulation zones to the chart so it can shade them as bands.
    if chart and playbook and playbook.get('accum_zones'):
        chart['accum_zones'] = playbook['accum_zones']

    return {
        'ticker': ticker,
        'name': name or ticker,
        'price_str': _fmt_price(cur),
        'change_pct_str': _fmt_pct(change_pct),
        'change_dir': 'up' if change_pct >= 0 else 'down',
        'daily': daily_ta,
        'weekly': weekly_ta,
        'chart': chart,
        'playbook': playbook,
    }


def fetch_ta_watchlist(dynamic_tickers: list[str] = None) -> list[dict]:
    """Compute TA for all configured tickers. dynamic_tickers = movers/news additions."""
    cfg = _load_config()
    core = cfg.get('core', [])
    max_dyn = cfg.get('max_dynamic', 0)
    dynamic = []
    if dynamic_tickers and max_dyn > 0:
        for t in dynamic_tickers:
            if t not in core and t not in dynamic:
                dynamic.append(t)
                if len(dynamic) >= max_dyn:
                    break
    all_tickers = core + dynamic
    core_set = set(core)
    print(f"  TA: computing for {len(all_tickers)} tickers ({len(core)} core + {len(dynamic)} dynamic)...")
    out = []
    for t in all_tickers:
        result = compute_ta(t)
        if not result:
            print(f"    warn: TA skipped for {t}")
            continue
        # Dynamic movers can surface junk (leveraged ETNs, sub-$5 tickers) with
        # no clean level structure - if the playbook couldn't build zones, the
        # card is noise. Keep core always; drop playbook-less dynamic cards.
        if t not in core_set and not result.get('playbook'):
            print(f"    skip dynamic {t}: no usable level structure")
            continue
        out.append(result)
    print(f"  -> {len(out)}/{len(all_tickers)} TA cards generated")
    return out


if __name__ == '__main__':
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'MU'
    result = compute_ta(ticker)
    if not result:
        print(f"No data for {ticker}")
        sys.exit(1)
    import json
    print(json.dumps(result, indent=2, default=str))
