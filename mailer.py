import os
import ssl
import smtplib
import logging
from datetime import date, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _build_body(mp_list: list[dict], target_date: date) -> str:
    today = target_date.strftime("%d/%m/%Y")
    count = len(mp_list)
    noun = "Medida Provisória" if count == 1 else "Medidas Provisórias"
    lines = [
        f"Foram identificadas {count} {noun} publicada(s) hoje ({today}):",
        "",
    ]
    for mp in mp_list:
        lines.append(f"• MP nº {mp['numero']}/{mp['ano']}")
        ementa = mp.get("ementa", "")
        if ementa:
            truncated = ementa[:250] + ("..." if len(ementa) > 250 else "")
            lines.append(f"  Ementa: {truncated}")
        url = mp.get("url_planalto", "")
        if url:
            lines.append(f"  Planalto: {url}")
        lines.append("")

    lines += [
        "A(s) nota(s) técnica(s) gerada(s) automaticamente está(ão) em anexo.",
        "",
        "--",
        "Monitor de Medidas Provisórias",
    ]
    return "\n".join(lines)


def _build_empty_body(target_date: date) -> str:
    return (
        f"Não foram identificadas Medidas Provisórias publicadas em "
        f"{target_date.strftime('%d/%m/%Y')}.\n\n"
        "--\nMonitor de Medidas Provisórias"
    )


def _attach_file(msg: MIMEMultipart, filepath: str):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        mime_subtype = "pdf"
    else:
        mime_subtype = "vnd.openxmlformats-officedocument.wordprocessingml.document"
    with open(filepath, "rb") as f:
        part = MIMEBase("application", mime_subtype)
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{os.path.basename(filepath)}"',
    )
    msg.attach(part)


def _send(msg: MIMEMultipart):
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=ctx)
        server.login(config.GMAIL_USER, config.GMAIL_APP_PASSWORD)
        server.sendmail(config.GMAIL_USER, config.RECIPIENT_EMAIL, msg.as_string())
    logger.info("E-mail enviado para %s", config.RECIPIENT_EMAIL)


def send_email(docx_files: list[str], mp_list: list[dict], target_date: date | None = None):
    if target_date is None:
        target_date = date.today()
    today = target_date.strftime("%d/%m/%Y")
    count = len(mp_list)
    subject = (
        f"[MP Monitor] {count} Medida(s) Provisória(s) publicada(s) em {today}"
    )

    msg = MIMEMultipart()
    msg["From"] = config.GMAIL_USER
    msg["To"] = config.RECIPIENT_EMAIL
    msg["Subject"] = subject

    msg.attach(MIMEText(_build_body(mp_list, target_date), "plain", "utf-8"))

    for filepath in docx_files:
        _attach_file(msg, filepath)

    _send(msg)


def send_empty_notification(target_date: date):
    subject = (
        f"[MP Monitor] Nenhuma MP publicada em {target_date.strftime('%d/%m/%Y')}"
    )
    msg = MIMEMultipart()
    msg["From"] = config.GMAIL_USER
    msg["To"] = config.RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(_build_empty_body(target_date), "plain", "utf-8"))
    _send(msg)
