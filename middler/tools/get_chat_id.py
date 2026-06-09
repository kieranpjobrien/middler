"""Discover your Telegram chat id(s) — the Phase-4 manual action helper.

After creating the bot with @BotFather and **sending it any message** (and adding
it to any group you want alerts in), run this. It calls ``getUpdates`` and prints
the chat ids it finds. Paste them into ``TELEGRAM_CHAT_IDS`` in ``.env``.
"""

from __future__ import annotations

import httpx

from middler.config import load_settings


def main() -> None:
    """Print the chat ids visible to the configured bot token."""
    token = load_settings().telegram_bot_token
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set. Create a bot via @BotFather, put the token in .env, then re-run.")
        return
    resp = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    data = resp.json()
    if not data.get("ok"):
        print(f"Telegram API error: {data}")
        return
    seen: dict[int, str] = {}
    for update in data.get("result", []):
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat", {})
        if "id" in chat:
            label = chat.get("title") or chat.get("username") or chat.get("first_name") or chat.get("type", "")
            seen[chat["id"]] = str(label)
    if not seen:
        print("No chats found. Send your bot a message (or add it to a group and post), then run this again.")
        return
    print("Found chats — add the id(s) to TELEGRAM_CHAT_IDS in .env:")
    for chat_id, label in seen.items():
        print(f"  {chat_id}   ({label})")


if __name__ == "__main__":
    main()
