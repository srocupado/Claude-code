import io
import re
import logging
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

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

# Check extra editions first (most common), then regular Section 1.
# False positives are avoided by the XML parser, which matches only article
# titles starting with "MEDIDA PROVISÓRIA Nº", not body-text references.
DOU_SECTIONS = ["DO1E", "DO1"]

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


def _extract_numero(text: str, href: str = "") -> str:
    m = re.search(r"N[ºo°]?\s*([\d\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(".", "")
    if href:
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
        # Ementa appears on the first substantive line AFTER the MP title heading
        ementa = ""
        found_title = False
        for ln in lines[:40]:
            if re.match(r"MEDIDA PROVIS[ÓO]RIA\s+N", ln, re.I):
                found_title = True
                continue
            if found_title and len(ln) > 20:
                if not re.match(r"(A PRESIDENTA|O PRESIDENTE|O VICE)", ln, re.I):
                    ementa = ln
                    break
        if not ementa:
            ementa = lines[0] if lines else ""
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
            "edicao_extra": bool(re.search(r"Edi[çc][aã]o Extra", texto, re.IGNORECASE)),
        })

    return results


# ── Source 2: Inlabs (DOU XML via Imprensa Nacional) ─────────────────────────
# Authentication: POST /logar.php with form fields email + password
# Returns session cookie: inlabs_session_cookie
# Download: GET /index.php?p=DATE&dl=DATE-SECTION.zip  → ZIP with XML files
# Reference: https://github.com/Imprensa-Nacional/inlabs

