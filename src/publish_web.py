"""Save briefing HTML for GitHub Pages and regenerate index."""
from pathlib import Path
from datetime import datetime
import re

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / 'docs'
BRIEFINGS_DIR = DOCS_DIR / 'briefings'

LT_MONTHS = {
    1: 'sausio', 2: 'vasario', 3: 'kovo', 4: 'balandžio', 5: 'gegužės',
    6: 'birželio', 7: 'liepos', 8: 'rugpjūčio', 9: 'rugsėjo',
    10: 'spalio', 11: 'lapkričio', 12: 'gruodžio',
}


def save_briefing_html(html: str, date_str: str) -> Path:
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)
    out = BRIEFINGS_DIR / f"briefing-{date_str}.html"
    out.write_text(html, encoding='utf-8')
    return out


def regenerate_index() -> Path:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(BRIEFINGS_DIR.glob('briefing-*.html'), reverse=True)
    entries = []
    for f in files:
        m = re.match(r'briefing-(\d{4})-(\d{2})-(\d{2})\.html', f.name)
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(y, mo, d)
            label = f"{y} m. {LT_MONTHS[mo]} {d} d."
        except (KeyError, ValueError):
            label = f.stem
            dt = None
        entries.append({
            'href': f"briefings/{f.name}",
            'label': label,
            'weekday': dt.strftime('%A') if dt else '',
            'iso': f"{y}-{mo:02d}-{d:02d}",
        })

    index_html = _build_index_html(entries)
    out = DOCS_DIR / 'index.html'
    out.write_text(index_html, encoding='utf-8')
    return out


def _build_index_html(entries: list) -> str:
    rows = '\n'.join(
        f'''        <a class="row" href="{e['href']}">
          <div class="row-date">{e['label']}</div>
          <div class="row-iso">{e['iso']}</div>
        </a>'''
        for e in entries
    ) or '        <div class="empty">Dar nėra briefing\'ų.</div>'

    return f'''<!DOCTYPE html>
<html lang="lt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>daug_pinigu - Dienos Briefing'ai</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ background: #0a0e1a; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif;
    background: #0a0e1a;
    color: #e6e8ee;
    max-width: 760px;
    margin: 0 auto;
    padding: 50px 24px 40px;
    min-height: 100vh;
  }}
  header {{
    border-bottom: 2px solid rgba(244,204,107,0.2);
    padding-bottom: 24px;
    margin-bottom: 32px;
  }}
  h1 {{
    font-size: 36px;
    font-weight: 800;
    color: #f4cc6b;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }}
  .sub {{ color: #8a92a3; font-size: 15px; }}
  .row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 18px 22px;
    background: rgba(255,255,255,0.04);
    border-left: 3px solid #f4cc6b;
    border-radius: 8px;
    margin-bottom: 10px;
    text-decoration: none;
    color: #e6e8ee;
    transition: background 0.15s, transform 0.15s;
  }}
  .row:hover {{ background: rgba(244,204,107,0.08); transform: translateX(4px); }}
  .row-date {{ font-size: 16px; font-weight: 600; }}
  .row-iso {{ font-size: 12px; color: #8a92a3; font-variant-numeric: tabular-nums; }}
  .empty {{ color: #6c7588; padding: 30px 0; text-align: center; }}
  footer {{
    margin-top: 40px;
    color: #6c7588;
    font-size: 12px;
    text-align: center;
  }}
</style>
</head>
<body>
  <header>
    <h1>daug_pinigu briefing\'ai</h1>
    <div class="sub">Kasdieniniai investiciniai pranešimai · paskutiniai virsuje</div>
  </header>
  <main>
{rows}
  </main>
  <footer>Generuojama automatiškai · Šaltiniai: Yahoo Finance, CoinGecko</footer>
</body>
</html>
'''


if __name__ == '__main__':
    regenerate_index()
    print(f"Regenerated index: {DOCS_DIR / 'index.html'}")
