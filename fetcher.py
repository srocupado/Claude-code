import re
import logging
from datetime import date

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

MONTHS_PT = {
    1: "JANEIRO", 2: "FEVEREIRO", 3: "MARÇO", 4: "ABRIL",
    5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
    9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
}

PLANALTO_BASE = "https://www.planalto.gov.br"
INLABS_BASE = "https://inlabs.in.gov.br"

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


def _make_session(referer: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if referer:
        s.headers["Referer"] = referer
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


# ── Source 1: Planalto ────────────────────────────────────────────────────────

def _fetch_planalto(target_date: date) -> list[dict] | None:
    """Returns list of MPs, empty list if none today, or None if unreachable."""
    year = target_date.year
    period = _planalto_period(year)
    index_url = f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{year}/Mpv/"
    date_str = _format_date_pt(target_date)

    logger.info("Consultando Planalto: %s", index_url)
    session = _make_session()
    resp = None
    for url_attempt in [index_url, index_url.lower()]:
        try:
            session.get(PLANALTO_BASE, timeout=15)
            r = session.get(url_attempt, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                resp = r
                break
        except requests.RequestException:
            pass

    if resp is None:
        logger.warning("Planalto indisponível – tentando Inlabs/DOU.")
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
        logger.info("  [Planalto] MP nº %s: %s", numero, mp_url)
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


# ── Source 2: Inlabs API (DOU oficial) ───────────────────────────────────────

def _inlabs_login() -> str | None:
    """Authenticates with Inlabs and returns the JWT token."""
    email = getattr(config, "INLABS_EMAIL", "")
    password = getattr(config, "INLABS_PASSWORD", "")
    if not email or not password:
        return None

    # Endpoint correto da API Inlabs (diferente da página de cadastro /acesso)
    auth_url = f"{INLABS_BASE}/opendata/api/1/autenticar"
    try:
        resp = requests.get(
            auth_url,
            params={"email": email, "senha": password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token") or data.get("access_token") or data.get("jwt")
        if not token:
            # Some versions return the token in the Authorization response header
            token = resp.headers.get("Authorization", "").replace("Bearer ", "") or None
        if token:
            logger.info("Inlabs: autenticação OK.")
        else:
            logger.warning("Inlabs: autenticação OK mas token não encontrado na resposta: %s", list(data.keys()))
        return token
    except Exception as exc:
        logger.warning("Inlabs: falha na autenticação (%s): %s", auth_url, exc)
        return None


def _fetch_inlabs(target_date: date) -> list[dict]:
    """Queries the Inlabs API (official DOU API) for MPs on target_date."""
    token = _inlabs_login()
    if not token:
        email = getattr(config, "INLABS_EMAIL", "")
        if not email:
            logger.warning("Inlabs: INLABS_EMAIL e INLABS_PASSWORD não configurados.")
            logger.warning("Cadastro gratuito em: https://inlabs.in.gov.br/acesso")
        else:
            logger.error("Inlabs: autenticação falhou. Verifique INLABS_EMAIL e INLABS_PASSWORD.")
        return []

    year = target_date.year
    period = _planalto_period(year)
    date_str = target_date.strftime("%Y-%m-%d")

    url = (
        f"{INLABS_BASE}/opendata/api/1/busca"
        f"?q=%22Medida+Provis%C3%B3ria%22"
        f"&s=do1%2Cdoe"        # Seção 1 + Edições Extras
        f"&dtInicio={date_str}"
        f"&dtFim={date_str}"
    )
    logger.info("Consultando Inlabs/DOU: %s", url)

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("Inlabs API falhou: %s", exc)
        return []

    items = data if isinstance(data, list) else data.get("items", data.get("results", []))
    results = []
    seen = set()

    for item in items:
        title = item.get("title", "") or item.get("titulo", "")
        title_upper = title.upper()
        if "MEDIDA PROVIS" not in title_upper:
            continue

        m = re.search(r"N[ºo°]?\s*([\d\.]+)", title_upper)
        if not m:
            continue
        numero = m.group(1).replace(".", "")
        if numero in seen:
            continue
        seen.add(numero)

        ementa = item.get("ementa") or item.get("abstract") or title
        dou_url = item.get("urlTitle") or item.get("url") or ""
        ano2d = str(year)[-2:]
        planalto_url = (
            f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{year}/Mpv/"
            f"mpv{numero}-{ano2d}.htm"
        )

        _, texto = _fetch_mp_page(planalto_url)
        if not texto and dou_url:
            _, texto = _fetch_mp_page(dou_url)

        logger.info("  [Inlabs] MP nº %s encontrada.", numero)
        results.append({
            "numero": numero,
            "ano": year,
            "ementa": ementa,
            "data_publicacao": target_date.isoformat(),
            "url_planalto": planalto_url,
            "texto_integral": texto or ementa,
        })

    if not results:
        logger.info("Inlabs: nenhuma MP encontrada em %s.", date_str)
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_mps(target_date: date) -> list[dict]:
    """Fetch MPs published on target_date. Planalto first, Inlabs/DOU as fallback."""
    result = _fetch_planalto(target_date)
    if result is None:
        logger.info("Usando Inlabs/DOU como fonte alternativa.")
        return _fetch_inlabs(target_date)
    return result
