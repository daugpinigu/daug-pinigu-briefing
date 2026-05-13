"""Radoslav stocks watchlist and crypto symbols."""

# Stocks watchlist (yfinance symbols)
STOCKS = [
    'ASML', 'SNDK', 'MU', 'META', 'AMD', 'TSLA', 'GLD', 'AVGO', 'MSFT', 'GOOGL',
    'UNH', 'AAPL', 'BE', 'AMZN', 'ADBE', 'ENS', 'NVDA', 'MSTR', 'NBIS', 'RDDT',
    'BIDU', 'PLTR', 'BABA', 'RKLB', 'DUOL', 'CRWV', 'ZM', 'SHOP', 'NFLX', 'HOOD',
    'IREN', 'NVO', 'PYPL', 'ENPH', 'HIMS', 'RIOT', 'GME', 'BMNR', 'FIG', 'ZETA',
    'SOFI', 'TSLL', 'OSS', 'CLSK', 'PATH', 'CONL', 'SBET', 'GRAB', 'VLN', 'BMNU',
]

# Crypto (CoinGecko IDs)
CRYPTO = [
    ('bitcoin', 'BTC', 'Bitcoin'),
    ('ethereum', 'ETH', 'Ethereum'),
    ('solana', 'SOL', 'Solana'),
    ('chainlink', 'LINK', 'Chainlink'),
    ('bittensor', 'TAO', 'Bittensor'),
]

# Futures of interest (yfinance syntax)
FUTURES = [
    ('ES=F', 'S&P 500'),
    ('NQ=F', 'Nasdaq 100'),
    ('YM=F', 'Dow'),
    ('RTY=F', 'Russell 2k'),
    ('^VIX', 'VIX'),
    ('CL=F', 'Crude Oil'),
    ('GC=F', 'Gold'),
]

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
