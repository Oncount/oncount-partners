"""Reset bot's `/` command list via Telegram setMyCommands.

Sequence:
1. deleteMyCommands (all scopes/locales) — clean Salebot legacy and ru-only entries
2. setMyCommands in DEFAULT scope (no language_code) — covers all users

Run: python scripts/setup_bot_commands.py
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
    {"command": "start",     "description": "🏠 Главное меню"},
    {"command": "transfer",  "description": "💰 Передать клиента"},
    {"command": "links",     "description": "🔗 Мои реферальные ссылки"},
    {"command": "stats",     "description": "📊 Моя статистика"},
    {"command": "products",  "description": "📦 Тарифы и сервисы"},
    {"command": "messages",  "description": "📨 Тексты рассылок"},
    {"command": "faq",       "description": "❓ Частые вопросы"},
]


def call(method: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main():
    # Wipe every scope/locale combo we know about
    print("Step 1: deleteMyCommands (default)")
    print(call("deleteMyCommands", {}))
    print("Step 1b: deleteMyCommands ru")
    print(call("deleteMyCommands", {"language_code": "ru"}))
    print("Step 1c: deleteMyCommands en")
    print(call("deleteMyCommands", {"language_code": "en"}))

    # Set new commands in default scope (visible to all users regardless of language)
    print("\nStep 2: setMyCommands DEFAULT scope, no language_code")
    print(call("setMyCommands", {"commands": COMMANDS}))

    # Verify
    print("\nStep 3: getMyCommands (default)")
    print(call("getMyCommands", {}))


if __name__ == "__main__":
    main()
