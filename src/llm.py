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

# Default model: Sonnet for quality Lithuanian + deeper analysis.
# Override via env LLM_MODEL=haiku for cost savings.
DEFAULT_MODEL = SONNET_MODEL if os.environ.get('LLM_MODEL', 'sonnet').lower() == 'sonnet' else HAIKU_MODEL

# Post-processing dictionary: bad LLM output -> proper Lithuanian
# Applied after LLM call to clean up common mistakes
CLEANUPS = [
    (re.compile(r'\breportine\b', re.I), 'pranešė'),
    (re.compile(r'\bsiginalizuod\w*\b', re.I), 'signalizuoja'),
    (re.compile(r'\bobalsai\b', re.I), 'akcentuoja'),
    (re.compile(r'\bzvilgnin\w*\b', re.I), 'žvilgsniu'),
    (re.compile(r'\bkatalstas\b', re.I), 'katalizatorius'),
    (re.compile(r'\bzalejau\b', re.I), 'neperžengė'),
    (re.compile(r'\bkompresyvus\b', re.I), 'siauras'),
    (re.compile(r'\binvestors\b', re.I), 'investuotojai'),
    (re.compile(r'\bexpectations\b', re.I), 'lūkesčiai'),
    (re.compile(r'\bcompression\b', re.I), 'spaudimas'),
    (re.compile(r'\bheadwind\b', re.I), 'neigiamas veiksnys'),
    (re.compile(r'\brefinancingui\b', re.I), 'refinansavimui'),
    (re.compile(r'\bdemand softening\b', re.I), 'paklausos silpnėjimas'),
    (re.compile(r'\bsignificantly miss\b', re.I), 'didelis miss'),
    (re.compile(r'\bsignificantly beat\b', re.I), 'didelis beat'),
    (re.compile(r'\benergia costs\b', re.I), 'energijos kaštai'),
    (re.compile(r'\bbyti\b', re.I), 'byrėti'),
    (re.compile(r'\blūkestis\b', re.I), 'lūkesčiai'),
    (re.compile(r'\bvaluation\b', re.I), 'vertinimas'),
    (re.compile(r'\bswaption skew\w*\b', re.I), 'palūkanų rizikos asimetrija'),
    (re.compile(r'\brealised vol\w*\b', re.I), 'realizuotas svyravimas'),
    (re.compile(r'\bduration exposure\b', re.I), 'trukmės pozicija'),
    (re.compile(r'\bdebt reduction\b', re.I), 'skolos mažinimas'),
    (re.compile(r'\bshareholder returns\b', re.I), 'akcininkų grąža'),
    (re.compile(r'\bcash inflows\b', re.I), 'pinigų įplaukos'),
    (re.compile(r'\bcash flow\b', re.I), 'pinigų srautas'),
    (re.compile(r'\bcapex\b', re.I), 'capex'),  # allowed but lowercase
    (re.compile(r'\bgrowth\b(?! tempas)', re.I), 'augimas'),
    (re.compile(r'\btop[\- ]line\b', re.I), 'pajamos'),
    (re.compile(r'\bbottom[\- ]line\b', re.I), 'pelnas'),
    (re.compile(r'\bmidday\b', re.I), 'vidurdienį'),
    (re.compile(r'\bpharma\b', re.I), 'farmacija'),
    (re.compile(r'\bpricing power\b', re.I), 'kainodaros galia'),
    (re.compile(r'\bcompetitive pressure\b', re.I), 'konkurencinis spaudimas'),
    (re.compile(r'\bmarjos\b', re.I), 'maržos'),
    (re.compile(r'\bSpread\w*\b', re.I), 'skirtumas'),
    # Typos found in production output
    (re.compile(r'\bscenrijus\b', re.I), 'scenarijus'),
    (re.compile(r'\bscenrij\w+\b', re.I), 'scenarijus'),
    (re.compile(r'\bnepalaank\w+\b', re.I), 'nepalankaus'),
    (re.compile(r'\bperstumdė\b', re.I), 'atidėjo'),
    (re.compile(r'\bperstumdo\b', re.I), 'atideda'),
    (re.compile(r'\bketvirčio punkto\b', re.I), '0.25 procentinio punkto'),
    (re.compile(r'\bsušvelninim\w+\b', re.I), 'atpalaidavimas'),
    # Awkward phrasings → cleaner Lithuanian
    (re.compile(r'\bturėjimo įmonė\b', re.I), 'kaupimo įmonė'),
    (re.compile(r'\bturėjimo bendrov\w+\b', re.I), 'kaupimo bendrovė'),
    (re.compile(r'\bšiuo lygiu\b', re.I), 'šiame lygyje'),
    (re.compile(r'\bguidance tikslumas\b', re.I), 'guidance tikslas'),
    (re.compile(r'\bplėtros tempo\b', re.I), 'plėtros tempas'),
    (re.compile(r'\bvienerius metus\b', re.I), 'vienus metus'),
    (re.compile(r'\binvestoriai\b', re.I), 'investuotojai'),
    (re.compile(r'\binvestorių\b', re.I), 'investuotojų'),
    (re.compile(r'\binvestoriams\b', re.I), 'investuotojams'),
    (re.compile(r'\bdrastiškai\b', re.I), 'smarkiai'),
    (re.compile(r'\bbrokerių įstaigos\b', re.I), 'brokeriai'),
    (re.compile(r'\bgrąžinamosios išmokos\b', re.I), 'grąžinamos sumos'),
    # Common ASCII anglicisms slipping through
    (re.compile(r'\bsoftening\b', re.I), 'silpnėjimas'),
    (re.compile(r'\bweakness\b', re.I), 'silpnumas'),
    (re.compile(r'\btightening\b', re.I), 'griežtinimas'),
    (re.compile(r'\beasing\b', re.I), 'švelninimas'),
]


