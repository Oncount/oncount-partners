"""One-time: set bot's `/` command list via Telegram setMyCommands.

Run locally: python scripts/setup_bot_commands.py
Requires BOT_TOKEN in env (or in .env).
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, ".")
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8368308511:AAEBnyB59RNXTLG70yb8ijoOS3HXLE3QFGk"

COMMANDS = [
    {"command": "start",     "description": "Главное меню"},
    {"command": "transfer",  "description": "📍 Передать клиента"},
    {"command": "links",     "description": "🔗 Мои реферальные ссылки"},
    {"command": "stats",     "description": "📊 Моя статистика"},
    {"command": "products",  "description": "📦 Тарифы и сервисы"},
    {"command": "messages",  "description": "📨 Тексты рассылок"},
    {"command": "faq",       "description": "❓ Частые вопросы"},
]


def main():
    body = json.dumps({"commands": COMMANDS, "language_code": "ru"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands",
        data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req, timeout=20)
    print(r.read().decode())


if __name__ == "__main__":
    main()