def _inlabs_login() -> tuple[requests.Session, str] | None:
    """Authenticates with Inlabs and returns (session, cookie_value)."""
    email = getattr(config, "INLABS_EMAIL", "")
    password = getattr(config, "INLABS_PASSWORD", "")
    if not email or not password:
        logger.warning("Inlabs: INLABS_EMAIL / INLABS_PASSWORD não configurados.")
        logger.warning("Cadastro gratuito em: https://inlabs.in.gov.br/acessar.php")
        return None

    session = _make_session(referer=INLABS_BASE)
    try:
        resp = session.post(
            f"{INLABS_BASE}/logar.php",
            data={"email": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
            allow_redirects=True,
        )
        resp.raise_for_status()
        cookie = session.cookies.get("inlabs_session_cookie")
        if not cookie:
            logger.error("Inlabs: autenticação falhou — cookie não retornado. Verifique e-mail/senha.")
            return None
        logger.info("Inlabs: autenticação OK.")
        return session, cookie
    except Exception as exc:
        logger.error("Inlabs: falha ao autenticar em /logar.php: %s", exc)
        return None


def _parse_dou_xml(xml_content: str, target_date: date) -> list[dict]:
    """Parses DOU XML content and extracts MP articles.

    Only matches articles whose TITLE starts with 'MEDIDA PROVISÓRIA Nº' —
    this avoids false positives from portarias/decretos that reference old MPs
    in their body text.

    Note: the date inside the title is the signing date, which may differ from
    the publication date (e.g. an MP signed on May 16 published in a DO1E on
    May 19). We do NOT filter by signing date — the ZIP itself was downloaded
    for the specific publication date, so all articles in it are from that day.
    """
    year = target_date.year
    period = _planalto_period(year)
    results = []
    seen: set[str] = set()

    # Matches titles that START with the MP declaration
    TITLE_RE = re.compile(
        r"^\s*MEDIDA PROVIS[ÓO]RIA\s+N[ºo°\.°]?\s*([\d\.]+)",
        re.IGNORECASE,
    )

    def _try_article(title_text: str, body_text: str) -> None:
        title_upper = title_text.strip().upper()
        m = TITLE_RE.match(title_upper)
        if not m:
            return
        numero = m.group(1).replace(".", "")
        if numero in seen:
            return
        seen.add(numero)
        logger.info("  [XML] MP nº %s encontrada no título: %.120s", numero, title_text.strip())
        results.append(_build_mp_dict(numero, year, period, body_text or title_text, target_date))

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        # Fallback: parse with BeautifulSoup (handles malformed XML)
        soup = BeautifulSoup(xml_content, "lxml-xml")
        for tag in soup.find_all(True):
            if tag.name and re.search(r"titulo|title|Titulo", tag.name, re.I):
                _try_article(tag.get_text(" ", strip=True),
                             tag.parent.get_text(" ", strip=True) if tag.parent else "")
        return results

    # Build parent map: stdlib ET has no getparent(), so we build it manually.
    # This lets us climb from a title element to the containing article body.
    parent_map: dict = {child: parent for parent in root.iter() for child in parent}

    # Walk all elements; treat text content as potential MP title
    for elem in root.iter():
        text = (elem.text or "").strip()
        if not text or len(text) > 2000:
            continue  # Skip empty or excessively long body blocks
        # Use the parent element so body_text includes the full article content
        parent = parent_map.get(elem, elem)
        body_text = ET.tostring(parent, encoding="unicode", method="text")
        _try_article(text, body_text)

    # Also check 'title' XML attributes (elem is already the article container)
    for elem in root.iter():
        attr_title = elem.get("title", "").strip()
        if attr_title:
            _try_article(attr_title, ET.tostring(elem, encoding="unicode", method="text"))

    # Fallback: scan each raw XML line (tags stripped) for MP title patterns.
    # Catches cases where the DOU XML nests text in child nodes rather than
    # elem.text, or uses an unexpected element name that the loops above miss.
    if not results:
        logger.info("  [XML] Nenhuma MP via ElementTree — tentando scan por linha.")
        for raw_line in xml_content.splitlines():
            line = re.sub(r"<[^>]+>", " ", raw_line).strip()
            if 20 <= len(line) <= 400:
                _try_article(line, xml_content)
        if not results:
            snippet = xml_content[:800].replace("\n", " ")
            logger.warning("  [XML] Nenhuma MP encontrada. Início do XML: %.800s", snippet)

    return results


def _build_mp_dict(numero: str, year: int, period: str, text_excerpt: str, target_date: date) -> dict:
    ano2d = str(year)[-2:]
    planalto_url = (
        f"{PLANALTO_BASE}/ccivil_03/_Ato{period}/{year}/Mpv/"
        f"mpv{numero}-{ano2d}.htm"
    )
    # Prefer ementa extracted directly from the Planalto HTML page (clean text)
    ementa_from_page, texto_planalto = _fetch_mp_page(planalto_url)
    if ementa_from_page:
        ementa = ementa_from_page
    else:
        # Fallback: extract from DOU XML text by regex
        # Pattern: capture text between the title date (ends with a year) and the
        # presidential preamble ("O PRESIDENTE"/"A PRESIDENTA").
        stripped = re.sub(r"<[^>]+>", " ", text_excerpt)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        m = re.search(
            r"DE\s+\d{4}\s+(.+?)(?=\s+O\s+PRESIDENTE|\s+A\s+PRESIDENTA|\s+O\s+VICE)",
            stripped,
            re.IGNORECASE | re.DOTALL,
        )
        ementa = re.sub(r"\s+", " ", m.group(1)).strip()[:600] if m else stripped[:600]
    texto_for_detection = texto_planalto or text_excerpt
    return {
        "numero": numero,
        "ano": year,
        "ementa": ementa,
        "data_publicacao": target_date.isoformat(),
        "url_planalto": planalto_url,
        "texto_integral": texto_planalto or text_excerpt[:6000],
        "edicao_extra": bool(re.search(r"Edi[çc][aã]o Extra", texto_for_detection, re.IGNORECASE)),
    }


def _fetch_inlabs(target_date: date) -> list[dict]:
    """Downloads DOU XML from Inlabs and extracts MPs for target_date."""
    auth = _inlabs_login()
    if not auth:
        return []
    session, cookie = auth

    date_str = target_date.strftime("%Y-%m-%d")
    results = []
    seen_numeros: set[str] = set()

    for section in DOU_SECTIONS:
        dl_param = f"{date_str}-{section}.zip"
        url = f"{INLABS_BASE}/index.php?p={date_str}&dl={dl_param}"
        logger.info("  [Inlabs] Baixando %s...", dl_param)

        try:
            resp = session.get(
                url,
                headers={"Cookie": f"inlabs_session_cookie={cookie}"},
                timeout=60,
                stream=True,
            )
            if resp.status_code == 404:
                logger.info("  [Inlabs] %s não publicado em %s (sem edição extra).", section, date_str)
                continue
            resp.raise_for_status()

            content = resp.content
            if len(content) < 100:
                logger.info("  [Inlabs] %s: arquivo vazio (sem publicação).", section)
                continue

            # Inlabs returns HTML (not 404) when a section wasn't published
            if content[:2] != b"PK":
                logger.info(
                    "  [Inlabs] %s: resposta não é ZIP (provavelmente seção não publicada). "
                    "Início: %.120s", section, content[:120]
                )
                continue

            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".xml"):
                        continue
                    xml_data = zf.read(name).decode("utf-8", errors="replace")
                    if "MEDIDA PROVIS" not in xml_data.upper():
                        continue
                    logger.info("  [Inlabs] MP(s) encontrada(s) em %s/%s", section, name)
                    for mp in _parse_dou_xml(xml_data, target_date):
                        if mp["numero"] not in seen_numeros:
                            seen_numeros.add(mp["numero"])
                            results.append(mp)
                            logger.info("    → MP nº %s/%s", mp["numero"], mp["ano"])

        except zipfile.BadZipFile:
            logger.warning("  [Inlabs] %s: arquivo ZIP inválido.", section)
        except Exception as exc:
            logger.warning("  [Inlabs] Erro ao processar %s: %s", section, exc)

    if not results:
        logger.info("Inlabs: nenhuma MP encontrada em %s.", date_str)
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_mps(target_date: date) -> list[dict]:
    """Fetch MPs published on target_date. Planalto first, Inlabs/DOU as fallback."""
    result = _fetch_planalto(target_date)
    if result is None or not result:
        if result is None:
            logger.info("Planalto indisponível — usando Inlabs/DOU.")
        else:
            logger.info("Planalto sem MPs para %s — confirmando via Inlabs/DOU.", target_date)
        return _fetch_inlabs(target_date)
    return result