# Compiled regex to detect ASCII-only words that look Lithuanian but lack diacritics
# Used as a sanity check (not for replacement - just to flag).
SUSPICIOUS_ASCII = re.compile(r'\b[a-zA-Z]+(?:as|is|us|ai|ei|os|ams|ams|ėje|umas|ybė)\b')


def _cleanup_text(text: str) -> str:
    """Apply post-processing cleanups to LLM output."""
    if not text:
        return text
    for pat, replacement in CLEANUPS:
        text = pat.sub(replacement, text)
    text = text.replace('—', '-').replace('–', '-')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

STYLE_GUIDE = """Tu rašai investiciniam kontentui Radoslavo balsu. Privalai laikytis VISŲ taisyklių:

GRAMATIKA - SVARBIAUSIA, BE IŠIMČIŲ:
- Lietuvių kalba PRIVALO būti gramatiškai TAISYKLINGA. Tikrink linksnius, galūnes, žodžių darybą, derinimą.
- VISADA naudok lietuviškas raides: ą, č, ę, ė, į, š, ų, ū, ž. JOKIŲ ASCII pakaitalų lietuviškuose žodžiuose.
- PRIEŠ rašydamas, mintyse PERSKAITYK žodį garsiai - jeigu skamba neaiškiai ar negirdėjai jo prieš tai, NEVARTOK. Naudok paprastesnį sinonimą.
- DRAUDŽIAMA improvizuoti naujadarus ar kalkuoti angliškus žodžius (pvz. "perstumdė palūkanas" - ne, sakyk "atidėjo palūkanų sprendimą"). Jeigu nežinai tikslaus lietuviško atitikmens - perfrazuok visą sakinį.
- DRAUDŽIAMA: "reportine", "zvilgnin", "katalstas", "siginalizuodama", "obalsai", "zalejau", "kompresyvus", "perstumdė", "scenrijus", "nepalaankaus", "investoriai".
- TAISYKLINGI ATITIKMENYS: "pranešė", "žvilgsniu", "katalizatorius", "signalizuoja", "akcentuoja", "neperžengė", "siauras", "atidėjo", "scenarijus", "nepalankaus", "investuotojai".
- LINKSNIŲ ATSARGUMAS: "šiuo lygiu" -> "šiame lygyje". "guidance tikslumas" -> "guidance tikslas". "plėtros tempo" (kilm.) -> "plėtros tempas" (vard.) kai sakinio subjektas. "vienerius metus" -> "vienus metus" arba "per metus".
- SKAIČIAI ir VIENETAI lietuviškai: "0.25 procentinio punkto" (ne "ketvirčio punkto" - tai pažodinis vertimas iš "quarter point").

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


def _llm_call_with_retry(client, prompt: str, model: str, max_tokens: int = 700,
                         max_retries: int = 3):
    """Call Claude with retry on 529 overloaded; fallback Sonnet -> Haiku on persistent overload."""
    import time
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp
        except Exception as e:
            last_err = e
            err_str = str(e)
            if '529' in err_str or 'overloaded' in err_str.lower():
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                if model == SONNET_MODEL:
                    print(f"  Sonnet overloaded, falling back to Haiku")
                    try:
                        return client.messages.create(
                            model=HAIKU_MODEL, max_tokens=max_tokens,
                            messages=[{"role": "user", "content": prompt}],
                        )
                    except Exception as e2:
                        last_err = e2
            else:
                break
    raise last_err


def is_enabled() -> bool:
    """Check if LLM is available (API key + SDK installed)."""
    if os.environ.get('LLM_ENABLED', 'true').lower() in ('false', '0', 'no'):
        return False
    return _get_client() is not None


def analyze_news(title: str, body: str, ticker: str = '',
                 stock_move: str = '', model: str = DEFAULT_MODEL) -> dict:
    """Generate Lithuanian analysis with structured key metrics extracted.

    Returns dict with 'metrics' (list of {label, value, note}) and 'analysis' (prose).
    Returns {'metrics': [], 'analysis': ''} on failure.
    """
    import json as _json
    client = _get_client()
    if not client or not body:
        return {'metrics': [], 'analysis': ''}

    ticker_ctx = f"\nTicker: {ticker}" if ticker else ""
    move_ctx = f"\nStock reaction: {stock_move}" if stock_move else ""

    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Iš naujienos ištrauk svarbiausius SKAIČIUS į struktūrinę formą, tada parašyk gilią analizę.

Grąžink TIK JSON, jokio paaiškinimo aplink:
{{
  "metrics": [
    {{"label": "trumpas Lietuviškas pavadinimas (max 20 simbolių)", "value": "skaičius su vienetu, pvz. -$0.40", "note": "konteksto eilutė, max 30 simbolių, pvz. vs +$0.03 est arba +3.8% YoY"}},
    ... iki 6 svarbiausių metrikų ...
  ],
  "analysis": "3-5 sakinių GILI investicinė analizė lietuvių kalba. NEPAKARTOTI skaičių iš metrics - tik kontekstas, ką tai reiškia, ką daryti. Naudoti tik leidžiamus anglicizmus iš style guide."
}}

JEI naujienoje NĖRA konkrečių skaičių (pvz., makro komentaras, ne earnings) - "metrics" gali būti tuščias [].
{ticker_ctx}{move_ctx}

HEADLINE: {title}

STRAIPSNIO TEKSTAS:
{body[:3000]}"""

    try:
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=700)
        text = resp.content[0].text.strip() if resp.content else ''
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return {'metrics': [], 'analysis': _cleanup_text(text)}
        try:
            data = _json.loads(m.group(0))
        except _json.JSONDecodeError:
            return {'metrics': [], 'analysis': _cleanup_text(text)}
        return {
            'metrics': data.get('metrics', []) or [],
            'analysis': _cleanup_text(data.get('analysis', '')),
        }
    except Exception as e:
        print(f"  warn: LLM analyze_news failed: {e}")
        return {'metrics': [], 'analysis': ''}


