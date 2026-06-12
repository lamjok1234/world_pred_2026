"""
Kicktipp Debug Bot — verbose version to diagnose scraping issues
Run this, then send /leaderboard and paste the terminal output here.
"""

import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
URL = "https://www.kicktipp.com/worldprediction2026/leaderboard"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.kicktipp.com/",
}

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_and_debug():
    print("\n" + "="*60)
    print("STEP 1: Sending HTTP request...")
    print(f"  URL: {URL}")

    r = requests.get(URL, headers=HEADERS, timeout=15)

    print(f"  Status code:     {r.status_code}")
    print(f"  Response length: {len(r.text)} chars")
    print(f"  Content-Type:    {r.headers.get('Content-Type','?')}")

    print("\nSTEP 2: Raw HTML (first 600 chars):")
    print("-"*40)
    print(r.text[:600])
    print("-"*40)

    print("\nSTEP 3: Parsing with BeautifulSoup...")
    soup = BeautifulSoup(r.text, "html.parser")

    tables = soup.find_all("table")
    print(f"  Tables found: {len(tables)}")

    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        print(f"\n  Table[{i}]: {len(rows)} rows")
        for j, row in enumerate(rows[:5]):
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            print(f"    Row[{j}]: {cells}")

    print("\nSTEP 4: Looking for match header pattern (e.g. 'MEX RSA 0-0')...")
    match_labels  = []
    match_results = []
    found_in_table = -1

    for i, table in enumerate(tables):
        rows = table.find_all("tr")
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            cols = []
            for cell in cells:
                m = re.match(r'^([A-Z]{2,4})\s+([A-Z]{2,4})\s+([\d]+-[\d]+|---)$', cell)
                if m:
                    cols.append(m)
            if cols:
                print(f"  ✅ Found match headers in Table[{i}]:")
                for m in cols:
                    label  = f"{m.group(1)} {m.group(2)}"
                    result = m.group(3)
                    match_labels.append(label)
                    match_results.append(result)
                    print(f"     {label} → {result}")
                found_in_table = i
                break
        if found_in_table >= 0:
            break

    if found_in_table < 0:
        print("  ❌ No match headers found in any table!")
        print("\nSTEP 5: All cell texts across all tables:")
        for i, table in enumerate(tables):
            print(f"\n  Table[{i}] all cells:")
            for row in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["th","td"])]
                if any(cells):
                    print(f"    {cells}")
        return [], [], []

    print(f"\nSTEP 5: Parsing player rows from Table[{found_in_table}]...")
    players = []
    table = tables[found_in_table]
    rows  = table.find_all("tr")
    num_matches = len(match_labels)

    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 4:
            continue
        pos = cells[0].replace(".", "").strip()
        if not pos.isdigit():
            continue
        name = cells[2].strip()
        if not name:
            continue

        preds = []
        for i in range(num_matches):
            col = 3 + i
            raw = cells[col] if col < len(cells) else ""
            preds.append(raw.strip() or "-")

        pts   = cells[-4].strip() if len(cells) >= 4 else "0"
        total = cells[-1].strip() if cells             else "0"

        player = {"pos": int(pos), "name": name, "preds": preds, "pts": pts or "0", "total": total or "0"}
        players.append(player)
        print(f"  Player: {name:15} preds={preds}  pts={pts}  total={total}")

    print(f"\n  Total players found: {len(players)}")
    print("="*60 + "\n")

    return match_labels, match_results, players


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Running debug fetch... check your terminal for full output.")
    try:
        match_labels, match_results, players = fetch_and_debug()
        if not match_labels:
            await update.message.reply_text(
                "❌ No match data found.\n\n"
                "Check terminal output and send it to Claude."
            )
        elif not players:
            await update.message.reply_text(
                f"⚠️ Found {len(match_labels)} matches but 0 players.\n\n"
                f"Matches: {match_labels}\n\nCheck terminal output."
            )
        else:
            summary = (
                f"✅ Scraping worked!\n\n"
                f"Matches: {len(match_labels)}\n"
                f"Players: {len(players)}\n\n"
                f"Sample — {players[0]['name']}: {players[0]['preds']}\n\n"
                f"Paste your terminal output to Claude to fix the bot."
            )
            await update.message.reply_text(summary)
    except Exception as e:
        await update.message.reply_text(f"❌ Exception: {e}")
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 *Debug Bot*\n\nSend /debug — it will fetch the Kicktipp page and print everything to the terminal.\n\nThen paste the terminal output to Claude.",
        parse_mode="Markdown"
    )


def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  Set TELEGRAM_BOT_TOKEN env var or paste your token into BOT_TOKEN.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("leaderboard", cmd_debug))  # both commands do debug
    print("🔍 Debug bot running. Send /debug in Telegram, then paste terminal output to Claude.")
    app.run_polling()


if __name__ == "__main__":
    main()
