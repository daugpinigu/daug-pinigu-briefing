"""Render Jinja2 HTML template to PNG via Playwright."""
import asyncio
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / 'templates'
OUTPUT_DIR = ROOT / 'output'


def render_html(template_name: str, context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(['html', 'xml']),
    )
    tpl = env.get_template(template_name)
    return tpl.render(**context)


async def html_to_png_async(html: str, output_path: Path, width: int = 1080) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            viewport={'width': width, 'height': 1920},
            device_scale_factor=2,
        )
        page = await context.new_page()
        await page.set_content(html, wait_until='networkidle')
        # Extra wait for Lightweight Charts (canvas) to fully render
        try:
            await page.wait_for_function(
                """() => {
                    const containers = document.querySelectorAll('.ta-chart-container[data-ticker]');
                    if (containers.length === 0) return true;
                    return Array.from(containers).every(c =>
                        c.querySelector('canvas') !== null
                    );
                }""",
                timeout=15000,
            )
            await page.wait_for_timeout(800)  # final paint settle
        except Exception:
            pass
        await page.screenshot(path=str(output_path), full_page=True, type='png')
        await browser.close()
    return output_path


def html_to_png(html: str, output_path: Path, width: int = 1080) -> Path:
    return asyncio.run(html_to_png_async(html, output_path, width))


if __name__ == '__main__':
    sample_context = {
        'date_long': '2026 m. gegužės 12 d., antradienis',
        'macro_events': [
            {'time_local': '15:30', 'country': 'US', 'name': 'CPI YoY', 'high_impact': True,
             'expected': '2.9%', 'prior': '3.1%'},
        ],
        'earnings': [
            {'symbol': 'AAPL', 'company': 'Apple Inc.', 'call_time': 'AMC',
             'eps_est': '1.50', 'market_cap': '3.2T'},
        ],
        'movers': {
            'gainers': [{'symbol': 'NVDA', 'price': '950', 'change': '5.2%', 'company': 'Nvidia'}],
            'losers': [{'symbol': 'XYZ', 'price': '10', 'change': '-15.0%', 'company': 'Xyz Corp'}],
        },
        'takeaway': 'CPI 15:30 - didžiausias šios dienos event\'as.',
        'generated_at': '07:00',
    }
    html = render_html('briefing.html', sample_context)
    out = html_to_png(html, OUTPUT_DIR / 'sample.png')
    print(f"Rendered: {out}")
