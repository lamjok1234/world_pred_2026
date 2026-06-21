"""
Kicktipp WorldPrediction2026 — Telegram Bot
/leaderboard — shows the prediction matrix exactly as on the website
/bonus       — shows the bonus questions as a clean text matrix
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def parse_header_cell(cell):
    m = re.match(r'^([A-Z]+)([\d]+-[\d]+|---)$', cell)
    if not m:
        return None, None
    teams, result = m.group(1), m.group(2)
    t1, t2 = teams[:3], teams[3:]
    if not t2:
        return None, None
    return f"{t1} {t2}", result


def split_pred(raw):
    raw = raw.strip()
    if not raw or raw == "---":
        return raw or "-", ""
    m = re.match(r'^(\d+)-(\d+)$', raw)
    if m:
        home, away_pts = m.group(1), m.group(2)
        if len(away_pts) > 1:
            return f"{home}-{away_pts[0]}", away_pts[1:]
        return f"{home}-{away_pts}", ""
    return raw, ""


def _truncate(text, width=20):
    """Truncate long strings cleanly so they don't break the table layout."""
    text = str(text)
    return (text[:width-2] + "..") if len(text) > width else text


# ---------------------------------------------------------------------------
# /leaderboard 
# ---------------------------------------------------------------------------

def fetch_matrix():
    r = requests.get(URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    match_labels, match_results, players = [], [], []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_row, num_matches = None, 0
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            labels, results = [], []
            for cell in cells:
                label, result = parse_header_cell(cell)
                if label:
                    labels.append(label)
                    results.append(result)
            if labels:
                match_labels, match_results = labels, results
                num_matches, header_row = len(labels), row
                break
        if not header_row:
            continue
        for row in rows:
            if row is header_row:
                continue
            cells = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            pos = cells[0].replace(".", "").strip()
            if not pos.isdigit():
                continue
            name = cells[2].strip()
            if not name:
                continue
            preds, pts_list = [], []
            for i in range(num_matches):
                raw = cells[3 + i] if 3 + i < len(cells) else ""
                pred, pts = split_pred(raw)
                preds.append(pred)
                pts_list.append(pts)
            players.append({
                "pos": int(pos), "name": name,
                "preds": preds, "pts": pts_list,
                "total": cells[-1].strip() or "0",
            })
        if players:
            break
    return match_labels, match_results, players


def build_table(match_labels, match_results, players):
    if not match_labels or not players:
        return "⚠️ No data found. Try again later."
    name_w, col_w = 7, 3
    home = [l.split()[0][:3] for l in match_labels]
    away = [l.split()[1][:3] if len(l.split()) > 1 else "   " for l in match_labels]

    def row(n, cols, t):
        return n[:name_w].ljust(name_w) + " " + " ".join(c.center(col_w) for c in cols) + f" {t:>2}"

    lines = ["🏆 *WorldPrediction2026*\n", "```",
             row("", home, " "), row("", away, "T"),
             row("Score", match_results, " "), "-" * len(row("", home, " "))]
    for p in players:
        preds = [p["preds"][i] if i < len(p["preds"]) else "-" for i in range(len(match_labels))]
        lines.append(row(p["name"], preds, p["total"]))
    lines += ["```", "_\\- = no prediction yet · T = total_"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /bonus  (NEW: Pure Text-Based Matrix)
# ---------------------------------------------------------------------------

def fetch_bonus_matrix():
    r = requests.get(URL + "?bonus=true", headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    
    table = soup.find("table", {"id": "ranking"})
    if not table:
        return [], [], []

    header_row = table.find("thead").find("tr")
    if not header_row:
        return [], [], []

    # 1. Extract exact short labels (WC, Tor, Gr A, SF...)
    labels = []
    for th in header_row.find_all("th", class_="ereignis"):
        kurz = th.find("div", class_="kurzfrage")
        if kurz and "display: none" not in (kurz.get("style", "")):
            labels.append(kurz.get_text(strip=True))

    # 2. Extract players
    players = []
    for tr in table.find("tbody").find_all("tr", class_="teilnehmer"):
        pos_el = tr.find("td", class_="position")
        name_el = tr.find("div", class_="mg_name")
        if not pos_el or not name_el:
            continue
            
        pos = pos_el.get_text(strip=True).replace(".", "")
        name = name_el.get_text(strip=True)
        if not pos.isdigit():
            continue

        answers = []
        for th in header_row.find_all("th", class_="ereignis"):
            kurz = th.find("div", class_="kurzfrage")
            if kurz and "display: none" in (kurz.get("style", "")):
                continue
                
            idx = th.get("data-index")
            cell = tr.find("td", attrs={"data-index": idx})
            
            if cell and cell.get("data-antwort") != "":
                # Instantly remove the score tag so it doesn't mix with the text
                sub_p = cell.find("sub", class_="p")
                if sub_p:
                    sub_p.decompose()
                
                ans_text = cell.get_text(strip=True)
                answers.append(ans_text)
            else:
                answers.append("-")

        # Extract Total Points
        total_el = tr.find("td", class_="gesamtpunkte")
        total = total_el.get_text(strip=True) if total_el else "0"

        players.append({
            "pos": int(pos),
            "name": name,
            "answers": answers,
            "total": total
        })

    # 3. Extract correct answers from headerboxes
    correct = []
    for th in header_row.find_all("th", class_="ereignis"):
        kurz = th.find("div", class_="kurzfrage")
        if kurz and "display: none" not in (kurz.get("style", "")):
            hbox = th.find("div", class_="headerbox")
            correct.append(hbox.get_text(strip=True) if hbox else "---")

    return labels, correct, players


def build_bonus_text(labels, correct, players):
    """Builds a fixed-width, highly readable matrix table for Telegram."""
    if not labels or not players:
        return "⚠️ No bonus data found. Try again later."

    name_w = 12
    col_w = 5

    def format_row(name, cols, total):
        # Format name column
        row_str = f"{name:<{name_w}} "
        # Format each answer column (center aligned)
        for c in cols:
            row_str += f"{c:^{col_w}}"
        # Format total column
        row_str += f" {total:>{3}}"
        return row_str

    # Separator line
    sep_len = name_w + 1 + (col_w * len(labels)) + 4
    separator = "─" * sep_len

    lines = [
        "🏆 *WorldPrediction2026 — Bonus Questions*\n",
        "```",
        # Correct Answers Row
        format_row("✅ Answer", correct, ""),
        # Header Labels Row
        format_row("Question", labels, "T"),
        separator
    ]

    # Player Rows
    for p in players:
        # Clean up answers to max 4 characters so they fit nicely
        display_answers = [ans[:4] if ans != "-" else "-" for ans in p["answers"]]
        lines.append(format_row(f"{p['pos']}. {p['name']}", display_answers, p["total"]))

    lines.append("```")
    lines.append("_T = Total Points_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *WorldPrediction2026 Bot*\n\n"
        "Use /leaderboard to see the prediction matrix.\n"
        "Use /bonus to see bonus questions as a text matrix.\n\n"
        "Type /help for all commands.",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "/leaderboard — Full prediction matrix (text)\n\n"
        "/bonus — Bonus questions matrix (text)\n\n"
        "/start — Welcome message\n\n"
        "/help — This message",
        parse_mode="Markdown",
    )


async def cmd_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching…")
    try:
        ml, mr, pl = fetch_matrix()
        text = build_table(ml, mr, pl)
    except Exception as e:
        logger.error(e)
        text = f"❌ Error: {e}"
    for chunk in [text[i:i + 4096] for i in range(0, len(text), 4096)]:
        await update.message.reply_text(chunk, parse_mode="Markdown")


async def cmd_bonus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Fetching bonus matrix…")
    try:
        labels, correct, players = fetch_bonus_matrix()
        text = build_bonus_text(labels, correct, players)
        for chunk in [text[i:i + 4096] for i in range(0, len(text), 4096)]:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text(f"❌ Error: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️  Set TELEGRAM_BOT_TOKEN env var or paste your token into BOT_TOKEN.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("bonus",       cmd_bonus))
    logger.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
