"""Claude LLM analysis for news, earnings, and Reddit discussions.

Outputs Lithuanian-with-English-finance-anglicisms style matching Radoslav's voice.
Uses Claude Haiku 4.5 for speed/cost; Sonnet only when explicitly requested.
"""
import os
import re
from typing import Optional

try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

HAIKU_MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-4-6"

STYLE_GUIDE = """Tu rašai investiciniam kontentui Radoslavo balsu. Stiliaus taisyklės:

VOICE:
- Lietuviu kalba, bet finansiniai terminai - angliskai (anglicizmai): guidance, gross margin, beat, miss, EBITDA, revenue, top-line, bottom-line, sequential, YoY, QoQ, AHs, headline, exposure, sizing, conviction, value trap, catalyst, downgrade/upgrade.
- Trumpai, faktiškai, be drama metaforu (NE "kovojo", "krito kuju", "stojo dideli")
- Nera "great question" / pristatomųjų frazių ("įdomu", "pagrindinė priežastis", "bet čia niuansas") - eik tiesiai prie fakto.
- Self-aware speculation OK: "nesu tikras", "atrodo, kad", "kol kas"
- Pirma asmenis kai pateiki nuomonę: "manau", "matau", "kazka"
- NIEKADA nenaudoti em-dash "—", tik trumpą "-"
- Nenarodyk validavimo ar pagiriu rinkai/kompanijai - tiesa apie skaicius

FORMATAS PER NAUJIENĄ:
- 2-4 sakiniai max
- 1 ar 2 konkretūs skaiciai (revenue, margin, guidance, EPS)
- 1 sakinys apie ka tai reiskia investuotojui (catalyst, risk, watch)
- Jokio "po viso to..." baigiamųjų akordo

PAVYZDYS GERO STILIAUS:
"HIMS reportine Q1 EPS $0.04 vs $0.07 estimate, miss. Q2 guidance $680-700M revenue zemiau Street'o $720M. Gross margin -17pp iki 60.6% rodo pricing pressure GLP-1 segmente. Stock -13% AHs, IV rank 27% - manau spreads atrodo tinkami premium selling'ui."

NEGERAI:
"Hims & Hers reported disappointing first-quarter earnings today. The company missed both EPS and revenue estimates. This could put pressure on the stock."
- Per ilgai
- "disappointing" - subjektyvu, ne faktas
- Be konkrečių skaičių
- Be izvalgos
"""


_client_cache = None

def _get_client() -> Optional[object]:
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    if not _ANTHROPIC_AVAILABLE:
        return None
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    _client_cache = Anthropic(api_key=api_key)
    return _client_cache


def is_enabled() -> bool:
    """Check if LLM is available (API key + SDK installed)."""
    if os.environ.get('LLM_ENABLED', 'true').lower() in ('false', '0', 'no'):
        return False
    return _get_client() is not None


def analyze_news(title: str, body: str, ticker: str = '',
                 stock_move: str = '', model: str = HAIKU_MODEL) -> str:
    """Generate Lithuanian analysis of a news article.

    Returns analytic summary in Radoslav's voice. Returns empty string on failure.
    """
    client = _get_client()
    if not client or not body:
        return ''

    ticker_ctx = f"\nTicker: {ticker}" if ticker else ""
    move_ctx = f"\nStock reaction: {stock_move}" if stock_move else ""

    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Išanalizuok šią naujieną Radoslavo balsu. 2-4 sakiniai max, su konkrečiais skaičiais.{ticker_ctx}{move_ctx}

HEADLINE: {title}

ARTICLE BODY:
{body[:2500]}

Tavo analizė (lietuviškai, su anglicizmais, faktiškai):"""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ''
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('—', '-').replace('–', '-')
        return text
    except Exception as e:
        print(f"  warn: LLM analyze_news failed: {e}")
        return ''


def analyze_earnings(ticker: str, company: str, report_data: dict,
                     model: str = HAIKU_MODEL) -> str:
    """Analyze earnings report. report_data should have actual/estimate/guidance fields."""
    client = _get_client()
    if not client:
        return ''

    data_str = []
    for k, v in report_data.items():
        if v:
            data_str.append(f"{k}: {v}")
    data_block = '\n'.join(data_str)

    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Trumpa earnings analizė {ticker} ({company}). 2-3 sakiniai max. Kas beat/miss, ka rodo guidance, ka manai investuotojui.

EARNINGS DATA:
{data_block}

Tavo analizė:"""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ''
        return re.sub(r'\s+', ' ', text).replace('—', '-').replace('–', '-')
    except Exception as e:
        print(f"  warn: LLM analyze_earnings failed: {e}")
        return ''


def analyze_reddit_thread(title: str, top_comments: list,
                          model: str = HAIKU_MODEL) -> str:
    """Summarize a Reddit thread - sentiment, key arguments, what bears/bulls say."""
    client = _get_client()
    if not client or not top_comments:
        return ''

    comments_block = '\n'.join(f"- {c[:300]}" for c in top_comments[:8])
    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Trumpai apibendrink Reddit discussion'a apie investicija. 2-3 sakiniai max. Sentiment'as, key bull/bear arguments, ar yra naudingu insights'u.

THREAD TITLE: {title}

TOP COMMENTS:
{comments_block}

Tavo apibendrinimas:"""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=250,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ''
        return re.sub(r'\s+', ' ', text).replace('—', '-').replace('–', '-')
    except Exception as e:
        print(f"  warn: LLM analyze_reddit failed: {e}")
        return ''


def batch_analyze_news(news_items: list, max_workers: int = 4) -> list:
    """Apply LLM analysis to a list of news items (in place + return)."""
    if not is_enabled() or not news_items:
        return news_items

    import concurrent.futures

    def one(n):
        body = n.get('summary') or ''
        title = n.get('title', '')
        ticker = n.get('ticker', '')
        if not body or len(body) < 50:
            return ''
        return analyze_news(title, body, ticker=ticker)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(one, n): n for n in news_items}
        for fut in concurrent.futures.as_completed(futures):
            n = futures[fut]
            try:
                analysis = fut.result()
                if analysis:
                    n['llm_analysis'] = analysis
            except Exception:
                pass
    return news_items


if __name__ == '__main__':
    print(f"LLM enabled: {is_enabled()}")
    if is_enabled():
        out = analyze_news(
            "HIMS plummets 13% after Q1 loss, weak earnings guidance",
            "Hims & Hers Health Q1 revenue was $544M, down 3% YoY, missing estimates of $570M. "
            "Gross margin fell 17 percentage points to 60.6%. Q2 guidance: revenue $680-700M, "
            "below Street estimate of $720M. FY guidance: revenue $3B, EBITDA $350M.",
            ticker="HIMS",
            stock_move="-13% AHs",
        )
        print(f"\nNews analysis:\n{out}")