def analyze_earnings(ticker: str, company: str, report_data: dict,
                     model: str = DEFAULT_MODEL) -> str:
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
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=250)
        text = resp.content[0].text.strip() if resp.content else ''
        return _cleanup_text(text)
    except Exception as e:
        print(f"  warn: LLM analyze_earnings failed: {e}")
        return ''


def extract_earnings_details(ticker: str, news_body: str,
                              model: str = DEFAULT_MODEL) -> dict:
    """Extract structured earnings data from news article via LLM.

    Returns dict with: revenue_actual, revenue_estimate, guidance_next_q,
    guidance_fy, key_quote, analyst_reaction.
    """
    client = _get_client()
    if not client or not news_body:
        return {}
    import json as _json
    prompt = f"""Iš šio earnings šaltinio (transcript arba news straipsnio) apie {ticker}, ištrauk struktūrinius duomenis. Jeigu tai earnings call transcript, ištrauk kelias verbatim CEO/CFO citatas - rinkis pačias informatyviausias (apie guidance, augimą, strategiją, market sąlygas). Grąžink TIK JSON, jokio paaiškinimo:

{{
  "revenue_actual": "$X.XB arba null",
  "revenue_estimate": "$X.XB arba null",
  "revenue_yoy_change": "+X% arba -X% arba null",
  "guidance_next_q_rev": "$X-XB arba null",
  "guidance_fy_rev": "$X.XB arba null",
  "guidance_ebitda_fy": "$XM arba null",
  "key_quote": "1 pati svarbiausia management citata (verbatim, anglų kalba) arba null",
  "key_quotes": ["iki 3 trumpų verbatim management citatų (anglų kalba, originalas iš transcript)"],
  "stock_reaction": "-X% AHs arba +X% pre-market arba null"
}}

ŠALTINIS:
{news_body[:4500]}"""

    try:
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=700)
        text = resp.content[0].text.strip() if resp.content else ''
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            return {}
        data = _json.loads(m.group(0))
        result = {}
        for k, v in data.items():
            if v in (None, 'null', '', 'N/A', []):
                result[k] = None if k != 'key_quotes' else []
            else:
                result[k] = v
        return result
    except Exception as e:
        print(f"  warn: LLM extract_earnings failed: {e}")
        return {}


