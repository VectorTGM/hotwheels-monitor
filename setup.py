#!/usr/bin/env python3
"""
Quick setup wizard for Hotwheels Monitor.
Run this first to configure your Telegram bot.
"""

import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

def main():
    print("=" * 50)
    print("  Hotwheels Monitor - Setup Wizard")
    print("=" * 50)
    print()

    # Load existing config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        config = {}

    # Telegram setup
    print("STEP 1: Telegram Bot Setup")
    print("-" * 40)
    print("1. Open Telegram and search for @BotFather")
    print("2. Send /newbot and follow the instructions")
    print("3. Copy the bot token you receive")
    print()

    token = input("Paste your Telegram bot token (or press Enter to skip): ").strip()
    if token:
        config["telegram_bot_token"] = token

    print()
    print("4. Now search for your new bot on Telegram")
    print("5. Send any message to the bot (like /start)")
    print("6. Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates")
    print("   (Replace <YOUR_TOKEN> with your actual token)")
    print("7. Find 'chat' -> 'id' in the response")
    print()

    chat_id = input("Paste your Telegram chat ID (or press Enter to skip): ").strip()
    if chat_id:
        config["telegram_chat_id"] = chat_id

    # Interval
    print()
    print("STEP 2: Check Interval")
    print("-" * 40)
    interval = input("How often to check in minutes? [5]: ").strip()
    config["check_interval_minutes"] = int(interval) if interval else 5

    # Save
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print()
    print("=" * 50)
    print("  Setup complete!")
    print(f"  Config saved to: {CONFIG_PATH}")
    print()
    print("  To run the monitor:")
    print("    pip install -r requirements.txt")
    print("    python monitor.py")
    print("=" * 50)

if __name__ == "__main__":
    main()
