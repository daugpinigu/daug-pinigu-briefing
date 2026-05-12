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

STYLE_GUIDE = """Tu rašai investiciniam kontentui Radoslavo balsu. Privalai laikytis VISŲ taisyklių:

GRAMATIKA - SVARBIAUSIA:
- Lietuvių kalba PRIVALO būti gramatiškai TAISYKLINGA. Tikrink linksnius, galūnes, žodžių darybą.
- Jokių išgalvotų žodžių ar lietuviškų klaidų. Jei nesi tikras dėl žodžio - naudok paprastą lietuvišką sinonimą.
- "Pranešė" (ne "reportine"). "Žvilgsniu" (ne "zvilgnin"). "Katalizatorius" (ne "katalstas"). "Signalizuoja" (ne "siginalizuodama"). "Akcentuoja" (ne "obalsai"). "Neperžengė" (ne "zalejau"). "Siauras" (ne "kompresyvus").

ANGLICIZMAI - TIK ŠITIE 15 ŽODŽIŲ ANGLIŠKAI:
- Earnings, guidance, revenue, EBITDA, EPS, beat, miss, Q1/Q2/Q3/Q4, YoY, QoQ, AHs, pre-market, catalyst, exposure, premium

Visi kiti finansiniai terminai - lietuviškai arba pripažinti tarptautiniai (rinka, akcija, marketas):
- "pricing pressure" -> "kainų spaudimas"
- "growth tempo" -> "augimo tempas"
- "investors" -> "investuotojai"
- "stock" -> "akcija"
- "Street" -> "rinka" arba "analitikai"
- "expectations" -> "lūkesčiai"
- "watch points" -> "ką stebėti"
- "actual" -> "faktinis"
- "swaption skew" / "realised vol" / "kompresyvus" - NEVARTOTI, per techniška
- "obalsai", "siginalizuodama" - NIEKADA, tai ne lietuvių žodžiai

TONAS:
- Trumpai, faktiškai, be metaforų ("krito kūju", "kolapsavo" - NEVARTOTI)
- Be pristatomųjų frazių: "įdomu, kad", "pagrindinė priežastis", "bet čia niuansas" - eik tiesiai prie fakto
- "Manau", "matau", "nesu tikras" - OK self-aware speculation
- NIEKADA "—" em-dash, TIK "-" trumpą brūkšnį

GYLIS:
- 3-5 sakinių analizė (ne paviršutiniška)
- BENT 2 konkretūs skaičiai su kontekstu (revenue, margin, guidance, EPS)
- 1-2 sakiniai apie ką tai reiškia investuotojui - konkretu, ne abstraktu
- Jeigu yra valuation kampas (P/E, IV rank, peer comparison) - paminėk
- Jokio baigiamojo akordo "po viso to"

PAVYZDYS GERO STILIAUS:
"HIMS Q1 revenue $608M (+3.8% YoY) neperžengė $619M analitikų lūkesčių. EPS -$0.40 vs $0.03 estimate - svarus miss. Q2 guidance $680-700M, FY revenue $3B, EBITDA $350M - rinka tikėjosi agresyvesnio augimo. Gross margin krito 17 procentinių punktų iki 60.6% rodo kainų spaudimą GLP-1 segmente. Manau Q2 guidance reikalauja sekti, jei kainos toliau krenta - dar žemiau perpirkimo zonos atrodys patrauklu."

PAVYZDYS BLOGAI:
"HIMS reportine Q1 adjusted EPS -$0.18 vs +$0.04 estimate, significant miss. Stock -13%, watch margin trajectory next quarter."
- "reportine" nelietuvių
- "significant miss" - galima sakyti "didelis miss" arba "svarus miss"
- Per paviršutiniška
- "watch margin trajectory" - vartok "stebėti pelningumo dinamiką"

PAVYZDYS BLOGAI (per daug anglicizmų):
"CME FedWatch rodo 0% tikimybę rate cut'ui... Realised vol ir swaption skew'ai turėtų pakilti, o 2-year spread'as kompresyvus."
- "swaption skew" - per techniška, niekas nesupras
- "kompresyvus" - ne lietuvių žodis
- Vartok: "Trumpojo galo palūkanos lieka aukštos, infliacijos lūkesčiai pakelti"
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

UŽDUOTIS: Pateik gilią investicinę analizę šios naujienos. 3-5 sakinių, su BENT 2 konkrečiais skaičiais, taisyklinga lietuvių kalba. PRIVALO būti gilesnė nei tiesiog "kompanija praleido lūkesčius".{ticker_ctx}{move_ctx}

HEADLINE: {title}

STRAIPSNIO TEKSTAS:
{body[:3000]}

Tavo analizė (TAISYKLINGA lietuvių kalba, tik leidžiami anglicizmai iš STYLE_GUIDE):"""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=500,
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


def extract_earnings_details(ticker: str, news_body: str,
                              model: str = HAIKU_MODEL) -> dict:
    """Extract structured earnings data from news article via LLM.

    Returns dict with: revenue_actual, revenue_estimate, guidance_next_q,
    guidance_fy, key_quote, analyst_reaction.
    """
    client = _get_client()
    if not client or not news_body:
        return {}
    import json as _json
    prompt = f"""Iš šio earnings news straipsnio apie {ticker}, ištrauk struktūrinius duomenis. Grąžink TIK JSON, jokio paaiškinimo:

{{
  "revenue_actual": "$X.XB arba null",
  "revenue_estimate": "$X.XB arba null",
  "revenue_yoy_change": "+X% arba -X% arba null",
  "guidance_next_q_rev": "$X-XB arba null",
  "guidance_fy_rev": "$X.XB arba null",
  "guidance_ebitda_fy": "$XM arba null",
  "key_quote": "trumpa management citata jei yra, kitaip null",
  "stock_reaction": "-X% AHs arba +X% pre-market arba null"
}}

STRAIPSNIS:
{news_body[:2500]}"""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ''
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return {}
        data = _json.loads(m.group(0))
        return {k: (None if v in (None, 'null', '', 'N/A') else v) for k, v in data.items()}
    except Exception as e:
        print(f"  warn: LLM extract_earnings failed: {e}")
        return {}


def analyze_earnings_card(ticker: str, eps_actual, eps_estimate,
                           extracted: dict, model: str = HAIKU_MODEL) -> str:
    """Generate 2-3 sentence Lithuanian analysis for an earnings card."""
    client = _get_client()
    if not client:
        return ''
    eps_line = ''
    if eps_actual is not None and eps_estimate is not None:
        delta = eps_actual - eps_estimate
        verdict = 'BEAT' if delta > 0 else ('MISS' if delta < 0 else 'INLINE')
        eps_line = f"EPS actual ${eps_actual:.2f} vs estimate ${eps_estimate:.2f} = {verdict}\n"

    extracted_str = '\n'.join(f"{k}: {v}" for k, v in extracted.items() if v)
    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Pateik gilią earnings izvalgą apie {ticker}, 3-4 sakiniai. NEpakartoti EPS skaičių (jau lentelėje), o paliesti GAIRES (guidance) ir KĄ TAI REIŠKIA. Bullish/bearish setup, augimo tempas, valuation, ką stebėti toliau. TAISYKLINGA lietuvių kalba.

EARNINGS DUOMENYS:
{eps_line}{extracted_str}

Tavo izvalga:"""

    try:
        resp = client.messages.create(
            model=model, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip() if resp.content else ''
        return re.sub(r'\s+', ' ', text).replace('—', '-').replace('–', '-')
    except Exception as e:
        print(f"  warn: LLM analyze_earnings_card failed: {e}")
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