def analyze_earnings_card(ticker: str, eps_actual, eps_estimate,
                           extracted: dict, model: str = DEFAULT_MODEL) -> dict:
    """Generate structured Lithuanian earnings analysis with two distinct horizons.

    Returns dict with two fields:
      - short_term: 3-4 sentences on 3-12 month tactical view (valuation,
        catalysts, momentum, what to watch next quarter)
      - long_term: 2-3 sentences on 3-5+ year structural picture (TAM,
        durable moat, secular drivers, structural risk)

    Both labeled "[Trumpalaikis 3-12 mėn]" / "[Ilgalaikis 3-5+ m]" tags are
    added in the template, not the prose itself. EXPERIMENTAL: time-horizon
    labels visible to user, will check after first brief if they stay.
    """
    client = _get_client()
    if not client:
        return {'short_term': '', 'long_term': ''}
    eps_line = ''
    if eps_actual is not None and eps_estimate is not None:
        delta = eps_actual - eps_estimate
        verdict = 'BEAT' if delta > 0 else ('MISS' if delta < 0 else 'INLINE')
        eps_line = f"EPS actual ${eps_actual:.2f} vs estimate ${eps_estimate:.2f} = {verdict}\n"

    extracted_str = '\n'.join(f"{k}: {v}" for k, v in extracted.items() if v)
    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Pateik {ticker} earnings izvalgą su DVIEM ATSKIROMIS sekcijomis. Tikslas - aiškiai atskirti tactical (3-12 mėn) nuo strategic (3-5+ metai) perspektyvos, kad investuotojas su skirtingu horizonu suprastų skirtingus prioritetus.

