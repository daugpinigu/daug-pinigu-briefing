"""Radoslav stocks watchlist and crypto symbols."""

# Stocks watchlist (yfinance symbols)
STOCKS = [
    'ASML', 'SNDK', 'MU', 'META', 'AMD', 'TSLA', 'GLD', 'AVGO', 'MSFT', 'GOOGL',
    'UNH', 'AAPL', 'BE', 'AMZN', 'ADBE', 'ENS', 'NVDA', 'MSTR', 'NBIS', 'RDDT',
    'BIDU', 'PLTR', 'BABA', 'RKLB', 'DUOL', 'CRWV', 'ZM', 'SHOP', 'NFLX', 'HOOD',
    'IREN', 'NVO', 'PYPL', 'ENPH', 'HIMS', 'RIOT', 'GME', 'BMNR', 'FIG', 'ZETA',
    'SOFI', 'TSLL', 'OSS', 'CLSK', 'PATH', 'CONL', 'SBET', 'GRAB', 'VLN', 'BMNU',
]

# Crypto treasury companies - GAAP EPS is dominated by non-cash
# mark-to-market of coin holdings (FASB fair value through income), so
# EPS vs analyst estimate is noise, not signal. Earnings cards for these
# tickers drop the BEAT/MISS verdict and the analysis is steered to
# treasury metrics instead (Radoslav 2026-07-15 after the BMNR card
# framed a -171% "EPS miss" as the story).
# label = neutral chip shown instead of BEAT/MISS; context = LLM framing.
CRYPTO_TREASURY = {
    'BMNR': {
        'label': 'ETH TREASURY',
        'context': ('BitMine Immersion - ETH treasury kompanija (Tom Lee chairman). '
                    'Visa tezė = ETH kaina ir ETH-per-share augimas, ne GAAP EPS: '
                    'nuostoliai/pelnai beveik vien non-cash ETH mark-to-market. '
                    'Analizuok: ETH holdings dydį ir pokytį, staking pajamas, '
                    'mNAV (market cap vs crypto+cash NAV) premiją ar discount, '
                    'dilution tempą (ATM emisijos), preferred (BMNP) kaštus.'),
    },
    'MSTR': {
        'label': 'BTC TREASURY',
        'context': ('Strategy (MicroStrategy) - BTC treasury. GAAP EPS dominuoja '
                    'BTC fair-value mark-to-market, ne signalas. Analizuok: BTC '
                    'holdings, BTC-per-share (BTC Yield), mNAV premiją/discount, '
                    'convertible/preferred (STRK/STRF/STRC) kaštus ir dividendų '
                    'padengimą, ATM dilution tempą.'),
    },
    'SBET': {
        'label': 'ETH TREASURY',
        'context': ('SharpLink Gaming - ETH treasury kompanija. GAAP EPS = ETH '
                    'mark-to-market triukšmas. Analizuok: ETH holdings ir '
                    'ETH-per-share, staking pajamas, mNAV premiją/discount, '
                    'dilution tempą.'),
    },
}

# Crypto (CoinGecko IDs)
CRYPTO = [
    ('bitcoin', 'BTC', 'Bitcoin'),
    ('ethereum', 'ETH', 'Ethereum'),
    ('solana', 'SOL', 'Solana'),
    ('chainlink', 'LINK', 'Chainlink'),
    ('bittensor', 'TAO', 'Bittensor'),
]

# Futures of interest (yfinance syntax). Order matters for display.
# All these are also available as ground-truth substitutions in manual_notes
# via the placeholder mechanism (e.g. {{wti}}, {{brent}}, {{gold}}, {{vix}}).
FUTURES = [
    ('ES=F', 'S&P 500'),
    ('NQ=F', 'Nasdaq 100'),
    ('YM=F', 'Dow'),
    ('RTY=F', 'Russell 2k'),
    ('^VIX', 'VIX'),
    ('CL=F', 'WTI Crude'),
    ('BZ=F', 'Brent Crude'),
    ('GC=F', 'Gold'),
    ('SI=F', 'Silver'),
    ('DX-Y.NYB', 'DXY'),
]

# Map placeholder name -> yfinance symbol for live-data substitution in
# manual_notes. Pipeline replaces {{name}} with the live spot price after
# fetching indices/crypto. Keep names short and lowercase.
PLACEHOLDER_SYMBOLS = {
    'sp500': 'ES=F',
    'nasdaq': 'NQ=F',
    'dow': 'YM=F',
    'russell': 'RTY=F',
    'vix': '^VIX',
    'wti': 'CL=F',
    'brent': 'BZ=F',
    'gold': 'GC=F',
    'silver': 'SI=F',
    'dxy': 'DX-Y.NYB',
}

PLACEHOLDER_CRYPTO = {
    'btc': 'bitcoin',
    'eth': 'ethereum',
    'sol': 'solana',
}

# AI sector core - dedicated section + news tracking
AI_TICKERS = [
    'NVDA', 'AMD', 'AVGO', 'MSFT', 'GOOGL', 'META', 'AMZN',
    'ASML', 'MU', 'TSM', 'ZM', 'PLTR', 'CRWV', 'NBIS',
]

# Tickers to fetch news for (limited to keep briefing fast)
NEWS_TICKERS = ['NVDA', 'AMZN', 'GOOGL', 'MSFT', 'META', 'ZM', 'PLTR', 'MU', 'AVGO']

# YouTube channels to monitor for daily insights (resolved 2026-05-13).
# Output rendered as synthesis prose - no channel/title attribution shown to reader.
YOUTUBE_CHANNELS = [
    ('UCBRpqrzuuqE8TZcWw75JSdw', 'The Compound'),           # Josh Brown, Michael Batnick
    ('UCcBzKSM4A-pIHMJWSnxmi_g', 'Fundstrat Direct'),       # Tom Lee
    ('UC6ipRbtXU3-xJLET6oz6Hsw', 'Couch Investor'),
    ('UC5cEHfCr6WOE1R1zcohd1IA', 'Jose Najarro Stocks'),    # Semis focus
    ('UCRhQsN8AVIfZuBNeRV1A37w', 'Norges Bank IM'),          # Norway sovereign fund
    ('UCPss8jtpAyp3k829QVX3jhQ', 'Steven Fiorillo'),
    ('UCvWx0-NX-9qVLCSW9yjdX-g', 'Future Investing'),
    ('UCD0yDGUSqKLyHviB6FUZzzg', 'Dr Crossroads'),           # Macro/geopolitics
]
