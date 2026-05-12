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
