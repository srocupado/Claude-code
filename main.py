#!/usr/bin/env python3
"""Monitor de Medidas Provisórias

Uso:
  python main.py                        # Busca MPs publicadas hoje
  python main.py --date 2026-04-10      # Busca MPs de uma data específica
  python main.py --schedule             # Executa todo dia no horário do .env (SCHEDULE_TIME)
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime

import schedule

import config
from fetcher import fetch_mps
from generator import generate_nota_tecnica
from docx_writer import write_nota_tecnica, convert_to_pdf
from mailer import send_email, send_empty_notification

os.makedirs("logs", exist_ok=True)
os.makedirs("output", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/mp_monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run(target_date: date):
    logger.info("=" * 60)
    logger.info("Iniciando busca de MPs em %s", target_date.strftime("%d/%m/%Y"))

    mps = fetch_mps(target_date)

    if not mps:
        logger.info("Nenhuma MP publicada em %s.", target_date.strftime("%d/%m/%Y"))
        if config.NOTIFY_IF_EMPTY:
            logger.info("Enviando notificação de ausência de MPs...")
            send_empty_notification(target_date)
        return

    logger.info("%d MP(s) encontrada(s). Gerando notas técnicas...", len(mps))

    attachment_files: list[str] = []
    processed_mps: list[dict] = []

    for mp in mps:
        label = f"MP nº {mp['numero']}/{mp['ano']}"
        logger.info("  → Gerando nota técnica para %s...", label)
        try:
            content = generate_nota_tecnica(mp)
            docx_path = write_nota_tecnica(mp, content)
            attachment_files.append(docx_path)
            pdf_path = convert_to_pdf(docx_path)
            if pdf_path:
                attachment_files.append(pdf_path)
            processed_mps.append(mp)
            logger.info("    ✓ Nota salva: %s", docx_path)
        except Exception:
            logger.exception("    ✗ Erro ao processar %s", label)

    if not attachment_files:
        logger.error("Nenhuma nota técnica pôde ser gerada. Encerrando sem envio.")
        return

    logger.info("Enviando %d arquivo(s) por e-mail para %s...", len(attachment_files), config.RECIPIENT_EMAIL)
    try:
        send_email(attachment_files, processed_mps)
        logger.info("E-mail enviado com sucesso.")
    except Exception:
        logger.exception("Falha ao enviar e-mail. As notas foram salvas em ./output/")

    logger.info("Concluído.")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor de Medidas Provisórias – gera Nota Técnica e envia por e-mail",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--date", "-d",
        metavar="YYYY-MM-DD",
        help="Data alvo para busca (padrão: hoje)",
        default=None,
    )
    parser.add_argument(
        "--schedule", "-s",
        action="store_true",
        help=f"Executa automaticamente todos os dias no horário definido em SCHEDULE_TIME (padrão: 08:00)",
    )
    args = parser.parse_args()

    try:
        config.validate()
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    if args.schedule:
        logger.info(
            "Modo agendado ativado. Execução diária às %s. Pressione Ctrl+C para encerrar.",
            config.SCHEDULE_TIME,
        )
        schedule.every().day.at(config.SCHEDULE_TIME).do(lambda: run(date.today()))
        # Run once immediately on startup
        run(date.today())
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        if args.date:
            try:
                target = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                logger.error("Formato de data inválido. Use YYYY-MM-DD (ex: 2026-05-01)")
                sys.exit(1)
        else:
            target = date.today()
        run(target)


if __name__ == "__main__":
    main()
