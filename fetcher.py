import re
import logging
from datetime import date

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MONTHS_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
    5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
    9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
}

PLANALTO_BASE = "https://www.planalto.gov.br"
CAMARA_API = "https://dadosabertos.camara.leg.br/api/v2"

# Full browser-like headers to avoid 403 on Planalto
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "DNT": "1",
}


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _planalto_period(year: int) -> str:
    start = ((year - 1991) // 4) * 4 + 1991
    return f"{start}-{start + 3}"


def _format_date_pt(d: date) -> str:
    day_str = f"{d.day}º" if d.day == 1 else str(d.day)
    return f"{day_str} DE {MONTHS_PT[d.month]} DE {d.year}"


def _extract_numero(text: str, href: str) -> str:
    m = re.search(r"N[ºo°]?\s*([\d\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(".", "")
    m = re.search(r"mpv(\d+)-", href.lower())
    if m:
        return m.group(1)
    return "???"


def _fetch_mp_page(url: str, session: requests.Session | None = None) -> tuple[str, str]:
    sess = session or _make_session()
    try:
        resp = sess.get(url, timeout=20)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # Ementa is usually within the first meaningful lines after the title
        ementa_lines = []
        for ln in lines[:20]:
            if ln.upper().startswith("MEDIDA PROVISÓRIA") or ln.upper().startswith("A PRESIDENTA") or ln.upper().startswith("O PRESIDENTE"):
                break
            if len(ln) > 30:
                ementa_lines.append(ln)
        ementa = " ".join(ementa_lines[:3]) if ementa_lines else lines[0] if lines else ""
        return ementa, "\n".join(lines[:500])
    except Exception as exc:
        logger.warning("Erro ao buscar página da MP (%s): %s", url, exc)
        return "", ""


def _fetch_planalto(target_date: date) -> list[dict] | None:
    """Scrapes the Planalto MP index for a given date.

    Returns a list of MP dicts, an empty list if no MPs were found today,
    or None if Planalto is unreachable (triggers fallback).
    """
    year = target_date.year
    period = _planalto_period(year)
    index_url = f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{year}/Mpv/"
    date_str = _format_date_pt(target_date)

    # Try both the canonical (mixed-case) and lowercase URL, as Planalto sometimes redirects
    index_url_lower = index_url.lower()
    logger.info("Consultando Planalto: %s", index_url)
    session = _make_session()
    resp = None
    for url_attempt in [index_url, index_url_lower]:
        try:
            session.get(PLANALTO_BASE, timeout=15)
            resp = session.get(url_attempt, timeout=20, allow_redirects=True)
            if resp.status_code == 200:
                break
            resp = None
        except requests.RequestException:
            resp = None
    if resp is None:
        logger.warning("Planalto indisponível – ativando fallback.")
        return None
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for link in soup.find_all("a", href=True):
        text = link.get_text(" ", strip=True)
        text_upper = text.upper()
        if "MEDIDA PROVIS" not in text_upper:
            continue
        if date_str not in text_upper:
            continue

        href = link["href"]
        if href.startswith("http"):
            mp_url = href
        else:
            href_clean = href.lstrip("./")
            mp_url = f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{year}/Mpv/{href_clean}"

        numero = _extract_numero(text_upper, href)
        logger.info("  → MP nº %s encontrada: %s", numero, mp_url)
        ementa, texto = _fetch_mp_page(mp_url, session)

        results.append({
            "numero": numero,
            "ano": year,
            "ementa": ementa or text,
            "data_publicacao": target_date.isoformat(),
            "url_planalto": mp_url,
            "texto_integral": texto,
        })

    return results


def _fetch_camara_fallback(target_date: date) -> list[dict]:
    date_str = target_date.isoformat()
    url = (
        f"{CAMARA_API}/proposicoes"
        f"?siglaTipo=MPV"
        f"&dataApresentacaoInicio={date_str}"
        f"&dataApresentacaoFim={date_str}"
        f"&ordem=ASC&ordenarPor=id"
    )
    logger.info("Fallback – consultando API da Câmara: %s", url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        body = resp.text.strip()
        if not body:
            logger.info("API da Câmara: resposta vazia (sem MPs para %s).", date_str)
            return []
        items = resp.json().get("dados", [])
    except requests.RequestException as exc:
        logger.error("API da Câmara indisponível: %s", exc)
        return []
    except ValueError:
        logger.warning("API da Câmara retornou resposta não-JSON (sem MPs para %s).", date_str)
        return []

    results = []
    for item in items:
        numero = str(item.get("numero", "???"))
        ano = int(item.get("ano", target_date.year))
        period = _planalto_period(ano)
        ano2d = str(ano)[-2:]
        planalto_url = (
            f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{ano}/Mpv/"
            f"mpv{numero}-{ano2d}.htm"
        )
        # Try to get the full text from Planalto even in fallback mode
        ementa_detail = item.get("ementa", "")
        _, texto = _fetch_mp_page(planalto_url)

        results.append({
            "numero": numero,
            "ano": ano,
            "ementa": ementa_detail,
            "data_publicacao": date_str,
            "url_planalto": planalto_url,
            "texto_integral": texto or ementa_detail,
        })
    return results


def fetch_mps(target_date: date) -> list[dict]:
    result = _fetch_planalto(target_date)
    if result is None:
        return _fetch_camara_fallback(target_date)
    return result
