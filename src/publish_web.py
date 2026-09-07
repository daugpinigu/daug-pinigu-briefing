"""Save briefing HTML for GitHub Pages and regenerate index."""
from pathlib import Path
from datetime import datetime
import re
import json

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / 'docs'
BRIEFINGS_DIR = DOCS_DIR / 'briefings'

NAV_START = '<!-- BRIEF-NAV-START -->'
NAV_END = '<!-- BRIEF-NAV-END -->'
LATEST_NAME = 'latest.html'

LT_WEEKDAYS = ['pirmadienis', 'antradienis', 'trečiadienis', 'ketvirtadienis',
               'penktadienis', 'šeštadienis', 'sekmadienis']

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
            'weekday': LT_WEEKDAYS[dt.weekday()] if dt else '',
            'iso': f"{y}-{mo:02d}-{d:02d}",
        })

    index_html = _build_index_html(entries)
    out = DOCS_DIR / 'index.html'
    out.write_text(index_html, encoding='utf-8')
    return out


def _build_index_html(entries: list) -> str:
    rows = '\n'.join(
        f'''        <a class="row" href="{e['href']}">
          <div class="row-date">{e['label']} <span class="row-wd">{e['weekday']}</span></div>
          <div class="row-iso">{e['iso']}</div>
        </a>'''
        for e in entries
    ) or '        <div class="empty">Dar nėra briefing\'ų.</div>'
    latest_btn = ''
    if entries:
        e0 = entries[0]
        latest_btn = (f'        <a class="latest-btn" href="{LATEST_NAME}">'
                      f'<span>&#9889; Atidaryti naujausią</span>'
                      f'<small>{e0["label"]} · {e0["weekday"]}</small></a>')

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
  .row-iso {{ font-size: 12px; color: #8a92a3; font-variant-numeric: tabular-nums; white-space: nowrap; margin-left: 12px; }}
  .row-wd {{ font-size: 12px; color: #8a92a3; font-weight: 400; margin-left: 6px; }}
  .latest-btn {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 20px 22px; margin-bottom: 22px; border-radius: 10px;
    background: rgba(244,204,107,0.12); border: 1px solid rgba(244,204,107,0.45);
    color: #f4cc6b; font-size: 17px; font-weight: 700; text-decoration: none;
    transition: background 0.15s;
  }}
  .latest-btn:hover {{ background: rgba(244,204,107,0.22); }}
  .latest-btn small {{ font-size: 12px; font-weight: 500; color: #e6e8ee; opacity: 0.8; }}
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
{latest_btn}
{rows}
  </main>
  <footer>Generuojama automatiškai · Šaltiniai: Yahoo Finance, CoinGecko</footer>
</body>
</html>
'''


# ---------------------------------------------------------------------------
# Navigation bar (prev / next / latest / archive) injected into every briefing
# ---------------------------------------------------------------------------

def _list_dates() -> list[str]:
    """Sorted ISO dates of all published briefings (oldest first)."""
    dates = []
    for f in BRIEFINGS_DIR.glob('briefing-*.html'):
        m = re.match(r'briefing-(\d{4}-\d{2}-\d{2})\.html$', f.name)
        if m:
            dates.append(m.group(1))
    return sorted(dates)


def _lt_label(iso: str) -> tuple[str, str]:
    try:
        dt = datetime.strptime(iso, '%Y-%m-%d')
        return f"{dt.year} m. {LT_MONTHS[dt.month]} {dt.day} d.", LT_WEEKDAYS[dt.weekday()]
    except ValueError:
        return iso, ''


NAV_CSS = """
<style>
  .brief-nav { position: sticky; top: 0; z-index: 1000; display: flex; align-items: center;
    justify-content: space-between; gap: 8px; flex-wrap: wrap;
    margin: -40px -44px 24px; padding: 10px 44px;
    background: rgba(10,14,26,0.92); backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
    border-bottom: 1px solid rgba(244,204,107,0.25);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", system-ui, sans-serif; }
  .brief-nav .bn-group { display: flex; align-items: center; gap: 6px; }
  .brief-nav a, .brief-nav span.bn-btn { display: inline-flex; align-items: center; gap: 6px;
    padding: 7px 12px; border-radius: 8px; font-size: 13px; font-weight: 600; line-height: 1;
    text-decoration: none; color: #e6e8ee; background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.08); white-space: nowrap; transition: background .15s; }
  .brief-nav a:hover { background: rgba(244,204,107,0.16); border-color: rgba(244,204,107,0.4); }
  .brief-nav span.bn-btn.bn-disabled { opacity: 0.35; cursor: default; }
  .brief-nav a.bn-latest { background: rgba(244,204,107,0.14); color: #f4cc6b; border-color: rgba(244,204,107,0.45); }
  .brief-nav a.bn-latest:hover { background: rgba(244,204,107,0.28); }
  .brief-nav .bn-current { font-size: 13px; color: #8a92a3; font-variant-numeric: tabular-nums; text-align: center; }
  .brief-nav .bn-current b { color: #e6e8ee; font-weight: 600; }
  @media (max-width: 720px) {
    .brief-nav { margin: -20px -16px 16px; padding: 8px 12px; }
    .brief-nav a, .brief-nav span.bn-btn { padding: 8px 10px; font-size: 12px; }
    .brief-nav .bn-current { width: 100%; order: -1; font-size: 12px; }
    .brief-nav .bn-label { display: none; }
  }
</style>
"""


def build_nav_html(date_iso: str, prev_iso, next_iso,
                   latest_iso: str) -> str:
    label, weekday = _lt_label(date_iso)
    is_latest = date_iso == latest_iso

    if prev_iso:
        prev_btn = (f'<a href="briefing-{prev_iso}.html" rel="prev" title="{prev_iso}">'
                    f'&#8592; <span class="bn-label">Ankstesnis</span></a>')
    else:
        prev_btn = '<span class="bn-btn bn-disabled">&#8592; <span class="bn-label">Ankstesnis</span></span>'

    if next_iso:
        next_btn = (f'<a href="briefing-{next_iso}.html" rel="next" title="{next_iso}">'
                    f'<span class="bn-label">Kitas</span> &#8594;</a>')
    else:
        next_btn = '<span class="bn-btn bn-disabled"><span class="bn-label">Kitas</span> &#8594;</span>'

    latest_btn = ('' if is_latest else
                  f'<a class="bn-latest" href="{LATEST_NAME}" title="Naujausias briefing\'as">&#9889; Naujausias</a>')
    current_tag = ' · <span style="color:#f4cc6b">naujausias</span>' if is_latest else ''

    return (
        f'{NAV_START}{NAV_CSS}'
        f'<nav class="brief-nav" data-date="{date_iso}"'
        f'{" data-prev=%s" % chr(34) + prev_iso + chr(34) if prev_iso else ""}'
        f'{" data-next=%s" % chr(34) + next_iso + chr(34) if next_iso else ""}>'
        f'<div class="bn-group">{prev_btn}{next_btn}</div>'
        f'<div class="bn-current"><b>{label}</b> · {weekday}{current_tag}</div>'
        f'<div class="bn-group">{latest_btn}'
        f'<a href="../index.html" title="Visi briefing\'ai">&#9776; Visi</a></div>'
        f'</nav>'
        '<script>document.addEventListener("keydown",function(e){'
        'if(e.target&&/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;'
        'var n=document.querySelector(".brief-nav");if(!n)return;'
        'if(e.key==="ArrowLeft"&&n.dataset.prev)location.href="briefing-"+n.dataset.prev+".html";'
        'if(e.key==="ArrowRight"&&n.dataset.next)location.href="briefing-"+n.dataset.next+".html";});</script>'
        f'{NAV_END}'
    )


def inject_nav(html: str, nav: str) -> str:
    """Insert nav right after <body>; replace an existing one (idempotent)."""
    if NAV_START in html and NAV_END in html:
        return re.sub(re.escape(NAV_START) + r'.*?' + re.escape(NAV_END), lambda _: nav, html,
                      count=1, flags=re.S)
    m = re.search(r'<body[^>]*>', html)
    if not m:
        return html
    return html[:m.end()] + '\n' + nav + '\n' + html[m.end():]


def patch_all_briefings() -> int:
    """Re-inject nav into every briefing so prev/next/latest links stay correct.
    Only rewrites files whose content actually changes (keeps git diffs small)."""
    dates = _list_dates()
    if not dates:
        return 0
    latest = dates[-1]
    changed = 0
    for i, d in enumerate(dates):
        prev_iso = dates[i - 1] if i > 0 else None
        next_iso = dates[i + 1] if i + 1 < len(dates) else None
        path = BRIEFINGS_DIR / f'briefing-{d}.html'
        html = path.read_text(encoding='utf-8')
        new_html = inject_nav(html, build_nav_html(d, prev_iso, next_iso, latest))
        if new_html != html:
            path.write_text(new_html, encoding='utf-8')
            changed += 1
    return changed


def write_latest_redirect():
    """docs/briefings/latest.html + docs/latest.html -> newest briefing (stable URL)."""
    dates = _list_dates()
    if not dates:
        return None
    latest = dates[-1]
    for target_dir, href in ((BRIEFINGS_DIR, f'briefing-{latest}.html'),
                             (DOCS_DIR, f'briefings/briefing-{latest}.html')):
        page = (
            '<!DOCTYPE html><html lang="lt"><head><meta charset="UTF-8">'
            '<meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={href}">'
            f'<script>location.replace("{href}");</script>'
            '<title>daug_pinigu briefing - naujausias</title>'
            '<style>body{background:#0a0e1a;color:#e6e8ee;font-family:system-ui,sans-serif;'
            'display:flex;align-items:center;justify-content:center;height:100vh;margin:0}'
            'a{color:#f4cc6b}</style></head>'
            f'<body><p>Nukreipiama į naujausią briefing\'ą ({latest})&hellip; '
            f'<a href="{href}">Atidaryti</a></p></body></html>\n'
        )
        (target_dir / LATEST_NAME).write_text(page, encoding='utf-8')
    return latest


def finalize_site() -> dict:
    """Everything that must run after a new briefing HTML is saved."""
    patched = patch_all_briefings()
    latest = write_latest_redirect()
    regenerate_index()
    (BRIEFINGS_DIR / 'manifest.json').write_text(
        json.dumps({'latest': latest, 'dates': _list_dates()}, indent=0), encoding='utf-8')
    return {'patched': patched, 'latest': latest}


if __name__ == '__main__':
    info = finalize_site()
    print(f"Site finalized: latest={info['latest']}, nav patched in {info['patched']} files, "
          f"index -> {DOCS_DIR / 'index.html'}")
