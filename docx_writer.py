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

# Colors matching a formal government document palette
COLOR_DARK = RGBColor(0x1F, 0x39, 0x64)   # dark navy
COLOR_BODY = RGBColor(0x00, 0x00, 0x00)   # black


def _set_margins(doc: Document, top=2.5, bottom=2.5, left=3.0, right=2.5):
    for section in doc.sections:
        section.top_margin = Cm(top)
        section.bottom_margin = Cm(bottom)
        section.left_margin = Cm(left)
        section.right_margin = Cm(right)


def _set_default_font(doc: Document, name="Arial", size=11):
    style = doc.styles["Normal"]
    font = style.font
    font.name = name
    font.size = Pt(size)
    font.color.rgb = COLOR_BODY


def _add_title(doc: Document, text: str):
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(4)
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(14)
    run.font.color.rgb = COLOR_DARK
    run.font.name = "Arial"


def _add_subtitle(doc: Document, text: str):
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(12)
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = COLOR_DARK
    run.font.name = "Arial"


def _add_divider(doc: Document):
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(6)
    pPr = para._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "1F3964")
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_metadata_line(doc: Document, label: str, value: str):
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(2)
    para.paragraph_format.space_before = Pt(2)
    label_run = para.add_run(label + " ")
    label_run.bold = True
    label_run.font.size = Pt(11)
    label_run.font.name = "Arial"
    val_run = para.add_run(value)
    val_run.font.size = Pt(11)
    val_run.font.name = "Arial"


def _add_section_heading(doc: Document, text: str):
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(14)
    para.paragraph_format.space_after = Pt(4)
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = COLOR_DARK
    run.font.name = "Arial"


def _add_labeled_block(doc: Document, label: str, body: str):
    """Adds a bold label paragraph followed by body text paragraphs."""
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(14)
    para.paragraph_format.space_after = Pt(4)
    run = para.add_run(label)
    run.bold = True
    run.font.size = Pt(12)
    run.font.color.rgb = COLOR_DARK
    run.font.name = "Arial"
    _add_body_text(doc, body)


def _add_body_text(doc: Document, text: str):
    """Splits text on double newlines to add multiple paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []
    for i, para_text in enumerate(paragraphs):
        # Single newlines inside a block become line breaks within the same paragraph
        lines = para_text.splitlines()
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(6)
        para.paragraph_format.first_line_indent = Cm(0)
        para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for j, line in enumerate(lines):
            run = para.add_run(line)
            run.font.size = Pt(11)
            run.font.name = "Arial"
            if j < len(lines) - 1:
                run.add_break()


def write_nota_tecnica(mp: dict, content: dict, output_dir: str = OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)

    doc = Document()
    _set_margins(doc)
    _set_default_font(doc)

    # ── Title & subtitle ──────────────────────────────────────────────────────
    title = content.get(
        "titulo",
        f"NOTA TÉCNICA MP nº {mp['numero']}/{mp['ano']}",
    )
    subtitle = content.get("subtitulo", "Análise de Impacto da Medida Provisória")
    _add_title(doc, title)
    _add_subtitle(doc, subtitle)
    _add_divider(doc)

    # ── Metadata ──────────────────────────────────────────────────────────────
    pub_date = date.fromisoformat(mp["data_publicacao"]) if mp.get("data_publicacao") else date.today()
    prazo_60  = pub_date + timedelta(days=60)
    prazo_120 = pub_date + timedelta(days=120)

    doc.add_paragraph().paragraph_format.space_after = Pt(2)
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
    _add_divider(doc)

    # ── Ementa / Explicação da matéria ────────────────────────────────────────
    _add_labeled_block(
        doc,
        "Ementa / Explicação da matéria:",
        content.get("ementa_expandida", mp.get("ementa", "")),
    )

    # ── Numbered sections ─────────────────────────────────────────────────────
    for i in range(1, 7):
        title_key = f"secao_{i}_titulo"
        body_key = f"secao_{i}_conteudo"
        if title_key in content:
            _add_section_heading(doc, content[title_key])
            if body_key in content:
                _add_body_text(doc, content[body_key])

    # ── Arguments and recommendation ─────────────────────────────────────────
    for label, key in [
        ("Argumento favorável:", "argumento_favoravel"),
        ("Argumento contrário:", "argumento_contrario"),
        ("Recomendação estratégica:", "recomendacao"),
    ]:
        if content.get(key):
            _add_labeled_block(doc, label, content[key])

    # ── Fixed closing block (not generated by AI) ─────────────────────────────
    _add_divider(doc)
    vigencia_para = doc.add_paragraph()
    vigencia_para.paragraph_format.space_before = Pt(8)
    vigencia_para.paragraph_format.space_after = Pt(4)
    v_run = vigencia_para.add_run("Vigência: ")
    v_run.bold = True
    v_run.font.size = Pt(11)
    v_run.font.name = "Arial"
    v_val = vigencia_para.add_run("A Medida Provisória entra em vigor na data de sua publicação.")
    v_val.font.size = Pt(11)
    v_val.font.name = "Arial"

    sig_para = doc.add_paragraph()
    sig_para.paragraph_format.space_before = Pt(12)
    sig_para.paragraph_format.space_after = Pt(4)
    sig_run = sig_para.add_run("Assessoria da Liderança do Podemos")
    sig_run.bold = True
    sig_run.font.size = Pt(11)
    sig_run.font.color.rgb = COLOR_DARK
    sig_run.font.name = "Arial"

    # ── Save ──────────────────────────────────────────────────────────────────
    # ASCII-only filename: special chars (É, º) break GitHub Actions artifact ZIP download
    filename = f"NOTA_TECNICA_-_MPV_n{mp['numero']}_de_{mp['ano']}.docx"
    filepath = os.path.join(output_dir, filename)
    doc.save(filepath)
    logger.info("Nota técnica salva: %s", filepath)
    return filepath
