# Daily Briefing - daug_pinigu

Automatinis kasdieninis investicinis briefing'as. Renka makro events, top earnings ir market movers, generuoja PNG vizualą ir siunčia į Telegram.

## Kas tame briefing'e

- **Macro events** - dienos makro events (CPI, FOMC, jobs, GDP ir t.t.) su Vilniaus laiko zona. Filtruoja JAV, EZ, DE, GB, CN, JP, LT.
- **Top earnings** - top 10 dienos earnings pagal market cap (>$10B)
- **Market movers** - top 5 gainers/losers
- **Key takeaway** - dienos svarbiausias dalykas vienoje frazėje

## Lokalus paleidimas

```bash
cd projects/daily-briefing
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# .env failas su TELEGRAM_BOT_TOKEN ir TELEGRAM_CHAT_ID jau yra
cd src && python3 main.py
```

PNG įrašomas į `output/briefing-YYYY-MM-DD.png` ir iškart siunčiamas į Telegram.

## Deployment'as - GitHub Actions

GitHub Actions paleidžia script'ą kasdien 07:00 Vilniaus laiku (darbo dienomis).

### Setup'as:

1. Sukurk private GitHub repo (pvz., `daug-pinigu-briefing`).
2. Šitas projektas (visas `daily-briefing/` aplankas) - pirmas commit'as į repo.
3. Repo settings → Secrets and variables → Actions → New repository secret:
   - `TELEGRAM_BOT_TOKEN` = tavo bot token
   - `TELEGRAM_CHAT_ID` = tavo chat ID
4. Actions tab'e patikrink, ar workflow'as įgalintas.
5. Manual run iš `Actions → Daily Briefing → Run workflow` patikrinimui.

### Cron grafikas

Workflow'as `.github/workflows/daily.yml`:
- 04:00 UTC ir 05:00 UTC (=07:00 Vilnius, abi DST'os padengtos)
- Tik darbo dienomis (Pn-Pn)
- `workflow_dispatch` - rankinis paleidimas iš UI

## Failai

```
daily-briefing/
├── .github/workflows/daily.yml    # GitHub Actions cron
├── src/
│   ├── fetch.py                   # data fetchers (Yahoo, Finviz)
│   ├── render.py                  # HTML → PNG via Playwright
│   ├── send.py                    # Telegram bot API
│   └── main.py                    # orchestrator
├── templates/briefing.html        # Jinja2 template
├── output/                        # generated PNGs (gitignored)
├── requirements.txt
├── .env                           # secrets (gitignored)
└── .env.example                   # template
```

## Saugumas

- `.env` failas su token'u į git NEEINA (jau yra `.gitignore`)
- GitHub Actions naudoja Secrets - užšifruoti, nematomi log'uose
- Bot token'as = visiškas valdymas botui. Jei nutekės - @BotFather → `/revoke` ir gauk naują

## Data šaltiniai

- **Yahoo Finance** - economic calendar, earnings calendar (scrape, no API key)
- **Finviz** - pre-market gainers/losers (scrape, no API key)

Visi šaltiniai nemokami, be API key'ų. Jei kada nors lūš dėl pakeitimų - reikės atnaujinti scraping logic'ą `src/fetch.py`.

## Tobulinimas ateityje

- Pridėti weekly overview (sekmadienio briefing'as su visa savaite)
- Open positions tracker (reikalauja sąrašo)
- Pre-market futures (ES, NQ, YM, RTY) ir VIX
- Specifinių watchlist tickers individualus monitoring'as
- AI sektoriaus dedicated sekcija (Nvidia, Anthropic stake stocks)
