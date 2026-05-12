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
    ('CL=F', 'Crude Oil'),
    ('GC=F', 'Gold'),
    ('ES=F', 'S&P 500'),
    ('NQ=F', 'Nasdaq 100'),
    ('^VIX', 'VIX'),
]