PRIVALOMAS atsakymo formatas (TIKSLIAI šis pavidalas, BE jokio kito teksto):
SHORT_TERM: <3-4 sakiniai apie 3-12 mėn perspektyvą. Liesti: guidance, šio ketvirčio momentum, valuation, artimi katalizatoriai/rizikos, ką stebėti kitą ketvirtį. NEpakartoti EPS skaičių - jie jau lentelėje.>
LONG_TERM: <2-3 sakiniai apie 3-5+ metų struktūrinį paveikslą. Liesti: TAM ekspansija, durable competitive moat, sekularūs varikliai (pvz. AI capex ciklas, demografijos trendai, reguliacinis pranašumas), struktūrinis risk. NE tactical info - kažkas tinkamo ilgalaikiui pozicijai.>

JOKIO kitų sekcijų, jokių brūkšnių (em-dash), tik trumpi "-". Lietuviška TAISYKLINGA gramatika.

EARNINGS DUOMENYS:
{eps_line}{extracted_str}

Tavo izvalga:"""

    try:
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=800)
        text = resp.content[0].text.strip() if resp.content else ''
        # Parse SHORT_TERM and LONG_TERM blocks
        st_match = re.search(r'SHORT_TERM\s*:\s*(.+?)(?:\n\s*LONG_TERM|$)', text, re.I | re.DOTALL)
        lt_match = re.search(r'LONG_TERM\s*:\s*(.+)', text, re.I | re.DOTALL)
        short_term = _cleanup_text(st_match.group(1).strip()) if st_match else ''
        long_term = _cleanup_text(lt_match.group(1).strip()) if lt_match else ''
        # Backward compat: if parsing fails, return whole text as short_term
        if not short_term and not long_term and text:
            short_term = _cleanup_text(text)
        return {'short_term': short_term, 'long_term': long_term}
    except Exception as e:
        print(f"  warn: LLM analyze_earnings_card failed: {e}")
        return {'short_term': '', 'long_term': ''}


def analyze_macro_event(event: dict, model: str = DEFAULT_MODEL) -> str:
    """Generate 2-3 sentence Lithuanian commentary for a macro event.

    Focus on what the actual vs estimate means for Fed policy, rates, sectors.
    Only called for high-impact US events with actual values.
    """
    client = _get_client()
    if not client:
        return ''
    name = event.get('name', '')
    actual = event.get('actual', '')
    estimate = event.get('estimate', '')
    previous = event.get('previous', '')
    country = event.get('country', '')
    if not actual or not name:
        return ''

    data_line = f"{name} ({country}): aktualus {actual}"
    if estimate:
        data_line += f", lūkestis {estimate}"
    if previous:
        data_line += f", praeitas {previous}"

    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Trumpa makro komentarui 2-3 sakiniai apie šį ekonominį duomenį. KĄ TAI REIŠKIA investuotojui? Fed politikos signalas, palūkanų kreivė, sektorinis poveikis. Konkretu, ne abstraktu.

DUOMUO:
{data_line}

Tavo komentaras:"""

    try:
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=250)
        text = resp.content[0].text.strip() if resp.content else ''
        return _cleanup_text(text)
    except Exception as e:
        print(f"  warn: LLM analyze_macro failed: {e}")
        return ''


def analyze_reddit_thread(title: str, top_comments: list,
                          model: str = DEFAULT_MODEL) -> str:
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
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=250)
        text = resp.content[0].text.strip() if resp.content else ''
        return _cleanup_text(text)
    except Exception as e:
        print(f"  warn: LLM analyze_reddit failed: {e}")
        return ''


