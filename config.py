import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "")
NOTIFY_IF_EMPTY = os.getenv("NOTIFY_IF_EMPTY", "false").lower() == "true"
SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "08:00")


def validate():
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not GMAIL_USER:
        missing.append("GMAIL_USER")
    if not GMAIL_APP_PASSWORD:
        missing.append("GMAIL_APP_PASSWORD")
    if not RECIPIENT_EMAIL:
        missing.append("RECIPIENT_EMAIL")
    if missing:
        raise ValueError(
            f"Variáveis de ambiente ausentes no .env: {', '.join(missing)}\n"
            "Copie .env.example para .env e preencha os valores."
        )
