import os
import requests
from dotenv import load_dotenv

# zuerst prüfen, ob die globale .env existiert
if os.path.exists("/etc/aktienbriefing/.env"):
    load_dotenv("/etc/aktienbriefing/.env")
else:
    load_dotenv()  # Fallback für lokale Tests
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

text = "✅ Test von Aktien-Briefing: Telegram-Verbindung erfolgreich."
resp = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
    timeout=10,
)
print(resp.status_code, resp.text)
