"""Optional Telegram notification via the official Telegram Bot API -- a
lightweight "check your email" nudge sent alongside each signal email
(CLAUDE.md section 6), not a replacement for it. Chosen over WhatsApp's
CallMeBot route (still documented in project history) because it's an
official API with instant setup and no per-recipient opt-in delay, and
it supports a real group chat, not just individuals.

Best-effort by design: a Telegram send failure is logged loudly to
stderr but never raises, so a Telegram/network hiccup can't turn a
real, successfully-sent email alert into a failed GitHub Actions run.

Configured via:
  TELEGRAM_BOT_TOKEN -- the token BotFather gives you for your bot
  TELEGRAM_CHAT_IDS  -- comma-separated chat ids to send to (one per
                        recipient, or a group's chat id -- see README)
Either unset/empty = feature disabled, not an error -- nothing sends,
nothing fails.
"""

import json
import os
import sys
import urllib.request

from .market_data_client import INSTRUMENTS

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def bot_token():
    # `or ""`, not the two-arg os.environ.get default: a GitHub Actions
    # workflow referencing a never-added secret sets the env var to an
    # empty string, not absent (CLAUDE.md section 12) -- this must
    # degrade to "feature disabled", not crash.
    return os.environ.get("TELEGRAM_BOT_TOKEN") or ""


def chat_ids():
    raw = os.environ.get("TELEGRAM_CHAT_IDS") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def format_telegram_message(signal):
    symbol = signal["symbol"]
    decimals = INSTRUMENTS[symbol]["price_decimals"]
    return (
        f"\U0001F4C8 [{symbol}] {signal['direction']} Signal - Entry Formed\n"
        f"Entry: {signal['entry']:.{decimals}f} | Stop: {signal['stop_loss']:.{decimals}f}\n"
        f"Full trade plan sent to your email."
    )


def send_telegram_notification(message):
    """Best-effort fan-out to every configured chat id. Never raises --
    a failure (bad token, network error, chat hasn't started the bot)
    is printed to stderr so it's visible in the run log, but doesn't
    fail the run -- the email alert, sent separately before this is
    called, is the real deliverable.
    """
    token = bot_token()
    if not token:
        return

    url = TELEGRAM_API_URL.format(token=token)
    for chat_id in chat_ids():
        payload = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as resp:
                resp.read()
        except Exception as exc:
            print(f"Telegram notification to chat {chat_id} failed: {exc}", file=sys.stderr)
