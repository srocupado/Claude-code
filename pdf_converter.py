import os
import subprocess
import logging

logger = logging.getLogger(__name__)


def convert_to_pdf(docx_path: str) -> str:
    """Convert a DOCX file to PDF using LibreOffice headless. Returns the PDF path."""
    output_dir = os.path.dirname(os.path.abspath(docx_path))
    result = subprocess.run(
        [
            "libreoffice", "--headless", "--convert-to", "pdf",
            "--outdir", output_dir,
            os.path.abspath(docx_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed (code {result.returncode}): {result.stderr}"
        )
    pdf_path = os.path.splitext(os.path.abspath(docx_path))[0] + ".pdf"
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF não encontrado após conversão: {pdf_path}")
    logger.info("PDF gerado: %s", pdf_path)
    return pdf_path