def research_past_event_with_web(event: dict, model: str = DEFAULT_MODEL) -> dict:
    """Use Anthropic web_search tool to find actual result + analysis for a
    past-time high-impact macro event with no actual data in our sources.

    Critical: this auto-fills the gap that the user saw on 2026-05-13 with
    Fed Chair vote — event time passed (21:40), result was in news (Warsh
    54-45) but briefing rendered with actual="-". The pipeline must NEVER
    leave a past-time high-impact event without a result.

    Returns {actual, llm_analysis} dict; empty on failure.
    """
    client = _get_client()
    if not client:
        return {}

    name = event.get('name', '')
    country = event.get('country', '')
    time_local = event.get('time_local', '')
    estimate = event.get('estimate', '')
    if not name:
        return {}

    from datetime import datetime as _dt
    today = _dt.now().strftime('%Y-%m-%d')

    prompt = f"""{STYLE_GUIDE}

Šiandien ({today}) įvyko šis makro įvykis:
- Pavadinimas: {name}
- Šalis: {country}
- Planuotas laikas: {time_local}
- Lūkestis: {estimate or 'nepateiktas'}

UŽDUOTIS: Atlik web paiešką, surask FAKTINĮ rezultatą šiam įvykiui (ne lūkestis - kas iš tiesų įvyko). Tada parašyk analizę.

Privalomas atsakymo formatas (BE jokio kito teksto):
ACTUAL: <trumpai, max 25 simboliai - pvz. "PASS 54-45" arba "0.5%" arba "Patvirtinta">
ANALYSIS: <3-5 sakiniai lietuviškai - kas iš tiesų įvyko (konkretūs skaičiai/pavadinimai), kodėl tai svarbu rinkoms, ką tai reiškia Fed politikai/investuotojui. Naudok WebSearch rezultatus.>

JOKIO ICONS, jokių brūkšnių (em-dash), tik trumpi "-"."""

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": prompt}]
        )
        text = ''
        for block in (resp.content or []):
            if hasattr(block, 'text') and block.text:
                text += block.text
        text = text.strip()
        if not text:
            return {}

        actual_match = re.search(r'ACTUAL\s*:\s*(.+?)(?:\n|ANALYSIS|$)', text, re.I | re.DOTALL)
        analysis_match = re.search(r'ANALYSIS\s*:\s*(.+)', text, re.I | re.DOTALL)
        actual = (actual_match.group(1).strip() if actual_match else '')[:60]
        analysis = analysis_match.group(1).strip() if analysis_match else ''
        analysis = _cleanup_text(analysis)
        return {'actual': actual, 'llm_analysis': analysis}
    except Exception as e:
        print(f"  warn: research_past_event_with_web {name}: {e}")
        return {}


