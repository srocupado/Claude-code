import os
import logging
from datetime import date, timedelta

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

logger = logging.getLogger(__name__)

OUTPUT_DIR = "output"

# Template uses #333333 for every element — no navy, no pure black
COLOR_TEXT = RGBColor(0x33, 0x33, 0x33)


def _set_margins(doc: Document, top=2.0, bottom=2.0, left=3.0, right=1.5):
    for section in doc.sections:
        section.top_margin    = Cm(top)
        section.bottom_margin = Cm(bottom)
        section.left_margin   = Cm(left)
        section.right_margin  = Cm(right)


def _set_default_font(doc: Document):
    """Template base style: Times New Roman 10 pt, no explicit color."""
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(10)


# ── Low-level helpers ────────────────────────────────────────────────────────

def _new_para(doc: Document, align=WD_ALIGN_PARAGRAPH.JUSTIFY) -> object:
    """Create a paragraph with zero space_before / space_after."""
    para = doc.add_paragraph()
    para.alignment = align
    para.paragraph_format.space_before = Pt(0)
    para.paragraph_format.space_after  = Pt(0)
    return para


def _styled_run(para, text: str, *, bold=False, size=12, font_name: str | None = None):
    """Add a run with explicit color and optional bold/font/size."""
    r = para.add_run(text)
    r.bold            = bold
    r.font.size       = Pt(size)
    r.font.color.rgb  = COLOR_TEXT
    if font_name:
        r.font.name = font_name
    return r


def _blank(doc: Document):
    """Empty paragraph — used as vertical spacer (zero space_before/after)."""
    _new_para(doc)


def _add_divider(doc: Document):
    """Paragraph with bottom border in template color."""
    para = _new_para(doc)
    pPr  = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"),   "single")
    bottom.set(qn("w:sz"),    "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "333333")
    pBdr.append(bottom)
    pPr.append(pBdr)


# ── Document-level builders ──────────────────────────────────────────────────

def _add_title(doc: Document, text: str):
    para = _new_para(doc, WD_ALIGN_PARAGRAPH.CENTER)
    _styled_run(para, text, bold=True, size=14, font_name="Source Sans Pro")


def _add_subtitle(doc: Document, text: str):
    para = _new_para(doc, WD_ALIGN_PARAGRAPH.CENTER)
    _styled_run(para, text, bold=True, size=14, font_name="Source Sans Pro")


def _add_metadata_line(doc: Document, label: str, value: str):
    para = _new_para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY)
    _styled_run(para, label + " ", bold=True,  size=12)
    _styled_run(para, value,        bold=False, size=12)


def _add_section_heading(doc: Document, text: str):
    """Blank line → bold heading → blank line."""
    _blank(doc)
    para = _new_para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY)
    _styled_run(para, text, bold=True, size=12)
    _blank(doc)


def _add_labeled_block(doc: Document, label: str, body: str):
    """Blank → bold label → blank → body paragraphs."""
    _blank(doc)
    para = _new_para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY)
    _styled_run(para, label, bold=True, size=12)
    _blank(doc)
    _add_body_text(doc, body)


def _add_body_text(doc: Document, text: str):
    """Split on double newlines → one paragraph each; single newline → line break."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    for para_text in paragraphs:
        lines = para_text.splitlines()
        para = _new_para(doc, WD_ALIGN_PARAGRAPH.JUSTIFY)
        for j, line in enumerate(lines):
            r = para.add_run(line)
            r.font.size      = Pt(12)
            r.font.color.rgb = COLOR_TEXT
            if j < len(lines) - 1:
                r.add_break()


# ── Public API ───────────────────────────────────────────────────────────────

def write_nota_tecnica(mp: dict, content: dict, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)

    doc = Document()
    _set_margins(doc)
    _set_default_font(doc)

    # ── Title & subtitle ──────────────────────────────────────────────────────
    title    = content.get("titulo",    f"NOTA TÉCNICA MP nº {mp['numero']}/{mp['ano']}")
    subtitle = content.get("subtitulo", "Análise de Impacto da Medida Provisória")
    _add_title(doc, title)
    _add_subtitle(doc, subtitle)
    _add_divider(doc)

    # ── Metadata ──────────────────────────────────────────────────────────────
    pub_date  = date.fromisoformat(mp["data_publicacao"]) if mp.get("data_publicacao") else date.today()
    prazo_60  = pub_date + timedelta(days=60)
    prazo_120 = pub_date + timedelta(days=120)

    _add_metadata_line(doc, "Expedidor:", "Poder Executivo – Presidência da República")
    _add_metadata_line(doc, "Publicação no DOU (Edição Extra):", pub_date.strftime("%d/%m/%Y"))
    _add_metadata_line(doc, "Vigência imediata (art. 62, §3º, CF):", pub_date.strftime("%d/%m/%Y"))
    _add_metadata_line(doc, "Prazo de vigência – 1ª prorrogação (60 dias):", prazo_60.strftime("%d/%m/%Y"))
    _add_metadata_line(doc, "Prazo máximo de vigência – 2ª prorrogação (120 dias):", prazo_120.strftime("%d/%m/%Y"))
    _add_metadata_line(doc, "Tramitação:", "Comissão Mista → Câmara dos Deputados → Senado Federal")
    _add_metadata_line(doc, "Relator na comissão mista:", "a designar")
    _add_metadata_line(doc, "Data de atualização:", date.today().strftime("%d/%m/%Y"))
    if mp.get("url_planalto"):
        _add_metadata_line(doc, "Texto no Planalto:", mp["url_planalto"])

    # ── Ementa / Explicação da matéria ────────────────────────────────────────
    _add_labeled_block(
        doc,
        "Ementa / Explicação da matéria:",
        content.get("ementa_expandida", mp.get("ementa", "")),
    )

    # ── Numbered sections ─────────────────────────────────────────────────────
    for i in range(1, 7):
        title_key = f"secao_{i}_titulo"
        body_key  = f"secao_{i}_conteudo"
        if title_key in content:
            _add_section_heading(doc, content[title_key])
            if body_key in content:
                _add_body_text(doc, content[body_key])

    # ── Arguments and recommendation ─────────────────────────────────────────
    for label, key in [
        ("Argumento favorável:",    "argumento_favoravel"),
        ("Argumento contrário:",    "argumento_contrario"),
        ("Recomendação estratégica:", "recomendacao"),
    ]:
        if content.get(key):
            _add_labeled_block(doc, label, content[key])

    # ── Fixed closing block (hardcoded — not generated by AI) ─────────────────
    _blank(doc)
    _add_divider(doc)
    _blank(doc)
    _add_metadata_line(
        doc,
        "Vigência:",
        "A Medida Provisória entra em vigor na data de sua publicação.",
    )
    _blank(doc)
    sig = _new_para(doc, WD_ALIGN_PARAGRAPH.LEFT)
    _styled_run(sig, "Assessoria da Liderança do Podemos", bold=True, size=12)

    # ── Save ──────────────────────────────────────────────────────────────────
    # ASCII-only filename: special chars (É, º) break GitHub Actions artifact ZIP
    filename = f"NOTA_TECNICA_-_MPV_n{mp['numero']}_de_{mp['ano']}.docx"
    filepath = os.path.join(output_dir, filename)
    doc.save(filepath)
    logger.info("Nota técnica salva: %s", filepath)
    return filepath