def synthesize_youtube_insights(videos: list, watchlist: list,
                                model: str = DEFAULT_MODEL) -> str:
    """Synthesize multiple YouTube video transcripts into one investor narrative.

    OUTPUT STILIUS (kritinis): tai turi atrodyti kaip Radoslav asmeniniai pamąstymai
    po medžiagos peržiūros, NE kaip "kūrėjas X sakė". Jokio video pavadinimo,
    jokio kanalo paminėjimo, jokios "kažkas YouTube'e sakė" formuluotės.

    Returns markdown-ish Lithuanian prose, 4-6 paragraphs, ~600-1000 words.
    """
    client = _get_client()
    if not client or not videos:
        return ''

    # Build a context block: title + description + transcript snippet per video.
    # Cap individual transcripts to keep total prompt manageable.
    pieces = []
    for i, v in enumerate(videos, 1):
        title = v.get('title', '')
        desc = (v.get('description') or '')[:600]
        transcript = (v.get('transcript') or '')
        # Cap transcript length per video so 5+ videos fit in context
        if len(transcript) > 5000:
            transcript = transcript[:2500] + ' [...] ' + transcript[-2500:]
        if not transcript and not desc:
            continue
        block = f"--- ŠALTINIS #{i} ---\nPavadinimas: {title}\n"
        if desc:
            block += f"Aprašymas: {desc}\n"
        if transcript:
            block += f"Transcript:\n{transcript}\n"
        pieces.append(block)

    if not pieces:
        return ''

    context_block = '\n\n'.join(pieces)
    watchlist_str = ', '.join(watchlist[:30])

    prompt = f"""{STYLE_GUIDE}

UŽDUOTIS: Tu peržiūrėjai kelis investicinius video šaltinius per pastarąsias 48h. Dabar rašyk kaip ASMENINIUS PAMĄSTYMUS - tarsi tai būtų tavo paties įžvalgos po medžiagos peržiūros. Tikslas: 4-6 pastraipos, ~600-900 žodžių, vientisas naratyvas.

PRIVALOMOS TAISYKLĖS:
1. NEMINĖTI video pavadinimų, kūrėjų vardų, kanalų - rašyti pirmu asmeniu ("matau", "manau", "stebėdamas rinkas").
2. NEDUOTI nuorodų į šaltinius.
3. Sutelkti dėmesį į PRIORITETUS:
   - Watchlist kompanijos: {watchlist_str}
   - Makro: Fed, palūkanos, CPI/PPI/PCE, infliacija, recession signalai
   - Geopolitika ir US politika veikianti rinkas (tarifai, Kinija, Iranas, karai)
   - Sektoriniai trendai (semis, AI, crypto, energy)
4. Synthesizuoti per visus šaltinius - jei keli kūrėjai liečia tą pačią temą, surask konsensusą ir prieštaras.
5. Pateik VALUE - kiekvienas paragrafas turi turėti "ką tai reiškia investuotojui" elementą.
6. Pradėk paragrafais kaip natūralus pasakojimas, ne sausi bullet'ai. Bet leiskite konkretiems skaičiams ir tezėms (ne tik abstrakcijos).
7. Lietuvių kalba pagal style guide. Galima vartoti finansų anglicizmus (capex, guidance, beat/miss, dovish/hawkish, etc.).
8. Jeigu kuriame šaltinyje yra prieštaringa nuomonė kitiems - akcentuok įdomias įžvalgas ir kontrargumentus, ne konsensus thinking.

VENGTI:
- "Matau YouTube'e..." / "Vienas analitikas sakė..." / "Kažkas teigia..." - VISKAS turi būti tavo pamąstymai
- Generic frazių ("rinka neaišku", "viskas priklauso")
- Brūkšnių (em-dash) - tik trumpi "-"

ŠALTINIAI:
{context_block}

Tavo pamąstymai (4-6 paragrafai, vientisas tekstas):"""

    try:
        resp = _llm_call_with_retry(client, prompt, model, max_tokens=2000)
        text = resp.content[0].text.strip() if resp.content else ''
        return _cleanup_text(text)
    except Exception as e:
        print(f"  warn: LLM youtube synthesis failed: {e}")
        return ''


def batch_analyze_news(news_items: list, max_workers: int = 4) -> list:
    """Apply LLM analysis (with metrics extraction) to news items. Returns only items with successful analysis."""
    if not is_enabled() or not news_items:
        return news_items

    import concurrent.futures

    def one(n):
        body = n.get('summary') or ''
        title = n.get('title', '')
        ticker = n.get('ticker', '')
        # If article body fetch failed (Google News redirects, paywalls), fall
        # back to title-only analysis — better than dropping the story entirely.
        if not body or len(body) < 50:
            if title and len(title) >= 25:
                body = f"(Pilno straipsnio teksto neprieinama.) Antraštė: {title}"
            else:
                return {'metrics': [], 'analysis': ''}
        return analyze_news(title, body, ticker=ticker)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(one, n): n for n in news_items}
        for fut in concurrent.futures.as_completed(futures):
            n = futures[fut]
            try:
                result = fut.result()
                if result and result.get('analysis'):
                    n['llm_analysis'] = result['analysis']
                    n['llm_metrics'] = result.get('metrics', [])
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
